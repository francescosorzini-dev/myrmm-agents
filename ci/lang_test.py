#!/usr/bin/env python3
"""Metodo multilingua: dizionari, correzioni in DB, filtro delle pagine, raccolta testi, lingua per utente e cliente, 1.42.0.
Uso: python3 ci/lang_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request, urllib.parse, http.cookiejar
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8799; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-lang-"); srv = os.path.join(tmp, "server")
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



    json.dump({"Il mio profilo": "My profile", "Lingua": "Language", "Password": "Password!", "predefinita del sistema": "system default", "Sistema": "System"}, open(os.path.join(srv, "lang", "en.json"), "w"), ensure_ascii=False)
    json.dump({"Il mio profilo": "Mi perfil"}, open(os.path.join(srv, "lang", "es.json"), "w"), ensure_ascii=False)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('op',?, 'operator','',1,?,0)", h, now)
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('vis',?, 'viewer','',1,?,0)", h, now)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def login(ctx, user, pw_=PW):
            pg = ctx.new_page(); pg.goto(BASE); pg.fill("input[name=username]", user); pg.click("button[type=submit]")
            pg.wait_for_selector("input[name=password]", timeout=5000); pg.fill("input[name=password]", pw_); pg.click("button[type=submit]"); pg.wait_for_selector(".rail", timeout=8000); return pg
        c = br.new_context(viewport={"width": 1360, "height": 900}); p = login(c, "admin"); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("dialog", lambda d: d.accept())
        def post(path, form=None, ctx=c, **kw): return ctx.request.post(BASE + path, form=form or {}, max_redirects=0, **kw)
        def page(url, ctx=c):
            r = ctx.request.get(BASE + url); return r.text()

        t0 = page("?view=profile")
        rec("italiano: nessuna modifica alla pagina", "<h2>Il mio profilo</h2>" in t0 and '<html lang="it"' in t0)
        # lingua predefinita inglese
        post("?action=lang_save", {"lang": "en"})
        t1 = page("?view=profile")
        rec("inglese: titolo tradotto e html lang", "<h2>My profile</h2>" in t1 and '<html lang="en"' in t1, t1[:0])
        rec("inglese: ciò che non ha traduzione resta in italiano", "Verifica in due passaggi" in t1)
        rec("inglese: corrispondenza esatta (non tocca testi più lunghi)", "Cambia password" in t1)
        rec("inglese: l'elenco delle lingue mostra i nomi propri", "Français" in t1 and "Español" in t1)
        post("?action=lang_save", {"lang": "fr"})
        t2 = page("?view=profile")
        rec("francese senza dizionario: ripiega sull'inglese", "<h2>My profile</h2>" in t2 and '<html lang="fr"' in t2)
        post("?action=lang_save", {"lang": "xx"}); rec("lingua inesistente rifiutata (resta francese)", '<html lang="fr"' in page("?view=profile"))
        # correzioni in DB prevalgono sul file
        post("?action=lang_tr_save", {"lang": "fr", "back": "view=lang&l=fr", "s[0]": "Il mio profilo", "t[0]": "Mon profil"})
        rec("francese: correzione in database", "<h2>Mon profil</h2>" in page("?view=profile"))
        post("?action=lang_tr_save", {"lang": "en", "back": "view=lang&l=en", "s[0]": "Il mio profilo", "t[0]": "Your profile"})
        post("?action=lang_save", {"lang": "en"})
        rec("la correzione in database prevale sul file", "<h2>Your profile</h2>" in page("?view=profile"))
        post("?action=lang_tr_save", {"lang": "en", "back": "view=lang&l=en", "s[0]": "Il mio profilo", "t[0]": ""})
        rec("svuotando la correzione torna il file", "<h2>My profile</h2>" in page("?view=profile"))
        # script e stile non vengono toccati
        rec("script e stile intatti", "<script" in t1 and "</script>" in t1 and "<h2>My profile</h2>" in t1)
        # ogni utente la sua lingua
        co = br.new_context(); po = login(co, "op")
        rec("operatore: vede la lingua del sistema", "<h2>My profile</h2>" in page("?view=profile", co))
        post("?action=lang_user", {"lang": "es"}, co)
        rec("operatore: lingua personale spagnola", "<h2>Mi perfil</h2>" in page("?view=profile", co) and "<h2>My profile</h2>" in page("?view=profile"))
        post("?action=lang_user", {"lang": ""}, co); rec("operatore: torna alla predefinita", "<h2>My profile</h2>" in page("?view=profile", co))
        post("?action=lang_user", {"lang": "zz"}, co); rec("lingua personale inesistente ignorata", q("SELECT lang FROM users WHERE username='op'")[0][0] == "")
        # permessi
        rec("operatore: pagina traduzioni negata", "permesso negato" in page("?view=lang&l=en", co) or "ruolo" in page("?view=lang&l=en", co))
        before = q("SELECT v FROM meta WHERE k='lang'")[0][0]; post("?action=lang_save", {"lang": "es"}, co); post("?action=lang_import", {"lang": "es"}, co)
        rec("operatore: non può cambiare la lingua del sistema", q("SELECT v FROM meta WHERE k='lang'")[0][0] == before, before)
        cv = br.new_context(); pv = login(cv, "vis"); post("?action=lang_tr_save", {"lang": "es", "s[0]": "Zeta", "t[0]": "Z"}, cv)
        rec("viewer: non può scrivere traduzioni", q("SELECT COUNT(*) FROM i18n_override WHERE src='Zeta'")[0][0] == 0)
        # export / import
        post("?action=lang_save", {"lang": "en"})
        ex = c.request.get(BASE + "?action=lang_export&l=en"); j = json.loads(ex.body())
        rec("esporta: JSON con le traduzioni esistenti", ex.status == 200 and j.get("Il mio profilo") == "My profile" and "attachment" in ex.headers["content-disposition"], list(j)[:3])
        ex2 = json.loads(c.request.get(BASE + "?action=lang_export&l=en&missing=1").body())
        rec("esporta mancanti: solo voci vuote", all(v == "" for k, v in ex2.items() if not k.startswith("__")) and "Il mio profilo" not in ex2)
        imp = os.path.join(tp := os.path.join(tmp, "x"), "imp.json"); os.makedirs(tp, exist_ok=True)
        json.dump({"Nuovo testo di prova": "New test text", "vuota": "", "x" * 3000: "troppo lunga"}, open(imp, "w"))
        p.goto(BASE + "?view=system#t=lingue"); p.wait_for_selector("form[action*=lang_import]")
        p.select_option("form[action*=lang_import] select[name=lang]", "en"); p.set_input_files("form[action*=lang_import] input[type=file]", imp); p.click("form[action*=lang_import] button"); p.wait_for_selector("main")
        rec("importa: voci valide salvate, vuote e troppo lunghe scartate", q("SELECT txt FROM i18n_override WHERE lang='en' AND src='Nuovo testo di prova'") == [("New test text",)] and q("SELECT COUNT(*) FROM i18n_override WHERE src='vuota'")[0][0] == 0 and q("SELECT COUNT(*) FROM i18n_override WHERE length(src)>2000")[0][0] == 0, p.inner_text("main")[:200])
        bad = os.path.join(tp, "bad.json"); open(bad, "w").write("non è json")
        p.goto(BASE + "?view=system#t=lingue"); p.set_input_files("form[action*=lang_import] input[type=file]", bad); p.click("form[action*=lang_import] button"); p.wait_for_selector("main")
        rec("importa: file non valido rifiutato con messaggio", "non è un JSON valido" in p.inner_text("main"), p.inner_text("main")[:200])
        # pagina di gestione
        p.goto(BASE + "?view=system#t=lingue"); p.wait_for_selector("main")
        txt = p.inner_text("main")
        rec("Sistema → Lingue: tabella di copertura per ogni lingua", "Français" in txt and "Español" in txt and "origine" in txt, txt[:100])
        post("?action=lang_save", {"collect_form": "1", "collect": "1"}); page("?view=profile"); page("?view=devices"); post("?action=lang_save", {"collect_form": "1"})
        p.goto(BASE + "?view=lang&l=en&f=all"); p.wait_for_selector("main")
        rec("pagina traduzioni: elenco e campo di modifica", p.locator("textarea[name^='t[']").count() > 0)
        first = p.locator("input[name^='s[']").first.get_attribute("value")
        p.locator("textarea[name^='t[']").first.fill("Tradotto a mano"); p.click("button:has-text('Salva questa pagina')"); p.wait_for_selector("main")
        rec("pagina traduzioni: salvataggio dal form", q("SELECT txt FROM i18n_override WHERE lang='en' AND src=?", first) == [("Tradotto a mano",)], first)
        # lingua per cliente
        p.goto(BASE + "?view=system#t=lingue"); p.wait_for_selector("form[action*=lang_site]")
        p.select_option("form[action*=lang_site] select[name='l[Acme]']", "fr"); p.click("form[action*=lang_site] button"); p.wait_for_selector("main")
        rec("lingua del cliente salvata", q("SELECT lang FROM sites WHERE name='Acme'")[0][0] == "fr" and q("SELECT lang FROM sites WHERE name='Beta'")[0][0] == "")
        # raccolta dei testi
        post("?action=lang_save", {"lang": "it"}); post("?action=lang_save", {"collect_form": "1", "collect": "1"})
        page("?view=profile"); page("?view=devices"); page("?view=scripts")
        seen = [r[0] for r in q("SELECT src FROM i18n_seen")]
        rec("raccolta: registra i testi delle pagine in italiano", "Il mio profilo" in seen and len(seen) > 15, len(seen))
        rec("raccolta: scarta nomi host, numeri e simili", not any(s in seen for s in ("A-PC1", "10.0.0.5", "42", "A-PC2")) and not any("@" in s for s in seen), [s for s in seen if re.search(r"\d", s) and " " not in s][:5])
        rec("raccolta: scarta i corpi degli script", not any(x.startswith("#") or "# ====" in x or "Write-Output" in x for x in seen), [x[:60] for x in seen if x.startswith("#") or "# ====" in x][:3])
        p.goto(BASE + "?view=lang&l=en&f=missing"); rec("i testi raccolti compaiono tra quelli da tradurre", p.locator("td:has-text('pagina')").count() >= 0 and p.locator("textarea[name^='t[']").count() > 0)
        post("?action=lang_save", {"collect_form": "1", "clear_seen": "1"})
        rec("raccolta spenta e svuotata", q("SELECT COUNT(*) FROM i18n_seen")[0][0] == 0 and q("SELECT v FROM meta WHERE k='i18n_collect'")[0][0] == "0")
        page("?view=profile"); rec("raccolta spenta: non registra più", q("SELECT COUNT(*) FROM i18n_seen")[0][0] == 0)

        # flag «non da tradurre»
        q("INSERT OR IGNORE INTO i18n_seen(src,ts) VALUES('Testo di prova uno',?),('Testo di prova due',?),('# ==== corpo script',?)", now, now, now)
        post("?action=lang_tr_save", {"lang": "en", "back": "view=lang", "s[0]": "Testo di prova uno", "t[0]": "", "nt[0]": "1", "s[1]": "Testo di prova due", "t[1]": ""})
        rec("flag: salvato per la voce spuntata e non per l'altra", q("SELECT src FROM i18n_skip ORDER BY src") == [("Testo di prova uno",)], q("SELECT src FROM i18n_skip"))
        ex = json.loads(c.request.get(BASE + "?action=lang_export&l=en&missing=1").text())
        rec("flag: esportazione dei mancanti esclude le voci flaggate e ne porta l'elenco", "Testo di prova uno" not in ex and "Testo di prova due" in ex and ex.get("__non_tradurre__") == ["Testo di prova uno"], list(ex)[:3])
        ex2 = json.loads(c.request.get(BASE + "?action=lang_export&l=en").text())
        rec("flag: esportazione completa porta l'elenco", ex2.get("__non_tradurre__") == ["Testo di prova uno"])
        p.goto(BASE + "?view=lang&l=en&f=skip"); rec("flag: filtro «Non da tradurre» le mostra spuntate", p.locator("input[name^='nt[']:checked").count() == 1 and "Testo di prova uno" in p.inner_text("main"))
        p.goto(BASE + "?view=lang&l=en&f=missing"); rec("flag: spariscono da «Da tradurre»", "Testo di prova uno" not in p.inner_text("main"))
        post("?action=lang_save", {"collect_form": "1", "collect": "1"}); q("DELETE FROM i18n_seen")
        q("INSERT INTO i18n_skip(src) VALUES('Il mio profilo')")
        page("?view=profile"); rec("flag: la raccolta non registra più un testo flaggato", "Il mio profilo" not in [r[0] for r in q("SELECT src FROM i18n_seen")])
        post("?action=lang_save", {"collect_form": "1", "collect": "0"})
        q("INSERT OR IGNORE INTO i18n_seen(src,ts) VALUES('# ==== corpo script',?)", now)
        post("?action=lang_skip_all", {"lang": "en", "f": "missing", "q": "script"})
        rec("flag: «segna tutte» sul filtro", ("# ==== corpo script",) in q("SELECT src FROM i18n_skip"))
        q("DELETE FROM i18n_skip")
        import io
        c.request.post(BASE + "?action=lang_import", multipart={"lang": "en", "f": {"name": "x.json", "mimeType": "application/json", "buffer": json.dumps({"__non_tradurre__": ["Voce A"], "Ciao mondo": "Hello world"}).encode()}}, max_redirects=0)
        rec("flag: l'importazione ricorda l'elenco e non tratta __ come testo", q("SELECT src FROM i18n_skip") == [("Voce A",)] and not q("SELECT 1 FROM i18n_override WHERE src LIKE '\\_\\_%' ESCAPE '\\'") and q("SELECT txt FROM i18n_override WHERE src='Ciao mondo'") == [("Hello world",)])
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
