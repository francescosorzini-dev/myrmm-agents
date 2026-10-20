# Prova della logica di agent/deploy_win.ps1 senza un PC Windows: i cmdlet CIM/SMB sono sostituiti da simulazioni.
# Uso: pwsh -File deploy_win_mock.ps1 <deploy_win.ps1> <scenario>   (scenari: dry-ok | dry-noserver | run-ok | run-notenrolled | run-fail | already | denied)
param([string]$Script, [string]$Scenario)
$ErrorActionPreference = 'Stop'
$fake = Join-Path ([IO.Path]::GetTempPath()) ('fakewin-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force (Join-Path $fake 'Temp') | Out-Null
$global:installed = ($Scenario -eq 'already')
$global:installRan = $false
$global:calls = New-Object System.Collections.ArrayList

function New-CimSessionOption { param($Protocol) return [pscustomobject]@{ Protocol = $Protocol } }
function New-CimSession {
    param($ComputerName, $Credential, $SessionOption, $OperationTimeoutSec)
    if ($Scenario -eq 'denied') { throw [System.UnauthorizedAccessException]::new('Access is denied. (0x80070005)') }
    [void]$global:calls.Add('session:' + $ComputerName + ':' + $Credential.UserName)
    return [pscustomobject]@{ Name = 'mock' }
}
function Remove-CimSession { param($CimSession) [void]$global:calls.Add('session-closed') }
function Get-CimInstance {
    param($CimSession, $ClassName, $Filter)
    switch ($ClassName) {
        'Win32_OperatingSystem' { return [pscustomobject]@{ Caption = 'Microsoft Windows 11 Pro'; Version = '10.0.22631'; CSName = 'PC-PROVA' } }
        'Win32_LogicalDisk' { return [pscustomobject]@{ FreeSpace = [int64](80GB) } }
        'Win32_Service' { if ($global:installed) { return [pscustomobject]@{ State = 'Running' } } else { return $null } }
        'Win32_Process' { return $null }
    }
}
function Invoke-CimMethod {
    param($CimSession, $ClassName, $MethodName, $Arguments)
    $cmd = $Arguments.CommandLine
    [void]$global:calls.Add('exec:' + $cmd)
    if ($cmd -match 'Invoke-WebRequest') {
        $m = [regex]::Match($cmd, '"%SystemRoot%\\Temp\\([^"]+)"'); $f = Join-Path $fake ('Temp/' + $m.Groups[1].Value)
        if ($Scenario -eq 'dry-noserver') { Set-Content $f 'ERRORE Impossibile connettersi al server remoto' } else { Set-Content $f 'HTTP 200' }
    } elseif ($cmd -match '-File "%SystemRoot%\\Temp\\([^"]+)\.ps1"') {
        $global:installRan = $true
        $log = Join-Path $fake ('Temp/' + $Matches[1] + '.log')
        switch ($Scenario) {
            'run-ok' { Set-Content $log "myrmm-agent 1.36.0 installato e arruolato."; $global:installed = $true }
            'run-notenrolled' { Set-Content $log "WARNING: Servizio avviato ma non ancora arruolato"; $global:installed = $true }
            'run-fail' { Set-Content $log "SHA-256 del binario non corrisponde"; }
        }
    }
    return [pscustomobject]@{ ReturnValue = 0; ProcessId = 4242 }
}
function New-PSDrive {
    param($Name, $PSProvider, $Root, $Credential)
    [void]$global:calls.Add('smb:' + $Root)
    Microsoft.PowerShell.Management\New-PSDrive -Name $Name -PSProvider FileSystem -Root $fake -Scope Global
}
$env:MYRMM_DEP_IP = '10.0.0.5'; $env:MYRMM_DEP_U = 'DOM\admin'; $env:MYRMM_DEP_P = 'S3greta!'; $env:MYRMM_DEP_URL = 'https://rmm.example.it/index.php'
$env:MYRMM_DEP_MODE = if ($Scenario -like 'dry*' -or $Scenario -eq 'already' -or $Scenario -eq 'denied') { 'dry' } else { 'run' }
$inst = Join-Path $fake 'install-src.ps1'; Set-Content $inst 'Write-Output "install"'; $env:MYRMM_DEP_SCRIPT = $inst
$out = & $Script 2>&1 | Out-String
Write-Output $out
Write-Output ('CALLS ' + ($global:calls -join ' ## '))
Write-Output ('LEFTOVER ' + ((Get-ChildItem (Join-Path $fake 'Temp') -ErrorAction SilentlyContinue | Measure-Object).Count))
Remove-Item -Recurse -Force $fake -ErrorAction SilentlyContinue
