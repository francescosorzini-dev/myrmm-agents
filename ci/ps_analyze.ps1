# Analisi statica di script PowerShell con il parser di pwsh, contro i limiti di Windows PowerShell 5.1 (quello che esegue l'agent).
# Ingresso: file JSON [{name, body}]; uscita: JSON [{name, problems[]}]. Non esegue nulla.
param([Parameter(Mandatory)][string]$In, [Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = 'Stop'
$items = Get-Content -LiteralPath $In -Raw -Encoding UTF8 | ConvertFrom-Json
$badTok = @('AndAnd','OrOr','QuestionQuestion','QuestionQuestionEquals','QuestionDot','QuestionMark','QuestionLBracket')
$badAst = @('TernaryExpressionAst','PipelineChainAst')
$badVar = @('IsWindows','IsLinux','IsMacOS','IsCoreCLR','PSStyle','PSNativeCommandUseErrorActionPreference')
$badCmd = @('Join-String','Test-Json','Get-Error','ConvertFrom-Markdown','Remove-Alias','Get-Clipboard','Set-Clipboard')
$badParam = @{
  'ConvertFrom-Json' = @('AsHashtable','Depth','NoEnumerate'); 'ConvertTo-Json' = @('AsArray','EnumsAsStrings');
  'Get-Content' = @('AsByteStream'); 'Set-Content' = @('AsByteStream'); 'ForEach-Object' = @('Parallel','ThrottleLimit');
  'Invoke-WebRequest' = @('SkipHttpErrorCheck','SkipCertificateCheck','AllowUnencryptedAuthentication','Authentication','Token');
  'Invoke-RestMethod' = @('SkipHttpErrorCheck','SkipCertificateCheck','AllowUnencryptedAuthentication','Authentication','Token','ResponseHeadersVariable');
  'Test-Connection' = @('TargetName','IPv4','IPv6','Traceroute','MaxHops','TimeoutSeconds','Repeat');
  'Select-String' = @('Raw'); 'Sort-Object' = @('Top'); 'Get-Date' = @('AsUTC'); 'Start-Process' = @('Environment');
  'Out-File' = @(); 'Write-Host' = @(); 'Select-Object' = @(); 'Format-Table' = @(); 'Compress-Archive' = @('CompressionLevelX')
}
$interactive = @('Read-Host','Get-Credential','Out-GridView','Show-Command','Pause','Read-Host')
$res = foreach ($it in $items) {
  $p = New-Object System.Collections.Generic.List[string]
  $tokens = $null; $errs = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseInput([string]$it.body, [ref]$tokens, [ref]$errs)
  foreach ($e in $errs) { $p.Add("sintassi riga $($e.Extent.StartLineNumber): $($e.Message)") }
  foreach ($t in $tokens) { if ($badTok -contains $t.Kind.ToString()) { $p.Add("sintassi solo di PowerShell 7 ($($t.Kind)) riga $($t.Extent.StartLineNumber)") } }
  foreach ($a in $ast.FindAll({ $true }, $true)) {
    $n = $a.GetType().Name
    if ($badAst -contains $n) { $p.Add("costrutto solo di PowerShell 7 ($n) riga $($a.Extent.StartLineNumber)") }
    if ($n -eq 'VariableExpressionAst' -and ($badVar -contains $a.VariablePath.UserPath)) { $p.Add("variabile solo di PowerShell 6+ (`$$($a.VariablePath.UserPath)) riga $($a.Extent.StartLineNumber)") }
    if ($n -eq 'CommandAst') {
      $cn = $a.GetCommandName()
      if ($cn) {
        if ($badCmd -contains $cn) { $p.Add("comando assente in 5.1: $cn riga $($a.Extent.StartLineNumber)") }
        if ($interactive -contains $cn) { $p.Add("comando interattivo: $cn riga $($a.Extent.StartLineNumber)") }
        $pn = @($a.CommandElements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] } | ForEach-Object { $_.ParameterName })
        if ($badParam.ContainsKey($cn)) { foreach ($x in $pn) { if ($badParam[$cn] -contains $x) { $p.Add("parametro assente in 5.1: $cn -$x riga $($a.Extent.StartLineNumber)") } } }
        if ($cn -eq 'Invoke-WebRequest' -and -not ($pn | Where-Object { 'UseBasicParsing'.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) -and $_.Length -ge 3 })) { $p.Add("Invoke-WebRequest senza -UseBasicParsing (in 5.1 usa Internet Explorer) riga $($a.Extent.StartLineNumber)") }
        if (($cn -eq 'Out-File' -or $cn -eq 'Set-Content' -or $cn -eq 'Add-Content') -and ($a.Extent.Text -match '(?i)-Encoding\s+(utf8NoBOM|utf8BOM|ansi|oem)\b')) { $p.Add("-Encoding non valido in 5.1 riga $($a.Extent.StartLineNumber)") }
      }
    }
    if ($n -eq 'StringConstantExpressionAst' -or $n -eq 'ExpandableStringExpressionAst') { if ($a.Extent.Text -match '(?<!`)`(e|u\{)') { $p.Add("escape solo di PowerShell 6+ riga $($a.Extent.StartLineNumber)") } }
  }
  [pscustomobject]@{ name = $it.name; problems = @($p | Select-Object -Unique) }
}
$res | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath $Out -Encoding UTF8
