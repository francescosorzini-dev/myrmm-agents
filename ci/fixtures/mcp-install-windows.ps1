# Installa il server MCP di myrmm su questo PC: un solo eseguibile (nessun Python) e la configurazione con il token.
# ====================================================================================
# @var MCP_TOKEN (obbligatoria): token API di myrmm (Operazioni → API e collaudo). Vale solo per questo uso: crealo apposta e revocalo se serve.
# @var MCP_URL (opzionale, default indirizzo di myrmm letto dalla config dell'agent): indirizzo di index.php.
# ====================================================================================
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$tok = @'
{{MCP_TOKEN|linea}}
'@
$url = @'
{{MCP_URL|linea}}
'@
$tok = $tok.Trim(); $url = $url.Trim()
if ($tok -notmatch '^myrmm_[0-9a-f]{48}$') { Write-Output 'MCP_TOKEN mancante o non valido (atteso myrmm_ + 48 caratteri esadecimali).'; exit 2 }
if (-not $url) { $c = Join-Path $env:ProgramData 'myrmm\config.json'; if (Test-Path $c) { $url = (Get-Content $c -Raw | ConvertFrom-Json).server_url } }
if ($url -notmatch '^https://[^\s''"]+$') { Write-Output 'MCP_URL mancante o non https.'; exit 2 }
$dir = Join-Path $env:ProgramFiles 'myrmm-mcp'
$exe = Join-Path $dir 'myrmm-mcp.exe'
$new = $exe + '.new'
$hdr = @{ 'X-Api-Token' = $tok }
$base = $url + '?action=api&r=mcp&os=windows&arch=amd64'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
try {
    $info = Invoke-RestMethod -Headers $hdr -Uri ($base + '&info=1')
    if ($info.sha256 -notmatch '^[0-9a-f]{64}$') { Write-Output 'Risposta inattesa da myrmm: il server MCP per Windows non risulta pubblicato (server/update/myrmm-mcp-windows-amd64.exe).'; exit 4 }
    Remove-Item $new -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest -UseBasicParsing -Headers $hdr -Uri $base -OutFile $new
    $h = (Get-FileHash -Algorithm SHA256 -Path $new).Hash.ToLower()
} catch {
    Write-Output "Scarico del server MCP non riuscito (token non valido, myrmm non raggiungibile o file bloccato dall'antivirus): $($_.Exception.Message)"
    Remove-Item $new -Force -ErrorAction SilentlyContinue
    exit 4
}
if ($h -ne $info.sha256) { Remove-Item $new -Force -ErrorAction SilentlyContinue; Write-Output 'Il file scaricato non corrisponde all''hash pubblicato dal server: non lo installo.'; exit 4 }
# sostituisce l'eseguibile anche se un assistente lo sta usando: Windows permette di rinominare un .exe in esecuzione
$old = $exe + '.old'
Remove-Item $old -Force -ErrorAction SilentlyContinue
if (Test-Path $exe) { Move-Item $exe $old -Force }
Move-Item $new $exe -Force
Remove-Item $old -Force -ErrorAction SilentlyContinue
# ripulisce l'installazione precedente basata su Python (1.53)
foreach ($n in 'python', 'myrmm_mcp.py', 'myrmm-mcp.cmd') { Remove-Item (Join-Path $dir $n) -Recurse -Force -ErrorAction SilentlyContinue }
$cfg = Join-Path $dir 'myrmm-mcp.json'
[IO.File]::WriteAllText($cfg, (@{ url = $url; token = $tok } | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
& icacls.exe $dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
& icacls.exe $cfg /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
$old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
$ver = (& $exe --version 2>&1 | Out-String).Trim(); $rc = $LASTEXITCODE
$ErrorActionPreference = $old
if ($rc -ne 0) { Write-Output "L'eseguibile scaricato non parte su questo PC: $ver"; Write-Output ('Sistema: ' + (Get-CimInstance Win32_OperatingSystem).Caption + ' ' + (Get-CimInstance Win32_OperatingSystem).Version + '. Servono gli stessi requisiti dell''agent (Windows 10 / Server 2016 o successivi).'); exit 3 }
Write-Output "Server MCP installato: $ver"
$ErrorActionPreference = 'Continue'
$chk = (& $exe --check 2>&1 | Out-String).Trim(); $rc = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
Write-Output $chk
if ($rc -ne 0) { Write-Output 'ATTENZIONE: file installati ma la verifica del token è fallita.'; exit 5 }
Write-Output "Installato in $dir. Configurazione leggibile solo da Amministratori e SYSTEM."
Write-Output "Claude Desktop: esegui «myrmm MCP: collega Claude Desktop (Windows)» (configura l'utente del PC senza altri passaggi)."
Write-Output "Claude Code (da prompt di un amministratore): claude mcp add myrmm -- `"$exe`""
