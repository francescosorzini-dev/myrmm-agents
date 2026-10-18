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

function Call-Agent([string]$path, $body) {
    if (-not $script:base) { $script:base = Get-Base }
    if (-not $script:base) { return $null }
    $h = @{ 'X-Myrmm-Tray' = '1' }
    try {
        if ($null -ne $body) {
            $json = $body | ConvertTo-Json -Compress
            return Invoke-RestMethod -Uri ($script:base + $path) -Method Post -Headers $h -TimeoutSec 5 -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) -UseBasicParsing
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
[void]$tbl.RowStyles.Add((New-Object System.Windows.Forms.RowStyle('Absolute', 112)))
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

$subj = New-Object System.Windows.Forms.TextBox
$subj.Dock = 'Top'; $subj.MaxLength = 140; $subj.Visible = $false
$bottom.Controls.Add($subj)
$chk = New-Object System.Windows.Forms.CheckBox
$chk.Text = 'Apri una richiesta di assistenza (ticket)'; $chk.Dock = 'Top'; $chk.Height = 24; $chk.AutoSize = $false
$bottom.Controls.Add($chk)
$chk.Add_CheckedChanged({
    $subj.Visible = $chk.Checked
    $tbl.RowStyles[1].Height = $(if ($chk.Checked) { 140 } else { 112 })
    if ($chk.Checked) { $subj.Focus() | Out-Null }
})

$inp = New-Object System.Windows.Forms.TextBox
$inp.Multiline = $true; $inp.Dock = 'Fill'; $inp.AcceptsReturn = $false; $inp.MaxLength = 2000
$bottom.Controls.Add($inp)
$inp.BringToFront()

function Render($log) {
    $log = @($log | Where-Object { $_ })
    $sig = ($log | ForEach-Object { "$($_.dir)|$($_.ts)|$($_.sent)|$($_.text)" }) -join "`n"
    if ($sig -eq $script:lastSig) { return }
    $script:lastSig = $sig
    $rtb.Clear()
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
        $rtb.AppendText([string]$e.text + "`r`n`r`n")
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
$inp.Add_KeyDown({ param($s, $e) if ($e.KeyCode -eq 'Return' -and -not $e.Shift) { $e.SuppressKeyPress = $true; Send-Message } })

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
