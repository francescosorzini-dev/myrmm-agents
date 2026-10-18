#!/usr/bin/env python3
"""Prova su un VERO Windows (Windows PowerShell 5.1, da amministratore) gli script di libreria «myrmm MCP: installa/rimuovi su Windows».
Gli script sono quelli esportati da server/index.php (ci/fixtures/, vedi ci/export_install_scripts.py) e girano come li fa l'agent:
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand <script in UTF-16>.
Il server è finto (ci/fake_myrmm.py) e serve l'eseguibile compilato dal workflow. Per usare http (la prova è locale) la sola modifica allo script
è «^https://» → «^https?://».
Uso (su Windows): python ci/windows_install_test.py PERCORSO\\myrmm-mcp.exe        Altrove: salta."""
import base64, hashlib, json, os, re, subprocess, sys, time
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
if os.name != "nt": print("Windows richiesto: salto"); sys.exit(0)
import fake_myrmm

EXE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else sys.exit("uso: windows_install_test.py PERCORSO\\myrmm-mcp.exe")
TOK = "myrmm_" + "0123456789abcdef" * 3
DIR = os.path.join(os.environ["ProgramFiles"], "myrmm-mcp"); INST = os.path.join(DIR, "myrmm-mcp.exe"); CFG = os.path.join(DIR, "myrmm-mcp.json")
ok = bad = 0
def rec(n, c, x=""):
    global ok, bad
    if c: ok += 1; print("  ok   ", n)
    else:
        bad += 1; print("  FALLITO", n, str(x)[:900]); print("::error title=%s::%s" % (n, str(x)[:900].replace("\r", " ").replace("\n", "%0A")))
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def mat(name, vals):
    body = open(os.path.join(HERE, "fixtures", name), encoding="utf-8").read()
    def sub(m):   # come il server: {{NOME|linea}} toglie gli a capo
        v = vals.get(m.group(1), "")
        return re.sub(r"\r\n|\r|\n", " ", v) if m.group(2) else v
    body = re.sub(r"\{\{\s*([A-Za-z_]\w*)\s*(\|\s*linea\s*)?\}\}", sub, body)
    return body.replace("^https://", "^https?://")
def run(script, timeout=240):
    enc = base64.b64encode(("$ProgressPreference='SilentlyContinue'; " + script).encode("utf-16-le")).decode()
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", enc],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr).strip()

psv = run("$PSVersionTable.PSVersion.ToString() + ' ' + $PSVersionTable.PSEdition")[1]
print("PowerShell di prova: " + psv)
rec("la prova gira su Windows PowerShell 5.1 (Desktop)", psv.startswith("5.1") and "Desktop" in psv, psv)
rec("l'eseguibile da installare esiste", os.path.isfile(EXE), EXE)
SRCSHA = sha(EXE)
srv = fake_myrmm.start(EXE, TOK)
INSTALL = lambda vals=None: run(mat("mcp-install-windows.ps1", dict({"MCP_TOKEN": TOK, "MCP_URL": srv.url}, **(vals or {}))))
try:
    if os.path.isdir(DIR): run("Remove-Item '%s' -Recurse -Force" % DIR)

    print("== installazione")
    rc, out = INSTALL()
    rec("installazione: esito 0", rc == 0, "rc=%s\n%s" % (rc, out))
    rec("l'eseguibile installato è quello pubblicato (stesso hash)", os.path.isfile(INST) and sha(INST) == SRCSHA, out)
    rec("verifica del token riuscita", "Collegamento verificato" in out and "Server MCP installato: myrmm-mcp " in out, out)
    cfgb = open(CFG, "rb").read() if os.path.isfile(CFG) else b""
    rec("configurazione: UTF-8 senza BOM, con url e token", cfgb[:3] != b"\xef\xbb\xbf" and json.loads(cfgb or b"{}") == {"url": srv.url, "token": TOK}, cfgb[:120])
    acl = run("icacls.exe '%s'; icacls.exe '%s'" % (CFG, DIR))[1]
    rec("permessi: la configurazione non è leggibile da Users/Everyone", not re.search(r"\\Users|Everyone|Authenticated Users", acl.split(DIR)[0]) and "SYSTEM" in acl and "Administrators" in acl, acl)
    rec("niente file di appoggio rimasti (.new)", not os.path.exists(INST + ".new"), os.listdir(DIR))
    r = subprocess.run([INST, "--version"], capture_output=True, text=True); rec("l'eseguibile parte: --version", r.returncode == 0 and r.stdout.startswith("myrmm-mcp "), r.stdout + r.stderr)
    r = subprocess.run([INST, "--check"], capture_output=True, text=True, encoding="utf-8", errors="replace"); rec("--check con la configurazione scritta dallo script", r.returncode == 0 and "Collegamento verificato" in r.stdout, r.stdout + r.stderr)

    print("== sostituzione con l'eseguibile in uso")
    p = subprocess.Popen([INST], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE); time.sleep(1.5)
    rec("l'assistente è in esecuzione", p.poll() is None, p.poll())
    rc, out = INSTALL()
    rec("reinstallazione mentre l'eseguibile è in uso: esito 0 (Windows rinomina un .exe in esecuzione)", rc == 0 and os.path.isfile(INST) and sha(INST) == SRCSHA, "rc=%s\n%s" % (rc, out))
    p.kill(); p.wait()

    print("== errori")
    before = sha(INST)
    srv.mode = "badhash"; rc, out = INSTALL()
    rec("hash diverso da quello pubblicato: esito 4, nessuna installazione", rc == 4 and "non corrisponde" in out and sha(INST) == before and not os.path.exists(INST + ".new"), "rc=%s\n%s" % (rc, out))
    srv.mode = "denied"; rc, out = INSTALL()
    rec("server che rifiuta il token: esito 4", rc == 4 and "Scarico del server MCP non riuscito" in out and not os.path.exists(INST + ".new"), "rc=%s\n%s" % (rc, out))
    srv.mode = "ok"
    n0 = len(srv.hits); rc, out = INSTALL({"MCP_TOKEN": "myrmm_zz"})
    rec("token con formato sbagliato: esito 2, nessuna richiesta al server", rc == 2 and "MCP_TOKEN" in out and len(srv.hits) == n0, "rc=%s\n%s" % (rc, out))
    rc, out = INSTALL({"MCP_URL": "https://x'y"})
    rec("indirizzo con apice: esito 2", rc == 2 and "MCP_URL" in out, "rc=%s\n%s" % (rc, out))
    rc, out = INSTALL({"MCP_TOKEN": TOK + "'@\nWrite-Output PWNED"})
    rec("token con un tentativo di uscire dalla here-string: respinto, nulla eseguito", rc == 2 and "PWNED" not in out, "rc=%s\n%s" % (rc, out))

    print("== rimozione")
    rc, out = run(mat("mcp-remove-windows.ps1", {}))
    rec("rimozione: esito 0, cartella e token spariti", rc == 0 and "Rimosso" in out and not os.path.exists(DIR), "rc=%s\n%s" % (rc, out))
    rc, out = run(mat("mcp-remove-windows.ps1", {}))
    rec("seconda rimozione: «Non era installato.»", rc == 0 and "Non era installato." in out, out)
finally:
    srv.stop()
    try: run("Get-Process myrmm-mcp -ErrorAction SilentlyContinue | Stop-Process -Force; Remove-Item '%s' -Recurse -Force -ErrorAction SilentlyContinue" % DIR)
    except Exception: pass

print("\n%d ok, %d falliti" % (ok, bad)); sys.exit(1 if bad else 0)
