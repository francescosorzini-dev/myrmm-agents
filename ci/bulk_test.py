#!/usr/bin/env python3
"""Menu «Azioni» degli elenchi (1.62.0): Script, Attività, Alert (con schede), Ticket, Asset; menu laterale diviso in «Libreria» e «Automazione».
Selezione multipla, voci abilitate secondo il numero di righe, riepilogo prima di agire, azione server unica ?action=bulk.
Uso: python3 ci/bulk_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8801; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"; H = {"Origin": f"http://127.0.0.1:{PORT}"}
tmp = tempfile.mkdtemp(prefix="myrmm-bulk-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog)
ok = bad = 0
def rec(n, c, x=""):
    global ok, bad
    if c: ok += 1; print("OK  ", n)
    else: bad += 1; print("FALLITO", n, str(x)[:300])
DB = os.path.join(srv, "data", "myrmm.sqlite")
def q(sql, *a):
    c = sqlite3.connect(DB, timeout=20); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
try:
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers=H), timeout=5)
    except Exception: pass
    time.sleep(1)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    q("INSERT OR IGNORE INTO sites(name,created) VALUES('Acme',?)", now)
    q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('PC-UNO','Windows 11','k1','Acme',?, '{}',?)", now, now)
    did = q("SELECT id FROM devices")[0][0]
    for i in range(4): q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,'open',?)", did, f"prova:{i}", "warn" if i else "crit", f"Alert di prova {i}", now)
    for i in range(3): q("INSERT INTO tickets(device_id,title,status,priority,assignee,site,created,updated) VALUES(?,?,'open','normal','','Acme',?,?)", did, f"Ticket di prova {i}", now, now)
    for n in ("tmpA", "tmpB", "tmpC"): q("INSERT INTO scripts(name,description,body,timeout,platform,created) VALUES(?,?,?,?,?,?)", n, "prova", "Write-Output 1", 60, "windows", now)
    with sync_playwright() as pw:
        br = pw.chromium.launch(); c = br.new_context(viewport={"width": 1360, "height": 900}); p = c.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        except Exception: pass
        p.wait_for_selector(".rail")
        def menu_open():
            if not p.evaluate("document.querySelector('#bkmenu').open"): p.click("#bkmenu summary")
        def item(label): return p.locator("#bkmenu .mi", has_text=label).first
        def confirm():
            p.wait_for_selector("#bkDlg[open]"); p.locator("#bkDlg button", has_text="Conferma").click(); p.wait_for_load_state()

        # ---- menu laterale
        p.goto(BASE + "?view=scripts"); p.wait_for_selector("main")
        grp = p.evaluate("""[...document.querySelectorAll('.rail, nav')].map(n=>n.innerText).join('\\n')""")
        lines = [l.strip() for l in grp.split("\n") if l.strip()]
        def after(g):
            i = lines.index(g) if g in lines else -1
            out = []
            for l in lines[i + 1:]:
                if l in ("Libreria", "Automazione", "Report e audit", "Amministrazione", "Parco macchine", "Assistenza"): break
                out.append(l)
            return out
        rec("menu laterale: gruppo «Libreria» con Script, Runbook, Pacchetti", i_ok := all(x in after("Libreria") for x in ("Script", "Runbook", "Pacchetti")), after("Libreria"))
        p.goto(BASE + "?view=jobs"); p.wait_for_selector("main")
        lines = [l.strip() for l in p.evaluate("[...document.querySelectorAll('.rail, nav')].map(n=>n.innerText).join('\\n')").split("\n") if l.strip()]
        rec("menu laterale: «Automazione» con Regole, Check, Patch, Attività, Manutenzione", all(x in after("Automazione") for x in ("Regole", "Check", "Patch", "Attività", "Manutenzione")) and "Script" not in after("Automazione"), after("Automazione"))

        # ---- Script
        p.goto(BASE + "?view=scripts"); p.wait_for_selector("#sltab")
        rec("script: niente pulsanti Esegui…/Modifica per riga", p.locator("#sltab a:has-text('Esegui…')").count() == 0 and p.locator("#sltab td.ra").count() == 0)
        rec("script: una casella per riga", p.locator("#sltab input.bsel").count() >= 3)
        menu_open()
        rec("script: senza selezione le voci sono disattivate", all(p.locator("#bkmenu .mi").nth(i).is_disabled() for i in range(p.locator("#bkmenu .mi").count())))
        p.keyboard.press("Escape")
        p.locator("#sltab tr", has_text="tmpA").locator("input.bsel").check(); menu_open()
        rec("script: con una riga si abilitano Esegui e Modifica", not item("Esegui su device").is_disabled() and not item("Modifica").is_disabled())
        item("Modifica").click(); p.wait_for_load_state()
        rec("script: «Modifica…» apre la scheda dello script", "edit=" in p.url and "tmpA" in p.inner_text("#edit"), p.url)
        p.goto(BASE + "?view=scripts"); p.wait_for_selector("#sltab")
        for n in ("tmpA", "tmpB"): p.locator("#sltab tr", has_text=n).locator("input.bsel").check()
        menu_open()
        rec("script: con due righe Esegui e Modifica si disattivano", item("Esegui su device").is_disabled() and item("Modifica").is_disabled() and not item("Elimina").is_disabled())
        item("Elimina").click(); p.wait_for_selector("#bkDlg[open]")
        rec("script: il riepilogo elenca i due script e avvisa", "tmpA" in p.inner_text("#bkDlg") and "tmpB" in p.inner_text("#bkDlg") and "2 elementi" in p.inner_text("#bkDlg"), p.inner_text("#bkDlg"))
        confirm()
        left = [r[0] for r in q("SELECT name FROM scripts WHERE name LIKE 'tmp%'")]
        rec("script: eliminati in blocco i due selezionati, il terzo resta", left == ["tmpC"], left)
        rec("script: messaggio di esito", "Fatto su 2 elementi" in p.inner_text("main"), p.inner_text("main")[:200])

        # ---- Alert
        p.goto(BASE + "?view=alerts"); p.wait_for_selector(".htabs")
        tabs = [t.strip().split("\n")[0] for t in p.locator(".htabs a").all_inner_texts()]
        rec("alert: schede orizzontali", [t.split(" ")[0] for t in tabs][:3] == ["Da", "Miei", "Non"] and len(tabs) == 6, tabs)
        rec("alert: niente pulsanti Prendi in carico/Posticipa/Chiudi per riga", p.locator("main table button:has-text('Prendi in carico')").count() == 0 and p.locator("main table button:has-text('Chiudi')").count() == 0 and p.locator("main table button:has-text('Posticipa')").count() == 0)
        boxes = p.locator("main input.bsel"); rec("alert: una casella per riga", boxes.count() == 4, boxes.count())
        boxes.nth(0).check(); boxes.nth(1).check(); menu_open(); item("Prendi in carico").click(); p.wait_for_selector("#bkDlg[open]")
        rec("alert: riepilogo con 2 alert", "2 elementi" in p.inner_text("#bkDlg"), p.inner_text("#bkDlg"))
        confirm()
        rec("alert: presi in carico da admin", q("SELECT COUNT(*) FROM alerts WHERE ack_by='admin'")[0][0] == 2)
        p.goto(BASE + "?view=alerts&tab=mine"); p.wait_for_selector("main")
        rec("alert: scheda Miei mostra i 2 presi in carico", p.locator("main input.bsel").count() == 2, p.locator("main input.bsel").count())
        p.locator("main input.bsel").nth(0).check(); menu_open(); item("Posticipa").click(); p.wait_for_selector("#bkDlg[open]"); confirm()
        rec("alert: posticipato con la scelta nel riepilogo", q("SELECT COUNT(*) FROM alerts WHERE snooze_until IS NOT NULL")[0][0] == 1)
        p.goto(BASE + "?view=alerts&tab=snz"); p.wait_for_selector("main")
        rec("alert: scheda Posticipati", p.locator("main input.bsel").count() == 1)
        p.locator("main input.bsel").nth(0).check(); menu_open(); item("Riattiva").click(); p.wait_for_selector("#bkDlg[open]"); confirm()
        rec("alert: riattivato", q("SELECT COUNT(*) FROM alerts WHERE snooze_until IS NOT NULL")[0][0] == 0)
        p.goto(BASE + "?view=alerts"); p.wait_for_selector("main")
        p.locator("main input.bkall").first.check(); menu_open()
        rec("alert: «seleziona tutte» conta tutte le righe", p.inner_text("#bkN") == "4", p.inner_text("#bkN"))
        item("Chiudi a mano").click(); p.wait_for_selector("#bkDlg[open]"); confirm()
        rec("alert: chiusi a mano tutti e 4", q("SELECT COUNT(*) FROM alerts WHERE status='resolved'")[0][0] == 4)
        p.goto(BASE + "?view=alerts&tab=done"); p.wait_for_selector("main")
        rec("alert: scheda Risolti", "Alert di prova" in p.inner_text("main"))
        p.goto(BASE + "?view=alerts&tab=op"); p.wait_for_selector("main"); rec("alert: scheda Per operatore", "Per operatore" in p.inner_text("main"))

        # ---- Ticket
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("main table")
        rec("ticket: una casella per riga", p.locator("main input.bsel").count() == 3, p.locator("main input.bsel").count())
        p.locator("main input.bkall").first.check(); menu_open(); item("Cambia stato").click(); p.wait_for_selector("#bkDlg[open]")
        p.select_option("#bkDlg select[name=status]", "working"); confirm()
        rec("ticket: stato cambiato su tutti e tre", q("SELECT COUNT(*) FROM tickets WHERE status='working'")[0][0] == 3)
        rec("ticket: nota di sistema nel ticket", q("SELECT COUNT(*) FROM ticket_notes WHERE kind='system' AND body LIKE 'stato:%'")[0][0] == 3)
        p.locator("main input.bsel").nth(0).check(); menu_open(); item("Cambia priorità").click(); p.wait_for_selector("#bkDlg[open]")
        p.select_option("#bkDlg select[name=priority]", "high"); confirm()
        rec("ticket: priorità cambiata su uno", q("SELECT COUNT(*) FROM tickets WHERE priority='high'")[0][0] == 1)
        p.locator("main input.bsel").nth(1).check(); menu_open(); item("Assegna a").click(); p.wait_for_selector("#bkDlg[open]"); confirm()
        rec("ticket: assegnato a me", q("SELECT COUNT(*) FROM tickets WHERE assignee='admin'")[0][0] == 1)
        p.locator("main input.bkall").first.check(); menu_open(); item("Cambia stato").click(); p.wait_for_selector("#bkDlg[open]")
        p.select_option("#bkDlg select[name=status]", "closed"); confirm()
        rec("ticket: chiusi in blocco", q("SELECT COUNT(*) FROM tickets WHERE status='closed' AND closed_at IS NOT NULL")[0][0] == 3)

        # ---- Asset
        tid = q("SELECT id FROM asset_types ORDER BY id LIMIT 1")[0][0]
        for n in ("Stampante 1", "Stampante 2"):
            r = c.request.post(BASE + "?action=asset_save", form={"id": "0", "type_id": str(tid), "name": n, "site": "Acme", "status": "attivo"}, headers=H, max_redirects=0)
        rec("asset: creati due asset di prova", q("SELECT COUNT(*) FROM assets")[0][0] == 2, q("SELECT COUNT(*) FROM assets"))
        p.goto(BASE + "?view=assets"); p.wait_for_selector("main table")
        rec("asset: caselle e menu Azioni", p.locator("main input.bsel").count() == 2 and p.locator("#bkmenu").count() == 1)
        p.locator("main input.bkall").first.check(); menu_open()
        rec("asset: «Stampa etichette QR» attiva con la selezione", not item("Stampa etichette").is_disabled())
        item("Elimina").click(); p.wait_for_selector("#bkDlg[open]"); confirm()
        rec("asset: eliminati in blocco, finiscono nel cestino", q("SELECT COUNT(*) FROM assets")[0][0] == 0 and q("SELECT COUNT(*) FROM trash WHERE kind='asset'")[0][0] == 2)

        # ---- Attività
        q("INSERT INTO jobs(device_id,script,timeout,created,origin,status) VALUES(?,?,?,?,?,'pending')", did, "Write-Output 1", 60, now, "manuale")
        q("INSERT INTO jobs(device_id,script,timeout,created,origin,status) VALUES(?,?,?,?,?,'pending')", did, "Write-Output 2", 60, now, "manuale")
        p.goto(BASE + "?view=jobs"); p.wait_for_selector("main table")
        rec("attività: niente barra «Interrompi selezionati» sopra l'elenco", p.locator("#jStop").count() == 0)
        rec("attività: caselle sui job attivi", p.locator("main input.jsel").count() == 2, p.locator("main input.jsel").count())
        menu_open(); item("Seleziona i job in coda").click(); p.wait_for_timeout(200); menu_open()
        rec("attività: «Seleziona i job in coda o in corso» li spunta", p.inner_text("#bkN") == "2", p.inner_text("#bkN"))
        p.once("dialog", lambda d: d.accept()); item("Interrompi").click(); p.wait_for_timeout(1200)
        rec("attività: interrotti senza ricaricare la pagina", q("SELECT COUNT(*) FROM jobs WHERE status IN ('cancelled','cancel')")[0][0] == 2, q("SELECT status FROM jobs"))
        rec("nessun errore JS", not errs, errs)
        br.close()
finally:
    sp.terminate()
print(f"\n{ok}/{ok + bad} ok")
err = open(os.path.join(tmp, "php.err")).read()
if "PHP Warning" in err or "PHP Fatal" in err or "PHP Notice" in err or "Deprecated" in err: print("PHP:", err[-800:]); bad += 1
sys.exit(1 if bad else 0)
