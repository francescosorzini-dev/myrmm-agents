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
)

//go:embed tray.ps1
var trayScript string

// myrmm-tray.exe compresso (generato da release.sh da ./tray): l'alternativa nativa alla tray PowerShell.
//
//go:embed tray_exe.gz
var trayExeGz []byte

func trayGo(cfg *Config) bool { return strings.EqualFold(cfg.TrayImpl, "go") && len(trayExeGz) > 1024 }

func trayOn(cfg *Config) bool { return !strings.EqualFold(cfg.TrayMode, "off") }

// trayApply: la console ha scelto «on» o «off» per questo device: si ricorda la scelta (file tray.mode, prevale su config.json)
// e si installa o si toglie l'icona subito, senza riavviare il servizio.
func trayApply(cfg *Config, mode, impl string, log service.Logger) {
	if im := strings.ToLower(strings.TrimSpace(impl)); (im == "go" || im == "ps") && !strings.EqualFold(im, cfg.TrayImpl) && !(im == "ps" && cfg.TrayImpl == "") {
		if err := os.WriteFile(filepath.Join(dataDir(), "tray.impl"), []byte(im), 0o644); err != nil {
			_ = log.Warningf("tray: %v", err)
		}
		cfg.TrayImpl = im
		_ = log.Infof("tray: programma %q su richiesta della console", im)
		if trayOn(cfg) {
			go trayStart(cfg, log)
		}
	}
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
	exePath := filepath.Join(dir, "myrmm-tray.exe")
	const killAll = `Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {$_.CommandLine -like '*myrmm*tray.ps1*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}; Get-Process -Name 'myrmm-tray' -ErrorAction SilentlyContinue | Stop-Process -Force`
	if !trayOn(cfg) {
		if _, err := os.Stat(hashFile); err == nil { // era installata: si toglie
			_ = psDetached(`Stop-ScheduledTask -TaskName 'myrmm-tray'; Unregister-ScheduledTask -TaskName 'myrmm-tray' -Confirm:$false; ` + killAll)
			_ = os.Remove(hashFile)
			_ = os.Remove(script)
			_ = os.Remove(exePath)
		}
		return
	}
	chatServe(cfg)
	useGo := trayGo(cfg)
	var h string
	if useGo {
		sum := sha256.Sum256(trayExeGz)
		h = "go:" + hex.EncodeToString(sum[:])
	} else {
		sum := sha256.Sum256([]byte(trayScript + "|v2"))
		h = hex.EncodeToString(sum[:])
	}
	if b, err := os.ReadFile(hashFile); err == nil && string(b) == h {
		have := script
		if useGo {
			have = exePath
		}
		if _, e2 := os.Stat(have); e2 == nil {
			return // già installata e aggiornata
		}
	}
	var action string // blocco PowerShell che definisce $exe e $arg dell'attività
	if useGo {
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
		// se la tray è in esecuzione il file è bloccato: prima si ferma
		_ = psDetached(killAll)
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
		_ = os.Remove(script)
		action = `$exe=` + psq(exePath) + `; $arg=$null`
	} else {
		// BOM UTF-8: PowerShell 5 legge correttamente gli accenti
		if err := os.WriteFile(script, append([]byte{0xEF, 0xBB, 0xBF}, []byte(trayScript)...), 0o644); err != nil {
			_ = log.Warningf("tray: %v", err)
			return
		}
		_ = os.Remove(exePath)
		action = `$s=` + psq(script) + `
$arg='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$s+'"'
if([Environment]::OSVersion.Version.Build -ge 17763){ $exe='conhost.exe'; $arg='--headless powershell.exe '+$arg } else { $exe='powershell.exe' }`
	}
	reg := `$ErrorActionPreference='Stop'
` + action + `
if($arg){ $a=New-ScheduledTaskAction -Execute $exe -Argument $arg } else { $a=New-ScheduledTaskAction -Execute $exe }
$t=New-ScheduledTaskTrigger -AtLogOn
$p=New-ScheduledTaskPrincipal -GroupId 'S-1-5-32-545' -RunLevel Limited
$c=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
` + killAll + `
Register-ScheduledTask -TaskName 'myrmm-tray' -Action $a -Trigger $t -Principal $p -Settings $c -Force | Out-Null
Start-ScheduledTask -TaskName 'myrmm-tray'`
	if err := psDetached(reg); err != nil {
		_ = log.Warningf("tray: registrazione attività fallita: %v", err)
		return
	}
	_ = os.WriteFile(hashFile, []byte(h), 0o644)
	_ = log.Infof("tray: icona installata (attività pianificata myrmm-tray, %s)", map[bool]string{true: "exe in Go", false: "PowerShell"}[useGo])
}

func psq(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

func psDetached(script string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodePowerShell(script))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}
