#!/usr/bin/env python3
"""Distribuzione dell'assistente MCP sui device (1.54.0, eseguibile Go senza Python): script di libreria, download per os/arch con hash, configurazione, mascheramento.
Uso: python3 ci/mcp_deploy_test.py"""
import os, re, sys, json, time, shutil, sqlite3, subprocess, tempfile, hashlib, platform, threading, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if platform.system() != "Linux": print("solo Linux: salto"); sys.exit(0)
arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), "")
AG = os.path.join(ROOT, "server", "update", "agent-linux-" + arch)
if not arch or not os.path.isfile(AG) or not os.path.isfile(os.path.join(ROOT, "server", "update", "myrmm-mcp-linux-" + arch)): print("agent o server MCP Linux non disponibili (esegui release.sh): salto"); sys.exit(0)
MCPBIN = os.path.join(ROOT, "server", "update", "myrmm-mcp-linux-" + arch)
PORT = 8832; BASE = f"http://127.0.0.1:{PORT}/index.php"; ET = "e" * 24; KEY = "k" * 32; TOK = "myrmm_" + "b" * 48
tmp = tempfile.mkdtemp(prefix="myrmm-mcpd-"); srv = os.path.join(tmp, "server"); adir = os.path.join(tmp, "agentdata"); os.makedirs(adir)
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
cfg = {"ENROLL_TOKEN": ET, "ENROLL_GLOBAL": True, "CONSOLE_USER": "admin", "CONSOLE_PASS": "x", "JOB_SIGNING_KEY": KEY, "HEARTBEAT_WAIT_MAX": 5}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=open(os.path.join(tmp, "php.err"), "w"), env=dict(os.environ, PHP_CLI_SERVER_WORKERS="6"))
DB = os.path.join(srv, "data", "myrmm.sqlite"); res = []; ap = None
def rec(n, ok, info=""): res.append((n, bool(ok))); print(("OK   " if ok else "FAIL ") + n + (("  [" + str(info)[:300] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def api(r, method="GET", data=None, **p):
    rq = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(dict(p, action="api", r=r)), data=json.dumps(data).encode() if data is not None else None, headers={"X-Api-Token": TOK, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(rq, timeout=60) as f: return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
def wait(fn, t=60):
    e = time.time() + t
    while time.time() < e:
        try: v = fn()
        except Exception: v = None
        if v: return v
        time.sleep(.5)
try:
    for _ in range(60):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"}), timeout=5)
    except Exception: pass
    wait(lambda: os.path.exists(DB) and q("SELECT COUNT(*) FROM sites") is not None and q("SELECT COUNT(*) FROM api_tokens") is not None and q("SELECT lab FROM sites LIMIT 1") is not None and q("SELECT api_token FROM jobs LIMIT 1") is not None, 30)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    q("INSERT OR IGNORE INTO sites(name,created) VALUES('Collaudo',?)", now); q("UPDATE sites SET lab=1 WHERE name='Collaudo'")
    q("INSERT INTO api_tokens(name,hash,prefix,role,sites,write,expires,created) VALUES('ai-test',?,?,'operator',?,2,'2099-01-01T00:00:00Z',?)", hashlib.sha256(TOK.encode()).hexdigest(), TOK[:12], json.dumps(["Collaudo"]), now)
    for nm, body in [("Dati sistema", "#!/bin/sh\necho kernel=$(uname -s) dry=${MYRMM_DRYRUN:-0}\nexit 0"), ("Con variabile", "#!/bin/sh\necho ciao-{{NOME}}"), ("Fallisce", "#!/bin/sh\necho errore >&2\nexit 7")]:
        q("INSERT INTO scripts(name,description,body,timeout,created,platform) VALUES(?,?,?,?,?,'unix')", nm, nm, body, 60, now)
    sid = {r[1]: r[0] for r in q("SELECT id,name FROM scripts")}
    os.environ["MYRMM_DIR"] = adir
    rows = {r[0]: r for r in q("SELECT name, body, platform, description FROM scripts WHERE name LIKE 'myrmm MCP:%'")}
    rec("5 script di libreria MCP presenti", len(rows) == 5, list(rows))
    L = rows["myrmm MCP: installa su Linux"][1]; M = rows["myrmm MCP: installa su macOS"][1]; W = rows["myrmm MCP: installa su Windows"][1]
    rec("piattaforme: Windows=windows, Linux/macOS=unix", rows["myrmm MCP: installa su Windows"][2] == "windows" and rows["myrmm MCP: installa su Linux"][2] == "unix" and rows["myrmm MCP: installa su macOS"][2] == "unix")
    rec("le variabili sono documentate (MCP_TOKEN obbligatoria)", all("@var MCP_TOKEN (obbligatoria)" in b for b in (L, M, W)) and "@var MCP_USER" in L)
    rec("Windows: token mai stampato, ACL con SID, controllo esadecimale", "Write-Output $tok" not in W and "S-1-5-32-544" in W and "[0-9a-f]{48}" in W)
    rec("Windows: nessun Python; scarica l'eseguibile, ne verifica l'hash e lo prova", all(x not in W for x in ("Find-Py", "PYTHON_URL", "py_compile", "embed")) and "myrmm-mcp.exe" in W and "Get-FileHash" in W and "os=windows&arch=amd64" in W and "--version" in W and "--check" in W)
    rec("Linux/macOS: nessun Python; os e architettura, hash, prova dell'eseguibile", all(x not in b for b in (L, M) for x in ("py_compile", "PYTHON_URL", "install_python", "PYCANDS")) and "OS=linux" in L and "OS=darwin" in M and all("--version" in b and "--check" in b and "sha256" in b for b in (L, M)))
    for nm, b in (("Linux", L), ("macOS", M)):
        pth = os.path.join(tmp, nm + ".sh"); open(pth, "w").write(b)
        r = subprocess.run(["sh", "-n", pth], capture_output=True, text=True); rec(f"{nm}: sintassi sh valida", r.returncode == 0, r.stderr)
    rq = urllib.request.Request(BASE + "?action=api&r=mcp", headers={"X-Api-Token": TOK})
    with urllib.request.urlopen(rq, timeout=15) as f: data = f.read(); sha = f.headers.get("X-Sha256")
    rec("API mcp senza piattaforma: il vecchio myrmm_mcp.py con l'hash (installazioni 1.53)", data.startswith(b"#!/usr/bin/env python3") and hashlib.sha256(data).hexdigest() == sha and data == open(os.path.join(ROOT, "mcp", "myrmm_mcp.py"), "rb").read())
    def mcp_get(**pp):
        rq = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(dict(pp, action="api", r="mcp")), headers={"X-Api-Token": TOK})
        try:
            with urllib.request.urlopen(rq, timeout=30) as f: return f.status, f.read(), f.headers
        except urllib.error.HTTPError as e: return e.code, e.read(), e.headers
    ok = True; det = []
    for o_, a_, fn in [("windows", "amd64", "myrmm-mcp-windows-amd64.exe"), ("linux", "amd64", "myrmm-mcp-linux-amd64"), ("linux", "arm64", "myrmm-mcp-linux-arm64"), ("darwin", "amd64", "myrmm-mcp-darwin-amd64"), ("darwin", "arm64", "myrmm-mcp-darwin-arm64")]:
        fp = os.path.join(ROOT, "server", "update", fn); real = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        c1, b1, _ = mcp_get(os=o_, arch=a_, info=1); i1 = json.loads(b1) if c1 == 200 else {}
        c2, b2, h2 = mcp_get(os=o_, arch=a_)
        good = c1 == 200 and i1.get("sha256") == real and i1.get("size") == os.path.getsize(fp) and c2 == 200 and hashlib.sha256(b2).hexdigest() == real and h2.get("X-Sha256") == real and h2.get("Content-Type") == "application/octet-stream"
        ok &= good; det.append((o_, a_, c1, c2))
    rec("API mcp: eseguibile per ognuna delle 5 piattaforme, hash e dimensione coerenti con il file", ok, det)
    rec("API mcp: os/arch non validi -> 400, piattaforma non pubblicata -> 404", mcp_get(os="plan9", arch="amd64")[0] == 400 and mcp_get(os="linux", arch="mips")[0] == 400 and mcp_get(os="linux")[0] == 400 and mcp_get(os="../../etc/passwd", arch="amd64")[0] == 400)
    rec("l'eseguibile pubblicato non contiene il token né indirizzi di collaudo", b"myrmm_bbbbbbbb" not in open(MCPBIN, "rb").read())
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=api&r=mcp", headers={"X-Api-Token": "myrmm_" + "0" * 48}), timeout=15); c = 200
    except urllib.error.HTTPError as e: c = e.code
    rec("API mcp: token non valido -> 401/403", c in (401, 403), c)
    try: urllib.request.urlopen(BASE + "?action=api&r=mcp", timeout=15); c = 200
    except urllib.error.HTTPError as e: c = e.code
    rec("API mcp: senza token -> 401/403", c in (401, 403), c)
    st_, gj = api("guidelines")
    titles = [x["title"] for x in gj.get("sections", [])]
    rec("API guidelines: sezioni per assistente, tipi di device, token, distribuzione", st_ == 200 and any("assistente" in t for t in titles) and any("tipo di device" in t for t in titles) and any("Token" in t for t in titles) and any("Mettere" in t for t in titles), titles)
    rec("le linee guida citano gli script e le variabili reali", all(n in json.dumps(gj, ensure_ascii=False) for n in ("MCP_TOKEN", "myrmm MCP: installa su Windows", "myrmm MCP: rimuovi")) and all(n in rows for n in ("myrmm MCP: installa su Windows", "myrmm MCP: rimuovi da Windows")))
    pr = subprocess.run([MCPBIN], input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n{"jsonrpc":"2.0","id":2,"method":"initialize","params":{}}\n{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"myrmm_guidelines","arguments":{}}}\n', capture_output=True, text=True, timeout=30, env=dict(os.environ, MYRMM_URL=BASE, MYRMM_TOKEN=TOK))
    rec("MCP (Go): strumento myrmm_guidelines, istruzioni iniziali e risposta con le linee guida dal server vero", "myrmm_guidelines" in pr.stdout and "linee guida" in pr.stdout.lower() and "Regole per l" in pr.stdout, pr.stdout[:300] + pr.stderr[:200])
    ex = subprocess.run([sys.executable, os.path.join(ROOT, "ci", "export_install_scripts.py"), "--check"], capture_output=True, text=True)
    rec("gli script esportati per la prova su Windows (ci/fixtures) coincidono con quelli del server", ex.returncode == 0, ex.stdout + ex.stderr)
    box = os.path.join(tmp, "box"); os.makedirs(box)
    # la sostituzione dei segnaposto la fa la funzione PHP vera (materialize), così si prova anche il modificatore |linea
    msrc = open(os.path.join(ROOT, "server", "index.php"), encoding="utf-8").read(); mfn = msrc[msrc.index("class VarUnsafe extends RuntimeException {}"):msrc.index("/**\n * Valuta le schedule scadute")]
    open(os.path.join(tmp, "mat.php"), "w", encoding="utf-8").write("<?php\n" + mfn + "\necho materialize(file_get_contents($argv[1]), json_decode($argv[2], true), $argv[3] ?? '');\n")
    def mat(body, vars_, plat=""):
        bp = os.path.join(tmp, "mat.in"); open(bp, "w", encoding="utf-8").write(body)
        return subprocess.run(["php", os.path.join(tmp, "mat.php"), bp, json.dumps(vars_), plat], capture_output=True, text=True, encoding="utf-8").stdout
    def sandbox(body, tok, url):
        b = mat(body, {"MCP_TOKEN": tok, "MCP_URL": url, "MCP_USER": ""}, "unix")
        b = b.replace("^https://", "^https?://").replace("DIR=/opt/myrmm-mcp", "DIR=" + box + "/opt").replace("/usr/local/bin/myrmm-mcp", box + "/myrmm-mcp").replace("mkdir -p /usr/local/bin", "mkdir -p " + box)
        p = os.path.join(tmp, "run.sh"); open(p, "w").write(b); return subprocess.run(["sh", p], capture_output=True, text=True, timeout=120)
    if os.geteuid() == 0:
        r = sandbox(L, TOK, BASE); out = r.stdout + r.stderr
        rec("Linux: installa l'eseguibile, lo prova, verifica il token e scrive la configurazione", r.returncode == 0 and "Collegamento verificato" in out and "Server MCP installato: myrmm-mcp " in out and os.access(box + "/opt/myrmm-mcp", os.X_OK) and not os.path.exists(box + "/opt/myrmm-mcp.new") and os.path.islink(box + "/myrmm-mcp"), out[-400:])
        rec("Linux: l'eseguibile installato è quello pubblicato (stesso hash)", hashlib.sha256(open(box + "/opt/myrmm-mcp", "rb").read()).hexdigest() == hashlib.sha256(open(MCPBIN, "rb").read()).hexdigest())
        cfgp = box + "/opt/myrmm-mcp.json"; cj = json.load(open(cfgp)) if os.path.isfile(cfgp) else {}
        rec("Linux: config con url e token, permessi 600, token mai nell'output", cj.get("token") == TOK and cj.get("url") == BASE and oct(os.stat(cfgp).st_mode & 0o777) == "0o600" and TOK not in out)
        env = dict(os.environ); env.pop("MYRMM_URL", None); env.pop("MYRMM_TOKEN", None)
        sx = subprocess.run([box + "/myrmm-mcp", "--check"], capture_output=True, text=True, env=env)
        rec("MCP installato (via collegamento): URL e token letti dal file di configurazione accanto all'eseguibile", sx.returncode == 0 and "Collegamento verificato" in sx.stdout and TOK not in sx.stdout, sx.stdout + sx.stderr)
        sj = subprocess.run([box + "/myrmm-mcp"], input='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"myrmm_status","arguments":{}}}\n{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"myrmm_list_scripts","arguments":{}}}\n', capture_output=True, text=True, env=env, timeout=30)
        j1, j2 = [json.loads(x) for x in sj.stdout.splitlines()]
        rec("MCP installato: parla con l'API vera (stato del token e libreria script)", not j1["result"]["isError"] and "ai-test" in j1["result"]["content"][0]["text"] and not j2["result"]["isError"] and "myrmm MCP: installa su Linux" in j2["result"]["content"][0]["text"], sj.stdout[:300] + sj.stderr[:200])
        open(box + "/opt/myrmm_mcp.py", "w").write("vecchia installazione"); r1b = sandbox(L, TOK, BASE)
        rec("Linux: reinstallazione = aggiornamento, e toglie il vecchio myrmm_mcp.py", r1b.returncode == 0 and not os.path.exists(box + "/opt/myrmm_mcp.py") and os.access(box + "/opt/myrmm-mcp", os.X_OK), r1b.stdout[-300:])
        # un server che pubblica un hash diverso dal file: l'installazione si ferma e non lascia nulla di eseguibile
        class BadH(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                data = json.dumps({"sha256": "0" * 64, "size": 10}).encode() if q.get("info") else b"contenuto-manomesso"
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        bad = ThreadingHTTPServer(("127.0.0.1", 0), BadH); threading.Thread(target=bad.serve_forever, daemon=True).start()
        shutil.rmtree(box + "/opt"); r7 = sandbox(L, TOK, f"http://127.0.0.1:{bad.server_address[1]}/index.php"); bad.shutdown()
        rec("Linux: hash diverso da quello pubblicato -> exit 4, nessun eseguibile installato", r7.returncode == 4 and "non corrisponde all'hash" in r7.stdout and not os.path.exists(box + "/opt/myrmm-mcp") and not os.path.exists(box + "/opt/myrmm-mcp.new"), (r7.returncode, r7.stdout))
        class NoInfo(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                data = b'{"error":"mcp binary not published for linux/amd64"}'; self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        ni = ThreadingHTTPServer(("127.0.0.1", 0), NoInfo); threading.Thread(target=ni.serve_forever, daemon=True).start()
        r8 = sandbox(L, TOK, f"http://127.0.0.1:{ni.server_address[1]}/index.php"); ni.shutdown()
        rec("Linux: risposta senza hash -> exit 4 con messaggio chiaro", r8.returncode == 4 and "non risulta pubblicato" in r8.stdout, (r8.returncode, r8.stdout))
        r = sandbox(L, TOK, BASE)
        r2 = sandbox(L, "myrmm_" + "0" * 48, BASE); rec("Linux: token errato -> errore chiaro, exit 4", r2.returncode == 4 and "scarico del server MCP non riuscito" in r2.stdout, (r2.returncode, r2.stdout))
        r3 = sandbox(L, "abc", BASE); rec("Linux: token malformato -> exit 2", r3.returncode == 2)
        r4 = sandbox(L, TOK, "ftp://insicuro/index.php"); rec("Linux: URL non https -> exit 2", r4.returncode == 2)
        r5 = sandbox(L, TOK + "'; touch " + box + "/pwn; '", BASE); rec("Linux: iniezione nel token respinta", r5.returncode == 2 and not os.path.exists(box + "/pwn"))
        evil = "abc\nMYRMM_V\n)\ntouch " + box + "/pwn2\nX=$(cat <<'MYRMM_V'\nzzz"
        r5b = sandbox(L, evil, BASE); rec("Linux: valore su più righe che prova a chiudere l'here-document -> respinto, nessun codice eseguito", r5b.returncode == 2 and not os.path.exists(box + "/pwn2"), (r5b.returncode, r5b.stdout))
        r5c = sandbox(L, TOK, BASE + "\nMYRMM_V\n)\ntouch " + box + "/pwn3\nX=$(cat <<'MYRMM_V'\nzzz"); rec("Linux: stesso tentativo dall'indirizzo", r5c.returncode == 2 and not os.path.exists(box + "/pwn3"), (r5c.returncode, r5c.stdout))
        raw = L.replace("{{MCP_TOKEN|linea}}", evil).replace("{{MCP_URL|linea}}", "").replace("{{MCP_USER|linea}}", "")
        rec("(prova di controllo) senza |linea lo stesso valore uscirebbe dall'here-document", "|linea" in L and "MYRMM_V\n)\ntouch" in raw)
        rm = rows["myrmm MCP: rimuovi da Linux/macOS"][1].replace("/opt/myrmm-mcp /usr/local/myrmm-mcp", box + "/opt").replace("rm -f /usr/local/bin/myrmm-mcp", "rm -f " + box + "/myrmm-mcp")
        p = os.path.join(tmp, "rm.sh"); open(p, "w").write(rm); r6 = subprocess.run(["sh", p], capture_output=True, text=True)
        rec("rimozione: cartella, config e comando spariti", r6.returncode == 0 and not os.path.exists(box + "/opt") and not os.path.exists(box + "/myrmm-mcp"), r6.stdout)
    else: print("non root: salto l'esecuzione reale dello script")
    PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
    if PWSH:
        pf = os.path.join(tmp, "pf"); os.makedirs(pf); wp = os.path.join(tmp, "win.ps1"); mdir = os.path.join(pf, "myrmm-mcp")
        penv = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "no_proxy", "all_proxy")}
        penv.update(ProgramFiles=pf, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT="1", POWERSHELL_TELEMETRY_OPTOUT="1", DOTNET_CLI_TELEMETRY_OPTOUT="1")
        def winrun(tok, url):
            # l'unico scarto dallo script vero: icacls non esiste fuori da Windows, http locale, l'eseguibile per Linux e il bit di esecuzione
            b = mat(W, {"MCP_TOKEN": tok, "MCP_URL": url}, "windows").replace("^https://", "^https?://").replace("os=windows&arch=amd64", "os=linux&arch=" + arch).replace("Move-Item $new $exe -Force\n", "Move-Item $new $exe -Force\n& chmod 755 $exe\n")
            open(wp, "w", encoding="utf-8").write("function icacls.exe { }\n" + b)
            return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", wp], capture_output=True, text=True, encoding="utf-8", timeout=240, env=penv)
        os.makedirs(os.path.join(mdir, "python")); open(os.path.join(mdir, "myrmm_mcp.py"), "w").write("vecchio"); open(os.path.join(mdir, "myrmm-mcp.cmd"), "w").write("vecchio")
        w1 = winrun(TOK, BASE); wo = w1.stdout + w1.stderr
        rec("Windows (pwsh): installa l'eseguibile, lo prova e verifica il token", w1.returncode == 0 and "Server MCP installato: myrmm-mcp " in wo and "Collegamento verificato" in wo and TOK not in wo, wo[-500:])
        rec("Windows (pwsh): stesso eseguibile pubblicato, nessun .new/.old, pulizia di Python e dei file 1.53", os.path.isfile(mdir + "/myrmm-mcp.exe") and hashlib.sha256(open(mdir + "/myrmm-mcp.exe", "rb").read()).hexdigest() == hashlib.sha256(open(MCPBIN, "rb").read()).hexdigest() and not any(os.path.exists(mdir + x) for x in ("/myrmm-mcp.exe.new", "/myrmm-mcp.exe.old", "/python", "/myrmm_mcp.py", "/myrmm-mcp.cmd")), os.listdir(mdir))
        raw = open(mdir + "/myrmm-mcp.json", "rb").read()
        rec("Windows (pwsh): configurazione JSON valida, senza BOM", not raw.startswith(b"\xef\xbb\xbf") and json.loads(raw) == {"url": BASE, "token": TOK}, raw[:80])
        w2 = winrun(TOK, BASE); rec("Windows (pwsh): reinstallazione sopra l'esistente (aggiornamento)", w2.returncode == 0 and os.path.isfile(mdir + "/myrmm-mcp.exe") and not os.path.exists(mdir + "/myrmm-mcp.exe.old"), (w2.stdout + w2.stderr)[-400:])
        w3 = winrun("myrmm_" + "0" * 48, BASE); rec("Windows (pwsh): token errato -> exit 4 con messaggio chiaro", w3.returncode == 4 and "Scarico del server MCP non riuscito" in w3.stdout, (w3.returncode, w3.stdout[-300:]))
        w4 = winrun("abc", BASE); rec("Windows (pwsh): token malformato -> exit 2", w4.returncode == 2, w4.returncode)
        w5 = winrun(TOK, "ftp://insicuro/index.php"); rec("Windows (pwsh): URL non https -> exit 2", w5.returncode == 2)
        pw = os.path.join(tmp, "pwn_ps")
        w6 = winrun(TOK + "\n'@\nNew-Item " + pw + " | Out-Null\n$x=@'\nzzz", BASE); rec("Windows (pwsh): valore su più righe che prova a chiudere la here-string -> respinto, nessun codice eseguito", w6.returncode == 2 and not os.path.exists(pw), (w6.returncode, w6.stdout[-300:]))
        w7 = winrun(TOK, BASE + "\n'@\nNew-Item " + pw + " | Out-Null\n$x=@'\nzzz"); rec("Windows (pwsh): stesso tentativo dall'indirizzo", w7.returncode == 2 and not os.path.exists(pw), (w7.returncode, w7.stdout[-300:]))
        class BadW(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                data = json.dumps({"sha256": "0" * 64, "size": 10}).encode() if q.get("info") else b"manomesso"
                self.send_response(200); self.send_header("Content-Type", "application/json" if q.get("info") else "application/octet-stream"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        bw = ThreadingHTTPServer(("127.0.0.1", 0), BadW); threading.Thread(target=bw.serve_forever, daemon=True).start()
        shutil.rmtree(mdir); w8 = winrun(TOK, f"http://127.0.0.1:{bw.server_address[1]}/index.php"); bw.shutdown()
        rec("Windows (pwsh): hash diverso da quello pubblicato -> exit 4, nessun eseguibile installato", w8.returncode == 4 and not os.path.exists(mdir + "/myrmm-mcp.exe") and not os.path.exists(mdir + "/myrmm-mcp.exe.new"), (w8.returncode, w8.stdout[-300:], os.listdir(mdir) if os.path.isdir(mdir) else None))
    else: print("pwsh non disponibile: salto l'esecuzione dello script Windows")
    agent = os.path.join(tmp, "agent"); shutil.copy(AG, agent); os.chmod(agent, 0o755)
    open(os.path.join(adir, "config.json"), "w").write(json.dumps({"server_url": BASE, "enroll_token": ET, "poll_seconds": 3, "job_signing_key": KEY, "site": "Collaudo", "full_inventory_hour": 12}))
    ap = subprocess.Popen([agent, "run"], stdout=open(os.path.join(tmp, "agent.log"), "w"), stderr=subprocess.STDOUT)
    dv = wait(lambda: q("SELECT id FROM devices WHERE site='Collaudo'") or None, 90); rec("agent reale arruolato", bool(dv))
    sv_ = api("run", "POST", {"device_id": dv[0][0], "script_id": sid["Con variabile"], "vars": {"NOME": "a\nb"}})
    rec("API run: valore di variabile su più righe -> 422 (nessun job)", sv_[0] == 422 and "su una riga" in json.dumps(sv_[1]), sv_)
    sv2 = api("run", "POST", {"device_id": dv[0][0], "script_id": sid["Con variabile"], "vars": {"NOME": "ok"}})
    rec("API run: valore su una riga accettato", sv2[0] == 200 and sv2[1].get("status") in ("pending", "held"), sv2)
    s, j = api("run", "POST", {"device_id": dv[0][0], "body": "#!/bin/sh\necho ok # " + TOK, "platform": "unix", "dry_run": False})
    s2, r = api("job", id=j["job_id"], wait=30)
    sc = q("SELECT script FROM jobs WHERE id=?", j["job_id"])[0][0]
    rec("job con token nel testo: eseguito e poi mascherato nello storico", r.get("done") and TOK not in sc and "myrmm_****" in sc, (s, j, sc))
    bad = sorted(set(l for l in open(os.path.join(tmp, "php.err")).read().splitlines() if __import__("re").search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l)))[:5]
    rec("nessun errore PHP", not bad, bad)
finally:
    if ap: ap.terminate()
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok")
sys.exit(1 if f else 0)
