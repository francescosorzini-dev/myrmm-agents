# myrmm - icona nella systray e chat con l'assistenza (Windows).
# Avviata all'accesso dell'utente dall'attivita' pianificata "myrmm-tray"; parla solo con l'agent locale (127.0.0.1).
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$mutex = New-Object System.Threading.Mutex($false, 'Local\myrmm-tray')
if (-not $mutex.WaitOne(0)) { exit }

$script:base = $null
$script:st = $null
$script:lastNotified = 0
$script:lastSeen = 0
$script:lastSig = ''
$script:online = $null

function Get-Base {
    $f = Join-Path $PSScriptRoot 'tray.json'
    if (Test-Path $f) {
        $p = (Get-Content -Raw $f | ConvertFrom-Json).port
        if ($p) { return "http://127.0.0.1:$p" }
    }
    return $null
}

function Call-Agent([string]$path, $body, [int]$timeout = 5) {
    if (-not $script:base) { $script:base = Get-Base }
    if (-not $script:base) { return $null }
    $h = @{ 'X-Myrmm-Tray' = '1' }
    try {
        if ($null -ne $body) {
            $json = $body | ConvertTo-Json -Compress
            return Invoke-RestMethod -Uri ($script:base + $path) -Method Post -Headers $h -TimeoutSec $timeout -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) -UseBasicParsing
        }
        return Invoke-RestMethod -Uri ($script:base + $path) -Headers $h -TimeoutSec 5 -UseBasicParsing
    } catch { $script:base = $null; return $null }
}

function New-TrayIcon([bool]$ok) {
    $bmp = New-Object System.Drawing.Bitmap 32, 32
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.TextRenderingHint = 'AntiAliasGridFit'
    $col = if ($ok) { [System.Drawing.Color]::FromArgb(37, 99, 235) } else { [System.Drawing.Color]::FromArgb(120, 120, 120) }
    $g.FillEllipse((New-Object System.Drawing.SolidBrush $col), 1, 1, 30, 30)
    $f = New-Object System.Drawing.Font('Segoe UI', 17, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $sf = New-Object System.Drawing.StringFormat
    $sf.Alignment = 'Center'; $sf.LineAlignment = 'Center'
    $g.DrawString('m', $f, [System.Drawing.Brushes]::White, (New-Object System.Drawing.RectangleF(0, 0, 32, 32)), $sf)
    $g.Dispose()
    return [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}

function To-Local($t) {
    if ($t -isnot [datetime]) { $t = [datetime]::Parse([string]$t, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind) }
    return $t.ToLocalTime()
}

# ---- finestra della chat ----
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Assistenza'
$form.Size = New-Object System.Drawing.Size(440, 540)
$form.MinimumSize = New-Object System.Drawing.Size(340, 360)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.ShowInTaskbar = $true

$tbl = New-Object System.Windows.Forms.TableLayoutPanel
$tbl.Dock = 'Fill'; $tbl.ColumnCount = 1; $tbl.RowCount = 2
[void]$tbl.RowStyles.Add((New-Object System.Windows.Forms.RowStyle('Percent', 100)))
[void]$tbl.RowStyles.Add((New-Object System.Windows.Forms.RowStyle('Absolute', 144)))
$form.Controls.Add($tbl)

$rtb = New-Object System.Windows.Forms.RichTextBox
$rtb.Dock = 'Fill'; $rtb.ReadOnly = $true; $rtb.BackColor = [System.Drawing.Color]::White; $rtb.BorderStyle = 'None'
$rtb.DetectUrls = $false
$tbl.Controls.Add($rtb, 0, 0)

$bottom = New-Object System.Windows.Forms.Panel
$bottom.Dock = 'Fill'; $bottom.Padding = New-Object System.Windows.Forms.Padding(6)
$tbl.Controls.Add($bottom, 0, 1)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = 'Invia'; $btn.Dock = 'Right'; $btn.Width = 84
$bottom.Controls.Add($btn)

$tools = New-Object System.Windows.Forms.FlowLayoutPanel
$tools.Dock = 'Top'; $tools.Height = 30; $tools.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 2)
$btnShot = New-Object System.Windows.Forms.Button
$btnShot.Text = 'Screenshot'; $btnShot.AutoSize = $true
$btnImg = New-Object System.Windows.Forms.Button
$btnImg.Text = 'Allega immagine...'; $btnImg.AutoSize = $true
$tools.Controls.Add($btnShot); $tools.Controls.Add($btnImg)
$bottom.Controls.Add($tools)

$subj = New-Object System.Windows.Forms.TextBox
$subj.Dock = 'Top'; $subj.MaxLength = 140; $subj.Visible = $false
$bottom.Controls.Add($subj)
$chk = New-Object System.Windows.Forms.CheckBox
$chk.Text = 'Apri una richiesta di assistenza (ticket)'; $chk.Dock = 'Top'; $chk.Height = 24; $chk.AutoSize = $false
$bottom.Controls.Add($chk)
$chk.Add_CheckedChanged({
    $subj.Visible = $chk.Checked
    $tbl.RowStyles[1].Height = $(if ($chk.Checked) { 172 } else { 144 })
    if ($chk.Checked) { $subj.Focus() | Out-Null }
})

$inp = New-Object System.Windows.Forms.TextBox
$inp.Multiline = $true; $inp.Dock = 'Fill'; $inp.AcceptsReturn = $false; $inp.MaxLength = 2000
$bottom.Controls.Add($inp)
$inp.BringToFront()

# ---- immagini: screenshot, allegati, miniature ----
$script:thumbs = @{}
$script:hits = @()

function Get-ImgBytes([string]$n) {
    if (-not $script:base) { $script:base = Get-Base }
    if (-not $script:base) { return $null }
    try {
        $r = Invoke-WebRequest -Uri ($script:base + '/img?n=' + [uri]::EscapeDataString($n)) -Headers @{ 'X-Myrmm-Tray' = '1' } -TimeoutSec 10 -UseBasicParsing
        return ,[byte[]]$r.Content
    } catch { return $null }
}

function Get-ThumbRtf([string]$n) {
    if ($script:thumbs.ContainsKey($n)) { return $script:thumbs[$n] }
    $b = Get-ImgBytes $n
    if (-not $b) { return $null }
    try {
        $ms = New-Object System.IO.MemoryStream(, $b)
        $img = [System.Drawing.Image]::FromStream($ms)
        $w = [Math]::Min(280, $img.Width)
        $h = [int][Math]::Max(1, $img.Height * $w / $img.Width)
        $bmp = New-Object System.Drawing.Bitmap($w, $h)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.InterpolationMode = 'HighQualityBicubic'
        $g.DrawImage($img, 0, 0, $w, $h)
        $g.Dispose()
        $o = New-Object System.IO.MemoryStream
        $bmp.Save($o, [System.Drawing.Imaging.ImageFormat]::Png)
        $hex = [BitConverter]::ToString($o.ToArray()).Replace('-', '').ToLower()
        $rtf = '{\rtf1\ansi{\pict\pngblip\picw' + $w + '\pich' + $h + '\picwgoal' + ($w * 15) + '\pichgoal' + ($h * 15) + ' ' + $hex + '}}'
        $bmp.Dispose(); $img.Dispose()
        $script:thumbs[$n] = $rtf
        return $rtf
    } catch { return $null }
}

function Show-Viewer([string]$n) {
    $b = Get-ImgBytes $n
    if (-not $b) { return }
    try {
        $ms = New-Object System.IO.MemoryStream(, $b)
        $img = [System.Drawing.Image]::FromStream($ms)
        $v = New-Object System.Windows.Forms.Form
        $v.Text = 'Immagine'; $v.StartPosition = 'CenterScreen'; $v.Size = New-Object System.Drawing.Size(900, 650)
        $pic = New-Object System.Windows.Forms.PictureBox
        $pic.Dock = 'Fill'; $pic.SizeMode = 'Zoom'; $pic.Image = $img; $pic.BackColor = [System.Drawing.Color]::FromArgb(40, 40, 40)
        $v.Controls.Add($pic)
        $v.Add_KeyDown({ param($s, $e) if ($e.KeyCode -eq 'Escape') { $s.Close() } })
        $v.KeyPreview = $true
        [void]$v.ShowDialog()
        $v.Dispose(); $img.Dispose()
    } catch { }
}

# anteprima obbligatoria: nulla parte verso l'assistenza senza che l'utente abbia visto l'immagine e premuto Invia
function Confirm-Image($img, [string]$title, [bool]$retry) {
    $d = New-Object System.Windows.Forms.Form
    $d.Text = $title; $d.StartPosition = 'CenterScreen'; $d.Size = New-Object System.Drawing.Size(780, 640)
    $d.MinimumSize = New-Object System.Drawing.Size(520, 420); $d.TopMost = $true; $d.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $pic = New-Object System.Windows.Forms.PictureBox
    $pic.Dock = 'Fill'; $pic.SizeMode = 'Zoom'; $pic.Image = $img; $pic.BackColor = [System.Drawing.Color]::FromArgb(40, 40, 40)
    $d.Controls.Add($pic)
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Dock = 'Top'; $lbl.Height = 48; $lbl.Padding = New-Object System.Windows.Forms.Padding(8, 6, 8, 0)
    $lbl.Text = "Controlla l'anteprima. L'immagine arriva all'assistenza solo se premi Invia: verifica che non mostri password o dati riservati."
    $d.Controls.Add($lbl)
    $pnl = New-Object System.Windows.Forms.Panel
    $pnl.Dock = 'Bottom'; $pnl.Height = 88; $pnl.Padding = New-Object System.Windows.Forms.Padding(8)
    $cap = New-Object System.Windows.Forms.TextBox
    $cap.Dock = 'Top'; $cap.MaxLength = 500
    $cap2 = New-Object System.Windows.Forms.Label
    $cap2.Dock = 'Top'; $cap2.Height = 20; $cap2.Text = 'Messaggio (facoltativo):'
    $fl = New-Object System.Windows.Forms.FlowLayoutPanel
    $fl.Dock = 'Fill'; $fl.FlowDirection = 'RightToLeft'
    $bOk = New-Object System.Windows.Forms.Button; $bOk.Text = 'Invia'; $bOk.DialogResult = 'OK'; $bOk.Width = 90
    $bNo = New-Object System.Windows.Forms.Button; $bNo.Text = 'Annulla'; $bNo.DialogResult = 'Cancel'; $bNo.Width = 90
    $fl.Controls.Add($bOk); $fl.Controls.Add($bNo)
    if ($retry) {
        $bRe = New-Object System.Windows.Forms.Button; $bRe.Text = 'Rifai'; $bRe.DialogResult = 'Retry'; $bRe.AutoSize = $true
        $fl.Controls.Add($bRe)
    }
    $pnl.Controls.Add($fl); $pnl.Controls.Add($cap); $pnl.Controls.Add($cap2)
    $d.Controls.Add($pnl)
    $d.AcceptButton = $bOk; $d.CancelButton = $bNo
    $res = $d.ShowDialog()
    $txt = $cap.Text.Trim()
    $d.Dispose()
    return @{ res = [string]$res; text = $txt }
}

function Send-Image($img, [string]$kind, [string]$text) {
    # l'immagine parte come PNG: e' l'agent a ridurla e comprimerla (nessuna codifica JPEG in questo script)
    $ms = New-Object System.IO.MemoryStream
    $img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    if ($ms.Length -gt 14000000) { [System.Windows.Forms.MessageBox]::Show("L'immagine e' troppo grande per essere inviata.", 'Assistenza') | Out-Null; return }
    $b64 = [Convert]::ToBase64String($ms.ToArray())
    $r = Call-Agent '/send' @{ text = $text; img = $b64; kind = $kind } 60
    if ($r) { Poll $true } else { [System.Windows.Forms.MessageBox]::Show("Impossibile inviare l'immagine (se e' molto grande, riduci l'area o riprova).", 'Assistenza') | Out-Null }
}

# cattura con lo strumento di Windows (Win+Maiusc+S): l'utente sceglie l'area, l'immagine arriva negli appunti
Add-Type -Namespace Myrmm -Name Clip -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern uint GetClipboardSequenceNumber();'
function Get-ClipImageAfterSnip {
    $seq = [Myrmm.Clip]::GetClipboardSequenceNumber()
    $started = $false
    try { Start-Process 'ms-screenclip:'; $started = $true } catch { }
    if (-not $started) { [System.Windows.Forms.SendKeys]::SendWait('{PRTSC}') }
    $end = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $end) {
        Start-Sleep -Milliseconds 300
        [System.Windows.Forms.Application]::DoEvents()
        if ([Myrmm.Clip]::GetClipboardSequenceNumber() -ne $seq -and [System.Windows.Forms.Clipboard]::ContainsImage()) {
            return [System.Windows.Forms.Clipboard]::GetImage()
        }
    }
    return $null
}

function Do-Screenshot {
  try {
    $form.Hide()
    Start-Sleep -Milliseconds 300
    $img = $null
    do {
        $img = Get-ClipImageAfterSnip
        if (-not $img) { $ni.ShowBalloonTip(4000, 'Assistenza', 'Nessuno screenshot catturato.', [System.Windows.Forms.ToolTipIcon]::Info); break }
        $r = Confirm-Image $img 'Anteprima screenshot' $true
        if ($r.res -eq 'Retry') { $img.Dispose(); $img = $null }
    } while ($r.res -eq 'Retry')
    if ($img -and $r.res -eq 'OK') { Send-Image $img 'shot' $r.text }
    if ($img) { $img.Dispose() }
    Show-Chat
  } catch { try { Show-Chat } catch { } }
}

function Do-Attach([string]$path) {
  try {
    if (-not $path) {
        $dlg = New-Object System.Windows.Forms.OpenFileDialog
        $dlg.Filter = 'Immagini|*.png;*.jpg;*.jpeg;*.gif;*.bmp|Tutti i file|*.*'
        if ($dlg.ShowDialog() -ne 'OK') { return }
        $path = $dlg.FileName
    }
    $ms = New-Object System.IO.MemoryStream(, [System.IO.File]::ReadAllBytes($path))
    $img = $null
    try { $img = [System.Drawing.Image]::FromStream($ms) } catch { }
    if (-not $img) { [System.Windows.Forms.MessageBox]::Show("Il file scelto non e' un'immagine che si possa inviare (usa PNG, JPEG, GIF o BMP).", 'Assistenza') | Out-Null; return }
    $r = Confirm-Image $img 'Anteprima immagine' $false
    if ($r.res -eq 'OK') { Send-Image $img 'file' $r.text }
    $img.Dispose()
  } catch { }
}

function Do-Paste {
  try {
    $img = [System.Windows.Forms.Clipboard]::GetImage()
    if (-not $img) { return }
    $r = Confirm-Image $img 'Anteprima immagine incollata' $false
    if ($r.res -eq 'OK') { Send-Image $img 'file' $r.text }
    $img.Dispose()
  } catch { }
}

$btnShot.Add_Click({ Do-Screenshot })
$btnImg.Add_Click({ Do-Attach '' })
$rtb.Add_MouseClick({ param($s, $e)
    try {
        $i = $rtb.GetCharIndexFromPosition($e.Location)
        foreach ($h in $script:hits) { if ($i -ge $h.s -and $i -lt $h.e) { Show-Viewer $h.n; break } }
    } catch { }
})

function Render($log) {
    $log = @($log | Where-Object { $_ })
    $sig = ($log | ForEach-Object { "$($_.dir)|$($_.ts)|$($_.sent)|$($_.text)|$($_.img)|$($_.ready)|$($_.failed)" }) -join "`n"
    if ($sig -eq $script:lastSig) { return }
    $script:lastSig = $sig
    $rtb.Clear()
    $script:hits = @()
    foreach ($e in $log) {
        $when = (To-Local $e.ts).ToString('dd/MM HH:mm')
        $mine = ($e.dir -eq 'user')
        $who = if ($mine) { 'Tu' } elseif ($e.author) { [string]$e.author } else { 'Assistenza' }
        $rtb.SelectionStart = $rtb.TextLength
        $rtb.SelectionColor = if ($mine) { [System.Drawing.Color]::FromArgb(90, 90, 90) } else { [System.Drawing.Color]::FromArgb(37, 99, 235) }
        $rtb.SelectionFont = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
        $rtb.AppendText("$who  $when" + $(if ($mine -and -not $e.sent) { '  (invio...)' } else { '' }) + "`r`n")
        $rtb.SelectionStart = $rtb.TextLength
        $rtb.SelectionColor = [System.Drawing.Color]::Black
        $rtb.SelectionFont = New-Object System.Drawing.Font('Segoe UI', 10)
        if ($e.img) {
            $th = $null
            if ($e.ready) { $th = Get-ThumbRtf ([string]$e.img) }
            if ($th) {
                $rtb.SelectionStart = $rtb.TextLength
                $rtb.SelectedRtf = $th
                $rtb.SelectionStart = $rtb.TextLength
                $rtb.SelectionColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
                $rtb.SelectionFont = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Underline)
                $st0 = $rtb.TextLength
                $rtb.AppendText("  [ingrandisci]")
                $script:hits += @{ s = $st0; e = $rtb.TextLength; n = [string]$e.img }
                $rtb.SelectionStart = $rtb.TextLength
                $rtb.SelectionColor = [System.Drawing.Color]::Black
                $rtb.SelectionFont = New-Object System.Drawing.Font('Segoe UI', 10)
                $rtb.AppendText("`r`n")
            } else {
                $rtb.SelectionColor = [System.Drawing.Color]::Gray
                $rtb.AppendText($(if ($e.failed) { "(immagine non inviata)`r`n" } else { "(immagine in arrivo...)`r`n" }))
                $rtb.SelectionColor = [System.Drawing.Color]::Black
            }
        }
        if ($e.text) { $rtb.AppendText([string]$e.text + "`r`n") }
        $rtb.AppendText("`r`n")
    }
    if (@($log).Count -eq 0) {
        $rtb.SelectionColor = [System.Drawing.Color]::Gray
        $rtb.AppendText("Scrivi qui un messaggio per contattare l'assistenza. Per una richiesta formale spunta la casella 'Apri una richiesta di assistenza'.")
    }
    $rtb.SelectionStart = $rtb.TextLength
    $rtb.ScrollToCaret()
}

function Send-Message {
  try {
    $t = $inp.Text.Trim()
    if ($t -eq '') { return }
    $body = @{ text = $t }
    if ($chk.Checked) {
        $ti = $subj.Text.Trim()
        if ($ti -eq '') { [System.Windows.Forms.MessageBox]::Show("Scrivi l'oggetto della richiesta.", 'Assistenza') | Out-Null; return }
        $body = @{ text = $t; ticket = $true; title = $ti }
    }
    $r = Call-Agent '/send' $body
    if ($r) { $inp.Clear(); if ($chk.Checked) { $chk.Checked = $false; $subj.Clear() }; Poll $true } else { [System.Windows.Forms.MessageBox]::Show('Impossibile inviare il messaggio: riprova tra poco.', 'Assistenza') | Out-Null }
  } catch { }
}
$btn.Add_Click({ Send-Message })
$inp.Add_KeyDown({ param($s, $e)
    if ($e.KeyCode -eq 'Return' -and -not $e.Shift) { $e.SuppressKeyPress = $true; Send-Message }
    elseif ($e.Control -and $e.KeyCode -eq 'V' -and [System.Windows.Forms.Clipboard]::ContainsImage()) { $e.SuppressKeyPress = $true; Do-Paste }
})

# ---- icona e menu ----
$ni = New-Object System.Windows.Forms.NotifyIcon
$icoOn = New-TrayIcon $true
$icoOff = New-TrayIcon $false
$ni.Icon = $icoOff
$ni.Text = 'myrmm'
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$miHost = $menu.Items.Add('myrmm'); $miHost.Enabled = $false
$miVer = $menu.Items.Add('Agent'); $miVer.Enabled = $false
$miSt = $menu.Items.Add('Stato'); $miSt.Enabled = $false
[void]$menu.Items.Add('-')
$miChat = $menu.Items.Add("Contatta l'assistenza...")
$miShot = $menu.Items.Add("Invia uno screenshot...")
$ni.ContextMenuStrip = $menu
$ni.Visible = $true

function Show-Chat {
    if (-not $form.Visible) { $form.Show() }
    if ($form.WindowState -eq 'Minimized') { $form.WindowState = 'Normal' }
    $form.Activate()
    $inp.Focus() | Out-Null
    Poll $true
}
$miChat.Add_Click({ try { Show-Chat } catch { } })
$miShot.Add_Click({ try { Do-Screenshot } catch { } })
$ni.Add_DoubleClick({ try { Show-Chat } catch { } })
$ni.Add_BalloonTipClicked({ try { Show-Chat } catch { } })
$form.Add_FormClosing({ param($s, $e) $e.Cancel = $true; $form.Hide() })

function Poll([bool]$force) {
    try { Poll-Inner } catch { }
}

function Poll-Inner {
    $open = if ($form.Visible) { 1 } else { 0 }
    $q = "/state?open=$open&seen=$($script:lastSeen)"
    $st = Call-Agent $q $null
    if (-not $st) {
        if ($script:online -ne $false) { $script:online = $false; $ni.Icon = $icoOff; $ni.Text = 'myrmm - agent non raggiungibile' }
        return
    }
    $script:st = $st
    $ok = [bool]$st.online
    if ($script:online -ne $ok) {
        $script:online = $ok
        $ni.Icon = if ($ok) { $icoOn } else { $icoOff }
        $ni.Text = if ($ok) { 'myrmm - collegato' } else { 'myrmm - server non raggiungibile' }
    }
    $miHost.Text = 'myrmm - ' + $st.host
    $miVer.Text = 'Agent v' + $st.version
    $miSt.Text = if ($ok) { 'Collegato al server' } else { 'Server non raggiungibile' }
    $log = @($st.log | Where-Object { $_ })
    $maxOp = 0
    foreach ($e in $log) { if ($e.dir -eq 'op' -and [int]$e.srv_id -gt $maxOp) { $maxOp = [int]$e.srv_id } }
    if ($form.Visible) {
        $script:lastSeen = $maxOp
        Render $log
    } else {
        $newer = $log | Where-Object { $_.dir -eq 'op' -and [int]$_.srv_id -gt [Math]::Max([int]$st.read, $script:lastNotified) } | Select-Object -Last 1
        if ($newer) {
            $script:lastNotified = [int]$newer.srv_id
            $txt = [string]$newer.text
            if (-not $txt -and $newer.img) { $txt = 'Ti ha inviato un''immagine.' }
            if ($txt.Length -gt 120) { $txt = $txt.Substring(0, 120) + '...' }
            $ni.ShowBalloonTip(10000, 'Assistenza', $txt, [System.Windows.Forms.ToolTipIcon]::Info)
        }
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$timer.Add_Tick({
    $timer.Interval = if ($form.Visible) { 2000 } else { 5000 }
    Poll $false
})
$timer.Start()
Poll $false
[System.Windows.Forms.Application]::Run()
