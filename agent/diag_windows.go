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
H 'Attivita pianificata myrmm-tray (icona e chat)'
$t=Get-ScheduledTask -TaskName 'myrmm-tray'
if($t){ $t | Format-List TaskName,State | Out-String; $i=$t|Get-ScheduledTaskInfo; "ultima esecuzione: $($i.LastRunTime)  esito: 0x{0:X}  prossima: $($i.NextRunTime)" -f $i.LastTaskResult
  "azione: $($t.Actions.Execute) $($t.Actions.Arguments)"; "principal: $($t.Principal.GroupId)$($t.Principal.UserId) livello $($t.Principal.RunLevel)"; "trigger: $(($t.Triggers|%{$_.CimClass.CimClassName}) -join ', ')" } else { 'ATTIVITA NON TROVATA: l''agent non l''ha registrata (tray_mode=off, errore alla registrazione, o agent non aggiornato)' }
H 'Processi icona (myrmm-tray.exe)'
$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'myrmm-tray.exe' -or $_.CommandLine -like '*tray.ps1*' }
if($p){ $p | ForEach-Object { $o=Invoke-CimMethod -InputObject $_ -MethodName GetOwner; "pid $($_.ProcessId)  sessione $($_.SessionId)  utente $($o.Domain)\$($o.User)" } } else { 'nessun processo myrmm-tray in esecuzione (nessun utente collegato dopo la registrazione, o l''icona e'' terminata)' }
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
H 'Registro Utilita di pianificazione per myrmm-tray (ultimi 15)'
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational'} -MaxEvents 400 | Where-Object { $_.Message -like '*myrmm-tray*' } | Select-Object -First 15 | ForEach-Object { "$($_.TimeCreated.ToString('s')) id $($_.Id) $($_.Message -replace '\s+',' ')" }
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
