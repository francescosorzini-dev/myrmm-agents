#!/usr/bin/env python3
"""Numerazione ticket configurabile e personalizzazione del marchio (white label), 1.40.0.
Uso: python3 ci/brand_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse, http.cookiejar
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8794; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-brand-"); srv = os.path.join(tmp, "server")
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

    import struct, zlib
    def png(rgb=(200, 30, 30)):
        raw = b"".join(b"\x00" + bytes(rgb) * 8 for _ in range(8))
        def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
    tp = os.path.join(tmp, "x"); os.makedirs(tp)
    open(os.path.join(tp, "logo.png"), "wb").write(png())
    open(os.path.join(tp, "logo.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#c00"/></svg>')
    open(os.path.join(tp, "evil.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    open(os.path.join(tp, "evil2.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><circle r="1"/></svg>')
    open(os.path.join(tp, "fake.png"), "wb").write(b"not an image at all")
    open(os.path.join(tp, "big.png"), "wb").write(png() + b"\x00" * 300000)

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        # ---- login anonimo: predefiniti
        c0 = br.new_context(viewport={"width": 1360, "height": 900}); p0 = c0.new_page()
        p0.goto(BASE); html0 = p0.content()
        rec("login: titolo e nome predefiniti", "<title>Accedi · myrmm</title>" in html0 and "myrmm</div>" in html0)
        rec("login: logo predefinito (formica)", 'class="logo" viewBox' in html0 and "img class=\"logo\"" not in html0)
        rec("login: colore predefinito", "--ac:#16803c" in html0 and "--ac:#4cc776" in html0)
        rec("logo personalizzato assente: 404", c0.request.get(BASE + "?action=brand_logo").status == 404)
        c0.close()

        c = br.new_context(viewport={"width": 1360, "height": 900}); p = c.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e)))
        p.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
        p.on("dialog", lambda d: d.accept())
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        p.wait_for_selector(".rail", timeout=8000)
        rec("console: marchio predefinito nel menu", p.inner_text("#rail .brand").strip() == "myrmm" and p.locator("#rail .brand svg.logo").count() == 1)

        nav_n = [0]
        def system_page(tab="impostazioni"):
            nav_n[0] += 1
            p.goto(BASE + f"?view=system&n={nav_n[0]}#t={tab}"); p.wait_for_selector("main")
        def new_ticket(title):
            r = c.request.post(BASE + "?action=tk_new", form={"device_id": str(dev["A-PC1"]), "title": title, "priority": "normal"}, max_redirects=0)
            return r.status
        def codes(): return [x[0] for x in q("SELECT code FROM tickets ORDER BY id")]

        # ---- numerazione ticket
        system_page("codice-dei-ticket")
        rec("ticket: scheda del modello con valore predefinito", p.locator("input[name=fmt]").input_value() == "T-{YYYY}-{N:4}")
        year = time.strftime("%Y")
        new_ticket("uno"); new_ticket("due")
        cs = codes()
        rec("ticket: formato predefinito T-AAAA-NNNN", cs == [f"T-{year}-0001", f"T-{year}-0002"], cs)

        def save_fmt(f):
            system_page("codice-dei-ticket"); p.fill("input[name=fmt]", f); p.click("form[action*=tk_fmt_save] button[type=submit]"); p.wait_for_selector("main")
            return p.inner_text("main")
        t = save_fmt("T-{YY}{MM}{DD}-{N:4}")
        rec("ticket: modello salvato con messaggio", "Modello dei codici ticket salvato" in t, t[:200])
        today = time.strftime("%y%m%d", time.gmtime())
        new_ticket("tre"); new_ticket("quattro")
        cs = codes()
        rec("ticket: nuovo modello giornaliero, progressivo riparte", cs[2:] == [f"T-{today}-0001", f"T-{today}-0002"], cs)
        rec("ticket: i vecchi codici restano invariati", cs[:2] == [f"T-{year}-0001", f"T-{year}-0002"], cs)
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("main")
        rec("ticket: elenco mostra entrambi i formati", f"T-{today}-0002" in p.inner_text("main") and f"T-{year}-0001" in p.inner_text("main"))
        p.fill("input[name=q]", f"T-{today}-0001") if p.locator("input[name=q]").count() else None
        for bad in ["", "abc", "T-{N}{N}", "T-{YYYY}", "T {N}", "T-{N:9}", "T-<{N}>"]:
            if bad == "": continue
            t = save_fmt(bad)
            rec(f"ticket: modello non valido rifiutato «{bad}»", "Modello non valido" in t or "Serve esattamente" in t, t[:160])
        rec("ticket: il modello valido resta dopo i rifiuti", q("SELECT v FROM meta WHERE k='tk_fmt'")[0][0] == "T-{YY}{MM}{DD}-{N:4}")
        save_fmt("INC-{N:3}"); new_ticket("cinque"); new_ticket("sei")
        rec("ticket: modello senza data, progressivo continuo", codes()[-2:] == ["INC-001", "INC-002"], codes())
        save_fmt("")   # vuoto = predefinito
        new_ticket("sette")
        rec("ticket: modello vuoto = predefinito, prosegue il conteggio dell'anno", codes()[-1] == f"T-{year}-0003", codes())
        rec("ticket: audit del cambio modello", len(q("SELECT 1 FROM audit WHERE action='tk_fmt_save'")) >= 3)

        # ---- white label
        def brand_form(name=None, color=None, color_default=False, logo=None, logo_remove=False):
            system_page("personalizzazione-del-marchio")
            f = p.locator("form[action*=brand_save]")
            f.locator("input[name=name]").fill(name or "")
            if color: f.locator("input[name=color]").evaluate("(e,v)=>{e.value=v}", color)
            cd = f.locator("input[name=color_default]")
            cd.set_checked(bool(color_default))
            if logo: f.locator("input[name=logo]").set_input_files(logo)
            if logo_remove and f.locator("input[name=logo_remove]").count(): f.locator("input[name=logo_remove]").check()
            f.locator("button[type=submit]").click(); p.wait_for_selector("main")
            return p.inner_text("main")
        rec("marchio: scheda presente e predefiniti", (system_page("personalizzazione-del-marchio") or True) and p.locator("form[action*=brand_save] input[name=name]").input_value() == "" and p.locator("input[name=color_default]").is_checked())
        t = brand_form(name="Acme RMM", color="#0b5fff")
        rec("marchio: salvataggio nome e colore", "Personalizzazione salvata" in t, t[:200])
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        rec("marchio: nome nel menu", p.inner_text("#rail .brand").strip() == "Acme RMM")
        rec("marchio: titolo scheda", p.title() == "Acme RMM", p.title())
        rec("marchio: piè di pagina", "Acme RMM v" in p.inner_text("footer"))
        ac = p.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ac').trim()")
        rec("marchio: colore principale applicato", ac.lower() in ("#0b5fff", "#5f95ff", "#3d7bff") or ac.startswith("#"), ac)
        rec("marchio: il colore scelto compare nel CSS", "#0b5fff" in p.content().lower())
        rec("marchio: colore scuro schiarito per il tema scuro", "--ac:#0b5fff;--on-ac:#ffffff" in p.content().lower() or "--ac:#0b5fff" in p.content().lower())
        rec("marchio: logo predefinito invariato", p.locator("#rail .brand svg.logo").count() == 1)
        def rgb(v):
            m = re.match(r"#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})", v.strip().lower()); return tuple(int(x, 16) for x in m.groups())
        for tema in ("dark", "light"):
            p.evaluate(f"document.documentElement.dataset.theme='{tema}'")
            nv = {k: p.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('--{k}').trim()") for k in ("bg", "sf2", "br", "fg", "mut")}
            rec(f"marchio: sfumature dei grigi seguono il blu ({tema})", all(rgb(v)[2] >= rgb(v)[0] and rgb(v)[2] >= rgb(v)[1] for v in nv.values()) and rgb(nv["bg"])[2] > rgb(nv["bg"])[1], nv)
            rec(f"marchio: nessun verde residuo nei grigi ({tema})", not any(rgb(v)[1] > rgb(v)[2] for v in nv.values()), nv)
        p.evaluate("document.documentElement.dataset.theme='dark'")
        rec("marchio: stato «ok/avviso/errore» resta semantico", p.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ok').trim()") in ("#5fd7a3", "#0f766e"))
        p.screenshot(path="/tmp/brand-blue.png")
        c9 = br.new_context(viewport={"width": 1280, "height": 800}); p9 = c9.new_page(); p9.goto(BASE); p9.wait_for_selector(".login"); p9.screenshot(path="/tmp/brand-blue-login.png")
        lg = p9.evaluate("(()=>{var o=[];document.querySelectorAll('.login *').forEach(function(e){var c=getComputedStyle(e);[c.backgroundColor,c.backgroundImage,c.color,c.borderColor,c.fill].forEach(function(v){var m=(v||'').match(/rgba?\\((\\d+), (\\d+), (\\d+)/g);if(m)m.forEach(function(x){var n=x.match(/\\d+/g).map(Number);if(n[1]>n[2]+25&&n[1]>n[0]+25)o.push(x)})})});return o.slice(0,5)})()")
        rec("marchio: nessun verde nella pagina di accesso", not lg, lg)
        c9.close()
        c1 = br.new_context(); p1 = c1.new_page(); p1.goto(BASE); h1 = p1.content()
        rec("marchio: login usa il nome nuovo", "<title>Accedi · Acme RMM</title>" in h1 and "Acme RMM</div>" in h1)
        c1.close()
        # logo PNG
        t = brand_form(name="Acme RMM", color_default=True, logo=os.path.join(tp, "logo.png"))
        rec("marchio: logo PNG caricato", "Personalizzazione salvata" in t, t[:200])
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        rec("marchio: logo personalizzato nel menu", p.locator("#rail .brand img.logo").count() == 1 and p.locator("#rail .brand svg.logo").count() == 0)
        rec("marchio: logo visibile (caricato davvero)", p.evaluate("(()=>{var i=document.querySelector('#rail .brand img.logo');return i.complete&&i.naturalWidth>0})()"))
        rec("marchio: colore tornato predefinito", "--ac:#16803c" in p.content())
        anon = br.new_context(); ar = anon.request.get(BASE + "?action=brand_logo")
        rec("marchio: logo servito senza accesso (serve alla pagina di accesso)", ar.status == 200 and ar.headers.get("content-type") == "image/png")
        rec("marchio: intestazioni di sicurezza sul logo", "sandbox" in ar.headers.get("content-security-policy", "") and ar.headers.get("x-content-type-options") == "nosniff")
        anon.close()
        files = os.listdir(os.path.join(srv, "data", "brand"))
        rec("marchio: nome file casuale e .htaccess nella cartella", any(re.fullmatch(r"[0-9a-f]{32}\.png", f) for f in files) and ".htaccess" in files, files)
        ht = open(os.path.join(srv, "data", "brand", ".htaccess")).read()
        rec("marchio: .htaccess nega l'accesso diretto ai file (Apache)", "Require all denied" in ht and "Deny from all" in ht)
        # SVG valido sostituisce il PNG
        brand_form(name="Acme RMM", color_default=True, logo=os.path.join(tp, "logo.svg"))
        files = os.listdir(os.path.join(srv, "data", "brand"))
        rec("marchio: SVG valido accettato e PNG precedente eliminato", any(f.endswith(".svg") for f in files) and not any(f.endswith(".png") for f in files), files)
        # file non ammessi
        for nm, fn in [("SVG con script", "evil.svg"), ("SVG con evento", "evil2.svg"), ("falso PNG", "fake.png"), ("oltre 256 KB", "big.png")]:
            t = brand_form(name="Acme RMM", color_default=True, logo=os.path.join(tp, fn))
            rec(f"marchio: rifiutato {nm}", "Personalizzazione salvata" not in t and ("Formato non valido" in t or "supera" in t), t[:160])
        files = os.listdir(os.path.join(srv, "data", "brand"))
        rec("marchio: dopo i rifiuti resta solo l'SVG buono", [f for f in files if f != ".htaccess"].__len__() == 1 and any(f.endswith(".svg") for f in files), files)
        # colore e nome non validi
        t = brand_form(name='Brutto "nome"', color_default=True)
        rec("marchio: nome con virgolette rifiutato", "Nome non valido" in t, t[:160])
        system_page("personalizzazione-del-marchio"); f = p.locator("form[action*=brand_save]")
        f.locator("input[name=name]").evaluate("e=>{e.removeAttribute('maxlength');e.value='X'.repeat(41)}"); f.locator("button[type=submit]").click(); p.wait_for_selector("main")
        t41 = p.inner_text("main")
        rec("marchio: nome oltre 40 caratteri rifiutato", "Nome non valido" in t41 and q("SELECT v FROM meta WHERE k='brand_name'")[0][0] != 'X' * 41, t41[:160])
        r = c.request.post(BASE + "?action=brand_save", multipart={"name": "Acme RMM", "color": "rosso"}, max_redirects=0)
        r2 = c.request.get(BASE + "?view=system&e=1", max_redirects=0)
        rec("marchio: colore non valido rifiutato", q("SELECT v FROM meta WHERE k='brand_color'")[0][0] == "")
        # email: nome nell'oggetto
        src = open(os.path.join(srv, "index.php")).read()
        rec("marchio: oggetto email usa il nome personalizzato", "brand_name_mail()" in src and "'[myrmm" not in src)
        # contrasto: colore chiaro -> testo scuro sul pulsante; colore scuro -> testo chiaro
        def accents(color):
            brand_form(name="Acme RMM", color=color)
            return p.content().lower()
        h1 = accents("#ffe600"); h2 = accents("#001a66")
        rec("marchio: giallo chiaro: invariato sul tema scuro con testo scuro, scurito sul tema chiaro con testo bianco", "--ac:#ffe600;--on-ac:#06130b" in h1 and "--ac:#807300;--on-ac:#ffffff" in h1, re.findall(r"--ac:#[0-9a-f]{6};--on-ac:#[0-9a-f]{6}", h1))
        rec("marchio: blu notte: schiarito sul tema scuro, invariato con testo bianco sul tema chiaro", "--ac:#001a66;--on-ac:#ffffff" in h2 and "--ac:#7381ab;--on-ac:#ffffff" in h2, re.findall(r"--ac:#[0-9a-f]{6};--on-ac:#[0-9a-f]{6}", h2))
        # ripristino
        brand_form(name="", color_default=True, logo_remove=True)
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        rec("marchio: ripristino ai predefiniti", p.inner_text("#rail .brand").strip() == "myrmm" and p.locator("#rail .brand svg.logo").count() == 1 and "--ac:#16803c" in p.content())
        rec("marchio: cartella senza loghi dopo il ripristino", [f for f in os.listdir(os.path.join(srv, "data", "brand")) if f != ".htaccess"] == [])
        rec("marchio: audit del salvataggio", len(q("SELECT 1 FROM audit WHERE action='brand_save'")) >= 4)
        # accesso: solo admin
        c2 = br.new_context(); 
        r = c2.request.post(BASE + "?action=brand_save", multipart={"name": "Intruso"}, max_redirects=0)
        rec("marchio: senza accesso non si modifica", q("SELECT v FROM meta WHERE k='brand_name'")[0][0] != "Intruso")
        c2.close()

        # ---- diagnostica prestazioni
        system_page("diagnostica-prestazioni")
        rec("prestazioni: scheda presente, nessuna misura iniziale", p.locator("form[action*=perf_run]").count() == 1 and "Ultima misura" not in p.inner_text("main"))
        p.click("form[action*=perf_run] button[type=submit]"); p.wait_for_selector("main")
        txt = p.inner_text("main")
        rec("prestazioni: messaggio e tabella dopo la misura", "Misura completata" in txt and "Ultima misura" in txt)
        for voce in ["Versione", "OPcache", "Latenza di una piccola scrittura", "Scrittura di 1 MB", "5.000 inserimenti", "Scrittura singola con commit", "Elenco device (tutti)", "Conteggio audit", "Ticket aperti con device"]:
            rec(f"prestazioni: voce «{voce}»", voce in txt)
        rec("prestazioni: OPcache non attiva segnalata come critica con suggerimento (CLI)", "OPcache" in txt and ("non attiva" in txt or "attiva" in txt))
        rec("prestazioni: nessun file di prova lasciato nella cartella dati", not [f for f in os.listdir(os.path.join(srv, "data")) if f.startswith(".perf-")], os.listdir(os.path.join(srv, "data")))
        rec("prestazioni: audit registrato", len(q("SELECT 1 FROM audit WHERE action='perf_run'")) == 1)
        rec("prestazioni: database integro dopo la misura", q("PRAGMA integrity_check")[0][0] == "ok")
        j = json.loads(q("SELECT v FROM meta WHERE k='perf_last'")[0][0])
        rec("prestazioni: ogni riga ha 5 campi e uno stato valido", all(len(r) == 5 and r[3] in ("ok", "warn", "err", "info") for r in j["rows"]), j["rows"][:2])
        rec("prestazioni: nessun valore NaN/vuoto", all(r[2] != "" and "nan" not in r[2].lower() for r in j["rows"]))
        c3 = br.new_context(); r3 = c3.request.post(BASE + "?action=perf_run", max_redirects=0); c3.close()
        rec("prestazioni: senza accesso non si può lanciare", len(q("SELECT 1 FROM audit WHERE action='perf_run'")) == 1)
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
