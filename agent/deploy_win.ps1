# myrmm - distribuzione dell'agent su un PC Windows dalla sonda Windows (SMB + WMI/DCOM).
# Eseguito dall'agent della sonda; i parametri arrivano dall'ambiente (la password non compare mai sulla riga di comando).
#   MYRMM_DEP_IP     indirizzo del PC di destinazione
#   MYRMM_DEP_U / MYRMM_DEP_P   account amministratore (DOMINIO\utente, utente@dominio o NOMEPC\utente)
#   MYRMM_DEP_MODE   dry = solo controlli | run = installazione
#   MYRMM_DEP_SCRIPT percorso dello script di installazione da copiare (solo run)
#   MYRMM_DEP_URL    URL del server (per verificare che il PC lo raggiunga)
# Uscita: righe "MYRMM_STEP ..." e, in fondo, "MYRMM_RESULT {json}".
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ip = $env:MYRMM_DEP_IP
$mode = $env:MYRMM_DEP_MODE
$cs = $null
$drv = $null

function Step([string]$t) { Write-Output ("MYRMM_STEP " + $t) }
function Finish([bool]$ok, [string]$state, [string]$detail) {
    Write-Output ('MYRMM_RESULT ' + (@{ ok = $ok; state = $state; detail = $detail } | ConvertTo-Json -Compress))
}
function Clean-Err([string]$m) {
    $m = ($m -replace '\s+', ' ').Trim()
    if ($m -match 'Access is denied|Accesso negato|0x80070005|E_ACCESSDENIED') { return 'accesso negato: utente o password errati, o l''account non è amministratore del PC (per gli account locali serve LocalAccountTokenFilterPolicy=1)' }
    if ($m -match '1219|Multiple connections|più connessioni') { return 'esiste già una connessione al PC con un altro utente (chiudila con net use \\' + $ip + ' /delete)' }
    if ($m -match '53|network path|percorso di rete|1203|1231|RPC server is unavailable|server RPC|0x800706BA') { return 'PC non raggiungibile via SMB/WMI (firewall di Windows: servono «Condivisione file e stampanti» e «Strumentazione gestione Windows (WMI)»)' }
    if ($m -match 'logon failure|1326|password non corretti|user name or password') { return 'utente o password errati' }
    return $m
}
function Wait-Process-Remote($session, [int]$procId, [int]$maxSec) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $maxSec) {
        $p = Get-CimInstance -CimSession $session -ClassName Win32_Process -Filter ("ProcessId=" + $procId) -ErrorAction SilentlyContinue
        if (-not $p) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}
function Run-Remote($session, [string]$cmd) {
    $r = Invoke-CimMethod -CimSession $session -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
    if ($r.ReturnValue -ne 0) { throw ("creazione del processo remoto fallita (codice " + $r.ReturnValue + ")") }
    return [int]$r.ProcessId
}

try {
    if (-not $ip) { throw 'indirizzo mancante' }
    $sec = ConvertTo-SecureString $env:MYRMM_DEP_P -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential ($env:MYRMM_DEP_U, $sec)

    Step 'Connessione WMI (DCOM)'
    $opt = New-CimSessionOption -Protocol Dcom
    $cs = New-CimSession -ComputerName $ip -Credential $cred -SessionOption $opt -OperationTimeoutSec 30 -ErrorAction Stop
    $os = Get-CimInstance -CimSession $cs -ClassName Win32_OperatingSystem -ErrorAction Stop
    $disk = Get-CimInstance -CimSession $cs -ClassName Win32_LogicalDisk -Filter "DeviceID='C:'" -ErrorAction SilentlyContinue
    $svc = Get-CimInstance -CimSession $cs -ClassName Win32_Service -Filter "Name='myrmm-agent'" -ErrorAction SilentlyContinue
    $freeGb = if ($disk) { [math]::Round($disk.FreeSpace / 1GB, 1) } else { -1 }
    $info = ('{0} {1} · {2} · utente {3} · spazio libero C: {4} GB' -f $os.Caption, $os.Version, $os.CSName, $env:MYRMM_DEP_U, $freeGb)
    if ($svc -and $svc.State -eq 'Running') { Finish $true 'skip' ('agent già installato e in esecuzione. ' + $info); return }

    Step 'Accesso alla condivisione amministrativa (SMB)'
    $drv = 'MYRMMDEP' + (Get-Random -Maximum 99999)
    New-PSDrive -Name $drv -PSProvider FileSystem -Root ("\\" + $ip + "\ADMIN$") -Credential $cred -ErrorAction Stop | Out-Null
    $tmpName = 'myrmm-probe-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $tmpDir = $drv + ':\Temp'
    if (-not (Test-Path $tmpDir)) { $tmpDir = $drv + ':\' }

    Step 'Verifica che il PC raggiunga il server'
    $chk = $tmpName + '.txt'
    $url = ($env:MYRMM_DEP_URL -replace "'", '')
    $cmd = 'cmd /c powershell -NoProfile -NonInteractive -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri ''' + $url + '?action=ping'' -TimeoutSec 10; ''HTTP '' + $r.StatusCode } catch { if ($_.Exception.Response) { ''HTTP '' + [int]$_.Exception.Response.StatusCode } else { ''ERRORE '' + $_.Exception.Message } }" > "%SystemRoot%\Temp\' + $chk + '" 2>&1'
    $pidChk = Run-Remote $cs $cmd
    $null = Wait-Process-Remote $cs $pidChk 45
    $reach = 'non verificato'
    $chkPath = Join-Path $tmpDir $chk
    for ($i = 0; $i -lt 5 -and -not (Test-Path $chkPath); $i++) { Start-Sleep -Seconds 1 }
    if (Test-Path $chkPath) {
        $reach = ((Get-Content $chkPath -ErrorAction SilentlyContinue) -join ' ').Trim()
        Remove-Item $chkPath -Force -ErrorAction SilentlyContinue
    }
    $reachOk = $reach -match '^HTTP \d+'
    $info = $info + ' · il PC verso il server: ' + $reach

    if ($mode -eq 'dry') {
        if (-not $reachOk) { Finish $false 'fail' ('il PC non raggiunge il server (' + $reach + '): l''installazione non potrebbe scaricare l''agent. ' + $info); return }
        if ($freeGb -ge 0 -and $freeGb -lt 1) { Finish $false 'fail' ('spazio libero insufficiente. ' + $info); return }
        Finish $true 'ok' ('pronto per l''installazione. ' + $info)
        return
    }

    if (-not $reachOk) { Finish $false 'fail' ('il PC non raggiunge il server (' + $reach + '). ' + $info); return }
    Step 'Copia dello script di installazione'
    $name = 'myrmm-install-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    Copy-Item -LiteralPath $env:MYRMM_DEP_SCRIPT -Destination (Join-Path $tmpDir ($name + '.ps1')) -Force
    $logName = $name + '.log'
    Step 'Installazione sul PC'
    $cmd = 'cmd /c powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%SystemRoot%\Temp\' + $name + '.ps1" > "%SystemRoot%\Temp\' + $logName + '" 2>&1'
    $pidInst = Run-Remote $cs $cmd
    $ended = Wait-Process-Remote $cs $pidInst 420
    $log = ''
    $logPath = Join-Path $tmpDir $logName
    if (Test-Path $logPath) { $log = ((Get-Content $logPath -Tail 6 -ErrorAction SilentlyContinue) -join ' | ') }
    Remove-Item (Join-Path $tmpDir ($name + '.ps1')) -Force -ErrorAction SilentlyContinue
    Remove-Item $logPath -Force -ErrorAction SilentlyContinue
    if (-not $ended) { Finish $false 'fail' ('installazione ancora in corso dopo 7 minuti: controlla il PC. ' + $log); return }

    Step 'Verifica del servizio'
    $svc = $null
    for ($i = 0; $i -lt 10; $i++) {
        $svc = Get-CimInstance -CimSession $cs -ClassName Win32_Service -Filter "Name='myrmm-agent'" -ErrorAction SilentlyContinue
        if ($svc -and $svc.State -eq 'Running') { break }
        Start-Sleep -Seconds 3
    }
    if ($svc -and $svc.State -eq 'Running') {
        if ($log -match 'non ancora arruolato') { Finish $true 'ok' ('installato, ma non ancora arruolato: ' + $log) }
        else { Finish $true 'ok' ('installato e in esecuzione. ' + $log) }
    } else {
        Finish $false 'fail' ('il servizio myrmm-agent non risulta in esecuzione. ' + $log)
    }
} catch {
    Finish $false 'fail' (Clean-Err $_.Exception.Message)
} finally {
    if ($drv) { Remove-PSDrive -Name $drv -Force -ErrorAction SilentlyContinue }
    if ($cs) { Remove-CimSession -CimSession $cs -ErrorAction SilentlyContinue }
}
