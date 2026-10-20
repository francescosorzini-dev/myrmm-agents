#!/usr/bin/env python3
"""Dossier d'audit: documenti PDF/Excel/CSV, mappa dei controlli, ZIP con impronte, lingue, perimetro, 1.42.0.
Uso: python3 ci/dossier_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse, http.cookiejar
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8800; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-dos-"); srv = os.path.join(tmp, "server")
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




    import io, zipfile, hashlib, openpyxl, subprocess as sps
    ym = time.strftime("%Y-%m"); lastm = time.strftime("%Y-%m", time.gmtime(time.time() - 40 * 86400))
    def ts(days=0): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    inv = {"os": "Windows 10 Pro", "os_build": "19045", "manufacturer": "Dell", "model": "Latitude 5440", "serial": "SN0123", "ram_gb": 16, "agent_version": "1.0", "disks": [{"DeviceID": "C:", "size_gb": 476, "free_gb": 30}], "logged_user": "mario"}
    sw = [{"name": "7-Zip", "version": "23.01", "publisher": "Igor Pavlov"}, {"name": "Café Données", "version": "1", "publisher": "Ñandú & Çia"}] + [{"name": "App %d" % i, "version": "1.%d" % i, "publisher": "Vendor"} for i in range(60)]
    sec = {"av": {"present": True, "name": "Defender", "enabled": True, "updated": True}, "bitlocker": {"volumes": [{"mount": "C:", "protected": True}]}, "firewall": {"domain": True, "private": True, "public": True}, "local_admins": ["Administrator", "mario"], "backup": {"product": "Veeam", "last_success": ts(1)}}
    q("UPDATE devices SET inventory=?, full_inv=?, full_inv_at=? WHERE hostname='A-PC1'", json.dumps(inv), json.dumps({"software": sw, "security": sec}), now)
    inv2 = dict(inv, os="Windows 7 Professional"); q("UPDATE devices SET inventory=?, last_seen=? WHERE hostname='A-PC2'", json.dumps(inv2), ts(20))
    for i in range(5): q("INSERT INTO alerts(device_id,type,severity,message,status,created,resolved_at) VALUES(?,?,?,?,?,?,?)", dev["A-PC1"], "disk:C:", "warn", "Disco quasi pieno %d" % i, "resolved" if i < 3 else "open", ts(3), ts(2) if i < 3 else None)
    q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["A-PC2"], "cpu", "crit", "CPU al 100% da ore", "open", ts(15))
    q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dev["B-PC1"], "cpu", "crit", "Segreto di Beta", "open", ts(1))
    for i, (sev, st) in enumerate([("Critical", "available"), ("Important", "available"), ("Moderate", "installed"), ("Critical", "installed"), ("Low", "failed")]):
        q("INSERT INTO patches(device_id,uid,kb,title,severity,category,mb,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?)", dev["A-PC1"], "u%d" % i, "KB50000%d" % i, "Aggiornamento di prova %d" % i, sev, "x", 10, st, ts(40), ts(1) if st == "installed" else ts(40))
    q("INSERT INTO expiries(site,kind,name,due,notes,created) VALUES(?,?,?,?,?,?)", "Acme", "dominio", "acme.it", time.strftime("%Y-%m-%d", time.gmtime(time.time() + 20 * 86400)), "rinnovo", now)
    q("INSERT INTO expiries(site,kind,name,due,notes,created) VALUES(?,?,?,?,?,?)", "Acme", "licenza", "Office scaduta", time.strftime("%Y-%m-%d", time.gmtime(time.time() - 5 * 86400)), "", now)
    q("INSERT INTO expiries(site,kind,name,due,notes,created) VALUES(?,?,?,?,?,?)", "Beta", "dominio", "beta-segreto.it", "2030-01-01", "", now)
    for a, d_ in [("run_script", "Pulizia disco su device #%d" % dev["A-PC1"]), ("power", "reboot su device #%d" % dev["A-PC1"]), ("run_script", "Script su device #%d" % dev["B-PC1"])]:
        q("INSERT INTO audit(user,action,detail,ip,ts) VALUES(?,?,?,?,?)", "admin", a, d_, "127.0.0.1", ts(2))
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('op1',?, 'operator','Acme',1,?,1)", h, now)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('op2',?, 'operator','Gamma',1,?,0)", h, now)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('vis',?, 'viewer','',1,?,0)", h, now)
    q("INSERT INTO sites(name,created) VALUES('Vuoto',?)", now)
    json.dump({"Report esecutivo": "Executive report", "Indice": "Contents", "Cliente": "Client", "Periodo": "Period", "Sintesi per la direzione": "Executive summary", "Pagina %d di %d": "Page %d of %d", "Conforme": "Compliant", "Mappa dei controlli e delle evidenze": "Controls and evidence map"}, open(os.path.join(srv, "lang", "en.json"), "w"), ensure_ascii=False)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def login(ctx, user, pw_=PW):
            pg = ctx.new_page(); pg.goto(BASE); pg.fill("input[name=username]", user); pg.click("button[type=submit]")
            pg.wait_for_selector("input[name=password]", timeout=5000); pg.fill("input[name=password]", pw_); pg.click("button[type=submit]"); pg.wait_for_selector(".rail", timeout=8000); return pg
        c = br.new_context(viewport={"width": 1360, "height": 900}); p = login(c, "admin"); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("dialog", lambda d: d.accept())
        def get(url, ctx=c): return ctx.request.get(BASE + url)
        _dv = get("?view=device&id=%d" % dev["A-PC1"]).text()
        rec("scheda device: sezione Sicurezza dai dati dell'agent", "<h4>Sicurezza</h4>" in _dv and "Antivirus/EDR" in _dv and "Cifratura del disco" in _dv, _dv[:100])
        def pdf_text(b, layout=True):
            f = os.path.join(tmp, "t.pdf"); open(f, "wb").write(b); return sps.run(["pdftotext"] + (["-layout"] if layout else []) + [f, "-"], capture_output=True, text=True).stdout
        def pages(b):
            from pypdf import PdfReader; return len(PdfReader(io.BytesIO(b)).pages)
        KINDS = ["exec", "inventory", "patch", "incidents", "access", "risks", "expiry", "controls"]
        Q = f"&site=Acme&from={lastm}&to={ym}"
        keep = os.environ.get("DOS_KEEP")
        texts = {}
        for k in KINDS:
            r = get(f"?action=report_get&kind=doc&doc={k}{Q}&fmt=pdf"); b = r.body()
            f = os.path.join(tmp, f"{k}.pdf"); open(f, "wb").write(b)
            if keep: open(f"/tmp/dos-{k}.pdf", "wb").write(b)
            qr = sps.run(["qpdf", "--check", f], capture_output=True, text=True)
            tx = pdf_text(b); texts[k] = tx
            rec(f"{k} PDF: valido (qpdf), tipo e almeno copertina+indice+contenuto", r.status == 200 and b[:5] == b"%PDF-" and "No syntax or stream encoding errors found" in qr.stdout and "WARNING" not in qr.stdout and pages(b) >= 3, (r.status, qr.stdout[-200:]))
            rec(f"{k} PDF: cliente, periodo, ID documento e numerazione", "Acme" in tx and re.search(r"[A-Z]{3}-[0-9A-F]{8}", tx) and re.search(r"Pagina \d+ di \d+", tx) and (fmt_ := time.strftime("%Y")) in tx, tx[:300])
        rec("exec PDF: indice con le sezioni e numeri di pagina", re.search(r"Indice", texts["exec"]) and re.search(r"Sintesi per la direzione\s+3", texts["exec"]) is not None, texts["exec"][:900])
        rec("exec PDF: indicatori, stato complessivo e decisioni", "Stato complessivo" in texts["exec"] and "Disponibilità stimata" in texts["exec"] and "Cosa richiede una vostra decisione" in texts["exec"] and "Windows 7" in texts["exec"], texts["exec"][:200])
        rec("exec PDF: accenti e caratteri speciali corretti", "Disponibilità" in texts["exec"] and "?" not in re.sub(r"\s\?\s", "", "".join(re.findall(r"[A-Za-zàèìòù]+\?[A-Za-zàèìòù]+", texts["exec"]))))
        rec("inventory PDF: dispositivi, software e accenti (Ñ, Ç, é)", "A-PC1" in texts["inventory"] and "7-Zip" in texts["inventory"] and "Latitude 5440" in texts["inventory"], texts["inventory"][:300])
        rec("patch PDF: patch in sospeso, installate, gravità tradotta", "KB500000" in texts["patch"] and "Critica" in texts["patch"] and "KB500003" in texts["patch"], texts["patch"][:300])
        rec("incidents PDF: eventi, ticket e durata", "Disco quasi pieno" in texts["incidents"] and "CPU al 100%" in texts["incidents"], texts["incidents"][:300])
        rec("access PDF: utenti con 2FA e operazioni del cliente", "op1" in texts["access"] and "Pulizia disco" in texts["access"] and "op2" not in texts["access"] and "Script su device" not in texts["access"], texts["access"][:400])
        rec("risks PDF: fine supporto e patch critiche", "Windows 7" in texts["risks"] and "Alto" in texts["risks"], texts["risks"][:300])
        rec("expiry PDF: scadenze del cliente soltanto", "acme.it" in texts["expiry"] and "Office scaduta" in texts["expiry"] and "beta-segreto" not in texts["expiry"], texts["expiry"][:300])
        _n=re.sub(r"\s+"," ",texts["controls"]).lower(); rec("controls PDF: riferimenti NIS2 ed evidenze", "21(2)(j)" in texts["controls"] and "verifica in due" in _n and "non attesta" in _n, texts["controls"][:400])
        for fw, tok in [("iso27001", "A.8.8"), ("gdpr", "32(1)(c)"), ("agid", "ABSC 4")]:
            tx = pdf_text(get(f"?action=report_get&kind=doc&doc=controls{Q}&fw={fw}&fmt=pdf").body()); rec(f"controls: standard {fw}", tok in tx, tx[:200])
        # evidenze dall'agent (sicurezza) → esito nella mappa
        wb = openpyxl.load_workbook(io.BytesIO(get(f"?action=report_get&kind=doc&doc=controls{Q}&fmt=xlsx").body())); ws = wb["Controlli"]; rows = [[x.value for x in r] for r in ws.iter_rows(min_row=2)]
        by = {r[0]: r for r in rows}
        rec("controls XLSX: backup con evidenza dell'agent", "backup" in str(by["21(2)(c)"][3]).lower() and by["21(2)(c)"][2] in ("Conforme", "Da attenzionare"), by["21(2)(c)"])
        rec("controls XLSX: cifratura e antivirus rilevati", "Cifratura del disco attiva" in str(by["21(2)(h)"][3]) and "Antivirus" in str(by["21(2)(g)"][3]), (by["21(2)(h)"], by["21(2)(g)"]))
        rec("controls XLSX: voci organizzative «Da integrare»", by["21(2)(d)"][2] == "Da integrare" and by["21(2)(a)"][2] == "Da integrare", by["21(2)(d)"])
        rec("controls: 2FA parziale → da attenzionare", by["21(2)(j)"][2] == "Da attenzionare", by["21(2)(j)"])
        rec("controls: patch critiche vecchie → carenza", by["21(2)(e)"][2] == "Carenza", by["21(2)(e)"])
        # Excel e CSV dei documenti
        for k, sheet in [("inventory", "Dispositivi"), ("patch", "Patch in sospeso"), ("incidents", "Eventi"), ("access", "Utenti"), ("expiry", "Scadenze")]:
            wbk = openpyxl.load_workbook(io.BytesIO(get(f"?action=report_get&kind=doc&doc={k}{Q}&fmt=xlsx").body()))
            rec(f"{k} XLSX: apre e contiene il foglio «{sheet}»", sheet in wbk.sheetnames and wbk[sheet].max_row >= 2, wbk.sheetnames)
        wbk = openpyxl.load_workbook(io.BytesIO(get(f"?action=report_get&kind=doc&doc=inventory{Q}&fmt=xlsx").body()))
        rec("inventory XLSX: software completo per dispositivo (62 righe)", wbk["Software per dispositivo"].max_row == 63 and any("Café Données" == (x.value or "") for x in wbk["Software per dispositivo"]["B"]), wbk["Software per dispositivo"].max_row)
        wbk = openpyxl.load_workbook(io.BytesIO(get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=xlsx").body())); rec("exec XLSX: foglio di sintesi con gli indicatori", wbk.sheetnames[0] == "Sintesi" and wbk["Sintesi"].max_row > 5, wbk.sheetnames)
        t_ = get(f"?action=report_get&kind=doc&doc=incidents{Q}&fmt=csv").body().decode("utf-8-sig"); rec("incidents CSV", "Disco quasi pieno" in t_ and "Segreto di Beta" not in t_, t_[:200])
        # inglese
        r = get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=pdf&lang=en"); tx = pdf_text(r.body())
        rec("inglese: titoli e riquadri tradotti, il resto ripiega sull'italiano", "Executive report" in tx and "Executive summary" in tx and "Contents" in tx and re.search(r"Page \d+ of \d+", tx) and "Client" in tx, tx[:300])
        rec("inglese: formato data ISO nei documenti", re.search(r"20\d\d-\d\d-\d\d", pdf_text(get(f"?action=report_get&kind=doc&doc=incidents{Q}&fmt=pdf&lang=en").body())) is not None)
        r2 = get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=pdf&lang=xx"); rec("lingua inesistente: usa quella del cliente", r2.status == 200 and "Report esecutivo" in pdf_text(r2.body()))
        q("UPDATE sites SET lang='en' WHERE name='Acme'"); tx3 = pdf_text(get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=pdf").body())
        rec("lingua del cliente: i documenti escono in inglese di default", "Executive report" in tx3)
        # dossier ZIP
        r = get(f"?action=report_get&kind=dossier{Q}&lang=it"); z = zipfile.ZipFile(io.BytesIO(r.body())); names = z.namelist()
        rec("dossier ZIP: PDF ed Excel di tutti gli otto documenti + indice + impronte", r.status == 200 and "zip" in r.headers["content-type"] and sum(n.endswith(".pdf") for n in names) == 8 and sum(n.endswith(".xlsx") for n in names) == 8 and "SHA256SUMS.txt" in names and any(n.startswith("00-") for n in names), names)
        sums = dict(reversed(l.split("  ", 1)) for l in z.read("SHA256SUMS.txt").decode().splitlines())
        rec("dossier ZIP: le impronte SHA-256 corrispondono ai file", all(hashlib.sha256(z.read(n)).hexdigest() == h_ for n, h_ in sums.items()) and len(sums) == 16)
        idx = z.read([n for n in names if n.startswith("00-")][0]).decode()
        rec("dossier ZIP: indice con cliente, periodo e ID dei documenti", "Acme" in idx and re.search(r"[A-Z]{3}-[0-9A-F]{8}", idx) and "SHA256SUMS" in idx, idx[:300])
        keep and open("/tmp/dossier.zip", "wb").write(r.body())
        rec("dossier ZIP: gli Excel interni si aprono", all(openpyxl.load_workbook(io.BytesIO(z.read(n))) for n in names if n.endswith(".xlsx")))
        # coerenza dell'ID: stesso contenuto = stesso ID
        a1 = re.search(r"[A-Z]{3}-[0-9A-F]{8}", pdf_text(get(f"?action=report_get&kind=doc&doc=risks{Q}&fmt=pdf&lang=it").body())).group(0); a2 = re.search(r"[A-Z]{3}-[0-9A-F]{8}", pdf_text(get(f"?action=report_get&kind=doc&doc=risks{Q}&fmt=pdf&lang=it").body())).group(0)
        rec("ID documento stabile a parità di contenuto", a1 == a2, (a1, a2))
        # logo e colore del marchio: copertina con logo PNG
        import struct, zlib
        def png(rgb=(200, 30, 30)):
            raw = b"".join(b"\x00" + bytes(rgb) * 16 for _ in range(16))
            def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
            return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
        tp = os.path.join(tmp, "x"); os.makedirs(tp, exist_ok=True); open(os.path.join(tp, "logo.png"), "wb").write(png())
        p.goto(BASE + "?view=system#t=personalizzazione-del-marchio"); p.wait_for_selector("form[action*=brand_save]")
        p.fill("form[action*=brand_save] input[name=name]", "Studio Èlite"); p.set_input_files("form[action*=brand_save] input[type=file]", os.path.join(tp, "logo.png")); p.fill("form[action*=brand_save] input[name=color]", "#1f5fbf") if p.locator("form[action*=brand_save] input[name=color]").count() else None
        p.click("form[action*=brand_save] button[type=submit]"); p.wait_for_selector("main")
        b = get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=pdf&lang=it").body(); keep and open("/tmp/dos-brand.pdf", "wb").write(b)
        rec("marchio: nome personalizzato nel PDF e logo PNG incorporato", "Studio Èlite" in pdf_text(b) and b"/Subtype /Image" in b, pdf_text(b)[:150])
        qr = sps.run(["qpdf", "--check", os.path.join(tmp, "t.pdf")], capture_output=True, text=True); rec("marchio: PDF con immagine ancora valido", "No syntax or stream encoding errors found" in qr.stdout, qr.stdout[-200:])
        # perimetro e permessi
        cb = br.new_context(); pb = login(cb, "op2")
        rec("perimetro: cliente non suo → 404 (documento, ZIP)", get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=pdf", cb).status == 404 and get(f"?action=report_get&kind=dossier{Q}", cb).status == 404)
        rec("perimetro: cliente senza dispositivi → 404", get("?action=report_get&kind=doc&doc=exec&site=Vuoto&fmt=pdf").status == 404)
        rec("documento sconosciuto → 404", get(f"?action=report_get&kind=doc&doc=boh{Q}&fmt=pdf").status == 404)
        cv = br.new_context(); pv = login(cv, "vis"); rec("viewer: può scaricare documenti e dossier del proprio perimetro", get(f"?action=report_get&kind=doc&doc=exec{Q}&fmt=pdf", cv).status == 200 and get(f"?action=report_get&kind=dossier{Q}", cv).status == 200)
        cn = br.new_context(); rn = cn.request.get(BASE + f"?action=report_get&kind=dossier{Q}", max_redirects=0); rec("senza accesso: niente dossier", rn.status in (302, 401, 403) or b"PK" != rn.body()[:2], rn.status)
        pq = login(br.new_context(), "op2"); 
        # periodo: validazione
        r = get(f"?action=report_get&kind=doc&doc=exec&site=Acme&from=2999-01&to=2999-02&fmt=pdf"); rec("periodo nel futuro: ricondotto a un periodo valido", r.status == 200 and "2999" not in pdf_text(r.body()))
        r = get(f"?action=report_get&kind=doc&doc=exec&site=Acme&from=2000-01&to={ym}&fmt=pdf"); rec("periodo troppo lungo: limitato a 24 mesi", r.status == 200 and "2000" not in pdf_text(r.body()))
        r = get(f"?action=report_get&kind=doc&doc=exec&site=Acme&from=zzz&to=qqq&fmt=pdf"); rec("periodo non valido: mese scorso", r.status == 200)
        rec("audit: dossier_get e doc_get registrati", len(q("SELECT 1 FROM audit WHERE action='dossier_get'")) >= 2 and len(q("SELECT 1 FROM audit WHERE action='doc_get'")) >= 10)
        # pagina
        p.goto(BASE + "?view=dossier"); p.wait_for_selector("main")
        rec("pagina Dossier audit: cliente, periodo, lingua, standard", all(p.locator(f"select[name={n}], input[name={n}]").count() == 1 for n in ("site", "from", "to", "lang", "fw")))
        rec("pagina Dossier audit: otto documenti x tre formati e il dossier", p.locator("a[data-doc]").count() == 24 and p.locator("#dosZip").count() == 1, p.locator("a[data-doc]").count())
        with p.expect_download() as dl: p.click("#dosZip")
        rec("pagina Dossier audit: il pulsante scarica lo ZIP", dl.value.suggested_filename.startswith("dossier-acme") and zipfile.is_zipfile(dl.value.path()), dl.value.suggested_filename)
        p.click("a[data-doc=exec][data-fmt=xlsx]") if False else None
        with p.expect_download() as dl2: p.locator("a[data-doc=patch][data-fmt=xlsx]").click()
        rec("pagina Dossier audit: scarica un Excel singolo", dl2.value.suggested_filename.endswith(".xlsx"), dl2.value.suggested_filename)
        rec("menù laterale: voce Dossier audit", p.locator("#rail a[href='?view=dossier']").count() == 1)
        pv.goto(BASE + "?view=dossier"); pv.wait_for_selector("main"); rec("viewer: vede la pagina Dossier audit", pv.locator("#dosZip").count() == 1)
        for qs_ in ("&lang=fr", "&fw=boh", "&from=" + lastm + "&to=" + ym):
            p.goto(BASE + "?view=dossier" + qs_); p.wait_for_selector("main")
        p.goto(BASE + "?view=lang&l=en&f=missing"); p.wait_for_selector("main"); rec("le stringhe dei documenti compaiono tra quelle traducibili", "Report esecutivo" in p.content() or p.locator("textarea[name^='t[']").count() > 0)

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
