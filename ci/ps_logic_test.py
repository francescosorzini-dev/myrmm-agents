#!/usr/bin/env python3
"""Prova la logica PowerShell dello script RustDesk con comandi finti (serve pwsh; senza, salta).
Estrae i blocchi da server/index.php: si prova il testo che viene davvero distribuito.
Verifica: Start-Service che solleva un errore terminante (l'errore visto in campo) non interrompe lo script,
URL e password hanno un valore predefinito quando le variabili sono vuote."""
import sys as _s
try: _s.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import os, re, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'server', 'index.php'), encoding='utf-8').read()
SHELLS = [x for x in ('powershell', 'pwsh') if shutil.which(x)]
if not SHELLS: print('pwsh non disponibile: salto'); sys.exit(0)
ok = bad = 0
def check(n, c, x=''):
    global ok, bad
    if c: ok += 1; print('  ok   ', n)
    else: bad += 1; print('  FALLITO', n, x)
pw = ''
def ps(code):
    f = os.path.join(tempfile.mkdtemp(), 't.ps1'); open(f, 'w', encoding='utf-8-sig').write(code)
    r = subprocess.run([pw, '-NoProfile', '-File', f], capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip()
for pw in SHELLS:
  print('== ' + pw)
  for var in ('rustdesk', 'rustdeskAsk'):
      m = re.search(r"\$%s = <<<'PS'\n(.*?)\nPS;" % var, SRC, re.S); assert m, var
      body = m.group(1)
      print('RustDesk Windows · ' + var)
      fn = re.search(r"^function Start-RDService.*?^}\n", body + '\n', re.S | re.M); assert fn, 'Start-RDService'
      # 1) Start-Service fallisce con errore terminante e sc.exe pure: la funzione non deve lanciare
      code = ("$ErrorActionPreference='Stop'\n$global:n=0\nfunction Start-Sleep { }\n"
              "function Get-Service { param($Name,$ErrorAction) [pscustomobject]@{Status='Stopped'} }\n"
              "function Start-Service { param($Name,$ErrorAction) $global:n++; throw 'Impossibile avviare il servizio RustDesk sul computer .' }\n"
              "function sc.exe { throw 'sc fallito' }\n" + fn.group(0) + "\nStart-RDService 'x.exe'\n'FINE n=' + $global:n\n")
      rc, o = ps(code); check('Start-Service terminante non interrompe lo script', rc == 0 and 'FINE n=12' in o, o)
      # 2) servizio assente e mai creato: nessuna eccezione
      code = ("$ErrorActionPreference='Stop'\nfunction Start-Sleep { }\nfunction Get-Service { $null }\n" + fn.group(0) + "\nStart-RDService ''\n'FINE'\n")
      rc, o = ps(code); check('servizio assente: nessuna eccezione', rc == 0 and 'FINE' in o, o)
      # 3) servizio già in esecuzione: ritorna subito
      code = ("$ErrorActionPreference='Stop'\nfunction Start-Sleep { }\nfunction Get-Service { [pscustomobject]@{Status='Running'} }\nfunction Start-Service { throw 'non deve essere chiamato' }\n" + fn.group(0) + "\nStart-RDService 'x.exe'\n'FINE'\n")
      rc, o = ps(code); check('servizio già attivo: nessuna azione', rc == 0 and 'FINE' in o, o)
      # 4) URL predefinito
      u = re.search(r"^\[Net\.ServicePointManager\].*?^if \(-not \$url\) \{ \$url = '[^']+' \}\n", body + '\n', re.S | re.M); assert u, 'blocco URL'
      code = ("$ErrorActionPreference='Stop'\n$url=''\nfunction Invoke-RestMethod { throw 'rete assente' }\n" + u.group(0) + "\n$url\n")
      rc, o = ps(code); check('URL vuoto e GitHub irraggiungibile: versione fissa', rc == 0 and re.search(r'^https://github\.com/rustdesk/rustdesk/releases/download/.+x86_64\.exe$', o, re.M) is not None, o)
      code = ("$ErrorActionPreference='Stop'\n$url=''\nfunction Invoke-RestMethod { [pscustomobject]@{assets=@([pscustomobject]@{name='rustdesk-9.9.9-x86_64.msi';browser_download_url='https://m'},[pscustomobject]@{name='rustdesk-9.9.9-x86_64.exe';browser_download_url='https://e/9.9.9.exe'})} }\n" + u.group(0) + "\n$url\n")
      rc, o = ps(code); check('URL vuoto: ultima release da GitHub (solo .exe x86_64)', rc == 0 and o.splitlines()[-1] == 'https://e/9.9.9.exe', o)
      code = ("$ErrorActionPreference='Stop'\n$url='https://mio/rd.exe'\nfunction Invoke-RestMethod { throw 'non deve essere chiamato' }\n" + u.group(0) + "\n$url\n")
      rc, o = ps(code); check('URL indicato dall\'utente: rispettato', rc == 0 and o.splitlines()[-1] == 'https://mio/rd.exe', o)
      if var == 'rustdesk':
          g = re.search(r"^if \(-not \$pw\) \{.*?^}\n", body + '\n', re.S | re.M); assert g, 'blocco password'
          code = "$ErrorActionPreference='Stop'\n$pw=''\n" + g.group(0) + "\n$pw\n"
          rc, o = ps(code); a = o.splitlines()[-1] if o else ''
          rc2, o2 = ps(code)
          check('password vuota: 20 caratteri alfanumerici casuali', rc == 0 and re.fullmatch(r'[A-Za-z0-9]{20}', a) is not None and a != (o2.splitlines()[-1] if o2 else ''), o)
          code = "$ErrorActionPreference='Stop'\n$pw='Mia-Pw_1'\n" + g.group(0) + "\n$pw\n"
          rc, o = ps(code); check('password indicata: invariata', rc == 0 and o == 'Mia-Pw_1', o)

# --- interprete cmd: il server incapsula il testo in uno script PowerShell che lo esegue con cmd.exe
import json as _j
fns = "\n".join(re.search(r"^function %s\(.*?^}\n" % n, SRC, re.S | re.M).group(0) if n == "win_wrap_cmd" else re.search(r"^function %s\([^\n]*\n" % n, SRC, re.M).group(0) for n in ("script_interp", "script_strip_interp", "script_set_interp", "win_wrap_cmd"))
tf = os.path.join(tempfile.mkdtemp(), "w.php")
open(tf, "w", encoding="utf-8").write("<?php\n" + fns + "\n$b = \"#!cmd\\r\\necho caff\\u00e8 \\\"x y\\\" & echo 'q'\\r\\nexit /b 7\\r\\n\";\n"
    "echo json_encode(['i' => script_interp($b), 'n' => script_interp(\"Get-Date\"), 's' => script_strip_interp($b), 'w' => win_wrap_cmd(script_strip_interp($b)), 'r' => script_set_interp(\"dir\", 'cmd'), 'p' => script_set_interp($b, 'ps')]);\n")
w = _j.loads(subprocess.run(["php", tf], capture_output=True, text=True, encoding="utf-8").stdout)
print('Interprete cmd')
check('riconosce #!cmd (anche con CRLF) e lo toglie', w['i'] == 'cmd' and w['n'] == 'default' and not w['s'].startswith('#!') and w['r'] == "#!cmd\ndir" and not w['p'].startswith('#!'), str(w)[:200])
for pw in SHELLS:
    f = os.path.join(tempfile.mkdtemp(), 'w.ps1'); open(f, 'w', encoding='utf-8-sig').write(w['w'])
    rc, o = ps("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e); if($e){$e|%%{$_.Message}; exit 1}else{'ok'}" % f)
    check('lo script generato è PowerShell valido (' + pw + ')', rc == 0 and o.endswith('ok'), o)
    if os.name == 'nt':
        r = subprocess.run([pw, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', f], capture_output=True, text=True, encoding='cp850', errors='replace', timeout=60)
        check('su Windows: cmd.exe esegue il testo, restituisce uscita e codice 7 (' + pw + ')', r.returncode == 7 and 'caff' in r.stdout and 'x y' in r.stdout and "'q'" in r.stdout, str(r.returncode) + r.stdout + r.stderr)
        check('su Windows: il file temporaneo viene rimosso', not [x for x in os.listdir(os.environ.get('TEMP', '.')) if x.startswith('myrmm-') and x.endswith('.cmd')], '')
print('%d ok, %d falliti' % (ok, bad)); sys.exit(1 if bad else 0)
