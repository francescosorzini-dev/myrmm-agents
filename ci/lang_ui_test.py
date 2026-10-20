#!/usr/bin/env python3
"""Console in inglese con il dizionario vero (server/lang/en.json): le pagine principali non devono lasciare italiano visibile,
i placeholder delle textarea e le etichette con dato dinamico si traducono. Uso: python3 ci/lang_ui_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8814; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-langui-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite"); res = []
def rec(name, ok, info=""):
    res.append((name, bool(ok))); print(("OK   " if ok else "FAIL ") + name + (("  [" + str(info)[:3000] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
IT = re.compile(r"\b(il|lo|gli|del|della|che|per|con|non|sono|nel|alla|dei|delle|una|più|nessun\w*|tutti|aggiungi|salva|elimina|crea|apri|chiudi|clienti|apparati|scansione|mostra|errore|impostazioni|avvia|ultimo|ogni|anche|già|puoi|solo|dopo|prima|quando|dove|come)\b", re.I)
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
    q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('PC-UNO','windows','k1','Acme',?,'{}',?)", now, now)
    did = q("SELECT id FROM devices")[0][0]
    with sync_playwright() as pw:
        br = pw.chromium.launch(); c = br.new_context(viewport={"width": 1360, "height": 900}); p = c.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail", timeout=8000)
        c.request.post(BASE + "?action=lang_save", form={"lang": "en"}, max_redirects=0)
        left = {}
        for v in ["dashboard", "devices", "tickets", "scripts", "alerts", "system", "assets", "profile", "docs", "network", "runbooks", "onboard", "fields", "import", "clients", "filters", "users", "rules", "packs", "inventory", "expiry", "assettypes", "deploy", "vars", "rules", "patch", "trash", "netwiz", "maint", "report", "lang", "jobs", "depts", "checks", "chats", "diag", "tasks", "dossier", "newdevice", f"device&id={did}", f"term&id={did}", f"services&id={did}", f"files&id={did}", f"run&id={did}"]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main", timeout=8000)
            txt = p.evaluate("document.body.innerText")
            bad = [l.strip()[:120] for l in txt.split("\n") if len(IT.findall(l)) >= 2]
            left[v] = bad
        tot = sum(len(b) for b in left.values())
        rec("pagine principali in inglese: nessuna frase italiana residua", tot == 0, json.dumps({k: v for k, v in left.items() if v}, ensure_ascii=False))
        p.goto(BASE + "?view=device&id=%d" % did); html = p.content()
        rec("etichetta con dato dinamico tradotta", "Device page" in html or "Device: PC-UNO" in html or "PC-UNO" in html and "Scheda device" not in html)
        p.goto(BASE + "?view=scripts"); p.wait_for_selector("#sltm .tm-btn"); p.click("#sltm .tm-btn"); mt_ = p.inner_text("#sltm"); rec("script: il menu etichette è in inglese", "Tags" in mt_ and "security" in mt_ and "Sicurezza" not in mt_ and "Piattaforma" not in mt_, mt_[:150]); p.keyboard.press("Escape")
        q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('PC-SPENTO','windows','k2','Acme','2020-01-01T00:00:00Z','{}',?)", now)
        def it_(sel):
            return [l.strip()[:100] for l in p.inner_text(sel).split("\n") if len(IT.findall(l)) >= 2]
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT"); p.click("#amAll") if p.locator("#amAll").is_visible() else None
        p.click("#actsel summary"); p.click("#amAll"); mt_ = p.inner_text("#actsel"); rec("device: menu Azioni in inglese", "Actions" in p.inner_text("#actsel summary") and "Full inventory" in mt_ and not it_("#actsel"), str(it_("#actsel")) + mt_[:120])
        p.locator("#actsel .mi[data-act=invreq]").click(); p.wait_for_selector("#invSum[open]"); rec("device: riepilogo prima di agire in inglese", "online now" in p.inner_text("#invSum") and not it_("#invSum"), str(it_("#invSum")) + p.inner_text("#invSum")[:200]); p.keyboard.press("Escape")
        p.click("#actsel summary"); p.locator("#actsel .mi[data-open=run]").click(); p.wait_for_selector("#bulkp.open"); rec("device: pannello Esegui in inglese", "Run on" in p.inner_text("#bulkp .bp-h") and not it_("#bulkp"), str(it_("#bulkp")))
        p.keyboard.press("Escape"); p.click("#vwsel summary"); rec("device: menu Viste in inglese", "Views" in p.inner_text("#vwsel summary") and not it_("#vwsel"), str(it_("#vwsel"))); p.click("#vwsel summary")
        p.click("#addm summary"); p.wait_for_selector("#addQ"); p.wait_for_timeout(400); rec("aggiungi: menu in inglese", "On this page" in p.inner_text("#addL") and "Device with agent" in p.inner_text("#addL") and not it_("#addm"), str(it_("#addm")) + p.inner_text("#addL")[:100]); p.keyboard.press("Escape")
        p.goto(BASE + "?view=device&id=%d" % q("SELECT id FROM devices WHERE hostname='PC-UNO'")[0][0]); p.wait_for_selector(".dhead"); p.click("#actsel summary"); mt_ = p.inner_text("#actsel")
        rec("scheda: menu Azioni in inglese", "Actions" in p.inner_text(".dhead") and "Quick diagnostics" in mt_ and "Power" in mt_ and "Maintenance" in mt_ and not it_("#actsel"), str(it_("#actsel")) + mt_[:150])
        p.locator("#actsel .mi[data-act=power]").first.click(); p.wait_for_selector("#invSum[open]"); rec("scheda: riepilogo prima di agire in inglese", "Reboot" in p.inner_text("#invSum") and not it_("#invSum"), str(it_("#invSum")) + p.inner_text("#invSum")[:200]); p.keyboard.press("Escape")
        q("DELETE FROM devices WHERE hostname='PC-SPENTO'")
        p.goto(BASE + "?view=sites"); rec("lang html impostata", p.evaluate("document.documentElement.lang") == "en")
        r = c.request.get(BASE + "?view=assets"); rec("placeholder di textarea tradotto", 'placeholder="add a note' in r.text() or "aggiungi una nota" not in r.text())
        c.request.post(BASE + "?action=lang_save", form={"collect_form": "1", "collect": "1"}, max_redirects=0); q("DELETE FROM i18n_seen")
        for v in ("lang&l=en&f=all", "assettypes", "system", "scripts", "devices", "device&id=%d" % did): p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
        seen = [r[0] for r in q("SELECT src FROM i18n_seen")]
        open("/tmp/seen.json", "w").write(json.dumps(seen, ensure_ascii=False))
        rec("raccolta in inglese: niente chiavi con <{n}> né testi già tradotti", not any("<{n}>" in x for x in seen) and not any(x.startswith("A type is a template") for x in seen), [x[:80] for x in seen if "<{n}>" in x or x.startswith("A type")][:3])
        c.request.post(BASE + "?action=lang_save", form={"collect_form": "1", "collect": "0"}, max_redirects=0)
        rec("nessun errore JS", not errs, errs[:3]); br.close()
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    bad = sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l)))[:10]
    rec("nessun errore PHP", not bad, bad)
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok"); sys.exit(1 if f else 0)
