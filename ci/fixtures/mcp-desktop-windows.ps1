# Collega Claude Desktop di un utente di questo PC al server MCP di myrmm (prima va eseguito «myrmm MCP: installa su Windows»).
# ====================================================================================
# @var MCP_USER (opzionale, default l'utente collegato alla console): utente Windows di cui configurare Claude Desktop (es. mario oppure DOMINIO\mario).
# ====================================================================================
$ErrorActionPreference = 'Stop'
$user = @'
{{MCP_USER|linea}}
'@
$user = $user.Trim()
$dir = Join-Path $env:ProgramFiles 'myrmm-mcp'
$exe = Join-Path $dir 'myrmm-mcp.exe'
$cfg = Join-Path $dir 'myrmm-mcp.json'
if (-not (Test-Path $exe)) { Write-Output 'Il server MCP non è installato su questo PC: esegui prima «myrmm MCP: installa su Windows».'; exit 6 }
if (-not $user) { $user = [string](Get-CimInstance Win32_ComputerSystem).UserName }
if (-not $user) { Write-Output 'Nessun utente collegato alla console: indica MCP_USER.'; exit 2 }
if ($user -notmatch '^[\w .\\-]{1,80}$') { Write-Output 'MCP_USER non valido.'; exit 2 }
$short = $user.Split('\')[-1]
$prof = Get-CimInstance Win32_UserProfile | Where-Object { -not $_.Special -and $_.LocalPath -and ((Split-Path $_.LocalPath -Leaf) -ieq $short) } | Select-Object -First 1
if (-not $prof) { Write-Output "Profilo dell'utente '$short' non trovato su questo PC (deve aver fatto l'accesso almeno una volta)."; exit 2 }
$home_ = $prof.LocalPath
$sid = $prof.SID
# Claude Desktop installato da Microsoft Store/MSIX usa una cartella di dati propria; quello classico usa %APPDATA%\Claude
$targets = @(Join-Path $home_ 'AppData\Roaming\Claude\claude_desktop_config.json')
$pk = Join-Path $home_ 'AppData\Local\Packages'
if (Test-Path $pk) { Get-ChildItem $pk -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue | ForEach-Object { $targets += (Join-Path $_.FullName 'LocalCache\Roaming\Claude\claude_desktop_config.json') } }
$utf8 = New-Object Text.UTF8Encoding($false)
foreach ($path in $targets) {
    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    $obj = $null
    if (Test-Path $path) {
        $raw = [IO.File]::ReadAllText($path)
        Copy-Item $path ($path + '.myrmm.bak') -Force
        if ($raw.Trim()) { try { $obj = $raw | ConvertFrom-Json } catch { Write-Output "Il file $path non è un JSON valido: non lo tocco (copia in .myrmm.bak)."; exit 7 } }
    }
    if (-not $obj) { $obj = [pscustomobject]@{} }
    if (-not $obj.PSObject.Properties['mcpServers']) { $obj | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) }
    $entry = [pscustomobject]@{ command = $exe; args = @() }
    if ($obj.mcpServers.PSObject.Properties['myrmm']) { $obj.mcpServers.myrmm = $entry } else { $obj.mcpServers | Add-Member -NotePropertyName myrmm -NotePropertyValue $entry }
    [IO.File]::WriteAllText($path, ($obj | ConvertTo-Json -Depth 20), $utf8)
    & icacls.exe $path /grant ('*' + $sid + ':(M)') | Out-Null
    Write-Output "Configurato: $path"
}
# il server MCP legge indirizzo e token dal suo file di configurazione (nessun token nel profilo dell'utente): l'utente deve poterlo leggere
& icacls.exe $cfg /grant ('*' + $sid + ':(R)') | Out-Null
$found = (Test-Path (Join-Path $home_ 'AppData\Local\AnthropicClaude')) -or (Test-Path (Join-Path $home_ 'AppData\Local\Programs\Claude')) -or [bool](Get-ChildItem $pk -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue)
Write-Output "Utente: $short. L'utente può leggere $cfg (contiene il token)."
if ($found) { Write-Output 'Chiudi Claude Desktop del tutto (icona nell''area di notifica → Esci) e riaprilo: lo strumento «myrmm» compare tra i connettori.' }
else { Write-Output 'ATTENZIONE: Claude Desktop non risulta installato per questo utente. Installalo da https://claude.ai/download: la configurazione è già pronta e verrà letta alla prima apertura.' }
