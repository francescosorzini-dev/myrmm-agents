#!/usr/bin/env python3
"""Screenshot e immagini nella chat con l'utente (1.63.0): lato agent (heartbeat) e lato console (allega, incolla, chiedi screenshot, condividi).
Uso: python3 ci/chat_img_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.request, base64
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8802; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"; H = {"Origin": f"http://127.0.0.1:{PORT}"}
tmp = tempfile.mkdtemp(prefix="myrmm-chatimg-"); srv = os.path.join(tmp, "server")
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
    import http.client
    PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    def hb(key, chat, light=True):
        req = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"light": light, "chat": chat}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    def dev_get(key, n):
        try:
            r = urllib.request.urlopen(urllib.request.Request(BASE + "?action=chat_img_dev&n=" + n, headers={"X-Device-Key": key}), timeout=10)
            return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e: return e.code, b"", e.headers
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    q("INSERT OR IGNORE INTO sites(name,created) VALUES('Acme',?)", now)
    for hn, k in (("PC-UNO", "k1"), ("PC-DUE", "k2")):
        q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,'Windows 11',?,'Acme',?, '{}',?)", hn, k, now, now)
    did = q("SELECT id FROM devices WHERE hostname='PC-UNO'")[0][0]
    b64 = base64.b64encode(PNG).decode()
    adir = os.path.join(srv, "data", "assets")

    # ---- agent -> server
    r = hb("k1", {"out": [{"cid": "c1", "text": "", "img": b64, "kind": "shot"}]})
    row = q("SELECT img, kind, text, dir FROM chat_msgs WHERE cid='c1'")
    rec("agent: screenshot senza testo accettato e confermato", r["chat"]["ok"] == ["c1"] and len(row) == 1 and row[0][1] == "shot" and row[0][3] == "user", (r, row))
    img1 = row[0][0] if row else ""
    rec("agent: file salvato nella cartella protetta con nome casuale", bool(__import__("re").fullmatch(r"ci[0-9a-f]{32}", img1)) and os.path.isfile(os.path.join(adir, img1)) and open(os.path.join(adir, img1), "rb").read() == PNG, img1)
    hb("k1", {"out": [{"cid": "c1", "text": "", "img": b64, "kind": "shot"}]})
    rec("agent: ritrasmissione dello stesso messaggio non duplica riga né file", q("SELECT COUNT(*) FROM chat_msgs WHERE cid='c1'")[0][0] == 1 and len([f for f in os.listdir(adir) if f.startswith("ci")]) == 1)
    r = hb("k1", {"out": [{"cid": "c2", "text": "", "img": base64.b64encode(b"<html><script>alert(1)</script>").decode()}]})
    rec("agent: contenuto non immagine senza testo scartato (e confermato per non ritrasmettere)", q("SELECT COUNT(*) FROM chat_msgs WHERE cid='c2'")[0][0] == 0 and r["chat"]["ok"] == ["c2"])
    r = hb("k1", {"out": [{"cid": "c3", "text": "guarda", "img": base64.b64encode(b"MZ\x90\x00 eseguibile").decode(), "kind": "file"}]})
    row = q("SELECT img, text FROM chat_msgs WHERE cid='c3'")
    rec("agent: file non immagine con testo: resta solo il testo", row == [("", "guarda")], row)
    r = hb("k1", {"out": [{"cid": "c4", "text": "", "img": base64.b64encode(PNG + b"\0" * 4300000).decode()}]})
    rec("agent: immagine oltre 4 MB rifiutata", q("SELECT COUNT(*) FROM chat_msgs WHERE cid='c4'")[0][0] == 0)
    r = hb("k1", {"out": [{"cid": "c5", "text": "", "img": "!!!non-base64!!!"}]})
    rec("agent: base64 non valido non rompe l'heartbeat", q("SELECT COUNT(*) FROM chat_msgs WHERE cid='c5'")[0][0] == 0 and "chat" in r)

    with sync_playwright() as pw:
        br = pw.chromium.launch(); c = br.new_context(viewport={"width": 1360, "height": 900}, bypass_csp=True); p = c.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        except Exception: pass
        p.wait_for_selector(".rail")
        # ---- lettura dalla console
        rs = c.request.get(BASE + "?action=chat_img&n=" + img1)
        rec("console: l'immagine si legge (image/png, nosniff, sandbox)", rs.status == 200 and rs.headers.get("content-type") == "image/png" and rs.headers.get("x-content-type-options") == "nosniff" and "sandbox" in rs.headers.get("content-security-policy", "") and rs.body() == PNG, (rs.status, rs.headers))
        for badn in ("ci" + "0" * 32, "../data/config.php", "..%2Fdata%2Fconfig.php", "config.php", ""):
            rb = c.request.get(BASE + "?action=chat_img&n=" + badn)
            rec(f"console: nome «{badn[:20]}» non servito", rb.status == 404 and b"password" not in rb.body().lower(), rb.status)
        c2 = br.new_context(); r0 = c2.request.get(BASE + "?action=chat_img&n=" + img1, max_redirects=0)
        rec("console: senza accesso l'immagine non si legge", r0.status != 200 or r0.body() != PNG, r0.status)
        # ---- pagina chat: l'utente ha inviato un'immagine
        p.goto(BASE + f"?view=chat&device_id={did}"); p.wait_for_selector("#chBox")
        p.wait_for_selector("#chBox img", timeout=8000)
        rec("chat console: la miniatura dell'utente compare nella conversazione", p.locator("#chBox img").count() >= 1 and img1 in (p.locator("#chBox img").first.get_attribute("src") or ""))
        rec("chat console: l'immagine è caricata davvero (non rotta)", p.evaluate("document.querySelector('#chBox img').naturalWidth") >= 1)
        rec("chat console: «guarda» con file non immagine mostra solo il testo", "guarda" in p.inner_text("#chBox"))
        # ingrandisci e condividi sul device
        p.locator("#chBox img").first.click(); p.wait_for_selector("#chLb", state="visible")
        rec("chat console: ingrandimento con Apri, Allega al device, Chiudi (senza ticket niente «Allega al ticket»)", all(p.locator("#chLbBar button", has_text=x).count() == 1 for x in ("Apri", "Allega al device", "Chiudi")) and p.locator("#chLbBar button", has_text="Allega al ticket").count() == 0)
        p.locator("#chLbBar button", has_text="Allega al device").click(); p.wait_for_function("document.querySelector('#chNote').textContent.includes('Allegata')")
        at = q("SELECT kind, ref, name, stored, size FROM attachments")
        rec("condivisione: copia tra gli allegati del device (file distinto, estensione corretta)", len(at) == 1 and at[0][0] == "device" and at[0][1] == did and at[0][2].endswith(".png") and at[0][3] != img1 and open(os.path.join(adir, at[0][3]), "rb").read() == PNG, at)
        p.keyboard.press("Escape")
        p.goto(BASE + f"?view=device&id={did}"); p.wait_for_selector("main")
        rec("scheda device: l'immagine condivisa è tra gli Allegati", "chat-" in p.inner_text("#att"))
        # ---- console -> utente: allega file
        p.goto(BASE + f"?view=chat&device_id={did}"); p.wait_for_selector("#chBox")
        tmpf = os.path.join(tmp, "foto.png"); open(tmpf, "wb").write(PNG)
        p.set_input_files("#chFile", tmpf); p.wait_for_selector("#chPrev", state="visible", timeout=5000)
        rec("chat console: allegando un'immagine compare l'anteprima con ✕", p.evaluate("document.querySelector('#chPrevImg').src.startsWith('data:image')") and p.locator("#chPrevX").count() == 1)
        p.fill("#chTx", "ecco lo schema"); p.click("#chForm button[type=submit]")
        p.wait_for_function("document.querySelectorAll('#chBox img').length>=2", timeout=8000)
        row = q("SELECT img, kind, text FROM chat_msgs WHERE dir='op' AND img<>''")
        rec("chat console: invio di immagine + testo registrato (kind file)", len(row) == 1 and row[0][1] == "file" and row[0][2] == "ecco lo schema", row)
        rec("chat console: anteprima svuotata dopo l'invio", p.evaluate("getComputedStyle(document.querySelector('#chPrev')).display") == "none")
        # solo immagine, senza testo
        p.set_input_files("#chFile", tmpf); p.wait_for_selector("#chPrev", state="visible"); p.click("#chForm button[type=submit]")
        p.wait_for_function("document.querySelectorAll('#chBox img').length>=3", timeout=8000)
        rec("chat console: invio di sola immagine accettato", q("SELECT COUNT(*) FROM chat_msgs WHERE dir='op' AND img<>''")[0][0] == 2)
        # non immagine
        txt = os.path.join(tmp, "x.txt"); open(txt, "w").write("ciao")
        p.set_input_files("#chFile", txt); time.sleep(.5)
        rec("chat console: un file non immagine non genera anteprima", p.evaluate("getComputedStyle(document.querySelector('#chPrev')).display") == "none")
        # server: rifiuta contenuto non immagine anche se dichiarato image/png
        rs = c.request.post(BASE + "?action=chat_send", headers=H, multipart={"device_id": str(did), "text": "", "img": {"name": "finta.png", "mimeType": "image/png", "buffer": b"<script>alert(1)</script>"}})
        rec("server: chat_send rifiuta un finto PNG (controllo sui byte)", rs.status == 400 and q("SELECT COUNT(*) FROM chat_msgs WHERE dir='op' AND img<>''")[0][0] == 2, rs.status)
        # incolla
        p.evaluate("""()=>{const b=atob('%s'),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);const f=new File([a],'x.png',{type:'image/png'});const dt=new DataTransfer();dt.items.add(f);document.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}))}""" % b64)
        try: p.wait_for_selector("#chPrev", state="visible", timeout=4000); pasted = True
        except Exception: pasted = False
        rec("chat console: Ctrl+V di un'immagine mostra l'anteprima", pasted)
        p.click("#chPrevX")
        # ---- richiesta di screenshot (consenso lato utente)
        p.once("dialog", lambda d: d.accept()); p.click("#chAsk"); time.sleep(1)
        row = q("SELECT kind, text FROM chat_msgs WHERE dir='op' AND kind='shotreq'")
        rec("chat console: «Chiedi uno screenshot» crea una richiesta che spiega anteprima e scelta dell'utente", len(row) == 1 and "anteprima" in row[0][1], row)
        rec("chat console: la richiesta è segnalata nella conversazione", "richiesta di screenshot" in p.inner_text("#chBox"))
        # ---- server -> agent: nomi immagine e scarico protetto
        r = hb("k1", {"ack": 0})
        msgs = r["chat"]["msgs"]; ims = [m for m in msgs if m.get("img")]
        rec("agent: i messaggi dell'assistenza portano il nome dell'immagine e il tipo", len(ims) == 2 and all(m["kind"] == "file" for m in ims) and any(m["kind"] == "shotreq" for m in msgs), msgs)
        st, body, hd = dev_get("k1", ims[0]["img"])
        rec("agent: scarico dell'immagine con la chiave del device", st == 200 and body == PNG and hd.get("Content-Type") == "image/png", st)
        st, _, _ = dev_get("k2", ims[0]["img"])
        rec("agent: un altro device non può scaricare l'immagine", st == 404, st)
        st, _, _ = dev_get("k1", img1)
        rec("agent: le immagini inviate dall'utente non si scaricano indietro (solo quelle dell'assistenza)", st == 404, st)
        st, _, _ = dev_get("k1", "../data/config.php")
        rec("agent: nome con percorso rifiutato", st == 404, st)
        try: urllib.request.urlopen(BASE + "?action=chat_img_dev&n=" + ims[0]["img"], timeout=5); noauth = 200
        except urllib.error.HTTPError as e: noauth = e.code
        rec("agent: senza chiave 401", noauth == 401, noauth)
        # ---- chat collegata a un ticket: immagine dell'utente allegata e nota; condivisione verso il ticket
        q("INSERT INTO tickets(device_id,title,status,priority,assignee,site,created,updated,channel) VALUES(?,?,'open','normal','','Acme',?,?,'tray')", did, "Stampante", now, now)
        tid = q("SELECT id FROM tickets WHERE title='Stampante'")[0][0]
        q("INSERT INTO chats(device_id,status,ticket_id,updated) VALUES(?,'open',?,?) ON CONFLICT(device_id) DO UPDATE SET ticket_id=excluded.ticket_id, status='open'", did, tid, now)
        hb("k1", {"out": [{"cid": "c6", "text": "ecco l'errore", "img": b64, "kind": "shot"}]})
        at = q("SELECT kind, ref FROM attachments WHERE kind='ticket'")
        nt = q("SELECT body, kind FROM ticket_notes WHERE ticket_id=? AND body='ecco l''errore'", tid)
        rec("ticket collegato: screenshot dell'utente allegato al ticket e testo come nota", at == [("ticket", tid)] and len(nt) == 1, (at, nt))
        hb("k1", {"out": [{"cid": "c7", "text": "", "img": b64, "kind": "shot"}]})
        rec("ticket collegato: anche lo screenshot senza testo finisce nel ticket", q("SELECT COUNT(*) FROM attachments WHERE kind='ticket'")[0][0] == 2 and q("SELECT COUNT(*) FROM ticket_notes WHERE ticket_id=? AND body='[immagine allegata]'", tid)[0][0] == 1)
        p.goto(BASE + f"?view=tickets&id={tid}"); p.wait_for_selector("#att")
        rec("ticket: riquadro Allegati con gli screenshot", p.locator("#att .attrow").count() == 2 and "chat-" in p.inner_text("#att"), p.inner_text("#att")[:200])
        p.goto(BASE + f"?view=chat&device_id={did}"); p.wait_for_selector("#chBox img")
        p.locator("#chBox img").first.click(); p.wait_for_selector("#chLb", state="visible")
        rec("chat console: con ticket collegato compare «Allega al ticket»", p.locator("#chLbBar button", has_text="Allega al ticket").count() == 1)
        p.locator("#chLbBar button", has_text="Allega al ticket").click(); p.wait_for_function("document.querySelector('#chNote').textContent.includes('ticket')")
        rec("condivisione: allegato anche al ticket dal pulsante", q("SELECT COUNT(*) FROM attachments WHERE kind='ticket'")[0][0] == 3)
        # ---- nuova richiesta con screenshot dal tray
        q("DELETE FROM chats WHERE device_id=?", did)
        before = q("SELECT COUNT(*) FROM attachments WHERE kind='ticket'")[0][0]
        hb("k1", {"out": [{"cid": "c8", "text": "non stampa", "img": b64, "kind": "shot", "ticket": "1", "title": "Stampante bloccata"}]})
        nt = q("SELECT id FROM tickets WHERE title='Stampante bloccata'")
        rec("nuova richiesta con screenshot: ticket creato e immagine allegata", len(nt) == 1 and q("SELECT COUNT(*) FROM attachments WHERE kind='ticket' AND ref=?", nt[0][0])[0][0] == 1 and q("SELECT COUNT(*) FROM attachments WHERE kind='ticket'")[0][0] == before + 1)
        # ---- conservazione 30 giorni
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 40 * 86400))
        q("UPDATE chat_msgs SET ts=? WHERE cid='c1'", old); q("UPDATE meta SET v='0' WHERE k='last_housekeeping'") if q("SELECT COUNT(*) FROM meta WHERE k='last_housekeeping'")[0][0] else q("INSERT INTO meta(k,v) VALUES('last_housekeeping','0')")
        hb("k1", {}, light=False)
        row = q("SELECT img, kind FROM chat_msgs WHERE cid='c1'")
        rec("conservazione: oltre 30 giorni il file sparisce e il messaggio resta", row == [("", "gone")] and not os.path.isfile(os.path.join(adir, img1)), row)
        at = q("SELECT stored FROM attachments WHERE kind='device'")
        rec("conservazione: la copia allegata al device resta", len(at) == 1 and os.path.isfile(os.path.join(adir, at[0][0])))
        p.goto(BASE + f"?view=chat&device_id={did}"); p.wait_for_selector("#chBox"); time.sleep(1.2)
        rec("chat console: l'immagine scaduta è indicata, senza immagine rotta", "immagine scaduta" in p.inner_text("#chBox"))
        # ---- elenco chat
        q("INSERT INTO chats(device_id,status,updated) VALUES(?,'open',?) ON CONFLICT(device_id) DO UPDATE SET status='open'", did, now)
        q("INSERT INTO chat_msgs(device_id,ts,dir,author,text,img,kind) VALUES(?,?,'user','u','',?, 'shot')", did, now + "", "ci" + "a" * 32)
        p.goto(BASE + "?view=chats"); p.wait_for_selector("main")
        rec("elenco chat: un messaggio con sola immagine mostra «immagine»", "immagine" in p.inner_text("main").lower())
        # ---- eliminazione device ripulisce i file
        files_before = [f for f in os.listdir(adir) if f.startswith("ci")]
        rec("errori JavaScript nella pagina chat", not errs, errs)
        br.close()
    print(f"\n{ok} ok, {bad} falliti")
finally:
    sp.terminate()
err = open(os.path.join(tmp, "php.err")).read()
if "PHP Warning" in err or "PHP Fatal" in err or "PHP Notice" in err or "Deprecated" in err: print("PHP:", err[-800:]); bad += 1
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
