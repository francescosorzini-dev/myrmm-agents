#!/usr/bin/env python3
"""Backup 1.49: strumenti, abbinamento automatico dal software, sonda PowerShell, esiti, alert, report.
Uso: python3 ci/backup_test.py"""
import email, os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, io, zipfile, hashlib, csv, threading, socketserver, base64, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8824; SMTP_PORT = 8825; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-rc-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32, "SMTP_HOST": "127.0.0.1", "SMTP_PORT": SMTP_PORT, "SMTP_SECURE": "none", "REPORT_EMAIL": "boss@example.it", "ALERT_EMAIL_FROM": "myrmm@example.it"}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)

errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite")
res = []
def rec(name, ok, info=""):
    res.append((name, bool(ok))); print(("OK   " if ok else "FAIL ") + name + (("  [" + str(info)[:300] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def ts(days=0, hours=0): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400 - hours * 3600))
def hb(key, body=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body or {"inventory": {"os": "Windows 10 Pro"}}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"}), timeout=60).read() or b"{}")
def result(key, jid, out, code=0):
    urllib.request.urlopen(urllib.request.Request(BASE + "?action=result", data=json.dumps({"job_id": jid, "exit_code": code, "stdout": out}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"}), timeout=30).read()
def probe(tools):
    """Risposta finta della sonda: tools = {tool_id: [(ts|None, msg, err), ...]}"""
    return "MYRMM_BK " + json.dumps({"v": 1, "full": True, "host": "X", "tools": [{"id": tid, "checks": [{"i": i, "ts": c[0], "tsf": None, "msg": c[1], "err": c[2], "run": None} for i, c in enumerate(cs)]} for tid, cs in tools.items()]})
def last_job(dev_id): 
    r = q("SELECT id,script FROM jobs WHERE device_id=? AND origin='backup' ORDER BY id DESC LIMIT 1", dev_id); return r[0] if r else None

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
    now = ts()
    for n in ("Acme", "Beta"): q("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", n, now)
    def addev(hn, site, os_, osname, software):
        full = {"software": [{"name": s, "version": "1", "publisher": "x"} for s in software], "security": {"av": {"present": True, "enabled": True, "updated": True}}, "system": {"os": os_}}
        q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,full_inv,full_inv_at,created) VALUES(?,?,?,?,?,?,?,?,?)", hn, osname, "k-" + hn, site, now, json.dumps({"os": os_}), json.dumps(full), now, now)
    addev("A-PC1", "Acme", "Windows 10 Pro", "windows", ["7-Zip", "Veeam Agent for Microsoft Windows"])
    addev("A-PC2", "Acme", "Windows 11 Pro", "windows", ["Acronis Cyber Protect Home Office", "Chrome"])
    addev("A-SRV", "Acme", "Windows Server 2019 Standard", "windows", ["7-Zip"])
    addev("A-SRV2", "Acme", "Windows Server 2022 Standard", "windows", ["SuperSafe Backup Pro 9", "Notepad++"])
    addev("B-PC1", "Beta", "Windows 11 Pro", "windows", ["Veeam Agent for Microsoft Windows"])
    addev("A-LNX", "Acme", "Ubuntu 22.04", "linux", ["Veeam Agent for Linux"])
    dev = {r[1]: r[0] for r in q("SELECT id,hostname FROM devices")}
    h2 = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('beta',?, 'operator','Beta',1,?,0)", h2, now)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('vis',?, 'viewer','',1,?,0)", h2, now)
    H = {"Origin": f"http://127.0.0.1:{PORT}"}
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def login(ctx, user, pw_=PW):
            pg = ctx.new_page(); pg.goto(BASE); pg.fill("input[name=username]", user); pg.click("button[type=submit]")
            pg.wait_for_selector("input[name=password]", timeout=5000); pg.fill("input[name=password]", pw_); pg.click("button[type=submit]"); pg.wait_for_selector(".rail", timeout=8000); return pg
        c = br.new_context(viewport={"width": 1360, "height": 900}); p = login(c, "admin"); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("dialog", lambda d: d.accept())
        def get(url, ctx=c): return ctx.request.get(BASE + url)
        def post(url, data, ctx=c): return ctx.request.post(BASE + url, data=urllib.parse.urlencode(data, doseq=True), headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}), max_redirects=0)

        # --- strumenti predefiniti e pagina
        get("?view=backup")
        tools = {r[1]: r[0] for r in q("SELECT id,`key` FROM bk_tools")}
        rec("strumenti predefiniti creati", len(tools) >= 9 and {"wsb", "veeam_agent", "veeam_br", "acronis"} <= set(tools), tools)
        for tab in ("stato", "strumenti", "abbinamenti", "prova"):
            r = get("?view=backup&tab=" + tab); rec("pagina Backup · " + tab, r.status == 200 and "Controllo dei backup" in r.text(), r.status)
        r = get("?view=backup&tab=strumenti&edit=new"); rec("modulo nuovo strumento", r.status == 200 and "bkrows" in r.text() and "bktpl" in r.text())
        r = get("?view=backup&tab=strumenti&edit=%d" % tools["veeam_agent"]); rec("modulo di modifica mostra i controlli", "Veeam Agent" in r.text() and 'value="190"' in r.text() or "190" in r.text())
        rec("voce Backup nel menu", "view=backup" in get("?view=dashboard").text())

        # --- abbinamento automatico dal software installato
        r = get("?view=backup&tab=abbinamenti").text()
        def row(hn): 
            m = re.search(r"<tr><td><a[^>]*>%s</a>.*?</tr>" % re.escape(hn), r, re.S); return m.group(0) if m else ""
        rec("A-PC1: Veeam Agent abbinato dal software", "Veeam Agent for Windows" in row("A-PC1") and "software installato" in row("A-PC1"), row("A-PC1")[:300])
        rec("A-PC2: Acronis abbinato dal software", "Acronis Cyber Protect" in row("A-PC2"), row("A-PC2")[:300])
        rec("A-SRV: Windows Server Backup abbinato perché server", "Windows Server Backup" in row("A-SRV") and "server Windows" in row("A-SRV"), row("A-SRV")[:300])
        rec("Linux escluso dall'abbinamento", row("A-LNX") == "")
        rec("software di backup non riconosciuto suggerito", "SuperSafe Backup Pro 9" in r and "Crea strumento" in r)

        # --- sonda: job accodato dall'heartbeat, configurazione in base64
        hb("k-A-PC1"); j = last_job(dev["A-PC1"])
        rec("l'heartbeat accoda la sonda per A-PC1", j is not None)
        m = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", j[1]) if j else None
        cfgj = json.loads(base64.b64decode(m.group(1))) if m else {}
        rec("configurazione in base64 con lo strumento giusto", [t["id"] for t in cfgj.get("tools", [])] == [tools["veeam_agent"]] and cfgj.get("full") is True, cfgj)
        rec("nessun testo della configurazione fuori dal base64", "Failed|Error" not in j[1] and "Veeam Agent'" not in j[1])
        rec("A-SRV: sonda per Windows Server Backup", (lambda jj: jj is not None)(hb("k-A-SRV", {"inventory": {"os": "Windows Server 2019 Standard"}}) is not None and last_job(dev["A-SRV"])))
        hb("k-A-PC1"); rec("niente doppioni di job", q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin='backup'", dev["A-PC1"])[0][0] == 1)
        hb("k-A-LNX"); rec("Linux: nessuna sonda", last_job(dev["A-LNX"]) is None)

        # --- esiti
        VA = tools["veeam_agent"]
        result("k-A-PC1", j[0], probe({VA: [(ts(hours=5), "Backup job finished with Success", ""), (None, "", "")]}))
        s = q("SELECT state,last_success,why FROM bk_status WHERE device_id=? AND tool_id=?", dev["A-PC1"], VA)
        rec("esito ok: stato ok", s and s[0][0] == "ok" and s[0][2] == "software", s)
        rec("nessun alert con backup ok", not q("SELECT 1 FROM alerts WHERE device_id=? AND type LIKE 'backup:%' AND status='open'", dev["A-PC1"]))
        # fallito più recente del riuscito
        q("UPDATE bk_probe SET ts=0 WHERE device_id=?", dev["A-PC1"]); hb("k-A-PC1"); j = last_job(dev["A-PC1"])
        result("k-A-PC1", j[0], probe({VA: [(ts(hours=30), "ok", ""), (ts(hours=2), "Job failed: Error 0x80", "")]}))
        s = q("SELECT state,detail FROM bk_status WHERE device_id=? AND tool_id=?", dev["A-PC1"], VA)
        rec("fallimento più recente = stato fallito", s and s[0][0] == "fail" and "failed" in s[0][1].lower(), s)
        al = q("SELECT severity,message FROM alerts WHERE device_id=? AND type=? AND status='open'", dev["A-PC1"], "backup:%d" % VA)
        rec("alert aperto per il fallimento", len(al) == 1 and al[0][0] == "warn", al)
        # fermo da 10 giorni
        q("UPDATE bk_probe SET ts=0 WHERE device_id=?", dev["A-PC1"]); hb("k-A-PC1"); j = last_job(dev["A-PC1"])
        result("k-A-PC1", j[0], probe({VA: [(ts(10), "old", ""), (None, "", "")]}))
        s = q("SELECT state FROM bk_status WHERE device_id=? AND tool_id=?", dev["A-PC1"], VA)
        rec("riuscito vecchio = fermo", s[0][0] == "stale", s)
        rec("alert per backup fermo con i giorni", any("10 giorni" in a[0] for a in q("SELECT message FROM alerts WHERE device_id=? AND type=? AND status='open'", dev["A-PC1"], "backup:%d" % VA)), q("SELECT message FROM alerts WHERE device_id=?", dev["A-PC1"]))
        # ripresa
        q("UPDATE bk_probe SET ts=0 WHERE device_id=?", dev["A-PC1"]); hb("k-A-PC1"); j = last_job(dev["A-PC1"])
        result("k-A-PC1", j[0], probe({VA: [(ts(hours=1), "ok", ""), (None, "", "")]}))
        rec("alert chiuso quando il backup riparte", not q("SELECT 1 FROM alerts WHERE device_id=? AND type=? AND status='open'", dev["A-PC1"], "backup:%d" % VA))
        # nessun dato: strumento non verificato → da verificare, niente alert
        AC = tools["acronis"]; hb("k-A-PC2"); j2 = last_job(dev["A-PC2"])
        result("k-A-PC2", j2[0], probe({AC: [(None, "", "nessun file recente"), (None, "", "nessun file recente")]}))
        s = q("SELECT state,detail FROM bk_status WHERE device_id=? AND tool_id=?", dev["A-PC2"], AC)
        rec("senza dati e non rigoroso = da verificare", s and s[0][0] == "nodata" and "nessun file" in s[0][1], s)
        rec("da verificare non apre alert", not q("SELECT 1 FROM alerts WHERE device_id=? AND type LIKE 'backup:%'", dev["A-PC2"]))
        q("UPDATE bk_tools SET strict=1 WHERE id=?", AC); 
        # sonda risultato corrotto
        hb("k-B-PC1"); j3 = last_job(dev["B-PC1"]); result("k-B-PC1", j3[0], "boom", 1)
        rec("risultato illeggibile non rompe nulla", q("SELECT err FROM bk_probe WHERE device_id=?", dev["B-PC1"])[0][0] != "")

        # --- modifica e creazione di strumenti
        newt = {"name": "SuperSafe Backup", "match": "^SuperSafe Backup", "fresh_h": "36", "alert": "1", "severity": "crit",
                "c[0][type]": "logfile", "c[0][role]": "success", "c[0][label]": "Riuscito", "c[0][path]": "C:\\ProgramData\\SuperSafe\\*.log", "c[0][pattern]": "Job (completed|done)", "c[0][ts_regex]": "^(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})", "c[0][ts_format]": "yyyy-MM-dd HH:mm:ss", "c[0][tail_kb]": "256", "c[0][files]": "2", "c[0][lookback_h]": "48",
                "c[1][type]": "registry", "c[1][role]": "success", "c[1][label]": "Chiave", "c[1][rpath]": "HKLM:\\SOFTWARE\\SuperSafe", "c[1][value]": "LastOk", "c[1][format]": "unix",
                "c[2][type]": "service", "c[2][name]": "SuperSafeSvc", "c[2][require]": "1", "c[2][label]": "Servizio",
                "c[3][type]": "script", "c[3][role]": "success", "c[3][label]": "Script", "c[3][body]": "Get-Date"}
        r = post("?action=bk_save", newt); rec("salvataggio nuovo strumento", r.status in (302, 303), r.status)
        st_ = q("SELECT id,name,fresh_h,severity,checks,builtin FROM bk_tools WHERE name='SuperSafe Backup'")
        rec("strumento salvato con 4 controlli di tipo diverso", st_ and [c["type"] for c in json.loads(st_[0][4])] == ["logfile", "registry", "service", "script"] and st_[0][5] == 0, st_)
        ck = json.loads(st_[0][4]) if st_ else [{}]*4
        rec("campi dei controlli conservati", ck[0].get("tail_kb") == 256 and ck[0].get("ts_format") == "yyyy-MM-dd HH:mm:ss" and ck[1].get("format") == "unix" and ck[1].get("path") == "HKLM:\\SOFTWARE\\SuperSafe" and ck[2].get("require") == 1, ck)
        SS = st_[0][0]
        r = get("?view=backup&tab=abbinamenti").text(); rec("il nuovo strumento si abbina da solo a A-SRV2", "SuperSafe Backup" in re.search(r"<tr><td><a[^>]*>A-SRV2</a>.*?</tr>", r, re.S).group(0))
        rec("il suggerimento sparisce una volta coperto", "SuperSafe Backup Pro 9" not in r.split("Software di backup non riconosciuto")[1].split("</table>")[0] if "Software di backup non riconosciuto" in r else True)
        hb("k-A-SRV2", {"inventory": {"os": "Windows Server 2022 Standard"}}); j4 = last_job(dev["A-SRV2"]); sc = j4[1] if j4 else ""
        cfg4 = json.loads(base64.b64decode(re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", sc).group(1)))
        rec("la sonda di A-SRV2 contiene gli strumenti abbinati (WSB + nuovo)", sorted(t["id"] for t in cfg4["tools"]) == sorted([tools["wsb"], SS]), [t["id"] for t in cfg4["tools"]])
        rec("lo script utente viaggia solo dentro al base64", "Get-Date" not in sc.split("FromBase64String")[0].split("function Chk")[0] and "SuperSafeSvc" not in sc)
        # servizio fermo con require → fallito
        result("k-A-SRV2", j4[0], probe({SS: [(ts(hours=1), "line", ""), (None, "", ""), (None, "", ""), (None, "", "")]}) .replace('"run": null', '"run": false', 3))
        s = q("SELECT state FROM bk_status WHERE device_id=? AND tool_id=?", dev["A-SRV2"], SS)
        rec("servizio obbligatorio non attivo = fallito", s and s[0][0] in ("fail",), s)
        # validazioni
        bad = dict(newt, **{"match": "([unclosed"}); r = post("?action=bk_save", bad); rec("espressione di abbinamento non valida respinta", "non+valida" in (r.headers.get("location") or "") or "valida" in (r.headers.get("location") or ""), r.headers.get("location"))
        r = post("?action=bk_save", {"name": "Vuoto"}); rec("senza controlli respinto", q("SELECT COUNT(*) FROM bk_tools WHERE name='Vuoto'")[0][0] == 0)
        r = post("?action=bk_save", {"name": "Reg", "c[0][type]": "registry", "c[0][rpath]": "C:\\evil", "c[0][value]": "x"}); rec("chiave di registro non valida respinta", q("SELECT COUNT(*) FROM bk_tools WHERE name='Reg'")[0][0] == 0)
        # modifica di un predefinito, poi ripristino
        r = post("?action=bk_save", {"id": tools["wsb"], "name": "WSB modificato", "servers": "1", "fresh_h": "12", "c[0][type]": "eventlog", "c[0][log]": "Application", "c[0][ids]": "1,2"})
        rec("predefinito modificabile", q("SELECT name,fresh_h FROM bk_tools WHERE id=?", tools["wsb"])[0] == ("WSB modificato", 12))
        post("?action=bk_restore", {"id": tools["wsb"]}); rec("ripristino del predefinito", q("SELECT name,fresh_h FROM bk_tools WHERE id=?", tools["wsb"])[0] == ("Windows Server Backup", 72))
        r = post("?action=bk_del", {"id": tools["wsb"]}); rec("predefinito non eliminabile", q("SELECT COUNT(*) FROM bk_tools WHERE id=?", tools["wsb"])[0][0] == 1)
        post("?action=bk_dup", {"id": SS}); rec("duplica", q("SELECT COUNT(*) FROM bk_tools WHERE name LIKE 'SuperSafe Backup%(copia)'")[0][0] == 1)
        dup = q("SELECT id FROM bk_tools WHERE name LIKE '%(copia)'")[0][0]; post("?action=bk_del", {"id": dup}); rec("elimina personalizzato", q("SELECT COUNT(*) FROM bk_tools WHERE id=?", dup)[0][0] == 0)
        exp = json.dumps({"name": "Importato", "match": "Foo", "fresh_h": 24, "checks": [{"type": "eventlog", "log": "Application", "ids": "7", "role": "success"}]})
        post("?action=bk_import", {"json": exp}); rec("importa da JSON", q("SELECT COUNT(*) FROM bk_tools WHERE name='Importato'")[0][0] == 1)
        post("?action=bk_import", {"json": "non json"}); rec("JSON non valido respinto", True)
        imp = q("SELECT id FROM bk_tools WHERE name='Importato'")[0][0]; post("?action=bk_toggle", {"id": imp}); rec("disattiva", q("SELECT enabled FROM bk_tools WHERE id=?", imp)[0][0] == 0)
        # forza / escludi
        r = post("?action=bk_ov", {"device_id": dev["B-PC1"], "tool_id": tools["wsb"], "mode": "on"}); rec("forza uno strumento a mano", "manual" in str(q("SELECT mode FROM bk_override")) or q("SELECT mode FROM bk_override WHERE device_id=?", dev["B-PC1"])[0][0] == "on")
        r = get("?view=backup&tab=abbinamenti").text; r = get("?view=backup&tab=abbinamenti").text(); rec("abbinamento forzato visibile", "forzato a mano" in re.search(r"<tr><td><a[^>]*>B-PC1</a>.*?</tr>", r, re.S).group(0))
        post("?action=bk_ov", {"device_id": dev["A-PC1"], "tool_id": VA, "mode": "off"}); r = get("?view=backup&tab=abbinamenti").text()
        rec("escludi uno strumento a mano", "Veeam Agent" not in re.search(r"<tr><td><a[^>]*>A-PC1</a>.*?</td><td[^>]*>.*?</td><td>(.*?)</td>", r, re.S).group(1))
        q("UPDATE bk_probe SET ts=0 WHERE device_id=?", dev["A-PC1"]); hb("k-A-PC1")
        rec("lo strumento escluso toglie stato e sonda", not q("SELECT 1 FROM bk_status WHERE device_id=? AND tool_id=?", dev["A-PC1"], VA))
        post("?action=bk_ov", {"device_id": dev["A-PC1"], "tool_id": VA, "mode": ""})

        # --- prova e permessi
        r = post("?action=bk_test", {"device_id": dev["A-PC2"], "tool_id": AC}); jt = last_job(dev["A-PC2"])
        rec("«Prova» accoda una sonda con un solo strumento", jt is not None and [t["id"] for t in json.loads(base64.b64decode(re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", jt[1]).group(1)))["tools"]] == [AC])
        hb("k-A-PC2"); jt = last_job(dev["A-PC2"])
        result("k-A-PC2", jt[0], probe({AC: [(ts(hours=3), "Backup completed successfully", ""), (None, "", "")]}))
        r = get("?view=backup&tab=prova&dev=%d&tool=%d" % (dev["A-PC2"], AC)).text()
        rec("pagina Prova mostra data e riga trovate", "Backup completed successfully" in r and "Esito calcolato" in r and "Script PowerShell" in r)
        r = get("?view=backup&tab=stato").text(); rec("pagina Stato elenca gli esiti", "A-PC2" in r and "Acronis Cyber Protect" in r and "da verificare" in r)
        r = get("?view=backup&tab=stato&st=ok").text(); rec("filtro per stato", "A-PC2" in r)
        cv = br.new_context(); pv = login(cv, "vis")
        rec("viewer vede lo stato", cv.request.get(BASE + "?view=backup&tab=stato").status == 200)
        rec("viewer non vede il modulo di modifica", "bkrows" not in cv.request.get(BASE + "?view=backup&tab=strumenti&edit=new").text())
        r = cv.request.post(BASE + "?action=bk_save", data=urllib.parse.urlencode(newt), headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}), max_redirects=0); rec("viewer non può salvare", r.status in (401, 403))
        r = cv.request.post(BASE + "?action=bk_scan", data="", headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}), max_redirects=0); rec("viewer non può avviare la lettura", r.status in (401, 403))
        cb = br.new_context(); pb = login(cb, "beta")
        r = cb.request.get(BASE + "?view=backup&tab=abbinamenti").text(); rec("operatore Beta vede solo i suoi device", "B-PC1" in r and "A-PC1" not in r and "A-SRV" not in r)
        r = cb.request.get(BASE + "?view=backup&tab=stato").text(); rec("stato filtrato per cliente", "A-PC2" not in r)
        r = cb.request.post(BASE + "?action=bk_test", data=urllib.parse.urlencode({"device_id": dev["A-PC2"], "tool_id": AC}), headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}), max_redirects=0)
        rec("operatore non prova device di altri clienti", "non+validi" in (r.headers.get("location") or ""), r.headers.get("location"))
        r = post("?action=bk_scan", {}); rec("«Controlla ora» ripianifica", r.status in (302, 303) and q("SELECT COUNT(*) FROM bk_probe WHERE ts=0")[0][0] >= 1)

        # --- report
        q("UPDATE bk_tools SET enabled=1 WHERE id=?", imp)
        r = post("?action=rc_run", {"report": "backup", "mode": "per", "pk": "last_30", "sites[]": "Acme", "formats[]": ["json", "csvl"]})
        hid = q("SELECT id,name FROM rc_history ORDER BY id DESC")
        rec("report Backup generato", r.status in (302, 303) and hid, r.status)
        body = ""
        for hid_, nm in hid:
            if nm.endswith(".json"): body = get("?action=rc_get&id=%d" % hid_).text()
        rec("report: stato per strumento", "Acronis Cyber Protect" in body and "Windows Server Backup" in body, body[:300])
        rec("report: copertura (server senza backup / da verificare)", "Copertura del backup" in body and "A-SRV" in body)
        rec("report: modelli non verificati segnalati", "Modello di lettura non ancora verificato" in body)
        for rep in ("exec", "security", "compliance"):
            r = post("?action=rc_run", {"report": rep, "mode": "per", "pk": "last_30", "sites[]": "Acme", "formats[]": "pdf"}); rec("report %s con il nuovo backup" % rep, r.status in (302, 303), r.status)
        r = get("?view=dossier"); rec("dossier si apre", r.status == 200)

        rec("nessun errore JS nella console", not errs, errs[:2])
        errtxt = open(os.path.join(tmp, "php.err")).read()
        bad = [l for l in errtxt.splitlines() if re.search(r"Fatal|Warning|Notice|Deprecated|Uncaught|Parse error", l)]
        rec("nessun errore PHP a fine test", not bad, "\n".join(bad[:6]))
        br.close()
finally:
    sp.terminate()
    print("\nTemp:", tmp)
fails = [n for n, ok in res if not ok]
print("\n%d/%d ok" % (len(res) - len(fails), len(res)))
sys.exit(1 if fails else 0)
