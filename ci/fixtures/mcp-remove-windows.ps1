# Rimuove il server MCP di myrmm e il suo token da questo PC.
# ====================================================================================
# Nessuna variabile da impostare. Poi revoca il token in console (Operazioni → API e collaudo) se non serve più altrove.
# ====================================================================================
$dir = Join-Path $env:ProgramFiles 'myrmm-mcp'
Get-Process -Name 'myrmm-mcp' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force; Write-Output "Rimosso $dir (con la configurazione e il token)." } else { Write-Output 'Non era installato.' }
