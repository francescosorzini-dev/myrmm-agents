//go:build windows

package main

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf16"
)

func dataDir() string {
	if pd := os.Getenv("ProgramData"); pd != "" {
		return filepath.Join(pd, "myrmm")
	}
	exe, _ := os.Executable()
	return filepath.Dir(exe)
}

func platTag() string { return "windows/" + goArch() }

// invScript raccoglie l'inventario via CIM. Eseguito dall'agent come PowerShell:
// zero dipendenze Go aggiuntive, dati precisi (OS, RAM, dischi, seriale, IP).
const invScript = `
$ErrorActionPreference='SilentlyContinue'
$os=Get-CimInstance Win32_OperatingSystem
$cs=Get-CimInstance Win32_ComputerSystem
$bios=Get-CimInstance Win32_BIOS
$disks=Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
  Select-Object DeviceID,@{n='size_gb';e={[math]::Round($_.Size/1GB,1)}},@{n='free_gb';e={[math]::Round($_.FreeSpace/1GB,1)}}
$ips=(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True").IPAddress |
  Where-Object {$_ -match '^\d+\.'}
$cpuPct=[math]::Round((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average,0)
$ramPct=if($os.TotalVisibleMemorySize){[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize*100,0)}else{0}
[pscustomobject]@{
  hostname=$env:COMPUTERNAME; os=$os.Caption; os_version=$os.Version; os_build=$os.BuildNumber
  ram_gb=[math]::Round($cs.TotalPhysicalMemory/1GB,1); cpu=$cs.NumberOfLogicalProcessors
  cpu_pct=$cpuPct; ram_pct=$ramPct
  manufacturer=$cs.Manufacturer; model=$cs.Model; serial=$bios.SerialNumber
  last_boot=$os.LastBootUpTime.ToString('o'); logged_user=$cs.UserName
  disks=@($disks); ips=@($ips)
} | ConvertTo-Json -Compress -Depth 4
`

// fullInvScript raccoglie l'inventario dettagliato. Pesante: va eseguito a
// intervallo lungo (full_inventory_hour), NON a ogni heartbeat.
// NB: il software è letto dal registro Uninstall (NON Win32_Product, che è
// lento e forza una riconfigurazione MSI di ogni pacchetto).
const fullInvScript = `
$ErrorActionPreference='SilentlyContinue'
$os=Get-CimInstance Win32_OperatingSystem
$cs=Get-CimInstance Win32_ComputerSystem
$bios=Get-CimInstance Win32_BIOS
$bb=Get-CimInstance Win32_BaseBoard
$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1
$gpu=@(Get-CimInstance Win32_VideoController | Select-Object @{n='name';e={$_.Name}},@{n='driver';e={$_.DriverVersion}})
$mem=@(Get-CimInstance Win32_PhysicalMemory | Select-Object @{n='slot';e={$_.DeviceLocator}},@{n='cap_gb';e={[math]::Round($_.Capacity/1GB,1)}},@{n='speed';e={$_.Speed}},@{n='part';e={$_.PartNumber.Trim()}})
$pdisk=@(Get-CimInstance Win32_DiskDrive | Select-Object @{n='model';e={$_.Model}},@{n='size_gb';e={[math]::Round($_.Size/1GB,1)}},@{n='bus';e={$_.InterfaceType}},@{n='serial';e={$_.SerialNumber.Trim()}})
$ldisk=@(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object @{n='id';e={$_.DeviceID}},@{n='size_gb';e={[math]::Round($_.Size/1GB,1)}},@{n='free_gb';e={[math]::Round($_.FreeSpace/1GB,1)}},@{n='fs';e={$_.FileSystem}})
$net=@(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" | Select-Object @{n='desc';e={$_.Description}},@{n='mac';e={$_.MACAddress}},@{n='ip';e={@($_.IPAddress)}},@{n='gw';e={@($_.DefaultIPGateway)}},@{n='dns';e={@($_.DNSServerSearchOrder)}},@{n='dhcp';e={$_.DHCPEnabled}})
$paths='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
$sw=@(Get-ItemProperty $paths | Where-Object {$_.DisplayName} |
  Select-Object @{n='name';e={$_.DisplayName}},@{n='version';e={$_.DisplayVersion}},@{n='publisher';e={$_.Publisher}},@{n='install_date';e={$_.InstallDate}} |
  Sort-Object name -Unique)
$hotfix=@(Get-HotFix | Select-Object @{n='kb';e={$_.HotFixID}},@{n='type';e={$_.Description}},@{n='installed';e={if($_.InstalledOn){$_.InstalledOn.ToString('yyyy-MM-dd')}}})
$svc=@(Get-CimInstance Win32_Service | Where-Object {$_.StartMode -eq 'Auto'} |
  Select-Object @{n='name';e={$_.Name}},@{n='display';e={$_.DisplayName}},@{n='state';e={$_.State}})
$users=@(Get-LocalUser | Select-Object Name,@{n='enabled';e={$_.Enabled}},@{n='last_logon';e={if($_.LastLogon){$_.LastLogon.ToString('o')}}})
$admins=@(Get-LocalGroupMember -Group 'Administrators' | Select-Object @{n='member';e={$_.Name}},@{n='type';e={$_.ObjectClass}})
[pscustomobject]@{
  system=[pscustomobject]@{
    hostname=$env:COMPUTERNAME; os=$os.Caption; os_version=$os.Version; os_build=$os.BuildNumber
    os_arch=$os.OSArchitecture; install_date=$os.InstallDate.ToString('o'); last_boot=$os.LastBootUpTime.ToString('o')
    domain=$cs.Domain; part_of_domain=$cs.PartOfDomain; logged_user=$cs.UserName
  }
  hardware=[pscustomobject]@{
    manufacturer=$cs.Manufacturer; model=$cs.Model; serial=$bios.SerialNumber
    bios_version=($bios.SMBIOSBIOSVersion); bios_date=$bios.ReleaseDate.ToString('yyyy-MM-dd')
    baseboard=($bb.Manufacturer+' '+$bb.Product)
    cpu=$cpu.Name; cpu_cores=$cpu.NumberOfCores; cpu_threads=$cpu.NumberOfLogicalProcessors
    ram_gb=[math]::Round($cs.TotalPhysicalMemory/1GB,1); ram_modules=$mem; gpu=$gpu
  }
  disks_physical=$pdisk; disks_logical=$ldisk; network=$net
  software=$sw; hotfix=$hotfix; services_auto=$svc; local_users=$users; local_admins=$admins
  collected_at=(Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json -Compress -Depth 6
`

// secScript raccoglie le prove di sicurezza (valori grezzi, interpretati da normalizeWinSecurity). Ogni sezione è indipendente:
// se una non è disponibile (per esempio SecurityCenter2 sui server) la chiave resta assente e il server la mostra come «non rilevato».
const secScript = `
$ErrorActionPreference='SilentlyContinue'
$r=[ordered]@{}
try {
  $av=@(Get-CimInstance -Namespace 'root/SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop | Select-Object @{n='name';e={$_.displayName}},@{n='state';e={[int]$_.productState}})
  $r.av=$av
} catch { $r.av=@() }
try { $d=Get-MpComputerStatus -ErrorAction Stop
  $r.defender=[pscustomobject]@{rtp=[bool]$d.RealTimeProtectionEnabled; enabled=[bool]$d.AntivirusEnabled; sig_age_days=[int]$d.AntivirusSignatureAge}
} catch {}
try { $bl=@(Get-BitLockerVolume -ErrorAction Stop | Where-Object {$_.VolumeType -in 'OperatingSystem','Data'} | Select-Object @{n='mount';e={$_.MountPoint}},@{n='status';e={[string]$_.ProtectionStatus}})
  $r.bitlocker=$bl } catch {}
try { $fw=@(Get-NetFirewallProfile -ErrorAction Stop | Select-Object @{n='name';e={[string]$_.Name}},@{n='enabled';e={[bool]$_.Enabled}})
  $r.firewall=$fw } catch {}
try { $t=Get-Tpm -ErrorAction Stop; $r.tpm=[pscustomobject]@{present=[bool]$t.TpmPresent; ready=[bool]$t.TpmReady} } catch {}
try {
  $b=$null
  $wb=Get-WBSummary -ErrorAction Stop
  if($wb -and $wb.LastSuccessfulBackupTime -and $wb.LastSuccessfulBackupTime.Year -gt 2000){ $b=[pscustomobject]@{product='Windows Server Backup'; last_success=$wb.LastSuccessfulBackupTime.ToUniversalTime().ToString('o')} }
  if(-not $b){
    $ev=Get-WinEvent -FilterHashtable @{LogName='Veeam Agent'; Id=190} -MaxEvents 1 -ErrorAction Stop
    if($ev){ $b=[pscustomobject]@{product='Veeam Agent'; last_success=$ev.TimeCreated.ToUniversalTime().ToString('o')} }
  }
  if($b){ $r.backup=$b }
} catch {}
[pscustomobject]$r | ConvertTo-Json -Compress -Depth 5
`

// encodePowerShell converte lo script in -EncodedCommand (UTF-16LE base64),
// evitando ogni problema di quoting/escape nel passaggio argomenti.
func encodePowerShell(script string) string {
	u := utf16.Encode([]rune(script))
	buf := make([]byte, len(u)*2)
	for i, r := range u {
		binary.LittleEndian.PutUint16(buf[i*2:], r)
	}
	return base64.StdEncoding.EncodeToString(buf)
}

// psPrefix precede ogni script: niente barre di avanzamento e output in UTF-8 senza BOM (altrimenti le lettere accentate
// arrivano nella tabella codici OEM del computer, es. 850, e il server le vede sbagliate).
const psPrefix = "$ProgressPreference='SilentlyContinue'; try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }; "

// platCommand prepara il comando PowerShell per uno script.
// -OutputFormat Text evita che stderr arrivi come CLIXML ("#< CLIXML ...");
// $ProgressPreference silenzia le barre di avanzamento (Invoke-WebRequest, moduli) che altrimenti finiscono in stderr.
func platCommand(ctx context.Context, script string) (*exec.Cmd, func()) {
	cmd := exec.CommandContext(ctx, "powershell.exe",
		"-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text",
		"-EncodedCommand", encodePowerShell(psPrefix+script))
	return cmd, func() {}
}

// platKill termina l'intero albero di processi (powershell + figli: msiexec, installer…).
func platKill(cmd *exec.Cmd) error {
	if cmd.Process != nil {
		_ = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid)).Run()
		return cmd.Process.Kill()
	}
	return nil
}

// detachedFlags: CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP. NON usare DETACHED_PROCESS: powershell.exe senza console esce subito
// con codice 0 senza eseguire nulla (verificato su Windows Server 2022: stesso comportamento per riavvio dopo update e disinstallazione).
const detachedFlags = 0x08000000 | 0x00000200

// restartSelf: processo staccato, il restart ferma questo stesso servizio e lo riavvia col nuovo exe.
func restartSelf() {
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
		"Start-Sleep 3; Restart-Service myrmm-agent")
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: detachedFlags}
	_ = cmd.Start()
}

// restartHard: ultimo tentativo quando Restart-Service non ha riavviato il servizio (PowerShell bloccato, servizio che non si ferma):
// un processo staccato ferma e riavvia il servizio con sc.exe, e l'agent stesso esce dopo pochi secondi.
func restartHard() {
	cmd := exec.Command("cmd.exe", "/c", "ping -n 6 127.0.0.1 >nul & sc.exe stop myrmm-agent >nul & ping -n 5 127.0.0.1 >nul & sc.exe start myrmm-agent >nul")
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: detachedFlags}
	_ = cmd.Start()
	go func() { time.Sleep(4 * time.Second); os.Exit(1) }()
}

func runJSONScript(script string, timeoutSec int) (map[string]any, error) {
	r := runScript(script, timeoutSec, 0)
	if r.ExitCode != 0 || r.Stdout == "" {
		return nil, fmt.Errorf("exit %d %s", r.ExitCode, r.Stderr)
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(r.Stdout), &m); err != nil {
		return nil, fmt.Errorf("JSON non valido: %v", err)
	}
	return m, nil
}

func platInventory() (map[string]any, error) { return runJSONScript(invScript, 60) }
func platFullInventory() (map[string]any, error) {
	m, err := runJSONScript(fullInvScript, 300)
	if err != nil {
		return nil, err
	}
	sec := map[string]any{}
	if raw, e := runJSONScript(secScript, 120); e == nil {
		sec = normalizeWinSecurity(raw, time.Now())
	}
	if la, ok := m["local_admins"]; ok { // amministratori locali: già raccolti dallo script principale
		names := []any{}
		for _, a := range asList(la) {
			if n, _ := a["member"].(string); n != "" {
				names = append(names, n)
			}
		}
		sec["local_admins"] = names
	}
	m["security"] = sec
	return m, nil
}

// uninstallScript: PowerShell che ferma e cancella il servizio, poi rimuove binario e dati (separato per poterlo verificare nei test).
func uninstallScript(exe, data, trace string) string {
	q := func(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }
	script := "$ErrorActionPreference='SilentlyContinue'; $lg=" + q(trace) + "; 'avvio '+(Get-Date -f s)+' pid '+$PID | Out-File -Append $lg; Unregister-ScheduledTask -TaskName 'myrmm-tray' -Confirm:$false; Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object {$_.CommandLine -like '*myrmm*tray.ps1*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}; Get-Process -Name 'myrmm-tray' | Stop-Process -Force; Start-Sleep 3; sc.exe stop myrmm-agent | Out-Null; Start-Sleep 4; sc.exe delete myrmm-agent | Out-Null; Start-Sleep 1;" +
		"foreach($f in " + q(exe) + "," + q(exe+".new") + "," + q(exe+".old") + "){for($i=0;$i -lt 10 -and (Test-Path $f);$i++){Remove-Item -Force $f; if(Test-Path $f){Start-Sleep 2}}};"
	leaf := strings.ToLower(filepath.Base(data))
	if leaf == "myrmm" || leaf == "myrmm-agent" {
		script += "Remove-Item -Recurse -Force " + q(data) + ";"
	} else {
		for _, f := range []string{"state.json", "config.json", "enroll-status.txt", "uninstalling.flag"} {
			script += "Remove-Item -Force " + q(filepath.Join(data, f)) + ";"
		}
	}
	script += "$d=" + q(filepath.Dir(exe)) + "; if((Test-Path $d) -and -not (Get-ChildItem -Force $d)){Remove-Item -Force $d};" +
		"'fine '+(Get-Date -f s)+' errori: '+$Error.Count | Out-File -Append $lg; $Error | ForEach-Object { $_.ToString() } | Out-File -Append $lg"
	return script
}

// platUninstall: lo esegue in un PowerShell staccato. Traccia in %SystemRoot%\Temp (fuori dalla cartella dati: sopravvive alla rimozione).
func platUninstall(exe, data string) {
	trace := filepath.Join(os.Getenv("SystemRoot"), "Temp", "myrmm-uninstall.log")
	script := uninstallScript(exe, data, trace)
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodePowerShell(script))
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: detachedFlags}
	if f, err := os.OpenFile(trace+".out", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil { // eventuali errori del PowerShell
		cmd.Stdout, cmd.Stderr = f, f
	}
	if err := cmd.Start(); err != nil {
		_ = os.WriteFile(trace, []byte("avvio del PowerShell di disinstallazione fallito: "+err.Error()+"\r\n"), 0o644)
		return
	}
	go func() { // esito del processo staccato (se muore subito, qui si vede il codice)
		err := cmd.Wait()
		_ = os.WriteFile(trace+".exit", []byte(fmt.Sprintf("%s: %v (stato %v)\r\n", time.Now().Format(time.RFC3339), err, cmd.ProcessState)), 0o644)
	}()
}
