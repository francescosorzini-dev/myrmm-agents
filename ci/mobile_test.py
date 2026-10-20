#!/usr/bin/env python3
"""Check-in dei telefoni Android/iOS senza agent (1.46.0).
Uso: python3 ci/mobile_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8816; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-mob-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite")
res = []
APKV = open(os.path.join(ROOT, "server", "update", "apk-version.txt")).read().strip()

def rec(name, ok, info=""):
    res.append((name, bool(ok))); print(("OK   " if ok else "FAIL ") + name + (("  [" + str(info)[:200] + "]") if (not ok and info != "") else ""), flush=True)

def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r

def post(body, form=False, token_hdr=None):
    if form: data = urllib.parse.urlencode(body).encode(); ct = "application/x-www-form-urlencoded"
    else: data = json.dumps(body).encode(); ct = "application/json"
    rq = urllib.request.Request(BASE + "?action=mobile_checkin", data=data, headers={"Content-Type": ct})
    try:
        with urllib.request.urlopen(rq, timeout=10) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}

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
            if os.path.exists(DB) and sqlite3.connect(DB).execute("SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM sites),(SELECT COUNT(*) FROM scripts)").fetchone() is not None: break
        except Exception: pass
        time.sleep(.3)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for n in ("Acme", "Beta"): q("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", n, now)
    TA, TB = "st-" + "a" * 32, "st-" + "b" * 32
    q("INSERT INTO site_tokens(site,token,created) VALUES('Acme',?,?)", TA, now)
    q("INSERT INTO site_tokens(site,token,created) VALUES('Beta',?,?)", TB, now)

    A = {"token": TA, "id": "pixel-0001-abcdef", "name": "Telefono di Mario", "os": "android", "os_version": "14", "manufacturer": "Google",
         "model": "Pixel 8", "battery": 80, "charging": 0, "free_gb": 42.5, "total_gb": 128, "ip": "192.168.1.50", "user": "mario", "interval_min": 60}
    c, j = post(A)
    rec("check-in: crea il device", c == 200 and j.get("ok") and j.get("device_id"), (c, j))
    rows = q("SELECT id,hostname,os,site,mobile_id,mobile_min,last_seen,inventory FROM devices WHERE mobile_id=?", A["id"])
    rec("device nel cliente del token, os android, intervallo 60", len(rows) == 1 and rows[0][2] == "android" and rows[0][3] == "Acme" and rows[0][5] == 60 and rows[0][1] == "Telefono di Mario", rows)
    inv = json.loads(rows[0][7]) if rows else {}
    rec("inventario mappato", inv.get("os") == "Android 14" and inv.get("model") == "Pixel 8" and inv.get("battery_pct") == 80 and inv.get("disks", [{}])[0].get("free_gb") == 42.5 and inv.get("ips") == ["192.168.1.50"], inv)
    did = rows[0][0]
    ck = q("SELECT threshold,param FROM checks WHERE type='offline_min' AND device_id=?", did)
    rec("soglia offline propria: 120 min", ck == [(120.0, "mobile")], ck)

    A2 = dict(A, battery=55, name="Altro nome"); c, j = post(A2)
    rows = q("SELECT COUNT(*),MAX(hostname) FROM devices WHERE mobile_id=?", A["id"])
    inv = json.loads(q("SELECT inventory FROM devices WHERE id=?", did)[0][0])
    rec("secondo check-in aggiorna senza duplicare", rows == [(1, "Telefono di Mario")] and inv["battery_pct"] == 55, rows)

    c, j = post(dict(A, id="short")); rec("id troppo corto: 400", c == 400, (c, j))
    c, j = post(dict(A, token="st-" + "z" * 32)); rec("token errato: 403", c == 403, (c, j))
    c, j = post(dict(A, token=TB)); rec("stesso id con il token di un altro cliente: 403", c == 403, (c, j))

    c, j = post({"token": TB, "id": "iphone-0002-xyz987", "os": "iOS", "os_version": "17.5", "model": "iPhone 15", "battery": "91", "interval_min": "720"}, form=True)
    r2 = q("SELECT os,site,mobile_min,hostname,inventory FROM devices WHERE mobile_id='iphone-0002-xyz987'")
    i2 = json.loads(r2[0][4]) if r2 else {}
    rec("iOS via form: cliente Beta, 720 min, produttore Apple", c == 200 and r2 and r2[0][:3] == ("ios", "Beta", 720) and i2.get("manufacturer") == "Apple" and r2[0][3].startswith("iPhone 15-"), (c, r2))
    ck = q("SELECT threshold FROM checks WHERE type='offline_min' AND device_id=(SELECT id FROM devices WHERE mobile_id='iphone-0002-xyz987')")
    rec("iOS: soglia offline 1440 min", ck == [(1440.0,)], ck)

    with sync_playwright() as pw:
        br = pw.chromium.launch(); cx = br.new_context(viewport={"width": 1360, "height": 900}); p = cx.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        p.wait_for_load_state()
        def page(url): p.goto(BASE + url); p.wait_for_load_state(); return p.content()
        # 100 minuti fa: per un telefono a 60 min è ancora online (finestra 120), per un agent no
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 100 * 60))
        q("UPDATE devices SET last_seen=? WHERE id=?", old, did)
        html = page(f"?view=device&id={did}")
        rec("scheda: telefono visto 100 min fa è online", 'class="pill ok">online' in html, re.findall(r'class="pill (?:ok|err)">\w+', html)[:3])
        print({k: k in html for k in ("Telefono con check-in", "Task manager", "Inventario completo ora")})
        rec("scheda: nota telefono e niente azioni da agent", "Telefono con check-in" in html and "Task manager" not in html and "Inventario completo ora" not in html)
        q("UPDATE devices SET last_seen=? WHERE id=?", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 200 * 60)), did)
        html = page(f"?view=device&id={did}")
        rec("scheda: visto 200 min fa è offline", 'class="pill err">offline' in html)
        q("UPDATE devices SET last_seen=? WHERE id=?", old, did)
        html = page("?view=devices")
        rec("elenco device: il telefono è presente", "Telefono di Mario" in html)
        html = page("?view=deploy")
        rec("istruzioni: pagina di installazione con la sezione telefoni", "Telefoni e tablet (Android e iOS)" in html and "action=mobile_checkin" in html and "Comandi" in html)
        # --- telefono con app APK: comandi dalla console
        H = {"Origin": f"http://127.0.0.1:{PORT}", "Content-Type": "application/x-www-form-urlencoded"}
        def cpost(url, data): return cx.request.post(BASE + url, data=urllib.parse.urlencode(data), headers=H, max_redirects=0)
        K = {"token": TA, "id": "apk-0123456789abcdef0123456789abcdef", "name": "Tel APK", "os": "android", "os_version": "14", "manufacturer": "Google", "model": "Pixel 8",
             "battery": 70, "charging": 0, "free_gb": 20, "total_gb": 128, "ip": "192.168.1.60", "interval_min": 30, "client": "apk", "app_version": "1.0.0", "sec_patch": "2026-09-05", "admin": True}
        c, j = post(K); kid = j.get("device_id")
        inv = json.loads(q("SELECT inventory FROM devices WHERE id=?", kid)[0][0])
        rec("APK: inventario con client, versione app, patch e amministratore", c == 200 and j.get("commands") == [] and inv.get("mobile_client") == "apk" and inv.get("agent_version") == "apk 1.0.0" and inv.get("security_patch") == "2026-09-05" and inv.get("mobile_admin") == 1, (c, j, inv))
        c, j = post(A); rec("telefono senza APK: nessun comando in risposta", c == 200 and j.get("commands") == [], j)
        c, j2 = post(K); rec("APK: la risposta indica la versione pubblicata e dove scaricarla", j2.get("apk", {}).get("version") == APKV and j2["apk"]["url"].endswith("?action=mobile_apk"), j2)
        c, j3 = post(A); rec("telefono senza APK: nessun avviso di versione", "apk" not in j3, j3)
        html = page(f"?view=device&id={kid}")
        rec("scheda APK: pulsanti Controlla ora, Blocca schermo, Ripristina", "mobile_cmd&amp;cmd=lock" in html or "mobile_cmd&cmd=lock" in html)
        rec("scheda APK: avviso app 1.0.0 con la versione pubblicata disponibile", f"app 1.0.0: disponibile la {APKV}" in html, html[html.find("Telefono con l"):][:300])
        html = page(f"?view=device&id={did}")
        rec("scheda check-in semplice: nessun pulsante di comando", "mobile_cmd" not in html)
        r = cpost(f"?action=mobile_cmd&cmd=lock", {"device_id": did}); rec("comando su un telefono senza APK rifiutato", q("SELECT COUNT(*) FROM mobile_cmds WHERE device_id=?", did)[0][0] == 0)
        r = cpost(f"?action=mobile_cmd&cmd=lock", {"device_id": kid}); r = cpost(f"?action=mobile_cmd&cmd=lock", {"device_id": kid})
        rec("blocco in coda, il doppio clic non duplica", q("SELECT COUNT(*) FROM mobile_cmds WHERE device_id=? AND type='lock' AND status='pending'", kid)[0][0] == 1)
        r = cpost(f"?action=mobile_cmd&cmd=wipe", {"device_id": kid, "confirm": "sbagliato"}); rec("ripristino senza il nome giusto: non accodato", q("SELECT COUNT(*) FROM mobile_cmds WHERE type='wipe'")[0][0] == 0)
        r = cpost(f"?action=mobile_cmd&cmd=wipe", {"device_id": kid, "confirm": "Tel APK"}); rec("ripristino con conferma: accodato", q("SELECT COUNT(*) FROM mobile_cmds WHERE type='wipe' AND status='pending'")[0][0] == 1)
        r = cpost(f"?action=mobile_cmd&cmd=boh", {"device_id": kid}); rec("comando sconosciuto rifiutato", q("SELECT COUNT(*) FROM mobile_cmds")[0][0] == 2)
        c, j = post(K); cm = j.get("commands", [])
        rec("check-in: consegna i comandi in coda", [x["type"] for x in cm] == ["lock", "wipe"] and all(x["id"] > 0 for x in cm), j)
        rec("comandi consegnati: stato sent", q("SELECT COUNT(*) FROM mobile_cmds WHERE status='sent'")[0][0] == 2)
        c, j = post(K); rec("senza esito vengono riproposti", [x["type"] for x in j.get("commands", [])] == ["lock", "wipe"], j)
        c, j = post(dict(K, done=[{"id": cm[0]["id"], "ok": True, "msg": ""}, {"id": cm[1]["id"], "ok": False, "msg": "ripristino remoto non consentito sul telefono"}]))
        rec("esiti: eseguito e non riuscito, niente più in coda", j.get("commands") == [] and q("SELECT status FROM mobile_cmds ORDER BY id") == [("done",), ("failed",)], (j, q("SELECT status,result FROM mobile_cmds")))
        html = page(f"?view=device&id={kid}"); rec("scheda: storico con esito e motivo", "eseguito" in html and "non riuscito" in html and "ripristino remoto non consentito" in html)
        rec("comandi nell'audit", q("SELECT COUNT(*) FROM audit WHERE action='mobile_cmd'")[0][0] == 2)
        other = {"token": TB, "id": K["id"], "client": "apk", "os": "android"}; c, j = post(other); rec("un altro cliente non può riusare l'id né ricevere comandi", c == 403, (c, j))
        cpost("?action=mobile_cmd&cmd=ping", {"device_id": kid}); q("UPDATE mobile_cmds SET created='2020-01-01T00:00:00Z' WHERE status='pending'")
        c, j = post(K); rec("comandi scaduti (24 h) non vengono consegnati", j.get("commands") == [] and q("SELECT status FROM mobile_cmds ORDER BY id DESC LIMIT 1") == [("expired",)], (j, q("SELECT status FROM mobile_cmds")))
        rg = cx.request.get(BASE + "?action=mobile_setup&u=https%3A%2F%2Fx.it%2Findex.php&t=st-abc&n=%3Cb%3EProva%3C%2Fb%3E&i=5"); bd = rg.text()
        rec("pagina del QR: pulsante verso myrmm:// con dati, senza HTML iniettato", rg.status == 200 and 'href="myrmm://setup?u=https%3A%2F%2Fx.it%2Findex.php&amp;t=st-abc&amp;n=%3Cb%3EProva%3C%2Fb%3E&amp;i=15"' in bd and "<b>Prova</b>" not in bd, bd[bd.find("<a "):][:200])
        rec("nessun errore JS", not errs, errs[:3]); br.close()

    # offline: scan_offline apre l'alert con la soglia propria e lo chiude al check-in
    q("UPDATE devices SET last_seen=? WHERE id=?", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300 * 60)), did)
    c, j = post(A)
    rec("check-in dopo un'assenza: nessun alert offline aperto", not q("SELECT 1 FROM alerts WHERE device_id=? AND type='offline' AND status='open'", did))

    for _ in range(12): post(dict(A, token="st-" + "q" * 32))
    c, j = post(A); rec("troppi token errati: 429", c == 429, (c, j))
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    bad = sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l)))[:10]
    rec("nessun errore PHP", not bad, bad)
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok")
sys.exit(1 if f else 0)
