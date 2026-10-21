//go:build windows

package main

import (
	"context"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

// Raccolta specifica di Windows: servizio, attività pianificata dell'icona, processi, criteri di PowerShell/AV, registro eventi.
const diagPS = `
$ErrorActionPreference='SilentlyContinue'
function H($t){ "` + "`n" + `--- $t ---" }
H 'Windows'
$os=Get-CimInstance Win32_OperatingSystem; "$($os.Caption) $($os.Version) build $($os.BuildNumber) $($os.OSArchitecture)"
"avvio: $($os.LastBootUpTime)  |  ora locale: $(Get-Date -Format o)  |  fuso: $((Get-TimeZone).Id)"
H 'PowerShell e criteri'
"versione $($PSVersionTable.PSVersion)  |  LanguageMode: $($ExecutionContext.SessionState.LanguageMode)"
Get-ExecutionPolicy -List | Format-Table -AutoSize | Out-String -Width 200
H 'Servizio myrmm-agent'
Get-CimInstance Win32_Service -Filter "Name='myrmm-agent'" | Format-List Name,State,StartMode,StartName,PathName,ProcessId,ExitCode | Out-String -Width 200
H 'Tray (dalla 1.67 e un sottocomando dell agent, avviato dal servizio in ogni sessione)'
$p=Get-CimInstance Win32_Process -Filter "Name='myrmm-agent.exe'" | Where-Object { $_.CommandLine -match ' tray$' }
if($p){ $p | ForEach-Object { $o=Invoke-CimMethod -InputObject $_ -MethodName GetOwner; "pid $($_.ProcessId)  sessione $($_.SessionId)  utente $($o.Domain)\$($o.User)" } } else { 'nessun processo tray in esecuzione' }
H 'Resti delle versioni precedenti (devono mancare)'
"attivita pianificata myrmm-tray: $([bool](Get-ScheduledTask -TaskName 'myrmm-tray' -ErrorAction SilentlyContinue))"
"chiave Run: $((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue).'myrmm-tray')"
"myrmm-tray.exe nella cartella dati: $(Test-Path (Join-Path $env:ProgramData 'myrmm\\myrmm-tray.exe'))"
H 'Sessioni (quser)'
quser 2>&1 | Out-String
H 'Windows Forms disponibile'
try { Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop; 'ok' } catch { "NO: $($_.Exception.Message)" }
H 'Antivirus'
Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select-Object displayName,productState | Format-Table -AutoSize | Out-String
Get-MpComputerStatus | Select-Object AMServiceEnabled,RealTimeProtectionEnabled,AntivirusSignatureAge | Format-List | Out-String
H 'AppLocker / criteri di esecuzione software'
$a=Get-AppLockerPolicy -Effective -ErrorAction SilentlyContinue; if($a -and $a.RuleCollections.Count){ "AppLocker: $($a.RuleCollections.Count) raccolte di regole attive" } else { 'AppLocker: nessuna regola' }
H 'Permessi cartella dati'
icacls "$env:ProgramData\myrmm" 2>&1 | Out-String
H 'Proxy di sistema'
netsh winhttp show proxy 2>&1 | Out-String
H 'Sincronizzazione orologio'
w32tm /query /status 2>&1 | Select-Object -First 8 | Out-String
H 'Registro eventi: sorgente myrmm-agent (ultimi 30)'
Get-WinEvent -FilterHashtable @{LogName='Application';ProviderName='myrmm-agent'} -MaxEvents 30 | ForEach-Object { "$($_.TimeCreated.ToString('s')) [$($_.LevelDisplayName)] $($_.Message -replace '\s+',' ')" }
H 'Spazio su disco'
Get-PSDrive -PSProvider FileSystem | Select-Object Name,@{n='libero_GB';e={[math]::Round($_.Free/1GB,1)}} | Format-Table -AutoSize | Out-String
`

func platDiag() string {
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", encodePowerShell(diagPS))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.CombinedOutput()
	s := strings.TrimSpace(string(out))
	if ctx.Err() != nil {
		s += "\n[timeout: raccolta Windows interrotta dopo 90 s]"
	} else if err != nil && s == "" {
		s = "errore PowerShell: " + err.Error()
	}
	return s
}
