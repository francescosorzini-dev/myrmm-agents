#!/usr/bin/env python3
"""myrmm - test di integrazione end-to-end (Windows, Linux, macOS).

Avvia il server PHP con una configurazione di prova, installa l'agent (servizio su Windows, processo in foreground
altrove), poi pilota la console via HTTP come farebbe un operatore e verifica job, diagnostica, chat, task di tray,
script PowerShell e disinstallazione. Scrive report.md / report.json / log in --out.

Uso: python ci/run_tests.py --server server --agent agent.exe --out out
"""
import sys as _s
try: _s.stdout.reconfigure(encoding='utf-8'); _s.stderr.reconfigure(encoding='utf-8')
except Exception: pass
import argparse, http.cookiejar, json, os, platform, re, shutil, sqlite3, subprocess, sys, time, traceback
import urllib.error, urllib.parse, urllib.request

for _s in (sys.stdout, sys.stderr):   # nomi dei test con frecce e accenti: sulla console Windows (cp1252) non devono interrompere la suite
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

WIN = platform.system() == "Windows"
RES = []          # (nome, esito PASS|FAIL|WARN|SKIP, dettaglio)
T0 = time.time()
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}/index.php"
TPORT = 23389   # porta dell'echo server usata per provare il tunnel
TOKEN, KEY, PW = "ci-enroll-token-0123456789ab", "ci-signing-key-ci-signing-key-0123", "CiPassword-12345!"


def rec(name, ok, detail="", warn=False):
    st = "PASS" if ok else ("WARN" if warn else "FAIL")
    RES.append((name, st, str(detail)[:600]))
    print(f"[{st}] {name}" + (f" - {str(detail)[:300]}" if detail and st != "PASS" else ""), flush=True)
    return ok


def skip(name, why):
    RES.append((name, "SKIP", why)); print(f"[SKIP] {name} - {why}", flush=True)


def guard(name):
    """Decoratore: un'eccezione nel test diventa un FAIL, non ferma la suite."""
    def deco(fn):
        def w(*a, **k):
            try: return fn(*a, **k)
            except Exception as e:
                rec(name, False, "eccezione: " + "".join(traceback.format_exception_only(type(e), e)).strip())
        return w
    return deco


def sh(cmd, timeout=120, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout, errors="replace", **kw)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def ps(script, timeout=120, exe=None):
    exe = exe or ("powershell.exe" if WIN else "pwsh")
    return sh([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout)


# ---------------------------------------------------------------- console HTTP
class Console:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj), NoRedirect())

    def req(self, url, data=None, headers=None, timeout=60):
        h = dict(headers or {})
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        r = urllib.request.Request(url, data=body, headers=h)
        try:
            resp = self.op.open(r, timeout=timeout)
        except urllib.error.HTTPError as e:
            resp = e
        return resp.status if hasattr(resp, "status") else resp.code, resp.read().decode("utf-8", "replace"), dict(resp.headers)

    def login(self):
        return self.req(BASE + "?action=login", {"username": "admin", "password": PW})

    def get(self, q): return self.req(BASE + "?" + q)
    def post(self, action, data): return self.req(BASE + "?action=" + action, data)

    def json(self, q=None, action=None, data=None):
        s, b, _ = self.get(q) if data is None else self.post(action, data)
        return s, json.loads(b)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


def agent_http(path, method="GET", body=None, port=47653):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers={"X-Myrmm-Tray": "1"})
    with urllib.request.urlopen(r, timeout=10) as x: return json.loads(x.read().decode())


def wait(fn, secs, step=2):
    end = time.time() + secs
    while time.time() < end:
        try:
            v = fn()
            if v: return v
        except Exception: pass
        time.sleep(step)
    return None


# ---------------------------------------------------------------- DB (sola lettura)
def dbq(db, sql, args=()):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try: return c.execute(sql, args).fetchall()
    finally: c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True); ap.add_argument("--agent", required=True); ap.add_argument("--out", default="out")
    ap.add_argument("--newer-agent", help="binario con versione più alta, per provare l'auto-aggiornamento"); ap.add_argument("--newer-version", default="99.0.0")
    ap.add_argument("--keep", action="store_true", help="non disinstallare alla fine")
    a = ap.parse_args()
    out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True)
    work = os.path.join(out, "work"); shutil.rmtree(work, ignore_errors=True)
    srv = os.path.join(work, "server"); shutil.copytree(a.server, srv, ignore=shutil.ignore_patterns("data", "update"))
    os.makedirs(os.path.join(srv, "update"), exist_ok=True)  # vuota: i binari di rilascio non devono sostituire l'agent in prova
    os.makedirs(os.path.join(srv, "data"), exist_ok=True)
    agent = os.path.abspath(a.agent)
    adir = os.path.join(os.environ.get("ProgramData", "C:/ProgramData"), "myrmm") if WIN else os.path.join(work, "agentdata")
    os.makedirs(adir, exist_ok=True)
    env_info = f"{platform.platform()} · Python {platform.python_version()}"

    # ---- configurazione server
    rc, h = sh(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"])
    rec("php disponibile", rc == 0, h)
    cfg = {"ENROLL_TOKEN": TOKEN, "ENROLL_GLOBAL": True, "CONSOLE_USER": "admin", "CONSOLE_PASS": h.strip(), "JOB_SIGNING_KEY": KEY, "TUNNEL_PORTS": [TPORT, 3389], "TUNNEL_NET_PORTS": [TPORT, 443], "TUNNEL_WAIT_MAX": 0 if WIN else 8, "HEARTBEAT_WAIT_MAX": 0 if WIN else 20, "NET_FAILS": 2}
    rc2, o2 = sh(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)])
    open(os.path.join(srv, "data", "config.php"), "w").write(o2)
    rc, o = sh(["php", "-l", os.path.join(srv, "data", "config.php")]); rec("config.php di prova valido", rc == 0, o)
    rc, o = sh(["php", "-l", os.path.join(srv, "index.php")]); rec("php -l index.php", rc == 0, o)

    slog = open(os.path.join(out, "server.log"), "w")
    senv = dict(os.environ)
    if not WIN: senv["PHP_CLI_SERVER_WORKERS"] = "8"   # su Windows php -S ha un solo worker: i tunnel usano attese brevi (TUNNEL_WAIT_MAX)
    sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=slog, stderr=subprocess.STDOUT, env=senv)
    con = Console()
    try:
        ok = wait(lambda: con.get("action=ping")[0] in (200, 302, 401, 403) or con.get("")[0] in (200, 302, 401), 30)
        rec("server PHP in ascolto", bool(ok))
        db = os.path.join(srv, "data", "myrmm.sqlite")

        # ---- console: login e crawl di tutte le viste
        s, b, hd = con.login()
        rec("login console", s in (302, 303) and "location" in {k.lower() for k in hd}, f"HTTP {s}")
        s, b, _ = con.get("view=dashboard"); rec("dashboard dopo il login", s == 200 and "myrmm" in b, f"HTTP {s}")
        views = ["dashboard", "devices", "inventory", "alerts", "mywork", "assets", "chats", "assettypes", "scripts", "checks", "patch", "vars",
                 "fields", "files", "tasks", "services", "deploy", "audit", "users", "clients", "depts", "onboard", "filters", "rules", "packs",
                 "run", "jobs", "maint", "expiry", "report", "sitediag", "profile", "system", "diag"]
        bad = []
        for v in views:
            s, b, _ = con.get("view=" + v)
            if s != 200 or re.search(r"Fatal error|Parse error|Warning: |Notice: |Deprecated: |Uncaught", b): bad.append(f"{v}:{s}")
        rec(f"crawl {len(views)} viste console senza errori PHP", not bad, ", ".join(bad))

        # ---- script PowerShell: sintassi di tutti quelli di libreria (5.1 e 7) + tray.ps1
        rows = dbq(db, "SELECT name, body, platform FROM scripts")
        pdir = os.path.join(out, "ps"); os.makedirs(pdir, exist_ok=True)
        parse_tpl = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
                     "if($e){$e|%%{ '{0}:{1} {2}' -f $_.Extent.StartLineNumber,$_.Extent.StartColumnNumber,$_.Message }; exit 1}")
        shells = [x for x in (["powershell.exe"] if WIN else []) + ["pwsh"] if shutil.which(x)]
        if not shells: skip("sintassi PowerShell", "nessuna shell PowerShell disponibile")
        files = []
        for i, (n, body, pl) in enumerate(rows):
            if pl == "unix": continue
            f = os.path.join(pdir, f"lib{i:03d}.ps1"); open(f, "w", encoding="utf-8-sig").write(re.sub(r"\{\{[A-Z0-9_]+\}\}", "x", body)); files.append((n, f))
            f = os.path.join(pdir, f"lib{i:03d}v.ps1"); open(f, "w", encoding="utf-8-sig").write(re.sub(r"\{\{[A-Z0-9_]+\}\}", "", body)); files.append((n + " (variabili vuote)", f))
        tray = os.path.join(os.path.dirname(os.path.abspath(a.server)), "agent", "tray.ps1")
        if os.path.isfile(tray): files.append(("agent/tray.ps1", tray))
        for sh_exe in shells:
            fails = []
            for n, f in files:
                rc, o = sh([sh_exe, "-NoProfile", "-Command", parse_tpl % f.replace("'", "''")], 60)
                if rc != 0: fails.append(f"{n}: {o.strip()[:160]}")
            rec(f"sintassi {len(files)} script PowerShell ({sh_exe})", not fails, " | ".join(fails))

        # ---- logica PowerShell dello script RustDesk (Start-Service che fallisce, valori predefiniti)
        rc, o = sh([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps_logic_test.py")], 300)
        rec("script RustDesk Windows: logica e valori predefiniti", rc == 0, o[-600:])
        rc, o = sh([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "clixml_test.py")], 60)
        rec("pulizia dell'output CLIXML di PowerShell", rc == 0, o[-400:])

        # ---- agent
        os.environ["MYRMM_DIR"] = adir
        cj = {"server_url": BASE, "enroll_token": TOKEN, "poll_seconds": 10, "job_signing_key": KEY, "site": "CI", "tunnel_ports": [TPORT], "net_tunnel_ports": [TPORT], "full_inventory_hour": 12}
        open(os.path.join(adir, "config.json"), "w").write(json.dumps(cj))
        aproc = None
        if WIN:
            rc, o = sh([agent, "install"]); rec("agent install (servizio)", rc == 0, o)
            rc, o = sh([agent, "start"]); rec("agent start", rc == 0, o)
        else:
            aproc = subprocess.Popen([agent, "run"], stdout=open(os.path.join(out, "agent.log"), "w"), stderr=subprocess.STDOUT)
        dev = wait(lambda: dbq(db, "SELECT id, hostname, os, inventory, last_seen FROM devices ORDER BY id DESC LIMIT 1") or None, 90)
        if not rec("agent arruolato", bool(dev)):
            raise SystemExit("senza device non si può proseguire")
        did = dev[0][0]
        if WIN:
            rc, o = sh(["sc.exe", "query", "myrmm-agent"]); rec("servizio myrmm-agent RUNNING", "RUNNING" in o, o[-300:])
            rc, o = sh(["sc.exe", "qc", "myrmm-agent"]); rec("servizio avvio automatico", "AUTO_START" in o, o[-300:])
            rc, o = ps("(Get-CimInstance Win32_Process -Filter \"Name='myrmm-agent.exe' OR Name='agent.exe'\" | Select -First 1).Name")
        inv = wait(lambda: (lambda r: r and r[0][0] and json.loads(r[0][0]))(dbq(db, "SELECT inventory FROM devices WHERE id=?", (did,))), 90)
        rec("inventario ricevuto", bool(inv), "")
        if inv:
            for k in ("os", "ram_gb") if False else ():
                pass
            keys = sorted(inv.keys()); rec("inventario: campi base", any(k in inv for k in ("os", "os_name", "hostname")), ",".join(keys)[:300])
            if WIN:
                rec("inventario: stato sessione presente", any(k in inv for k in ("session_state", "session_user", "logged_user")), ",".join(k for k in keys if "sess" in k or "user" in k))
        s, b, _ = con.get(f"view=device&id={did}"); rec("scheda device (con «Salute del device»)", s == 200 and "Salute del device" in b, f"HTTP {s}")
        for v in ("inventory", "diag&device_id=%d" % did, "chat&device_id=%d" % did):
            s, b, _ = con.get("view=" + v); rec(f"vista {v.split('&')[0]} con device reale", s == 200 and not re.search(r"Fatal error|Warning: |Notice: ", b), f"HTTP {s}")

        # ---- job: diagnostiche rapide e script di libreria in sola lettura
        def run_job(script_text, timeout=120, origin_post="newjob"):
            before = dbq(db, "SELECT COALESCE(MAX(id),0) FROM jobs")[0][0]
            con.post("newjob", {"device_id": did, "script": script_text, "timeout": timeout})
            jid = wait(lambda: (dbq(db, "SELECT MAX(id) FROM jobs")[0][0] or 0) > before and dbq(db, "SELECT MAX(id) FROM jobs")[0][0], 10)
            res = wait(lambda: dbq(db, "SELECT exit_code, stdout, stderr FROM results WHERE job_id=? ORDER BY id DESC LIMIT 1", (jid,)) or None, timeout + 30)
            return jid, res

        probe = "Write-Output ('myrmm-ci-ok ' + $PSVersionTable.PSVersion.ToString() + ' ' + [Environment]::UserName)" if WIN else "echo myrmm-ci-ok $(id -un)"
        jid, res = run_job(probe, 90)
        rec("job ad hoc eseguito dall'agent", bool(res) and res[0][0] == 0 and "myrmm-ci-ok" in (res[0][1] or ""), res and (res[0][1] or res[0][2]))
        if res and WIN: print("    ->", res[0][1].strip())

        ro = ["Windows: informazioni sistema", "Windows: elenco software installato", "Windows: stato attivazione licenza", "Windows: utenti locali",
              "Windows: elenca amministratori locali (con controllo)", "Windows: sessioni utente (quser)", "Windows: condivisioni SMB",
              "Windows: porte in ascolto con processo", "Windows: attività pianificate non Microsoft", "Windows: ultimi riavvii e crash",
              "Windows: accessi falliti nelle ultime 24 ore", "Windows: hotfix installate", "Windows: test connettività", "Windows: stampanti installate",
              "Windows: processi per memoria e CPU", "Windows: cerca negli eventi", "Windows: verifica canale sicuro con il dominio"] if WIN else \
             ["Linux/macOS: informazioni sistema", "Linux: porte in ascolto", "Linux/macOS: processi per memoria", "Linux/macOS: utenti, sudo e ultimi accessi"]
        # senza dominio / con servizi assenti alcuni script terminano con codice != 0 legittimamente: contano solo gli errori di parsing/eccezione PowerShell
        tolerant = {"Windows: verifica canale sicuro con il dominio", "Windows: stato attivazione licenza", "Windows: accessi falliti nelle ultime 24 ore", "Windows: cerca negli eventi"}
        for n in ro:
            r = dbq(db, "SELECT id, timeout FROM scripts WHERE name=?", (n,))
            if not r: rec(f"script «{n}» presente in libreria", False); continue
            before = dbq(db, "SELECT COALESCE(MAX(id),0) FROM jobs")[0][0]
            con.post("runscript", {"device_id": did, "script_id": r[0][0]})
            jid = wait(lambda: (lambda m: m > before and m)(dbq(db, "SELECT MAX(id) FROM jobs")[0][0] or 0), 10)
            res = wait(lambda: dbq(db, "SELECT exit_code, stdout, stderr FROM results WHERE job_id=? ORDER BY id DESC LIMIT 1", (jid,)) or None, min(int(r[0][1]), 240) + 30)
            if not res: rec(f"esegui «{n}»", False, "nessun risultato"); continue
            code, so, se = res[0]; txt = (so or "") + (se or "")
            parse_err = re.search(r"ParserError|ParseException|Unexpected token|Missing (closing|terminator)|The term '.*' is not recognized|non è riconosciuto", txt)
            rec(f"esegui «{n}»", (code == 0 or n in tolerant) and not parse_err and len(txt.strip()) > 0, f"exit {code}: {txt.strip()[:250]}")

        # ---- diagnostica completa dalla console
        con.post("dev_diag", {"device_id": did})
        jr = wait(lambda: dbq(db, "SELECT id FROM jobs WHERE origin='diag:run' ORDER BY id DESC LIMIT 1") or None, 10)
        dres = wait(lambda: dbq(db, "SELECT exit_code, stdout FROM results WHERE job_id=?", (jr[0][0],)) or None, 240) if jr else None
        rec("diagnostica completa (#myrmm-diag) ricevuta", bool(dres) and dres[0][0] == 0 and "tray_mode" in (dres[0][1] or "") or (bool(dres) and len(dres[0][1] or "") > 500), dres and (dres[0][1] or "")[:200])
        if dres:
            open(os.path.join(out, "diag-da-console.txt"), "w", encoding="utf-8").write(dres[0][1] or "")
            if WIN:
                bad = [m for m in ("Eccezione", "Exception", "Cannot find", "non è riconosciuto", "ParserError") if m in (dres[0][1] or "")]
                rec("diagnostica Windows senza errori PowerShell", not bad, ",".join(bad), warn=True)
        rc, o = sh([agent, "diag"], 180); rec("CLI «agent diag»", rc == 0 and len(o) > 500, o[:200])
        open(os.path.join(out, "diag-cli.txt"), "w", encoding="utf-8").write(o)

        # ---- tunnel TCP (RDP/SSH) attraverso il relay del server
        import socket, threading, hashlib, random
        def echo_server():
            ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ls.bind(("127.0.0.1", TPORT)); ls.listen(4)
            def h(c):
                try:
                    while True:
                        b = c.recv(65536)
                        if not b: break
                        c.sendall(b)
                except OSError: pass
                finally: c.close()
            while True:
                try: c, _ = ls.accept()
                except OSError: return
                threading.Thread(target=h, args=(c,), daemon=True).start()
        threading.Thread(target=echo_server, daemon=True).start()
        s, r = con.json(action="tun_open", data={"device_id": did, "port": 9, "json": 1}); rec("tunnel: porta non ammessa rifiutata", s == 400 or "error" in r, r)
        s, r = con.json(action="tun_open", data={"device_id": did, "port": TPORT, "json": 1})
        tid, ttok = r.get("id"), r.get("token")
        rec("tunnel: aperto dalla console (richiesta firmata)", s == 200 and bool(tid), r)
        def tinfo(): return con.json(f"action=tun_info&id={tid}")[1]
        up = wait(lambda: tinfo().get("ag_seen"), 90)
        rec("tunnel: l'agent riceve la richiesta e si prepara", bool(up), tinfo())
        bad = subprocess.run([agent, "tunnel", "-u", BASE, "-id", tid, "-token", "0" * 32, "-listen", "127.0.0.1:23391"], capture_output=True, text=True, timeout=60)
        rec("tunnel: token errato rifiutato dall'helper", bad.returncode != 0, bad.stderr[:200])
        bad2 = subprocess.run([agent, "tunnel", "-u", BASE, "-id", tid, "-token", ttok, "-listen", "0.0.0.0:23391"], capture_output=True, text=True, timeout=60)
        rec("tunnel: l'helper rifiuta indirizzi non di loopback", bad2.returncode != 0 and "loopback" in bad2.stderr, bad2.stderr[:200])
        hp = subprocess.Popen([agent, "tunnel", "-u", BASE, "-id", tid, "-token", ttok, "-listen", "127.0.0.1:23390", "-grace", "4s"], stdout=open(os.path.join(out, "tunnel-helper.log"), "w"), stderr=subprocess.STDOUT)
        def conn_local():
            c = socket.socket(); c.settimeout(5); c.connect(("127.0.0.1", 23390)); return c
        cs = wait(lambda: conn_local(), 30, 1)
        rec("tunnel: l'helper ascolta sulla porta locale", bool(cs))
        if cs:
            cs.settimeout(60)
            t0 = time.time(); cs.sendall(b"ping-myrmm"); got = b""
            while len(got) < 10: got += cs.recv(100)
            rtt = time.time() - t0
            rec("tunnel: eco di un messaggio breve attraverso il relay", got == b"ping-myrmm", f"andata e ritorno {rtt*1000:.0f} ms")
            payload = random.Random(7).randbytes((256 if WIN else 2048) * 1024); rcv = bytearray()
            def reader():
                try:
                    while len(rcv) < len(payload):
                        b = cs.recv(65536)
                        if not b: break
                        rcv.extend(b)
                except OSError: pass
            rt = threading.Thread(target=reader); rt.start(); t0 = time.time()
            for i in range(0, len(payload), 65536): cs.sendall(payload[i:i + 65536])
            rt.join(180); dt = time.time() - t0
            rec("tunnel: dati integri andata e ritorno (%s)" % ("256 KB" if WIN else "2 MB"), hashlib.sha256(bytes(rcv)).hexdigest() == hashlib.sha256(payload).hexdigest(), f"{len(rcv)} byte ricevuti in {dt:.1f} s ({2*len(payload)/1048576/max(dt,0.01):.2f} MB/s totali)")
            ti = tinfo(); rec("tunnel: la console vede agent collegato e traffico", ti.get("connected") and ti["up"] > 200000 and ti["dn"] > 200000, ti)
            cs.close()
            # come mstsc dopo l'accettazione del certificato: chiude la prima connessione e ne apre altre (anche in parallelo) sullo stesso tunnel
            def ping(c, msg):
                c.settimeout(60); c.sendall(msg); g = b""
                while len(g) < len(msg): g += c.recv(100)
                return g == msg
            c2, c3 = conn_local(), conn_local()
            ok2 = ping(c2, b"seconda-connessione") and ping(c3, b"terza-parallela") and ping(c2, b"ancora-la-seconda")
            rec("tunnel: nuove connessioni (anche parallele) sullo stesso tunnel dopo la chiusura della prima", ok2)
            c2.close(); c3.close()
        wait(lambda: hp.poll() is not None, 60)
        ti = tinfo(); rec("tunnel: si chiude quando il client si scollega", ti.get("state") == "closed", ti)
        rec("tunnel: coda del relay svuotata alla chiusura", dbq(db, "SELECT COUNT(*) FROM tunnel_chunks WHERE tid=?", (tid,))[0][0] == 0)
        au = [x[0] for x in dbq(db, "SELECT action FROM audit WHERE action LIKE 'tunnel_%'")]
        rec("tunnel: aperture, collegamenti e chiusure nel registro di audit", {"tunnel_open", "tunnel_connect", "tunnel_close"} <= set(au), au)
        s, r = con.json(action="tun_open", data={"device_id": did, "port": TPORT, "json": 1})
        s2, b2, _ = con.post("tun_close", {"id": r.get("id")}); rec("tunnel: chiusura dalla console", s2 in (302, 303) and tinfo.__call__ is not None and con.json(f"action=tun_info&id={r.get('id')}")[1].get("state") == "closed")
        s, b, _ = con.get(f"view=device&id={did}"); rec("scheda device con riquadro Tunnel", s == 200 and "Tunnel (" in b, f"HTTP {s}")
        # helper: -ssh avvia ssh sul tunnel (qui un ssh finto) e chiude il tunnel quando ssh termina
        if not WIN:
            fdir = os.path.join(out, "fakessh"); os.makedirs(fdir, exist_ok=True); fout = os.path.join(fdir, "args.txt")
            open(os.path.join(fdir, "ssh"), "w").write('#!/bin/sh\necho "$@" > "%s"\nsleep 1\nexit 0\n' % fout); os.chmod(os.path.join(fdir, "ssh"), 0o755)
            s, r = con.json(action="tun_open", data={"device_id": did, "port": TPORT, "json": 1})
            henv = dict(os.environ); henv["PATH"] = fdir + os.pathsep + henv["PATH"]
            hs = subprocess.Popen([agent, "tunnel", "-u", BASE, "-id", r.get("id"), "-token", r.get("token"), "-listen", "127.0.0.1:23392", "-ssh", "tecnico", "-alias", "myrmm-d%s" % did], env=henv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try: hs_out = hs.communicate(timeout=90)[0]
            except subprocess.TimeoutExpired: hs.kill(); hs_out = hs.communicate()[0] + " (timeout)"
            args_ = open(fout).read().strip() if os.path.exists(fout) else ""
            rec("tunnel -ssh: l'helper lancia ssh verso la porta locale con utente e alias", args_ == "-p 23392 -o StrictHostKeyChecking=accept-new -o HostKeyAlias=myrmm-d%s tecnico@127.0.0.1" % did, args_ + " | " + hs_out[-200:])
            rec("tunnel -ssh: il tunnel si chiude quando ssh termina", hs.returncode == 0 and "Tunnel chiuso" in hs_out, hs_out[-200:])
            s, r = con.json(action="tun_open", data={"device_id": did, "port": TPORT, "json": 1})
            hb = subprocess.run([agent, "tunnel", "-u", BASE, "-id", r.get("id"), "-token", r.get("token"), "-listen", "127.0.0.1:23393", "-ssh", "-oProxyCommand=x", "-wait", "3s"], capture_output=True, text=True, timeout=60)
            rec("tunnel -ssh: nome utente con opzioni ssh rifiutato", "nome utente non valido" in hb.stderr, hb.stderr[-200:])
            con.post("tun_close", {"id": r.get("id")})

        # ---- chat e tray
        if WIN:
            if os.path.isfile(os.path.join(adir, "tray.ps1")): rec("tray.ps1 installato", True)
            else: rec("tray.ps1 installato", bool(wait(lambda: os.path.isfile(os.path.join(adir, "tray.ps1")), 40)))
            rc, o = ps("Get-ScheduledTask -TaskName 'myrmm-tray' | Select TaskName,State | Format-List | Out-String; (Get-ScheduledTask -TaskName 'myrmm-tray').Principal | Format-List | Out-String")
            rec("attività pianificata myrmm-tray registrata", "myrmm-tray" in o and rc == 0, o.strip()[:300])
            rc, o = ps("Get-ScheduledTaskInfo -TaskName 'myrmm-tray' | Format-List LastRunTime,LastTaskResult,NumberOfMissedRuns | Out-String")
            rec("info attività myrmm-tray", rc == 0, o.strip()[:300], warn=True)
            state = wait(lambda: agent_http("/state"), 30)
            rec("API locale chat su 127.0.0.1:47653", bool(state) and state.get("version"), json.dumps(state)[:200] if state else "non raggiungibile")
            try:
                urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:47653/state"), timeout=5); rec("API locale rifiuta richieste senza header", False)
            except urllib.error.HTTPError as e: rec("API locale rifiuta richieste senza header", e.code == 403, e.code)
            s, r = con.json(action="chat_send", data={"device_id": did, "text": "ciao dall'operatore CI"})
            rec("chat: operatore invia messaggio", s == 200, r)
            got = wait(lambda: (lambda st: st and any(m.get("dir") == "op" and "operatore CI" in m.get("text", "") for m in st.get("log", [])))(agent_http("/state")), 60)
            rec("chat: il messaggio arriva all'agent (chat.json)", bool(got))
            agent_http("/send", "POST", json.dumps({"Text": "risposta dell'utente CI"}).encode())
            s, r = None, None
            got = wait(lambda: (lambda x: any(m["dir"] == "user" and "utente CI" in m["text"] for m in x[1]["msgs"]))(con.json(f"action=chat_poll&device_id={did}")), 60)
            rec("chat: la risposta dell'utente arriva in console", bool(got))
            # avvio reale dell'icona (richiede un desktop: in CI può non esserci)
            tp = subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", os.path.join(adir, "tray.ps1")],
                                  stdout=open(os.path.join(out, "tray-run.log"), "w"), stderr=subprocess.STDOUT)
            time.sleep(15); alive = tp.poll() is None
            rec("tray.ps1: avvio manuale (resta attivo oppure cede il posto all'istanza del task)", alive or tp.poll() == 0, "uscito con codice %s (vedi tray-run.log)" % tp.poll())
            tr = dbq(db, "SELECT tray_seen FROM devices WHERE id=?", (did,))[0][0]
            rec("console vede l'icona attiva (tray_seen)", bool(tr) and int(tr) > time.time() - 180, f"tray_seen={tr}", warn=True)
            if alive: tp.kill()
        else:
            skip("chat/tray", "solo Windows")

        # ---- auto-aggiornamento (servizio che sostituisce il proprio exe e si riavvia)
        if WIN and a.newer_agent:
            ud = os.path.join(srv, "update"); os.makedirs(ud, exist_ok=True)
            shutil.copy(a.newer_agent, os.path.join(ud, "agent.exe")); open(os.path.join(ud, "version.txt"), "w").write(a.newer_version + "\n")
            def ver():
                r = dbq(db, "SELECT inventory FROM devices WHERE id=?", (did,))
                return (json.loads(r[0][0]).get("agent_version") if r and r[0][0] else None)
            got = wait(lambda: ver() == a.newer_version, 300, 5)
            rec(f"auto-aggiornamento dell'agent a {a.newer_version} (riavvio del servizio)", bool(got), f"versione vista: {ver()}")
            rc, o = sh(["sc.exe", "query", "myrmm-agent"]); rec("servizio RUNNING dopo l'aggiornamento", "RUNNING" in o, o[-200:])
            rec("l'aggiornamento non crea un nuovo device", dbq(db, "SELECT COUNT(*) FROM devices")[0][0] == 1)
            run_ok = run_job(probe, 120)[1]
            rec("job eseguito dopo l'aggiornamento", bool(run_ok) and run_ok[0][0] == 0, run_ok and run_ok[0][1])
        elif WIN:
            skip("auto-aggiornamento", "binario più recente non fornito")

        # ---- sonda di rete (1.32): l'agent reale controlla ping e porte TCP e il server dichiara su/giù
        import socket as _so, threading as _th
        pl = _so.socket(); pl.setsockopt(_so.SOL_SOCKET, _so.SO_REUSEADDR, 1); pl.bind(("127.0.0.1", 0)); pl.listen(8); pport = pl.getsockname()[1]
        def _acc():
            while True:
                try: c_, _a = pl.accept(); c_.close()
                except OSError: return
        _th.Thread(target=_acc, daemon=True).start()
        cl = _so.socket(); cl.bind(("127.0.0.1", 0)); cport = cl.getsockname()[1]; cl.close()
        con.post("site_create", {"name": "Rete CI"}); con.post("dev_assign", {"device_id": did, "site": "Rete CI", "dept": ""})
        con.post("probe_set", {"device_id": did, "on": "1"}); con.post("net_subnet_add", {"site": "Rete CI", "cidr": "127.0.0.0/8", "name": "loopback"})
        sid_ = dbq(db, "SELECT id FROM net_subnets")[0][0]
        con.post("net_subnet_probe", {"subnet_id": sid_, "device_id": did, "op": "add", "prio": "1"})
        for nm, kd, pt in (("ping locale", "ping", ""), ("porta aperta", "tcp", pport), ("porta chiusa", "tcp", cport)):
            con.post("net_target_add", {"site": "Rete CI", "name": nm, "ip": "127.0.0.1", "kind": kd, "port": pt, "every": "15"})
        rec("sonda: apparati registrati", dbq(db, "SELECT COUNT(*) FROM net_targets")[0][0] == 3)
        def _st(): return {r[0]: r[1] for r in dbq(db, "SELECT name, status FROM net_targets")}
        got = wait(lambda: _st().get("porta aperta") == "up" and _st().get("porta chiusa") == "down", 180, 5)
        st_ = _st(); rec("sonda: porta aperta → su, porta chiusa → giù (agent reale)", bool(got), str(st_))
        pg = wait(lambda: _st().get("ping locale") in ("up", "down"), 30, 3)
        rec("sonda: ping locale eseguito dall'agent", bool(pg), str(_st()), warn=True)
        rec("sonda: ping locale riuscito", _st().get("ping locale") == "up", str(dbq(db, "SELECT detail FROM net_targets WHERE name='ping locale'")), warn=True)
        al_ = dbq(db, "SELECT type, device_id, message FROM alerts WHERE type LIKE 'net:%' AND status='open'")
        rec("sonda: avviso aperto solo per la porta chiusa", len(al_) == 1 and "porta chiusa" in al_[0][2] and al_[0][1] == did, str(al_))
        rtt_ = dbq(os.path.join(srv, "data", "metrics.sqlite"), "SELECT COUNT(*) FROM m_raw WHERE metric='net.rtt'")[0][0]
        rec("sonda: tempi di risposta registrati nelle metriche", rtt_ >= 1, str(rtt_))
        s_, b_, _ = con.get("view=network&tab=apparati"); rec("sonda: pagina Rete con apparati reali", s_ == 200 and "porta aperta" in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_), f"HTTP {s_}")
        # ---- tunnel verso un apparato della LAN passando dalla sonda (1.33): porta locale e proxy SOCKS5
        tgt = dbq(db, "SELECT id FROM net_targets WHERE name='porta aperta'")[0][0]
        s, r = con.json(action="tun_net_open", data={"target_id": tgt, "port": 9, "json": 1}); rec("tunnel apparato: porta non ammessa rifiutata", s == 400, r)
        s, r = con.json(action="tun_net_open", data={"target_id": tgt, "port": TPORT, "json": 1})
        ntid, ntok = r.get("id"), r.get("token"); rec("tunnel apparato: aperto dalla console (richiesta firmata con la destinazione)", s == 200 and bool(ntid) and r.get("host") == "127.0.0.1", r)
        def ninfo(i): return con.json(f"action=tun_info&id={i}")[1]
        rec("tunnel apparato: la sonda riceve la richiesta e si prepara", bool(wait(lambda: ninfo(ntid).get("ag_seen"), 90)), ninfo(ntid))
        hp2 = subprocess.Popen([agent, "tunnel", "-u", BASE, "-id", ntid, "-token", ntok, "-listen", "127.0.0.1:23392", "-grace", "4s"], stdout=open(os.path.join(out, "tunnel-net-helper.log"), "w"), stderr=subprocess.STDOUT)
        def conn2(port):
            c = socket.socket(); c.settimeout(5); c.connect(("127.0.0.1", port)); return c
        c_ = wait(lambda: conn2(23392), 30, 1); rec("tunnel apparato: l'helper ascolta sulla porta locale", bool(c_))
        if c_:
            c_.settimeout(60); c_.sendall(b"ping-apparato"); g_ = b""
            while len(g_) < 13: g_ += c_.recv(100)
            rec("tunnel apparato: eco attraverso sonda e relay", g_ == b"ping-apparato"); c_.close()
        wait(lambda: hp2.poll() is not None, 60)
        rec("tunnel apparato: si chiude quando il client si scollega", ninfo(ntid).get("state") == "closed", ninfo(ntid))
        s, r = con.json(action="tun_net_open", data={"target_id": tgt, "port": TPORT, "json": 1}); n2, k2 = r.get("id"), r.get("token")
        wait(lambda: ninfo(n2).get("ag_seen"), 90)
        hp3 = subprocess.Popen([agent, "tunnel", "-u", BASE, "-id", n2, "-token", k2, "-socks", "127.0.0.1:23393", "-dest", f"127.0.0.1:{TPORT}", "-grace", "4s"], stdout=open(os.path.join(out, "tunnel-socks-helper.log"), "w"), stderr=subprocess.STDOUT)
        def socks_conn(host, port):
            c = conn2(23393); c.settimeout(30); c.sendall(b"\x05\x01\x00"); assert c.recv(2) == b"\x05\x00"
            c.sendall(b"\x05\x01\x00\x01" + bytes(int(x) for x in host.split(".")) + port.to_bytes(2, "big")); rep_ = c.recv(10); return c, rep_
        sc = wait(lambda: socks_conn("127.0.0.1", 9)[1], 30, 1)
        rec("tunnel apparato: il proxy SOCKS5 rifiuta una destinazione diversa", bool(sc) and sc[1] == 2, str(sc))
        cc, rp = socks_conn("127.0.0.1", TPORT); rec("tunnel apparato: il proxy SOCKS5 accetta la destinazione del tunnel", rp[1] == 0, str(rp))
        if rp[1] == 0:
            cc.sendall(b"via-socks"); g_ = b""
            while len(g_) < 9: g_ += cc.recv(100)
            rec("tunnel apparato: eco attraverso il proxy SOCKS5", g_ == b"via-socks")
        cc.close(); wait(lambda: hp3.poll() is not None, 60)
        hp3.poll() is None and hp3.kill()
        au2 = [x[0] for x in dbq(db, "SELECT detail FROM audit WHERE action='tunnel_open' AND detail LIKE '%127.0.0.1%'")]
        rec("tunnel apparato: aperture registrate nell'audit con apparato e sonda", len(au2) >= 2, au2)
        # ---- SNMP (1.34): la sonda reale interroga apparati simulati (snmpsim: stampante, switch, firewall)
        import shutil as _sh
        simexe = _sh.which("snmpsim-command-responder")
        if not simexe: skip("SNMP con apparati simulati", "snmpsim non installato (pip install snmpsim-lextudio)")
        else:
            import tempfile as _tf
            simdir = _tf.mkdtemp(prefix="simdata"); subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "snmpsim", "gen.py"), simdir], check=True); os.chmod(simdir, 0o755)
            for f_ in os.listdir(simdir): os.chmod(os.path.join(simdir, f_), 0o644)
            sport = 16100 + (os.getpid() % 500)
            sim = subprocess.Popen([simexe, f"--data-dir={simdir}", *[f"--agent-udpv4-endpoint=127.0.0.{n}:{sport}" for n in (11, 12, 13, 14, 15, 16, 17)]] + (["--process-user=nobody", "--process-group=nogroup"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []), stdout=open(os.path.join(out, "snmpsim.log"), "w"), stderr=subprocess.STDOUT)
            time.sleep(4)
            try:
                for ip_, comm_ in (("127.0.0.11", "printer"), ("127.0.0.12", "switch"), ("127.0.0.13", "firewall"), ("127.0.0.14", "sbagliata"), ("127.0.0.15", "ups"), ("127.0.0.16", "nas"), ("127.0.0.17", "ap")):
                    con.post("net_subnet_add", {"site": "Rete CI", "cidr": ip_ + "/32", "name": comm_})
                    sn_ = dbq(db, "SELECT id FROM net_subnets WHERE cidr=?", (ip_ + "/32",))[0][0]
                    con.post("net_subnet_probe", {"subnet_id": sn_, "device_id": did, "op": "add", "prio": "1"})
                    con.post("net_subnet_snmp", {"subnet_id": sn_, "v": "2c", "comm": comm_})
                    con.post("net_target_add", {"site": "Rete CI", "name": "snmp-" + comm_, "ip": ip_, "kind": "snmp", "port": sport, "every": "15"})
                def _sn(nm): 
                    r_ = dbq(db, "SELECT status, sinfo, detail FROM net_targets WHERE name=?", ("snmp-" + nm,)); return r_[0] if r_ else ("", "", "")
                got = wait(lambda: _sn("printer")[0] == "up" and _sn("switch")[0] == "up" and _sn("firewall")[0] == "up" and _sn("printer")[1] != "", 150, 5)
                rec("snmp: la sonda legge stampante, switch e firewall simulati", bool(got), str([_sn(x)[0:1] + (_sn(x)[2],) for x in ("printer", "switch", "firewall")]))
                pi = json.loads(_sn("printer")[1] or "{}"); swi = json.loads(_sn("switch")[1] or "{}"); fwi = json.loads(_sn("firewall")[1] or "{}")
                rec("snmp: stampante riconosciuta da sola, toner, matricola e pagine", pi.get("profile") == "printer" and pi.get("info", {}).get("serial") == "VNB3K12345" and pi.get("m", {}).get("pages") == 48213 and [x["pct"] for x in pi.get("sup", [])] == [80, 7, -1], str(pi)[:300])
                rec("snmp: switch riconosciuto da solo, 24 porte (6 attive)", swi.get("profile") == "switch" and swi.get("m", {}).get("ports_total") == 24 and swi.get("m", {}).get("ports_up") == 6, str(swi.get("m")))
                rec("snmp: firewall riconosciuto da solo, CPU/memoria/disco", fwi.get("profile") == "firewall" and fwi.get("m", {}).get("cpu") == 20 and fwi.get("m", {}).get("disk") == 91, str(fwi.get("m")))
                got = wait(lambda: all(_sn(x)[0] == "up" and _sn(x)[1] != "" for x in ("ups", "nas", "ap")), 120, 5)
                ui_ = json.loads(_sn("ups")[1] or "{}"); ni_ = json.loads(_sn("nas")[1] or "{}"); ai_ = json.loads(_sn("ap")[1] or "{}")
                rec("snmp: UPS riconosciuto da solo — batteria 97%, autonomia 42 min, rete elettrica presente", bool(got) and ui_.get("profile") == "ups" and ui_.get("m", {}).get("batt_pct") == 97 and ui_.get("m", {}).get("runtime_min") == 42 and ui_.get("m", {}).get("on_battery") == 0, str(ui_.get("m")))
                rec("snmp: NAS riconosciuto da solo — un disco anomalo, RAID a posto", ni_.get("profile") == "nas" and ni_.get("m", {}).get("disk_bad") == 1 and ni_.get("m", {}).get("raid_bad") == 0 and ni_.get("info", {}).get("modello") == "DS920+", str(ni_.get("m")))
                rec("snmp: access point riconosciuto da solo — 16 client Wi-Fi", ai_.get("profile") == "ap" and ai_.get("m", {}).get("clients") == 16, str(ai_.get("m")))
                nb_ = [(n_.get("name"), n_.get("p")) for n_ in swi.get("nbr", [])]; nf_ = [(n_.get("name"), n_.get("p")) for n_ in fwi.get("nbr", [])]
                rec("snmp: vicini LLDP dello switch e CDP del firewall arrivati al server", ("FW-SEDE", "lldp") in nb_ and ("AP-PIANO1", "lldp") in nb_ and ("SW-CED", "cdp") in nf_, f"{nb_} {nf_}")
                al_ = dbq(db, "SELECT type FROM alerts WHERE status='open' AND type LIKE 'net:%'")
                tid_p = dbq(db, "SELECT id FROM net_targets WHERE name='snmp-printer'")[0][0]; tid_f = dbq(db, "SELECT id FROM net_targets WHERE name='snmp-firewall'")[0][0]
                rec("snmp: avvisi reali — toner ciano al 7% e disco del firewall al 91%", (f"net:{tid_p}:supply",) in al_ and (f"net:{tid_f}:thr:disk",) in al_, str(al_))
                # apparato con community sbagliata: giù con il motivo
                tid_b = dbq(db, "SELECT id FROM net_targets WHERE name='snmp-sbagliata'")[0][0]
                gotb = wait(lambda: _sn("sbagliata")[0] == "down", 120, 5)
                rec("snmp: community sbagliata → apparato giù con il motivo", bool(gotb) and "SNMP" in _sn("sbagliata")[2], str(_sn("sbagliata")))
                # porte osservate + controllo veloce con l'agent reale
                tid_w = dbq(db, "SELECT id FROM net_targets WHERE name='snmp-switch'")[0][0]
                import urllib.parse as _up
                con.post("net_snmp_set", {"id": tid_w, "what": "obs", "obs[]": "3", "fast": "10"})
                got = wait(lambda: any(f.get("i") == 3 and f.get("op") == 2 for f in json.loads(dbq(db, "SELECT sinfo FROM net_targets WHERE id=?", (tid_w,))[0][0]).get("if", [])) and dbq(db, "SELECT 1 FROM alerts WHERE status='open' AND type=?", (f"net:{tid_w}:if:3",)), 120, 5)
                rec("snmp: porta osservata (la 3 è giù nel simulatore) apre l'avviso", bool(got))
                # scansione apparato
                con.post("net_snmp_scan", {"id": tid_p})
                gotw = wait(lambda: dbq(db, "SELECT scan FROM net_snmp_walk WHERE target_id=?", (tid_p,)), 120, 5)
                s_, b_, _ = con.get(f"view=nettarget&id={tid_p}&sq=VNB3K")
                rec("snmp: «Scansiona apparato» eseguita dalla sonda, risultati nella scheda", bool(gotw) and s_ == 200 and "VNB3K12345" in b_, f"HTTP {s_}")
                s_, b_, _ = con.get(f"view=nettarget&id={tid_p}"); rec("snmp: scheda apparato reale senza errori", s_ == 200 and "Cyan" in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_))
                # OID personalizzato letto dall'apparato simulato
                con.post("net_snmp_set", {"id": tid_p, "what": "cust_add", "name": "pagine2", "oid": "1.3.6.1.2.1.43.10.2.1.4.1.1"})
                got = wait(lambda: any(c_.get("name") == "pagine2" and c_.get("v") == 48213 for c_ in json.loads(dbq(db, "SELECT sinfo FROM net_targets WHERE id=?", (tid_p,))[0][0]).get("cust", [])), 90, 5)
                rec("snmp: OID personalizzato letto dall'apparato", bool(got))
            finally:
                sim.terminate(); sim.wait(timeout=10); _sh.rmtree(simdir, ignore_errors=True)
        # ---- scoperta della rete (1.35): l'agent reale scansiona e il server elenca / censisce
        con.post("net_subnet_add", {"site": "Rete CI", "cidr": "127.0.0.1/32", "name": "solo-locale"})
        sid_s = dbq(db, "SELECT id FROM net_subnets WHERE cidr='127.0.0.1/32'")[0][0]
        con.post("net_subnet_probe", {"subnet_id": sid_s, "device_id": did, "op": "add", "prio": "1"})
        webport = int(BASE.rsplit(":", 1)[1].split("/")[0])
        r_pc = con.post("probe_conf", {"device_id": did, "scan_min": "0", "scan_ports": f"{pport},{webport},{cport}"})
        pc_db = dbq(db, "SELECT probe_cfg FROM devices WHERE id=?", (did,))[0][0]
        rec("scoperta: porte della sonda salvate dal server", f"{pport}" in pc_db and f"{cport}" in pc_db, f"{r_pc[:1]} {pc_db}")
        con.post("net_scan_now", {"subnet_id": sid_s})
        got = wait(lambda: any(pport in [x["p"] for x in json.loads(r_[0])] for r_ in dbq(db, "SELECT ports FROM net_found WHERE subnet_id=?", (sid_s,))), 180, 5)
        rec("scoperta: la sonda scansiona la rete su richiesta e l'apparato compare in «Scoperti»", bool(got))
        fr = dbq(db, "SELECT ip, ports, up, kind, title, state FROM net_found WHERE subnet_id=?", (sid_s,))
        fp = [x["p"] for x in json.loads(fr[0][1])] if fr else []
        rec("scoperta: porte aperte trovate (listener di prova e server web), quella chiusa no", pport in fp and webport in fp and cport not in fp, str(fr)[:300])
        rec("scoperta: apparato web con titolo/intestazione, tipo riconosciuto", bool(fr) and fr[0][3] in ("web", "linux", "windows", "unknown") and fr[0][5] == "new", str(fr)[:200])
        s_, b_, _ = con.get("view=network&tab=scoperti"); rec("scoperta: pagina Scoperti con l'apparato reale", s_ == 200 and "127.0.0.1" in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_))
        fid = dbq(db, "SELECT id FROM net_found WHERE subnet_id=?", (sid_s,))[0][0]
        con.post("net_found_act", {"op": "census", "monitor": "auto", "ids[]": fid})
        rec("scoperta: censimento con un clic crea asset e monitoraggio", dbq(db, "SELECT COUNT(*) FROM assets WHERE location='IP 127.0.0.1' OR data LIKE '%127.0.0.1%'")[0][0] >= 1 and dbq(db, "SELECT state FROM net_found WHERE id=?", (fid,))[0][0] == "known")
        # ---- distribuzione dell'agent dalla sonda (1.36): credenziali cifrate per la sola sonda, prova a vuoto obbligatoria
        pubk = dbq(db, "SELECT probe_pub FROM devices WHERE id=?", (did,))[0][0]
        rec("distribuzione: la sonda ha comunicato la sua chiave pubblica (32 byte)", len(__import__("base64").b64decode(pubk or "")) == 32, str(pubk)[:20])
        con.post("net_found_act", {"op": "deploy", "ids[]": fid})
        con.post("net_deploy_start", {"mode": "run", "ids[]": fid, f"os[{fid}]": "unix", "unix_u": "root", "unix_p": "x", "unix_port": str(cport)})
        r_ = dbq(db, "SELECT mode, state, detail FROM net_deploy ORDER BY id DESC LIMIT 1")
        rec("distribuzione: l'installazione è rifiutata se non c'è una prova a vuoto riuscita", bool(r_) and r_[0][1] == "fail" and "prova a vuoto" in r_[0][2], str(r_))
        con.post("net_deploy_start", {"mode": "dry", "ids[]": fid, f"os[{fid}]": "unix", "unix_u": "root", "unix_p": "SegretoDiProva!", "unix_port": str(cport)})
        gotd = wait(lambda: dbq(db, "SELECT 1 FROM net_deploy WHERE mode='dry' AND state IN ('fail','ok') AND detail<>'' AND id=(SELECT MAX(id) FROM net_deploy)"), 120, 4)
        r_ = dbq(db, "SELECT state, detail, cred FROM net_deploy WHERE mode='dry' ORDER BY id DESC LIMIT 1")
        rec("distribuzione: la sonda decifra le credenziali e prova davvero (porta SSH chiusa → esito chiaro)", bool(gotd) and r_[0][0] == "fail" and "porta SSH chiusa" in r_[0][1], str(r_))
        rec("distribuzione: la password non compare né in chiaro nel database né nell'audit", "SegretoDiProva" not in json.dumps(dbq(db, "SELECT * FROM net_deploy")) and "SegretoDiProva" not in json.dumps(dbq(db, "SELECT * FROM audit")))
        con.post("net_deploy_start", {"mode": "dry", "ids[]": fid, f"os[{fid}]": "win", "win_u": "x\\admin", "win_p": "y"})
        r_ = dbq(db, "SELECT state, detail FROM net_deploy ORDER BY id DESC LIMIT 1")
        if not WIN: rec("distribuzione: verso Windows serve una sonda Windows", r_[0][0] == "fail" and "sonda Windows" in r_[0][1], str(r_))
        s_, b_, _ = con.get("view=network&tab=distribuzione"); rec("distribuzione: pagina con lo storico degli esiti", s_ == 200 and "127.0.0.1" in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_))
        # logica dello script Windows di distribuzione, con CIM/SMB simulati (PowerShell 7 o Windows PowerShell)
        pwsh_ = _sh.which("pwsh") or _sh.which("powershell")
        if not pwsh_: skip("distribuzione: script Windows con WMI/SMB simulati", "PowerShell non disponibile")
        else:
            here_ = os.path.dirname(os.path.abspath(__file__))
            exp_ = {"dry-ok": "ok", "dry-noserver": "fail", "run-ok": "ok", "run-notenrolled": "ok", "run-fail": "fail", "already": "skip", "denied": "fail"}
            bad_ = []
            for sc_, want_ in exp_.items():
                o_ = subprocess.run([pwsh_, "-NoProfile", "-File", os.path.join(here_, "deploy_win_mock.ps1"), os.path.join(here_, "..", "agent", "deploy_win.ps1"), sc_], capture_output=True, text=True, timeout=180).stdout
                m_ = re.search(r"MYRMM_RESULT (\{.*\})", o_)
                if not m_ or json.loads(m_.group(1)).get("state") != want_: bad_.append((sc_, o_[-200:]))
            rec("distribuzione: script Windows (7 scenari: ok, server irraggiungibile, già installato, accesso negato…)", not bad_, str(bad_)[:300])
        con.post("probe_set", {"device_id": did, "on": "0"}); pl.close()

        # ---- disinstallazione
        if not a.keep:
            con.post("dev_uninstall", {"device_id": did})
            if WIN:
                gone = wait(lambda: not dbq(db, "SELECT 1 FROM devices WHERE id=?", (did,)), 120)
                rec("disinstallazione: device rimosso dalla console", bool(gone))
                time.sleep(45)
                rec("disinstallazione: l'agent non si riarruola come nuovo device", dbq(db, "SELECT COUNT(*) FROM devices")[0][0] == 0, f"device in elenco: {dbq(db, 'SELECT id, hostname FROM devices')}")
                gone = wait(lambda: "1060" in sh(["sc.exe", "query", "myrmm-agent"])[1] or "does not exist" in sh(["sc.exe", "query", "myrmm-agent"])[1], 90)
                rec("disinstallazione: servizio rimosso", bool(gone), sh(["sc.exe", "query", "myrmm-agent"])[1][-200:])
                rc, o = ps("if(Get-ScheduledTask -TaskName 'myrmm-tray' -ErrorAction SilentlyContinue){'PRESENTE'}else{'ASSENTE'}")
                rec("disinstallazione: attività myrmm-tray rimossa", "ASSENTE" in o, o.strip())
                rec("disinstallazione: dati locali ripuliti", wait(lambda: not os.path.exists(os.path.join(adir, "config.json")), 60), os.listdir(adir) if os.path.isdir(adir) else "")
            else:   # in primo piano (run) l'agent per progetto NON si disinstalla: lo si verifica
                rec("disinstallazione ignorata se l'agent gira in primo piano", bool(wait(lambda: "primo piano" in open(os.path.join(out, "agent.log")).read(), 60)))
                aproc.terminate()
    except SystemExit as e:
        print("interrotto:", e)
    except Exception as e:
        rec("esecuzione suite", False, traceback.format_exc()[-500:])
    finally:
        sp.terminate()
        try: sp.wait(10)
        except Exception: sp.kill()
        slog.close()
        if WIN:
            rc, o = ps("Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='myrmm-agent'} -MaxEvents 120 -ErrorAction SilentlyContinue | Sort-Object TimeCreated | ForEach-Object { $_.TimeCreated.ToString('s') + ' ' + $_.LevelDisplayName + ' ' + ($_.Message -replace '\\s+',' ') }", 60)
            open(os.path.join(out, "agent-eventlog.txt"), "w", encoding="utf-8").write(o)
            ul = os.path.join(os.environ.get("SystemRoot", "C:/Windows"), "Temp", "myrmm-uninstall.log")
            for sfx, dn in (("", "uninstall-trace.txt"), (".out", "uninstall-trace-out.txt"), (".exit", "uninstall-trace-exit.txt")):
                if os.path.isfile(ul + sfx): shutil.copy(ul + sfx, os.path.join(out, dn))
        # log utili
        for f in ("agent.log", "tray.log", "chat.json", "tray.json", "config.json"):
            p = os.path.join(adir, f)
            if os.path.isfile(p) and f != "config.json": shutil.copy(p, os.path.join(out, "agentdata-" + f))
        n = {k: sum(1 for r in RES if r[1] == k) for k in ("PASS", "FAIL", "WARN", "SKIP")}
        md = [f"# myrmm - test di integrazione", f"_{env_info} · {time.time() - T0:.0f} s_", "",
              f"**{n['PASS']} ok · {n['FAIL']} falliti · {n['WARN']} avvisi · {n['SKIP']} saltati**", "", "| Esito | Test | Dettaglio |", "|---|---|---|"]
        for nm, st, d in RES: md.append(f"| {st} | {nm} | {d.replace('|', '/').replace(chr(10), ' ')[:300]} |")
        open(os.path.join(out, "report.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
        json.dump(RES, open(os.path.join(out, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("\n".join(md) + "\n")
        print("\n" + "\n".join(md[2:4]))
        sys.exit(1 if n["FAIL"] else 0)


if __name__ == "__main__":
    main()
