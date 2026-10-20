#!/usr/bin/env python3
"""Funzioni mostrate per tipo di device e inventario ricco dell'APK (1.53.0).
Uso: python3 ci/devkind_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8830; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-kind-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite")
res = []

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
    q("INSERT OR IGNORE INTO sites(name,created) VALUES('Acme',?)", now)
    TA = "st-" + "a" * 32
    q("INSERT INTO site_tokens(site,token,created) VALUES('Acme',?,?)", TA, now)
    inv = json.dumps({"os": "Windows 11", "agent_version": "1.0"})
    def mk(host, os_, invj): 
        q("INSERT INTO devices(hostname,os,api_key,site,created,last_seen,inventory) VALUES(?,?,?,'Acme',?,?,?)", host, os_, "k" + host, now, now, invj)
        return q("SELECT id FROM devices WHERE hostname=?", host)[0][0]
    idw = mk("WIN-PC", "windows", inv); idl = mk("LNX-SRV", "linux", json.dumps({"os": "Ubuntu 24.04"})); idm = mk("MAC-1", "darwin", json.dumps({"os": "macOS 14"}))
    A = {"token": TA, "id": "pixel-0001-abcdef", "name": "Telefono di Mario", "os": "android", "os_version": "14", "manufacturer": "Google", "model": "Pixel 8",
         "battery": 80, "charging": 0, "free_gb": 42.5, "total_gb": 128, "ip": "192.168.1.50", "interval_min": 60, "client": "apk", "app_version": "1.2.0", "sec_patch": "2026-09-05", "admin": 1,
         "uptime_h": 52.5, "ram_gb": 7.5, "ram_pct": 61, "batt_temp": 31.2, "batt_health": "buona", "net": "Wi-Fi",
         "details": {"sdk": 34, "build": "AP1A.240505", "abi": "arm64-v8a", "cores": 8, "kernel": "5.15.0", "locale": "it-IT", "tz": "Europe/Rome", "screen": "1080x2400 @420dpi", "carrier": "TIM",
                     "encrypted": 1, "screen_lock": 1, "adb": 0, "dev_options": 0, "root_hint": 0, "hardware": "tensor", "board": "shiba",
                     "apps": [{"name": "Chrome", "version": "125.0", "pkg": "com.android.chrome", "installed": "2025-01-02"}, {"name": "Banca", "version": "3.1", "pkg": "it.banca", "installed": "2025-03-04"}], "apps_system": 90, "apps_total": 92}}
    r = urllib.request.urlopen(urllib.request.Request(BASE + "?action=mobile_checkin", data=json.dumps(A).encode(), headers={"Content-Type": "application/json"}), timeout=10)
    idp = json.loads(r.read())["device_id"]
    row = q("SELECT inventory, full_inv, full_inv_at FROM devices WHERE id=?", idp)[0]
    iv = json.loads(row[0]); fi = json.loads(row[1] or "{}")
    rec("APK: inventario vivo (RAM, uptime, rete, batteria)", iv.get("ram_gb") == 7.5 and iv.get("ram_pct") == 61 and iv.get("uptime_h") == 52.5 and iv.get("network_type") == "Wi-Fi" and iv.get("battery_health") == "buona" and iv.get("battery_temp") == 31.2 and iv.get("last_boot", "").endswith("UTC"), iv)
    rec("APK: inventario completo salvato (sistema, hardware, telefono, app)", fi.get("system", {}).get("os_arch") == "arm64-v8a" and fi.get("hardware", {}).get("cpu_cores") == 8 and fi.get("mobile", {}).get("Operatore") == "TIM" and fi.get("mobile", {}).get("Cifratura dei dati") == "sì" and [a["name"] for a in fi.get("software", [])] == ["Banca", "Chrome"] and row[2], fi)
    A2 = dict(A); del A2["details"]; A2["battery"] = 70
    urllib.request.urlopen(urllib.request.Request(BASE + "?action=mobile_checkin", data=json.dumps(A2).encode(), headers={"Content-Type": "application/json"}), timeout=10).read()
    rec("check-in senza dettagli: l'inventario completo resta", len(json.loads(q("SELECT full_inv FROM devices WHERE id=?", idp)[0][0]).get("software", [])) == 2)

    with sync_playwright() as pw:
        br = pw.chromium.launch(); cx = br.new_context(viewport={"width": 1360, "height": 900}); p = cx.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        p.wait_for_load_state()
        def dev(i):
            p.goto(BASE + f"?view=device&id={i}"); p.wait_for_load_state()
            return p.content(), [a.inner_text().strip() for a in p.query_selector_all(".dnav a")]
        hw, tw = dev(idw); hl, tl = dev(idl); hm, tm = dev(idm); hp, tp = dev(idp)
        rec("Windows: patch, servizi, riavvio, comandi PowerShell, sessione e chat", all(x in hw for x in ("Servizi · Windows", "Riavvio e spegnimento", "PowerShell o cmd", "Chat con l", "Sessione")) and "Salute e patch" in " ".join(tw), tw)
        rec("Linux: niente patch Windows né chat; servizi systemd e shell Linux", "Servizi · systemd" in hl and "shell Linux" in hl and "Chat con l" not in hl and "aggiornamenti di Windows" not in hl and not any("patch" in x.lower() for x in tl), (tl, "Servizi · systemd" in hl, "shell Linux" in hl))
        rec("macOS: launchd e shell macOS, niente patch", "Servizi · launchd" in hm and "shell macOS" in hm and "aggiornamenti di Windows" not in hm)
        rec("Android: nessuna scheda Metriche, Script, Accesso remoto", not any(x.startswith(("Metriche", "Script", "Accesso remoto")) for x in tp), tp)
        rec("Android: niente servizi, riavvio, comandi, schedulazioni, patch, tunnel, chat, disinstalla agent", not any(x in hp for x in ("Servizi ·", "Riavvio e spegnimento", "Esegui un comando", "Schedulazioni e monitor", "Scansiona patch", "Tunnel", "Chat con l", "Sessione", "disinstalla agent")), [x for x in ("Servizi ·", "Riavvio e spegnimento", "Esegui un comando", "Schedulazioni e monitor", "Scansiona patch", "Tunnel", "Chat con l", "Sessione", "disinstalla agent") if x in hp])
        rec("Android: restano check-in, comandi del telefono, hardware, elenco app e batteria", all(x in hp for x in ("Blocca schermo", "Controlla ora", "Telefono", "Cifratura dei dati", "Chrome", "Salute batteria")) and any(x.startswith("Hardware") for x in tp), tp)
        rec("Android: riquadro con 'app' invece di 'agent'", "versione app" in hp and "versione agent" not in hp)
        p.goto(BASE + "?view=inventory"); p.wait_for_load_state()
        cells = p.evaluate("""() => { const o = {}; document.querySelectorAll('#invT tbody tr').forEach(r => { const h = r.querySelector('.c-host'); o[h.innerText.split(' ')[0]] = {patch: r.querySelector('.c-patch').innerText.trim(), rd: r.querySelector('.c-rd').innerText.trim(), f: r.dataset.f}; }); return o; }""")
        rec("lista: telefono con '—' in Patch e RustDesk, senza flag 'noinv'", cells.get("Telefono", {}).get("patch") == "—" and cells["Telefono"]["rd"] == "—" and "noinv" not in cells["Telefono"]["f"], cells)
        rec("lista: Windows ha il conteggio patch, Linux/macOS '—'", cells["WIN-PC"]["patch"] == "0" and cells["LNX-SRV"]["patch"] == "—" and cells["MAC-1"]["patch"] == "—", cells)
        rec("lista: il flag 'senza RustDesk' resta solo dove ha senso", "noinv" in cells["WIN-PC"]["f"])
        rec("nessun errore JS", not errs, errs[:3]); br.close()
    # azioni di gruppo: il telefono non riceve richieste di inventario/agent
    q("UPDATE devices SET full_inv_req=0, agent_push=0")
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    bad = sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l)))[:10]
    rec("nessun errore PHP", not bad, bad)
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok")
sys.exit(1 if f else 0)
