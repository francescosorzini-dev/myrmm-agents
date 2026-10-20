#!/usr/bin/env python3
"""Coerenza del layout (UI-LINEE-GUIDA.md): stesso posto per ricerca, azione principale e barra di selezione; intestazione fissa;
bersagli >= 24px; stato mai solo a colori; nessuna scorciatoia a tasto singolo dentro i campi. Uso: python3 ci/layout_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8796; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-layout-"); srv = os.path.join(tmp, "server")
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
    if nd < 3: bad(f"device creati {nd} (attesi 3)")
    dbz = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
    for i in range(12):
        dbz.execute("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,?,?,?,?, '{}',?)", (f"PC-{i:02d}", "windows", f"kk{i}", "Acme", now, now))
        dbz.execute("INSERT INTO assets(type_id,name,site,created,updated) VALUES((SELECT MIN(id) FROM asset_types),?,?,?,?)", (f"Asset {i}", "Acme", now, now))
        dbz.execute("INSERT INTO sites(name,created) VALUES(?,?)", (f"Cliente{i}", now))
    for k, val in (("bitlocker", "Non protetto"), ("secure_boot", "0"), ("tpm", "Assente"), ("firewall", "Attivo"), ("antivirus", "Defender"), ("defender_firme", "2"), ("uac", "1"), ("smb1", "0"), ("rdp", "0"), ("os_attivato", "1"), ("ultimo_aggiornamento", "2026-09-01"), ("riavvio_pendente", "0"), ("uptime_giorni", "5"), ("disco_sistema_libero_gb", "50"), ("batteria_salute", "80")):   # pannello «Conformità flotta» (15 righe)
        dbz.execute("INSERT OR IGNORE INTO custom_fields(name,label,type,created) VALUES(?,?, 'text', ?)", (k, k, now))
        fid = dbz.execute("SELECT id FROM custom_fields WHERE name=?", (k,)).fetchone()[0]
        for did in [r[0] for r in dbz.execute("SELECT id FROM devices LIMIT 3")]: dbz.execute("INSERT OR REPLACE INTO device_fields(device_id,field_id,value,updated,source) VALUES(?,?,?,?,'test')", (did, fid, val, now))
    dbz.commit(); dbz.close()
    views = ["devices", "assets", "tickets", "docs", "clients", "users", "audit", "alerts", "jobs", "network&tab=scoperti", "network&tab=credenziali", "todo", "trash", "scripts", "expiry"]
    with sync_playwright() as pw:
        br = pw.chromium.launch(); c = br.new_context(viewport={"width": 1360, "height": 800}); p = c.new_page()
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        except Exception: pass
        p.wait_for_selector(".rail", timeout=8000)
        # il menu «+ Aggiungi» sta sempre nella barra alta, nello stesso punto
        pos = set()
        for v in ["dashboard", "devices", "assets", "tickets", "docs", "clients"]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
            b = p.locator("#addm summary").bounding_box()
            if not b: bad(f"{v}: manca «+ Aggiungi»"); continue
            if b["y"] > 70: bad(f"{v}: «+ Aggiungi» non è nella barra alta (y={b['y']:.0f})")
            pos.add(round(b["x"] / 4))
            top = p.locator(".top").bounding_box()
            if top and b["x"] < top["width"] / 2: bad(f"{v}: «+ Aggiungi» non è a destra")
        if len(pos) > 2: bad(f"«+ Aggiungi» cambia posizione tra le pagine: {sorted(pos)}")
        # elenchi: ricerca sopra la tabella, uguale ovunque; intestazione fissa; barra di selezione al posto della ricerca
        lx = {}
        for v in views:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
            lt = p.locator(".lt")
            if lt.count() == 0: continue   # elenco corto: nessuna barra, va bene
            b = lt.first.bounding_box(); t = p.locator(".lt + .tw table").first.bounding_box() if p.locator(".lt + .tw table").count() else None
            sb = p.locator(".lt input[type=search]").first.bounding_box()
            if not sb or p.evaluate("document.querySelector('.lt').parentNode.classList.contains('card')"): continue   # elenco dentro un riquadro (chiuso o a parte)
            lx.setdefault(round(sb["x"] / 6), []).append(v)
            if t and sb["y"] > t["y"]: bad(f"{v}: la ricerca sta sotto la tabella")
            if p.evaluate("getComputedStyle(document.querySelector('.lt')).position") != "sticky": bad(f"{v}: la barra dell'elenco non è fissa")
            if p.locator(".lt .lbulk").count() != 1: bad(f"{v}: manca la barra di selezione")
            hp = p.evaluate("(()=>{var h=document.querySelector('.lst table th');return h?getComputedStyle(h).position:'-'})()")
            if hp not in ("sticky", "-"): bad(f"{v}: l'intestazione della tabella non è fissa")
            if p.locator(".lt input[type=search]").first.get_attribute("aria-label") in (None, ""): bad(f"{v}: ricerca senza etichetta")
        if len(lx) > 1: bad(f"il campo di ricerca cambia posizione orizzontale tra gli elenchi: {lx}")
        # l'intestazione resta visibile scorrendo (fissa nella pagina o nel contenitore) e a pagina ferma non copre le righe
        for v in ["devices", "assets", "clients", "audit", "tickets"]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main table", state="attached")
            sel = "#invT" if v == "devices" else ".lst table"
            if p.locator(sel).count() == 0:
                if v in ("devices", "assets", "clients"): bad(f"{v}: tabella non trovata ({sel})")
                continue
            g0 = p.evaluate("(s)=>{var t=document.querySelector(s),h=t.querySelector('th').getBoundingClientRect(),r=[].filter.call(t.rows,function(x){return !x.querySelector('th')&&x.getBoundingClientRect().height>0})[0].getBoundingClientRect();return h.bottom<=r.top+2}", sel)
            if not g0: bad(f"{v}: a pagina ferma l'intestazione copre le righe")
            top = p.evaluate("""(s)=>{var t=document.querySelector(s),th=t.querySelector('th'),w=null;for(var e=t.parentNode;e&&e.tagName!=='MAIN';e=e.parentNode){var c=getComputedStyle(e);if(/(auto|scroll)/.test(c.overflowY)&&e.scrollHeight>e.clientHeight+1){w=e;break}}
              if(w){w.scrollTop=400;return th.getBoundingClientRect().top-w.getBoundingClientRect().top}
              t.rows[t.rows.length-1].scrollIntoView({block:'end'});return th.getBoundingClientRect().top<0?-1:0}""", sel)
            if abs(top) > 3: bad(f"{v}: l'intestazione non resta fissa scorrendo (scarto {top:.0f})")
            p.evaluate("window.scrollTo(0,0)")
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        if p.locator("text=Conformità flotta").count() == 0: bad("dashboard: pannello Conformità flotta assente nei dati di prova")
        else:
            r0 = p.evaluate("(()=>{var t=[...document.querySelectorAll('main table')].filter(x=>x.closest('.panel')&&x.closest('.panel').textContent.indexOf('Conformità')>=0)[0],h=t.querySelector('th').getBoundingClientRect(),r=t.rows[1].getBoundingClientRect();return [h.bottom,r.top]})()")
            if r0[0] > r0[1] + 2: bad(f"dashboard: intestazione della Conformità sopra le righe {r0}")
            if p.locator("text=Filtra le righe").count(): bad("dashboard: ricerca doppia")
        # bersagli minimi e focus visibile
        small = []
        for v in ["devices", "assets", "tickets", "network&tab=credenziali", "todo"]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
            small += [f"{v}: {x}" for x in p.evaluate("""()=>{var o=[];document.querySelectorAll('main button, main .btn2, main input[type=submit], main input[type=checkbox]').forEach(function(e){var r=e.getBoundingClientRect();if(r.width>0&&((e.type==='checkbox'?(r.height<18||r.width<18):(r.height<24||r.width<24)))&&getComputedStyle(e).visibility!=='hidden')o.push((e.textContent||e.name||e.type).trim().slice(0,30)+' '+Math.round(r.width)+'x'+Math.round(r.height))});return o.slice(0,5)}""")]
        for x in small[:10]: bad("bersaglio troppo piccolo: " + x)
        # stato mai solo a colori: ogni .pill ha testo
        for v in ["devices", "network&tab=credenziali", "todo", "alerts"]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
            n = p.evaluate("[...document.querySelectorAll('main .pill')].filter(e=>!e.textContent.trim()&&!e.getAttribute('aria-label')).length")
            if n: bad(f"{v}: {n} indicatori di stato senza testo")
        # le scorciatoie non agiscono mentre si scrive
        p.goto(BASE + "?view=devices"); p.wait_for_selector("main")
        inp = p.locator("#invQ")
        if inp.count():
            inp.focus(); u0 = p.url; p.keyboard.type("njx?/"); 
            if p.url != u0 or p.evaluate("document.getElementById('kbo').classList.contains('on')"): bad("una scorciatoia a tasto singolo è scattata dentro un campo")
        p.goto(BASE + "?view=devices"); p.wait_for_selector("main"); p.keyboard.press("?")
        if not p.evaluate("document.getElementById('kbo').classList.contains('on')"): bad("«?» non apre le scorciatoie")
        p.keyboard.press("Escape")
        # su telefono niente scroll orizzontale nelle pagine nuove
        c2 = br.new_context(viewport={"width": 390, "height": 800}); q = c2.new_page(); q.goto(BASE); q.fill("input[name=username]", "admin"); q.click("button[type=submit]")
        try: q.wait_for_selector("input[name=password]", timeout=3000); q.fill("input[name=password]", PW); q.click("button[type=submit]")
        except Exception: pass
        q.wait_for_selector(".rail", timeout=8000)
        for v in ["todo", "netwiz", "newdevice", "import", "trash", "network&tab=credenziali", "devices", "clients", "assets", "tickets", "users", "audit"]:
            q.goto(BASE + "?view=" + v); q.wait_for_selector("main")
            if q.evaluate("document.documentElement.scrollWidth>window.innerWidth+1"): bad(f"{v}: scroll orizzontale su telefono")
            ov = q.evaluate("[...document.querySelectorAll('main *')].filter(e=>{var r=e.getBoundingClientRect();return r.width>0&&r.right>window.innerWidth+1&&!e.closest('.tw')&&!e.closest('.bulkp:not(.open)')&&!(e.closest('details:not([open])')&&!e.closest('summary'))}).length")
            if ov: bad(f"{v}: {ov} elementi escono dallo schermo su telefono")
        br.close()
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    for ln in sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught|Error", l) and "Accepted" not in l and "Closing" not in l))[:20]: bad("log PHP: " + ln[:220])
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(problems)} problemi di layout"); sys.exit(1 if problems else 0)
