//go:build windows

package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/kardianos/service"
	"golang.org/x/sys/windows/registry"
)

// myrmm-tray.exe compresso (generato da release.sh da ./tray): la tray è un programma nativo, senza script.
//
//go:embed tray_exe.gz
var trayExeGz []byte

func trayOn(cfg *Config) bool { return !strings.EqualFold(cfg.TrayMode, "off") }

// trayApply: la console ha scelto «on» o «off» per questo device: si ricorda la scelta (file tray.mode, prevale su config.json)
// e si installa o si toglie l'icona subito, senza riavviare il servizio.
func trayApply(cfg *Config, mode string, log service.Logger) {
	m := strings.ToLower(strings.TrimSpace(mode))
	if m != "on" && m != "off" {
		return
	}
	cur := "on"
	if !trayOn(cfg) {
		cur = "off"
	}
	if m == cur {
		return
	}
	if err := os.WriteFile(filepath.Join(dataDir(), "tray.mode"), []byte(m), 0o644); err != nil {
		_ = log.Warningf("tray: %v", err)
	}
	cfg.TrayMode = m
	_ = log.Infof("tray: %s su richiesta della console", map[string]string{"on": "attivata", "off": "disattivata"}[m])
	go trayStart(cfg, log)
}

// trayStart: avvia l'API locale e installa (o aggiorna) l'icona nella systray come attività pianificata
// «myrmm-tray», che parte all'accesso di ogni utente e gira con i suoi diritti, non con quelli del servizio.
func trayStart(cfg *Config, log service.Logger) {
	host, _ := os.Hostname()
	chatMu.Lock()
	chatMeta.Host, chatMeta.Site = host, cfg.Site
	chatMu.Unlock()
	dir := dataDir()
	hashFile := filepath.Join(dir, "tray.hash")
	oldScript := filepath.Join(dir, "tray.ps1") // versioni fino alla 1.64: tray in PowerShell, non più usata
	exePath := filepath.Join(dir, "myrmm-tray.exe")
	const killAll = `Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {$_.CommandLine -like '*myrmm*tray.ps1*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}; Get-Process -Name 'myrmm-tray' -ErrorAction SilentlyContinue | Stop-Process -Force`
	if !trayOn(cfg) {
		if _, err := os.Stat(hashFile); err == nil { // era installata: si toglie
			_ = psDetached(`Stop-ScheduledTask -TaskName 'myrmm-tray'; Unregister-ScheduledTask -TaskName 'myrmm-tray' -Confirm:$false; ` + killAll)
			_ = os.Remove(hashFile)
			_ = os.Remove(oldScript)
			_ = os.Remove(exePath)
		}
		trayRunKey(exePath, false)
		return
	}
	chatServe(cfg)
	if len(trayExeGz) < 1024 {
		_ = log.Warningf("tray: eseguibile non incorporato in questo agent")
		return
	}
	sum := sha256.Sum256(trayExeGz)
	h := "go:" + hex.EncodeToString(sum[:])
	if b, err := os.ReadFile(hashFile); err == nil && string(b) == h {
		if _, e2 := os.Stat(exePath); e2 == nil {
			trayRunKey(exePath, true)
			return // già installata e aggiornata
		}
	}
	zr, err := gzip.NewReader(bytes.NewReader(trayExeGz))
	if err != nil {
		_ = log.Warningf("tray: %v", err)
		return
	}
	raw, err := io.ReadAll(io.LimitReader(zr, 64<<20))
	if err != nil {
		_ = log.Warningf("tray: %v", err)
		return
	}
	_ = psDetached(killAll) // se è in esecuzione il file è bloccato (e la vecchia tray PowerShell va tolta)
	tmp := exePath + ".new"
	if err := os.WriteFile(tmp, raw, 0o755); err != nil {
		_ = log.Warningf("tray: %v", err)
		return
	}
	_ = os.Remove(exePath)
	if err := os.Rename(tmp, exePath); err != nil {
		_ = log.Warningf("tray: %v", err)
		return
	}
	_ = os.Remove(oldScript)
	reg := `$ErrorActionPreference='Stop'
$a=New-ScheduledTaskAction -Execute ` + psq(exePath) + `
$t=New-ScheduledTaskTrigger -AtLogOn
$p=New-ScheduledTaskPrincipal -GroupId 'S-1-5-32-545' -RunLevel Limited
$c=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'myrmm-tray' -Action $a -Trigger $t -Principal $p -Settings $c -Force | Out-Null
Start-ScheduledTask -TaskName 'myrmm-tray'`
	if err := psDetached(reg); err != nil {
		_ = log.Warningf("tray: registrazione attività fallita: %v", err)
		return
	}
	trayRunKey(exePath, true)
	_ = os.WriteFile(hashFile, []byte(h), 0o644)
	_ = log.Infof("tray: icona installata (attività pianificata myrmm-tray)")
}

// Avvio all'accesso, seconda via oltre all'attività pianificata: la chiave Run di sistema parte per ogni utente che accede
// (anche dove Utilità di pianificazione non lancia l'attività). Il blocco per sessione della tray evita le doppie copie.
const runKeyPath = `SOFTWARE\Microsoft\Windows\CurrentVersion\Run`

func trayRunKey(exe string, on bool) {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, runKeyPath, registry.SET_VALUE)
	if err != nil {
		return
	}
	defer k.Close()
	if on {
		_ = k.SetStringValue("myrmm-tray", `"`+exe+`"`)
	} else {
		_ = k.DeleteValue("myrmm-tray")
	}
}

func psq(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

func psDetached(script string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodePowerShell(script))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}
