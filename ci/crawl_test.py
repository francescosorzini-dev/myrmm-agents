#!/usr/bin/env python3
"""Crawl dell'interfaccia: visita ogni pagina e ogni scheda con ruoli diversi e cerca errori PHP, errori JS, HTTP >= 400,
link rotti e overflow orizzontale su telefono. Uso: python3 ci/crawl_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8795; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-crawl-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32, "TUNNEL_MODE": "on"}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
problems = []; n_pages = 0
def bad(m): problems.append(m); print("PROBLEMA", m, flush=True)
try:
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"}), timeout=5)
    except Exception: pass
    for _ in range(50):
        try:
            if os.path.exists(os.path.join(srv, "data", "myrmm.sqlite")) and sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")).execute("SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM sites),(SELECT COUNT(*) FROM scripts)").fetchone() is not None: break
        except Exception: pass
        time.sleep(.3)
    db = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for u, r in (("oper", "operator"), ("viewer", "viewer")):
        db.execute("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES(?,?,?, '',1,?,0)", (u, h, r, now))
    db.commit(); db.close()
    def post(body, key, path="heartbeat"):
        urllib.request.urlopen(urllib.request.Request(BASE + "?action=" + path, data=json.dumps(body).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"}), timeout=15).read()
    keys = ["k1", "k2", "k3"]
    dbx = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
    for (hn, osn, site), k in zip([("SRV-WIN", "windows", "Acme"), ("PC-WIN", "windows", "Acme"), ("LNX01", "linux", "Beta")], keys):
        dbx.execute("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,?,?,?,?, '{}',?)", (hn, osn, k, site, now, now))
    dbx.commit(); dbx.close()
    inv = lambda os_: {"os": os_, "cpu_pct": 55, "ram_pct": 60, "ram_gb": 16, "cpu": "Xeon", "disks": [{"DeviceID": "C:", "size_gb": 200, "free_gb": 15}], "ips": ["10.0.0.5"], "agent_version": "1.19.1",
                       "software": [{"name": "7-Zip", "version": "23"}], "services": [{"name": "Spooler", "state": "Running"}], "session_state": "attiva", "session_user": "mario"}
    for k, o in zip(keys, ["Windows Server 2022", "Windows 11", "Ubuntu 22.04"]):
        try: post({"inventory": inv(o)}, k)
        except Exception as e: bad(f"heartbeat: {e}")
    time.sleep(.5)
    db = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
    nd = db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]; dev_ids = [r[0] for r in db.execute("SELECT id FROM devices")]
    db.execute("INSERT INTO assets(type_id,name,site,created,updated) VALUES((SELECT MIN(id) FROM asset_types),'SIM test','Acme',?,?)", (now, now))
    db.execute("INSERT INTO filters(name,criteria,created) VALUES('Tutti i Windows','{\"mode\":\"and\",\"conds\":[]}',?)", (now,))
    db.commit(); db.close()
    dbz = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
    for i in range(12):   # abbastanza righe perché gli elenchi mostrino ricerca, barra di selezione e intestazione fissa
        dbz.execute("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,?,?,?,?, '{}',?)", (f"PC-{i:02d}", "windows", f"kk{i}", "Acme", now, now))
        dbz.execute("INSERT INTO assets(type_id,name,site,created,updated) VALUES((SELECT MIN(id) FROM asset_types),?,?,?,?)", (f"Asset {i}", "Acme", now, now))
        dbz.execute("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", (f"Cliente{i}", now))
    for k, val in (("bitlocker", "Non protetto"), ("secure_boot", "0"), ("tpm", "Assente"), ("firewall", "Attivo"), ("antivirus", "Defender"), ("defender_firme", "2"), ("uac", "1"), ("smb1", "0"), ("rdp", "0"), ("os_attivato", "1"), ("ultimo_aggiornamento", "2026-09-01"), ("riavvio_pendente", "0"), ("uptime_giorni", "5"), ("disco_sistema_libero_gb", "50"), ("batteria_salute", "80")):   # pannello «Conformità flotta» (15 righe)
        dbz.execute("INSERT OR IGNORE INTO custom_fields(name,label,type,created) VALUES(?,?, 'text', ?)", (k, k, now))
        fid = dbz.execute("SELECT id FROM custom_fields WHERE name=?", (k,)).fetchone()[0]
        for did in [r[0] for r in dbz.execute("SELECT id FROM devices LIMIT 3")]: dbz.execute("INSERT OR REPLACE INTO device_fields(device_id,field_id,value,updated,source) VALUES(?,?,?,?,'test')", (did, fid, val, now))
    dbz.commit(); dbz.close()
    if nd < 3: bad(f"device creati {nd} (attesi 3)")
    views = ["dashboard", "devices", "inventory", "alerts", "mywork", "assets", "chats", "diag", "assettypes", "scripts", "checks", "patch", "vars", "fields", "files", "tasks", "services", "deploy", "audit", "users", "clients", "depts", "onboard", "todo", "netwiz", "newdevice", "import", "trash", "network&tab=credenziali", "network&tab=sottoreti", "docs", "docs&edit=0",
             "filters", "rules", "packs", "run&script=1", "runbooks", "jobs", "maint", "expiry", "report", "sitediag", "profile", "system", "asset&id=1", "chat&device_id=1", "tunnel&id=1", "inexistente", "device&id=999"]
    for d in dev_ids: views += [f"device&id={d}", f"device&id={d}&mr=7d", f"device&id={d}&mr=1y"]
    def audit(role, user, mobile=False):
        global n_pages
        OVF = lambda: str(p.evaluate("""()=>{var W=window.innerWidth,o=[];document.querySelectorAll('body *').forEach(function(e){var r=e.getBoundingClientRect();if(r.right>W+1&&r.width>0&&getComputedStyle(e).position!=='fixed'){var pp=e.parentElement,clip=false;while(pp&&pp!==document.body){if(getComputedStyle(pp).overflowX!=='visible'){clip=true;break}pp=pp.parentElement}if(!clip)o.push(e.tagName+'.'+e.className+' '+Math.round(r.right)+' <'+(e.parentElement?e.parentElement.tagName+'.'+e.parentElement.className:'')+'>')}});return o.slice(0,5)}"""))
        with sync_playwright() as pw:
            br = pw.chromium.launch(); c = br.new_context(viewport={"width": 390 if mobile else 1360, "height": 800}); p = c.new_page(); errs = []
            p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
            p.on("response", lambda r: errs.append(f"HTTP {r.status} {r.url[-80:]}") if r.status >= 400 and "favicon" not in r.url else None)
            p.goto(BASE); p.fill("input[name=username]", user); p.click("button[type=submit]")
            try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
            except Exception: pass
            p.wait_for_selector(".rail", timeout=8000)
            for v in views:
                errs.clear(); p.goto(BASE + "?view=" + v); n_pages += 1
                try: p.wait_for_selector("main", timeout=5000)
                except Exception:
                    if not (role != "admin" and "Accesso negato" in p.content() or "negat" in p.content().lower() or "permess" in p.content().lower()): bad(f"[{role}] {v}: nessun <main>")
                    continue
                html = p.content()
                for m in re.finditer(r"(Warning|Notice|Fatal error|Deprecated|Parse error|Uncaught)[^<]{0,300}(on line \d+| in /)", html):
                    if "Notice" == m.group(1) and "Nuovo" in html[max(0, m.start()-20):m.start()]: continue
                    bad(f"[{role}] {v}: possibile errore PHP: …{re.sub(chr(10), ' ', html[max(0, m.start()-40):m.start()+160])}…"); break
                # tabelle: l'intestazione non deve stare in mezzo alle righe; una sola ricerca per elenco
                geo = p.evaluate("""()=>{var o=[];document.querySelectorAll('main table').forEach(function(t){var th=t.querySelector('th'),tr=[].filter.call(t.rows,function(r){return !r.querySelector('th')&&r.getBoundingClientRect().height>0})[0];if(!th||!tr)return;var a=th.getBoundingClientRect(),b=tr.getBoundingClientRect();if(a.bottom>b.top+2&&a.top>=b.top-2)o.push('intestazione sopra le righe ('+Math.round(a.top)+' vs '+Math.round(b.top)+')');var w=t.closest('.tw');if(w){var s=0,p=w.previousElementSibling;while(p&&s<4){var q='input[type=search]:not(.selq):not(.cbp input),input.tq';if(p.matches&&p.matches(q))s++;if(p.querySelector&&p.querySelector(q))s++;p=p.previousElementSibling;if(s>=2)break}if(s>=2)o.push('ricerca doppia')}});return o.slice(0,3)}""")
                for g in geo: bad(f"[{role}] {v}: {g}")
                for e in errs:
                    if v in ("inexistente", "device&id=999") and e.startswith("HTTP"): continue
                    if role == "viewer" and e.startswith("HTTP 403"): continue
                    bad(f"[{role}] {v}: {e}")
                if mobile and p.evaluate("document.documentElement.scrollWidth>window.innerWidth+1"): bad(f"[{role}] {v}: scroll orizzontale su telefono — " + OVF())
                if mobile:
                    fuori = p.evaluate("[...document.querySelectorAll('main *')].filter(e=>{var r=e.getBoundingClientRect();if(!(r.width>0&&r.right>window.innerWidth+1))return false;if(e.closest('.bulkp:not(.open)'))return false;for(var x=e;x&&x.tagName!=='MAIN';x=x.parentNode){if(x.tagName==='DETAILS'&&!x.open&&x!==e&&e.tagName!=='SUMMARY'&&!e.closest('summary'))return false;var c=getComputedStyle(x);if(/(auto|scroll)/.test(c.overflowX)&&x.scrollWidth>x.clientWidth+1&&x!==e)return false}return true}).slice(0,3).map(e=>e.tagName+'.'+e.className+' '+Math.round(e.getBoundingClientRect().right))")
                    if fuori: bad(f"[{role}] {v}: elementi fuori schermo su telefono: {fuori}")
                # ogni scheda laterale e ogni link interno principale
                tabs = p.locator(".dnav a:visible")
                for i in range(tabs.count()):
                    try:
                        tabs.nth(i).click(); p.wait_for_timeout(60)
                        if mobile and p.evaluate("document.documentElement.scrollWidth>window.innerWidth+1"): bad(f"[{role}] {v} scheda {i}: scroll orizzontale su telefono — " + OVF())
                    except Exception as e: bad(f"[{role}] {v} scheda {i}: {str(e)[:80]}")
                for e in errs:
                    if not (v in ("inexistente", "device&id=999") and e.startswith("HTTP")): bad(f"[{role}] {v} (dopo click schede): {e}")
            br.close()
    if os.environ.get("CRAWL_ONLY") == "mobile": audit("admin-mobile", "admin", True)
    else: audit("admin", "admin"); audit("operatore", "oper"); audit("viewer", "viewer"); audit("admin-mobile", "admin", True)
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    for ln in sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught|Error", l) and "Accepted" not in l and "Closing" not in l))[:40]: bad("log PHP: " + ln[:220])
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{n_pages} pagine visitate, {len(problems)} problemi"); sys.exit(1 if problems else 0)
