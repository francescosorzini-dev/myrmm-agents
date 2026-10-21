Write-Output 'myrmm: scarico l''agent (compresso)...'
$gz = $tmp + '.gz'
Invoke-WebRequest -UseBasicParsing -Uri '{{URL}}' -OutFile $gz
$in = [IO.File]::OpenRead($gz); try { $z = New-Object IO.Compression.GZipStream($in, [IO.Compression.CompressionMode]::Decompress); $o = [IO.File]::Create($tmp); try { $z.CopyTo($o) } finally { $o.Dispose(); $z.Dispose() } } finally { $in.Dispose(); Remove-Item $gz -Force -ErrorAction SilentlyContinue }
