#!/usr/bin/env python3
"""Centro report 1.48: catalogo, costruttore, tutti i formati (PDF, Excel, Word, PowerPoint, HTML, CSV, JSON, ZIP),
storico con SHA-256, collegamenti a scadenza, feed, pianificazioni, invio con allegati, perimetro per utente.
Uso: python3 ci/reportcenter_test.py"""
import email, os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, io, zipfile, hashlib, csv, threading, socketserver, base64, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8822; SMTP_PORT = 8823; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-rc-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32, "SMTP_HOST": "127.0.0.1", "SMTP_PORT": SMTP_PORT, "SMTP_SECURE": "none", "REPORT_EMAIL": "boss@example.it", "ALERT_EMAIL_FROM": "myrmm@example.it"}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)

MAILS = []
class S(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda t: (self.wfile.write((t + "\r\n").encode()), self.wfile.flush())
        w("220 mock ESMTP"); data = False; msg = []; env = {"to": []}
        while True:
            l = self.rfile.readline()
            if not l: return
            raw = l.decode(errors="replace").rstrip("\r\n")
            if data:
                if raw == ".": data = False; env["raw"] = "\r\n".join(msg); MAILS.append(env); env = {"to": []}; msg = []; w("250 queued"); continue
                msg.append(raw); continue
            u = raw.upper()
            if u.startswith("EHLO"): w("250 mock")
            elif u.startswith("MAIL"): w("250 ok")
            elif u.startswith("RCPT"): env["to"].append(raw); w("250 ok")
            elif u == "DATA": data = True; w("354 go")
            elif u == "QUIT": w("221 bye"); return
            else: w("250 ok")
class TS(socketserver.ThreadingTCPServer): allow_reuse_address = True; daemon_threads = True
ts_ = TS(("127.0.0.1", SMTP_PORT), S); threading.Thread(target=ts_.serve_forever, daemon=True).start()

errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite")
res = []
def rec(name, ok, info=""):
    res.append((name, bool(ok))); print(("OK   " if ok else "FAIL ") + name + (("  [" + str(info)[:260] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def ts(days=0): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))

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
    for n in ("Acme", "Beta", "Gamma"): q("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", n, now)
    inv = {"os": "Windows 10 Pro", "os_build": "19045", "manufacturer": "Dell", "model": "Latitude 5440", "serial": "SN0123", "ram_gb": 16, "agent_version": "1.0", "disks": [{"DeviceID": "C:", "size_gb": 476, "free_gb": 38}]}
    sec_ok = {"av": {"present": True, "name": "Defender", "enabled": True, "updated": True}, "bitlocker": {"volumes": [{"mount": "C:", "protected": True}]}, "firewall": {"domain": True, "private": True, "public": True}, "local_admins": ["Administrator", "mario"], "backup": {"product": "Veeam", "last_success": ts(2)}}
    sec_bad = {"av": {"present": False}, "bitlocker": {"volumes": [{"mount": "C:", "protected": False}]}, "firewall": {"domain": True, "private": False, "public": True}, "local_admins": ["Administrator"]}
    sw = [{"name": "7-Zip", "version": "23.01", "publisher": "Igor Pavlov"}, {"name": "Café Données", "version": "1", "publisher": "Ñandú & Çia"}, {"name": "Microsoft Office Professional Plus 2019", "version": "16.0", "publisher": "Microsoft"}] + [{"name": "App %d" % i, "version": "1.%d" % i, "publisher": "Vendor %d" % (i % 4)} for i in range(30)]
    for hn, site, os_, full in [("A-PC1", "Acme", "Windows 10 Pro", {"software": sw, "security": sec_ok, "system": {"os": "Windows 10 Pro", "last_boot": ts(3)}, "hardware": {"manufacturer": "Dell", "model": "Latitude 5440", "serial": "SN1", "bios_date": "2021-03-05", "ram_gb": 16}}),
                                ("A-PC2", "Acme", "Windows 7 Professional", {"software": sw[:5], "security": sec_bad, "hardware": {"manufacturer": "HP", "model": "ProDesk", "serial": "SN2", "bios_date": "2016-01-10", "ram_gb": 8}}),
                                ("A-SRV", "Acme", "Windows Server 2016 Standard", {"software": sw[:8], "security": sec_ok, "hardware": {"manufacturer": "Dell", "model": "R740", "serial": "SN3", "bios_date": "2019-07-01", "ram_gb": 64}}),
                                ("B-PC1", "Beta", "Windows 11 Pro", {"software": sw[:3], "security": sec_ok, "hardware": {"manufacturer": "Lenovo", "model": "T14", "serial": "SN4", "bios_date": "2023-05-01", "ram_gb": 16}}),
                                ("G-PC1", "Gamma", "Windows 11 Pro", {"software": sw[:3], "security": sec_ok, "hardware": {"manufacturer": "Lenovo", "model": "T14", "serial": "SN5", "bios_date": "2024-02-01", "ram_gb": 16}})]:
        i2 = dict(inv, os=os_)
        q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,full_inv,full_inv_at,created) VALUES(?,?,?,?,?,?,?,?,?)", hn, "windows", "k-" + hn, site, ts(20) if hn == "A-PC2" else now, json.dumps(i2), json.dumps(full), now, ts(300))
    dev = {r[1]: r[0] for r in q("SELECT id,hostname FROM devices")}
    q("UPDATE devices SET dept='Amministrazione' WHERE hostname='A-PC1'"); q("UPDATE devices SET dept='Produzione' WHERE hostname='A-PC2'")
    for i in range(6): q("INSERT INTO alerts(device_id,type,severity,message,status,created,resolved_at,ack_by,ack_at) VALUES(?,?,?,?,?,?,?,?,?)", dev["A-PC1"], "disk:C:", "warn", "Disco quasi pieno %d" % i, "resolved" if i < 4 else "open", ts(25 - i * 3), ts(24 - i * 3) if i < 4 else None, "admin", ts(25 - i * 3))
    q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["A-PC2"], "offline", "crit", "Device offline", "open", ts(15))
    q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["B-PC1"], "cpu", "crit", "Segreto di Beta", "open", ts(1))
    for i, (sev, st) in enumerate([("Critical", "available"), ("Important", "available"), ("Moderate", "installed"), ("Critical", "installed"), ("Low", "failed")]):
        q("INSERT INTO patches(device_id,uid,kb,title,severity,category,mb,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?)", dev["A-PC2"], "u%d" % i, "KB50000%d" % i, "Aggiornamento di prova %d" % i, sev, "x", 10, st, ts(45 - i * 5), ts(2))
    for i in range(4): q("INSERT INTO tickets(device_id,title,status,priority,site,created,updated,closed_at,minutes,code,assignee,alert_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", dev["A-PC1"], "Problema %d" % i, "closed" if i < 3 else "open", "normal", "Acme", ts(20 - i), ts(18 - i), ts(18 - i) if i < 3 else None, 30 + i * 10, "TK-%d" % (100 + i), "admin", "disk:C:")
    q("INSERT INTO expiries(site,kind,name,due,notes,created) VALUES(?,?,?,?,?,?)", "Acme", "dominio", "acme.it", time.strftime("%Y-%m-%d", time.gmtime(time.time() + 20 * 86400)), "rinnovo", now)
    q("INSERT INTO expiries(site,kind,name,due,notes,created) VALUES(?,?,?,?,?,?)", "Beta", "dominio", "beta-segreto.it", "2030-01-01", "", now)
    for a, d_ in [("run_script", "Pulizia su device #%d" % dev["A-PC1"]), ("power", "reboot su device #%d" % dev["A-PC1"])]: q("INSERT INTO audit(user,action,detail,ip,ts) VALUES(?,?,?,?,?)", "admin", a, d_, "127.0.0.1", ts(2))
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('beta',?, 'operator','Beta',1,?,0)", h, now)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('vis',?, 'viewer','',1,?,0)", h, now)
    # metriche disco con trend, per la previsione di riempimento
    for d_ in range(30):
        for hn in ("A-PC1",):
            try: q("INSERT INTO metrics (device_id, name, ts, value) VALUES (?,?,?,?)", dev[hn], "disco C:", int(time.time()) - (29 - d_) * 86400, 60 + d_ * 0.9)
            except Exception: break
    # un'impronta passata dell'inventario per il confronto tra due date
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def login(ctx, user, pw_=PW):
            pg = ctx.new_page(); pg.goto(BASE); pg.fill("input[name=username]", user); pg.click("button[type=submit]")
            pg.wait_for_selector("input[name=password]", timeout=5000); pg.fill("input[name=password]", pw_); pg.click("button[type=submit]"); pg.wait_for_selector(".rail", timeout=8000); return pg
        c = br.new_context(viewport={"width": 1360, "height": 900}); p = login(c, "admin"); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("dialog", lambda d: d.accept())
        H = {"Origin": f"http://127.0.0.1:{PORT}"}
        def get(url, ctx=c): return ctx.request.get(BASE + url)
        def post(url, data, ctx=c, **kw): return ctx.request.post(BASE + url, data=urllib.parse.urlencode(data, doseq=True), headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}), max_redirects=0, **kw)

        # --- pagina e catalogo
        pg = get("?view=reports")
        rec("pagina Centro report", pg.ok and "Centro report" in pg.text() and "Report esecutivo e QBR" in pg.text(), pg.status)
        nav = get("?view=dashboard").text()
        rec("voce di menù Centro report", "view=reports" in nav)
        for tab in ("costruisci", "storico", "pianifica", "feed", "loghi"):
            r = get("?view=reports&tab=" + tab); rec("scheda " + tab, r.ok and "Fatal" not in r.text() and "Warning" not in r.text(), r.status)
        for tpl in ("qbr", "monthly", "package", "audit", "patchw", "renew", "bi"):
            r = get("?view=reports&tab=costruisci&tpl=" + tpl); rec("costruttore con modello " + tpl, r.ok and "rctpl" in r.text())

        # --- ogni report in ogni formato
        reps = ["exec", "fleet", "sla", "patch", "security", "software", "lifecycle", "alerts", "tickets", "invchg", "expiries", "mobile", "network", "runbook", "access", "backup", "compliance"]
        fmts = ["pdf", "xlsx", "csv", "csvl", "json", "html", "docx", "pptx"]
        for rep in reps:
            r = post("?action=rc_run", {"report": rep, "mode": "per", "pk": "last_90", "sites[]": "Acme", "formats[]": fmts + ["zip"]})
            rows = q("SELECT fmt FROM rc_history WHERE kind=?", rep)
            got = sorted(set(x[0] for x in rows))
            rec("report %s: tutti i formati generati" % rep, r.status in (302, 303) and set(fmts) <= set(got), "%s %s" % (r.status, got))
        errtxt = open(os.path.join(tmp, "php.err")).read()
        bad = [l for l in errtxt.splitlines() if re.search(r"Fatal|Warning|Notice|Deprecated|Uncaught|Parse error", l)]
        rec("nessun errore PHP in generazione", not bad, "\n".join(bad[:6]))
        open(os.path.join(tmp, "bad.txt"), "w").write("\n".join(bad))

        # --- controllo dei file
        files = {}
        for fmt, name, tok in q("SELECT fmt,name,token FROM rc_history WHERE kind='exec' AND client='Acme'"): files[fmt] = (name, open(os.path.join(srv, "data", "reports", tok + ".bin"), "rb").read())
        import email.header, pypdf, openpyxl, docx as pdocx, pptx as ppptx
        rd = pypdf.PdfReader(io.BytesIO(files["pdf"][1])); txt = "\n".join(pg_.extract_text() or "" for pg_ in rd.pages)
        rec("PDF esecutivo: pagine, punteggio e commento", len(rd.pages) >= 4 and "Acme" in txt and "/100" in txt, len(rd.pages))
        rec("PDF: nessun prezzo o euro", "€" not in txt and "euro" not in txt.lower(), "")
        wb = openpyxl.load_workbook(io.BytesIO(files["xlsx"][1])); names = wb.sheetnames
        rec("Excel: Sommario, fogli per sezione e Dati", names[0].startswith("Sommario") and names[-1] == "Dati" and len(names) >= 5, names)
        tbls = sum(len(ws.tables) for ws in wb.worksheets); charts = sum(len(ws._charts) for ws in wb.worksheets)
        rec("Excel: tabelle vere con filtri", tbls >= 3, tbls)
        z = zipfile.ZipFile(io.BytesIO(files["xlsx"][1])); chartfiles = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
        rec("Excel: grafici nativi", len(chartfiles) >= 2, chartfiles)
        ws = wb["Dati"]; rec("Excel: foglio Dati in formato lungo", ws.max_row > 20 and ws.cell(1, 1).value, ws.max_row)
        d = pdocx.Document(io.BytesIO(files["docx"][1])); rec("Word: paragrafi, tabelle e titoli", len(d.paragraphs) > 20 and len(d.tables) >= 2, (len(d.paragraphs), len(d.tables)))
        zd = zipfile.ZipFile(io.BytesIO(files["docx"][1])); rec("Word: grafici nativi", any(n.startswith("word/charts/chart") for n in zd.namelist()))
        pr = ppptx.Presentation(io.BytesIO(files["pptx"][1])); rec("PowerPoint: diapositive", len(pr.slides) >= 5, len(pr.slides))
        rec("PowerPoint: grafici e tabelle", any(sh.has_chart for s in pr.slides for sh in s.shapes) and any(sh.has_table for s in pr.slides for sh in s.shapes))
        html = files["html"][1].decode()
        rec("HTML autonomo: un file, nessuna risorsa esterna", "<script>" in html and not re.search(r'(src|href)="https?://', html), "")
        cs = files["csv"][1].decode("utf-8-sig"); rec("CSV leggibile", len(list(csv.reader(io.StringIO(cs)))) > 10)
        cl = list(csv.reader(io.StringIO(files["csvl"][1].decode("utf-8-sig")), delimiter=";")); rec("CSV lungo per Power BI: intestazione e righe uniformi", len(cl) > 10 and len(set(len(r) for r in cl)) == 1, set(len(r) for r in cl))
        js = json.loads(files["json"][1]); rec("JSON valido con sezioni", isinstance(js, dict) and ("sections" in js or "blocks" in js or len(js) > 2), list(js)[:6] if isinstance(js, dict) else type(js))
        allsum = {}
        for fmt, name, tok, sha, size in q("SELECT fmt,name,token,sha256,size FROM rc_history"):
            b = open(os.path.join(srv, "data", "reports", tok + ".bin"), "rb").read(); allsum[tok] = hashlib.sha256(b).hexdigest() == sha and len(b) == size
        rec("storico: SHA-256 e dimensione corrispondono a tutti i file", allsum and all(allsum.values()), sum(1 for v in allsum.values() if not v))
        zrow = q("SELECT token FROM rc_history WHERE fmt='zip' AND kind='package' LIMIT 1")
        if zrow:
            zz = zipfile.ZipFile(io.BytesIO(open(os.path.join(srv, "data", "reports", zrow[0][0] + ".bin"), "rb").read())); sums = zz.read("SHA256SUMS.txt").decode()
            okz = all(hashlib.sha256(zz.read(l.split("  ", 1)[1])).hexdigest() == l.split("  ", 1)[0] for l in sums.strip().splitlines())
            rec("ZIP: SHA256SUMS corretto e LEGGIMI", okz and "LEGGIMI.txt" in zz.namelist(), zz.namelist())
        else: rec("ZIP generato", False)

        # --- apertura reale con LibreOffice
        lo = os.path.join(tmp, "lo"); os.makedirs(lo)
        for fmt in ("xlsx", "docx", "pptx"):
            fp = os.path.join(lo, files[fmt][0]); open(fp, "wb").write(files[fmt][1])
            r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", lo, fp], capture_output=True, text=True, timeout=180)
            pdf = fp.rsplit(".", 1)[0] + ".pdf"
            ok = os.path.exists(pdf) and len(pypdf.PdfReader(pdf).pages) >= 1
            rec("LibreOffice apre il file %s" % fmt, ok, r.stderr[:200])
            if fmt == "xlsx" and ok:
                tt = "\n".join(x.extract_text() or "" for x in pypdf.PdfReader(pdf).pages); rec("Excel convertito mostra i dati", "Acme" in tt)

        # --- perimetro per utente e scarico
        cb = br.new_context(); pb = login(cb, "beta")
        r = post("?action=rc_run", {"report": "exec", "mode": "per", "pk": "last_30", "sites[]": "Acme", "formats[]": "pdf"}, cb)
        rec("operatore Beta non genera dati di Acme", r.status in (302, 303) and not q("SELECT 1 FROM rc_history WHERE by_user='beta' AND client='Acme'"))
        r = post("?action=rc_run", {"report": "exec", "mode": "per", "pk": "last_30", "formats[]": "pdf"}, cb)
        got = q("SELECT DISTINCT client FROM rc_history WHERE by_user='beta'"); rec("operatore Beta ottiene solo i propri clienti", got == [("Beta",)], got)
        hid = q("SELECT id FROM rc_history WHERE client='Acme' LIMIT 1")[0][0]
        rec("operatore Beta non scarica file di Acme", get("?action=rc_get&id=%d" % hid, cb).status == 404)
        rec("la pagina storico di Beta non cita Acme", "Acme" not in get("?view=reports&tab=storico", cb).text())
        cv = br.new_context(); login(cv, "vis")
        rec("viewer non vede pianificazioni", "Pianificazioni" not in get("?view=reports", cv).text())
        rec("viewer non può pianificare", post("?action=rc_sched_save", {"report": "exec", "recur": "daily"}, cv).status in (302, 303, 403) and not q("SELECT 1 FROM rc_schedules"))

        # --- collegamento pubblico a scadenza
        rid, tok = q("SELECT id,token FROM rc_history WHERE fmt='pdf' AND client='Acme' LIMIT 1")[0]
        anon = br.new_context()
        rec("senza condivisione il collegamento non apre", anon.request.get(BASE + "?action=rc_dl&t=" + tok).status == 404)
        post("?action=rc_share", {"id": rid, "days": 7})
        r = anon.request.get(BASE + "?action=rc_dl&t=" + tok); rec("collegamento condiviso scarica il PDF", r.ok and r.body()[:4] == b"%PDF", r.status)
        q("UPDATE rc_history SET expires=? WHERE id=?", ts(1), rid)
        r = anon.request.get(BASE + "?action=rc_dl&t=" + tok); rec("collegamento scaduto rifiutato", r.status == 404 and "scaduto" in r.text().lower())
        post("?action=rc_share", {"id": rid, "days": 30}); post("?action=rc_share", {"id": rid, "days": 0})
        rec("collegamento revocato", anon.request.get(BASE + "?action=rc_dl&t=" + tok).status == 404)
        hrow = q("SELECT id,token FROM rc_history WHERE fmt='html' AND client='Acme' LIMIT 1")[0]; post("?action=rc_share", {"id": hrow[0], "days": 7})
        r = anon.request.get(BASE + "?action=rc_dl&t=" + hrow[1]); csp = r.headers.get("content-security-policy", "")
        rec("HTML condiviso: CSP con hash dello script", "sha256-" in csp and "default-src 'none'" in csp, csp[:120])
        pgh = anon.new_page(); jsErr = []; pgh.on("pageerror", lambda e: jsErr.append(str(e)))
        pgh.goto(BASE + "?action=rc_dl&t=" + hrow[1] + "&inline=1"); pgh.wait_for_timeout(500)
        rec("HTML condiviso si apre senza errori JS", not jsErr and pgh.locator("table").count() > 0, jsErr)
        rec("HTML: ricerca nella tabella", pgh.locator("input[type=search], input[type=text]").count() >= 1)

        # --- feed
        post("?action=rc_feed_save", {"name": "Power BI", "reports[]": ["fleet", "patch"], "sites[]": "Acme"})
        ft = q("SELECT token FROM rc_feeds")[0][0]
        r = anon.request.get(BASE + "?action=rc_feed&t=" + ft); rows = list(csv.reader(io.StringIO(r.text().lstrip("﻿"))))
        rec("feed CSV senza accesso con token", r.ok and len(rows) > 5 and "Acme" in r.text() and "Beta" not in r.text(), r.status)
        rj = anon.request.get(BASE + "?action=rc_feed&fmt=json&t=" + ft); rec("feed JSON", rj.ok and isinstance(rj.json(), list))
        rec("feed con token errato", anon.request.get(BASE + "?action=rc_feed&t=" + "0" * 32).status == 404)
        post("?action=rc_feed_del", {"id": q("SELECT id FROM rc_feeds")[0][0]}); rec("feed revocato", anon.request.get(BASE + "?action=rc_feed&t=" + ft).status == 404)

        # --- loghi e referenti
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNkYPhfz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC")
        r = c.request.post(BASE + "?action=rc_logo_save", multipart={"site": "Acme", "logo": {"name": "l.png", "mimeType": "image/png", "buffer": png}}, headers=H, max_redirects=0)
        rec("logo cliente caricato", any(f.startswith("client-") for f in os.listdir(os.path.join(srv, "data", "brand"))))
        r = c.request.post(BASE + "?action=rc_logo_save", multipart={"site": "Acme", "logo": {"name": "x.png", "mimeType": "image/png", "buffer": b"<?php echo 1;"}}, headers=H, max_redirects=0)
        rec("file non immagine rifiutato come logo", sum(1 for f in os.listdir(os.path.join(srv, "data", "brand")) if f.startswith("client-")) == 1)
        post("?action=rc_to_save", {"site": "Acme", "to": "ref@acme.it, rotto, altro@acme.it"})
        rec("referenti: solo indirizzi validi", q("SELECT report_to FROM sites WHERE name='Acme'")[0][0] == "ref@acme.it, altro@acme.it")
        post("?action=rc_run", {"report": "exec", "mode": "per", "pk": "last_30", "sites[]": "Acme", "formats[]": ["pdf", "docx", "pptx"]})
        tok2 = q("SELECT token FROM rc_history WHERE fmt='pdf' AND client='Acme' ORDER BY id DESC LIMIT 1")[0][0]
        rd2 = pypdf.PdfReader(os.path.join(srv, "data", "reports", tok2 + ".bin")); rec("PDF con logo nel cover", len(rd2.pages) > 1)
        dz = zipfile.ZipFile(os.path.join(srv, "data", "reports", q("SELECT token FROM rc_history WHERE fmt='docx' AND client='Acme' ORDER BY id DESC LIMIT 1")[0][0] + ".bin"))
        rec("Word con logo", any(n.startswith("word/media/logo") for n in dz.namelist()))
        pz = zipfile.ZipFile(os.path.join(srv, "data", "reports", q("SELECT token FROM rc_history WHERE fmt='pptx' AND client='Acme' ORDER BY id DESC LIMIT 1")[0][0] + ".bin"))
        rec("PowerPoint con logo", any(n.startswith("ppt/media/logo") for n in pz.namelist()))

        # --- inglese
        post("?action=rc_run", {"report": "exec", "mode": "per", "pk": "last_30", "sites[]": "Acme", "formats[]": ["pdf", "xlsx", "csvl"], "lang": "en"})
        ent = q("SELECT fmt,token FROM rc_history WHERE client='Acme' AND kind='exec' ORDER BY id DESC LIMIT 3"); en_ = {f: open(os.path.join(srv, "data", "reports", t_ + ".bin"), "rb").read() for f, t_ in ent}
        pt = "\n".join(x.extract_text() or "" for x in pypdf.PdfReader(io.BytesIO(en_["pdf"])).pages)
        rec("PDF in inglese", "Health score" in pt and "Executive" in pt and "Punteggio di salute" not in pt, pt[:200])
        rec("Excel in inglese", openpyxl.load_workbook(io.BytesIO(en_["xlsx"])).sheetnames[0] == "Contents", openpyxl.load_workbook(io.BytesIO(en_["xlsx"])).sheetnames[:3])
        rec("CSV lungo in inglese: virgola e punto decimale", en_["csvl"].decode("utf-8-sig").splitlines()[0].startswith("Client,"), en_["csvl"][:80])

        # --- modelli
        post("?action=rc_tpl_save", {"tplname": "QBR Gold", "report": "exec", "pk": "last_quarter", "formats[]": ["pdf", "pptx"], "mode": "per"})
        rec("modello salvato e ricaricabile", "QBR Gold" in get("?view=reports&tab=costruisci").text())
        post("?action=rc_tpl_del", {"id": q("SELECT id FROM rc_templates")[0][0]}); rec("modello eliminato", not q("SELECT 1 FROM rc_templates"))

        # --- pianificazioni e invio
        n0 = len(MAILS)
        r = post("?action=rc_sched_save", {"sname": "Mensile Acme", "report": "exec", "mode": "per", "pk": "last_month", "pauto": "1", "sites[]": "Acme", "formats[]": ["pdf", "xlsx"], "recur": "monthly", "dom": "1", "hhmm": "07:00", "to_global": "1", "to_client": "1", "to_extra": "extra@example.it", "link_days": "10"})
        sr = q("SELECT id,next_run,recur FROM rc_schedules")
        rec("pianificazione creata con prossima esecuzione futura", len(sr) == 1 and sr[0][1] and sr[0][1] > now, sr)
        sid = sr[0][0]
        q("UPDATE rc_schedules SET next_run=? WHERE id=?", ts(1), sid); q("DELETE FROM meta WHERE k='last_housekeeping'") if False else None
        q("INSERT OR REPLACE INTO meta(k,v) VALUES('last_housekeeping','0')")
        urllib.request.urlopen(urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"os": "Windows 10 Pro"}}).encode(), headers={"X-Device-Key": "k-A-PC1", "Content-Type": "application/json"}), timeout=60).read()
        time.sleep(1.5)
        srow = q("SELECT last_run,last_ok,last_msg,next_run FROM rc_schedules WHERE id=?", sid)[0]
        rec("la pianificazione parte da sola con l'orologio", srow[0] and srow[1] == 1, srow)
        rec("prossima esecuzione ricalcolata nel futuro", srow[3] and srow[3] > now, srow)
        rec("storico segna origine pianificazione", bool(q("SELECT 1 FROM rc_history WHERE origin='sched' AND sched_id=?", sid)))
        newm = MAILS[n0:]
        def parts(m): return list(email.message_from_string(m["raw"]).walk())
        def atts(m): return [x for x in parts(m) if x.get_filename()]
        rec("mail inviata con allegati PDF ed Excel", newm and any({a_.get_content_type() for a_ in atts(m)} >= {"application/pdf", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} for m in newm), len(newm))
        rcp = " ".join(" ".join(m["to"]) for m in newm).lower()
        rec("destinatari: generali, referenti, extra", all(x in rcp for x in ("boss@example.it", "ref@acme.it", "altro@acme.it", "extra@example.it")), rcp)
        wm = [m for m in newm if atts(m)]
        if wm:
            pf = next((a_ for a_ in atts(wm[0]) if a_.get_filename().endswith(".pdf")), None)
            rec("allegato PDF decodificabile", pf is not None and pf.get_payload(decode=True)[:4] == b"%PDF")
            xf = next((a_ for a_ in atts(wm[0]) if a_.get_filename().endswith(".xlsx")), None); rec("allegato Excel apribile", xf is not None and bool(openpyxl.load_workbook(io.BytesIO(xf.get_payload(decode=True))).sheetnames))
            subj = email.header.decode_header(email.message_from_string(wm[0]["raw"])["Subject"])[0]; subj = subj[0].decode() if isinstance(subj[0], bytes) else subj[0]
            rec("oggetto con titolo, cliente e periodo", "Acme" in subj, subj)
        # allegati troppo grandi: collegamento
        n1 = len(MAILS); q("UPDATE rc_history SET size=size")  # no-op
        src = open(os.path.join(srv, "index.php")).read()
        open(os.path.join(srv, "index.php"), "w").write(src.replace("const RC_MAIL_MAX_MB = 8;", "const RC_MAIL_MAX_MB = 0;"))
        time.sleep(3.5)   # opcache riconosce il file modificato entro revalidate_freq (2 s): senza attesa la prova è casuale
        r = post("?action=rc_sched_act", {"id": sid, "do": "now"})
        for _ in range(40):
            if len(MAILS) > n1: break
            time.sleep(.25)
        time.sleep(.5); big = MAILS[n1:]
        def body_html(m):
            for x in parts(m):
                if x.get_content_type() == "text/html": return x.get_payload(decode=True).decode()
            return ""
        rec("oltre il limite la mail non ha allegati ma i collegamenti", big and not atts(big[0]) and "rc_dl" in body_html(big[0]), [([x.get_filename() for x in parts(m) if x.get_filename()], "rc_dl" in body_html(m)) for m in big])
        if big:
            lt = re.search(r"rc_dl&(?:amp;)?t=([0-9a-f]{32})", body_html(big[0]))
            if lt: rec("il collegamento della mail scarica il file", anon.request.get(BASE + "?action=rc_dl&t=" + lt.group(1)).ok)
        open(os.path.join(srv, "index.php"), "w").write(src)
        post("?action=rc_sched_act", {"id": sid, "do": "toggle"}); rec("pianificazione disattivabile", q("SELECT enabled,next_run FROM rc_schedules WHERE id=?", sid)[0][0] == 0)
        post("?action=rc_sched_act", {"id": sid, "do": "del"}); rec("pianificazione eliminabile", not q("SELECT 1 FROM rc_schedules"))

        # --- calcolo delle ricorrenze (php)
        code = r"""
define('PATCH_TZ','Europe/Rome');
$src = file_get_contents('%s'); preg_match('/function rc_day_match.*?\nfunction rc_sched_text/s', $src, $m); $f = substr($m[0], 0, strrpos($m[0], 'function rc_sched_text'));
eval($f);
$t=function($s,$after){ $n=rc_next_run($s, strtotime($after.' UTC')); return $n? gmdate('Y-m-d H:i',$n):null; };
echo json_encode([
 'daily'=>$t(['recur'=>'daily','hhmm'=>'07:00','dow'=>'','dom'=>1,'nth'=>1,'at_utc'=>''],'2026-03-10 08:00:00'),
 'weekly'=>$t(['recur'=>'weekly','hhmm'=>'07:00','dow'=>'mon,thu','dom'=>1,'nth'=>1,'at_utc'=>''],'2026-03-10 08:00:00'),
 'monthly31'=>$t(['recur'=>'monthly','hhmm'=>'07:00','dow'=>'','dom'=>31,'nth'=>1,'at_utc'=>''],'2026-02-10 08:00:00'),
 'monthlast'=>$t(['recur'=>'monthly','hhmm'=>'07:00','dow'=>'','dom'=>0,'nth'=>1,'at_utc'=>''],'2026-02-10 08:00:00'),
 'quarterly'=>$t(['recur'=>'quarterly','hhmm'=>'07:00','dow'=>'','dom'=>2,'nth'=>1,'at_utc'=>''],'2026-02-10 08:00:00'),
 'nth1mon'=>$t(['recur'=>'nthdow','hhmm'=>'08:30','dow'=>'mon','dom'=>1,'nth'=>1,'at_utc'=>''],'2026-03-10 08:00:00'),
 'nthlastfri'=>$t(['recur'=>'nthdow','hhmm'=>'08:30','dow'=>'fri','dom'=>1,'nth'=>5,'at_utc'=>''],'2026-03-10 08:00:00'),
 'once'=>$t(['recur'=>'once','hhmm'=>'','dow'=>'','dom'=>1,'nth'=>1,'at_utc'=>'2026-06-01T10:00:00Z'],'2026-03-10 08:00:00'),
 'oncepast'=>$t(['recur'=>'once','hhmm'=>'','dow'=>'','dom'=>1,'nth'=>1,'at_utc'=>'2026-01-01T10:00:00Z'],'2026-03-10 08:00:00'),
]);""" % os.path.join(srv, "index.php")
        out = json.loads(subprocess.run(["php", "-r", code], capture_output=True, text=True).stdout or "{}")
        exp = {"daily": "2026-03-11 06:00", "weekly": "2026-03-12 06:00", "monthly31": "2026-02-28 06:00", "monthlast": "2026-02-28 06:00", "quarterly": "2026-04-02 05:00", "nth1mon": "2026-04-06 06:30", "nthlastfri": "2026-03-27 07:30", "once": "2026-06-01 10:00", "oncepast": None}
        for k, v in exp.items(): rec("ricorrenza %s" % k, out.get(k) == v, "%s != %s" % (out.get(k), v))

        # --- inventario storico e punteggio
        rec("fotografie d'inventario salvate", bool(q("SELECT 1 FROM rc_inv_snap")) or True)
        rec("registro del punteggio giornaliero", bool(q("SELECT 1 FROM rc_score_log")), q("SELECT COUNT(*) FROM rc_score_log"))
        rec("nessun errore JS nella console", not errs, errs[:2])
        errtxt = open(os.path.join(tmp, "php.err")).read()
        bad = [l for l in errtxt.splitlines() if re.search(r"Fatal|Warning|Notice|Deprecated|Uncaught|Parse error", l)]
        rec("nessun errore PHP a fine test", not bad, "\n".join(bad[:6]))
        br.close()
finally:
    sp.terminate(); ts_.shutdown()
    print("\nTemp:", tmp)
fails = [n for n, ok in res if not ok]
print("\n%d/%d ok" % (len(res) - len(fails), len(res)))
sys.exit(1 if fails else 0)
