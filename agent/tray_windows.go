//go:build windows

package main

import (
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/kardianos/service"
)

//go:embed tray.ps1
var trayScript string

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
	script := filepath.Join(dir, "tray.ps1")
	if !trayOn(cfg) {
		if _, err := os.Stat(hashFile); err == nil { // era installata: si toglie
			_ = psDetached(`Stop-ScheduledTask -TaskName 'myrmm-tray'; Unregister-ScheduledTask -TaskName 'myrmm-tray' -Confirm:$false; Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {$_.CommandLine -like '*myrmm*tray.ps1*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}`)
			_ = os.Remove(hashFile)
			_ = os.Remove(script)
		}
		return
	}
	chatServe(cfg)
	sum := sha256.Sum256([]byte(trayScript + "|v2"))
	h := hex.EncodeToString(sum[:])
	if b, err := os.ReadFile(hashFile); err == nil && string(b) == h {
		if _, e2 := os.Stat(script); e2 == nil {
			return // già installata e aggiornata
		}
	}
	// BOM UTF-8: PowerShell 5 legge correttamente gli accenti
	if err := os.WriteFile(script, append([]byte{0xEF, 0xBB, 0xBF}, []byte(trayScript)...), 0o644); err != nil {
		_ = log.Warningf("tray: %v", err)
		return
	}
	reg := `$ErrorActionPreference='Stop'
$s=` + psq(script) + `
$arg='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$s+'"'
if([Environment]::OSVersion.Version.Build -ge 17763){ $exe='conhost.exe'; $arg='--headless powershell.exe '+$arg } else { $exe='powershell.exe' }
$a=New-ScheduledTaskAction -Execute $exe -Argument $arg
$t=New-ScheduledTaskTrigger -AtLogOn
$p=New-ScheduledTaskPrincipal -GroupId 'S-1-5-32-545' -RunLevel Limited
$c=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {$_.CommandLine -like '*myrmm*tray.ps1*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}
Register-ScheduledTask -TaskName 'myrmm-tray' -Action $a -Trigger $t -Principal $p -Settings $c -Force | Out-Null
Start-ScheduledTask -TaskName 'myrmm-tray'`
	if err := psDetached(reg); err != nil {
		_ = log.Warningf("tray: registrazione attività fallita: %v", err)
		return
	}
	_ = os.WriteFile(hashFile, []byte(h), 0o644)
	_ = log.Infof("tray: icona installata (attività pianificata myrmm-tray)")
}

func psq(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

func psDetached(script string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodePowerShell(script))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}
