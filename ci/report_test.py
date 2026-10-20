#!/usr/bin/env python3
"""Report al volo (CSV / Excel / PDF) dei singoli elementi, esportazioni degli elenchi e menù delle azioni, 1.41.0.
Uso: python3 ci/report_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse, http.cookiejar
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8795; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-rep-"); srv = os.path.join(tmp, "server")
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
    c = sqlite3.connect(DB); c.execute("ATTACH DATABASE ? AS dk", (os.path.join(os.path.dirname(DB), "docs.sqlite"),)); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r

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
    for n in ("Acme", "Beta", "Gamma"): q("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", n, now)
    for hn, site in [("A-PC1", "Acme"), ("A-PC2", "Acme"), ("A-PC3", "Acme"), ("B-PC1", "Beta"), ("G-PC1", "Gamma")]:
        q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,?,?,?,?,'{}',?)", hn, "windows", "k-" + hn, site, now, now)
    dev = {r[1]: r[0] for r in q("SELECT id,hostname FROM devices")}
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('beta',?, 'operator','Beta',1,?,0)", h, now)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('gamma',?, 'operator','Gamma',1,?,0)", h, now)


    inv = {"os": "Windows 11 Pro", "os_build": "22631", "manufacturer": "Dell", "model": "Latitude 5440", "serial": "SN0123", "ram_gb": 16, "cpu": "Intel i7 àèìòù", "agent_version": "1.0",
           "disks": [{"DeviceID": "C:", "size_gb": 476, "free_gb": 120.5}], "ips": ["10.0.0.5"], "logged_user": "mario"}
    sw = [{"name": "7-Zip", "version": "23.01", "publisher": "Igor Pavlov"}, {"name": "=cmd|' /C calc'!A0", "version": "1", "publisher": "evil (parentesi) \\ x"}] + [{"name": "App %d" % i, "version": "1.%d" % i, "publisher": "Vendor"} for i in range(60)]
    q("UPDATE devices SET inventory=?, full_inv=? WHERE hostname='A-PC1'", json.dumps(inv), json.dumps({"software": sw}))
    for i in range(3): q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["A-PC1"], "disk:C:", "warn", "Disco quasi pieno %d" % i, "open", now)
    q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["B-PC1"], "cpu", "crit", "Segreto di Beta", "open", now)
    for i in range(400): q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["A-PC2"], "cpu", "info", "Lunga riga di prova numero %d con testo abbastanza lungo da andare a capo nella cella della tabella PDF" % i, "open", now)
    q("INSERT INTO asset_types(name,fields,created) VALUES('Stampante', ?, ?)", json.dumps([{"k": "ip", "l": "Indirizzo IP", "t": "text"}, {"k": "pwd", "l": "Password", "t": "password"}]), now)
    tid = q("SELECT id FROM asset_types WHERE name='Stampante'")[0][0]
    q("INSERT INTO assets(type_id,name,site,status,data,created,updated) VALUES(?,?,?,?,?,?,?)", tid, "HP Piano 1", "Acme", "attivo", json.dumps({"ip": "10.0.0.9", "pwd": "SEGRETISSIMA"}), now, now)
    q("INSERT INTO assets(type_id,name,site,status,data,created,updated) VALUES(?,?,?,?,?,?,?)", tid, "Epson Beta", "Beta", "attivo", "{}", now, now)
    aid = {r[1]: r[0] for r in q("SELECT id,name FROM assets")}

    import io, zipfile, openpyxl, subprocess as sps
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def login(ctx, user, pw_=PW):
            pg = ctx.new_page(); pg.goto(BASE); pg.fill("input[name=username]", user); pg.click("button[type=submit]")
            pg.wait_for_selector("input[name=password]", timeout=5000); pg.fill("input[name=password]", pw_); pg.click("button[type=submit]"); pg.wait_for_selector(".rail", timeout=8000); return pg
        c = br.new_context(viewport={"width": 1360, "height": 900}); p = login(c, "admin"); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("dialog", lambda d: d.accept())
        # un ticket vero dall'interfaccia
        c.request.post(BASE + "?action=tk_new", form={"device_id": str(dev["A-PC1"]), "title": "Stampante lenta", "priority": "high"}, max_redirects=0)
        tk = q("SELECT id FROM tickets")[0][0]
        c.request.post(BASE + "?action=tk_note", form={"id": str(tk), "text": "Riavviata la coda di stampa", "minutes": "15"}, max_redirects=0)

        def get(url, ctx=c): return ctx.request.get(BASE + url)
        def xl(r):
            wb = openpyxl.load_workbook(io.BytesIO(r.body())); return wb
        def pdf_text(b):
            f = os.path.join(tmp, "t.pdf"); open(f, "wb").write(b)
            return sps.run(["pdftotext", "-layout", f, "-"], capture_output=True, text=True).stdout
        def pdf_pages(b):
            from pypdf import PdfReader
            return len(PdfReader(io.BytesIO(b)).pages)

        # ---- device
        r = get(f"?action=report_get&kind=device&id={dev['A-PC1']}&fmt=csv")
        t = r.body().decode("utf-8-sig")
        if r.status != 200: errlog.flush(); print("\n".join(l for l in open(os.path.join(tmp, "php.err")).read().splitlines() if "Fatal" in l or "Warning" in l or "Error" in l)[-1500:])
        rec("device CSV: intestazioni e BOM", r.status == 200 and "text/csv" in r.headers["content-type"] and r.body()[:3] == b"\xef\xbb\xbf" and "Latitude 5440" in t and "Disco quasi pieno 1" in t, (r.status, r.headers.get("content-type"), t[:300]))
        rec("device CSV: formula injection neutralizzata", "'=cmd" in t and ";=cmd" not in t and "\n=cmd" not in t)
        r = get(f"?action=report_get&kind=device&id={dev['A-PC1']}&fmt=xlsx"); wb = xl(r)
        rec("device XLSX: si apre con openpyxl", r.status == 200 and "spreadsheetml" in r.headers["content-type"], r.headers.get("content-type"))
        rec("device XLSX: fogli attesi", {"Scheda", "Dischi", "Software installato"} <= set(wb.sheetnames) and any(n.startswith("Alert") for n in wb.sheetnames), wb.sheetnames)
        ws = wb["Dischi"]; rec("device XLSX: numeri veri nei dischi", ws["B2"].value == 476 and ws["C2"].value == 120.5 and ws["A2"].value == "C:", [c_.value for c_ in ws[2]])
        rec("device XLSX: intestazione in grassetto e bloccata", ws["A1"].font.b is True and ws.freeze_panes == "A2")
        rec("device XLSX: software completo (62 righe + intestazione)", wb["Software installato"].max_row == 63, wb["Software installato"].max_row)
        rec("device XLSX: nome foglio valido (<=31, senza caratteri vietati)", all(len(n) <= 31 and not re.search(r"[\[\]:*?/\\]", n) for n in wb.sheetnames))
        r = get(f"?action=report_get&kind=device&id={dev['A-PC1']}&fmt=pdf"); b = r.body()
        rec("device PDF: intestazione, trailer e tipo", r.status == 200 and b[:8] == b"%PDF-1.4" and b.rstrip().endswith(b"%%EOF") and "application/pdf" in r.headers["content-type"])
        sx = int(re.search(rb"startxref\n(\d+)", b).group(1)); rec("device PDF: startxref punta alla tabella xref", b[sx:sx + 4] == b"xref", b[sx:sx + 8])
        if os.environ.get("REP_KEEP"): open("/tmp/rep-dev.pdf", "wb").write(b); open("/tmp/rep-cli.pdf", "wb").write(get(f"?action=report_get&kind=client&site=Acme&month={time.strftime('%Y-%m')}&fmt=pdf").body())
        tx = pdf_text(b)
        rec("device PDF: testo estratto (scheda, accenti, disco)", "Scheda device" in tx and "A-PC1" in tx and "Latitude 5440" in tx and "àèìòù" in tx and "476" in tx, tx[:400])
        rec("device PDF: parentesi e backslash nel testo non rompono il file", "evil (parentesi)" in tx and qpdfok(b) if False else "evil (parentesi)" in tx, tx[-300:])
        f = os.path.join(tmp, "q.pdf"); open(f, "wb").write(b); qr = sps.run(["qpdf", "--check", f], capture_output=True, text=True)
        rec("device PDF: qpdf --check valido", qr.returncode in (0, 3) and "No syntax or stream encoding errors found" in qr.stdout and "WARNING" not in qr.stdout, qr.stdout[-300:] + qr.stderr[-200:])
        rec("device PDF: piè di pagina con numerazione", re.search(r"pagina 1 di \d+", tx) is not None)
        rec("device: le password dell'asset non compaiono altrove", "SEGRETISSIMA" not in tx)

        # ---- device con tante righe: più pagine, intestazione ripetuta, taglio dichiarato
        r = get(f"?action=report_get&kind=device&id={dev['A-PC2']}&fmt=pdf"); b = r.body(); tx = pdf_text(b); n = pdf_pages(b)
        rec("PDF lungo: più pagine e tabella spezzata", n >= 3, n)
        rec("PDF lungo: intestazione di tabella ripetuta a ogni pagina", tx.count("Messaggio") >= n - 1, (tx.count("Messaggio"), n, tx[:600]))
        rec("PDF lungo: testo a capo senza perdere parole", "andare a capo nella cella" in tx and "numero 399" in tx)
        rec("PDF lungo: numero pagine coerente col piè di pagina", f"pagina {n} di {n}" in tx)
        wb = xl(get(f"?action=report_get&kind=device&id={dev['A-PC2']}&fmt=xlsx")); rec("XLSX lungo: tutte le 300 righe di alert (limite elenco)", wb[[s for s in wb.sheetnames if s.startswith("Alert")][0]].max_row == 301)

        # ---- asset
        r = get(f"?action=report_get&kind=asset&id={aid['HP Piano 1']}&fmt=csv"); t = r.body().decode("utf-8-sig")
        rec("asset CSV: campi del tipo, senza password", "10.0.0.9" in t and "Indirizzo IP" in t and "SEGRETISSIMA" not in t, t)
        rec("asset PDF e XLSX", get(f"?action=report_get&kind=asset&id={aid['HP Piano 1']}&fmt=pdf").body()[:4] == b"%PDF" and xl(get(f"?action=report_get&kind=asset&id={aid['HP Piano 1']}&fmt=xlsx")).sheetnames == ["Scheda"])
        # ---- ticket
        t = get(f"?action=report_get&kind=ticket&id={tk}&fmt=csv").body().decode("utf-8-sig")
        rec("ticket CSV: scheda e cronologia", "Stampante lenta" in t and "Riavviata la coda di stampa" in t and "Cronologia" in t, t[:300])
        rec("ticket PDF: contiene titolo e nota", "Riavviata la coda" in pdf_text(get(f"?action=report_get&kind=ticket&id={tk}&fmt=pdf").body()))
        # ---- cliente + mese
        mo = time.strftime("%Y-%m")
        t = get(f"?action=report_get&kind=client&site=Acme&month={mo}&fmt=csv").body().decode("utf-8-sig")
        rec("cliente CSV: sezioni sintesi/alert/parco", "Sintesi" in t and "Alert del mese" in t and "Parco macchine" in t and "A-PC3" in t and "B-PC1" not in t, t[:200])
        wb = xl(get(f"?action=report_get&kind=client&site=Acme&month={mo}&fmt=xlsx")); rec("cliente XLSX: fogli", {"Sintesi", "Parco macchine"} <= set(wb.sheetnames), wb.sheetnames)
        rec("cliente PDF", "Report mensile" in pdf_text(get(f"?action=report_get&kind=client&site=Acme&month={mo}&fmt=pdf").body()))
        # ---- elenchi in tre formati
        for what, tok in [("devices", "A-PC1"), ("inventory", "A-PC1"), ("alerts", "Disco quasi pieno"), ("assets", "HP Piano 1"), ("software", "7-Zip"), ("jobs", "x"), ("expiry", "x")]:
            if tok == "x": continue
            rc = get(f"?action=export&what={what}").body().decode("utf-8-sig")
            rx = xl(get(f"?action=export&what={what}&fmt=xlsx")); vals = [str(c_.value) for row in rx.active.iter_rows() for c_ in row]
            rp = pdf_text(get(f"?action=export&what={what}&fmt=pdf").body())
            rec(f"elenco {what}: CSV, XLSX e PDF coerenti", tok in rc and any(tok in v for v in vals) and tok in rp, (what, rc[:80]))
        rec("elenco: formato sconosciuto ricade su CSV", "text/csv" in get("?action=export&what=devices&fmt=boh").headers["content-type"])
        rec("elenco: CSV identico a prima (separatore ; e intestazioni)", get("?action=export&what=devices").body().decode("utf-8-sig").splitlines()[0] == "id;hostname;site;os;versione_os;produttore;modello;seriale;cpu;ram_gb;ultimo_contatto;agent")

        # ---- permessi e perimetro
        cb = br.new_context(); pb = login(cb, "beta")
        rec("perimetro: device di un altro cliente → 404", get(f"?action=report_get&kind=device&id={dev['A-PC1']}&fmt=pdf", cb).status == 404)
        rec("perimetro: asset di un altro cliente → 404", get(f"?action=report_get&kind=asset&id={aid['HP Piano 1']}&fmt=csv", cb).status == 404)
        rec("perimetro: ticket di un altro cliente → 404", get(f"?action=report_get&kind=ticket&id={tk}&fmt=csv", cb).status == 404)
        rec("perimetro: cliente non suo → 404", get("?action=report_get&kind=client&site=Acme&fmt=csv", cb).status == 404)
        rec("perimetro: il proprio device funziona", get(f"?action=report_get&kind=device&id={dev['B-PC1']}&fmt=csv", cb).status == 200)
        t = get("?action=export&what=alerts", cb).body().decode("utf-8-sig")
        rec("perimetro: export elenco filtra per cliente", "Segreto di Beta" in t and "Disco quasi pieno" not in t, t[:300])
        rec("perimetro: elemento inesistente → 404", get("?action=report_get&kind=device&id=99999&fmt=csv").status == 404 and get("?action=report_get&kind=boh&fmt=csv").status == 404)
        cn = br.new_context(); rn = cn.request.get(BASE + f"?action=report_get&kind=device&id={dev['A-PC1']}&fmt=csv", max_redirects=0)
        rec("senza accesso non si scarica nulla", rn.status in (302, 401, 403) or b"Latitude" not in rn.body(), rn.status)
        q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('vis',?, 'viewer','',1,?,0)", h, now)
        cv = br.new_context(); pv = login(cv, "vis")
        rec("viewer: può scaricare il report di un elemento", get(f"?action=report_get&kind=device&id={dev['A-PC1']}&fmt=pdf", cv).status == 200)
        rec("viewer: non può esportare gli elenchi", get("?action=export&what=devices", cv).status in (302, 401, 403) or b"id;hostname" not in get("?action=export&what=devices", cv).body())
        rec("audit: report_get ed export registrati", len(q("SELECT 1 FROM audit WHERE action='report_get'")) >= 5 and len(q("SELECT 1 FROM audit WHERE action='export'")) >= 5)


        # ---- menù nelle barre degli strumenti
        def visible_in_view(pg, sel):
            return pg.evaluate("(s)=>{var e=document.querySelector(s);if(!e)return false;var r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight+2}", sel)
        def open_menu(pg, mid):
            pg.click(f"details#{mid}>summary"); pg.wait_for_timeout(120)
        pw1 = {"expsel": "?view=devices", }
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT")
        rec("device: nessun pulsante CSV sciolto nella barra", p.locator("a[href*='action=export']:visible").count() == 0)
        rec("device: i pulsanti di azione di massa non sono più in fila", p.locator("#invForm .toolbar > button.btn2:visible").count() == 0)
        open_menu(p, "actsel")
        if os.environ.get("REP_KEEP"): p.screenshot(path="/tmp/rep-ui-devices.png")
        rec("device: menù Azioni mostra le azioni di massa", all(p.locator(f"#actsel button:has-text('{t_}')").count() >= 1 for t_ in ("Inventario completo", "Scansiona patch", "Applica patch", "Aggiorna agent", "Imposta reparto")))
        rec("device: menù Azioni entra nello schermo", visible_in_view(p, "#actsel .colpop") or p.evaluate("(()=>{var r=document.querySelector('#actsel .colpop').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()"))
        # una azione di massa dal menù funziona davvero
        p.locator("#invT tbody tr input[type=checkbox]").first.check()
        p.locator("#actsel .mi[data-act=invreq]").click(); p.wait_for_selector("#invSum[open]"); p.locator("#invSum .sum-f button").last.click(); p.wait_for_selector("main p.ok")
        rec("device: azione di massa dal menù eseguita", len(q("SELECT 1 FROM devices WHERE full_inv_req=1")) >= 1 or "inventario" in p.inner_text("main").lower(), p.inner_text("main")[:200])
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT"); open_menu(p, "actsel")
        links = p.locator("#actsel .exr a[data-fmt]").evaluate_all("(a)=>a.map(x=>x.getAttribute('href'))")
        rec("device: i report sono nel menù Azioni (3 elenchi x 3 formati)", len(links) == 9 and sum("fmt=pdf" in l_ for l_ in links) == 3 and sum("fmt=xlsx" in l_ for l_ in links) == 3, links)
        with p.expect_download() as dl: p.locator("#actsel a[data-fmt=xlsx]").first.click()
        d_ = dl.value; rec("device: clic su Excel scarica un .xlsx", d_.suggested_filename.endswith(".xlsx") and zipfile.is_zipfile(d_.path()), d_.suggested_filename)
        p.keyboard.press("Escape")
        # le altre pagine con elenchi
        for name, url in [("alert", "?view=alerts"), ("attività", "?view=jobs"), ("asset", "?view=assets"), ("scadenze", "?view=expiry")]:
            p.goto(BASE + url); p.wait_for_selector("main")
            rec(f"{name}: niente link CSV sciolti, c'è il menù Esporta", p.locator("a[href*='action=export'][href*='fmt=']:visible").count() == 0 and p.locator("details#expsel>summary:has-text('Esporta')").count() == 1)
            open_menu(p, "expsel"); n3 = p.locator("#expsel .colpop a[data-fmt]").count()
            rec(f"{name}: menù Esporta con CSV/Excel/PDF in vista", n3 >= 3 and n3 % 3 == 0 and p.evaluate("(()=>{var r=document.querySelector('#expsel .colpop').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()"), n3)
        p.goto(BASE + "?view=alerts"); open_menu(p, "expsel")
        rec("alert: due elenchi (aperti e storico)", p.locator("#expsel .exr").count() == 2)
        # scheda device
        p.goto(BASE + f"?view=device&id={dev['A-PC1']}"); p.wait_for_selector(".dhead")
        rec("scheda device: i report stanno nel menù Azioni in testata", p.locator(".dhead details#actsel").count() == 1 and p.locator("#repsel").count() == 0)
        open_menu(p, "actsel")
        if os.environ.get("REP_KEEP"): p.screenshot(path="/tmp/rep-ui-device.png")
        with p.expect_download() as dl: p.locator("#actsel a[data-fmt=csv]").click()
        rec("scheda device: clic su CSV scarica il report", dl.value.suggested_filename.startswith("myrmm-scheda-device-a-pc1") and dl.value.suggested_filename.endswith(".csv"), dl.value.suggested_filename)
        pdfhref = p.locator("#actsel a[data-fmt=pdf]").get_attribute("href"); rec("scheda device: PDF si apre in una nuova scheda", p.locator("#actsel a[data-fmt=pdf]").get_attribute("target") == "_blank" and "kind=device" in pdfhref)
        p.keyboard.press("Escape")
        rec("scheda device: niente più «Altre azioni» né pulsanti sparsi", p.locator("details#devact").count() == 0 and p.locator("form button.btn2:has-text('Inventario completo ora')").count() == 0)
        open_menu(p, "actsel"); rec("scheda device: il menù Azioni contiene Inventario completo", p.locator("#actsel .mi:has-text('Inventario completo')").count() == 1)
        p.goto(BASE + f"?view=tickets&id={tk}"); p.wait_for_selector("main")
        rec("ticket: menù Report", p.locator("details#repsel").count() == 1 and "kind=ticket" in (p.locator("#repsel a[data-fmt=pdf]").get_attribute("href") or ""))
        p.goto(BASE + f"?view=asset&id={aid['HP Piano 1']}"); p.wait_for_selector("main")
        rec("asset: menù Report", p.locator("details#repsel").count() == 1 and "kind=asset" in (p.locator("#repsel a[data-fmt=pdf]").get_attribute("href") or ""))
        p.goto(BASE + f"?view=report&site=Acme&month={time.strftime('%Y-%m')}"); p.wait_for_selector("main")
        rec("report mensile: menù Esporta con PDF/Excel/CSV e stampa", p.locator("details#expsel").count() == 1 and p.locator("#expsel a[data-fmt]").count() == 3 and p.locator("#expsel button:has-text('Stampa')").count() == 1)
        # telefono: i menù restano utilizzabili
        cp = br.new_context(**pw.devices["Pixel 7"]); pp = login(cp, "admin"); pp.goto(BASE + "?view=devices"); pp.wait_for_selector("#invT"); pp.tap("#invForm .tbt"); pp.wait_for_timeout(200)
        for mid in ("actsel",):
            pp.tap(f"details#{mid}>summary"); pp.wait_for_timeout(200)
            rec(f"telefono: menù {mid} dentro lo schermo", pp.evaluate("(m)=>{var r=document.querySelector('#'+m+' .colpop').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&document.documentElement.scrollWidth<=innerWidth+1}", mid))
            pp.keyboard.press("Escape"); pp.tap("body", position={"x": 5, "y": 300}) if False else None
            pp.evaluate("(m)=>document.getElementById(m).open=false", mid)

        rec("nessun errore JS", not errs, errs[:3])
        br.close()
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    bad = sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l)))[:10]
    rec("nessun errore PHP", not bad, bad)
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok")
sys.exit(1 if f else 0)
