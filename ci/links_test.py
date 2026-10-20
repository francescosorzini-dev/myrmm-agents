#!/usr/bin/env python3
"""Collegamenti multipli e allegati (1.39.0): apparati con più device, documenti legati a più clienti/device/apparati,
allegati su documenti, device e apparati; visibilità per perimetro clienti; cestino; eliminazione del device.
Uso: python3 ci/links_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse, http.cookiejar
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8795; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-links-"); srv = os.path.join(tmp, "server")
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
    tpath = os.path.join(tmp, "x"); os.makedirs(tpath)
    open(os.path.join(tpath, "config-switch.txt"), "w").write("hostname SW1\nvlan 10\n")
    open(os.path.join(tpath, "manuale.pdf"), "wb").write(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    open(os.path.join(tpath, "annex.docx"), "wb").write(b"PK\x03\x04fake")
    open(os.path.join(tpath, "evil.php"), "w").write("<?php echo 'x';")

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def login(user):
            c = br.new_context(viewport={"width": 1360, "height": 900}); p = c.new_page(); errs = []
            p.on("pageerror", lambda e: errs.append("JS: " + str(e)))
            p.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
            p.on("dialog", lambda d: d.accept())
            p.goto(BASE); p.fill("input[name=username]", user); p.click("button[type=submit]")
            p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
            p.wait_for_selector(".rail", timeout=8000)
            return p, errs
        p, errs = login("admin")

        def pick(wrap, text):
            """sceglie una voce nel selettore a etichette (select o combobox)."""
            w = p.locator(wrap)
            sel = w.locator("select")
            val = sel.evaluate("(s,t)=>{var o=[].find.call(s.options,function(o){return o.textContent.indexOf(t)===0});return o?o.value:null}", text)
            sel.select_option(value=val)

        # ---- migrazione dei vecchi allegati degli asset (tabella asset_files) nella tabella generale
        os.makedirs(os.path.join(srv, "data", "assets"), exist_ok=True)
        open(os.path.join(srv, "data", "assets", "legacyfile0001"), "wb").write(b"vecchio allegato")
        q("INSERT INTO assets(type_id,name,site,created,updated) VALUES((SELECT MIN(id) FROM asset_types),'Vecchio asset','Acme',?,?)", now, now)
        oa = q("SELECT id FROM assets WHERE name='Vecchio asset'")[0][0]
        q("INSERT INTO asset_files(asset_id,name,stored,size,ts,author) VALUES(?,?,?,?,?,?)", oa, "vecchio.txt", "legacyfile0001", 16, now, "admin")
        p.goto(BASE + f"?view=asset&id={oa}"); p.wait_for_selector("#att")
        rec("migrazione: i vecchi allegati dell'asset compaiono tra gli allegati", "vecchio.txt" in p.inner_text("#att") and not q("SELECT 1 FROM asset_files"))
        lh = p.locator("#att a", has_text="vecchio.txt").first.get_attribute("href")
        rec("migrazione: il vecchio allegato si scarica ancora", b"vecchio allegato" in p.request.get(BASE.replace("index.php", "") + lh).body())

        # ---- apparato con più device
        tid = q("SELECT MIN(id) FROM asset_types")[0][0]
        p.goto(BASE + f"?view=asset&type={tid}"); p.wait_for_selector("form[action$=asset_save]")
        p.fill("input[name=name]", "Stampante piano 1"); p.select_option("select[name=site]", "Acme")
        p.locator("select[name=device_id]").select_option(value=str(dev["A-PC1"]))
        pick(".lkp[data-name=xdev]", "A-PC2"); pick(".lkp[data-name=xdev]", "A-PC3")
        rec("apparato: chip dei device aggiunti", p.locator(".lkp[data-name=xdev] .lkchip").count() == 2)
        p.click("form[action$=asset_save] button[type=submit]"); p.wait_for_selector("text=Asset creato")
        aid = q("SELECT id FROM assets WHERE name='Stampante piano 1'")[0][0]
        rec("apparato: collegamenti salvati (principale + 2)", q("SELECT device_id FROM assets WHERE id=?", aid)[0][0] == dev["A-PC1"] and len(q("SELECT 1 FROM asset_devices WHERE asset_id=?", aid)) == 2)
        rec("apparato: elenca tutti i device", all(x in p.inner_text("main") for x in ("A-PC1", "A-PC2", "A-PC3")))
        for hn in ("A-PC1", "A-PC2", "A-PC3"):
            p.goto(BASE + f"?view=device&id={dev[hn]}"); p.wait_for_selector(".dhead")
            rec(f"device {hn}: vede l'apparato collegato", "Stampante piano 1" in p.text_content("main"))
        p.goto(BASE + f"?view=device&id={dev['B-PC1']}"); p.wait_for_selector(".dhead")
        rec("device di un altro cliente: nessun apparato", "Stampante piano 1" not in p.text_content("main"))
        # device di un altro cliente rifiutato
        p.goto(BASE + f"?view=asset&id={aid}"); p.wait_for_selector("form[action$=asset_save]")
        p.evaluate("(v)=>{var w=document.querySelector('.lkp[data-name=xdev]');var i=document.createElement('input');i.type='hidden';i.name='xdev[]';i.value=v;w.appendChild(i)}", str(dev["B-PC1"]))
        p.click("form[action$=asset_save] button[type=submit]"); p.wait_for_selector("text=altro cliente")
        rec("apparato: un device di un altro cliente è rifiutato", len(q("SELECT 1 FROM asset_devices WHERE asset_id=?", aid)) == 2)
        # toglie un chip
        p.goto(BASE + f"?view=asset&id={aid}"); p.wait_for_selector("form[action$=asset_save]")
        p.locator(".lkp[data-name=xdev] .lkchip .lkx").first.click()
        p.click("form[action$=asset_save] button[type=submit]"); p.wait_for_selector("text=Salvato")
        rec("apparato: togliere un device lo scollega", len(q("SELECT 1 FROM asset_devices WHERE asset_id=?", aid)) == 1)

        # ---- documento con più clienti, device e apparati
        p.goto(BASE + f"?view=docs&edit=0&asset={aid}"); p.wait_for_selector("form[action$=doc_save]")
        rec("documento da apparato: apparato e cliente già impostati", p.locator(".lkp[data-name=xasset] .lkchip").count() == 1 and p.input_value("form[action$=doc_save] select[name=site]") == "Acme")
        p.fill("input[name=title]", "Procedura stampa"); p.fill("#edBody", "# Stampa\n\nPassi.")
        pick(".lkp[data-name=xsite]", "Beta"); pick(".lkp[data-name=xdev]", "G-PC1")
        p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector(".md")
        did = q("SELECT id FROM docs WHERE title='Procedura stampa'")[0][0]
        links = sorted((r[0], r[1]) for r in q("SELECT kind, ref FROM doc_links WHERE doc_id=?", did))
        rec("documento: clienti, device e apparato salvati (il cliente del device si aggiunge)", links == sorted([("site", "Beta"), ("site", "Gamma"), ("device", str(dev["G-PC1"])), ("asset", str(aid))]), links)
        body = p.inner_text("main")
        rec("documento: la pagina elenca clienti, device, apparati", all(x in body for x in ("Acme", "Beta", "Gamma", "G-PC1", "Stampante piano 1")))
        p.goto(BASE + "?view=docs&site=Beta"); p.wait_for_selector("main")
        rec("elenco documenti: filtro per cliente trova anche i collegati", "Procedura stampa" in p.inner_text("main"))
        p.goto(BASE + "?view=docs"); p.wait_for_selector("main table")
        rec("elenco documenti: indica i collegamenti aggiuntivi", p.locator("tr", has_text="Procedura stampa").locator(".pill").count() >= 2)
        p.goto(BASE + f"?view=device&id={dev['G-PC1']}"); p.wait_for_selector(".dhead")
        rec("device collegato: il documento compare tra i suoi documenti", "Procedura stampa" in p.inner_text("#ddocs"))
        p.goto(BASE + f"?view=asset&id={aid}"); p.wait_for_selector("form[action$=asset_save]")
        rec("apparato: elenca il documento collegato", "Procedura stampa" in p.inner_text("#adocs"))
        # modifica: togliere un collegamento
        p.goto(BASE + f"?view=docs&edit={did}"); p.wait_for_selector("form[action$=doc_save]")
        rec("editor: i collegamenti esistenti sono precaricati", p.locator(".lkp .lkchip").count() == 4, p.locator(".lkp .lkchip").count())
        p.locator(".lkp[data-name=xdev] .lkchip .lkx").first.click(); p.locator(".lkp[data-name=xsite] .lkchip .lkx").first.click()
        p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector(".md")
        rec("editor: togliere i chip scollega", sorted(r[0] for r in q("SELECT kind FROM doc_links WHERE doc_id=?", did)) in (["asset", "site"], ["asset", "site", "site"]) and not q("SELECT 1 FROM doc_links WHERE doc_id=? AND kind='device'", did), q("SELECT kind,ref FROM doc_links WHERE doc_id=?", did))

        # ---- perimetro clienti: chi vede solo Beta/Gamma
        q("INSERT OR IGNORE INTO doc_links(doc_id,kind,ref) VALUES(?, 'site', 'Gamma')", did)
        pg, _ = login("gamma")
        pg.goto(BASE + f"?view=docs&id={did}"); pg.wait_for_selector("main")
        rec("perimetro: un utente di un cliente collegato vede il documento", "Procedura stampa" in pg.inner_text("main"))
        q("DELETE FROM doc_links WHERE doc_id=? AND kind='site' AND ref='Gamma'", did)
        pg.goto(BASE + f"?view=docs&id={did}"); pg.wait_for_selector("main")
        rec("perimetro: un utente di un cliente non collegato non lo vede", "Procedura stampa" not in pg.inner_text("main"))
        pg.context.close()

        # ---- allegati
        def upload(page, files):
            page.set_input_files("form[action$=att_up] input[type=file]", [os.path.join(tpath, f) for f in files])
            page.click("form[action$=att_up] button[type=submit]"); page.wait_for_load_state("load")
        p.goto(BASE + f"?view=docs&id={did}"); p.wait_for_selector("#att")
        upload(p, ["manuale.pdf", "annex.docx", "config-switch.txt"])
        rec("allegati documento: tre file caricati", p.locator("#att .attrow").count() == 3, p.inner_text("#att"))
        rec("allegati: icone per tipo", all(t in p.inner_text("#att") for t in ("PDF", "DOC", "TXT")))
        href = p.locator("#att .attrow a", has_text="config-switch.txt").first.get_attribute("href")
        r1 = p.request.get(BASE.replace("index.php", "") + href)
        rec("allegati: il download restituisce il contenuto e forza lo scarico", r1.ok and b"hostname SW1" in r1.body() and "attachment" in r1.headers.get("content-disposition", "") and r1.headers.get("content-type", "").startswith("application/octet-stream"), (r1.status, r1.headers))
        r2 = p.request.get(BASE.replace("index.php", "") + href + "&inline=1")
        rec("allegati: l'anteprima di un testo è sicura (sandbox, nosniff)", r2.ok and "sandbox" in r2.headers.get("content-security-policy", "") and r2.headers.get("x-content-type-options") == "nosniff" and "inline" in r2.headers.get("content-disposition", ""), r2.headers)
        upload(p, ["evil.php"])
        eid = q("SELECT id,stored FROM attachments WHERE name='evil.php'")[0]
        r3 = p.request.get(BASE.replace("index.php", "") + f"?action=att_get&id={eid[0]}&inline=1")
        rec("allegati: un .php si scarica soltanto, non si esegue né si apre", r3.ok and r3.headers.get("content-type", "").startswith("application/octet-stream") and "attachment" in r3.headers.get("content-disposition", ""))
        rec("allegati: il file su disco ha nome casuale", re.fullmatch(r"[0-9a-f]{32}", eid[1]) is not None and os.path.isfile(os.path.join(srv, "data", "assets", eid[1])))
        # apparato e device
        p.goto(BASE + f"?view=asset&id={aid}"); p.wait_for_selector("#att"); upload(p, ["manuale.pdf"])
        rec("allegati apparato: caricato", p.locator("#att .attrow").count() == 1)
        p.goto(BASE + f"?view=device&id={dev['A-PC1']}#t=dati"); p.wait_for_selector("#att")
        upload(p, ["config-switch.txt", "annex.docx"]); p.wait_for_selector("#att", state="attached")
        rec("allegati device: caricati e di nuovo nella scheda «Cliente e dati»", p.locator("#att .attrow").count() == 2 and "#t=dati" in p.url, p.url)
        # eliminazione
        p.locator("#att .attrow").first.locator("form button").click(); p.wait_for_load_state("load")
        rec("allegati device: eliminazione", p.locator("#att .attrow").count() == 1)
        # perimetro: non si scarica ciò che non si vede
        pb, _ = login("beta")
        rr = pb.request.get(BASE.replace("index.php", "") + href)
        rec("perimetro: l'allegato di un documento non visibile non si scarica", rr.status == 404, rr.status)
        pb.context.close()
        # limite di dimensione
        big = os.path.join(tpath, "grosso.bin"); open(big, "wb").write(b"0" * (30 * 1024 * 1024))
        p.goto(BASE + f"?view=asset&id={aid}"); p.wait_for_selector("#att")
        p.set_input_files("form[action$=att_up] input[type=file]", big)
        dl = []; p.on("dialog", lambda d: dl.append(d.message))
        p.click("form[action$=att_up] button[type=submit]"); p.wait_for_timeout(600)
        rec("allegati: oltre il limite il controllo nel browser blocca l'invio con un avviso", any("Troppo grande" in m for m in dl) and "att_up" not in p.url, dl)
        p.evaluate("document.querySelector('form.attup').submit()"); p.wait_for_load_state("load"); p.wait_for_selector("main")
        rec("allegati: oltre il limite anche il server risponde con un messaggio chiaro", "troppo grande" in p.inner_text("main").lower() and not q("SELECT 1 FROM attachments WHERE name='grosso.bin'"), p.inner_text("main")[:200])

        # ---- cestino: il documento eliminato torna con collegamenti e allegati
        nat = q("SELECT COUNT(*) FROM attachments WHERE kind='doc' AND ref=?", did)[0][0]; nlk = q("SELECT COUNT(*) FROM doc_links WHERE doc_id=?", did)[0][0]
        p.goto(BASE + f"?view=docs&id={did}"); p.wait_for_selector("form[action$=doc_del]"); p.click("form[action$=doc_del] button"); p.wait_for_load_state("load")
        rec("cestino: eliminando il documento allegati e collegamenti escono dalle tabelle", q("SELECT COUNT(*) FROM attachments WHERE kind='doc' AND ref=?", did)[0][0] == 0 and q("SELECT COUNT(*) FROM doc_links WHERE doc_id=?", did)[0][0] == 0)
        p.goto(BASE + "?view=trash"); p.wait_for_selector("main")
        p.locator("form[action$=trash_restore] button").first.click(); p.wait_for_load_state("load")
        rec("cestino: il ripristino riporta collegamenti e allegati", q("SELECT COUNT(*) FROM attachments WHERE kind='doc' AND ref=?", did)[0][0] == nat and q("SELECT COUNT(*) FROM doc_links WHERE doc_id=?", did)[0][0] == nlk >= 1, (nat, nlk))
        # ---- eliminazione di un device: via collegamenti e allegati
        d1 = dev["A-PC1"]; st_files = [r[0] for r in q("SELECT stored FROM attachments WHERE kind='device' AND ref=?", d1)]
        p.goto(BASE + f"?view=device&id={d1}"); p.wait_for_selector(".dhead")
        p.evaluate("(id)=>{var f=document.createElement('form');f.method='post';f.action='?action=devdelete';f.innerHTML='<input name=device_id value='+id+'><input name=id value='+id+'>';document.body.appendChild(f);f.submit()}", str(d1))
        p.wait_for_load_state("load"); time.sleep(.5)
        gone = not q("SELECT 1 FROM devices WHERE id=?", d1)
        if gone:
            rec("device eliminato: allegati e collegamenti spariscono", not q("SELECT 1 FROM attachments WHERE kind='device' AND ref=?", d1) and all(not os.path.exists(os.path.join(srv, "data", "assets", f)) for f in st_files))
        else:
            print("NOTA: azione di eliminazione device non trovata nel test, controllo saltato")
        rec("nessun errore JS", not errs, errs[:3])
        br.close()
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    bad = sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l) and "exceeds the limit" not in l))[:10]
    rec("nessun errore PHP", not bad, bad)
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok")
sys.exit(1 if f else 0)
