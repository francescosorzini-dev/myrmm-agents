"""Scenari per provare, su un sistema vero (runner GitHub: Linux, macOS, Windows), gli script di libreria che MODIFICANO qualcosa.
Ogni scenario è una sequenza di passi: {"run": nome-script, "vars": {...}, "rc": 0, "has": [...], "hasnot": [...]} esegue lo script come lo esegue l'agent;
{"code": "...", "rc": 0} esegue codice nativo (PowerShell su Windows, sh su Linux/macOS) per preparare lo stato o verificarlo (esce con 0 se va bene).
{"cleanup": "..."} gira sempre, alla fine. I runner sono macchine usa e getta, ma gli scenari rimettono comunque a posto ciò che toccano.
Esportati da ci/export_apply.py (che sostituisce i segnaposto come il server) ed eseguiti da ci/library_apply.py."""

W = "windows"; U = "unix"
P = "C:\\myrmm-prova"
def chk(cond, msg): return "if (-not (%s)) { Write-Output 'VERIFICA FALLITA: %s'; exit 1 }" % (cond, msg.replace("'", "''"))

SCENARI = []
def sc(nome, os_, *passi, cleanup=None, only=None):
    SCENARI.append(dict(nome=nome, os=os_, passi=list(passi), cleanup=cleanup, only=only))

# ------------------------------------------------------------------ Windows
sc("Windows: robocopy (anteprima, copia, specchio)", W,
   {"code": f"Remove-Item '{P}' -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory '{P}\\orig\\sub' -Force | Out-Null; 'a' | Set-Content '{P}\\orig\\a.txt'; 'b' | Set-Content '{P}\\orig\\sub\\b.txt'"},
   {"run": "Windows: copia o sincronizza una cartella con robocopy", "vars": {"ORIGINE": P + "\\orig", "DESTINAZIONE": P + "\\dest"}, "rc": 0, "has": ["anteprima"]},
   {"code": chk(f"-not (Test-Path '{P}\\dest\\a.txt')", "l'anteprima non deve copiare")},
   {"run": "Windows: copia o sincronizza una cartella con robocopy", "vars": {"ORIGINE": P + "\\orig", "DESTINAZIONE": P + "\\dest", "APPLICA": "si"}, "rc": 0, "has": ["ESEGUITA"]},
   {"code": chk(f"(Test-Path '{P}\\dest\\a.txt') -and (Test-Path '{P}\\dest\\sub\\b.txt')", "file copiati")},
   {"code": f"'z' | Set-Content '{P}\\dest\\stray.txt'"},
   {"run": "Windows: copia o sincronizza una cartella con robocopy", "vars": {"ORIGINE": P + "\\orig", "DESTINAZIONE": P + "\\dest", "MIRROR": "si"}, "rc": 0, "has": ["specchio"]},
   {"code": chk(f"Test-Path '{P}\\dest\\stray.txt'", "lo specchio in anteprima non deve eliminare")},
   {"run": "Windows: copia o sincronizza una cartella con robocopy", "vars": {"ORIGINE": P + "\\orig", "DESTINAZIONE": P + "\\dest", "MIRROR": "si", "APPLICA": "si"}, "rc": 0},
   {"code": chk(f"(-not (Test-Path '{P}\\dest\\stray.txt')) -and (Test-Path '{P}\\dest\\a.txt')", "specchio: il file in più va eliminato, gli altri restano")},
   {"code": f"New-Item -ItemType Directory '{P}\\zip' -Force | Out-Null"},
   {"run": "Windows: comprimi una cartella in un file ZIP", "vars": {"ORIGINE": P + "\\orig", "DESTINAZIONE": P + "\\zip"}, "rc": 0, "has": ["Creato"]},
   {"code": "Add-Type -AssemblyName System.IO.Compression.FileSystem; $z = @(Get-ChildItem '" + P + "\\zip\\*.zip'); " + chk("$z.Count -eq 1", "uno zip") + "; $a = [IO.Compression.ZipFile]::OpenRead($z[0].FullName); $n = $a.Entries.Count; $a.Dispose(); " + chk("$n -ge 2", "lo zip contiene i file")},
   cleanup=f"Remove-Item '{P}' -Recurse -Force -ErrorAction SilentlyContinue")

sc("Windows: eliminazione file vecchi", W,
   {"code": f"Remove-Item '{P}' -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory '{P}\\v' -Force | Out-Null; foreach ($n in 'a.log','b.log','c.txt') {{ 'x' | Set-Content \"{P}\\v\\$n\"; (Get-Item \"{P}\\v\\$n\").LastWriteTime = (Get-Date).AddDays(-90) }}; 'x' | Set-Content '{P}\\v\\nuovo.log'"},
   {"run": "Windows: elimina file vecchi in una cartella", "vars": {"PERCORSO": P + "\\v", "GIORNI": "30", "FILTRO": "*.log"}, "rc": 0, "has": ["nteprima"]},
   {"code": chk(f"@(Get-ChildItem '{P}\\v').Count -eq 4", "l'anteprima non deve eliminare")},
   {"run": "Windows: elimina file vecchi in una cartella", "vars": {"PERCORSO": P + "\\v", "GIORNI": "30", "FILTRO": "*.log", "APPLICA": "si"}, "rc": 0},
   {"code": chk(f"(-not (Test-Path '{P}\\v\\a.log')) -and (-not (Test-Path '{P}\\v\\b.log')) -and (Test-Path '{P}\\v\\c.txt') -and (Test-Path '{P}\\v\\nuovo.log')", "eliminati solo i .log vecchi")},
   {"run": "Windows: elimina file vecchi in una cartella", "vars": {"PERCORSO": "C:\\Windows", "APPLICA": "si"}, "rc": 2},
   cleanup=f"Remove-Item '{P}' -Recurse -Force -ErrorAction SilentlyContinue")

K = "SOFTWARE\\Policies\\MyrmmProva"; HK = "HKLM:\\" + K
sc("Windows: registro HKLM", W,
   {"code": f"Remove-Item '{HK}' -Recurse -Force -ErrorAction SilentlyContinue"},
   {"run": "Windows: imposta o elimina un valore del registro (HKLM)", "vars": {"CHIAVE": K, "NOME": "Prova", "VALORE": "7"}, "rc": 0, "has": ["Anteprima"]},
   {"code": chk(f"-not (Test-Path '{HK}')", "l'anteprima non deve creare la chiave")},
   {"run": "Windows: imposta o elimina un valore del registro (HKLM)", "vars": {"CHIAVE": K, "NOME": "Prova", "VALORE": "7", "APPLICA": "si"}, "rc": 0, "has": ["Impostato DWord = 7"]},
   {"code": f"$v = Get-ItemProperty '{HK}' -Name Prova; " + chk("$v.Prova -eq 7", "valore 7") + f"; " + chk(f"(Get-Item '{HK}').GetValueKind('Prova') -eq 'DWord'", "tipo DWord")},
   {"run": "Windows: imposta o elimina un valore del registro (HKLM)", "vars": {"CHIAVE": K, "NOME": "Testo", "VALORE": "ciao è l'ora", "TIPO": "String", "APPLICA": "si"}, "rc": 0},
   {"code": chk(f"(Get-ItemProperty '{HK}').Testo -eq \"ciao è l'ora\"", "stringa con apice e accento")},
   {"run": "Windows: imposta o elimina un valore del registro (HKLM)", "vars": {"CHIAVE": K, "NOME": "Prova", "AZIONE": "elimina", "APPLICA": "si"}, "rc": 0, "has": ["eliminato"]},
   {"code": chk(f"$null -eq (Get-ItemProperty '{HK}' -ErrorAction SilentlyContinue).Prova", "valore eliminato")},
   {"run": "Windows: imposta o elimina un valore del registro (HKLM)", "vars": {"CHIAVE": "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "NOME": "X", "VALORE": "1", "APPLICA": "si"}, "rc": 2},
   cleanup=f"Remove-Item '{HK}' -Recurse -Force -ErrorAction SilentlyContinue")

sc("Windows: variabile d'ambiente di sistema", W,
   {"code": "[Environment]::SetEnvironmentVariable('MYRMM_PROVA', $null, 'Machine')"},
   {"run": "Windows: imposta o elimina una variabile d'ambiente di sistema", "vars": {"NOME": "MYRMM_PROVA", "VALORE": "ciao; mondo"}, "rc": 0, "has": ["Impostata MYRMM_PROVA"]},
   {"code": chk("[Environment]::GetEnvironmentVariable('MYRMM_PROVA', 'Machine') -ceq 'ciao; mondo'", "variabile impostata")},
   {"run": "Windows: imposta o elimina una variabile d'ambiente di sistema", "vars": {"NOME": "MYRMM_PROVA", "AZIONE": "elimina"}, "rc": 0, "has": ["Eliminata"]},
   {"code": chk("$null -eq [Environment]::GetEnvironmentVariable('MYRMM_PROVA', 'Machine')", "variabile eliminata")},
   {"run": "Windows: imposta o elimina una variabile d'ambiente di sistema", "vars": {"NOME": "Path", "VALORE": "x"}, "rc": 2},
   cleanup="[Environment]::SetEnvironmentVariable('MYRMM_PROVA', $null, 'Machine')")

sc("Windows: regola firewall in ingresso", W,
   {"code": "Remove-NetFirewallRule -DisplayName 'myrmm-prova' -ErrorAction SilentlyContinue"},
   {"run": "Windows: apri o chiudi una porta in ingresso nel firewall", "vars": {"NOME": "prova", "PORTA": "54321", "REMOTI": "203.0.113.0/24"}, "rc": 0, "has": ["creata"]},
   {"code": "$r = Get-NetFirewallRule -DisplayName 'myrmm-prova'; " + chk("$r.Direction -eq 'Inbound' -and $r.Action -eq 'Allow' -and $r.Enabled -eq 'True'", "regola in ingresso, consenti, attiva") + "; $p = $r | Get-NetFirewallPortFilter; " + chk("$p.LocalPort -eq '54321' -and $p.Protocol -eq 'TCP'", "porta 54321 TCP") + "; $a = $r | Get-NetFirewallAddressFilter; " + chk("'203.0.113.0/255.255.255.0' -in @($a.RemoteAddress)", "indirizzi remoti")},
   {"run": "Windows: apri o chiudi una porta in ingresso nel firewall", "vars": {"NOME": "prova", "PORTA": "54321"}, "rc": 0, "has": ["esiste già"]},
   {"run": "Windows: apri o chiudi una porta in ingresso nel firewall", "vars": {"NOME": "prova", "AZIONE": "rimuovi"}, "rc": 0, "has": ["Rimosse 1"]},
   {"code": chk("@(Get-NetFirewallRule -DisplayName 'myrmm-prova' -ErrorAction SilentlyContinue).Count -eq 0", "regola rimossa")},
   cleanup="Remove-NetFirewallRule -DisplayName 'myrmm-prova' -ErrorAction SilentlyContinue")

sc("Windows: tipo di avvio di un servizio", W,
   {"code": "$global:orig = (Get-Service RemoteRegistry).StartType; Write-Output \"RemoteRegistry era: $global:orig\""},
   {"run": "Windows: cambia il tipo di avvio di un servizio", "vars": {"SERVIZIO": "RemoteRegistry", "TIPO": "manuale"}, "rc": 0, "has": ["Manual"]},
   {"code": chk("(Get-Service RemoteRegistry).StartType -eq 'Manual'", "avvio manuale")},
   {"run": "Windows: cambia il tipo di avvio di un servizio", "vars": {"SERVIZIO": "RemoteRegistry", "TIPO": "disattivato"}, "rc": 0},
   {"code": chk("(Get-Service RemoteRegistry).StartType -eq 'Disabled'", "avvio disattivato")},
   {"run": "Windows: cambia il tipo di avvio di un servizio", "vars": {"SERVIZIO": "WinDefend", "TIPO": "disattivato"}, "rc": 2},
   {"run": "Windows: cambia il tipo di avvio di un servizio", "vars": {"SERVIZIO": "Inesistente123", "TIPO": "manuale"}, "rc": 2},
   cleanup="Set-Service RemoteRegistry -StartupType Disabled -ErrorAction SilentlyContinue")

sc("Windows: termina un processo", W,
   {"code": "Get-Process ping -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Process -FilePath ping.exe -ArgumentList '-t','127.0.0.1' -WindowStyle Hidden; Start-Sleep 2; " + chk("@(Get-Process ping -ErrorAction SilentlyContinue).Count -ge 1", "ping avviato")},
   {"run": "Windows: termina un processo per nome", "vars": {"NOME": "ping"}, "rc": 0, "has": ["Anteprima"]},
   {"code": chk("@(Get-Process ping -ErrorAction SilentlyContinue).Count -ge 1", "l'anteprima non deve terminare")},
   {"run": "Windows: termina un processo per nome", "vars": {"NOME": "ping.exe", "APPLICA": "si"}, "rc": 0, "has": ["Terminati"]},
   {"code": "Start-Sleep 1; " + chk("@(Get-Process ping -ErrorAction SilentlyContinue).Count -eq 0", "ping terminato")},
   {"run": "Windows: termina un processo per nome", "vars": {"NOME": "lsass", "APPLICA": "si"}, "rc": 2},
   cleanup="Get-Process ping -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")

sc("Windows: utenti locali, gruppi e offboarding", W,
   {"code": "Remove-LocalUser -Name myrmmprova -ErrorAction SilentlyContinue; New-LocalUser -Name myrmmprova -Password (ConvertTo-SecureString 'Xy9!longPass-2026' -AsPlainText -Force) -AccountNeverExpires | Out-Null; " + chk("$null -ne (Get-LocalUser myrmmprova)", "utente creato")},
   {"run": "Windows: aggiungi o rimuovi un utente da un gruppo locale", "vars": {"UTENTE": "myrmmprova", "GRUPPO": "Remote Desktop Users"}, "rc": 0, "has": ["aggiunto"]},
   {"code": chk("@(Get-LocalGroupMember -Group 'Remote Desktop Users' | Where-Object { $_.Name -like '*\\myrmmprova' }).Count -eq 1", "membro del gruppo")},
   {"run": "Windows: aggiungi o rimuovi un utente da un gruppo locale", "vars": {"UTENTE": "myrmmprova", "GRUPPO": "Remote Desktop Users"}, "rc": 0, "has": ["già membro"]},
   {"run": "Windows: aggiungi o rimuovi un utente da un gruppo locale", "vars": {"UTENTE": "myrmmprova", "GRUPPO": "Remote Desktop Users", "AZIONE": "rimuovi"}, "rc": 0, "has": ["rimosso"]},
   {"code": chk("@(Get-LocalGroupMember -Group 'Remote Desktop Users' | Where-Object { $_.Name -like '*\\myrmmprova' }).Count -eq 0", "non più membro")},
   {"run": "Windows: aggiungi o rimuovi un utente da un gruppo locale", "vars": {"UTENTE": "Administrator", "GRUPPO": "Administrators", "AZIONE": "rimuovi"}, "rc": 2},
   {"code": "Add-LocalGroupMember -Group 'Remote Desktop Users' -Member myrmmprova"},
   {"run": "Windows: offboarding di un account locale", "vars": {"UTENTE": "myrmmprova"}, "rc": 0, "has": ["disabilitato"]},
   {"code": chk("-not (Get-LocalUser myrmmprova).Enabled", "account disabilitato") + "; " + chk("@(Get-LocalGroupMember -Group 'Remote Desktop Users' | Where-Object { $_.Name -like '*\\myrmmprova' }).Count -eq 0", "tolto dai gruppi")},
   {"run": "Windows: offboarding di un account locale", "vars": {"UTENTE": "Administrator"}, "rc": 2},
   cleanup="Remove-LocalUser -Name myrmmprova -ErrorAction SilentlyContinue")

sc("Windows: file hosts", W,
   {"run": "Windows: aggiungi o rimuovi una voce nel file hosts", "vars": {"NOME": "myrmm-prova.lan", "IP": "203.0.113.5"}, "rc": 0, "has": ["Aggiunta"]},
   {"code": chk("(Get-Content \"$env:SystemRoot\\System32\\drivers\\etc\\hosts\") -match '^203\\.0\\.113\\.5\\s+myrmm-prova\\.lan$'", "voce presente") + "; " + chk("Test-Path \"$env:SystemRoot\\System32\\drivers\\etc\\hosts.myrmm.bak\"", "copia di sicurezza")},
   {"run": "Windows: aggiungi o rimuovi una voce nel file hosts", "vars": {"NOME": "myrmm-prova.lan", "IP": "203.0.113.6"}, "rc": 0},
   {"code": chk("@((Get-Content \"$env:SystemRoot\\System32\\drivers\\etc\\hosts\") -match 'myrmm-prova\\.lan').Count -eq 1", "una sola voce dopo la modifica")},
   {"run": "Windows: aggiungi o rimuovi una voce nel file hosts", "vars": {"NOME": "myrmm-prova.lan", "AZIONE": "rimuovi"}, "rc": 0, "has": ["Rimossa"]},
   {"code": chk("@((Get-Content \"$env:SystemRoot\\System32\\drivers\\etc\\hosts\") -match 'myrmm-prova\\.lan').Count -eq 0", "voce rimossa")},
   cleanup="$f = \"$env:SystemRoot\\System32\\drivers\\etc\\hosts\"; (Get-Content $f) | Where-Object { $_ -notmatch 'myrmm-prova' } | Set-Content $f -Encoding ASCII")

# ------------------------------------------------------------------ Linux e macOS
T = "/tmp/myrmm-prova"
sc("Linux/macOS: eliminazione file vecchi", U,
   {"code": f"rm -rf {T}; mkdir -p {T}/v; for n in a.log b.log c.txt; do echo x > {T}/v/$n; touch -t 202001010000 {T}/v/$n; done; echo x > {T}/v/nuovo.log"},
   {"run": "Linux/macOS: elimina file vecchi in una cartella", "vars": {"PERCORSO": T + "/v", "GIORNI": "30", "FILTRO": "*.log"}, "rc": 0, "has": ["Anteprima", ": 2,"]},
   {"code": f"[ \"$(ls {T}/v | wc -l | tr -d ' ')\" = 4 ]"},
   {"run": "Linux/macOS: elimina file vecchi in una cartella", "vars": {"PERCORSO": T + "/v", "GIORNI": "30", "FILTRO": "*.log", "APPLICA": "si"}, "rc": 0, "has": ["Eliminati 2 file"]},
   {"code": f"[ ! -e {T}/v/a.log ] && [ ! -e {T}/v/b.log ] && [ -e {T}/v/c.txt ] && [ -e {T}/v/nuovo.log ]"},
   {"run": "Linux/macOS: elimina file vecchi in una cartella", "vars": {"PERCORSO": "/etc", "APPLICA": "si"}, "rc": 2},
   {"run": "Linux/macOS: elimina file vecchi in una cartella", "vars": {"PERCORSO": "/tmp/../etc", "APPLICA": "si"}, "rc": 2},
   cleanup=f"rm -rf {T}")

sc("Linux/macOS: archivia una cartella", U,
   {"code": f"rm -rf {T}; mkdir -p {T}/src/sub {T}/out; echo a > {T}/src/a.txt; echo b > {T}/src/sub/b.txt"},
   {"run": "Linux/macOS: archivia una cartella in un file tar.gz", "vars": {"SORGENTE": T + "/src", "DESTINAZIONE": T + "/out"}, "rc": 0, "has": ["Creato", "4 voci"]},
   {"code": f"set -- {T}/out/src-*.tar.gz; [ -f \"$1\" ] && tar -tzf \"$1\" | grep -q 'src/sub/b.txt'"},
   {"run": "Linux/macOS: archivia una cartella in un file tar.gz", "vars": {"SORGENTE": T + "/src", "DESTINAZIONE": T + "/src/dentro"}, "rc": 2},
   cleanup=f"rm -rf {T}")

sc("Linux: blocca e sblocca un account", U,
   {"code": "id myrmmprova >/dev/null 2>&1 && userdel -r myrmmprova; useradd -m myrmmprova && echo 'myrmmprova:Xy9!longPass-2026' | chpasswd && [ \"$(passwd -S myrmmprova | awk '{print $2}')\" = P ]"},
   {"run": "Linux: blocca o sblocca un account utente", "vars": {"UTENTE": "myrmmprova"}, "rc": 0},
   {"code": "[ \"$(passwd -S myrmmprova | awk '{print $2}')\" = L ]"},
   {"run": "Linux: blocca o sblocca un account utente", "vars": {"UTENTE": "myrmmprova", "AZIONE": "sblocca"}, "rc": 0},
   {"code": "[ \"$(passwd -S myrmmprova | awk '{print $2}')\" = P ]"},
   {"run": "Linux: blocca o sblocca un account utente", "vars": {"UTENTE": "root"}, "rc": 2},
   cleanup="userdel -r myrmmprova 2>/dev/null; true", only="linux")

sc("macOS: rimuovi la quarantena", U,
   {"code": f"rm -rf {T}; mkdir -p {T}/App.app; echo x > {T}/App.app/f; xattr -w com.apple.quarantine '0083;5f5e1000;Safari;' {T}/App.app; xattr -p com.apple.quarantine {T}/App.app >/dev/null"},
   {"run": "macOS: rimuovi l'attributo di quarantena da un'app o cartella", "vars": {"PERCORSO": T + "/App.app"}, "rc": 0},
   {"code": f"! xattr -p com.apple.quarantine {T}/App.app >/dev/null 2>&1"},
   cleanup=f"rm -rf {T}", only="macos")

sc("macOS: svuota la cache DNS", U,
   {"run": "macOS: svuota la cache DNS", "vars": {}, "rc": 0},
   only="macos")
