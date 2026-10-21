#!/usr/bin/env python3
"""Chat per utente sui PC con più sessioni (1.67.0): heartbeat per sessione, ticket dell'utente giusto, console con schede per utente,
scelta locale dell'icona adottata dalla console, agent precedente (una sola conversazione) ancora servito.
Uso: python3 ci/chat_sessions_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8843; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-chatsess-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = bad = 0
def rec(n, c, x=""):
    global ok, bad
    if c: ok += 1; print("OK  ", n)
    else: bad += 1; print("FALLITO", n, str(x)[:300])
DB = os.path.join(srv, "data", "myrmm.sqlite")
def q(sql, *a):
    c = sqlite3.connect(DB, timeout=20); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
A, B = "PC\\anna", "PC\\bruno"
try:
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"}), timeout=5)
    except Exception: pass
    time.sleep(1)
    def hb(key, chat, extra=None):
        body = {"light": True, "chat": chat}; body.update(extra or {})
        return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"}), timeout=15).read())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    q("INSERT OR IGNORE INTO sites(name,created) VALUES('Acme',?)", now)
    q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('TS-01','Windows Server 2022','ks','Acme',?, '{}',?)", now, now)
    q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('PC-VECCHIO','Windows 11','kv','Acme',?, '{}',?)", now, now)
    did = q("SELECT id FROM devices WHERE hostname='TS-01'")[0][0]; vid = q("SELECT id FROM devices WHERE hostname='PC-VECCHIO'")[0][0]

    # ---- agent -> server: due utenti scrivono sullo stesso device
    r = hb("ks", {"tray": True, "users": [A, B], "sessions": [
        {"user": A, "ack": 0, "read": 0, "out": [{"cid": "a1", "text": "il mio Outlook non parte"}]},
        {"user": B, "ack": 0, "read": 0, "out": [{"cid": "b1", "text": "la stampante non stampa", "ticket": "1", "title": "Stampante ferma"}]}]})
    rows = q("SELECT usr, author, text FROM chat_msgs WHERE dir='user' ORDER BY id")
    rec("heartbeat: ogni messaggio porta il suo utente", rows == [(A, A, "il mio Outlook non parte"), (B, B, "la stampante non stampa")], rows)
    rec("heartbeat: conferme per sessione", r["chat"]["sessions"][A]["ok"] == ["a1"] and r["chat"]["sessions"][B]["ok"] == ["b1"], r.get("chat"))
    tk = q("SELECT id, title, device_id FROM tickets WHERE title='Stampante ferma'")
    rec("ticket dalla tray: aperto a nome dell'utente giusto", len(tk) == 1 and q("SELECT ticket_usr FROM chats WHERE device_id=?", did)[0][0] == B)
    note = q("SELECT author FROM ticket_notes WHERE ticket_id=? AND kind='in'", tk[0][0])
    rec("ticket dalla tray: nota con il nome di Bruno", note and note[0][0] == B, note)
    rec("la risposta automatica «richiesta registrata» è solo per Bruno", q("SELECT usr FROM chat_msgs WHERE dir='op' AND text LIKE 'Richiesta registrata%'")[0][0] == B)
    hb("ks", {"tray": True, "sessions": [{"user": A, "ack": 0, "read": 0, "out": [{"cid": "a2", "text": "ancora io"}]}, {"user": B, "ack": 0, "read": 0, "out": [{"cid": "b2", "text": "ho riavviato la stampante"}]}]})
    rec("chat con ticket: i messaggi di Bruno sono note, quelli di Anna no", q("SELECT COUNT(*) FROM ticket_notes WHERE ticket_id=? AND kind='in'", tk[0][0])[0][0] == 2)

    with sync_playwright() as pw:
        br = pw.chromium.launch(); c = br.new_context(viewport={"width": 1360, "height": 900}, bypass_csp=True); p = c.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        except Exception: pass
        p.wait_for_selector(".rail")
        # ---- console: schede per utente
        d = c.request.get(BASE + f"?action=chat_poll&device_id={did}&user=*").json()
        rec("console: poll con «*» mostra tutto e l'elenco utenti", len(d["msgs"]) >= 5 and [u["name"] for u in d["users"]] == sorted([A, B]), d.get("users"))
        d = c.request.get(BASE + f"?action=chat_poll&device_id={did}&user=" + A.replace("\\", "%5C")).json()
        rec("console: poll di Anna ha solo i suoi messaggi", all(m["usr"] in (A, "") for m in d["msgs"]) and any("Outlook" in m["text"] for m in d["msgs"]) and not any("stampante non" in m["text"] for m in d["msgs"]))
        p.goto(BASE + f"?view=chat&device_id={did}"); p.wait_for_selector("#chUsers a", timeout=15000)
        rec("console: schede Anna, Bruno e Tutti", p.locator("#chUsers a").count() == 3, p.locator("#chUsers a").all_inner_texts())
        p.locator("#chUsers a", has_text="bruno").click(); p.wait_for_timeout(600)
        rec("console: la scheda di Bruno mostra i suoi messaggi e non quelli di Anna", "stampante" in p.inner_text("#chBox") and "Outlook" not in p.inner_text("#chBox"), p.inner_text("#chBox")[:200])
        p.fill("#chTx", "Bruno, arrivo tra 5 minuti"); p.keyboard.press("Enter"); p.wait_for_timeout(900)
        rows = q("SELECT usr, text FROM chat_msgs WHERE dir='op' AND text LIKE 'Bruno,%'")
        rec("console: il messaggio parte per Bruno", rows == [(B, "Bruno, arrivo tra 5 minuti")], rows)
        p.locator("#chUsers a", has_text="Tutti").click(); p.wait_for_timeout(500); p.fill("#chTx", "Avviso per tutti: riavvio alle 18"); p.keyboard.press("Enter"); p.wait_for_timeout(900)
        rec("console: «Tutti» scrive a tutti (utente vuoto)", q("SELECT usr FROM chat_msgs WHERE text LIKE 'Avviso per tutti%'") == [("",)])
        # ---- agent: ognuno riceve solo il suo
        r = hb("ks", {"sessions": [{"user": A, "ack": 0, "read": 0, "out": []}, {"user": B, "ack": 0, "read": 0, "out": []}]})
        ta = [m["text"] for m in r["chat"]["sessions"][A]["msgs"]]; tb = [m["text"] for m in r["chat"]["sessions"][B]["msgs"]]
        rec("consegna: Anna riceve solo l'avviso generale", ta == ["Avviso per tutti: riavvio alle 18"], ta)
        rec("consegna: Bruno riceve la risposta automatica, il suo messaggio e l'avviso", any("Richiesta registrata" in t for t in tb) and "Bruno, arrivo tra 5 minuti" in tb and "Avviso per tutti: riavvio alle 18" in tb, tb)
        last_a = r["chat"]["sessions"][A]["msgs"][-1]["id"]
        hb("ks", {"sessions": [{"user": A, "ack": last_a, "read": 0, "out": []}, {"user": B, "ack": 0, "read": 0, "out": []}]})
        rec("consegna: la conferma di Anna non conferma i messaggi di Bruno", q("SELECT COUNT(*) FROM chat_msgs WHERE dir='op' AND delivered=0 AND usr=?", B)[0][0] >= 1)
        # screenshot richiesto a un solo utente
        p.locator("#chUsers a", has_text="anna").click(); p.wait_for_timeout(500)
        p.once("dialog", lambda dlg: dlg.accept()); p.click("#chAsk"); p.wait_for_timeout(900)
        rec("console: la richiesta di screenshot va solo all'utente scelto", q("SELECT usr FROM chat_msgs WHERE kind='shotreq'") == [(A,)], q("SELECT usr FROM chat_msgs WHERE kind='shotreq'"))
        rec("nessun errore JavaScript nella chat", not errs, errs)

        # ---- agent precedente: una sola conversazione, senza «sessions»
        r = hb("kv", {"out": [{"cid": "v1", "text": "ciao dall'agent vecchio"}], "ack": 0, "read": 0})
        rec("agent precedente: messaggio accettato come conversazione senza utente", r["chat"]["ok"] == ["v1"] and q("SELECT usr FROM chat_msgs WHERE cid='v1'") == [("",)], r.get("chat"))
        c.request.post(BASE + "?action=chat_send", multipart={"device_id": str(vid), "text": "risposta al vecchio"}, headers={"Origin": f"http://127.0.0.1:{PORT}"})
        r = hb("kv", {"ack": 0, "read": 0, "out": []})
        rec("agent precedente: riceve i messaggi nella forma di sempre", [m["text"] for m in r["chat"]["msgs"]] == ["risposta al vecchio"], r.get("chat"))
        d = c.request.get(BASE + f"?action=chat_poll&device_id={vid}&user=*").json()
        rec("console con agent precedente: nessuna scheda utenti", d["users"] == [])
        p.goto(BASE + f"?view=chat&device_id={vid}"); p.wait_for_timeout(1500)
        rec("console con agent precedente: la chat funziona e la barra utenti resta nascosta", "risposta al vecchio" in p.inner_text("#chBox") and not p.locator("#chUsers").is_visible())

        # ---- scelta locale dell'icona (tray-config): la console la adotta
        r = hb("ks", {}, {"tray_local": "off"})
        rec("tray-config: la console adotta «off» e lo conferma all'agent", q("SELECT tray_mode FROM devices WHERE id=?", did)[0][0] == "off" and r.get("tray_mode") == "off", r.get("tray_mode"))
        r = hb("ks", {}, {"tray_local": "on"})
        rec("tray-config: e poi «on»", q("SELECT tray_mode FROM devices WHERE id=?", did)[0][0] == "on" and r.get("tray_mode") == "on")
        rec("tray-config: valore non valido ignorato", hb("ks", {}, {"tray_local": "x"}).get("tray_mode") == "on")
        p.goto(BASE + "?view=chats&tab=pc"); rec("pannello icona: mostra gli utenti collegati", A in p.content() or "anna" in p.content().lower())
        br.close()
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} ok, {bad} falliti"); sys.exit(1 if bad else 0)
