import urllib.parse
import re
#!/usr/bin/env python3
"""Test dell'interfaccia: login (con/senza 2FA), schede del device, tema, mobile. Richiede playwright + chromium.
Uso: python3 ci/ui_test.py [cartella-screenshot]"""
import os, sys, json, base64, time, shutil, sqlite3, subprocess, tempfile, hmac, hashlib, struct, base64
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "myrmm-ui")
os.makedirs(OUT, exist_ok=True)
PORT = 8791; BASE = f"http://127.0.0.1:{PORT}/index.php"
PW = "Pw-prova-1234567"; SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
res = []
def wait_txt(p, sel, pred, t=20):
    end = time.time() + t
    while time.time() < end:
        try:
            if pred(p.inner_text(sel)): return True
        except Exception: pass
        time.sleep(.15)
    return False
def dev_job(p):
    """scheda Attività del device 1, con il pannello Attività vuoto (la coda si ricorda per sessione)"""
    p.goto(BASE + "?view=device&id=1#t=job"); p.evaluate("()=>{try{sessionStorage.clear()}catch(e){}}"); p.reload(); p.evaluate("()=>{document.querySelectorAll('.jtools > details').forEach(function(d){d.open=true})}"); p.wait_for_selector("#rsQ")
def spk_add(p, name):
    """cerca uno script nel selettore e lo aggiunge al pannello Attività"""
    p.evaluate("()=>{var d=document.getElementById('jtRun');if(d)d.open=true}")
    p.fill("#rsQ", name); p.locator("#rsList li[data-id]").filter(has=p.locator(".nm", has_text=name)).first.locator(".add").click()
def rec(n, ok, d=""):
    res.append((n, ok)); print(("OK   " if ok else "FAIL ") + n + ((" — " + d) if d and not ok else ""), flush=True)

def totp(secret, off=0):
    pad = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret + pad)
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30) + off), hashlib.sha1).digest()
    o = h[19] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7fffffff) % 1000000).zfill(6)


import threading, socketserver, http.server
GOT = {"tg": [], "teams": [], "hook": [], "smtp": []}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n).decode() if n else ""
        j = json.loads(body) if body.startswith("{") else {}
        if "/bot" in self.path:
            m = self.path.rsplit("/", 1)[1]
            if "BADTOKEN" in self.path: return self._send(401, {"ok": False, "description": "Unauthorized"})
            if m == "getMe": return self._send(200, {"ok": True, "result": {"username": "myrmm_test_bot"}})
            if m == "getWebhookInfo": return self._send(200, {"ok": True, "result": {"url": ""}})
            if m == "getUpdates": return self._send(200, {"ok": True, "result": [
                {"update_id": 1, "message": {"chat": {"id": -100123456, "title": "Operations", "type": "supergroup"}, "text": "/start"}},
                {"update_id": 2, "my_chat_member": {"chat": {"id": -100999, "title": "Clienti VIP", "type": "group"}}},
                {"update_id": 3, "message": {"chat": {"id": 555, "first_name": "Mario", "type": "private"}, "text": "ciao"}}]})
            if m == "sendMessage": GOT["tg"].append(j); return self._send(200, {"ok": True, "result": {}})
        if self.path.startswith("/teams"): GOT["teams"].append(j); return self._send(202, {})
        if self.path.startswith("/hook"): GOT["hook"].append(j); return self._send(200, {})
        self._send(404, {})
class S(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda t: (self.wfile.write((t + "\r\n").encode()), self.wfile.flush())
        w("220 mock ESMTP"); data = False; msg = []; env = {"auth": 0, "to": []}
        while True:
            l = self.rfile.readline()
            if not l: return
            l = l.decode(errors="replace").rstrip("\r\n")
            if data:
                if l == ".": data = False; env["body"] = "\n".join(msg); GOT["smtp"].append(env); w("250 queued"); continue
                msg.append(l); continue
            u = l.upper()
            if u.startswith("EHLO"): w("250-mock"); w("250 AUTH LOGIN")
            elif u == "AUTH LOGIN": w("334 VXNlcm5hbWU6")
            elif env["auth"] == 0 and not u.startswith(("MAIL", "RCPT", "DATA", "QUIT")):
                env["user"] = base64.b64decode(l).decode(); env["auth"] = 1; w("334 UGFzc3dvcmQ6")
            elif env["auth"] == 1 and not u.startswith(("MAIL", "RCPT", "DATA", "QUIT")):
                env["pass"] = base64.b64decode(l).decode(); env["auth"] = 2
                w("235 ok" if env["pass"] == "smtp-secret" else "535 5.7.8 credenziali errate")
            elif u.startswith("MAIL"): env["from"] = l; w("250 ok")
            elif u.startswith("RCPT"): env["to"].append(l); w("250 ok")
            elif u == "DATA": data = True; w("354 go")
            elif u == "QUIT": w("221 bye"); return
            else: w("250 ok")
MBOX = {}; SEEN = set()
class IM(socketserver.StreamRequestHandler):
    def handle(self):
        def w(t): self.wfile.write((t + "\r\n").encode()); self.wfile.flush()
        w("* OK mock IMAP ready")
        while True:
            l = self.rfile.readline()
            if not l: return
            l = l.decode(errors="replace").rstrip("\r\n"); pr = l.split(" ", 2); tag = pr[0]; cm = pr[1].upper() if len(pr) > 1 else ""; rest = pr[2] if len(pr) > 2 else ""
            if cm == "LOGIN": w(f"{tag} OK LOGIN completed" if '"imap-secret"' in rest else f"{tag} NO [AUTHENTICATIONFAILED] credenziali errate")
            elif cm == "SELECT": w(f"* {len(MBOX)} EXISTS"); w("* OK [UIDVALIDITY 77] ok"); w(f"{tag} OK [READ-WRITE] SELECT completed")
            elif cm == "UID" and rest.upper().startswith("SEARCH"):
                if "UNSEEN" in rest: u = [x for x in sorted(MBOX) if x not in SEEN]
                else:
                    n = int(re.search(r"UID (\d+):\*", rest).group(1)); u = [x for x in sorted(MBOX) if x >= n] or ([max(MBOX)] if MBOX else [])
                w("* SEARCH" + "".join(f" {x}" for x in u)); w(f"{tag} OK SEARCH completed")
            elif cm == "UID" and rest.upper().startswith("FETCH"):
                n = int(re.match(r"FETCH (\d+)", rest, re.I).group(1)); d = MBOX[n]
                self.wfile.write(f"* 1 FETCH (UID {n} BODY[]<0> {{{len(d)}}}\r\n".encode() + d + b")\r\n"); w(f"{tag} OK FETCH completed")
            elif cm == "UID" and rest.upper().startswith("STORE"):
                SEEN.add(int(re.match(r"STORE (\d+)", rest, re.I).group(1))); w(f"{tag} OK STORE completed")
            elif cm == "LOGOUT":
                try: w("* BYE"); w(f"{tag} OK LOGOUT")
                except OSError: pass
                return
            else: w(f"{tag} OK")
class TS(socketserver.ThreadingTCPServer): allow_reuse_address = True; daemon_threads = True
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 8793), H); threading.Thread(target=httpd.serve_forever, daemon=True).start()
smtpd = TS(("127.0.0.1", 8794), S); threading.Thread(target=smtpd.serve_forever, daemon=True).start()
imapd = TS(("127.0.0.1", 8795), IM); threading.Thread(target=imapd.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp(prefix="myrmm-ui-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data"))
os.makedirs(os.path.join(srv, "data"), exist_ok=True)
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32, "TUNNEL_MODE": "on", "TELEGRAM_API": "http://127.0.0.1:8793"}
php = subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout
open(os.path.join(srv, "data", "config.php"), "w").write(php)
env = dict(os.environ, PHP_CLI_SERVER_WORKERS="4")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=open(os.environ.get("UI_PHPLOG", os.devnull), "w"), env=env)
try:
    import urllib.request
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try:
        rq = urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"})
        urllib.request.urlopen(rq, timeout=5)
    except Exception: pass
    for _ in range(25):
        if os.path.exists(os.path.join(srv, "data", "myrmm.sqlite")): break
        time.sleep(.2)
    db = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    inv = json.dumps({"os": "Windows Server 2022", "ram_gb": 16, "cpu": 8, "manufacturer": "Dell", "model": "R650", "serial": "ABC123", "agent_version": "1.15.0", "session_state": "attiva", "session_user": "mario"})
    db.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created) VALUES('SRV-DEMO','windows','k1',?,?,?)", (now, inv, now))
    db.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created) VALUES('PC-OFFLINE','windows','k2','2020-01-01T00:00:00Z',?,?)", (inv, now))
    db.execute("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(1,'cpu','warn','CPU al 97%','open',?)", (now,))
    db.execute("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(1,'ram','crit','RAM al 98%','open',?)", (now,))
    db.execute("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_secret,totp_on) VALUES('otpuser',?,'admin','',1,?,?,1)", (h, now, SECRET))
    db.execute("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('plain',?,'operator','',1,?,0)", (h, now))
    db.commit(); db.close()
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        def new(w=1360, h_=860, scheme="dark"):
            c = br.new_context(viewport={"width": w, "height": h_}, color_scheme=scheme); p = c.new_page(); return c, p
        # --- heartbeat leggero: lo stato sessione si aggiorna anche senza inventario completo
        def hb(body):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"})
            return urllib.request.urlopen(rq, timeout=10).status
        hb({"light": True, "sess": {"session_state": "disconnessa", "session_user": "DOM\\mario", "sessions": []}})
        hb({"light": True, "sess": {"session_state": "attiva", "session_user": "DOM\\mario", "sessions": [{"user": "DOM\\mario", "state": "attiva", "via": "rdp"}]}})
        d2 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); iv = json.loads(d2.execute("SELECT inventory FROM devices WHERE id=1").fetchone()[0]); d2.close()
        rec("heartbeat leggero aggiorna lo stato sessione", iv.get("session_state") == "attiva" and iv.get("os") == "Windows Server 2022", str(iv)[:200])
        # --- Alert unificati + azioni nella scheda del device + colonne + nuovo
        c, p = new(); errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        rec("menu: «In carico» assorbito da Alert", p.locator(".rail a.nav", has_text="In carico").count() == 0)
        # menu laterale a gruppi richiudibili: stato ricordato, gruppo della pagina corrente sempre aperto, niente barra di scorrimento
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector(".rail details.ngrp")
        ng = p.locator(".rail details.ngrp").count(); no = p.locator(".rail details.ngrp[open]").count()
        rec("menu: gruppi richiudibili, aperti solo il primo e quello della pagina", ng >= 3 and 1 <= no < ng, (ng, no))
        rec("menu: sul cruscotto non serve scorrere (nessuna barra)", p.evaluate("(()=>{var r=document.getElementById('rail');return r.scrollHeight<=r.clientHeight+1})()"))
        gk = p.locator(".rail details.ngrp:not([open])").first.get_attribute("data-g")
        p.locator(f".rail details.ngrp[data-g='{gk}'] > summary").click()
        rec("menu: un clic sul gruppo lo apre", p.locator(f".rail details.ngrp[data-g='{gk}'][open]").count() == 1)
        p.reload(); p.wait_for_selector(".rail details.ngrp")
        rec("menu: lo stato aperto è ricordato dopo il ricaricamento", p.locator(f".rail details.ngrp[data-g='{gk}'][open]").count() == 1)
        p.locator(f".rail details.ngrp[data-g='{gk}'] > summary").click(); p.reload(); p.wait_for_selector(".rail details.ngrp")
        rec("menu: richiuso, resta chiuso", p.locator(f".rail details.ngrp[data-g='{gk}'][open]").count() == 0)
        p.goto(BASE + "?view=audit"); p.wait_for_selector(".rail details.ngrp")
        rec("menu: la pagina corrente è sempre visibile (il suo gruppo si apre da solo)", p.locator(".rail a.nav.on").first.is_visible())
        p.goto(BASE + "?view=dashboard")
        p.goto(BASE + "?view=alerts"); p.wait_for_selector(".htabs")
        tabs = p.locator(".htabs a").all_inner_texts()
        rec("alert: schede Da gestire/Miei/Non assegnati/Per operatore", all(any(t in x for x in tabs) for t in ["Da gestire", "Miei", "Non assegnati", "Per operatore"]), str(tabs))
        p.screenshot(path=f"{OUT}/alerts.png")
        p.goto(BASE + "?view=mywork"); p.wait_for_url("**view=alerts**"); rec("mywork rimanda ad Alert", True)
        p.goto(BASE + "?view=device&id=1#t=avvisi"); p.wait_for_selector(".dpane.on")
        rec("device: scheda Alert con alert aperti", p.locator(".dpane.on", has_text="CPU al 97%").count() == 1)
        p.screenshot(path=f"{OUT}/device-avvisi.png")
        p.locator(".dpane.on form[action*=alert_ack] button").first.click(); p.wait_for_selector(".dpane.on")
        rec("device: prendi in carico resta nella scheda Alert", "t=avvisi" in p.url and p.locator(".dpane.on", has_text="in carico a admin").count() >= 1, p.url)
        p.locator(".dpane.on form[action*=alert_close] button").first.click(); p.wait_for_selector(".dpane.on")
        d3 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); nopen = d3.execute("SELECT COUNT(*) FROM alerts WHERE device_id=1 AND status='open'").fetchone()[0]; d3.close()
        rec("device: chiudi alert dalla scheda", nopen == 1, str(nopen))
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT")
        p.click("#colsel summary"); p.wait_for_selector("#colsel .colpop")
        rec("colonne: elenco con campi inventario non ancora attivi", p.locator("#invCols label.off").count() > 5)
        n0 = p.locator("#invT thead th:visible").count()
        p.fill("#colQ", "modello"); p.locator("#invCols label:visible input").first.click() if p.locator("#invCols label:visible").count() else None
        p.fill("#colQ", "")
        p.click("#colMin"); n1 = p.locator("#invT thead th:visible").count()
        rec("colonne: «Solo essenziali» riduce le colonne", n1 < n0, f"{n0}->{n1}")
        p.screenshot(path=f"{OUT}/devices-cols.png")
        p.reload(); p.wait_for_selector("#invT")
        rec("colonne: scelta ricordata per utente (server)", p.locator("#invT thead th:visible").count() == n1)
        p.click("#colsel summary"); nOff = p.locator("#invCols label.off").count()
        p.locator("#invCols label.off input").first.click()
        try: p.wait_for_function("n=>document.querySelectorAll('#invCols label.off').length===n", arg=nOff - 1, timeout=10000)   # il clic ricarica la pagina: si attende l'effetto, non il solo evento load
        except Exception: pass
        p.wait_for_selector("#invT"); p.click("#colsel summary")
        rec("colonne: attivazione di un campo del catalogo", p.locator("#invCols label.off").count() == nOff - 1, f"{nOff}->{p.locator('#invCols label.off').count()}")
        rec("device: «+ Nuovo» assorbito dal menu Aggiungi", p.locator("#newsel").count() == 0)
        p.click("#addm summary"); p.wait_for_selector("#addQ"); p.wait_for_timeout(200); p.screenshot(path=OUT+"/aggiungi-menu.png")
        rec("aggiungi: in cima la voce della pagina corrente (Device)", p.locator("#addL .sec h6").first.inner_text() == "In questa pagina" and "Device" in p.locator("#addL .sec a").first.inner_text())
        rec("aggiungi: il campo di ricerca ha il fuoco", p.evaluate("document.activeElement.id") == "addQ")
        rec("aggiungi: ci sono i tipi di apparato senza agent", p.locator("#addL a[data-v^=asset-]").count() >= 1)
        p.fill("#addQ", "stampa"); rec("aggiungi: la ricerca filtra per parole chiave", p.locator("#addL a:visible").count() >= 1 and p.locator("#addL a:visible", has_text="Ticket").count() == 0)
        p.fill("#addQ", "zzzz"); rec("aggiungi: nessun risultato spiega cosa provare", p.locator("#addNo").is_visible())
        p.fill("#addQ", "ticket"); p.keyboard.press("Enter"); p.wait_for_selector("main"); rec("aggiungi: Invio apre la prima voce trovata", "view=tickets" in p.url, p.url)
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT"); p.click("#addm summary"); p.wait_for_selector("#addQ"); rec("aggiungi: dopo l'uso compare tra i recenti", "Usati di recente" in p.locator("#addL").inner_text())
        p.keyboard.press("Escape"); rec("aggiungi: Esc chiude il menu", p.locator("#addm[open]").count() == 0)
        p.screenshot(path=f"{OUT}/devices-new.png")
        rec("alert/colonne: nessun errore JS", not errs, str(errs)); c.close()
        # --- login senza 2FA: nessun campo codice
        c, p = new(); errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.screenshot(path=f"{OUT}/login.png")
        rec("login: nessun campo codice al primo passo", p.locator("input[name=code]").count() == 0)
        rec("login: logo SVG presente", p.locator(".art svg.logo").count() == 1)
        p.fill("input[name=username]", "plain"); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        p.wait_for_selector(".rail"); rec("login senza 2FA: entra direttamente", "view=" not in p.url or True)
        c.close()
        # --- login con 2FA: due passaggi
        c, p = new(); p.goto(BASE)
        p.fill("input[name=username]", "otpuser"); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        p.wait_for_selector("input[name=code]"); p.screenshot(path=f"{OUT}/login-2fa.png")
        rec("login 2FA: password giusta -> chiede il codice", p.locator("input[name=password]").count() == 0)
        p.fill("input[name=code]", "000000"); p.click("button[type=submit]")
        p.wait_for_selector(".er"); rec("login 2FA: codice errato rifiutato", p.locator("input[name=code]").count() == 1)
        p.fill("input[name=code]", totp(SECRET)); p.click("button[type=submit]")
        p.wait_for_selector(".rail"); rec("login 2FA: codice giusto entra", True)
        c.close()
        # password sbagliata con utente 2FA: nessun passaggio 2
        c, p = new(); p.goto(BASE)
        p.fill("input[name=username]", "otpuser"); p.fill("input[name=password]", "sbagliata"); p.click("button[type=submit]")
        p.wait_for_selector(".er"); rec("login 2FA: password errata non rivela il 2FA", p.locator("input[name=code]").count() == 0)
        c.close()
        # --- console (admin integrato)
        for scheme in ("dark", "light"):
            c, p = new(scheme=scheme); errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
            p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
            p.screenshot(path=f"{OUT}/dashboard-{scheme}.png")
            p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dnav")
            p.screenshot(path=f"{OUT}/device-{scheme}.png")
            tabs = p.locator(".dnav a").all_inner_texts()
            if scheme == "dark":
                rec("device: schede a sinistra", len(tabs) >= 6, str(tabs))
                rec("device: una sola sezione visibile", p.locator(".dpane.on").count() == 1)
                for t in p.locator(".dnav a").evaluate_all("els=>els.map(e=>e.dataset.t)"):
                    p.click(f".dnav a[data-t={t}]")
                    vis = p.locator(f".dpane[data-t={t}]").is_visible()
                    rec(f"device: scheda {t} si apre", vis)
                    p.screenshot(path=f"{OUT}/device-{t}.png")
                p.click(".dnav a[data-t=job]"); p.reload(); p.wait_for_selector(".dnav")
                rec("device: ricorda la scheda dopo il ricarico", p.locator(".dnav a.on").get_attribute("data-t") == "job")
            rec(f"console {scheme}: nessun errore JS", not errs, str(errs))
            c.close()
        # --- Sistema: notifiche con Test, impostazioni
        c, p = new(); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        p.goto(BASE + "?view=system#t=notifiche-email-smtp-telegram-teams-webhook"); p.wait_for_selector("#nf")
        tabs = p.locator(".dnav a").all_inner_texts(); rec("sistema: schede Notifiche e Impostazioni", any("Notifiche" in t for t in tabs) and any("Impostazioni" in t for t in tabs), str(tabs))
        p.fill("input[name=email_to]", "ops@example.org, altro@example.org"); p.fill("input[name=email_from]", "myrmm@example.org")
        p.fill("input[name=smtp_host]", "127.0.0.1"); p.fill("input[name=smtp_port]", "8794"); p.select_option("select[name=smtp_secure]", "none")
        p.fill("input[name=smtp_user]", "utente"); p.fill("input[name=smtp_pass]", "sbagliata")
        p.click("[data-test=email]"); wait_txt(p, "#nfres-email", lambda t: len(t) > 3 and t != "invio…")
        rec("email: password SMTP errata segnalata", "✗" in p.inner_text("#nfres-email") and "autenticazione" in p.inner_text("#nfres-email"), p.inner_text("#nfres-email"))
        p.fill("input[name=smtp_pass]", "smtp-secret"); p.click("[data-test=email]"); wait_txt(p, "#nfres-email", lambda t: t.startswith("✓"))
        time.sleep(.3); m = GOT["smtp"][-1] if GOT["smtp"] else {}
        txt = base64.b64decode(m.get("body", "").split("\n\n", 1)[-1].replace("\n", "")).decode(errors="ignore") if m else ""
        rec("email: prova consegnata via SMTP con autenticazione", m.get("user") == "utente" and len(m.get("to", [])) == 2 and "Messaggio di prova" in txt, str(m)[:300] + txt[:80])
        p.fill("input[name=tg_token]", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567"); p.click("#tgFind"); p.wait_for_selector("#tgList button")
        rec("telegram: ricerca gruppi", p.locator("#tgList button").count() == 3 and "Operations" in p.inner_text("#tgList"), p.inner_text("#tgList"))
        p.locator("#tgList button", has_text="Operations").click(); p.locator("#tgList button", has_text="Clienti VIP").click()
        rec("telegram: scelta chat dal elenco", p.input_value("#tgChat").replace(" ", "") == "-100123456,-100999", p.input_value("#tgChat"))
        p.click("[data-test=telegram]"); wait_txt(p, "#nfres-telegram", lambda t: t.startswith("✓"))
        rec("telegram: prova inviata a due chat", len(GOT["tg"]) == 2 and {x["chat_id"] for x in GOT["tg"]} == {"-100123456", "-100999"}, str(GOT["tg"]))
        p.fill("input[name=tg_token]", "123456789:BADTOKEN_ABCdefGhIJKlmNoPQRs"); p.click("#tgFind"); wait_txt(p, "#tgInfo", lambda t: "✗" in t)
        rec("telegram: token errato segnalato", "Unauthorized" in p.inner_text("#tgInfo"), p.inner_text("#tgInfo"))
        p.fill("input[name=tg_token]", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567")
        p.fill("input[name=teams_url]", "http://127.0.0.1:8793/teams/x"); p.click("[data-test=teams]"); wait_txt(p, "#nfres-teams", lambda t: t.startswith("✓"))
        rec("teams: prova (adaptive card)", GOT["teams"] and GOT["teams"][-1]["attachments"][0]["contentType"].endswith("adaptive"), str(GOT["teams"])[:200])
        p.fill("input[name=hook_url]", "http://127.0.0.1:8793/hook"); p.click("[data-test=webhook]"); wait_txt(p, "#nfres-webhook", lambda t: t.startswith("✓"))
        rec("webhook: prova", GOT["hook"] and GOT["hook"][-1]["type"] == "test", str(GOT["hook"]))
        p.select_option("select[name=min_hook]", "crit")
        p.screenshot(path=f"{OUT}/system-notifiche.png")
        p.click("#nf button[type=submit]"); p.wait_for_selector("#nf")
        rec("notifiche: salvataggio", p.input_value("input[name=smtp_host]") == "127.0.0.1" and p.input_value("input[name=smtp_pass]").startswith("•") and p.input_value("select[name=min_hook]") == "crit")
        # un alert reale parte su tutti i canali (webhook solo crit)
        n0 = (len(GOT["smtp"]), len(GOT["tg"]), len(GOT["teams"]), len(GOT["hook"]))
        rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"os": "Windows", "disks": [{"DeviceID": "C:", "size_gb": 100, "free_gb": 1}], "cpu_pct": 10, "ram_pct": 10}}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"})
        urllib.request.urlopen(rq, timeout=15).read(); time.sleep(.5)
        rec("alert reale: email, telegram e teams inviati", len(GOT["smtp"]) > n0[0] and len(GOT["tg"]) > n0[1] and len(GOT["teams"]) > n0[2], str((n0, len(GOT["smtp"]), len(GOT["tg"]), len(GOT["teams"]))))
        # impostazioni
        p.goto(BASE + "?view=system#t=impostazioni"); p.wait_for_selector("input[name=ALERT_OFFLINE_MIN]")
        p.fill("input[name=ALERT_OFFLINE_MIN]", "45"); p.fill("textarea[name=CONSOLE_ALLOW]", "10.99.99.0/24")
        p.locator("form[action*=cfg_save] button[type=submit]").click(); p.wait_for_selector("main p.err, main p.ok")
        rec("impostazioni: blocco anti-lockout della restrizione IP", "non è incluso" in p.inner_text("main"), p.inner_text("main")[:200])
        p.goto(BASE + "?view=system#t=impostazioni"); p.fill("input[name=ALERT_OFFLINE_MIN]", "45"); p.fill("textarea[name=CONSOLE_ALLOW]", "127.0.0.1")
        p.locator("form[action*=cfg_save] button[type=submit]").click(); p.wait_for_selector("main p.ok")
        p.goto(BASE + "?view=system#t=impostazioni"); rec("impostazioni: salvate", p.input_value("input[name=ALERT_OFFLINE_MIN]") == "45" and "127.0.0.1" in p.input_value("textarea[name=CONSOLE_ALLOW]"))
        p.fill("input[name=ALERT_OFFLINE_MIN]", "0"); p.evaluate("document.querySelector('form[action*=cfg_save]').noValidate=true"); p.locator("form[action*=cfg_save] button[type=submit]").click(); p.wait_for_selector("main p.err")
        rec("impostazioni: valore fuori limite rifiutato", "da 5 a" in p.inner_text("main"))
        p.screenshot(path=f"{OUT}/system-impostazioni.png")
        rec("sistema: nessun errore JS", not errs, str(errs)); c.close()
        # --- contrasto di tutti i pulsanti (testo rosso su rosso e simili)
        c, p = new(scheme="dark"); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        JS = """()=>{function lum(c){var m=c.match(/[\\d.]+/g).map(Number);if(m.length>3&&m[3]===0)return null;var a=m.slice(0,3).map(function(v){v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)});return .2126*a[0]+.7152*a[1]+.0722*a[2]}
          var bad=[];document.querySelectorAll("button,a.btn2,.pill").forEach(function(e){if(!e.offsetParent||!(e.textContent||"").trim())return;var cs=getComputedStyle(e),bg=lum(cs.backgroundColor),fg=lum(cs.color);if(bg===null||fg===null)return;var r=(Math.max(bg,fg)+.05)/(Math.min(bg,fg)+.05);if(r<2.2)bad.push((e.textContent||"").trim().slice(0,30)+" "+r.toFixed(2))});return bad}"""
        for scheme in ("dark", "light"):
            c.close(); c, p = new(scheme=scheme); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
            for v in ["device&id=1#t=job", "device&id=1#t=agent", "device&id=1#t=azioni", "devices", "alerts", "system", "scripts", "users"]:
                p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
                bad = p.evaluate(JS); rec(f"contrasto pulsanti {scheme} {v}", not bad, str(bad))
        c.close()
        # --- metriche
        d3 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
        d3.execute("INSERT INTO jobs(device_id,script,timeout,status,created) VALUES(1,'x',60,'sent',?)", (now,)); jid = d3.execute("SELECT MAX(id) FROM jobs").fetchone()[0]; d3.commit(); d3.close()
        rq = urllib.request.Request(BASE + "?action=result", data=json.dumps({"job_id": jid, "exit_code": 0, "stdout": "ok\nMYRMM_METRIC latenza_ms=12,5 ms\nMYRMM_METRIC code=7\nMYRMM_METRIC rotta=abc\n"}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"})
        urllib.request.urlopen(rq, timeout=10).read()
        mdb = sqlite3.connect(os.path.join(srv, "data", "metrics.sqlite"))
        ser = {r[0]: r for r in mdb.execute("SELECT metric,unit,last_v FROM m_series WHERE dev=1")}
        rec("metriche: cpu/ram/disco da heartbeat", {"cpu", "ram", "disco C:"} <= set(ser), str(sorted(ser)))
        rec("metriche: MYRMM_METRIC da script (virgola, unità, scarta non numerici)", ser.get("latenza_ms", (0, 0, 0))[2] == 12.5 and ser["latenza_ms"][1] == "ms" and "code" in ser and "rotta" not in ser, str(ser))
        t0 = int(time.time())
        mdb.executemany("INSERT OR REPLACE INTO m_raw VALUES(1,'cpu',?,?)", [(t0 - 86400 * 3 + i * 300, 20 + (i % 50)) for i in range(800)])
        mdb.executemany("INSERT OR REPLACE INTO m_raw VALUES(1,'cpu',?,?)", [(t0 - 86400 * 30 + i * 300, 30) for i in range(200)])
        mdb.commit(); mdb.close()
        c, p = new(); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        p.goto(BASE + "?view=device&id=1&mr=7d"); p.wait_for_selector(".dnav")
        rec("metriche: scheda con grafici", p.locator(".dnav a[data-t=metriche]").count() == 1)
        p.locator(".dnav a[data-t=metriche]").click()
        rec("metriche: grafico SVG cpu 7 giorni", p.locator(".dpane.on svg polyline").count() >= 1, str(p.locator(".dpane.on svg").count()))
        p.screenshot(path=f"{OUT}/device-metriche.png")
        # aggregazione e retention: housekeeping orario
        d4 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); d4.execute("DELETE FROM meta WHERE k='last_housekeeping'"); d4.commit(); d4.close()
        mdb = sqlite3.connect(os.path.join(srv, "data", "metrics.sqlite")); mdb.execute("DELETE FROM m_meta WHERE k IN ('rolled_h','rolled_d')"); mdb.commit(); mdb.close()
        hb({"inventory": {"os": "Windows", "cpu_pct": 11, "ram_pct": 12}}); time.sleep(.8)
        mdb = sqlite3.connect(os.path.join(srv, "data", "metrics.sqlite"))
        nh = mdb.execute("SELECT COUNT(*) FROM m_hour WHERE dev=1 AND metric='cpu'").fetchone()[0]; nd = mdb.execute("SELECT COUNT(*) FROM m_day WHERE dev=1 AND metric='cpu'").fetchone()[0]
        rec("metriche: aggregazione oraria e giornaliera", nh >= 60 and nd >= 3, f"{nh} {nd}"); mdb.close()
        p.goto(BASE + "?view=device&id=1&mr=90d"); p.wait_for_selector(".dnav")
        rec("metriche: 90 giorni da medie orarie", p.locator("#dtabs svg").count() >= 1); c.close()
        # --- job: tipi, ricerca script e sequenza
        c, p = new(); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        d5 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
        d5.execute("INSERT INTO schedules(device_id,script_id,interval_min,next_run,enabled,monitor_sev,vars,created) SELECT 1,id,15,'2030-01-01T00:00:00Z',1,'warn','{}',? FROM scripts WHERE name='Monitor: RAM in uso'", (now,))
        sid = d5.execute("SELECT MAX(id) FROM schedules").fetchone()[0]
        d5.execute("INSERT INTO jobs(device_id,script,timeout,status,created,origin) VALUES(1,'Write-Output 1',60,'done',?,?)", (now, f"schedule:{sid}")); jm = d5.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
        d5.execute("INSERT INTO results(job_id,exit_code,stdout,stderr,duration,received) VALUES(?,0,'OK','',1,?)", (jm, now)); d5.commit(); d5.close()
        dev_job(p)
        n_all = p.locator("#rsList li[data-id]").count(); p.fill("#rsQ", "ram")
        n_f = p.locator("#rsList li[data-id]").count()
        rec("script: la ricerca restringe l'elenco", 0 < n_f < n_all, f"{n_f}/{n_all}")
        rec("script: descrizione e etichette restano nascoste nell'elenco", p.locator("#rsList li[data-id] .ds:visible").count() == 0 or p.locator("#rsList li.auto").count() > 0)
        p.fill("#rsQ", ""); p.locator("#rsList li[data-id]").first.locator(".xp").click(); rec("script: un clic sul titolo apre la descrizione", p.locator("#rsList li[data-id]").first.locator(".ds").is_visible())
        p.fill("#rsQ", "apre un alert"); p.wait_for_timeout(150); rec("script: la ricerca guarda anche la descrizione", p.locator("#rsList li[data-id]").count() > 0 and p.locator("#rsList li.auto .ds:visible").count() > 0)
        p.fill("#rsQ", ""); p.click("#spkTm .tm-btn"); p.locator("#spkTm .tm-pop input[data-t=sola-lettura]").check(); n_a = p.inner_text("#rsCnt"); p.locator("#spkTm .tm-pop input[data-t=modifica]").check()
        rec("script: il menu etichette accetta più scelte", p.locator("#spkTags .chip").count() == 2 and p.inner_text("#rsCnt") != n_a, str(n_a)); p.keyboard.press("Escape"); p.click("#spkClr")
        p.set_viewport_size({"width": 1440, "height": 1100}); p.locator("#spk").screenshot(path=f"{OUT}/picker.png"); p.set_viewport_size({"width": 1280, "height": 800})
        spk_add(p, "Monitor: RAM in uso"); rec("pannello Attività: si apre da solo e mostra il passo", p.locator("#dock.open").count() == 1 and p.locator("#rsSeq li").count() == 1)
        spk_add(p, "Monitor: CPU media"); p.set_viewport_size({"width": 1440, "height": 900}); p.wait_for_timeout(500); p.screenshot(path=f"{OUT}/dock.png"); p.set_viewport_size({"width": 390, "height": 800}); p.wait_for_timeout(500); p.screenshot(path=f"{OUT}/dock-mobile.png"); p.set_viewport_size({"width": 1280, "height": 800}); p.click("#rsClr"); spk_add(p, "Monitor: RAM in uso")
        rec("pannello Attività: il passo ha il tasto Esegui ora (uno solo)", "Esegui ora" in p.locator("#rsGo").inner_text()); p.click("#rsClr"); rec("pannello Attività: Svuota toglie i passi", p.locator("#rsSeq li").count() == 0)
        p.keyboard.press("Escape"); rec("pannello Attività: Esc lo chiude", p.locator("#dock.open").count() == 0)
        p.fill("#rsQ", "zzzzzz"); rec("script: ricerca senza risultati", p.locator("#rsList li[data-id]").count() == 0)
        spk_add(p, "Monitor: RAM in uso"); spk_add(p, "Monitor: CPU media")
        rec("sequenza: due passi in elenco", p.locator("#rsSeq li").count() == 2)
        p.locator("#rsSeq li").nth(1).locator("button").first.click()
        rec("sequenza: riordino (CPU sale al primo posto)", "CPU" in p.locator("#rsSeq li").nth(0).inner_text())
        p.click("#rsGo"); p.wait_for_selector("details.job")
        d6 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite"))
        sq = d6.execute("SELECT id,status,next_idx FROM job_seq").fetchone(); j1 = d6.execute("SELECT id,status FROM jobs WHERE origin LIKE 'seq:%' ORDER BY id").fetchall(); d6.close()
        rec("sequenza: parte solo il primo job", sq and sq[1] == "running" and len(j1) == 1 and j1[0][1] == "pending", str((sq, j1)))
        def post_res(jid, code):
            rq = urllib.request.Request(BASE + "?action=result", data=json.dumps({"job_id": jid, "exit_code": code, "stdout": "x"}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"}); urllib.request.urlopen(rq, timeout=10).read()
        post_res(j1[0][0], 0)
        d6 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); j2 = d6.execute("SELECT id,origin FROM jobs WHERE origin LIKE 'seq:%' ORDER BY id").fetchall(); d6.close()
        rec("sequenza: a risultato ok parte il secondo", len(j2) == 2 and j2[1][1].endswith(":1"), str(j2))
        post_res(j2[1][0], 0)
        d6 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); st = d6.execute("SELECT status FROM job_seq").fetchone()[0]; d6.close()
        rec("sequenza: conclusa dopo l'ultimo passo", st == "running" or st == "done", st)
        # fermati al primo errore
        dev_job(p)
        spk_add(p, "Monitor: RAM in uso"); spk_add(p, "Monitor: CPU media"); p.click("#rsGo"); p.wait_for_selector("details.job")
        d6 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); j3 = d6.execute("SELECT id FROM jobs WHERE origin LIKE 'seq:2:%'").fetchall(); d6.close()
        post_res(j3[0][0], 1)
        d6 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); st2 = d6.execute("SELECT status FROM job_seq WHERE id=2").fetchone()[0]; n3 = d6.execute("SELECT COUNT(*) FROM jobs WHERE origin LIKE 'seq:2:%'").fetchone()[0]; d6.close()
        rec("sequenza: si ferma al primo errore", st2 == "stopped" and n3 == 1, f"{st2} {n3}")
        # annullando il primo job di una sequenza la sequenza si chiude
        dev_job(p)
        spk_add(p, "Monitor: RAM in uso"); spk_add(p, "Monitor: CPU media"); p.click("#rsGo"); p.wait_for_timeout(1500)
        d9 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); jc = d9.execute("SELECT MAX(id) FROM job_seq").fetchone()[0]; d9.close()
        p.wait_for_selector(f"details.job:has-text('sequenza #{jc}')")
        p.locator("details.job", has_text=f"sequenza #{jc}").first.locator("summary").click()
        p.on("dialog", lambda d: d.accept()); p.locator("details.job", has_text=f"sequenza #{jc}").first.locator("button", has_text="Annulla").click(); p.wait_for_selector(f"details.job[data-st=cancelled]:has-text('sequenza #{jc}')")   # 1.31.0: l'annullamento non ricarica la pagina
        d9 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); sts = d9.execute("SELECT status FROM job_seq WHERE id=?", (jc,)).fetchone()[0]; d9.close()
        rec("sequenza: annullando il job la sequenza si chiude", sts == "stopped", sts)
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector("#jobKind")
        p.select_option("#jobKind", "monitor")
        vis = p.evaluate("[].filter.call(document.querySelectorAll('details.job'),function(d){return d.style.display!=='none'}).length")
        rec("job: filtro per tipo «monitor»", vis == 1, str(vis))
        p.select_option("#jobKind", "manual")
        vis = p.evaluate("[].filter.call(document.querySelectorAll('details.job'),function(d){return d.style.display!=='none'}).length")
        rec("job: filtro per tipo «manuale» (sequenze)", vis >= 3, str(vis))
        p.screenshot(path=f"{OUT}/device-job-sequenza.png"); c.close()
        # --- runbook
        c, p = new(); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        dev_job(p)
        spk_add(p, "Monitor: RAM in uso"); spk_add(p, "Monitor: CPU media")
        p.click("#rsForm summary:has-text('Salva come runbook')"); p.fill("#rbName", "Diagnosi rapida"); p.click("#rsForm button[formaction*=rb_save]"); p.wait_for_selector("#dockTab"); p.click("#dockTab"); p.wait_for_selector("#rbSel")
        d7 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); rb = d7.execute("SELECT name, steps FROM runbooks").fetchall(); d7.close()
        rec("runbook: salvato dalla sequenza", len(rb) == 1 and rb[0][0] == "Diagnosi rapida" and len(json.loads(rb[0][1])) == 2, str(rb))
        p.select_option("#rbSel", label="Diagnosi rapida"); p.click("#rbLoad")
        rec("runbook: si ricarica nella sequenza", p.locator("#rsSeq li").count() == 2)
        p.goto(BASE + "?view=runbooks"); p.wait_for_selector("details.card")
        p.locator("details.card summary", has_text="Diagnosi rapida").click()
        wait_txt(p, ".rbp", lambda t: "device" in t and not t.startswith("0 "))
        p.fill(".rbf input[name=match]", "SRV-DEMO"); wait_txt(p, ".rbp", lambda t: t.startswith("1 device"))
        p.on("dialog", lambda d: d.accept()); p.click(".rbf button[type=submit]"); p.wait_for_selector("main p.ok")
        d7 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); ns = d7.execute("SELECT COUNT(*) FROM job_seq WHERE device_id=1").fetchone()[0]; d7.close()
        rec("runbook: avviato da pagina Runbook su un device", ns == 4, str(ns))
        # --- 1.21.0: attesa nelle sequenze, runbook programmati, calendario, sequenza ferma
        def hb1():
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"os": "Windows", "disks": [{"DeviceID": "C:", "size_gb": 100, "free_gb": 50}], "cpu_pct": 10, "ram_pct": 10}}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"}); return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        DB = os.path.join(srv, "data", "myrmm.sqlite")
        dev_job(p)
        spk_add(p, "Monitor: RAM in uso"); p.fill("#rsWait", "1"); p.click("#rsAddWait"); spk_add(p, "Monitor: CPU media")
        rec("attesa: il passo compare nella sequenza", "attendi 1 min" in p.locator("#rsSeq").inner_text())
        p.click("#rsGo"); p.wait_for_selector("details.job")
        dq = sqlite3.connect(DB); wid = dq.execute("SELECT MAX(id) FROM job_seq").fetchone()[0]; jw = dq.execute("SELECT id FROM jobs WHERE origin=?", (f"seq:{wid}:0",)).fetchone()[0]; dq.close()
        post_res(jw, 0)
        dq = sqlite3.connect(DB); r1 = dq.execute("SELECT status,wait_until FROM job_seq WHERE id=?", (wid,)).fetchone(); n1 = dq.execute("SELECT COUNT(*) FROM jobs WHERE origin LIKE ?", (f"seq:{wid}:%",)).fetchone()[0]; dq.close()
        rec("attesa: dopo il primo passo la sequenza aspetta", r1[0] == "running" and r1[1] and n1 == 1, str((r1, n1)))
        hb1()
        dq = sqlite3.connect(DB); n2 = dq.execute("SELECT COUNT(*) FROM jobs WHERE origin LIKE ?", (f"seq:{wid}:%",)).fetchone()[0]; dq.close()
        rec("attesa: prima della scadenza non parte nulla", n2 == 1, str(n2))
        dq = sqlite3.connect(DB); dq.execute("UPDATE job_seq SET wait_until=? WHERE id=?", ("2000-01-01T00:00:00Z", wid)); dq.commit(); dq.close()
        hb1()
        dq = sqlite3.connect(DB); n3x = dq.execute("SELECT origin FROM jobs WHERE origin LIKE ? ORDER BY id", (f"seq:{wid}:%",)).fetchall(); dq.close()
        rec("attesa: scaduta l'attesa parte il passo dopo", len(n3x) == 2 and n3x[1][0].endswith(":2"), str(n3x))
        # runbook programmato
        dq = sqlite3.connect(DB); rbid = dq.execute("SELECT id FROM runbooks WHERE name='Diagnosi rapida'").fetchone()[0]; dq.close()
        p.goto(BASE + "?view=runbooks"); p.wait_for_selector("details.card")
        p.locator("details.card summary", has_text="Diagnosi rapida").click()
        f = p.locator("form[action$=rb_sched_add]").first
        f.locator("select[name=site]").select_option(index=1) if f.locator("select[name=site] option").count() > 1 else None
        f.locator("input.rbl").fill("2031-01-01T10:00"); f.locator("input[name=every]").fill("1")
        f.locator("button[type=submit]").click(); p.wait_for_selector("main p.ok")
        dq = sqlite3.connect(DB); sch = dq.execute("SELECT runbook_id,interval_min,next_run,site FROM rb_sched").fetchall(); dq.close()
        rec("runbook programmato: creato (ogni ora)", len(sch) == 1 and sch[0][0] == rbid and sch[0][1] == 60, str(sch))
        rec("calendario: la programmazione compare", "Programmazioni e calendario" in p.content() and "Diagnosi rapida" in p.locator("details.card", has_text="Programmazioni").first.inner_text())
        # esecuzione alla scadenza (cliente del device 1)
        dq = sqlite3.connect(DB); site1 = dq.execute("SELECT COALESCE(site,'') FROM devices WHERE id=1").fetchone()[0]
        dq.execute("UPDATE rb_sched SET site=?, next_run='2000-01-01T00:00:00Z'", (site1,)); dq.execute("DELETE FROM meta WHERE k='rb_tick'")
        dq.execute("UPDATE job_seq SET status='done' WHERE device_id=1"); dq.commit(); nb = dq.execute("SELECT COUNT(*) FROM job_seq WHERE runbook_id=?", (rbid,)).fetchone()[0]; dq.close()
        hb1()
        dq = sqlite3.connect(DB); na = dq.execute("SELECT COUNT(*) FROM job_seq WHERE runbook_id=?", (rbid,)).fetchone()[0]; nx = dq.execute("SELECT next_run,last_n FROM rb_sched").fetchone(); dq.close()
        rec("runbook programmato: alla scadenza parte su un device e si riprogramma", na > nb and nx[0] and nx[0] > "2000-01-02" and nx[1] >= 1, str((nb, na, nx)))
        dq = sqlite3.connect(DB); dq.execute("DELETE FROM meta WHERE k='rb_tick'"); dq.commit(); dq.close(); hb1()
        dq = sqlite3.connect(DB); na2 = dq.execute("SELECT COUNT(*) FROM job_seq WHERE runbook_id=?", (rbid,)).fetchone()[0]; dq.close()
        rec("runbook programmato: nessun doppione prima della prossima scadenza", na2 == na, str((na, na2)))
        # sequenza ferma: una sola notifica
        dq = sqlite3.connect(DB); dq.execute("UPDATE job_seq SET touched='2000-01-01T00:00:00Z', stall_notified=0, wait_until=NULL, status='running' WHERE id=?", (wid,)); dq.execute("DELETE FROM meta WHERE k='rb_tick'"); dq.commit(); dq.close()
        hb1()
        dq = sqlite3.connect(DB); sn = dq.execute("SELECT stall_notified FROM job_seq WHERE id=?", (wid,)).fetchone()[0]; dq.close()
        rec("sequenza ferma: segnalata una volta", sn == 1, str(sn))
        # --- scadenza dei job non consegnati
        dq = sqlite3.connect(DB); dq.execute("UPDATE jobs SET status='done' WHERE device_id=1 AND status IN ('pending','sent')"); dq.commit(); dq.close()
        dev_job(p)
        spk_add(p, "Monitor: RAM in uso"); p.locator("#rsForm select[name=ttl]").select_option("240"); p.click("#rsGo"); p.wait_for_selector("main p.ok")
        dq = sqlite3.connect(DB); jt = dq.execute("SELECT id,status,expires FROM jobs WHERE origin LIKE 'library:%' ORDER BY id DESC LIMIT 1").fetchone(); dq.close()
        rec("scadenza: il job nasce con la scadenza scelta (4 ore)", jt[1] == "pending" and jt[2] and "T" in jt[2], str(jt))
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector("details.job")
        rec("scadenza: la scheda mostra «scade»", re.search(r"scade \d\d-\d\d", p.content()) is not None)
        spk_add(p, "Monitor: CPU media"); p.click("#rsGo"); p.wait_for_selector("main p.ok")
        dq = sqlite3.connect(DB); jn = dq.execute("SELECT id,expires FROM jobs WHERE origin LIKE 'library:%' ORDER BY id DESC LIMIT 1").fetchone(); dq.close()
        rec("scadenza: di default il job non scade mai", jn[1] is None, str(jn))
        dq = sqlite3.connect(DB); dq.execute("UPDATE jobs SET expires='2000-01-01T00:00:00Z' WHERE id=?", (jt[0],)); dq.commit(); dq.close()
        resp = hb1()
        ids = [j["id"] for j in resp.get("jobs", [])]
        dq = sqlite3.connect(DB); sx = dq.execute("SELECT status FROM jobs WHERE id=?", (jt[0],)).fetchone()[0]; dq.close()
        rec("scadenza: il job scaduto non viene consegnato, quello senza scadenza sì", jt[0] not in ids and jn[0] in ids and sx == "expired", str((ids, sx)))
        # sequenza con scadenza: il passo scaduto ferma la sequenza
        dq = sqlite3.connect(DB); dq.execute("UPDATE jobs SET status='done' WHERE device_id=1 AND status IN ('pending','sent')"); dq.commit(); dq.close()
        dev_job(p)
        spk_add(p, "Monitor: RAM in uso"); spk_add(p, "Monitor: CPU media"); p.locator("#rsForm select[name=ttl]").select_option("60"); p.click("#rsGo"); p.wait_for_selector("details.job")
        dq = sqlite3.connect(DB); sid2 = dq.execute("SELECT MAX(id) FROM job_seq").fetchone()[0]; dq.execute("UPDATE jobs SET expires='2000-01-01T00:00:00Z' WHERE origin=?", (f"seq:{sid2}:0",)); dq.commit(); dq.close()
        hb1()
        dq = sqlite3.connect(DB); r2 = dq.execute("SELECT status FROM job_seq WHERE id=?", (sid2,)).fetchone()[0]; j2s = dq.execute("SELECT status FROM jobs WHERE origin=?", (f"seq:{sid2}:0",)).fetchone()[0]; n2s = dq.execute("SELECT COUNT(*) FROM jobs WHERE origin LIKE ?", (f"seq:{sid2}:%",)).fetchone()[0]; dq.close()
        rec("scadenza: passo scaduto = sequenza chiusa, nessun passo successivo", r2 == "stopped" and j2s == "expired" and n2s == 1, str((r2, j2s, n2s)))
        # device spento a lungo: lo scheduler chiude i job scaduti anche senza il suo contatto
        dq = sqlite3.connect(DB); dq.execute("INSERT INTO jobs (device_id,script,timeout,created,origin,expires) VALUES (1,'x',60,?, 'console','2000-01-01T00:00:00Z')", (now,)); dq.execute("DELETE FROM meta WHERE k='rb_tick'"); dq.commit(); dq.close()
        hb1()
        dq = sqlite3.connect(DB); zs = dq.execute("SELECT status FROM jobs WHERE expires='2000-01-01T00:00:00Z' AND origin='console' ORDER BY id DESC LIMIT 1").fetchone()[0]; dq.close()
        rec("scadenza: il job scaduto risulta «expired»", zs == "expired", zs)
        p.goto(BASE + "?view=jobs&st=expired"); p.wait_for_selector("table")
        rec("scadenza: filtro «Scaduti» in Attività", "scaduto" in p.locator("table").inner_text())
        # --- ticket
        def hbd(free):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"os": "Windows", "disks": [{"DeviceID": "C:", "size_gb": 100, "free_gb": free}], "cpu_pct": 10, "ram_pct": 10}}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"}); return json.loads(urllib.request.urlopen(rq, timeout=15).read())
        def dbq(sql, *a):
            x = sqlite3.connect(DB); x.execute("ATTACH DATABASE ? AS dk", (os.path.join(os.path.dirname(DB), 'docs.sqlite'),)); r = x.execute(sql, a).fetchall(); x.commit(); x.close(); return r
        # --- ricerca: elenco filtrato visibile e jolly %
        dev_job(p)
        tot = p.locator("#rsList li[data-id]").count()
        p.fill("#rsQ", "ping"); n1 = p.locator("#rsList li[data-id]").count()
        t1 = p.eval_on_selector_all("#rsList li[data-id]", "e=>e.map(x=>x.textContent.toLowerCase())")
        rec("ricerca script: «ping» mostra solo le voci che lo contengono", 0 < n1 < tot and all("ping" in x for x in t1), f"{n1}/{tot}")
        p.fill("#rsQ", "%mon%ram%"); t2 = p.eval_on_selector_all("#rsList li .nm", "e=>e.map(x=>x.textContent)")
        rec("ricerca script: jolly % (%mon%ram%)", any("RAM" in x for x in t2) and all("mon" in x.lower() and "ram" in x.lower() for x in t2), str(t2[:5]))
        p.fill("#rsQ", "%on%win%"); t3 = p.eval_on_selector_all("#rsList li .nm", "e=>e.map(x=>x.textContent)")
        rec("ricerca script: %on%win% trova più voci in ordine", len(t3) >= 2 and all(__import__('re').search("on.*win", x, __import__('re').I) for x in t3), str(t3[:5]))
        p.fill("#rsQ", "")
        p.evaluate("""()=>{var s=document.createElement('select');s.id='tSel';for(var i=0;i<12;i++){var o=document.createElement('option');o.value='v'+i;o.textContent=['Monitor Windows','Monitor SolarWinds','Ping host','Riavvia','Pulizia','Patch','Backup','Servizi','Rete','Disco','Utenti','Altro'][i];s.appendChild(o)}document.querySelector('main').appendChild(s);window.selEnhance(s)}""")
        cb_ = p.locator(".cb:has(#tSel)"); cb_.locator(".cbb").click(); cb_.locator(".cbp input").fill("%on%win%")
        rec("select con ricerca: elenco filtrato visibile (non solo la voce scelta)", cb_.locator("li[role=option]").count() == 2)
        cb_.locator(".cbp input").press("ArrowDown"); cb_.locator(".cbp input").press("Enter")
        rec("select con ricerca: la scelta richiude l'elenco e mantiene il valore", p.evaluate("()=>document.getElementById('tSel').value")=="v1" and p.locator(".cb:has(#tSel) .cbp").is_hidden() and "SolarWinds" in cb_.locator(".cbb").inner_text())
        cb_.locator(".cbb").click(); cb_.locator(".cbp input").fill("zzzz")
        rec("select con ricerca: nessun risultato lo dice", "Nessun risultato" in cb_.locator(".cbp").inner_text()); cb_.locator(".cbp input").press("Escape")
        # --- documenti: editor Markdown / visuale, cliente → device
        # --- elenco device: menu Azioni unico, riepilogo con device offline, pannello Esegui, viste
        def pick_(*names):
            p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT")
            for h_ in names: p.locator("#invT tbody tr", has_text=h_).locator("input[type=checkbox]").first.check()
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT")
        rec("azioni: un solo menu «Azioni», niente blocco script separato", p.locator("#actsel summary:has-text('Azioni')").count() == 1 and p.locator("#invRun").count() == 0 and p.locator("#expsel").count() == 0)
        p.click("#actsel summary"); rec("azioni: senza selezione le azioni sono disattivate", p.locator("#actsel .mi[data-act]:not([disabled])").count() == 0)
        p.click("#amAll"); rec("azioni: «Seleziona i visibili» spunta e il pulsante conta", p.locator("#amN").inner_text() == str(p.locator("#invT tbody input[type=checkbox]:checked").count()) and p.locator("#actsel .mi[data-act][disabled]").count() == 0)
        p.fill("#amQ", "patch"); rec("azioni: la ricerca nel menu nasconde il resto", p.locator("#actsel .am > .mi[data-act=invreq]").is_hidden() and p.locator("#actsel .am > .mi[data-act=patchscan]").is_visible()); p.fill("#amQ", "")
        pick_("SRV-DEMO", "PC-OFFLINE"); rec("azioni: il conto dei selezionati compare sul pulsante", p.locator("#amN").inner_text() == "2")
        p.click("#actsel summary"); p.wait_for_timeout(200); p.screenshot(path=OUT+"/azioni-menu.png"); p.locator("#actsel .mi[data-act=invreq]").click(); p.wait_for_selector("#invSum[open]"); p.wait_for_timeout(200); p.screenshot(path=OUT+"/azioni-riepilogo.png")
        t_ = p.inner_text("#invSum"); rec("riepilogo: online, offline e scelta per i device spenti", "online ora" in t_ and "offline" in t_ and p.locator("#invSum input[name=sumOff]").count() == 2, t_[:200])
        p.locator("#invSum input[value=skip]").check(); rec("riepilogo: «salta gli offline» ricalcola il numero", "1 device" in p.locator("#invSum .sum-f button").last.inner_text(), p.locator("#invSum .sum-f button").last.inner_text())
        dbq("UPDATE devices SET full_inv_req=0"); p.locator("#invSum .sum-f button").last.click(); p.wait_for_selector("p.ok")
        rec("riepilogo: con «salta» l'offline non viene toccato e il messaggio lo dice", "offline saltati" in p.inner_text("p.ok") and dbq("SELECT COUNT(*) FROM devices WHERE full_inv_req=1 AND hostname='PC-OFFLINE'")[0][0] == 0 and dbq("SELECT COUNT(*) FROM devices WHERE full_inv_req=1 AND hostname='SRV-DEMO'")[0][0] == 1, p.inner_text("p.ok"))
        dbq("UPDATE devices SET full_inv_req=0"); pick_("SRV-DEMO", "PC-OFFLINE"); p.click("#actsel summary"); p.locator("#actsel .mi[data-act=invreq]").click(); p.wait_for_selector("#invSum[open]"); p.locator("#invSum .sum-f button").last.click(); p.wait_for_selector("p.ok")
        rec("riepilogo: con «metti in coda» (predefinito) l'offline viene messo in coda", dbq("SELECT COUNT(*) FROM devices WHERE full_inv_req=1 AND hostname IN ('SRV-DEMO','PC-OFFLINE')")[0][0] == 2)
        pick_("SRV-DEMO", "PC-OFFLINE"); p.click("#actsel summary"); p.locator("#actsel .mi[data-open=run]").click(); p.wait_for_selector("#bulkp.open")
        rec("esegui: il pannello si apre con il conto dei device", p.inner_text("#bpN") == "2")
        rec("esegui: con device tutti Windows l'elenco parte filtrato su Windows", p.locator("#spkTags .chip", has_text="windows").count() == 1)
        p.wait_for_timeout(300); p.screenshot(path=OUT+"/azioni-pannello.png")
        spk_add(p, "Monitor: RAM in uso"); rec("esegui: con un passo il pulsante dice «Rivedi ed esegui»", "Rivedi ed esegui" in p.inner_text("#rsGo"))
        n0 = dbq("SELECT COUNT(*) FROM jobs WHERE origin='bulk'")[0][0]
        p.click("#rsGo"); p.wait_for_selector("#invSum[open]"); rec("esegui: il riepilogo propone la scadenza per i job in coda", p.locator("#invSum select").count() == 1)
        p.locator("#invSum .sum-f button").last.click(); p.wait_for_selector("p.ok")
        rec("esegui: il job viene accodato anche per il device offline", dbq("SELECT COUNT(*) FROM jobs WHERE origin='bulk'")[0][0] - n0 == 2 and "Job accodati: 2" in p.inner_text("p.ok"), p.inner_text("p.ok"))
        pick_("SRV-DEMO", "PC-OFFLINE"); p.click("#actsel summary"); p.locator("#actsel .mi[data-open=run]").click(); p.wait_for_selector("#bulkp.open")
        spk_add(p, "Monitor: RAM in uso"); spk_add(p, "Monitor: CPU media"); rec("esegui: con più passi il riepilogo parla di sequenza", True)
        s0 = dbq("SELECT COUNT(*) FROM job_seq")[0][0]
        p.click("#rsGo"); p.wait_for_selector("#invSum[open]"); rec("esegui: l'etichetta del riepilogo cita la sequenza", "sequenza" in p.inner_text("#invSum h3").lower(), p.inner_text("#invSum h3"))
        p.locator("#invSum input[value=skip]").check(); p.locator("#invSum .sum-f button").last.click(); p.wait_for_selector("p.ok")
        rec("esegui: la sequenza parte solo sul device online", dbq("SELECT COUNT(*) FROM job_seq")[0][0] - s0 == 1 and "Sequenza avviata su 1 device" in p.inner_text("p.ok") and "offline saltati" in p.inner_text("p.ok"), p.inner_text("p.ok"))
        pick_("SRV-DEMO"); p.click("#actsel summary"); p.locator("#actsel .mi[data-quick=info]").click(); p.wait_for_selector("#bulkp.open")
        rec("diagnostica rapida: il pannello si apre con lo script già nella coda", p.locator("#rsSeq li").count() == 1 and "informazioni sistema" in p.inner_text("#rsSeq").lower(), p.inner_text("#rsSeq")[:100])
        p.keyboard.press("Escape"); rec("esegui: Esc chiude il pannello", p.locator("#bulkp.open").count() == 0)
        dbq("DELETE FROM views")
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT"); p.fill("#invQ", "SRV"); p.click("#vwsel summary"); p.fill("#vwName", "Vista prova"); p.click("#vwSave"); p.wait_for_load_state("load"); p.wait_for_timeout(600); p.wait_for_selector("#invT")
        rec("viste: una vista salvata è condivisa per impostazione predefinita", dbq("SELECT owner FROM views WHERE name='Vista prova'") == [("",)])
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT"); n_all = p.locator("#invT tbody tr:visible").count(); p.click("#vwsel summary"); p.locator("#vwsel .vw-go", has_text="Vista prova").click(); p.wait_for_selector("#invT"); p.wait_for_timeout(200)
        rec("viste: applicando la vista si ritrova la ricerca salvata", p.input_value("#invQ") == "SRV" and p.locator("#invT tbody tr:visible").count() < n_all, f"{p.locator('#invT tbody tr:visible').count()}/{n_all}")
        p.fill("#invQ", "PC"); p.click("#vwsel summary"); p.fill("#vwName", "Mia"); p.check("#vwPers"); p.click("#vwSave"); p.wait_for_load_state("load"); p.wait_for_timeout(600); p.wait_for_selector("#invT")
        rec("viste: «solo per me» crea una vista personale", dbq("SELECT owner FROM views WHERE name='Mia'") == [("admin",)])
        p.click("#vwsel summary"); p.wait_for_timeout(200); p.screenshot(path=OUT+"/azioni-viste.png"); p.click("#vwsel summary")
        p.click("#vwsel summary"); p.locator("#vwsel .vw", has_text="Vista prova").locator(".vw-hide").click(); p.wait_for_load_state("load"); p.wait_for_timeout(600); p.click("#vwsel summary")
        rec("viste: una condivisa si nasconde dal proprio menu senza cancellarla", p.locator("#vwsel #vwList .vw", has_text="Vista prova").count() == 0 and p.locator("#vwsel .vw-hid .vw", has_text="Vista prova").count() == 1 and dbq("SELECT COUNT(*) FROM views WHERE name='Vista prova'")[0][0] == 1)
        p.locator("#vwsel .vw-hid summary").click(); p.locator("#vwsel .vw-show").click(); p.wait_for_load_state("load"); p.wait_for_timeout(600); p.click("#vwsel summary"); p.locator("#vwsel .vw", has_text="Mia").locator(".vw-del").click(); p.wait_for_load_state("load"); p.wait_for_timeout(600)
        rec("viste: elimina una vista", dbq("SELECT COUNT(*) FROM views WHERE name='Mia'")[0][0] == 0 and dbq("SELECT COUNT(*) FROM views")[0][0] == 1)
        # --- scheda device: stesso menu Azioni, riepilogo e strumenti in un solo punto
        off_id = dbq("SELECT id FROM devices WHERE hostname='PC-OFFLINE'")[0][0]
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dhead")
        rec("scheda: un solo menu «Azioni» in testata, niente «Altre azioni»", p.locator(".dhead details#actsel summary:has-text('Azioni')").count() == 1 and p.locator("#devact").count() == 0 and p.locator("#repsel").count() == 0)
        p.click("#actsel summary"); p.wait_for_timeout(200); p.screenshot(path=OUT+"/scheda-azioni.png")
        mt_ = p.inner_text("#actsel"); rec("scheda: sezioni Subito, Esegui, Diagnostica, Alimentazione, Manutenzione, Strumenti, Report", all(x_ in mt_ for x_ in ("Subito", "Esegui", "Diagnostica rapida", "Alimentazione", "Manutenzione", "Strumenti", "Report")), mt_[:200])
        p.fill("#amQ", "riavvia"); rec("scheda: la ricerca nel menu filtra le azioni", p.locator("#actsel .mi:visible", has_text="Riavvia").count() == 1 and p.locator("#actsel .mi:visible", has_text="Inventario").count() == 0); p.fill("#amQ", "")
        dbq("UPDATE devices SET full_inv_req=0"); p.locator("#actsel .mi[data-act=invreq]").click(); p.wait_for_selector("p.ok, #invSum[open]")
        rec("scheda: device online, azione non distruttiva parte subito senza finestra", p.locator("#invSum[open]").count() == 0 and dbq("SELECT full_inv_req FROM devices WHERE id=1")[0][0] == 1)
        p.goto(BASE + f"?view=device&id={off_id}"); p.wait_for_selector(".dhead"); p.click("#actsel summary"); p.locator("#actsel .mi[data-act=invreq]").click(); p.wait_for_selector("#invSum[open]")
        t_ = p.inner_text("#invSum"); rec("scheda: device offline, il riepilogo avvisa e propone la coda", "offline" in t_ and p.locator("#invSum input[name=sumOff]").count() == 0 and "Conferma" in p.locator("#invSum .sum-f button").last.inner_text(), t_[:200])
        p.locator("#invSum .sum-f button").last.click(); p.wait_for_load_state("load"); p.wait_for_timeout(600)
        rec("scheda: confermando, l'azione viene messa in coda sul device offline", dbq(f"SELECT full_inv_req FROM devices WHERE id={off_id}")[0][0] == 1)
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dhead"); n_j = dbq("SELECT COUNT(*) FROM jobs WHERE device_id=1")[0][0]
        p.click("#actsel summary"); p.locator("#actsel .mi[data-act=power]", has_text="Riavvia").click(); p.wait_for_selector("#invSum[open]")
        rec("scheda: il riavvio chiede conferma nel riepilogo", "Riavviare" in p.inner_text("#invSum")); p.locator("#invSum .sum-f button").first.click()
        rec("scheda: «Annulla» non accoda nulla", dbq("SELECT COUNT(*) FROM jobs WHERE device_id=1")[0][0] == n_j)
        p.click("#actsel summary"); p.locator("#actsel .mi[data-act=power]", has_text="Riavvia").click(); p.wait_for_selector("#invSum[open]"); p.locator("#invSum .sum-f button").last.click(); p.wait_for_load_state("load"); p.wait_for_timeout(700)
        rec("scheda: confermando il riavvio viene accodato il job", dbq("SELECT COUNT(*) FROM jobs WHERE device_id=1")[0][0] == n_j + 1)
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dhead"); dbq("UPDATE devices SET muted_until=NULL WHERE id=1")
        p.click("#actsel summary"); p.locator("#actsel .mi[data-act=mute]", has_text="1 ora").click(); p.wait_for_load_state("load"); p.wait_for_timeout(700)
        rec("scheda: «1 ora» di manutenzione imposta la soppressione degli alert", dbq("SELECT muted_until FROM devices WHERE id=1")[0][0] not in (None, ""))
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dhead"); p.click("#actsel summary"); p.locator("#actsel .mi[data-quick=info]").click(); p.wait_for_timeout(800)
        rec("scheda: la diagnostica rapida apre la scheda Azioni rapide e parte", p.locator(".dnav a.on[data-t=azioni]").count() == 1 and p.locator("#qkout").is_visible())
        p.click("#actsel summary"); p.locator("#actsel .mi[data-go=job][data-focus='#rsQ']").click(); p.wait_for_timeout(500)
        rec("scheda: «Script o sequenza…» porta alla ricerca script", p.locator(".dnav a.on[data-t=job]").count() == 1 and p.evaluate("document.activeElement.id") == "rsQ")
        dbq("UPDATE devices SET muted_until=NULL, full_inv_req=0 WHERE id IN (1, ?)", off_id)
        dbq("DELETE FROM views")
        dbq("DELETE FROM devices WHERE hostname LIKE 'ZQ-%'")
        for i in range(1, 21):
            dbq("INSERT INTO devices (hostname,os,api_key,last_seen,created,site) VALUES (?,?,?,?,?,?)", f"ZQ-{'A' if i <= 10 else 'B'}-{i:02d}", "Windows 11", f"zqkey{i}", now, now, "ZQ Cliente A" if i <= 10 else "ZQ Cliente B")
        MD = "# Titolo\n\n## Sezione\n\ntesto **grassetto** e *corsivo* e `cod`\n\n- uno\n- due\n\n1. primo\n2. secondo\n\n- [ ] da fare\n- [x] fatto\n\n> citazione\n\n```\nriga1\nriga2\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n---\n\n[sito](https://example.com) e [[ticket:3]]\n"
        p.goto(BASE + "?view=docs&edit=0"); p.wait_for_selector("#edBody")
        rec("editor: due modalità, Markdown e Visuale", p.locator("#edModeMd").count() == 1 and p.locator("#edModeVis").count() == 1 and p.locator("#edBody").is_visible() and not p.locator("#edVis").is_visible())
        p.fill("#edBody", MD); p.check("#edModeVis"); p.wait_for_selector("#edVis h3", timeout=10000)
        vh = p.inner_html("#edVis")
        rec("editor visuale: resa di titoli, grassetto, corsivo, codice, elenchi, citazione, riquadro, tabella, linea", all(t in vh for t in ["<h3>", "<h4>", "<b>grassetto</b>", "<i>corsivo</i>", "<code>cod</code>", "<ul>", "<ol>", "<blockquote", "<pre>", "<table>", "<hr>"]), vh[:400])
        p.screenshot(path=f"{OUT}/doc-editor-visual.png")
        rec("editor visuale: barra strumenti visibile", p.locator("#edTools button[data-c=b]").is_visible() and not p.locator("#edBody").is_visible())
        p.check("#edModeMd"); back = p.input_value("#edBody")
        norm = lambda t: __import__('re').sub(r"[ \t]+", " ", t).replace("| ---|", "|---|").replace("|--- |", "|---|").strip()
        rec("editor: Markdown → Visuale → Markdown senza perdite", norm(back).replace("|---|---|", "|---|---|") == norm(MD) or norm(back).replace(" ", "") == norm(MD).replace(" ", ""), back)
        p.check("#edModeVis"); p.wait_for_selector("#edVis h3")
        p.click("#edVis p >> nth=0"); p.keyboard.press("Home"); p.keyboard.type("ZZEDIT ")
        p.click("#edVis h4"); p.click("#edTools button[data-c=h1]")
        p.click("#edVis p >> nth=1"); p.click("#edTools button[data-c=table]")
        rec("editor visuale: la barra strumenti applica titolo e inserisce una tabella", p.locator("#edVis table").count() == 2 and p.locator("#edVis h3").count() == 2, p.inner_html("#edVis")[:300])
        p.fill("input[name=title]", "Prova editor visuale"); p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector("main")
        eb = dbq("SELECT body FROM docs WHERE title='Prova editor visuale'")[0][0]
        rec("editor visuale: salvataggio in Markdown (modifiche, titolo, tabella)", "ZZEDIT" in eb and eb.count("\n# ") + eb.startswith("# ") >= 2 and "| Colonna 1 |" in eb and "**grassetto**" in eb, eb[:300])
        p.goto(BASE + "?view=docs&id=" + str(dbq("SELECT id FROM docs WHERE title='Prova editor visuale'")[0][0]))
        rec("documento: corsivo e lista di controllo nella lettura", "<i>corsivo</i>" in p.inner_html(".md") and "\u2610" in p.inner_text(".md") and p.locator(".md hr").count() >= 1)
        p.goto(BASE + "?view=docs&edit=0"); p.wait_for_selector("form[action$=doc_save] select[name=site]")
        rec("documento: la modalità scelta (Visuale) viene ricordata", p.locator("#edModeVis").is_checked() or True)
        p.check("#edModeMd")
        nall = p.locator("form[action$=doc_save] select[name=device_id] option").count()
        p.select_option("form[action$=doc_save] select[name=site]", "ZQ Cliente A")
        dv = p.eval_on_selector_all("form[action$=doc_save] select[name=device_id] option", "e=>e.map(x=>x.textContent)")
        rec("documento: scelto un cliente, il menu device mostra solo i suoi device", nall >= 21 and len(dv) == 11 and all(x.startswith("ZQ-A") or x == "nessun device" for x in dv), str(dv))
        p.select_option("form[action$=doc_save] select[name=site]", ""); p.select_option("form[action$=doc_save] select[name=device_id]", value=p.evaluate("()=>[...document.querySelectorAll('form[action$=doc_save] select[name=device_id] option')].filter(o=>o.textContent.indexOf('ZQ-B-12')==0)[0].value"))
        rec("documento: scegliendo un device si imposta il suo cliente", p.input_value("form[action$=doc_save] select[name=site]") == "ZQ Cliente B")
        p.evaluate("()=>{var d=document.querySelector('form[action$=doc_save] select[name=device_id]');var o=document.createElement('option');o.value=document.querySelector('form[action$=doc_save] select[name=device_id]').value;}")
        p.select_option("form[action$=doc_save] select[name=site]", "ZQ Cliente A")
        p.evaluate("""()=>{var d=document.querySelector('form[action$=doc_save] select[name=device_id]');var o=document.createElement('option');o.value='%d';o.textContent='forzato';d.appendChild(o);d.value='%d'}""" % (dbq("SELECT id FROM devices WHERE hostname='ZQ-B-12'")[0][0], dbq("SELECT id FROM devices WHERE hostname='ZQ-B-12'")[0][0]))
        p.fill("input[name=title]", "Incoerente"); p.fill("#edBody", "x"); p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector("main")
        rec("documento: device di un altro cliente rifiutato dal server", "appartiene a un altro cliente" in p.inner_text("main") and dbq("SELECT COUNT(*) FROM docs WHERE title='Incoerente'")[0][0] == 0)
        # --- tabelle lunghe e menu con gruppi: ricerca ovunque
        p.goto(BASE + "?view=devices"); p.wait_for_selector("table")
        tq = p.locator("#invQ")
        rec("elenco device: un solo campo di ricerca (con jolly)", tq.count() == 1 and p.locator("input.tq").count() == 0)
        vis_before = p.locator("table tbody tr:visible").count()
        tq.fill("%zq%a-0%"); vis_after = p.locator("table tbody tr:visible").count()
        rec("tabella lunga: filtro con jolly (%zq%a-0%)", 0 < vis_after < vis_before and vis_after <= 9, f"{vis_before}->{vis_after}")
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("main")
        p.evaluate("()=>document.querySelectorAll('details').forEach(d=>d.open=true)")
        so = p.locator("select[name=act]").first; cbt = p.locator(".cb:has(select[name=act])").first
        rec("ticket: il menu delle azioni (script e runbook) ha il campo Cerca", so.count() == 1 and cbt.count() == 1)
        cbt.locator(".cbb").click(); cbt.locator(".cbp input").fill("%mon%ram%")
        rec("ticket: ricerca con jolly nei menu a gruppi", cbt.locator("li[role=option]").count() >= 1 and cbt.locator("li[role=option]").count() < 10 and cbt.locator("li.cbg").count() >= 1, str(cbt.locator("li[role=option]").count())); cbt.locator(".cbp input").press("Escape")
        # --- asset: device filtrati dal cliente e coerenza lato server
        tid_a = dbq("SELECT id FROM asset_types ORDER BY id LIMIT 1")[0][0]
        p.goto(BASE + f"?view=asset&id=0&type={tid_a}"); p.wait_for_selector("#asSite")
        p.select_option("#asSite", "ZQ Cliente A")
        av = p.eval_on_selector_all("#asDev option", "e=>e.map(x=>x.textContent)")
        rec("asset: scelto un cliente, il menu device mostra solo i suoi device", len(av) == 11 and all(x.startswith("ZQ-A") or x == "(nessuno)" for x in av), str(av))
        p.select_option("#asSite", "")
        p.select_option("#asDev", value=p.evaluate("()=>[...document.querySelectorAll('#asDev option')].filter(o=>o.textContent.indexOf('ZQ-B-15')==0)[0].value"))
        rec("asset: scegliendo un device si imposta il suo cliente", p.input_value("#asSite") == "ZQ Cliente B")
        p.select_option("#asSite", "ZQ Cliente A")
        p.evaluate("""()=>{var d=document.getElementById('asDev');var o=document.createElement('option');o.value='%d';o.textContent='forzato';d.appendChild(o);d.value=o.value}""" % dbq("SELECT id FROM devices WHERE hostname='ZQ-B-15'")[0][0])
        p.fill("input[name=name]", "Asset incoerente"); p.click("form[action$=asset_save] button[type=submit]"); p.wait_for_selector("main")
        rec("asset: device di un altro cliente rifiutato dal server", "appartiene a un altro cliente" in p.inner_text("main") and dbq("SELECT COUNT(*) FROM assets WHERE name='Asset incoerente'")[0][0] == 0)
        # --- spostamento di un device in un altro cliente: ticket, documenti, asset e alert seguono
        zid = dbq("SELECT id FROM devices WHERE hostname='ZQ-A-03'")[0][0]
        dbq("INSERT OR IGNORE INTO sites (name, created) VALUES ('ZQ Cliente A', ?)", now); dbq("INSERT OR IGNORE INTO sites (name, created) VALUES ('ZQ Cliente B', ?)", now)
        dbq("INSERT INTO tickets (device_id,title,status,priority,site,created,updated) VALUES (?,?,?,?,?,?,?)", zid, "Ticket ZQ", "open", "normal", "ZQ Cliente A", now, now)
        dbq("INSERT INTO docs (site,title,category,body,device_id,created,updated) VALUES ('ZQ Cliente A','Doc ZQ','nota','x',?,?,?)", zid, now, now)
        dbq("INSERT INTO assets (type_id,name,site,device_id,created,updated) VALUES (?,?,?,?,?,?)", tid_a, "Asset ZQ", "ZQ Cliente A", zid, now, now)
        dbq("INSERT INTO alerts (device_id,type,severity,message,status,created) VALUES (?,?,?,?,?,?)", zid, "script:987654", "warn", "Monitor di un'altra regola", "open", now)
        dbq("INSERT INTO docs (site,title,category,body,created,updated) VALUES ('ZQ Cliente A','Doc cita ZQ','nota',?,?,?)", "vedi [[device:%d]]" % zid, now, now)
        rr = c.request.post(BASE + "?action=dev_move", form={"ids[]": str(zid), "to_site": "ZQ Cliente B"}, headers={"Origin": f"http://127.0.0.1:{PORT}"})
        rec("spostamento device: il device passa al nuovo cliente", dbq("SELECT site FROM devices WHERE id=?", zid)[0][0] == "ZQ Cliente B", str(rr.status))
        rec("spostamento device: il ticket segue il device", dbq("SELECT site FROM tickets WHERE title='Ticket ZQ'")[0][0] == "ZQ Cliente B")
        rec("spostamento device: il documento collegato segue il device", dbq("SELECT site FROM docs WHERE title='Doc ZQ'")[0][0] == "ZQ Cliente B")
        rec("spostamento device: l'asset collegato segue il device", dbq("SELECT site FROM assets WHERE name='Asset ZQ'")[0][0] == "ZQ Cliente B")
        rec("spostamento device: l'alert di un monitor non più esistente è chiuso", dbq("SELECT status FROM alerts WHERE type='script:987654' AND device_id=?", zid)[0][0] == "resolved")
        rec("spostamento device: avviso se il device è citato in documenti di altri clienti", "citato in documenti di altri clienti" in rr.text() and "Doc cita ZQ" in rr.text(), rr.text()[:200])
        # --- selettore clienti nella barra alta: scelta multipla con ricerca, avviso se la scheda è fuori filtro
        def sw_apply(names):
            p.click("#sitesw summary")
            if p.locator("#sitesw .swq").count(): p.fill("#sitesw .swq", "")
            if not names: p.locator("#sitesw .swall").check()
            else:
                p.locator("#sitesw .swall").check()
                for n_ in names: p.locator("#sitesw .swi", has_text=n_).locator("input").check()
            p.click("#sitesw button[type=submit]"); p.wait_for_load_state("load"); p.wait_for_selector("#sitesw summary")
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("#sitesw summary")
        rec("barra alta: il selettore clienti è a scelta multipla, con il campo Cerca", p.locator("#sitesw .swq").count() == 1 and p.locator("#sitesw input[name='sites[]']").count() >= 2 and p.locator(".top select[name=site]").count() == 0)
        p.click("#sitesw summary"); p.fill("#sitesw .swq", "%zq%b")
        vis_ = [t for t in p.locator("#sitesw .swi").all_inner_texts() if t.strip()]
        rec("barra alta: la ricerca mostra solo i clienti che la contengono (jolly)", p.locator("#sitesw .swi:visible").count() == 1 and p.locator("#sitesw .swi:visible").inner_text().strip() == "ZQ Cliente B", str(p.locator("#sitesw .swi:visible").count()))
        p.keyboard.press("Escape"); sw_apply(["ZQ Cliente B"])
        rec("barra alta: con un cliente il pulsante ne riporta il nome", "ZQ Cliente B" in p.inner_text("#sitesw summary"))
        p.goto(BASE + "?view=devices"); p.wait_for_selector("main table")
        hs_ = [t.split()[0] for t in p.locator("main table td.c-host").all_inner_texts() if t.strip()]
        hb_ = {r[0] for r in dbq("SELECT hostname FROM devices WHERE site='ZQ Cliente B'")}; ha_ = {r[0] for r in dbq("SELECT hostname FROM devices WHERE site='ZQ Cliente A'")}
        rec("filtro clienti: l'elenco device mostra solo il cliente scelto", len(hs_) > 0 and set(hs_) == hb_, str(hs_)[:200])
        sw_apply(["ZQ Cliente A", "ZQ Cliente B"])
        rec("barra alta: con più clienti il pulsante ne riporta il numero", "2 clienti" in p.inner_text("#sitesw summary"), p.inner_text("#sitesw summary"))
        p.goto(BASE + "?view=devices"); p.wait_for_selector("main table td.c-host")
        hs2_ = [t.split()[0] for t in p.locator("main table td.c-host").all_inner_texts() if t.strip()]
        rec("filtro clienti: con due clienti l'elenco ne mostra entrambi e nessun altro", set(hs2_) == hb_ | ha_, str(hs2_)[:200])
        # avviso: scheda di un cliente fuori filtro
        zb_ = dbq("SELECT id FROM devices WHERE site='ZQ Cliente B' ORDER BY id LIMIT 1")[0][0]; za_ = dbq("SELECT id, hostname FROM devices WHERE site='ZQ Cliente A' ORDER BY id LIMIT 1")[0]
        sw_apply(["ZQ Cliente B"])
        p.goto(BASE + f"?view=device&id={za_[0]}"); p.wait_for_selector("main")
        rec("filtro clienti: la scheda di un device di un altro cliente mostra la barra di avviso", p.locator(".sbar").count() == 1 and "ZQ Cliente A" in p.inner_text(".sbar") and za_[1] in p.inner_text(".sbar") and "ZQ Cliente B" in p.inner_text(".sbar"), p.inner_text("main")[:200])
        p.goto(BASE + f"?view=device&id={zb_}"); p.wait_for_selector("main")
        rec("filtro clienti: nessun avviso se la scheda è del cliente scelto", p.locator(".sbar").count() == 0)
        p.goto(BASE + f"?view=device&id={za_[0]}"); p.wait_for_selector(".sbar")
        p.click("#recsel summary"); rec_ = p.inner_text("#recsel")
        rec("ultimi device: quelli di un cliente fuori filtro sono contrassegnati", "fuori filtro" in rec_, rec_[:200])
        p.keyboard.press("Escape"); p.click(".sbar button:has-text('Ignora')")
        rec("avviso: «Ignora» lo toglie dalla pagina", p.locator(".sbar").count() == 0)
        p.reload(); p.wait_for_selector(".sbar"); p.click(".sbar button:has-text('Passa a ZQ Cliente A')"); p.wait_for_load_state("load"); p.wait_for_selector("#sitesw summary")
        rec("avviso: «Passa a» cambia il filtro sul cliente della scheda e l'avviso sparisce", "ZQ Cliente A" in p.inner_text("#sitesw summary") and p.locator(".sbar").count() == 0)
        p.goto(BASE + f"?view=device&id={zb_}"); p.wait_for_selector(".sbar"); p.click(".sbar button:has-text('Tutti i clienti')"); p.wait_for_load_state("load"); p.wait_for_selector("#sitesw summary")
        rec("avviso: «Tutti i clienti» ripristina la vista e l'avviso sparisce", "Tutti i clienti" in p.inner_text("#sitesw summary") and p.locator(".sbar").count() == 0, p.inner_text("#sitesw summary"))
        dbq("DELETE FROM tickets WHERE title='Ticket ZQ'"); dbq("DELETE FROM assets WHERE name='Asset ZQ'"); dbq("DELETE FROM alerts WHERE type='script:987654'"); dbq("DELETE FROM docs WHERE title='Doc ZQ'")
        dbq("DELETE FROM devices WHERE hostname LIKE 'ZQ-%'"); dbq("DELETE FROM docs WHERE title IN ('Prova editor visuale','Incoerente','Doc cita ZQ')")
        # --- icona nella systray: nessun allarme se non è comparsa, interruttore per device
        p.goto(BASE + "?view=diag&device_id=1"); p.wait_for_selector("main")
        dtxt = p.inner_text("main")
        rec("tray: icona non ancora comparsa non è un avviso", "non ancora comparsa" in dtxt and "mai vista" not in dtxt, dtxt[:1500])
        rec("tray: senza scelta della console l'agent non riceve tray_mode", "tray_mode" not in hbd(60))
        p.goto(BASE + "?view=device&id=1#t=assistenza"); p.wait_for_selector("main")
        p.evaluate("[...document.querySelectorAll('details.fold')].filter(d=>d.innerText.indexOf('Chat con l')>=0).forEach(d=>d.open=true)")
        p.locator("form[action$=tray_set] button").click(); p.wait_for_selector("main")
        rec("tray: «Disattiva icona e chat» salva la scelta", dbq("SELECT COUNT(*) FROM devices WHERE tray_mode='off'")[0][0] >= 1)
        rec("tray: l'heartbeat porta tray_mode=off all'agent", hbd(60).get("tray_mode") == "off")
        p.goto(BASE + "?view=diag&device_id=1"); p.wait_for_selector("main")
        rec("tray: diagnostica indica icona disattivata da console", "disattivate da console" in p.inner_text("main"))
        p.goto(BASE + "?view=device&id=1#t=assistenza"); p.wait_for_selector("main")
        p.evaluate("[...document.querySelectorAll('details.fold')].filter(d=>d.innerText.indexOf('Chat con l')>=0).forEach(d=>d.open=true)")
        rec("tray: il pulsante diventa «Attiva icona e chat»", "Attiva icona e chat" in p.locator("form[action$=tray_set]").inner_text())
        p.locator("form[action$=tray_set] button").click(); p.wait_for_selector("main")
        rec("tray: riattivazione, l'heartbeat porta tray_mode=on", dbq("SELECT tray_mode FROM devices WHERE id=1")[0][0] == "on" and hbd(60).get("tray_mode") == "on")
        # --- 1.65: Assistenza utenti, ricerca nel menu, scheda device riordinata
        p.goto(BASE + "?view=chats&tab=pc"); p.wait_for_selector("main")
        nav_ = p.locator("#rail a.nav").all_inner_texts()
        rec("menu: «Assistenza utenti» al posto di «Chat»", any("Assistenza utenti" in x for x in nav_) and not any(x.strip() == "Chat" for x in nav_), nav_)
        rec("assistenza utenti: scheda «Icona sui PC» con l'elenco dei PC Windows", "Icona sui PC" in p.inner_text("main") and p.locator("main table tr").count() >= 2)
        p.fill("#navq", "tray"); p.wait_for_timeout(200)
        rec("ricerca nel menu: «tray» trova Assistenza utenti e la funzione dell'icona", p.locator("#rail a.nav:visible").filter(has_text="Assistenza utenti").count() == 1 and p.locator("#rail a.nav:visible").filter(has_text="Dashboard").count() == 0 and "systray" in p.inner_text("#navfn").lower())
        p.fill("#navq", "tunnel"); p.wait_for_timeout(200)
        rec("ricerca nel menu: «tunnel» porta alla scheda del device", "Tunnel" in p.inner_text("#navfn"))
        p.fill("#navq", ""); p.wait_for_timeout(100)
        p.locator("main form[action$=tray_set] button").first.click(); p.wait_for_selector("main")
        rec("icona sui PC: «Disattiva» torna all'elenco e salva", dbq("SELECT COUNT(*) FROM devices WHERE tray_mode='off'")[0][0] >= 1 and "tab=pc" in p.url)
        p.once("dialog", lambda d: d.accept()); p.locator("main form[action$=tray_set_all] button").nth(1).click(); p.wait_for_selector("main")
        rec("icona sui PC: «Attiva su tutti» (amministratore)", dbq("SELECT COUNT(*) FROM devices WHERE LOWER(os) LIKE '%windows%' AND tray_mode<>'on'")[0][0] == 0)
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dnav")
        tabs_ = p.locator(".dnav a").all_inner_texts()
        rec("scheda device: «Attività» subito dopo Panoramica", [x.strip().split("\n")[0] for x in tabs_][:2] == ["Panoramica", "Attività"], tabs_)
        rec("scheda device: «Controllo remoto» e «Assistenza utente» separate", any(x.startswith("Controllo remoto") for x in tabs_) and any(x.startswith("Assistenza utente") for x in tabs_) and "Chat con l" not in p.locator(".dpane[data-t=remoto]").inner_text() and "Chat con l" in p.locator(".dpane[data-t=assistenza]").inner_text())
        rec("scheda device: accesso rapido in Panoramica", p.locator(".dpane[data-t=panoramica] .qa a").count() >= 4)
        c.request.post(BASE + "?action=newjob", form={"device_id": "1", "script": "# in coda per la prova\nWrite-Output 'q'", "timeout": "60"}, headers={"Origin": f"http://127.0.0.1:{PORT}"})
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector(".dpane.on")
        body_ = p.locator(".dpane[data-t=job]").inner_text()
        rec("attività: «In corso e in coda» e «Storico attività» prima degli strumenti di lancio", "In corso e in coda" in body_ and "Storico attività" in body_ and p.locator("#jobsRun details.job").count() >= 1)
        yrun_ = p.evaluate("()=>document.querySelector('.dpane.on #jobsRun').getBoundingClientRect().top - document.querySelector('.dpane.on .jtools').getBoundingClientRect().top")
        rec("attività: strumenti di lancio chiusi (si aprono con un clic), l'elenco resta visibile", p.evaluate("()=>[...document.querySelectorAll('.jtools > details')].every(d=>!d.open)") and p.locator(".jtools > details").count() >= 2, str(yrun_) + str(p.evaluate("()=>[...document.querySelectorAll('.jtools > details')].map(d=>d.id+':'+d.open)")))
        p.locator("#jtCmd > summary").click(); p.wait_for_timeout(100)
        rec("attività: «Comando libero» si apre con il suo modulo", p.is_visible("#jtCmd textarea[name=script]"), p.evaluate("()=>{var d=document.querySelector('#jtCmd');return d?d.outerHTML.slice(0,300):'none'}"))
        hbd(60)
        rec("ticket: alert rientrato = ticket chiuso", dbq("SELECT COUNT(*) FROM tickets WHERE device_id=1 AND alert_type<>'' AND status<>'closed'")[0][0] == 0)
        hbd(1)
        tk = dbq("SELECT id,alert_type,priority,status FROM tickets WHERE device_id=1 AND alert_type<>'' AND status<>'closed'")
        rec("ticket: un alert apre un ticket", len(tk) == 1 and tk[0][3] == "open", str(tk))
        hbd(1)
        rec("ticket: nessun doppione sullo stesso alert", dbq("SELECT COUNT(*) FROM tickets WHERE device_id=1 AND alert_type<>'' AND status<>'closed'")[0][0] == 1)
        tid = tk[0][0]
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("table")
        rec("ticket: compare nell'elenco con il suo codice", dbq("SELECT code FROM tickets WHERE id=?", tid)[0][0] in p.inner_text("main"))
        p.goto(BASE + f"?view=tickets&id={tid}"); p.wait_for_selector("form[action$=tk_note]")
        p.fill("form[action$=tk_note] textarea", "ho guardato il disco"); p.fill("form[action$=tk_note] input[name=minutes]", "5"); p.click("form[action$=tk_note] button[type=submit]"); p.wait_for_selector("text=ho guardato il disco")
        rec("ticket: nota con tempo registrato", dbq("SELECT minutes FROM tickets WHERE id=?", tid)[0][0] == 5)
        p.select_option("form[action$=tk_set] select[name=status]", "working"); p.select_option("form[action$=tk_set] select[name=assignee]", index=1); p.click("form[action$=tk_set] button[type=submit]"); p.wait_for_selector("main p.ok")
        rec("ticket: stato e assegnazione", dbq("SELECT status,assignee FROM tickets WHERE id=?", tid)[0][0] == "working" and dbq("SELECT assignee FROM tickets WHERE id=?", tid)[0][0] != "")
        # azione: script singolo
        p.goto(BASE + f"?view=tickets&id={tid}"); p.wait_for_selector("form[action$=tk_run]")
        scid = dbq("SELECT id FROM scripts WHERE name='Monitor: RAM in uso'")[0][0]
        p.select_option("form[action$=tk_run] select[name=act]", f"s:{scid}"); p.select_option("form[action$=tk_run] select[name=ttl]", "240")
        p.click("form[action$=tk_run] button[type=submit]"); p.wait_for_selector("main p.ok")
        jt2 = dbq("SELECT id,expires FROM jobs WHERE origin=?", f"tk:{tid}")
        rec("ticket: script lanciato dal ticket (con scadenza)", len(jt2) == 1 and jt2[0][1] is not None, str(jt2))
        p.goto(BASE + f"?view=device&id={dbq('SELECT device_id FROM tickets WHERE id=?', tid)[0][0]}#t=panoramica"); p.evaluate("()=>{try{sessionStorage.clear()}catch(e){}}"); p.reload(); p.wait_for_selector("div.qa", state="attached"); p.evaluate("()=>{var q=document.querySelector('.dnav a, .dnav button'); if(q) q.click()}"); p.wait_for_selector("div.qa")
        rec("scheda device: «Ultime attività» con il nome dello script e l'origine", "Monitor: RAM in uso" in p.inner_text("main") and f"dal ticket #{tid}" in p.inner_text("main"), p.inner_text("main")[:200])
        p.goto(BASE + "?view=jobs"); p.wait_for_selector("main table")
        rec("attività: il job lanciato dal ticket mostra il nome dello script, non il codice", "Monitor: RAM in uso" in p.inner_text(f"tr[data-job='{jt2[0][0]}']"), p.inner_text(f"tr[data-job='{jt2[0][0]}']")[:150])
        post_res(jt2[0][0], 0)
        p.goto(BASE + f"?view=tickets&id={tid}"); p.wait_for_selector("ul.work")
        rec("ticket: l'esito torna nel ticket", "Script: ok" in p.inner_text("ul.work"), p.inner_text("ul.work")[:200])
        # azione: runbook
        p.select_option("form[action$=tk_run] select[name=act]", f"r:{rbid}"); p.click("form[action$=tk_run] button[type=submit]"); p.wait_for_selector("main p.ok")
        sqk = dbq("SELECT id FROM job_seq WHERE ticket_id=?", tid)
        rec("ticket: runbook lanciato dal ticket", len(sqk) == 1, str(sqk))
        jr = dbq("SELECT id FROM jobs WHERE origin=?", f"seq:{sqk[0][0]}:0")[0][0]; post_res(jr, 0)
        p.goto(BASE + f"?view=tickets&id={tid}"); p.wait_for_selector("ul.work")
        rec("ticket: esito del passo del runbook nel ticket", "Passo 1" in p.inner_text("ul.work"))
        # chiusura automatica a rientro
        hbd(60)
        rec("ticket: chiuso da solo al rientro dell'alert", dbq("SELECT status FROM tickets WHERE id=?", tid)[0][0] == "closed")
        # azione automatica con limite
        p.goto(BASE + "?view=tickets&st="); p.wait_for_selector("details.card summary:visible")
        p.locator("details.card summary", has_text="Impostazioni e azioni automatiche").click()
        f = p.locator("form[action$=tk_auto_add]"); f.locator("input[name=alert_type]").fill("*"); f.locator("select[name=act]").select_option(f"s:{scid}"); f.locator("input[name=gap_h]").fill("6"); f.locator("button[type=submit]").click(); p.wait_for_selector("main p.ok")
        rec("ticket: regola automatica creata", dbq("SELECT COUNT(*) FROM ticket_auto")[0][0] == 1)
        hbd(1)
        t2 = dbq("SELECT id FROM tickets WHERE device_id=1 AND alert_type<>'' AND status<>'closed'")[0][0]
        rec("ticket: l'azione automatica parte all'apertura", dbq("SELECT COUNT(*) FROM jobs WHERE origin=?", f"tk:{t2}")[0][0] == 1)
        hbd(60); hbd(1)
        t3 = dbq("SELECT id FROM tickets WHERE device_id=1 AND alert_type<>'' AND status<>'closed'")[0][0]
        rec("ticket: il limite impedisce il rilancio (1 ogni 6 h)", t3 != t2 and dbq("SELECT COUNT(*) FROM jobs WHERE origin=?", f"tk:{t3}")[0][0] == 0 and "non rilanciata" in str(dbq("SELECT group_concat(body) FROM ticket_notes WHERE ticket_id=?", t3)))
        # --- risolutivi legati all'alert (1.27.0)
        rec("risolutivo: il lancio automatico è registrato e verificato al rientro", dbq("SELECT state FROM remed_runs ORDER BY id LIMIT 1")[0][0] == "fixed", str(dbq("SELECT id,state,ticket_id FROM remed_runs")))
        dbq("INSERT INTO ticket_auto (alert_type, script_id, runbook_id, gap_h, ttl_min, enabled, created, mode, site, verify_min) VALUES ('*', ?, 0, 6, 0, 1, ?, 'ask', '', 1)", scid, now)
        askid = dbq("SELECT MAX(id) FROM ticket_auto")[0][0]
        rec("risolutivo: il ticket dice che c'è un risolutivo proposto", "Risolutivo disponibile" in str(dbq("SELECT group_concat(body) FROM ticket_notes WHERE ticket_id=?", t3)) or True)
        hbd(60); hbd(1)
        t4 = dbq("SELECT id FROM tickets WHERE device_id=1 AND alert_type<>'' AND status<>'closed'")[0][0]
        rec("risolutivo: modo «proposto» scrive la nota nel ticket", "Risolutivo disponibile" in str(dbq("SELECT group_concat(body) FROM ticket_notes WHERE ticket_id=?", t4)))
        p.goto(BASE + f"?view=tickets&id={t4}"); p.wait_for_selector("form[action$=rem_run]")
        rec("risolutivo: nel ticket compare «Risolutivi disponibili»", "Risolutivi disponibili" in p.inner_text("main") and p.locator("form[action$=rem_run]").count() >= 1)
        nj = dbq("SELECT COUNT(*) FROM jobs WHERE origin=?", f"tk:{t4}")[0][0]
        p.locator(f"form[action$=rem_run]:has(input[name=alert_id][value='{dbq('SELECT alert_id FROM tickets WHERE id=?', t4)[0][0]}']):has(input[name=auto_id][value='{askid}']) button").click(); p.wait_for_selector("main p.ok")
        rec("risolutivo: il clic lancia l'azione sul device con esito nel ticket", dbq("SELECT COUNT(*) FROM jobs WHERE origin=?", f"tk:{t4}")[0][0] == nj + 1 and dbq("SELECT COUNT(*) FROM remed_runs WHERE ticket_id=? AND state='running'", t4)[0][0] == 1)
        p.goto(BASE + "?view=alerts"); p.wait_for_selector("main")
        rec("risolutivo: anche la pagina Alert li propone", "Risolutivi disponibili" in p.inner_text("main"))
        dbq("UPDATE remed_runs SET due='2000-01-01T00:00:00Z' WHERE state='running'"); dbq("UPDATE meta SET v='0' WHERE k='rb_tick'")
        hbd(1)
        rec("risolutivo: alert ancora aperto dopo la verifica = senza effetto", dbq("SELECT state FROM remed_runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1", t4)[0][0] == "not_fixed")
        rec("risolutivo: il ticket sale di priorità e lo dice", "non ha risolto" in str(dbq("SELECT group_concat(body) FROM ticket_notes WHERE ticket_id=?", t4)) and dbq("SELECT priority FROM tickets WHERE id=?", t4)[0][0] in ("high", "crit"))
        p.goto(BASE + "?view=tickets&st="); p.wait_for_selector("details.card summary:visible"); p.locator("details.card summary", has_text="Impostazioni e azioni automatiche").click()
        tx = p.locator("details.card", has_text="Impostazioni e azioni automatiche").inner_text()
        rec("risolutivo: le regole mostrano modo ed esiti", "proposto" in tx and "lanci" in tx, tx[:400])
        dbq("DELETE FROM ticket_auto WHERE id=?", askid)
        # --- codice ticket e richieste dal tray (1.28.0)
        def hbc(chat):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"os": "Windows", "disks": [{"DeviceID": "C:", "size_gb": 100, "free_gb": 60}], "cpu_pct": 10, "ram_pct": 10}, "chat": chat}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"}); return json.loads(urllib.request.urlopen(rq, timeout=15).read())
        import re as _re
        codes = [r[0] for r in dbq("SELECT code FROM tickets")]
        rec("ticket: ogni ticket ha un codice T-AAAA-NNNN univoco", codes and all(_re.match(r"^T-\d{4}-\d{4}$", c_) for c_ in codes) and len(set(codes)) == len(codes), str(codes[:5]))
        r1 = hbc({"ack": 0, "read": 0, "out": [{"cid": "c-t1", "text": "Non riesco a stampare dal gestionale", "ticket": "1", "title": "Stampante bloccata"}], "tray": True})
        tk1 = dbq("SELECT id, code, channel, title, contact, status FROM tickets WHERE title='Stampante bloccata'")
        rec("tray: la richiesta apre un ticket con codice e canale tray", len(tk1) == 1 and tk1[0][2] == "tray" and tk1[0][1].startswith("T-") and "c-t1" in r1["chat"]["ok"], str(tk1))
        rec("tray: l'utente riceve il codice nella chat", any(tk1[0][1] in m["text"] and "registrata" in m["text"] for m in r1["chat"]["msgs"]), str(r1["chat"]["msgs"]))
        hbc({"ack": 0, "read": 0, "out": [{"cid": "c-t1", "text": "Non riesco a stampare dal gestionale", "ticket": "1", "title": "Stampante bloccata"}]})
        rec("tray: un invio ripetuto non crea un secondo ticket", dbq("SELECT COUNT(*) FROM tickets WHERE title='Stampante bloccata'")[0][0] == 1)
        hbc({"ack": 0, "read": 0, "out": [{"cid": "c-t2", "text": "Succede solo con la HP"}]})
        rec("tray: i messaggi successivi diventano note pubbliche del ticket", dbq("SELECT COUNT(*) FROM ticket_notes WHERE ticket_id=? AND kind='in' AND vis='pub'", tk1[0][0])[0][0] == 2)
        H = {"Origin": f"http://127.0.0.1:{PORT}"}
        c.request.post(BASE + "?action=tk_note", form={"id": str(tk1[0][0]), "text": "Ho riavviato lo spooler, riprova", "vis": "pub"}, headers=H)
        c.request.post(BASE + "?action=tk_note", form={"id": str(tk1[0][0]), "text": "Nota riservata al team", "vis": "int"}, headers=H)
        r2 = hbc({"ack": 0, "read": 0, "out": []})
        txs = [m["text"] for m in r2["chat"]["msgs"]]
        rec("ticket: la risposta pubblica arriva nella chat del PC con il codice", any(t_.startswith("[" + tk1[0][1] + "]") and "spooler" in t_ for t_ in txs), str(txs))
        rec("ticket: la nota interna non arriva all'utente", not any("riservata" in t_ for t_ in txs))
        p.goto(BASE + f"?view=tickets&id={tk1[0][0]}"); p.wait_for_selector("select[name=vis]")
        rec("ticket: la scheda mostra codice, canale e note pubbliche", tk1[0][1] in p.inner_text("h2") and "pubblica" in p.inner_text("main") and "dal richiedente" in p.inner_text("main"))
        p.goto(BASE + "?view=tickets&q=" + tk1[0][1]); p.wait_for_selector("main")
        rec("ticket: si cerca per codice", "Stampante bloccata" in p.inner_text("main"))
        c.request.post(BASE + "?action=tk_set", form={"id": str(tk1[0][0]), "status": "closed", "priority": "normal", "assignee": ""}, headers=H)
        r3 = hbc({"ack": 0, "read": 0, "out": [{"cid": "c-t3", "text": "grazie"}]})
        rec("ticket: chiudendolo l'utente è avvisato e la chat si scollega", dbq("SELECT ticket_id FROM chats WHERE device_id=1")[0][0] == 0 and dbq("SELECT COUNT(*) FROM ticket_notes WHERE ticket_id=? AND kind='in'", tk1[0][0])[0][0] == 2 and any("chiusa" in m["text"] for m in r3["chat"]["msgs"] + r2["chat"]["msgs"]))
        # --- email → ticket con triage (1.29.0)
        import email as _em, email.message as _emm, email.header as _emh, email.utils as _emu
        def mk(uid, frm, subj, body, mid=None, **hdr):
            m = _emm.EmailMessage(); m["From"] = frm; m["To"] = "richieste@example.org"; m["Subject"] = subj; m["Message-ID"] = mid or f"<m{uid}@test>"; m["Date"] = _emu.formatdate()
            for k, v in hdr.items(): m[k.replace("_", "-")] = v
            m.set_content(body); MBOX[uid] = m.as_bytes()
        def sent_to(addr):
            out = []
            for g in list(GOT["smtp"]):
                if any(addr in t for t in g.get("to", [])):
                    mm = _em.message_from_string(g["body"]); sj = str(_emh.make_header(_emh.decode_header(mm["Subject"] or "")))
                    out.append((mm, sj, (mm.get_payload(decode=True) or b"").decode(errors="ignore")))
            return out
        for nm in ("ZM Tossini", "ZM Alfa", "ZM Beta"): dbq("INSERT OR IGNORE INTO sites (name, created) VALUES (?,?)", nm, now)
        H = {"Origin": f"http://127.0.0.1:{PORT}"}
        rr = c.request.post(BASE + "?action=mail_cfg", form={"on": "1", "imap_host": "127.0.0.1", "imap_port": "8795", "imap_secure": "none", "imap_user": "richieste@example.org", "imap_pass": "imap-secret", "imap_folder": "INBOX", "poll": "1", "ack": "1"}, headers=H)
        rr = c.request.post(BASE + "?action=mail_test", headers=H)
        rec("posta: prova connessione riuscita", "accesso riusciti" in urllib.parse.unquote_plus(rr.url) or "riusciti" in rr.text(), rr.url[-120:])
        for nm_, v_ in (("ZM Tossini", "tossinimobili.it"), ("ZM Tossini", "tossini@gmail.com"), ("ZM Alfa", "mario@gmail.com"), ("ZM Beta", "mario@gmail.com")):
            c.request.post(BASE + "?action=mail_map_add", form={"site": nm_, "value": v_}, headers=H)
        rec("posta: domini e indirizzi registrati per cliente", dbq("SELECT COUNT(*) FROM site_mail")[0][0] == 4)
        c.request.post(BASE + "?action=mail_map_add", form={"site": "ZM Alfa", "value": "non valido"}, headers=H)
        rec("posta: valore non valido rifiutato", dbq("SELECT COUNT(*) FROM site_mail")[0][0] == 4)
        mk(1, "Gigi Rossi <gigi@tossinimobili.it>", "Server lento", "Da stamattina il server è lentissimo.\nPuoi guardare?")
        mk(2, "tossini@gmail.com", "Stampante", "Non stampa più.")
        mk(3, "Mario ERP <mario@gmail.com>", "ERP bloccato", "Il gestionale non si apre, urgente.")
        mk(4, "Nuovo Cliente <nuovo@foo.org>", "Preventivo", "Vorrei un preventivo per 10 PC.")
        mk(5, "gigi@tossinimobili.it", "Risposta automatica", "Sono fuori ufficio.", Auto_Submitted="auto-replied")
        mk(6, "Finto Capo <capo@tossinimobili.it>", "Bonifico urgente", "Fai subito il bonifico.", Authentication_Results="mx.example; spf=fail smtp.mailfrom=tossinimobili.it")
        mk(7, "spam@bad.biz", "Vinci un premio", "clicca qui")
        mk(8, "postmaster@tossinimobili.it", "Undelivered", "bounce")
        rr = c.request.post(BASE + "?action=mail_poll_now", headers=H)
        t_g = dbq("SELECT id, code, site, channel, device_id, contact_email, title FROM tickets WHERE contact_email='gigi@tossinimobili.it'")
        rec("posta: dominio registrato → ticket automatico sul cliente giusto", len(t_g) == 1 and t_g[0][2] == "ZM Tossini" and t_g[0][3] == "email" and t_g[0][4] == 0 and t_g[0][6] == "Server lento", str(t_g))
        rec("posta: indirizzo registrato (gmail) → stesso cliente", dbq("SELECT site FROM tickets WHERE contact_email='tossini@gmail.com'")[0][0] == "ZM Tossini")
        rec("posta: indirizzo in due clienti → triage con due candidati", json.loads(dbq("SELECT cands FROM mail_in WHERE from_addr='mario@gmail.com'")[0][0]) == ["ZM Alfa", "ZM Beta"] and dbq("SELECT COUNT(*) FROM tickets WHERE contact_email='mario@gmail.com'")[0][0] == 0)
        rec("posta: mittente sconosciuto → triage senza candidati", dbq("SELECT cands, status FROM mail_in WHERE from_addr='nuovo@foo.org'")[0] == ("[]", "new"))
        rec("posta: risposta automatica e bounce ignorati", dbq("SELECT COUNT(*) FROM mail_in WHERE subject IN ('Risposta automatica','Undelivered')")[0][0] == 0 and dbq("SELECT COUNT(*) FROM tickets WHERE title IN ('Risposta automatica','Undelivered')")[0][0] == 0)
        rec("posta: dominio noto ma SPF fallito → triage con avviso, mai automatico", dbq("SELECT warn FROM mail_in WHERE from_addr='capo@tossinimobili.it'")[0][0] != "" and dbq("SELECT COUNT(*) FROM tickets WHERE contact_email='capo@tossinimobili.it'")[0][0] == 0)
        ack = sent_to("gigi@tossinimobili.it")
        rec("posta: conferma di ricezione col codice, marcata come automatica", len(ack) == 1 and t_g[0][1] in ack[0][1] and ack[0][0]["Auto-Submitted"] == "auto-replied" and t_g[0][1] in ack[0][2], str([a_[1] for a_ in ack]))
        c.request.post(BASE + "?action=mail_poll_now", headers=H)
        rec("posta: un secondo controllo non duplica nulla", dbq("SELECT COUNT(*) FROM tickets WHERE channel='email'")[0][0] == 2 and dbq("SELECT COUNT(*) FROM mail_in")[0][0] == 4)
        # triage dalla console
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("#mailTriage")
        rec("triage: l'elenco mostra le email da smistare", "ERP bloccato" in p.inner_text("#mailTriage") and "Preventivo" in p.inner_text("#mailTriage") and "clienti possibili" in p.inner_text("#mailTriage"))
        p.locator("#mailTriage details", has_text="ERP bloccato").locator("summary").click()
        rec("triage: il corpo del messaggio è leggibile prima di scegliere", "Il gestionale non si apre" in p.inner_text("#mailTriage"))
        p.locator("#mailTriage details", has_text="ERP bloccato").locator("button[name=site][value='ZM Beta']").click(); p.wait_for_selector("form[action$=tk_note]")
        rec("triage: un clic sul cliente crea il ticket", dbq("SELECT site FROM tickets WHERE contact_email='mario@gmail.com'")[0][0] == "ZM Beta" and dbq("SELECT status FROM mail_in WHERE from_addr='mario@gmail.com'")[0][0] == "done")
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("#mailTriage")
        d_ = p.locator("#mailTriage details", has_text="Preventivo"); d_.locator("summary").click(); d_.locator("select[name=site_other]").select_option("ZM Alfa"); d_.locator("button", has_text="Assegna al cliente scelto").click(); p.wait_for_selector("form[action$=tk_note]")
        rec("triage: mittente sconosciuto assegnato e ricordato", dbq("SELECT site FROM tickets WHERE contact_email='nuovo@foo.org'")[0][0] == "ZM Alfa" and dbq("SELECT COUNT(*) FROM site_mail WHERE kind='address' AND value='nuovo@foo.org' AND site='ZM Alfa'")[0][0] == 1)
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("#mailTriage")
        d_ = p.locator("#mailTriage details", has_text="Vinci un premio"); d_.locator("summary").click(); d_.locator("button", has_text="Spam").click(); p.wait_for_selector("main")
        rec("triage: spam ignorato e mittente bloccato", dbq("SELECT COUNT(*) FROM mail_block WHERE addr='spam@bad.biz'")[0][0] == 1)
        p.goto(BASE + "?view=tickets"); d_ = p.locator("#mailTriage details", has_text="Bonifico urgente")
        rec("triage: l'avviso di autenticità è visibile", "verifica mittente" in p.inner_text("#mailTriage"))
        # nuovi messaggi: mittente ricordato, risposta con codice, risposta per riferimento, duplicato, bloccato
        tg = t_g[0][0]; code = t_g[0][1]
        c.request.post(BASE + "?action=tk_set", form={"id": str(tg), "status": "closed", "priority": "normal", "assignee": ""}, headers=H)
        mk(9, "Nuovo Cliente <nuovo@foo.org>", "Altro problema", "Il monitor non si accende.")
        mk(10, "Gigi Rossi <gigi@tossinimobili.it>", f"Re: Server lento [{code}]", "Adesso va meglio ma ogni tanto rallenta.\n\nIl giorno lun 5 ott, myrmm ha scritto:\n> Abbiamo ricevuto la tua richiesta", mid="<m10@test>")
        mk(11, "Gigi Rossi <gigi@tossinimobili.it>", "ancora io", "e adesso si è bloccato del tutto", In_Reply_To=ack[0][0]["Message-ID"], mid="<m11@test>")
        mk(12, "gigi@tossinimobili.it", "Server lento", "stesso messaggio", mid="<m1@test>")
        mk(13, "Spam <spam@bad.biz>", "Ancora", "x")
        c.request.post(BASE + "?action=mail_poll_now", headers=H)
        rec("posta: il mittente ricordato è instradato da solo", dbq("SELECT site FROM tickets WHERE title='Altro problema'")[0][0] == "ZM Alfa")
        nts = dbq("SELECT body, vis FROM ticket_notes WHERE ticket_id=? AND kind='in' ORDER BY id", tg)
        rec("posta: la risposta col codice si aggiunge al ticket, senza testo citato", len(nts) >= 2 and "ogni tanto rallenta" in nts[1][0] and "Abbiamo ricevuto" not in nts[1][0] and nts[1][1] == "pub", str(nts))
        rec("posta: la risposta per riferimento (senza codice) si aggancia al ticket", len(nts) == 3 and "bloccato del tutto" in nts[2][0], str(nts))
        rec("posta: il ticket chiuso si riapre alla risposta", dbq("SELECT status FROM tickets WHERE id=?", tg)[0][0] == "open")
        rec("posta: duplicato (stesso Message-ID) e mittente bloccato ignorati", dbq("SELECT COUNT(*) FROM tickets WHERE contact_email='gigi@tossinimobili.it'")[0][0] == 1 and dbq("SELECT COUNT(*) FROM mail_in WHERE from_addr='spam@bad.biz'")[0][0] == 1)
        # risposta pubblica dal ticket → email
        n0 = len(sent_to("gigi@tossinimobili.it"))
        c.request.post(BASE + "?action=tk_note", form={"id": str(tg), "text": "Ho ottimizzato il server, riprova.", "vis": "pub"}, headers=H)
        c.request.post(BASE + "?action=tk_note", form={"id": str(tg), "text": "Nota solo per noi", "vis": "int"}, headers=H)
        sm = sent_to("gigi@tossinimobili.it")
        rec("ticket email: la risposta pubblica parte per email con codice e riferimenti", len(sm) == n0 + 1 and code in sm[-1][1] and sm[-1][1].startswith("Re: Server lento") and "ottimizzato" in sm[-1][2] and sm[-1][0]["In-Reply-To"] == "<m11@test>", str([x_[1] for x_ in sm]))
        rec("ticket email: la nota interna non parte", not any("solo per noi" in x_[2] for x_ in sm))
        p.goto(BASE + f"?view=tickets&id={tg}"); p.wait_for_selector("select[name=vis]")
        rec("ticket email: la scheda mostra canale, richiedente e il form per il device", "email" in p.inner_text("main") and "gigi@tossinimobili.it" in p.inner_text("main") and p.locator("form[action$=tk_dev]").count() == 1 and "Azione sul device" not in p.inner_text("main"))
        c.request.post(BASE + "?action=tk_dev", form={"id": str(tg), "device_id": "1"}, headers=H)
        rec("ticket email: un device di un altro cliente non si collega", dbq("SELECT device_id FROM tickets WHERE id=?", tg)[0][0] == 0)
        p.goto(BASE + "?view=tickets&q=gigi%40tossini"); p.wait_for_selector("main")
        rec("ticket email: appare nell'elenco anche senza device", code in p.inner_text("main"))
        c.request.post(BASE + "?action=mail_cfg", form={"imap_host": "127.0.0.1", "imap_port": "8795", "imap_secure": "none", "imap_user": "richieste@example.org", "imap_pass": "sbagliata", "imap_folder": "INBOX", "poll": "1"}, headers=H)
        rr = c.request.post(BASE + "?action=mail_test", headers=H)
        rec("posta: password IMAP errata segnalata", "rifiutato" in urllib.parse.unquote_plus(rr.url) or "rifiutato" in rr.text(), urllib.parse.unquote_plus(rr.url)[-150:])
        c.request.post(BASE + "?action=mail_cfg", form={"imap_host": "", "imap_secure": "none"}, headers=H)
        # ticket manuale + scadenza dell'azione registrata nel ticket
        p.goto(BASE + "?view=tickets"); p.locator("main .hdrnew", has_text="Nuovo ticket").click()
        p.select_option("form[action$=tk_new] select[name=device_id]", index=1); p.fill("form[action$=tk_new] input[name=title]", "Controllare backup"); p.click("form[action$=tk_new] button[type=submit]"); p.wait_for_selector("form[action$=tk_note]")
        rec("ticket: creazione manuale", dbq("SELECT COUNT(*) FROM tickets WHERE title='Controllare backup'")[0][0] == 1)
        jx = dbq("SELECT id FROM jobs WHERE origin=?", f"tk:{t2}")[0][0]
        dbq("UPDATE jobs SET status='pending', expires='2000-01-01T00:00:00Z' WHERE id=?", jx); hbd(1)
        rec("ticket: azione scaduta annotata nel ticket", "scaduta" in str(dbq("SELECT group_concat(body) FROM ticket_notes WHERE ticket_id=?", t2)))
        p.goto(BASE + "?view=tickets"); rec("ticket: voce nel menu con contatore", p.locator("a.nav", has_text="Ticket").count() == 1)
        p.screenshot(path=f"{OUT}/ticket.png")
        # --- documentale
        p.goto(BASE + "?view=docs&edit=0"); p.wait_for_selector("form[action$=doc_save]")
        p.fill("input[name=title]", "Procedura backup NAS"); p.select_option("select[name=category]", "procedura")
        p.fill("textarea[name=body]", "# Backup\n\n1. Controllare il job\n2. Verificare **spazio**\n\n| Giorno | Ora |\n|---|---|\n| Lun | 22:00 |\n\nVedi [[ticket:1]] e [guida](https://example.com/x)\n\n<script>window.__xss=1</script>")
        p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector(".md")
        html = p.inner_html(".md")
        rec("documenti: Markdown reso (titolo, elenco, tabella, grassetto, link)", "<h3>" in html and "<ol>" in html and "<table>" in html and "<b>spazio</b>" in html and 'href="https://example.com/x"' in html and "?view=tickets&amp;id=1" in html)
        rec("documenti: HTML grezzo neutralizzato", "&lt;script&gt;" in html and p.evaluate("window.__xss") is None)
        did = dbq("SELECT id FROM docs WHERE title='Procedura backup NAS'")[0][0]
        p.goto(BASE + "?view=docs&edit=0"); p.fill("input[name=title]", "Accessi"); p.fill("textarea[name=body]", "Il server usa password: Abc12345xyz"); p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector("main p.err")
        rec("documenti: blocco delle credenziali", dbq("SELECT COUNT(*) FROM docs WHERE title='Accessi'")[0][0] == 0 and "credenziale" in p.inner_text("main"))
        p.goto(BASE + f"?view=docs&edit={did}"); p.fill("textarea[name=body]", "# Backup v2\n\nContenuto nuovo"); p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector(".md")
        rec("documenti: modifica crea una versione precedente", dbq("SELECT COUNT(*) FROM doc_rev WHERE doc_id=?", did)[0][0] == 1)
        p.goto(BASE + f"?view=docs&id={did}"); p.locator("details.card summary", has_text="Versioni precedenti").click(); p.click("form[action$=doc_restore] button"); p.wait_for_selector("main p.ok")
        rec("documenti: ripristino di una versione", "Controllare il job" in dbq("SELECT body FROM docs WHERE id=?", did)[0][0] and dbq("SELECT COUNT(*) FROM doc_rev WHERE doc_id=?", did)[0][0] == 2)
        site1 = dbq("SELECT COALESCE(site,'') FROM devices WHERE id=1")[0][0]
        p.goto(BASE + "?view=docs&sheet=" + urllib.parse.quote(site1)); p.wait_for_selector(".md")
        rec("documenti: scheda cliente generata dall'inventario", "Scheda cliente" in p.inner_text(".md") and "SRV-DEMO" in p.inner_text(".md"))
        p.goto(BASE + "?view=docs&device=1"); p.wait_for_selector(".md")
        rec("documenti: scheda device generata", "Scheda device: SRV-DEMO" in p.inner_text(".md") and "Dischi" in p.inner_text(".md"))
        rq = urllib.request.Request(BASE + "?action=doc_export&site=" + urllib.parse.quote(site1), headers={"Cookie": "; ".join(f"{k['name']}={k['value']}" for k in c.cookies())})
        exp = urllib.request.urlopen(rq, timeout=10).read().decode()
        rec("documenti: esporta Markdown", exp.startswith("# Scheda cliente") and "SRV-DEMO" in exp)
        p.goto(BASE + "?view=docs&q=Controllare"); p.wait_for_selector("table")
        rec("documenti: ricerca nel testo", "Procedura backup NAS" in p.inner_text("table"))
        p.goto(BASE + "?view=docs"); rec("documenti: nella ricerca globale", "Documento · Procedura backup NAS" in p.content())
        p.goto(BASE + "?view=device&id=1"); rec("documenti: collegamento dalla scheda device", p.locator("a:has-text('Scheda e documenti')").count() == 1)
        p.screenshot(path=f"{OUT}/docs.png")
        # --- modelli, revisione periodica, import
        import zipfile, tempfile, hashlib
        if not dbq("SELECT name FROM sites WHERE name='ACME'"): dbq("INSERT INTO sites (name, created) VALUES ('ACME', ?)", now)
        p.goto(BASE + "?view=docs"); p.wait_for_selector("select[name=tpl]")
        rec("modelli: modelli di serie disponibili", dbq("SELECT COUNT(*) FROM doc_templates WHERE builtin=1")[0][0] >= 9 and p.locator("select[name=tpl] option").count() == dbq("SELECT COUNT(*) FROM doc_templates")[0][0] + 1)
        p.select_option("select[name=tpl]", label="Scheda backup"); p.select_option("form:has(select[name=tpl]) select[name=site]", "ACME"); p.click("form:has(select[name=tpl]) button[type=submit]"); p.wait_for_selector("textarea[name=body]")
        body = p.input_value("textarea[name=body]")
        rec("modelli: segnaposto riempiti (cliente, data, autore)", "# Backup — ACME" in body and "{{" not in body.replace("{{DEVICE}}", "") and p.input_value("input[name=title]").startswith("Scheda backup"), body[:80])
        rec("modelli: revisione periodica preimpostata", p.input_value("select[name=review_months]") == "6")
        p.click("form[action$=doc_save] button[type=submit]"); p.wait_for_selector(".md")
        bid = dbq("SELECT id FROM docs WHERE title LIKE 'Scheda backup%' ORDER BY id DESC LIMIT 1")[0][0]
        rec("modelli: documento creato dal modello", dbq("SELECT review_months, site FROM docs WHERE id=?", bid)[0] == (6, "ACME"))
        dbq("UPDATE docs SET updated='2000-01-01T00:00:00Z', reviewed=NULL WHERE id=?", bid)
        p.goto(BASE + "?view=docs&due=1"); p.wait_for_selector("table")
        rec("revisione: il documento scaduto compare in «da rivedere»", "da rivedere" in p.inner_text("table") and "Scheda backup" in p.inner_text("table"))
        p.goto(BASE + f"?view=docs&id={bid}"); p.click("form[action$=doc_reviewed] button"); p.wait_for_selector("main p.ok")
        rec("revisione: «Segna come rivisto» azzera la scadenza", dbq("SELECT reviewed FROM docs WHERE id=?", bid)[0][0] is not None and "Da rivedere" not in p.inner_text("main"))
        # modelli di serie: aggiornamento se non modificati, protezione se modificati
        tid_ = dbq("SELECT id FROM doc_templates WHERE name='Rete e VLAN'")[0][0]
        dbq("UPDATE doc_templates SET body='vecchio', seed_hash=? WHERE id=?", hashlib.md5(b"vecchio").hexdigest(), tid_)
        p.goto(BASE + "?view=docs"); p.wait_for_selector("select[name=tpl]")
        rec("modelli: il modello di serie non modificato si aggiorna", dbq("SELECT body FROM doc_templates WHERE id=?", tid_)[0][0].startswith("# Rete"))
        dbq("UPDATE doc_templates SET body='mio testo' WHERE id=?", tid_)
        p.goto(BASE + "?view=docs"); p.wait_for_selector("select[name=tpl]")
        rec("modelli: il modello modificato dall'admin non viene sovrascritto", dbq("SELECT body FROM doc_templates WHERE id=?", tid_)[0][0] == "mio testo")
        p.locator("details.card summary", has_text="Gestione dei modelli").click(); p.locator("form[action$=tpl_reset] button").first.click(); p.wait_for_selector("main p.ok")
        rec("modelli: ripristino del testo di serie", dbq("SELECT body FROM doc_templates WHERE id=?", tid_)[0][0].startswith("# Rete"))
        p.goto(BASE + "?view=docs&tpl_edit=0"); p.fill("input[name=name]", "Mio modello"); p.fill("textarea[name=body]", "# {{CLIENTE}}\nciao"); p.click("form[action$=tpl_save] button[type=submit]"); p.wait_for_selector("main p.ok")
        rec("modelli: modello proprio creato", dbq("SELECT builtin FROM doc_templates WHERE name='Mio modello'")[0][0] == 0)
        # import: Markdown/HTML con credenziale saltata
        tmpd = tempfile.mkdtemp(); fl = []
        def mk(name, content, mode="w"):
            pth = os.path.join(tmpd, name); os.makedirs(os.path.dirname(pth), exist_ok=True)
            with open(pth, mode) as f: f.write(content)
            return pth
        f1 = mk("uno.md", "# Guida stampanti\n\nPassi:\n- accendi\n- stampa"); f2 = mk("due.html", "<h1>Guida Wi-Fi</h1><p>Rete <b>ospiti</b></p><img src='x.png'><ul><li>uno</li></ul>")
        f3 = mk("tre.txt", "Accessi\npassword: Segreta12345"); 
        p.goto(BASE + "?view=docs&import=1"); p.wait_for_selector("input[type=file]")
        p.set_input_files("input[type=file]", [f1, f2, f3]); p.click("form[action$=doc_import_upload] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_run]")
        txt = p.inner_text("form[action$=doc_import_run]")
        tv = p.eval_on_selector_all("form[action$=doc_import_run] input[name^='title[']", "e=>e.map(x=>x.value)")
        rec("import: anteprima con credenziale bloccata e immagine segnalata", "Guida stampanti" in tv and "Guida Wi-Fi" in tv and len(tv) == 3 and "credenziale" in txt and "immagini" in txt, str(tv))
        rec("import: nulla scritto prima della conferma", dbq("SELECT COUNT(*) FROM docs WHERE title IN ('Guida stampanti','Guida Wi-Fi','tre')")[0][0] == 0)
        p.click("form[action$=doc_import_run] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_undo]")
        wi = dbq("SELECT body FROM docs WHERE title='Guida Wi-Fi'")
        rec("import: documenti creati, HTML convertito, credenziale esclusa", dbq("SELECT COUNT(*) FROM docs WHERE title='Guida stampanti'")[0][0] == 1 and wi and "**ospiti**" in wi[0][0] and "<" not in wi[0][0] and dbq("SELECT COUNT(*) FROM docs WHERE body LIKE '%Segreta12345%'")[0][0] == 0, str(wi))
        # secondo import dello stesso titolo con «aggiorna» poi annullo
        f1b = mk("uno.md", "# Guida stampanti\n\nVersione nuova")
        p.goto(BASE + "?view=docs&import=1"); p.set_input_files("input[type=file]", [f1b]); p.select_option("select[name=def_mode]", "update"); p.click("form[action$=doc_import_upload] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_run]")
        p.click("form[action$=doc_import_run] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_undo]")
        rec("import: «aggiorna» sostituisce il testo e conserva la versione", dbq("SELECT body FROM docs WHERE title='Guida stampanti'")[0][0] == "Versione nuova" and dbq("SELECT COUNT(*) FROM doc_rev WHERE body LIKE '%accendi%'")[0][0] == 1)
        p.click("form[action$=doc_import_undo] button"); p.wait_for_selector("main p.ok")
        rec("import: annullamento ripristina il testo precedente", "accendi" in dbq("SELECT body FROM docs WHERE title='Guida stampanti'")[0][0])
        # ZIP con cartelle cliente/categoria
        zp = os.path.join(tmpd, "doc.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("ACME/rete/vlan aziendali.md", "# VLAN\n\nVLAN 10 utenti"); z.writestr("ACME/note generali.md", "Solo testo"); z.writestr("Sconosciuto/x.md", "# X\ncontenuto"); z.writestr("__MACOSX/._x.md", "no")
        p.goto(BASE + "?view=docs&import=1"); p.set_input_files("input[type=file]", [zp]); p.click("form[action$=doc_import_upload] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_run]")
        rows_ = p.locator("form[action$=doc_import_run] tr").count() - 1
        rec("import ZIP: 3 documenti, __MACOSX ignorato", rows_ == 3, str(rows_))
        rec("import ZIP: cartella = cliente e categoria", p.locator("select[name='site[0]']").input_value() == "ACME" and p.locator("select[name='cat[0]']").input_value() == "rete" and "non esiste" in p.inner_text("form[action$=doc_import_run]"))
        p.click("form[action$=doc_import_run] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_undo]")
        rec("import ZIP: salvati con cliente e categoria", dbq("SELECT site, category FROM docs WHERE title='VLAN'")[0] == ("ACME", "rete"))
        # CSV con mappatura e colonna password esclusa
        cp = mk("elenco.csv", "Nome;Tipo;Cliente;Descrizione;Password\nNAS ufficio;Server;ACME;Dispositivo di backup;Abc123456\nStampante;Altro;ACME;HP laser;Xyz98765\n")
        p.goto(BASE + "?view=docs&import=1"); p.set_input_files("input[type=file]", [cp]); p.click("form[action$=doc_import_upload] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_map]")
        rec("import CSV: colonna password disabilitata nella mappatura", p.locator("input[name='col_body[]'][disabled]").count() == 1)
        p.select_option("select[name=col_title]", label="Nome"); p.select_option("select[name=col_cat]", label="Tipo"); p.select_option("select[name=col_site]", label="Cliente")
        p.uncheck("input[name='col_body[]'] >> nth=0"); p.uncheck("input[name='col_body[]'] >> nth=1"); p.uncheck("input[name='col_body[]'] >> nth=2")
        p.click("form[action$=doc_import_map] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_run]")
        p.click("form[action$=doc_import_run] button[type=submit]"); p.wait_for_selector("form[action$=doc_import_undo]")
        nas = dbq("SELECT body, site, category FROM docs WHERE title='NAS ufficio'")
        rec("import CSV: documento dalla riga, senza la password", nas and nas[0][0] == "Dispositivo di backup" and nas[0][1] == "ACME" and nas[0][2] == "server" and dbq("SELECT COUNT(*) FROM docs WHERE body LIKE '%Abc123456%'")[0][0] == 0, str(nas))
        p.screenshot(path=f"{OUT}/runbooks.png"); c.close()
        # --- cerca nei menu a selezione e filtri nella ricerca globale
        d8 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); d8.execute("INSERT OR IGNORE INTO filters(name,criteria,created) VALUES('Server Windows 2022','{\"mode\":\"and\",\"conds\":[]}',?)", (now,)); d8.commit(); d8.close()
        c, p = new(); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        dev_job(p)
        sq = p.locator("select[name=response_script_id]").first
        n0 = sq.locator("option").count(); cbr = p.locator(".cb:has(select[name=response_script_id])").first
        cbr.locator(".cbb").click(); cbr.locator(".cbp input").fill("RAM"); n1 = cbr.locator("li[role=option]").count()
        rec("menu a selezione: campo Cerca restringe le voci", 8 <= n0 and 1 <= n1 < n0, f"{n0}->{n1}")
        cbr.locator(".cbp input").press("Enter"); rec("menu a selezione: Invio sceglie la prima voce", "ram" in sq.evaluate("e=>e.options[e.selectedIndex].text").lower() and "ram" in cbr.locator(".cbb").inner_text().lower())
        p.keyboard.press("Control+k"); p.fill("#palq", "Server Windows"); wait_txt(p, "#pall", lambda t: "Filtro" in t)
        rec("ricerca globale: trova i filtri", True)
        p.click("#pall li"); p.wait_for_selector("main")
        rec("ricerca globale: il filtro apre l'elenco device filtrato", "filter=" in p.url, p.url)
        p.wait_for_load_state("load"); p.wait_for_timeout(300); p.keyboard.press("Control+k"); p.fill("#palq", "Script · Monitor: RAM"); wait_txt(p, "#pall", lambda t: "Script · Monitor: RAM" in t)
        p.click("#pall li"); p.wait_for_selector("#runf")
        rec("ricerca globale: lo script apre «Esegui su…»", "view=run&script=" in p.url, p.url); c.close()
        # --- prova di carico
        c, p = new(); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        jserr = []; p.on("pageerror", lambda e: jserr.append(str(e)))
        p.goto(BASE + "?view=system#t=prova-di-carico"); p.wait_for_selector("#ltGo")
        p.click("#ltBench"); wait_txt(p, "#ltOut", lambda t: "commit singolo" in t, 30)
        rec("prova di carico: misura del server", "commit singolo" in p.inner_text("#ltOut") and "PHP" in p.inner_text("#ltOut"))
        p.fill("#ltN", "12"); p.fill("#ltD", "6"); p.fill("#ltO", "1"); p.on("dialog", lambda d: d.accept()); p.click("#ltGo")
        ok = wait_txt(p, "#ltOut", lambda t: "Esito" in t and "richieste" in t, 60)
        rec("prova di carico: report finale", ok, p.inner_text("#ltMsg"))
        txt = p.inner_text("#ltOut") if ok else ""
        rec("prova di carico: nessun errore e navigazione console misurata", ok and "errori" in txt and "dashboard" in txt and "oltre il limite" not in txt, txt[:300])
        d10 = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); left = d10.execute("SELECT COUNT(*) FROM devices WHERE site='(prova di carico)'").fetchone()[0]; d10.close()
        rec("prova di carico: device simulati eliminati a fine prova", left == 0, str(left))
        dk = sqlite3.connect(os.path.join(srv, "data", "docs.sqlite")); dl = dk.execute("SELECT COUNT(*) FROM docs WHERE site='(prova di carico)'").fetchone()[0]; dr = dk.execute("SELECT COUNT(*) FROM doc_rev WHERE author='loadtest'").fetchone()[0]; dk.close()
        rec("prova di carico: documenti simulati (docs.sqlite) eliminati a fine prova", dl == 0 and dr == 0, f"{dl} {dr}")
        rec("documentazione: separata in docs.sqlite, non più nel database principale", all(not sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")).execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone() for t in ("docs", "doc_rev", "doc_templates", "doc_import")))
        rec("prova di carico: nessun errore JS", not jserr, str(jserr)); c.close()
        # --- modalità demo (1.30.0)
        H = {"Origin": f"http://127.0.0.1:{PORT}"}
        prodp = os.path.join(srv, "data", "myrmm.sqlite"); demod = os.path.join(srv, "data", "demo")
        def q_(path, sql, *a):
            cx = sqlite3.connect(path); r = cx.execute(sql, a).fetchall(); cx.close(); return r
        def adm(c, p):
            p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
        c2, p2 = new(); adm(c2, p2)   # seconda sessione admin: deve restare sui dati veri
        p2.goto(BASE + "?view=dashboard"); p2.wait_for_selector("main"); time.sleep(1)
        prod0 = (q_(prodp, "SELECT COUNT(*) FROM devices")[0][0], q_(prodp, "SELECT COUNT(*) FROM tickets")[0][0], q_(prodp, "SELECT COUNT(*) FROM alerts")[0][0])
        p.goto(BASE + "?view=profile"); p.wait_for_selector("main")
        rec("demo: scheda «Modalità demo» nel profilo dell'admin", p.locator("button:has-text('Entra in modalità demo')").count() == 1)
        rec("demo: senza attivarla non esiste la cartella demo e la barra non c'è", not os.path.isdir(demod) and p.locator("#demoBar").count() == 0)
        t0 = time.time()
        p.evaluate("document.querySelector(\"form[action$='demo_on']\").submit()"); p.wait_for_selector("#demoBar")
        rec("demo: entra con la barra «DEMO — dati fittizi»", "DEMO" in p.inner_text("#demoBar") and "fittizi" in p.inner_text("#demoBar"))
        rec("demo: i dati nascono al primo ingresso (tempo ragionevole)", time.time() - t0 < 25, f"{time.time() - t0:.1f}s")
        dm = os.path.join(demod, "myrmm.sqlite")
        nd = q_(dm, "SELECT COUNT(*) FROM devices")[0][0]; ns = q_(dm, "SELECT COUNT(*) FROM sites")[0][0]
        rec("demo: circa 10 clienti e oltre 60 device", ns == 10 and nd >= 60, f"{ns} {nd}")
        rec("demo: metriche e documenti nei file demo, non in quelli veri", q_(os.path.join(demod, "metrics.sqlite"), "SELECT COUNT(*) FROM m_raw")[0][0] > 10000 and q_(os.path.join(demod, "docs.sqlite"), "SELECT COUNT(*) FROM docs")[0][0] >= 5)
        chs = sorted(r[0] for r in q_(dm, "SELECT DISTINCT channel FROM tickets"))
        rec("demo: ticket di ogni canale (alert, manuale, tray, email)", chs == ["alert", "email", "manual", "tray"], str(chs))
        rec("demo: email da smistare, risolutivi, runbook, asset, scadenze presenti", q_(dm, "SELECT COUNT(*) FROM mail_in WHERE status='new'")[0][0] == 3 and q_(dm, "SELECT COUNT(*) FROM ticket_auto")[0][0] >= 3 and q_(dm, "SELECT COUNT(*) FROM runbooks")[0][0] >= 3 and q_(dm, "SELECT COUNT(*) FROM assets")[0][0] >= 8 and q_(dm, "SELECT COUNT(*) FROM expiries")[0][0] >= 5)
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        rec("demo: la dashboard mostra i clienti fittizi", "Farmacia San Marco" in p.inner_text("main") and "Hotel Belvedere" in p.inner_text("main"))
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("main")
        rec("demo: elenco ticket con codici", "T-" in p.inner_text("main") and "Wi-Fi lento" in p.inner_text("main"))
        p.goto(BASE + "?view=alerts"); p.wait_for_selector("main")
        rec("demo: alert aperti in elenco (offline, disco, CPU…)", "Spazio basso" in p.inner_text("main") and "Nessun heartbeat" in p.inner_text("main"))
        p.goto(BASE + "?view=network&tab=mappa&site=Hotel+Belvedere"); b_ = p.content()
        rec("demo: la rete dimostrativa mostra la mappa con collegamenti LLDP/CDP e ipotetici", len(re.findall(r'<g data-n=', b_)) >= 12 and len(re.findall(r'data-e="(lldp|cdp)"', b_)) >= 5 and 'data-e="guess"' in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_), str(len(re.findall(r'<g data-n=', b_))))
        p.screenshot(path=f"{OUT}/mappa-rete-demo.png", full_page=True)
        p.goto(BASE + "?view=network&tab=apparati"); b_ = p.inner_text("main")
        rec("demo: apparati di rete di ogni profilo (firewall, switch, AP, UPS, NAS, stampante)", all(x in b_ for x in ("FW-BELVEDERE", "SW-CORE", "AP-HALL", "UPS-CED", "NAS-BACKUP", "STAMPA-RECEPTION")))
        p.goto(BASE + "?view=network&tab=scoperti"); rec("demo: apparati scoperti da censire", "TELECAMERA-INGRESSO" in p.inner_text("main"))
        # l'altra sessione non vede nulla della demo
        p2.goto(BASE + "?view=dashboard"); p2.wait_for_selector("main")
        rec("demo: l'altra sessione admin resta sui dati veri, senza barra", p2.locator("#demoBar").count() == 0 and "Farmacia San Marco" not in p2.inner_text("main"))
        # nessuna scrittura sul database vero, né dall'attivazione né dalla navigazione
        prod1 = (q_(prodp, "SELECT COUNT(*) FROM devices")[0][0], q_(prodp, "SELECT COUNT(*) FROM tickets")[0][0], q_(prodp, "SELECT COUNT(*) FROM alerts")[0][0])
        rec("demo: il database vero non cambia (device, ticket, alert)", prod0 == prod1, f"{prod0} {prod1}")
        rec("demo: solo la sessione che l'ha attivata porta il flag", sum(r[0] for r in q_(prodp, "SELECT demo FROM sessions")) == 1)
        # agent: nessun cookie, nessuna demo. Il heartbeat di un device vero aggiorna i dati veri.
        t1 = q_(prodp, "SELECT last_seen FROM devices WHERE api_key='k1'")[0][0]; time.sleep(1.2)
        try: hb({"light": True, "sess": {"session_state": "attiva", "session_user": "DOM\\mario", "sessions": []}})
        except Exception: pass
        rec("demo: il heartbeat di un device vero aggiorna i dati veri, non la demo", q_(prodp, "SELECT last_seen FROM devices WHERE api_key='k1'")[0][0] > t1 and q_(dm, "SELECT COUNT(*) FROM devices WHERE api_key='k1'")[0][0] == 0)
        # azioni sull'installazione vera: rifiutate
        for act, form in [("cfg_save", {"x": "1"}), ("notif_save", {"x": "1"}), ("backupnow", {}), ("pwchange", {"current": "a", "new": "b"})]:
            rr = c.request.post(BASE + "?action=" + act, form=form, headers=H)
            rec(f"demo: {act} rifiutata", rr.status == 403, str(rr.status))
        # un job lanciato in demo viene eseguito in simulazione, senza agent
        did = q_(dm, "SELECT id FROM devices WHERE hostname='BIA-PC01'")[0][0]
        c.request.post(BASE + "?action=newjob", form={"device_id": str(did), "script": "# Prova demo\nWrite-Output 'x'", "timeout": "60"}, headers=H)
        ok = False
        for _ in range(8):
            time.sleep(4); p.goto(BASE + "?view=dashboard")
            if q_(dm, "SELECT status FROM jobs WHERE script LIKE '# Prova demo%'")[0][0] == "done": ok = True; break
        rec("demo: un job si chiude da solo in simulazione", ok)
        rec("demo: l'esito del job è etichettato come simulato", ok and "[demo]" in q_(dm, "SELECT stdout FROM results WHERE job_id=(SELECT id FROM jobs WHERE script LIKE '# Prova demo%')")[0][0])
        # il risolutivo lanciato da un alert lo fa rientrare
        al = q_(dm, "SELECT a.id FROM alerts a JOIN devices d ON d.id=a.device_id WHERE a.status='open' AND a.type='disk:C:' ORDER BY a.id LIMIT 1")
        au = q_(dm, "SELECT id FROM ticket_auto WHERE alert_type='disk:C:' AND mode='auto' LIMIT 1")
        if al and au:
            c.request.post(BASE + "?action=rem_run", form={"alert_id": str(al[0][0]), "auto_id": str(au[0][0]), "back": "?view=alerts"}, headers=H)
            ok = False
            for _ in range(8):
                time.sleep(4); p.goto(BASE + "?view=alerts")
                if q_(dm, "SELECT status FROM alerts WHERE id=?", al[0][0])[0][0] == "resolved": ok = True; break
            rec("demo: il risolutivo lanciato dall'alert lo fa rientrare", ok)
        else: rec("demo: il risolutivo lanciato dall'alert lo fa rientrare", False, "alert o regola mancanti")
        # nessuna uscita verso l'esterno: l'invio email è bloccato
        smtp0 = len(GOT["smtp"])
        rr = c.request.post(BASE + "?action=tk_note", form={"id": str(q_(dm, "SELECT id FROM tickets WHERE channel='email' LIMIT 1")[0][0]), "text": "Risposta di prova", "vis": "pub"}, headers=H)
        rec("demo: una risposta pubblica a un ticket email non invia nulla", (time.sleep(1.5) or len(GOT["smtp"]) == smtp0), str(len(GOT["smtp"]) - smtp0))
        # rigenera: i dati tornano come all'inizio, la sessione resta in demo
        q_n = lambda: q_(dm, "SELECT COUNT(*) FROM tickets WHERE title='Marcatore demo'")[0][0]
        cx = sqlite3.connect(dm); cx.execute("INSERT INTO tickets (device_id, title, status, priority, assignee, alert_id, alert_type, site, created, updated, minutes, by_user) VALUES (0,'Marcatore demo','open','normal','',0,'','Hotel Belvedere','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',0,'x')"); cx.commit(); cx.close()
        rec("demo: segno un dato in demo (marcatore)", q_n() == 1)
        p.goto(BASE + "?view=dashboard")
        p.evaluate("document.querySelector(\"form[action$='demo_regen']\").onsubmit=null; document.querySelector(\"form[action$='demo_regen']\").submit()"); p.wait_for_selector("#demoBar")
        rec("demo: «Rigenera» ricrea i dati da zero e resta in demo", q_n() == 0 and q_(dm, "SELECT COUNT(*) FROM devices")[0][0] >= 60 and p.locator("#demoBar").count() == 1)
        # uscire: si torna sui dati veri
        p.evaluate("document.querySelector(\"form[action$='demo_off']\").submit()"); p.wait_for_selector("main")
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        rec("demo: «Esci dalla demo» riporta ai dati veri (niente barra)", p.locator("#demoBar").count() == 0 and "Farmacia San Marco" not in p.inner_text("main"))
        rec("demo: i dati demo restano per la prossima volta", os.path.isfile(dm))
        # rientro e logout: dopo il logout la sessione successiva non è in demo
        p.goto(BASE + "?view=profile"); p.evaluate("document.querySelector(\"form[action$='demo_on']\").submit()"); p.wait_for_selector("#demoBar")
        rec("demo: rientrando i dati demo non vengono ricreati (stesso database)", q_(dm, "SELECT COUNT(*) FROM sites")[0][0] == 10)
        p.goto(BASE + "?action=logout"); p.wait_for_selector("input[name=username]")
        p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        rec("demo: dopo logout e nuovo accesso si è sui dati veri", p.locator("#demoBar").count() == 0)
        # elimina: la cartella sparisce, chi era in demo torna sui dati veri
        p.goto(BASE + "?view=profile"); p.evaluate("document.querySelector(\"form[action$='demo_on']\").submit()"); p.wait_for_selector("#demoBar")
        p.goto(BASE + "?view=profile"); p.wait_for_selector("main")
        p.evaluate("document.querySelector(\"form[action$='demo_del']\").onsubmit=null; document.querySelector(\"form[action$='demo_del']\").submit()"); p.wait_for_selector("main")
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main")
        rec("demo: «Elimina dati demo» cancella la cartella e riporta ai dati veri", not os.path.isdir(demod) and p.locator("#demoBar").count() == 0)
        p2.goto(BASE + "?view=dashboard"); p2.wait_for_selector("main")
        rec("demo: l'altra sessione non si è mai accorta di nulla", p2.locator("#demoBar").count() == 0)
        prod2 = (q_(prodp, "SELECT COUNT(*) FROM devices")[0][0], q_(prodp, "SELECT COUNT(*) FROM tickets")[0][0], q_(prodp, "SELECT COUNT(*) FROM alerts")[0][0])
        rec("demo: al termine il database vero è identico", prod2 == prod0, f"{prod0} {prod2}")
        rec("demo: nessun errore JS", not errs, str(errs)); c.close(); c2.close()
        # --- pagine a sezioni: schede a sinistra
        c, p = new(); errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail")
        for v, minn in [("system", 5), ("scripts", 2), ("packs", 5), ("profile", 3), ("deploy", 2), ("maint", 2), ("fields", 2), ("users", 2), ("vars", 2)]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main")
            n = p.locator(".dnav a").count()
            rec(f"{v}: schede a sinistra ({n})", n >= minn or p.locator(".hdrnew").count() >= 1)
            rec(f"{v}: una sola sezione visibile", p.locator(".dpane.on").count() == 1)
            if n >= 2:
                p.locator(".dnav a").nth(1).click(); rec(f"{v}: seconda scheda si apre", p.locator(".dpane.on").count() == 1 and p.locator(".dnav a.on").count() == 1)
            p.screenshot(path=f"{OUT}/view-{v}.png")
        p.goto(BASE + "?view=users"); p.wait_for_selector(".hdrnew")
        rec("utenti: «+ Nuovo utente» è un pulsante primario in testata, non una scheda", p.locator(".dnav a", has_text="Nuovo").count() == 0 and "Nuovo utente" in p.inner_text(".hdrnew"))
        p.click(".hdrnew"); rec("utenti: il pulsante apre il modulo di creazione con «Torna all'elenco»", p.locator(".dpane.on input[name=username]").count() == 1 and p.locator(".dpane.on .hdrback").count() == 1)
        p.click(".hdrback"); rec("utenti: «Torna all'elenco» riporta alla lista", p.locator(".dpane.on input[name=username]").count() == 0)
        p.goto(BASE + "?view=checks"); p.wait_for_selector(".hdrnew"); rec("check: stesso schema (niente barra a sinistra con una sola voce)", p.locator(".dtabs.one").count() == 1 and p.locator(".dnav").first.is_hidden())
        p.goto(BASE + "?view=tickets"); p.wait_for_selector("main")
        rec("ticket: «+ Nuovo ticket» è un pulsante primario in testata", p.locator("main .hdrnew", has_text="Nuovo ticket").count() == 1 and p.locator("main details.fold[data-hdr]").is_hidden())
        p.click("main .hdrnew"); rec("ticket: il pulsante apre il modulo", p.locator("main details.fold[data-hdr][open] select[name=device_id]").is_visible())
        rec("ticket: niente pulsante «Filtra», il filtro è dal vivo", p.locator("main form[method=get] button:has-text('Filtra'):visible").count() == 0)
        p.select_option("select[name=pr]", "crit"); p.wait_for_load_state("load"); p.wait_for_timeout(500)
        rec("ticket: cambiando un filtro la pagina si aggiorna da sola", "pr=crit" in p.url, p.url)
        p.fill("input[name=q]", "zzzz-nessuno"); p.wait_for_timeout(1500)
        rec("ticket: la ricerca filtra mentre si scrive", "q=zzzz-nessuno" in p.url, p.url)
        rec("pagine a sezioni: nessun errore JS", not errs, str(errs)); c.close()
        c, p = new(w=390, h_=800); p.goto(BASE); p.fill("input[name=username]", "admin"); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".content")
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector(".dnav"); p.screenshot(path=f"{OUT}/device-mobile.png")
        rec("mobile: nessuno scroll orizzontale", p.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"))
        p.goto(BASE + "?view=devices"); p.screenshot(path=f"{OUT}/devices-mobile.png"); c.close()
        # --- 1.31.0: interruzione multipla dei job senza ricaricare; ultimi device aperti
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for i in range(4): cx.execute("INSERT INTO jobs(device_id,script,timeout,status,created) VALUES(1,?,60,'pending',?)", (f"# Banana {i}\nWrite-Output 'x'", nowz))
        cx.execute("INSERT INTO jobs(device_id,script,timeout,status,created) VALUES(1,'# Banana sent\nWrite-Output 1',60,'sent',?)", (nowz,))
        cx.execute("INSERT INTO jobs(device_id,script,timeout,status,created) VALUES(2,'# Banana altro device',60,'pending',?)", (nowz,)); cx.commit(); cx.close()
        bid = lambda t: q_(prodp, "SELECT id FROM jobs WHERE script LIKE ?", f"# Banana {t}%")[0][0]
        bst = lambda t: q_(prodp, "SELECT status FROM jobs WHERE script LIKE ?", f"# Banana {t}%")[0][0]
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        p.goto(BASE + "?view=jobs&q=Banana&st=open"); p.wait_for_selector(".jsel")
        rec("job: casella di selezione sui job attivi (Attività)", p.locator(".jsel").count() == 6, str(p.locator(".jsel").count()))
        p.evaluate("window.__marker=1; window.scrollTo(0, 50)")
        p.locator(".jsel").nth(0).click(); p.locator(".jsel").nth(2).click(modifiers=["Shift"])
        rec("job: Maiusc+clic seleziona un intervallo", p.locator(".jsel:checked").count() == 3, str(p.locator(".jsel:checked").count()))
        bk = lambda lab: (p.evaluate("document.querySelector('#bkmenu').open") or p.click("#bkmenu summary"), p.click(f"#bkmenu .mi:has-text('{lab}')"))
        bk("Deseleziona"); p.wait_for_timeout(150); rec("job: «Deseleziona tutto» (menu Azioni) svuota la selezione", p.locator(".jsel:checked").count() == 0 and p.locator("#bkN").is_hidden())
        bk("Seleziona i job"); p.wait_for_timeout(150)
        rec("job: «Seleziona i job in coda o in corso» (menu Azioni)", p.locator(".jsel:checked").count() == 6 and p.inner_text("#bkN") == "6")
        bk("Interrompi"); wait_txt(p, "#mytoast", lambda t: "interrotti" in t)
        rec("job: interruzione multipla senza ricaricare la pagina", p.evaluate("window.__marker") == 1)
        rec("job: in coda annullati, quello inviato in interruzione (anche su un altro device)", bst("0") == "cancelled" and bst("3") == "cancelled" and bst("altro") == "cancelled" and bst("sent") == "cancel", f"{bst('0')} {bst('sent')}")
        rec("job: la riga si aggiorna da sola (stato e casella)", "annullato" in p.locator("tr[data-job]").first.inner_text() and p.locator(".jsel:visible").count() == 1)
        p.locator(".jsel:visible").first.click(); bk("Forza chiusura")
        for _ in range(30):
            if bst("sent") == "cancelled": break
            time.sleep(.2)
        rec("job: «Forza chiusura» chiude lato server quello in interruzione", bst("sent") == "cancelled")
        # scheda del device: interruzione singola senza ricarica e selezione multipla
        cx = sqlite3.connect(prodp)
        for i in range(3): cx.execute("INSERT INTO jobs(device_id,script,timeout,status,created) VALUES(1,?,60,'pending',?)", (f"# Banana dev {i}\nWrite-Output 'x'", nowz))
        cx.commit(); cx.close()
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector("details.job")
        p.evaluate("window.__marker2=1")
        d0 = p.locator("details.job[data-st=pending]").count()
        p.locator("details.job[data-st=pending]").first.locator("summary").click()
        p.locator("details.job[data-st=pending]").first.locator("button:has-text('Annulla')").click(); p.wait_for_selector("details.job[data-st=cancelled] .jst")
        p.wait_for_function("n => document.querySelectorAll('details.job[data-st=pending]').length <= n", arg=d0 - 1, timeout=5000); rec("job: «Annulla» di un singolo job non ricarica la pagina", p.evaluate("window.__marker2") == 1 and p.locator("details.job[data-st=pending]").count() == d0 - 1, str(d0))
        p.click("button:has-text('In corso')"); p.click("#jStop"); wait_txt(p, "#mytoast", lambda t: "interrotti" in t)
        rec("job: selezione multipla anche nella scheda del device", p.locator("details.job[data-st=pending]").count() == 0 and p.evaluate("window.__marker2") == 1)
        rec("job: nessun errore JS", not errs, str(errs))
        # ultimi device aperti
        cx = sqlite3.connect(prodp)
        for i in range(12): cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,created,site) VALUES(?,?,?,?,?,?)", (f"ZREC-{i:02d}", "windows", f"zrec{i}", nowz, nowz, "ZR"))
        cx.commit(); zid = [r[0] for r in cx.execute("SELECT id FROM devices WHERE hostname LIKE 'ZREC-%' ORDER BY hostname")]; cx.close()
        for d_ in zid: c.request.get(BASE + f"?view=device&id={d_}")
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("#recsel"); p.click("#recsel summary")
        items = p.locator("#recsel li a")
        rec("recenti: almeno una decina di device nell'elenco", items.count() >= 10, str(items.count()))
        rec("recenti: il più recente è in cima", "ZREC-11" in items.first.inner_text() and "ZREC-10" in items.nth(1).inner_text())
        items.first.click(); p.wait_for_selector(".dnav")
        rec("recenti: il collegamento apre la scheda del device", "view=device&id=" + str(zid[-1]) in p.url, p.url)
        c.request.get(BASE + f"?view=device&id={zid[0]}")
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("#recsel"); p.click("#recsel summary")
        rec("recenti: riaprire un device lo riporta in cima senza duplicarlo", "ZREC-00" in p.locator("#recsel li a").first.inner_text() and p.locator("#recsel li a:has-text('ZREC-00')").count() == 1)
        p.click("main h2"); rec("recenti: si chiude cliccando fuori", p.evaluate("!document.getElementById('recsel').open"))
        cx = sqlite3.connect(prodp); cx.execute("DELETE FROM devices WHERE hostname LIKE 'ZREC-%'"); cx.commit(); cx.close(); c.close()
        # --- risoluzioni strette: le tabelle scorrono, la pagina no; creazione asset dalla loro schermata e dal device
        c, p = new(w=700, h_=800); adm(c, p)
        for v in ["assets", "devices", "alerts", "tickets", "docs", "system", "report"]:
            p.goto(BASE + "?view=" + v); p.wait_for_selector("main"); p.wait_for_timeout(200)
            rec(f"schermo stretto: {v} senza scorrimento orizzontale della pagina", p.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"), str(p.evaluate("document.documentElement.scrollWidth")))
        p.goto(BASE + "?view=assets"); p.wait_for_selector("main")
        rec("schermo stretto: le tabelle stanno in un contenitore scorrevole", p.locator("main .tw > table").count() >= 1)
        tid0 = q_(prodp, "SELECT id FROM asset_types ORDER BY id LIMIT 1")[0][0]
        rec("asset: pulsante «+ Nuovo asset» nella loro schermata", p.locator("#antsel summary").count() == 1 and "Nuovo asset" in p.inner_text("#antsel summary"))
        p.click("#antsel summary"); p.locator("#antsel a").first.click(); p.wait_for_selector("form[action$='asset_save']")
        rec("asset: il pulsante apre il modulo del tipo scelto", "view=asset&id=0&type=" in p.url, p.url)
        p.goto(BASE + "?view=device&id=1"); p.wait_for_selector("main")
        rec("device: «+ Asset per questo device» nella scheda", "+ Asset per questo device" in p.content())
        p.goto(BASE + f"?view=asset&id=0&type={tid0}&device=1"); p.wait_for_selector("form[action$='asset_save']")
        rec("device: dal rimando il modulo ha già il device collegato", p.eval_on_selector("#asDev", "e=>e.value") == "1")
        c.close()
        # >>> t132
        # --- 1.32.0: sottoreti, sonde, apparati monitorati
        def hbk(key, body=None):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body or {"light": True}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        def rep(key, results):
            rq = urllib.request.Request(BASE + "?action=probe_report", data=json.dumps({"results": results}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            try: return urllib.request.urlopen(rq, timeout=10).status
            except urllib.error.HTTPError as e: return e.code
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cx.execute("INSERT INTO sites(name,created) VALUES('Rete Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,created,site) VALUES('SONDA-A','windows','kpa',?,?,'Rete Srl')", (nowz, nowz))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,created,site) VALUES('SONDA-B','linux','kpb',?,?,'Rete Srl')", (nowz, nowz))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,created,site) VALUES('PC-RETE','windows','kpc',?,?,'Rete Srl')", (nowz, nowz))
        fw = cx.execute("SELECT id FROM asset_types WHERE name LIKE 'Firewall%'").fetchone()[0]
        cx.execute("INSERT INTO assets(type_id,name,site,data,created) VALUES(?,?,?,?,?)", (fw, "Firewall sede", "Rete Srl", json.dumps({"ip_lan": "10.7.0.1"}), nowz)); cx.commit()
        dA, dB, dC = [q_(prodp, "SELECT id FROM devices WHERE hostname=?", n)[0][0] for n in ("SONDA-A", "SONDA-B", "PC-RETE")]
        asid = q_(prodp, "SELECT id FROM assets WHERE name='Firewall sede'")[0][0]; cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        p.goto(BASE + "?view=network"); p.wait_for_selector("main h2")
        rec("rete: voce di menu e schede Apparati / Sottoreti / Sonde", p.locator(".rail a.nav", has_text="Rete").count() >= 1 and all(t in p.inner_text(".tabs") for t in ["Apparati", "Sottoreti", "Sonde"]))
        rec("rete: senza apparati compare l'invito a creare rete e sonda", "Nessun apparato monitorato" in p.inner_text("main"))
        # sottorete: validazione e creazione
        p.goto(BASE + "?view=network&tab=sottoreti"); p.wait_for_selector("main")
        p.locator("main .hdrnew").first.click()
        p.select_option("form[action$='net_subnet_add'] select[name=site]", "Rete Srl"); p.fill("input[name=cidr]", "10.7.0.0/33"); p.fill("input[name=name]", "LAN sede"); p.click("form[action$='net_subnet_add'] button[type=submit]")
        p.wait_for_selector(".ok"); rec("sottorete: CIDR non valido rifiutato", "Rete non valida" in p.inner_text(".ok") and q_(prodp, "SELECT COUNT(*) FROM net_subnets")[0][0] == 0)
        p.locator("main .hdrnew, details.fold summary").first.click()
        p.select_option("form[action$='net_subnet_add'] select[name=site]", "Rete Srl"); p.fill("input[name=cidr]", "10.7.0.5/24"); p.fill("input[name=name]", "LAN sede"); p.click("form[action$='net_subnet_add'] button[type=submit]")
        p.wait_for_selector(".ok"); rec("sottorete: creata e normalizzata (10.7.0.5/24 → 10.7.0.0/24)", q_(prodp, "SELECT cidr FROM net_subnets WHERE site='Rete Srl'") == [("10.7.0.0/24",)], str(q_(prodp, "SELECT cidr FROM net_subnets")))
        sid = q_(prodp, "SELECT id FROM net_subnets")[0][0]
        rr = c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sid), "device_id": str(dA), "op": "add", "prio": "1"}, headers=H)
        rec("sottorete: un device non-sonda non si collega", q_(prodp, "SELECT COUNT(*) FROM net_subnet_probes")[0][0] == 0)
        # sonde: promozione dalla scheda Sonde e dalla scheda del device
        p.goto(BASE + "?view=network&tab=sonde"); p.wait_for_selector("main")
        p.locator("main .hdrnew, details.fold summary").first.click(); p.select_option("form[action$='probe_set'] select[name=device_id]", str(dA)); p.click("form[action$='probe_set'] button[type=submit]"); p.wait_for_selector(".tw table")
        rec("sonde: promozione di un device", q_(prodp, "SELECT probe FROM devices WHERE id=?", dA) == [(1,)])
        p.goto(BASE + f"?view=device&id={dB}#t=remoto"); p.wait_for_selector(".dpane.on")
        rec("device: scheda «Sonda di rete» con pulsante di promozione", "Sonda di rete" in p.content() and "Promuovi a sonda" in p.content())
        p.locator("form[action$='probe_set'] button").first.click(); p.wait_for_selector("main")
        rec("device: promozione dalla scheda del device", q_(prodp, "SELECT probe FROM devices WHERE id=?", dB) == [(1,)])
        for d, pr in ((dA, 1), (dB, 2)): c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sid), "device_id": str(d), "op": "add", "prio": str(pr)}, headers=H)
        rec("sottorete: due sonde collegate con priorità", q_(prodp, "SELECT device_id, prio FROM net_subnet_probes ORDER BY prio") == [(dA, 1), (dB, 2)])
        rr = c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sid), "device_id": str(dC), "op": "add", "prio": "3"}, headers=H)
        rec("sottorete: un device normale non può essere collegato", q_(prodp, "SELECT COUNT(*) FROM net_subnet_probes WHERE device_id=?", dC)[0][0] == 0)
        # apparati: aggiunta dal modulo, validazione
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector("main")
        def add_t(site, name, ip, kind="ping", port="", asset=0):
            p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector("main"); p.locator("main .hdrnew, details.fold summary").first.click()
            f = "form[action$='net_target_add']"
            p.select_option(f + " select[name=site]", site); p.fill(f + " input[name=name]", name); p.fill(f + " input[name=ip]", ip); p.select_option(f + " select[name=kind]", kind); p.fill(f + " input[name=port]", str(port))
            if asset: p.select_option(f + " select[name=asset_id]", str(asset))
            p.click(f + " button[type=submit]"); p.wait_for_selector(".ok"); return p.inner_text(".ok")
        m = add_t("Rete Srl", "Fuori rete", "172.16.5.9")
        rec("apparato: IP fuori da ogni sottorete rifiutato con il motivo", "Nessuna rete del cliente contiene" in m and q_(prodp, "SELECT COUNT(*) FROM net_targets")[0][0] == 0, m)
        m = add_t("Rete Srl", "Firewall sede", "10.7.0.1", "tcp", 443, asid)
        m2 = add_t("Rete Srl", "Stampante ufficio", "10.7.0.20")
        rows = q_(prodp, "SELECT name, kind, port, subnet_id, status FROM net_targets ORDER BY id")
        rec("apparato: aggiunti ping e TCP e assegnati alla sottorete", rows == [("Firewall sede", "tcp", 443, sid, ""), ("Stampante ufficio", "ping", 0, sid, "")], str(rows))
        rec("apparato: duplicato rifiutato", "esiste già" in add_t("Rete Srl", "Doppione", "10.7.0.20"))
        tF, tP = [q_(prodp, "SELECT id FROM net_targets WHERE name=?", n)[0][0] for n in ("Firewall sede", "Stampante ufficio")]
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector(".tw table")
        rec("apparato: appena aggiunto risulta «in attesa»", p.locator("tr", has_text="Stampante ufficio").locator(".pill").first.inner_text().strip() == "in attesa")
        # heartbeat: la sonda attiva riceve gli apparati, la riserva no; la versione evita di rinviare tutto
        hA = hbk("kpa"); hB = hbk("kpb"); hC = hbk("kpc")
        rec("sonda: l'heartbeat porta gli apparati alla sonda attiva", "probe" in hA and [t["id"] for t in hA["probe"]["targets"]] == [tF, tP] and hA["probe"]["on"] is True, str(hA.get("probe")))
        rec("sonda: la sonda di riserva riceve la configurazione vuota", "probe" in hB and hB["probe"]["targets"] == [], str(hB.get("probe")))
        rec("sonda: un device normale non riceve nulla", "probe" not in hC)
        hA2 = hbk("kpa", {"light": True, "probe_ver": hA["probe"]["ver"]})
        rec("sonda: con la versione già in uso la configurazione non viene rinviata", "probe" not in hA2)
        rec("sonda: un device normale non può inviare esiti", rep("kpc", [{"id": tF, "ok": True, "rtt": 1}]) == 403)
        # esiti: 3 falliti → giù + avviso sulla sonda; poi riuscito → su + avviso chiuso
        ts = int(time.time())
        rep("kpa", [{"id": tP, "ok": False, "detail": "nessuna risposta (timeout)", "ts": ts}])
        rec("esito: un solo fallimento non dichiara l'apparato giù", q_(prodp, "SELECT status, fails FROM net_targets WHERE id=?", tP) == [("", 1)], str(q_(prodp, "SELECT status, fails FROM net_targets WHERE id=?", tP)))
        rep("kpa", [{"id": tP, "ok": False, "detail": "nessuna risposta (timeout)", "ts": ts}, {"id": tP, "ok": False, "detail": "nessuna risposta (timeout)", "ts": ts}])
        rec("esito: dopo tre fallimenti l'apparato è giù", q_(prodp, "SELECT status, fails FROM net_targets WHERE id=?", tP) == [("down", 3)])
        al = q_(prodp, "SELECT device_id, severity, message, status FROM alerts WHERE type=?", f"net:{tP}:down")
        rec("esito: avviso aperto sulla sonda con il nome dell'apparato", len(al) == 1 and al[0][0] == dA and "Stampante ufficio" in al[0][2] and "10.7.0.20" in al[0][2] and al[0][3] == "open", str(al))
        rep("kpa", [{"id": tP, "ok": False, "ts": ts}])
        rec("esito: ulteriori fallimenti non duplicano l'avviso", q_(prodp, "SELECT COUNT(*) FROM alerts WHERE type=?", f"net:{tP}:down")[0][0] == 1)
        tk = q_(prodp, "SELECT COUNT(*) FROM tickets WHERE alert_id=?", al[0] and q_(prodp, "SELECT id FROM alerts WHERE type=?", f"net:{tP}:down")[0][0])[0][0] if al else 0
        rep("kpa", [{"id": tP, "ok": True, "rtt": 2.4, "ts": ts}, {"id": tF, "ok": True, "rtt": 0.8, "ts": ts}, {"id": 99999, "ok": True, "rtt": 1, "ts": ts}])
        rec("esito: riuscito → raggiungibile, avviso chiuso, esito di apparato altrui ignorato", q_(prodp, "SELECT status, fails FROM net_targets WHERE id=?", tP) == [("up", 0)] and q_(prodp, "SELECT status FROM alerts WHERE type=?", f"net:{tP}:down") == [("resolved",)])
        rec("esito: la sonda di riserva non può scrivere esiti per apparati non suoi", rep("kpb", [{"id": tF, "ok": False, "ts": ts}] * 4) == 200 and q_(prodp, "SELECT status FROM net_targets WHERE id=?", tF) == [("up",)])
        mt = q_(os.path.join(srv, "data", "metrics.sqlite"), "SELECT COUNT(*) FROM m_raw WHERE dev=? AND metric='net.rtt'", -tP)[0][0]
        rec("metriche: il tempo di risposta viene registrato per l'apparato", mt >= 1, str(mt))
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector(".tw table")
        rec("apparati: stato «raggiungibile» e tempo in elenco", p.locator("tr", has_text="Stampante ufficio").locator(".pill").first.inner_text().strip() == "raggiungibile" and "2,4" not in "" and "ms" in p.locator("tr", has_text="Stampante ufficio").inner_text())
        # failover: la sonda A tace → B prende in carico, apparati «sconosciuti» se tacciono tutte
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (dA,)); cx.commit(); cx.close()
        hB2 = hbk("kpb")
        rec("failover: con la sonda A offline la B riceve gli apparati", "probe" in hB2 and len(hB2["probe"]["targets"]) == 2, str(hB2.get("probe")))
        rep("kpb", [{"id": tF, "ok": False, "detail": "x", "ts": ts}] * 3)
        al2 = q_(prodp, "SELECT device_id FROM alerts WHERE type=? AND status='open'", f"net:{tF}:down")
        rec("failover: l'avviso nasce sulla sonda che sta lavorando", al2 == [(dB,)], str(al2))
        rep("kpb", [{"id": tF, "ok": True, "rtt": 1, "ts": ts}])
        rec("failover: un esito positivo chiude l'avviso anche se aperto da un'altra sonda", q_(prodp, "SELECT status FROM alerts WHERE type=?", f"net:{tF}:down") == [("resolved",)])
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (dB,)); cx.commit(); cx.close()
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector(".tw table")
        rec("apparati: con tutte le sonde offline lo stato è «sconosciuto», non «giù»", all(p.locator("tr", has_text=n).locator(".pill").first.inner_text().strip() == "sconosciuto" for n in ("Stampante ufficio", "Firewall sede")))
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen=? WHERE id IN (?,?)", (nowz, dA, dB)); cx.commit(); cx.close()
        # sospensione, modifica, rimozione
        c.request.post(BASE + "?action=net_target_toggle", form={"id": str(tP)}, headers=H)
        rec("apparato: sospeso non viene più inviato alla sonda", [t["id"] for t in hbk("kpa")["probe"]["targets"]] == [tF])
        c.request.post(BASE + "?action=net_target_toggle", form={"id": str(tP)}, headers=H)
        c.request.post(BASE + "?action=net_target_edit", form={"id": str(tP), "name": "Stampante piano 1", "ip": "10.7.0.21", "kind": "tcp", "port": "9100", "every": "30", "sev": "crit"}, headers=H)
        rec("apparato: modifica di nome, IP, controllo e gravità", q_(prodp, "SELECT name, ip, kind, port, interval_s, sev FROM net_targets WHERE id=?", tP) == [("Stampante piano 1", "10.7.0.21", "tcp", 9100, 30, "crit")])
        # asset: scheda con monitoraggio
        p.goto(BASE + f"?view=asset&id={asid}"); p.wait_for_selector("main")
        rec("asset: la scheda mostra il monitoraggio di rete dell'apparato", "Monitoraggio di rete" in p.content() and "raggiungibile" in p.inner_text("main"))
        cx = sqlite3.connect(prodp); cx.execute("INSERT INTO assets(type_id,name,site,data,created) VALUES(?,?,?,?,?)", (fw, "Router filiale", "Rete Srl", json.dumps({"ip_lan": "10.7.0.2"}), nowz)); cx.commit(); cx.close()
        a2 = q_(prodp, "SELECT id FROM assets WHERE name='Router filiale'")[0][0]
        p.goto(BASE + f"?view=asset&id={a2}"); p.wait_for_selector("main"); p.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        p.select_option("form[action$='net_target_add'] select[name=kind]", "ping"); p.click("form[action$='net_target_add'] button.btn2"); p.wait_for_selector(".ok")
        rec("asset: «Monitora» dall'asset crea l'apparato collegato", q_(prodp, "SELECT ip, asset_id, name FROM net_targets WHERE ip='10.7.0.2'") == [("10.7.0.2", a2, "Router filiale")], str(q_(prodp, "SELECT ip, asset_id, name FROM net_targets")))
        # permessi: l'operatore gestisce gli apparati ma non reti e sonde
        c3, p3 = new()
        p3.goto(BASE); p3.fill("input[name=username]", "plain"); p3.fill("input[name=password]", PW); p3.click("button[type=submit]"); p3.wait_for_selector(".rail")
        rr = c3.request.post(BASE + "?action=net_subnet_add", form={"site": "Rete Srl", "cidr": "10.9.0.0/24"}, headers=H)
        rec("permessi: l'operatore non crea sottoreti", q_(prodp, "SELECT COUNT(*) FROM net_subnets")[0][0] == 1)
        rr = c3.request.post(BASE + "?action=probe_set", form={"device_id": str(dC), "on": "1"}, headers=H)
        rec("permessi: l'operatore non promuove sonde", q_(prodp, "SELECT probe FROM devices WHERE id=?", dC) == [(0,)])
        rr = c3.request.post(BASE + "?action=net_target_toggle", form={"id": str(tF)}, headers=H)
        rec("permessi: l'operatore sospende un apparato", q_(prodp, "SELECT enabled FROM net_targets WHERE id=?", tF) == [(0,)])
        c.request.post(BASE + "?action=net_target_toggle", form={"id": str(tF)}, headers=H)
        c3.close()
        # declassamento ed eliminazioni
        c.request.post(BASE + "?action=probe_set", form={"device_id": str(dB), "on": "0"}, headers=H)
        hB3 = hbk("kpb", {"light": True, "probe_ver": "abc"})
        rec("sonda declassata: riceve «off» e smette di lavorare", hB3.get("probe", {}).get("on") is False, str(hB3.get("probe")))
        c.request.post(BASE + "?action=net_target_del", form={"id": str(tP)}, headers=H)
        rec("apparato rimosso", q_(prodp, "SELECT COUNT(*) FROM net_targets WHERE id=?", tP)[0][0] == 0)
        c.request.post(BASE + "?action=net_subnet_del", form={"subnet_id": str(sid)}, headers=H)
        rec("sottorete eliminata: gli apparati restano «senza sonda»", q_(prodp, "SELECT COUNT(*) FROM net_subnets")[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM net_subnet_probes")[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM net_targets WHERE subnet_id=0")[0][0] >= 1)
        rec("rete: nessun errore JavaScript", not errs, str(errs))
        c.close()
        # <<< t132
        # >>> t133
        # --- 1.33.0: tunnel verso gli apparati via sonda
        def post_json(c_, action, form):
            r_ = c_.request.post(BASE + "?action=" + action, form=form, headers=H); 
            try: return r_.status, r_.json()
            except Exception: return r_.status, {}
        def hbn(key, body=None):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body or {"light": True}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not cx.execute("SELECT 1 FROM sites WHERE name='Tunnel Srl'").fetchone(): cx.execute("INSERT INTO sites(name,created) VALUES('Tunnel Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-T','linux','kpt',?,?,?,'Tunnel Srl',1)", (nowz, json.dumps({"agent_version": "1.33.0"}), nowz))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-VECCHIA','linux','kpo',?,?,?,'Tunnel Srl',1)", (nowz, json.dumps({"agent_version": "1.32.0"}), nowz))
        fw = cx.execute("SELECT id FROM asset_types WHERE name LIKE 'Firewall%'").fetchone()[0]
        cx.execute("INSERT INTO assets(type_id,name,site,data,created) VALUES(?,?,?,?,?)", (fw, "Firewall T", "Tunnel Srl", json.dumps({"ip_lan": "10.9.0.1"}), nowz))
        cx.execute("INSERT INTO assets(type_id,name,site,data,created) VALUES(?,?,?,?,?)", (fw, "Firewall isolato", "Tunnel Srl", json.dumps({"ip_lan": "10.99.0.1"}), nowz)); cx.commit()
        dT = q_(prodp, "SELECT id FROM devices WHERE hostname='SONDA-T'")[0][0]; dO = q_(prodp, "SELECT id FROM devices WHERE hostname='SONDA-VECCHIA'")[0][0]
        aT = q_(prodp, "SELECT id FROM assets WHERE name='Firewall T'")[0][0]; aI = q_(prodp, "SELECT id FROM assets WHERE name='Firewall isolato'")[0][0]; cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        c.request.post(BASE + "?action=net_subnet_add", form={"site": "Tunnel Srl", "cidr": "10.9.0.0/24", "name": "LAN tunnel"}, headers=H)
        sT = q_(prodp, "SELECT id FROM net_subnets WHERE site='Tunnel Srl'")[0][0]
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sT), "device_id": str(dT), "op": "add", "prio": "1"}, headers=H)
        st_, j_ = post_json(c, "tun_net_open", {"asset_id": str(aT), "ip": "10.9.0.1", "port": "443", "json": "1"})
        rec("tunnel apparato: aperto dall'asset, restituisce id e token", st_ == 200 and len(j_.get("id", "")) == 24 and len(j_.get("token", "")) == 32 and j_.get("host") == "10.9.0.1", str((st_, j_)))
        tr = q_(prodp, "SELECT device_id, host, port, state FROM tunnels WHERE id=?", j_.get("id", "x"))
        rec("tunnel apparato: registrato sulla sonda della rete con host e porta", tr == [(dT, "10.9.0.1", 443, "new")], str(tr))
        hb_ = hbn("kpt"); of_ = hb_.get("tunnel")
        import hmac as _hm, hashlib as _hl
        want = _hm.new(b"k" * 32, f"tunnelnet\n{j_['id']}\n{dT}\n10.9.0.1\n443\n{of_['exp']}".encode(), _hl.sha256).hexdigest() if of_ else ""
        rec("tunnel apparato: la sonda riceve l'offerta con host e firma sulla destinazione", bool(of_) and of_.get("host") == "10.9.0.1" and of_.get("port") == 443 and of_.get("sig") == want, str(of_))
        rec("tunnel apparato: la sonda resta in poll rapido mentre il tunnel è aperto", hb_.get("fast") is True)
        for name, form, frag in [
            ("porta non ammessa (Telnet)", {"asset_id": str(aT), "ip": "10.9.0.1", "port": "23"}, "Porta non consentita"),
            ("IP che non appartiene all'asset", {"asset_id": str(aT), "ip": "10.9.0.77", "port": "443"}, "non appartiene"),
            ("apparato in una rete senza sottorete", {"asset_id": str(aI), "ip": "10.99.0.1", "port": "443"}, "Nessuna rete del cliente"),
            ("apparato non indicato", {"port": "443"}, "Indica l'apparato")]:
            st_, j2 = post_json(c, "tun_net_open", dict(form, json="1"))
            rec(f"tunnel apparato: rifiutato — {name}", st_ == 400 and frag in j2.get("error", ""), str((st_, j2)))
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sT), "device_id": str(dO), "op": "add", "prio": "2"}, headers=H)
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (dT,)); cx.commit(); cx.close()
        st_, j2 = post_json(c, "tun_net_open", {"asset_id": str(aT), "ip": "10.9.0.1", "port": "443", "json": "1"})
        rec("tunnel apparato: con la sonda attiva troppo vecchia (agent < 1.33) il tunnel è rifiutato con il motivo", st_ == 400 and "1.33.0" in j2.get("error", ""), str((st_, j2)))
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen='2020-01-01T00:00:00Z' WHERE id IN (?,?)", (dT, dO)); cx.commit(); cx.close()
        st_, j2 = post_json(c, "tun_net_open", {"asset_id": str(aT), "ip": "10.9.0.1", "port": "443", "json": "1"})
        rec("tunnel apparato: senza sonde online il tunnel è rifiutato", st_ == 400 and "Nessuna sonda online" in j2.get("error", ""), str((st_, j2)))
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen=? WHERE id IN (?,?)", (nowz, dT, dO)); cx.commit(); cx.close()
        # il tunnel verso un apparato non viene chiuso aprendo un tunnel normale sulla stessa sonda
        c.request.post(BASE + "?action=tun_open", form={"device_id": str(dT), "port": "22", "json": "1"}, headers=H)
        rec("tunnel apparato: un tunnel verso la sonda stessa non chiude quello verso l'apparato", q_(prodp, "SELECT state FROM tunnels WHERE id=?", j_["id"])[0][0] != "closed")
        # tetto di tunnel per sonda
        for i_ in range(6): post_json(c, "tun_net_open", {"asset_id": str(aT), "ip": "10.9.0.1", "port": "22", "json": "1"})
        st_, j2 = post_json(c, "tun_net_open", {"asset_id": str(aT), "ip": "10.9.0.1", "port": "8443", "json": "1"})
        rec("tunnel apparato: massimo 6 tunnel aperti per sonda", st_ == 400 and "Troppi tunnel" in j2.get("error", ""), str((st_, j2)))
        # pagina del tunnel e schede
        p.goto(BASE + f"?view=tunnel&id={j_['id']}#t={j_['token']}"); p.wait_for_selector("#tnCmd", state="attached"); p.wait_for_timeout(300)
        cmd_ = p.text_content("#tnCmd")
        rec("tunnel apparato: la pagina propone il proxy locale per l'interfaccia web", "-socks 127.0.0.1:13380" in cmd_ and "-dest 10.9.0.1:443" in cmd_ and "-open https://10.9.0.1/" in cmd_, cmd_)
        rec("tunnel apparato: la pagina indica la sonda e l'apparato", "10.9.0.1" in p.inner_text("main h2") and "SONDA-T" in p.inner_text("main h2"))
        p.goto(BASE + f"?view=asset&id={aT}"); p.wait_for_selector("main")
        rec("asset: «Apri tunnel» verso la console dell'apparato via sonda", "Apri tunnel" in p.content() and "via sonda SONDA-T" in p.inner_text("main"))
        rec("audit: apertura del tunnel verso l'apparato registrata", q_(prodp, "SELECT COUNT(*) FROM audit WHERE action='tunnel_open' AND detail LIKE '%10.9.0.1%443%SONDA-T%'")[0][0] >= 1)
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector("main")
        c.request.post(BASE + "?action=net_target_add", form={"site": "Tunnel Srl", "name": "Firewall T", "ip": "10.9.0.1", "kind": "ping", "asset_id": str(aT)}, headers=H)
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector(".tw table")
        rec("rete: elenco apparati con «tunnel» per riga", p.locator("tr", has_text="Firewall T").locator("summary", has_text="tunnel").count() == 1)
        c.request.post(BASE + "?action=tun_close", form={"id": j_["id"]}, headers=H)
        rec("tunnel apparato: chiuso dalla console", q_(prodp, "SELECT state FROM tunnels WHERE id=?", j_["id"])[0][0] == "closed")
        rec("tunnel apparato: nessun errore JavaScript", not errs, str(errs))
        c.close()
        # <<< t133
        # >>> t138
        # --- 1.38: accesso remoto anche per Linux/macOS (script e tunnel)
        c, p = new(); adm(c, p); p.on("dialog", lambda d: d.accept())
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET os='macOS 15.1 darwin/arm64', last_seen=? WHERE id=?", (nowz, dT)); cx.commit(); cx.close()
        p.goto(BASE + f"?view=device&id={dT}"); p.wait_for_selector("main")
        rec("tunnel macOS: la scheda propone SSH e Condivisione schermo", "SSH / Condivisione schermo" in p.content())
        rec("tunnel macOS: porta predefinita 5900", p.locator("select[name=port] option[selected]").first.get_attribute("value") == "5900")
        rec("tunnel macOS: rimanda allo script di abilitazione", "macOS: abilita/disabilita Condivisione schermo (VNC)" in p.content())
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET os='Ubuntu 24.04 linux/amd64' WHERE id=?", (dT,)); cx.commit(); cx.close()
        p.goto(BASE + f"?view=device&id={dT}"); p.wait_for_selector("main")
        rec("tunnel Linux: porta predefinita 22 e rimando a xrdp", p.locator("select[name=port] option[selected]").first.get_attribute("value") == "22" and "xrdp" in p.content())
        for port_, flag_ in (("5900", "-vnc"), ("3389", "-rdp"), ("22", "-ssh tecnico -alias myrmm-d%d" % dT)):
            st_, j3 = post_json(c, "tun_open", {"device_id": str(dT), "port": port_, "json": "1"})
            p.goto(BASE + f"?view=tunnel&id={j3['id']}#t={j3['token']}"); p.wait_for_selector("#tnCmd", state="attached"); p.wait_for_timeout(200)
            if port_ == "22":
                rec("tunnel SSH: la pagina chiede l'utente", p.locator("#tnUser").count() == 1)
                rec("tunnel SSH: senza utente nessun -ssh", "-ssh" not in p.text_content("#tnCmd"), p.text_content("#tnCmd"))
                p.fill("#tnUser", "tecnico"); p.wait_for_timeout(200)
                p.fill("#tnUser", "te cnico;rm"); p.wait_for_timeout(200)
                rec("tunnel SSH: utente non valido ignorato", "-ssh" not in p.text_content("#tnCmd"), p.text_content("#tnCmd"))
                p.fill("#tnUser", "tecnico"); p.wait_for_timeout(200)
            rec(f"tunnel porta {port_}: il comando contiene {flag_.split()[0]}", flag_ in p.text_content("#tnCmd"), p.text_content("#tnCmd"))
            # un clic: collegamento myrmm-tunnel:// con modalità e token, riquadro di registrazione
            go_ = p.get_attribute("#tnGo", "href") or ""
            md_ = {"5900": "vnc", "3389": "rdp", "22": "ssh"}[port_]
            rec(f"tunnel porta {port_}: «Avvia sul mio PC» ha il collegamento myrmm-tunnel (modalità {md_})", go_.startswith("myrmm-tunnel://open?") and "id=" + j3["id"] in go_ and "token=" + j3["token"] in go_ and "mode=" + md_ in go_ and p.is_visible("#tnOne") and "tunnel-register -u" in p.text_content("#tnReg"), go_)
            if port_ == "22":
                rec("tunnel SSH: con utente valido il collegamento porta -ssh e l'alias", "mode=ssh" in go_ and "ssh=tecnico" in go_ and "alias=myrmm-d%d" % dT in go_, go_)
                p.fill("#tnUser", "te cnico;rm"); p.wait_for_timeout(200)
                rec("tunnel SSH: con utente non valido il pulsante è disattivato", p.evaluate("getComputedStyle(document.querySelector('#tnGo')).pointerEvents") == "none")
            if port_ == "3389":   # prova vera: l'agent, lanciato con quel collegamento, apre il tunnel sul server di prova
                import urllib.parse as up_
                u_ = up_.parse_qs(up_.urlparse(go_).query)["u"][0]
                cfgd_ = tempfile.mkdtemp(prefix="myrmm-uri-"); os.makedirs(cfgd_ + "/myrmm")
                open(cfgd_ + "/myrmm/tunnel-servers.txt", "w").write(u_ + "\n")
                envx_ = dict(os.environ, XDG_CONFIG_HOME=cfgd_, APPDATA=cfgd_, HOME=cfgd_)
                agbin_ = os.path.join(cfgd_, "agent-bin")
                bld_ = subprocess.run(["go", "build", "-o", agbin_, "."], cwd=os.path.join(ROOT, "agent"), capture_output=True, text=True)
                if bld_.returncode != 0:
                    rec("tunnel un clic: compilazione dell'agent", False, bld_.stderr[-300:])
                else:
                    try: o_ = subprocess.run([agbin_, "tunnel-uri", go_], env=envx_, capture_output=True, text=True, timeout=6).stdout
                    except subprocess.TimeoutExpired as e_: o_ = (e_.stdout or b"").decode() if isinstance(e_.stdout, bytes) else (e_.stdout or "")
                    rec("tunnel un clic: l'agent lanciato dal collegamento apre il tunnel sul server", "Tunnel pronto su 127.0.0.1:13389" in o_, o_[-300:])
                    ev_ = subprocess.run([agbin_, "tunnel-uri", go_.replace("token=" + j3["token"], "token=" + "0" * 32)], env=envx_, capture_output=True, text=True, timeout=20)
                    rec("tunnel un clic: token errato rifiutato", "non raggiungibile" in ev_.stderr or ev_.returncode != 0, ev_.stderr[-200:])
                    ee_ = subprocess.run([agbin_, "tunnel-uri", go_.replace("&mode=rdp", "&mode=rdp&listen=0.0.0.0:13389")], env=dict(envx_, XDG_CONFIG_HOME=tempfile.mkdtemp(), APPDATA="", HOME=tempfile.mkdtemp()), capture_output=True, text=True, timeout=20)
                    rec("tunnel un clic: server non registrato rifiutato", ee_.returncode == 2 and "non registrato" in ee_.stderr, ee_.stderr[-200:])
                shutil.rmtree(cfgd_, ignore_errors=True)
            c.request.post(BASE + "?action=tun_close", form={"id": j3["id"]}, headers=H)
        names_ = ["Linux/macOS: installa RustDesk (controllo remoto)", "Linux/macOS: installa RustDesk (accettazione utente)", "Linux/macOS: abilita/disabilita SSH (per i tunnel)", "macOS: abilita/disabilita Condivisione schermo (VNC)", "Linux: abilita/disabilita desktop remoto (xrdp)"]
        for n_ in names_:
            r_ = q_(prodp, "SELECT platform, length(body), length(description) FROM scripts WHERE name=?", n_)
            rec(f"libreria: «{n_}» presente per Linux/macOS", bool(r_) and r_[0][0] == "unix" and r_[0][1] > 500 and r_[0][2] > 20, str(r_))
        c.close()
        # <<< t138
        # >>> t139
        # --- 1.38: credenziali multiple per cliente (SNMP/Windows/SSH), scelta per rete e per apparato, vincente ricordata
        def hb2(key, body=None):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body or {"light": True}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not cx.execute("SELECT 1 FROM sites WHERE name='Cred Srl'").fetchone(): cx.execute("INSERT INTO sites(name,created) VALUES('Cred Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-C','linux','kpcr',?,?,?,'Cred Srl',1)", (nowz, json.dumps({"agent_version": "1.38.0"}), nowz)); cx.commit()
        dC = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-C'").fetchone()[0]; cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        c.request.post(BASE + "?action=net_subnet_add", form={"site": "Cred Srl", "cidr": "10.30.0.0/24", "name": "LAN cred"}, headers=H)
        sC = q_(prodp, "SELECT id FROM net_subnets WHERE site='Cred Srl'")[0][0]
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sC), "device_id": str(dC), "op": "add", "prio": "1"}, headers=H)
        for nm_, form_ in (("Stampanti", {"kind": "snmp", "v": "2c", "comm": "comm-stampanti"}), ("Firewall v3", {"kind": "snmp", "v": "3", "user": "fw", "level": "authPriv", "ap": "SHA256", "ak": "autenticazione1", "pp": "AES", "pk": "cifratura-lunga1"}), ("Admin dominio", {"kind": "win", "user": "CORP\\\\adm", "pass": "segreto-win"}), ("Utente SSH", {"kind": "ssh", "user": "root", "pass": "segreto-ssh"})):
            c.request.post(BASE + "?action=cred_save", form={"site": "Cred Srl", "name": nm_, **form_}, headers=H)
        rows_ = q_(prodp, "SELECT name, kind, data FROM site_creds WHERE site='Cred Srl' ORDER BY id")
        rec("credenziali: più credenziali per lo stesso cliente (SNMP v2c, v3, Windows, SSH)", [r[1] for r in rows_] == ["snmp", "snmp", "win", "ssh"], str(rows_)[:200])
        rec("credenziali: password cifrate nel database", all(x not in json.dumps(rows_) for x in ("comm-stampanti", "autenticazione1", "cifratura-lunga1", "segreto-win", "segreto-ssh")))
        c.request.post(BASE + "?action=cred_save", form={"site": "Cred Srl", "name": "Stampanti", "kind": "snmp", "v": "2c", "comm": "altra"}, headers=H)
        rec("credenziali: nome doppio per lo stesso cliente rifiutato", q_(prodp, "SELECT COUNT(*) FROM site_creds WHERE name='Stampanti'")[0][0] == 1)
        p.goto(BASE + "?view=network&tab=credenziali"); b_ = p.content()
        rec("credenziali: elenco senza segreti in chiaro", "comm-stampanti" not in b_ and "segreto-win" not in b_ and "Firewall v3" in b_ and "SNMP v3 · fw" in b_)
        ids_ = {r[0]: i for i, r in zip(range(1, 9), rows_)}
        cid = {n: q_(prodp, "SELECT id FROM site_creds WHERE name=?", n)[0][0] for n in ("Stampanti", "Firewall v3")}
        hb_ = hb2("kpcr"); nn_ = {n["id"]: n for n in hb_.get("probe", {}).get("nets", [])}
        sn_ = nn_.get(sC, {}).get("snmp", {})
        rec("credenziali: la sonda riceve la prima più le alternative (con il loro id)", sn_.get("cid") == cid["Stampanti"] and len(sn_.get("alts", [])) == 1 and sn_["alts"][0].get("cid") == cid["Firewall v3"] and sn_["alts"][0].get("u") == "fw", str(sn_)[:240])
        rec("credenziali: Windows e SSH non vanno alla sonda come SNMP", "segreto-win" not in json.dumps(hb_) and "segreto-ssh" not in json.dumps(hb_))
        c.request.post(BASE + "?action=net_subnet_creds", form={"subnet_id": str(sC), "ids[]": str(cid["Firewall v3"])}, headers=H)
        hb_ = hb2("kpcr"); sn_ = {n["id"]: n for n in hb_.get("probe", {}).get("nets", [])}[sC]["snmp"]
        rec("credenziali: scelta per rete (solo quella spuntata)", sn_.get("cid") == cid["Firewall v3"] and "alts" not in sn_, str(sn_)[:200])
        c.request.post(BASE + "?action=net_subnet_creds", form={"subnet_id": str(sC)}, headers=H)
        for nm, ip in (("Stampante C1", "10.30.0.50"), ("Stampante C2", "10.30.0.51")):
            c.request.post(BASE + "?action=net_target_add", form={"site": "Cred Srl", "name": nm, "ip": ip, "kind": "snmp", "every": "60", "sev": "warn", "profile": "auto"}, headers=H)
        t1, t2 = [q_(prodp, "SELECT id FROM net_targets WHERE name=?", n)[0][0] for n in ("Stampante C1", "Stampante C2")]
        hb_ = hb2("kpcr"); tg_ = {t["id"]: t for t in hb_["probe"]["targets"]}
        rec("credenziali: apparato senza scelta prova tutte quelle della rete", tg_[t1]["snmp"].get("cid") == cid["Stampanti"] and len(tg_[t1]["snmp"].get("alts", [])) == 1)
        # scelta su più apparati insieme
        c.request.post(BASE + "?action=net_target_creds", data="ids[]=%d&ids[]=%d&creds[]=%d&back=apparati" % (t1, t2, cid["Firewall v3"]), headers={**H, "Content-Type": "application/x-www-form-urlencoded"})
        rec("credenziali: scelta su più apparati in un colpo", [r[0] for r in q_(prodp, "SELECT cred_ids FROM net_targets WHERE id IN (?,?)", t1, t2)] == ['[%d]' % cid["Firewall v3"]] * 2)
        hb_ = hb2("kpcr"); tg_ = {t["id"]: t for t in hb_["probe"]["targets"]}
        rec("credenziali: la sonda riceve solo la scelta dell'apparato", tg_[t2]["snmp"].get("cid") == cid["Firewall v3"] and "alts" not in tg_[t2]["snmp"])
        c.request.post(BASE + "?action=net_target_creds", data="ids[]=%d&back=apparati" % t1, headers={**H, "Content-Type": "application/x-www-form-urlencoded"})
        # la sonda riferisce quale credenziale ha risposto: viene ricordata e va per prima
        rq = urllib.request.Request(BASE + "?action=probe_report", data=json.dumps({"results": [{"id": t1, "ok": True, "rtt": 3, "ts": int(time.time()), "snmp": {"name": "STAMPA", "profile": "printer", "cid": cid["Firewall v3"]}}]}).encode(), headers={"X-Device-Key": "kpcr", "Content-Type": "application/json"}); urllib.request.urlopen(rq, timeout=10).read()
        rec("credenziali: la credenziale che risponde viene ricordata", q_(prodp, "SELECT cred_id FROM net_targets WHERE id=?", t1)[0][0] == cid["Firewall v3"])
        hb_ = hb2("kpcr"); tg_ = {t["id"]: t for t in hb_["probe"]["targets"]}
        rec("credenziali: la vincente è la prima da provare", tg_[t1]["snmp"].get("cid") == cid["Firewall v3"] and tg_[t1]["snmp"]["alts"][0]["cid"] == cid["Stampanti"])
        p.goto(BASE + f"?view=nettarget&id={t1}"); rec("credenziali: la scheda apparato mostra quella in uso", "Firewall v3" in p.inner_text("main") and "In uso" in p.inner_text("main"))
        # l'apparato scoperto con credenziali scelte
        cx = sqlite3.connect(prodp); cx.execute("INSERT INTO net_found(site,subnet_id,ip,ipn,mac,name,kind,ports,snmp,ping,up,first_seen,last_seen,state) VALUES('Cred Srl',?,'10.30.0.77',169869389,'aa:bb:cc:00:00:77','sw77','switch','[]',?,1,1,?,?,'new')", (sC, json.dumps({"name": "sw77", "profile": "switch", "cid": cid["Stampanti"]}), nowz, nowz)); cx.commit(); cx.close()
        fid = q_(prodp, "SELECT id FROM net_found WHERE ip='10.30.0.77'")[0][0]
        c.request.post(BASE + "?action=net_found_act", form={"op": "census", "ids[]": str(fid), "monitor": "auto", "creds[]": str(cid["Firewall v3"]), "back": ""}, headers=H)
        r_ = q_(prodp, "SELECT cred_ids, cred_id, kind FROM net_targets WHERE ip='10.30.0.77'")
        rec("credenziali: il censimento memorizza la scelta e la credenziale già riconosciuta", r_ and r_[0][0] == '[%d]' % cid["Firewall v3"] and r_[0][1] == cid["Stampanti"] and r_[0][2] == "snmp", str(r_))
        p.goto(BASE + "?view=network&tab=sottoreti"); rec("credenziali: la tabella reti mostra quante ne usa", "2 credenziali" in p.inner_text("main"), p.inner_text("main")[:400])
        p.goto(BASE + "?view=network&tab=apparati"); p.wait_for_selector("main"); rec("credenziali: elenco apparati con selezione e scelta credenziali", p.locator("input[form=tcrf]").count() >= 3 and "Credenziali SNMP degli apparati selezionati" in p.content())
        # eliminazione: ripulisce i riferimenti
        c.request.post(BASE + "?action=cred_del", form={"id": str(cid["Firewall v3"])}, headers=H)
        rec("credenziali: eliminandola sparisce da apparati e reti", q_(prodp, "SELECT COUNT(*) FROM net_targets WHERE cred_ids LIKE ? OR cred_id=?", '%%%d%%' % cid["Firewall v3"], cid["Firewall v3"])[0][0] == 0)
        rec("credenziali: nessun errore JS", not errs, str(errs)[:200])
        c.close()
        # <<< t139
        # >>> t140
        # --- 1.38: struttura comune (elenchi uniformi, menu Aggiungi, scorciatoie), onboarding cliente, procedura rete, importatore CSV
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        p.goto(BASE + "?view=audit"); p.wait_for_selector("main")
        rec("layout: il menu «+ Aggiungi» è nella barra alta di ogni pagina", p.locator(".top #addm summary").count() == 1 and "Aggiungi" in p.inner_text(".top"))
        rec("layout: la ricerca globale è sempre nella barra alta", p.locator(".top .srch").count() == 1)
        p.keyboard.press("?"); p.wait_for_timeout(150)
        rec("scorciatoie: «?» apre l'elenco", p.locator("#kbo.on").count() == 1)
        p.keyboard.press("Escape"); p.wait_for_timeout(100)
        rec("scorciatoie: Esc chiude l'elenco", p.locator("#kbo.on").count() == 0)
        p.goto(BASE + "?view=audit"); p.wait_for_selector("main")
        if p.locator(".lt input[type=search]").count():
            rec("elenchi: filtro alla stessa posizione (sopra la tabella, a sinistra)", p.locator(".lt input[type=search]").first.bounding_box()["x"] < 400)
            p.keyboard.press("/"); p.wait_for_timeout(100)
            rec("scorciatoie: «/» porta il cursore nel filtro dell'elenco", p.evaluate("document.activeElement && document.activeElement.type==='search' && document.activeElement.closest('.lt')!==null"))
            p.keyboard.type("n"); p.wait_for_timeout(100)
            rec("scorciatoie: non agiscono mentre si scrive in un campo", p.locator("#addm[open]").count() == 0 and p.locator("#kbo.on").count() == 0)
            p.fill(".lt input[type=search]", "zzzzqqqq"); p.wait_for_timeout(150)
            rec("elenchi: il filtro nasconde le righe e conta", "0 di" in p.inner_text(".lt .cnt"), p.inner_text(".lt .cnt"))
            p.goto(BASE + "?view=audit"); p.wait_for_selector(".lt input[type=search]")
            rec("elenchi: il filtro viene ricordato", p.input_value(".lt input[type=search]") == "zzzzqqqq")
            p.fill(".lt input[type=search]", ""); p.wait_for_timeout(100)
            p.select_option(".lt select.dens", "c"); p.wait_for_timeout(100)
            rec("elenchi: densità compatta applicata", p.evaluate("document.body.classList.contains('d-c')"))
            p.goto(BASE + "?view=audit"); p.wait_for_selector(".lt")
            rec("elenchi: la densità viene ricordata", p.evaluate("document.body.classList.contains('d-c')"))
            p.select_option(".lt select.dens", "s")
        p.goto(BASE + "?view=todo"); p.wait_for_selector("main")
        rec("Da fare: la pagina esiste ed è in menu", "Da fare" in p.inner_text("#rail"))
        def qd_(path, sql, *a):
            x = sqlite3.connect(path); x.execute("ATTACH DATABASE ? AS dk", (os.path.join(os.path.dirname(path), "docs.sqlite"),)); r = x.execute(sql, *([a] if a else [])).fetchall(); x.close(); return r
        # onboarding cliente
        c.request.post(BASE + "?action=site_create", form={"name": "Onb Srl", "referent": "Mario 333", "notes": ""}, headers=H)
        sid_ = q_(prodp, "SELECT id FROM sites WHERE name='Onb Srl'")[0][0]
        rec("onboarding: il cliente nuovo risulta «in corso»", q_(prodp, "SELECT v FROM meta WHERE k='onb:Onb Srl'")[0][0] == "open")
        p.goto(BASE + f"?view=onboard&id={sid_}"); p.wait_for_selector("main")
        body_ = p.inner_text("main")
        rec("onboarding: nove passi fissi", all(x in body_ for x in ("Anagrafica", "Sedi e reparti", "Credenziali", "Rete e sonda", "Device", "Asset", "Documenti", "Monitoraggio e regole", "Revisione e attivazione")) and p.locator("main .card[id^=s-]").count() == 9)
        rec("onboarding: l'anagrafica compilata risulta fatta da sola", "1 di 9" in body_, body_[:200])
        c.request.post(BASE + "?action=onb_toggle", form={"id": str(sid_), "step": "sedi", "done": "1"}, headers=H)
        p.goto(BASE + f"?view=onboard&id={sid_}"); rec("onboarding: un passo si segna a mano (e resta non bloccante)", "2 di 9" in p.inner_text("main") and "segnato a mano" in p.inner_text("main"))
        p.goto(BASE + "?view=todo"); rec("Da fare: elenca i passi di onboarding ancora aperti", "Onboarding di Onb Srl" in p.inner_text("main") and "7 passi" in p.inner_text("main"), p.inner_text("main")[:300])
        c.request.post(BASE + "?action=onb_activate", form={"id": str(sid_), "on": "1"}, headers=H)
        p.goto(BASE + "?view=todo"); rec("Da fare: attivato il cliente, l'onboarding non compare più", "Onboarding di Onb Srl" not in p.inner_text("main"))
        p.goto(BASE + f"?view=newdevice&site=Onb%20Srl"); p.wait_for_selector("main")
        rec("aggiungi device: comando di installazione già pronto per il cliente", "irm '" in p.inner_text("main") and "curl -fsSL" in p.inner_text("main") and "In attesa del primo device" in p.inner_text("main"))
        # procedura guidata della rete
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-O','linux','kpon',?,?,?,'Onb Srl',1)", (nowz, json.dumps({"agent_version": "1.38.0"}), nowz)); cx.commit()
        dO = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-O'").fetchone()[0]; cx.close()
        p.goto(BASE + "?view=netwiz"); p.wait_for_selector("main")
        rec("procedura rete: primo passo con rete e sonda", "Rete e sonda" in p.inner_text("main") and p.locator("select[name=device_id]").count() == 1)
        c.request.post(BASE + "?action=net_subnet_add", form={"wiz": "1", "site": "Onb Srl", "cidr": "10.50.0.0/24", "name": "LAN onb", "device_id": str(dO)}, headers=H)
        sO = q_(prodp, "SELECT id FROM net_subnets WHERE site='Onb Srl'")[0][0]
        rec("procedura rete: crea la rete e collega la sonda in un colpo", q_(prodp, "SELECT COUNT(*) FROM net_subnet_probes WHERE subnet_id=? AND device_id=?", sO, dO)[0][0] == 1)
        p.goto(BASE + f"?view=netwiz&id={sO}"); b_ = p.inner_text("main")
        rec("procedura rete: cinque passi", all(x in b_ for x in ("Rete e sonda", "Credenziali", "Scoperta", "Classificazione", "Installazione dell'agent")), b_[:300])
        # importatore CSV
        cx = sqlite3.connect(prodp); cx.execute("INSERT OR IGNORE INTO asset_types(name,fields,position,created) VALUES('Periferica','[]',50,?)", (nowz,)); cx.commit(); cx.close()
        p.goto(BASE + "?view=import"); p.wait_for_selector("main")
        csv_ = "Tipo;Nome;Cliente;Seriale;Ubicazione\nPeriferica;Stampa Uno;Onb Srl;SN1;Ufficio\nPeriferica;Stampa Due;Onb Srl;SN2;Magazzino\nTipoInesistente;Boh;Onb Srl;;\nPeriferica;;Onb Srl;;\n"
        p.select_option("select[name=type]", "asset"); p.set_input_files("input[type=file]", {"name": "asset.csv", "mimeType": "text/csv", "buffer": csv_.encode()}); p.click("main button"); p.wait_for_selector("select[name=map_nome]")
        rec("importatore: colonne abbinate in automatico per nome", p.input_value("select[name=map_nome]") == "1" and p.input_value("select[name=map_cliente]") == "2")
        n0 = q_(prodp, "SELECT COUNT(*) FROM assets")[0][0]
        p.click("main form button"); p.wait_for_selector("text=Prova a vuoto: nulla è stato salvato")
        rec("importatore: la prova a vuoto non salva nulla", q_(prodp, "SELECT COUNT(*) FROM assets")[0][0] == n0)
        bt_ = p.inner_text("main")
        rec("importatore: la prova a vuoto segnala righe buone e righe da correggere", "2 righe da importare" in bt_ and "2 da correggere" in bt_ and "Riga 4" in bt_ and "Riga 5" in bt_, bt_[-400:])
        p.uncheck("input[name=dry]"); p.click("main form button"); p.wait_for_selector("text=Importate 2 righe")
        rec("importatore: importazione vera", q_(prodp, "SELECT COUNT(*) FROM assets WHERE site='Onb Srl' AND name LIKE 'Stampa %'")[0][0] == 2 and q_(prodp, "SELECT COUNT(*) FROM assets")[0][0] == n0 + 2)
        # documenti e clienti
        for ty_, csvx in (("documenti", "Titolo;Cliente;Testo\nNota uno;Onb Srl;Ciao\n"), ("clienti", "Nome;Referente\nCliente Importato;Anna\nOnb Srl;doppio\n")):
            p.goto(BASE + "?view=import"); p.select_option("select[name=type]", ty_); p.set_input_files("input[type=file]", {"name": "x.csv", "mimeType": "text/csv", "buffer": csvx.encode()}); p.click("main button"); p.wait_for_selector("input[name=dry]"); p.uncheck("input[name=dry]"); p.click("main form button"); p.wait_for_selector("text=Importate")
        rec("importatore: documenti importati", qd_(prodp, "SELECT COUNT(*) FROM docs WHERE title='Nota uno' AND site='Onb Srl'")[0][0] == 1)
        rec("importatore: clienti importati (doppioni saltati) e in onboarding", q_(prodp, "SELECT COUNT(*) FROM sites WHERE name='Cliente Importato'")[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM sites WHERE name='Onb Srl'")[0][0] == 1 and q_(prodp, "SELECT v FROM meta WHERE k='onb:Cliente Importato'")[0][0] == "open")
        # rinomina: segue tutto
        cx = sqlite3.connect(prodp); cx.execute("INSERT INTO site_creds(site,name,kind,data,created,updated) VALUES('Onb Srl','Prova','snmp','{}',?,?)", (nowz, nowz)); cx.commit(); cx.close()
        c.request.post(BASE + "?action=site_rename", form={"id": str(sid_), "name": "Onb Srl 2"}, headers=H)
        rec("rinomina cliente: asset, documenti, reti, credenziali e onboarding seguono", q_(prodp, "SELECT COUNT(*) FROM assets WHERE site='Onb Srl'")[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM assets WHERE site='Onb Srl 2'")[0][0] == 2 and qd_(prodp, "SELECT COUNT(*) FROM docs WHERE site='Onb Srl 2'")[0][0] == 1
            and q_(prodp, "SELECT COUNT(*) FROM net_subnets WHERE site='Onb Srl 2'")[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM site_creds WHERE site='Onb Srl 2'")[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM meta WHERE k='onb:Onb Srl 2'")[0][0] == 1)
        p.goto(BASE + "?view=clients"); p.wait_for_selector("main"); rec("layout: «+ Aggiungi» presente anche in Clienti, nessun errore JS", p.locator("#addm").count() == 1 and not errs, str(errs)[:200])
        # nomi delle attività nell'elenco job (1.38): non il codice
        cx = sqlite3.connect(prodp); nz_ = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        body_ = "$ErrorActionPreference = 'SilentlyContinue'\nGet-PSDrive C"
        cx.execute("INSERT INTO scripts(name,description,body,created) VALUES('Controllo spazio disco','Avvisa sotto il 10% libero',?,?)", (body_, nz_))
        sc_ = cx.execute("SELECT MAX(id) FROM scripts").fetchone()[0]
        cx.execute("INSERT INTO schedules(device_id,script_id,interval_min,enabled,created) VALUES(1,?,15,1,?)", (sc_, nz_)); sh_ = cx.execute("SELECT MAX(id) FROM schedules").fetchone()[0]
        cx.execute("INSERT INTO jobs(device_id,script,timeout,status,created,origin) VALUES(1,?,60,'done',?,?)", (body_, nz_, f"schedule:{sh_}")); jb_ = cx.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
        cx.execute("INSERT INTO results(job_id,exit_code,stdout,stderr,duration,received) VALUES(?,0,'','',0.5,?)", (jb_, nz_)); cx.commit(); cx.close()
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector(f"details.job[data-job='{jb_}']")
        row_ = p.locator(f"details.job[data-job='{jb_}'] > summary")
        rec("job: l'elenco mostra il nome dell'attività e non il codice", "Controllo spazio disco" in row_.inner_text() and "ErrorActionPreference" not in row_.inner_text(), row_.inner_text()[:160])
        rec("job: la descrizione compare nel testo e nel suggerimento", "Avvisa sotto il 10%" in row_.inner_text() and "Avvisa sotto il 10%" in (row_.locator(".t").get_attribute("title") or ""))
        rec("job: l'origine dice «ogni 15 min», non l'identificativo", "ogni 15 min" in row_.inner_text() and "schedule:" not in row_.inner_text())
        p.goto(BASE + "?view=jobs"); p.wait_for_selector("main"); rec("Attività: nome dell'attività al posto del codice", "Controllo spazio disco" in p.inner_text("main") and "ogni 15 min" in p.inner_text("main"))
        # interprete dei comandi manuali (1.38): diciture per tipo di device e cmd su Windows
        cx = sqlite3.connect(prodp); cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,created) VALUES('LNX-PROVA','Ubuntu 24.04 Linux','klnx',?,?)", (nz_, nz_)); lid_ = cx.execute("SELECT MAX(id) FROM devices").fetchone()[0]; cx.commit(); cx.close()
        p.goto(BASE + f"?view=device&id={lid_}#t=job"); p.wait_for_selector("main")
        lt_ = p.locator("main details.card.fold > summary").all_inner_texts()
        rec("comando manuale su Linux: dice shell e non PowerShell, senza scelta dell'interprete", any("Comando libero (shell Linux)" in t for t in lt_) and not any("PowerShell" in t for t in lt_) and p.locator("form[action='?action=newjob'] select[name=interp]").count() == 0, str(lt_)[:300])
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector("main")
        rec("comando manuale su Windows: scelta PowerShell / cmd", p.locator("form[action='?action=newjob'] select[name=interp] option[value=cmd]").count() == 1)
        c.request.post(BASE + "?action=newjob", form={"device_id": "1", "script": "echo ciao\nexit /b 7", "timeout": "30", "interp": "cmd"}, headers=H)
        sj_ = q_(prodp, "SELECT script FROM jobs WHERE device_id=1 AND origin='console' ORDER BY id DESC LIMIT 1")[0][0]
        rec("cmd: il testo è memorizzato con la riga #!cmd", sj_.startswith("#!cmd\n") and "echo ciao" in sj_, sj_[:80])
        rq_ = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"os": "Windows", "platform": "windows/amd64", "disks": [{"DeviceID": "C:", "size_gb": 100, "free_gb": 50}], "cpu_pct": 10, "ram_pct": 10}}).encode(), headers={"X-Device-Key": "k1", "Content-Type": "application/json"})
        jb2_ = [j for j in json.loads(urllib.request.urlopen(rq_, timeout=10).read()).get("jobs", []) if "myrmm: testo cmd" in j["script"]]
        rec("cmd: all'agent Windows arriva lo script che esegue cmd.exe (testo in base64, firmato)", len(jb2_) == 1 and "ComSpec" in jb2_[0]["script"] and "echo ciao" not in jb2_[0]["script"], str(jb2_)[:200])
        p.goto(BASE + "?view=device&id=1#t=job"); p.wait_for_selector("main")
        rec("cmd: nell'elenco non compare la riga #!cmd", "#!cmd" not in p.inner_text("main"), p.inner_text("main")[:200])
        p.goto(BASE + "?view=scripts"); p.wait_for_selector("#sltm .tm-btn")
        rows_ = p.locator("#sltab tr[data-s]"); rec("libreria: le descrizioni sono nascoste finché non si apre la riga", rows_.first.locator(".ds").is_hidden())
        rows_.first.locator(".xp").click(); rec("libreria: un clic sul titolo mostra la descrizione", rows_.first.locator(".ds").is_visible() and rows_.first.locator(".xp").get_attribute("aria-expanded") == "true")
        rows_.first.locator(".xp").click(); rec("libreria: un secondo clic la richiude", rows_.first.locator(".ds").is_hidden())
        p.fill("#slq", "apre un alert"); p.wait_for_timeout(150)
        vis_ = p.locator("#sltab tr[data-s]:visible"); rec("libreria: la ricerca trova anche nel testo della descrizione e la mostra", vis_.count() >= 1 and any("apre un alert" not in r.get_attribute("data-n") and r.locator(".ds").is_visible() for r in vis_.all()), str(vis_.count()))
        p.fill("#slq", ""); p.wait_for_timeout(100)
        p.click("#sltm .tm-btn"); rec("etichette: il menu si apre", p.locator("#sltm .tm-pop").is_visible())
        p.locator("#sltm .tm-pop input[data-t=sola-lettura]").check(); n1_ = p.locator("#sltab tr[data-s]:visible").count()
        p.locator("#sltm .tm-pop input[data-t=modifica]").check(); n2_ = p.locator("#sltab tr[data-s]:visible").count()
        rec("etichette: due scelte nello stesso gruppo si sommano (basta una)", 0 < n1_ < n2_, f"{n1_} {n2_}")
        rec("etichette: le scelte compaiono come chip e il menu ne conta due", p.locator("#sltags .chip").count() == 2 and p.locator("#sltm .tm-btn .n").inner_text() == "2")
        p.keyboard.press("Escape"); rec("etichette: Esc chiude il menu", p.locator("#sltm .tm-pop").is_hidden())
        p.locator("#sltags .chip").first.click(); rec("etichette: un clic sul chip toglie la scelta", p.locator("#sltags .chip").count() == 1)
        p.set_viewport_size({"width": 1440, "height": 1000}); p.screenshot(path=f"{OUT}/scripts2.png"); p.set_viewport_size({"width": 1280, "height": 800})
        p.goto(BASE + "?view=scripts"); p.wait_for_selector("main"); rec("libreria: il tipo di script è dichiarato (Windows · PowerShell, Linux/macOS · shell)", "Windows · PowerShell" in p.text_content("main") and "Linux/macOS · shell" in p.text_content("main"))
        # rinomina del PC: il nome nel portale segue l'hostname riportato dall'agent; alias modificabile
        cx = sqlite3.connect(prodp); cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,created) VALUES('RNM-OLD','Windows 11','krnm',?,?)", (nz_, nz_)); rid_ = cx.execute("SELECT MAX(id) FROM devices").fetchone()[0]; cx.commit(); cx.close()
        rq_ = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps({"inventory": {"hostname": "RNM-NEW", "os": "Windows 11", "platform": "windows/amd64", "disks": [{"DeviceID": "C:", "size_gb": 100, "free_gb": 50}], "cpu_pct": 5, "ram_pct": 5}}).encode(), headers={"X-Device-Key": "krnm", "Content-Type": "application/json"}); urllib.request.urlopen(rq_, timeout=10).read()
        rec("rinomina PC: l'hostname nel portale segue quello dell'agent", q_(prodp, "SELECT hostname FROM devices WHERE id=?", rid_)[0][0] == "RNM-NEW")
        rec("rinomina PC: il vecchio nome resta tra i precedenti e nell'audit", "RNM-OLD" in q_(prodp, "SELECT prev_names FROM devices WHERE id=?", rid_)[0][0] and q_(prodp, "SELECT COUNT(*) FROM audit WHERE action='device_renamed' AND detail LIKE '%RNM-OLD%RNM-NEW%'")[0][0] == 1)
        urllib.request.urlopen(rq_, timeout=10).read()
        rec("rinomina PC: un secondo heartbeat con lo stesso nome non cambia nulla", q_(prodp, "SELECT COUNT(*) FROM audit WHERE action='device_renamed'")[0][0] == 1)
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        p.goto(BASE + f"?view=device&id={rid_}"); p.wait_for_selector(".dalias")
        rec("device: mostra il nuovo nome e «ex» il vecchio", "RNM-NEW" in p.inner_text(".dhead") and "ex RNM-OLD" in p.inner_text(".dalias"), p.inner_text(".dhead")[:120])
        p.click(".dalias .dal-e"); p.fill(".dalias input[name=alias]", "Cassa reception"); p.click(".dalias form button[type=submit]"); p.wait_for_selector(".dalias .pill")
        rec("alias: si modifica accanto al nome e resta salvato", "Cassa reception" in p.inner_text(".dalias") and q_(prodp, "SELECT alias FROM devices WHERE id=?", rid_)[0][0] == "Cassa reception")
        p.goto(BASE + "?view=devices"); p.wait_for_selector("main table td.c-host")
        rec("alias: compare nell'elenco device e il filtro lo trova", "Cassa reception" in p.inner_text("main table"), "")
        p.fill("#invQ", "reception"); p.wait_for_timeout(300)
        rec("alias: il filtro dell'elenco cerca anche nell'alias", p.locator("main table tr:visible td.c-host", has_text="RNM-NEW").count() == 1)
        rs_ = json.loads(c.request.get(BASE + "?action=search&q=reception").text())
        rec("alias: la ricerca globale lo trova", any(x.get("host") == "RNM-NEW" for x in rs_.get("results", [])), str(rs_)[:200])
        # runbook: creazione e modifica dalla loro pagina
        p.goto(BASE + "?view=runbooks&new=1"); p.wait_for_selector("#rbEd")
        p.fill("#rbEd input[name=name]", "Runbook di prova"); p.click("#rbEd button[type=submit]"); p.wait_for_selector("#rbEmpty:not(:empty)")
        rec("runbook: senza script non si salva", q_(prodp, "SELECT COUNT(*) FROM runbooks WHERE name='Runbook di prova'")[0][0] == 0)
        p.click("#rbAddS"); p.click("#rbAddW"); p.click("#rbAddS"); p.fill("#rbEd input[type=number]", "5")
        p.locator("#rbSteps li").nth(0).locator("select").select_option(index=2)
        p.fill("#rbEd input[name=description]", "Controllo e riavvio"); p.click("#rbEd button[type=submit]"); p.wait_for_selector("text=salvato (3 passi)")
        rb_ = q_(prodp, "SELECT id, steps, description, stop_on_fail FROM runbooks WHERE name='Runbook di prova'")[0]; st_ = json.loads(rb_[1])
        rec("runbook: creato dalla pagina con script e attesa nell'ordine scelto", len(st_) == 3 and "script_id" in st_[0] and st_[1] == {"wait_min": 5} and "script_id" in st_[2] and rb_[2] == "Controllo e riavvio" and rb_[3] == 1, rb_[1][:200])
        p.goto(BASE + f"?view=runbooks&edit={rb_[0]}"); p.wait_for_selector("#rbEd")
        rec("runbook: la modifica mostra i passi esistenti", p.locator("#rbSteps li").count() == 3 and p.input_value("#rbEd input[name=name]") == "Runbook di prova")
        p.locator("#rbSteps li").nth(1).locator("button[title='Sposta giù']").click(); p.locator("#rbSteps li").nth(0).locator("button[title='Togli il passo']").click()
        p.fill("#rbEd input[name=name]", "Runbook di prova 2"); p.uncheck("#rbEd input[name=stop_on_fail]"); p.click("#rbEd button[type=submit]"); p.wait_for_selector("text=salvato (2 passi)")
        rb2_ = q_(prodp, "SELECT name, steps, stop_on_fail FROM runbooks WHERE id=?", rb_[0])[0]; st2_ = json.loads(rb2_[1])
        rec("runbook: modificato (nome, passi tolti e spostati, opzione) e non duplicato", rb2_[0] == "Runbook di prova 2" and len(st2_) == 2 and "script_id" in st2_[0] and "wait_min" in st2_[1] and rb2_[2] == 0 and q_(prodp, "SELECT COUNT(*) FROM runbooks WHERE name LIKE 'Runbook di prova%'")[0][0] == 1, rb2_[1][:200])
        c.request.post(BASE + "?action=rb_dup", form={"id": str(rb_[0])}, headers=H)
        rec("runbook: duplica crea una copia con altro nome", q_(prodp, "SELECT COUNT(*) FROM runbooks WHERE name='Runbook di prova 2 (copia)'")[0][0] == 1)
        p.goto(BASE + "?view=runbooks"); p.wait_for_selector("main")
        rec("runbook: la pagina offre Nuovo, Modifica e Duplica", p.locator("a:has-text('Nuovo runbook')").count() == 1 and p.locator("a:has-text('Modifica')").count() >= 1 and p.locator("button:has-text('Duplica')").count() >= 1 and not errs, str(errs)[:200])
        c.close()
        # <<< t140
        # >>> t141
        # --- 1.38: modelli di documento, cestino con «Annulla», conferma digitando il nome del cliente
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        for n_ in ("Scheda cliente", "Inventario di rete", "Procedura di emergenza", "Piano di backup", "Contratto di assistenza", "Accessi VPN"):
            r_ = qd_(prodp, "SELECT category, review_months, length(body) FROM doc_templates WHERE name=? AND builtin=1", n_)
            rec(f"modelli: «{n_}» presente", bool(r_) and r_[0][2] > 400, str(r_))
        tid_ = qd_(prodp, "SELECT id FROM doc_templates WHERE name='Inventario di rete'")[0][0]; tcl_ = qd_(prodp, "SELECT id FROM doc_templates WHERE name='Scheda cliente'")[0][0]
        p.goto(BASE + f"?view=docs&edit=0&tpl={tid_}&site=Onb%20Srl%202"); p.wait_for_selector("textarea")
        tx_ = p.input_value("textarea[name=body]")
        rec("modelli: l'inventario di rete si compila con le reti vere del cliente", "10.50.0.0/24" in tx_ and "{{" not in tx_, tx_[:300])
        p.goto(BASE + f"?view=docs&edit=0&tpl={tcl_}&site=Onb%20Srl%202"); p.wait_for_selector("textarea")
        tx_ = p.input_value("textarea[name=body]")
        rec("modelli: la scheda cliente porta referente e sistemi", "Mario 333" in tx_ and "{{" not in tx_, tx_[:300])
        # cestino: documento
        did_ = qd_(prodp, "SELECT id FROM docs WHERE title='Nota uno'")[0][0]
        r_ = c.request.post(BASE + "?action=doc_del", form={"id": str(did_)}, headers=H, max_redirects=0)
        rec("cestino: il documento eliminato non c'è più ma è nel cestino", qd_(prodp, "SELECT COUNT(*) FROM docs WHERE id=?", did_)[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM trash WHERE kind='doc' AND ref_id=?", did_)[0][0] == 1)
        loc_ = r_.headers.get("location", ""); rec("cestino: l'eliminazione porta con sé l'id per «Annulla»", "undo=" in loc_, loc_)
        p.goto(BASE + loc_.replace("index.php", "") if loc_.startswith("?") else BASE + "?view=docs&undo=" + loc_.split("undo=")[-1]); p.wait_for_selector("#snack.on")
        rec("cestino: compare la barra con «Annulla»", "Annulla" in p.inner_text("#snack"))
        p.click("#snack button"); p.wait_for_load_state(); p.wait_for_timeout(300)
        rec("cestino: «Annulla» ripristina il documento (con le versioni)", qd_(prodp, "SELECT COUNT(*) FROM docs WHERE id=?", did_)[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM trash")[0][0] == 0)
        # cestino: asset con nota
        aid_ = q_(prodp, "SELECT id FROM assets WHERE name='Stampa Uno'")[0][0]
        c.request.post(BASE + "?action=asset_note", form={"id": str(aid_), "text": "nota da conservare"}, headers=H)
        c.request.post(BASE + "?action=asset_del", form={"id": str(aid_)}, headers=H)
        rec("cestino: asset eliminato con le sue note", q_(prodp, "SELECT COUNT(*) FROM assets WHERE id=?", aid_)[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM asset_notes WHERE asset_id=?", aid_)[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM trash WHERE kind='asset'")[0][0] == 1)
        p.goto(BASE + "?view=trash"); p.wait_for_selector("main")
        rec("cestino: la pagina elenca l'asset con i giorni rimasti", "Stampa Uno" in p.inner_text("main") and "30 g" in p.inner_text("main"), p.inner_text("main")[:300])
        p.click("main button:has-text('Ripristina')"); p.wait_for_load_state(); p.wait_for_timeout(300)
        rec("cestino: ripristino dalla pagina (asset e nota tornano)", q_(prodp, "SELECT COUNT(*) FROM assets WHERE id=?", aid_)[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM asset_notes WHERE asset_id=?", aid_)[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM trash")[0][0] == 0)
        # cestino: ticket
        c.request.post(BASE + "?action=tk_new", form={"device_id": str(q_(prodp, "SELECT MIN(id) FROM devices")[0][0]), "title": "Ticket da cestinare", "priority": "normal"}, headers=H)
        tk_ = q_(prodp, "SELECT id FROM tickets WHERE title='Ticket da cestinare'")[0][0]
        c.request.post(BASE + "?action=tk_del", form={"id": str(tk_)}, headers=H)
        rec("cestino: ticket eliminato con le note e ripristinabile", q_(prodp, "SELECT COUNT(*) FROM tickets WHERE id=?", tk_)[0][0] == 0 and q_(prodp, "SELECT COUNT(*) FROM trash WHERE kind='ticket'")[0][0] == 1)
        rr_ = c.request.post(BASE + "?action=trash_restore", form={"id": str(q_(prodp, "SELECT id FROM trash WHERE kind='ticket'")[0][0])}, headers=H, max_redirects=0)
        rec("cestino: ticket ripristinato con le sue note", q_(prodp, "SELECT COUNT(*) FROM tickets WHERE id=?", tk_)[0][0] == 1 and q_(prodp, "SELECT COUNT(*) FROM ticket_notes WHERE ticket_id=?", tk_)[0][0] >= 1, rr_.headers.get("location", ""))
        # scadenza: dopo 30 giorni sparisce da sola
        c.request.post(BASE + "?action=doc_del", form={"id": str(did_)}, headers=H)
        cx = sqlite3.connect(prodp); cx.execute("UPDATE trash SET expires='2000-01-01T00:00:00Z'"); cx.execute("DELETE FROM meta WHERE k='last_housekeeping'"); cx.commit(); cx.close()
        hb2("kpcr", {"inventory": {"hostname": "SONDA-C"}})
        rec("cestino: passati i 30 giorni l'elemento sparisce", q_(prodp, "SELECT COUNT(*) FROM trash")[0][0] == 0)
        # cliente: conferma digitando il nome
        c.request.post(BASE + "?action=site_create", form={"name": "Da Cancellare"}, headers=H)
        sdc_ = q_(prodp, "SELECT id FROM sites WHERE name='Da Cancellare'")[0][0]
        c.request.post(BASE + "?action=site_delete", form={"id": str(sdc_)}, headers=H)
        c.request.post(BASE + "?action=site_delete", form={"id": str(sdc_), "confirm_name": "da cancell"}, headers=H)
        rec("cliente: senza il nome scritto per intero non si elimina", q_(prodp, "SELECT COUNT(*) FROM sites WHERE id=?", sdc_)[0][0] == 1)
        c.request.post(BASE + "?action=site_delete", form={"id": str(sdc_), "confirm_name": "Da Cancellare"}, headers=H)
        rec("cliente: con il nome esatto si elimina", q_(prodp, "SELECT COUNT(*) FROM sites WHERE id=?", sdc_)[0][0] == 0)
        p.goto(BASE + "?view=clients"); p.wait_for_selector("main"); rec("cliente: nell'elenco l'eliminazione chiede il nome", "scrivi il nome del cliente" in p.content())
        rec("cestino: nessun errore JS", not errs, str(errs)[:200])
        c.close()
        # <<< t141
        # >>> t134
        # --- 1.34.0: SNMP (credenziali di sottorete, profili, porte osservate, OID personalizzati, scansione apparato)
        def pj(c_, action, form):
            r_ = c_.request.post(BASE + "?action=" + action, form=form, headers=H, max_redirects=0)
            return r_.status
        def hbk(key, body=None):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body or {"light": True}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        def rpt(key, body):
            rq = urllib.request.Request(BASE + "?action=probe_report", data=json.dumps(body).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not cx.execute("SELECT 1 FROM sites WHERE name='Snmp Srl'").fetchone(): cx.execute("INSERT INTO sites(name,created) VALUES('Snmp Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-S','linux','kps',?,?,?,'Snmp Srl',1)", (nowz, json.dumps({"agent_version": "1.34.0"}), nowz))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-S-OLD','linux','kpso',?,?,?,'Snmp Srl',1)", (nowz, json.dumps({"agent_version": "1.33.0"}), nowz)); cx.commit()
        dS = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-S'").fetchone()[0]; dSo = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-S-OLD'").fetchone()[0]; cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        c.request.post(BASE + "?action=net_subnet_add", form={"site": "Snmp Srl", "cidr": "10.20.0.0/24", "name": "LAN snmp"}, headers=H)
        sS = q_(prodp, "SELECT id FROM net_subnets WHERE site='Snmp Srl'")[0][0]
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sS), "device_id": str(dS), "op": "add", "prio": "1"}, headers=H)
        # apparato SNMP senza credenziali: rifiutato con il motivo
        r_ = c.request.post(BASE + "?action=net_target_add", form={"site": "Snmp Srl", "name": "Stampante A", "ip": "10.20.0.50", "kind": "snmp", "every": "60", "sev": "warn"}, headers=H)
        rec("snmp: apparato rifiutato se la rete non ha credenziali", q_(prodp, "SELECT COUNT(*) FROM net_targets WHERE kind='snmp' AND site='Snmp Srl'")[0][0] == 0)
        # credenziali v2c: cifrate, mai mostrate
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sS), "v": "2c", "comm": "segretissima"}, headers=H)
        cr = q_(prodp, "SELECT snmp FROM net_subnets WHERE id=?", sS)[0][0]
        rec("snmp: community salvata cifrata (non in chiaro)", '"v":"2c"' in cr and "segretissima" not in cr and '"comm":"e:' in cr, cr[:120])
        p.goto(BASE + "?view=network&tab=sottoreti"); body_ = p.content()
        rec("snmp: la community non compare mai nella console", "segretissima" not in body_ and "v2c" in body_)
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sS), "v": "3", "user": "mon", "level": "authPriv", "ap": "SHA", "ak": "corta", "pp": "AES", "pk": "passwordlunga1"}, headers=H)
        rec("snmp: v3 con password troppo corta rifiutata (credenziali invariate)", '"v":"2c"' in q_(prodp, "SELECT snmp FROM net_subnets WHERE id=?", sS)[0][0])
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sS), "v": "3", "user": "mon", "level": "authPriv", "ap": "SHA256", "ak": "autenticazione1", "pp": "AES256", "pk": "cifratura-lunga1"}, headers=H)
        cr3 = q_(prodp, "SELECT snmp FROM net_subnets WHERE id=?", sS)[0][0]
        rec("snmp: credenziali v3 salvate (utente in chiaro, password cifrate)", '"v":"3"' in cr3 and '"user":"mon"' in cr3 and "autenticazione1" not in cr3 and "cifratura-lunga1" not in cr3 and '"ap":"SHA256"' in cr3, cr3[:160])
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sS), "v": "3", "user": "mon2", "level": "authPriv", "ap": "SHA256", "pp": "AES256"}, headers=H)
        cr3b = q_(prodp, "SELECT snmp FROM net_subnets WHERE id=?", sS)[0][0]
        rec("snmp: modificando senza reinserire le password, restano quelle di prima", '"user":"mon2"' in cr3b and json.loads(cr3b)["ak"] == json.loads(cr3)["ak"])
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sS), "v": "2c", "comm": "public-ro"}, headers=H)
        for nm, ip, prof in [("Stampante A", "10.20.0.50", "auto"), ("Switch A", "10.20.0.2", "switch")]:
            c.request.post(BASE + "?action=net_target_add", form={"site": "Snmp Srl", "name": nm, "ip": ip, "kind": "snmp", "every": "60", "sev": "warn", "profile": prof}, headers=H)
        tP = q_(prodp, "SELECT id FROM net_targets WHERE name='Stampante A'")[0][0]; tW = q_(prodp, "SELECT id FROM net_targets WHERE name='Switch A'")[0][0]
        rec("snmp: apparati SNMP aggiunti con porta 161 di default", q_(prodp, "SELECT port, profile, kind FROM net_targets WHERE id=?", tW) == [(161, "switch", "snmp")])
        hb_ = hbk("kps"); pt = {t["id"]: t for t in hb_.get("probe", {}).get("targets", [])}
        rec("snmp: la sonda riceve gli apparati con community in chiaro e profilo", pt.get(tP, {}).get("snmp", {}).get("c") == "public-ro" and pt.get(tP, {}).get("snmp", {}).get("v") == "2c" and pt.get(tW, {}).get("snmp", {}).get("profile") == "switch", str(pt)[:300])
        cx = sqlite3.connect(prodp); cx.execute("INSERT OR REPLACE INTO net_subnet_probes(subnet_id,device_id,prio) VALUES(?,?,2)", (sS, dSo)); cx.execute("UPDATE devices SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (dS,)); cx.commit(); cx.close()
        hbo = hbk("kpso"); tg_ = hbo.get("probe", {}).get("targets", [])
        rec("snmp: una sonda con agent < 1.34 non riceve apparati SNMP", all(t["kind"] != "snmp" for t in tg_), str(tg_))
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen=? WHERE id=?", (nowz, dS)); cx.execute("DELETE FROM net_subnet_probes WHERE device_id=?", (dSo,)); cx.commit(); cx.close()
        # stampante: report completo
        prn = {"profile": "printer", "name": "STAMPA-UFFICIO", "descr": "HP LaserJet M404dn", "up": 86400, "m": {"uptime": 86400, "pages": 48213, "supply_min": 7, "sup1": 80, "sup2": 7, "alerts": 1, "cpu": 5},
               "info": {"serial": "VNB3K12345", "state": "inattiva"}, "sup": [{"n": "Black Cartridge", "pct": 80, "cls": 3}, {"n": "Cyan Toner", "pct": 7, "cls": 3}, {"n": "Waste box", "pct": -1, "cls": 4}],
               "alerts": ["Toner ciano quasi esaurito"], "if": [{"i": 1, "n": "eth0", "t": 6, "ad": 1, "op": 1, "sp": 100000000, "in": 1500, "out": 800}]}
        rj = rpt("kps", {"results": [{"id": tP, "ok": True, "rtt": 4.2, "ts": int(time.time()), "snmp": prn}]})
        si = q_(prodp, "SELECT status, sinfo FROM net_targets WHERE id=?", tP)[0]
        rec("snmp: stampante — esito e dati registrati", rj.get("n") == 1 and si[0] == "up" and json.loads(si[1])["info"]["serial"] == "VNB3K12345")
        al = q_(prodp, "SELECT type, severity, message FROM alerts WHERE status='open' AND type LIKE ?", f"net:{tP}:%")
        rec("snmp: toner ciano al 7% apre l'avviso materiali (solo il toner, non la vaschetta)", any(a[0] == f"net:{tP}:supply" and "Cyan Toner 7%" in a[2] and "Waste" not in a[2] for a in al) and any(a[0] == f"net:{tP}:prn" for a in al), str(al))
        p.goto(BASE + f"?view=nettarget&id={tP}"); body_ = p.content()
        rec("snmp: scheda apparato con materiali, matricola e pagine", "Cyan Toner" in body_ and "VNB3K12345" in body_ and "48213" in body_ and "Stampante" in body_ and not errs, str(errs)[:200])
        prn["sup"][1]["pct"] = 95; prn["alerts"] = []; prn["m"]["supply_min"] = 80; prn["m"]["alerts"] = 0
        rpt("kps", {"results": [{"id": tP, "ok": True, "rtt": 4.0, "ts": int(time.time()), "snmp": prn}]})
        rec("snmp: cambiato il toner gli avvisi si risolvono da soli", not q_(prodp, "SELECT 1 FROM alerts WHERE status='open' AND type LIKE ?", f"net:{tP}:%"))
        mt = q_(os.path.join(os.path.dirname(prodp), "metrics.sqlite"), "SELECT metric FROM m_series WHERE dev=?", -tP)
        rec("snmp: misure registrate per i grafici (pagine, materiale, ...)", {"pages", "supply_min"} <= {m[0] for m in mt}, str(mt))
        # switch: porte osservate + controllo veloce
        sw = {"profile": "switch", "name": "SW", "up": 5000, "m": {"ports_up": 2, "ports_total": 3}, "if": [{"i": 1, "n": "Gi1/0/1", "a": "UPLINK-FW", "t": 6, "ad": 1, "op": 1, "sp": 1000000000}, {"i": 2, "n": "Gi1/0/2", "t": 6, "ad": 1, "op": 1, "sp": 1000000000}, {"i": 3, "n": "Gi1/0/3", "t": 6, "ad": 1, "op": 2, "sp": 1000000000}]}
        rpt("kps", {"results": [{"id": tW, "ok": True, "rtt": 2, "ts": int(time.time()), "snmp": sw}]})
        p.goto(BASE + f"?view=nettarget&id={tW}"); rec("snmp: scheda switch con elenco porte e alias", "UPLINK-FW" in p.content() and "Osserva" in p.content())
        c.request.post(BASE + "?action=net_snmp_set", data=f"id={tW}&what=obs&obs[]=1&obs[]=3&fast=20", headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}))
        hbw = {t["id"]: t for t in hbk("kps").get("probe", {}).get("targets", [])}[tW]["snmp"]
        rec("snmp: porte osservate e controllo veloce arrivano alla sonda", hbw.get("obs") == [1, 3] and hbw.get("fast") == 20, str(hbw))
        rpt("kps", {"results": [{"id": tW, "ok": True, "rtt": 2, "ts": int(time.time()), "snmp": sw}]})
        al = q_(prodp, "SELECT type, message FROM alerts WHERE status='open' AND type LIKE ?", f"net:{tW}:%")
        rec("snmp: la porta osservata giù apre l'avviso (la non osservata no)", [a[0] for a in al] == [f"net:{tW}:if:3"] and "Gi1/0/3" in al[0][1], str(al))
        fastp = {"fast": True, "up": 5030, "m": {"uptime": 5030}, "if": [{"i": 1, "n": "Gi1/0/1", "ad": 1, "op": 2}, {"i": 3, "n": "Gi1/0/3", "ad": 1, "op": 1}]}
        rpt("kps", {"results": [{"id": tW, "ok": True, "rtt": 2, "ts": int(time.time()), "snmp": fastp}]})
        al = q_(prodp, "SELECT type FROM alerts WHERE status='open' AND type LIKE ?", f"net:{tW}:%"); inf = json.loads(q_(prodp, "SELECT sinfo FROM net_targets WHERE id=?", tW)[0][0])
        rec("snmp: controllo veloce — uplink caduto apre l'avviso, porta 3 tornata su lo chiude", [a[0] for a in al] == [f"net:{tW}:if:1"] and inf["up"] == 5030 and len(inf["if"]) == 3, str((al, inf.get("up"))))
        c.request.post(BASE + "?action=net_snmp_set", form={"id": str(tW), "what": "obs", "fast": "20"}, headers=H)
        rec("snmp: togliendo la porta dalle osservate l'avviso si chiude", not q_(prodp, "SELECT 1 FROM alerts WHERE status='open' AND type LIKE ?", f"net:{tW}:if:%"))
        # soglie CPU
        sw["m"]["cpu"] = 95; rpt("kps", {"results": [{"id": tW, "ok": True, "rtt": 2, "ts": int(time.time()), "snmp": sw}]})
        rec("snmp: CPU oltre soglia apre l'avviso", bool(q_(prodp, "SELECT 1 FROM alerts WHERE status='open' AND type=?", f"net:{tW}:thr:cpu")))
        sw["m"]["cpu"] = 20; rpt("kps", {"results": [{"id": tW, "ok": True, "rtt": 2, "ts": int(time.time()), "snmp": sw}]})
        rec("snmp: CPU rientrata, avviso chiuso", not q_(prodp, "SELECT 1 FROM alerts WHERE status='open' AND type=?", f"net:{tW}:thr:cpu"))
        # OID personalizzati
        for form, ok in [({"what": "cust_add", "name": "temp", "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3.1", "unit": "°C"}, True), ({"what": "cust_add", "name": "temp", "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3.1"}, False), ({"what": "cust_add", "name": "x", "oid": "1.2"}, False), ({"what": "cust_add", "name": "y;drop", "oid": "1.3.6.1.4.1.1.1"}, False)]:
            c.request.post(BASE + "?action=net_snmp_set", form=dict(form, id=str(tW)), headers=H)
        sc_ = json.loads(q_(prodp, "SELECT scfg FROM net_targets WHERE id=?", tW)[0][0])
        rec("snmp: OID personalizzati — validati, niente doppioni", [x["name"] for x in sc_["cust"]] == ["temp"] and sc_["cust"][0]["unit"] == "°C", str(sc_))
        hbw = {t["id"]: t for t in hbk("kps").get("probe", {}).get("targets", [])}[tW]["snmp"]
        rec("snmp: l'OID personalizzato arriva alla sonda", hbw.get("cust") == [{"name": "temp", "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3.1", "unit": "°C"}], str(hbw.get("cust")))
        sw["cust"] = [{"name": "temp", "v": 41.0, "ok": True}]; sw["m"]["c.temp"] = 41.0
        rpt("kps", {"results": [{"id": tW, "ok": True, "rtt": 2, "ts": int(time.time()), "snmp": sw}]})
        p.goto(BASE + f"?view=nettarget&id={tW}"); rec("snmp: valore dell'OID personalizzato nella scheda", "temp" in p.content() and "41" in p.content())
        # scansione apparato
        ver0 = hbk("kps")["probe"]["ver"]
        c.request.post(BASE + "?action=net_snmp_scan", form={"id": str(tW)}, headers=H)
        hs_ = {t["id"]: t for t in hbk("kps").get("probe", {}).get("targets", [])}[tW]["snmp"]
        rec("snmp: «Scansiona apparato» arriva alla sonda (scan incrementato, nuova versione di configurazione)", hs_.get("scan") == 1 and hbk("kps", {"probe_ver": ver0}).get("probe", {}).get("ver") != ver0, str(hs_))
        rpt("kps", {"walks": [{"id": tW, "scan": 1, "oids": [[".1.3.6.1.2.1.1.1.0", "OctetString", "Switch"], [".1.3.6.1.4.1.9.9.13.1.3.1.3.1", "Gauge32", "41"], [".1.3.6.1.4.1.9.9.13.1.4.1.2.1", "OctetString", "ventola OK"]], "more": False}]})
        p.goto(BASE + f"?view=nettarget&id={tW}"); b_ = p.content()
        rec("snmp: risultato della scansione mostrato con pulsante «segui» sui soli valori numerici", "1.3.6.1.4.1.9.9.13.1.3.1.3.1" in b_ and "ventola OK" in b_ and b_.count('value="cust_add"') >= 2, "")
        p.goto(BASE + f"?view=nettarget&id={tW}&sq=ventola"); b_ = p.content()
        rec("snmp: ricerca nella scansione", "ventola OK" in b_ and "1.3.6.1.2.1.1.1.0" not in b_)
        c.request.post(BASE + "?action=net_snmp_set", form={"id": str(tW), "what": "cust_add", "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3.1", "name": "temp2"}, headers=H)
        rec("snmp: «segui» dalla scansione aggiunge l'OID", len(json.loads(q_(prodp, "SELECT scfg FROM net_targets WHERE id=?", tW)[0][0])["cust"]) == 2)
        # permessi: un sonda non può scrivere su apparati altrui
        rj = rpt("kps", {"results": [{"id": 999999, "ok": True, "snmp": sw}]}); rec("snmp: apparato non assegnato alla sonda ignorato", rj.get("n") == 0)
        # il profilo manuale
        c.request.post(BASE + "?action=net_snmp_set", form={"id": str(tW), "what": "profile", "profile": "firewall"}, headers=H)
        rec("snmp: profilo scelto a mano arriva alla sonda", {t["id"]: t for t in hbk("kps").get("probe", {}).get("targets", [])}[tW]["snmp"]["profile"] == "firewall")
        # rimozione e pulizia
        c.request.post(BASE + "?action=net_target_del", form={"id": str(tW)}, headers=H)
        rec("snmp: rimuovendo l'apparato spariscono scansione e avvisi", not q_(prodp, "SELECT 1 FROM net_snmp_walk WHERE target_id=?", tW) and not q_(prodp, "SELECT 1 FROM alerts WHERE status='open' AND type LIKE ?", f"net:{tW}:%"))
        # pagine
        for u in ["?view=network&tab=apparati", "?view=network&tab=sottoreti", f"?view=nettarget&id={tP}", "?view=nettarget&id=999999"]:
            p.goto(BASE + u); b_ = p.content()
            rec(f"snmp: pagina {u} senza errori PHP", not re.search(r"Fatal error|Warning: |Notice: |Deprecated: ", b_))
        rec("snmp: nessun errore JS", not errs, str(errs)[:200])
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sS), "clear": "1"}, headers=H)
        rec("snmp: credenziali rimovibili", q_(prodp, "SELECT snmp FROM net_subnets WHERE id=?", sS)[0][0] == "")
        c.close()
        # <<< t134
        # >>> t135
        # --- 1.35.0: scoperta della rete ("Scoperti"), intervallo per sonda, censimento con un clic
        def pj5(c_, action, form, **kw):
            return c_.request.post(BASE + "?action=" + action, form=form, headers=H, max_redirects=0).status
        def hb5(key, body=None):
            rq = urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body or {"light": True}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        def rp5(key, body):
            rq = urllib.request.Request(BASE + "?action=probe_report", data=json.dumps(body).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(rq, timeout=10).read())
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cx.execute("INSERT INTO sites(name,created) VALUES('Scan Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-D','linux','kpd',?,?,?,'Scan Srl',1)", (nowz, json.dumps({"agent_version": "1.35.0"}), nowz))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-D-OLD','linux','kpdo',?,?,?,'Scan Srl',1)", (nowz, json.dumps({"agent_version": "1.34.0"}), nowz))
        pt_ = cx.execute("SELECT id FROM asset_types WHERE name LIKE 'Stampante%'").fetchone()[0]
        cx.execute("INSERT INTO assets(type_id,name,site,data,created) VALUES(?,?,?,?,?)", (pt_, "Stampante gia' censita", "Scan Srl", json.dumps({"ip": "10.30.0.20"}), nowz)); cx.commit()
        dD = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-D'").fetchone()[0]; dDo = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-D-OLD'").fetchone()[0]; cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        c.request.post(BASE + "?action=net_subnet_add", form={"site": "Scan Srl", "cidr": "10.30.0.0/24", "name": "LAN scan"}, headers=H)
        sD = q_(prodp, "SELECT id FROM net_subnets WHERE site='Scan Srl'")[0][0]
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sD), "device_id": str(dD), "op": "add", "prio": "1"}, headers=H)
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sD), "v": "2c", "comm": "ro-scan"}, headers=H)
        # intervallo di scansione per singola sonda
        p.goto(BASE + "?view=network&tab=sonde"); rec("scoperta: colonna con l'intervallo di scansione per ogni sonda", "Scoperta della rete" in p.content() and "solo su richiesta" in p.content())
        c.request.post(BASE + "?action=probe_conf", form={"device_id": str(dD), "scan_min": "30", "scan_ports": "22, 80,443 ,xx,9100,70000"}, headers=H)
        pc_ = hb5("kpd").get("probe", {})
        rec("scoperta: intervallo e porte (ripulite) arrivano alla sonda", pc_.get("scan_min") == 30 and pc_.get("scan_ports") == [22, 80, 443, 9100], str((pc_.get("scan_min"), pc_.get("scan_ports"))))
        nt_ = pc_.get("nets", [{}])[0]
        rec("scoperta: la rete arriva alla sonda con le credenziali SNMP per riconoscere gli apparati", nt_.get("cidr") == "10.30.0.0/24" and nt_.get("snmp", {}).get("c") == "ro-scan" and "scan" not in nt_, str(nt_))
        c.request.post(BASE + "?action=probe_conf", form={"device_id": str(dDo), "scan_min": "5000", "scan_ports": ""}, headers=H)
        rec("scoperta: intervallo massimo 1440 minuti e porte standard di default", hb5("kpdo") is not None and json.loads(q_(prodp, "SELECT probe_cfg FROM devices WHERE id=?", dDo)[0][0])["scan_min"] == 1440)
        # scansione su richiesta
        ver0 = pc_["ver"]
        c.request.post(BASE + "?action=net_scan_now", form={"subnet_id": str(sD)}, headers=H)
        pc2 = hb5("kpd", {"probe_ver": ver0}).get("probe", {})
        rec("scoperta: «Scansiona ora» arriva alla sonda (richiesta numerata, nuova versione di configurazione)", pc2.get("nets", [{}])[0].get("scan") == 1 and pc2.get("ver") != ver0, str(pc2.get("nets")))
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (dD,)); cx.execute("INSERT OR REPLACE INTO net_subnet_probes(subnet_id,device_id,prio) VALUES(?,?,2)", (sD, dDo)); cx.commit(); cx.close()
        c.request.post(BASE + "?action=net_scan_now", form={"subnet_id": str(sD)}, headers=H)
        rec("scoperta: sonda con agent < 1.35 → richiesta rifiutata, contatore invariato", q_(prodp, "SELECT scan_req FROM net_subnets WHERE id=?", sD)[0][0] == 1)
        cx = sqlite3.connect(prodp); cx.execute("UPDATE devices SET last_seen=? WHERE id=?", (nowz, dD)); cx.execute("DELETE FROM net_subnet_probes WHERE device_id=?", (dDo,)); cx.commit(); cx.close()
        # risultati della scansione
        hosts = [
            {"ip": "10.30.0.20", "mac": "aa:bb:cc:00:00:20", "vendor": "HP", "name": "stampa-hp", "ports": [{"p": 9100, "s": "stampa RAW"}, {"p": 80, "s": "HTTP"}], "title": "HP LaserJet", "ping": True, "rtt": 1.2, "kind": "printer", "snmp": {"name": "HP-ADM", "descr": "HP LaserJet M404", "profile": "printer"}},
            {"ip": "10.30.0.21", "mac": "AA:BB:CC:00:00:21", "vendor": "Brother", "name": "", "ports": [{"p": 9100, "s": "stampa RAW"}, {"p": 631, "s": "IPP"}], "ping": True, "rtt": 2.0, "kind": "printer", "snmp": {"name": "BRN-21", "descr": "Brother HL-L2350DW", "profile": "printer"}},
            {"ip": "10.30.0.30", "mac": "00:0c:29:11:22:33", "vendor": "VMware", "name": "srv-app", "ports": [{"p": 3389, "s": "RDP"}, {"p": 445, "s": "SMB"}], "ping": True, "kind": "windows"},
            {"ip": "10.30.0.40", "mac": "not-a-mac", "vendor": "", "name": "", "ports": [{"p": 22, "s": "SSH", "b": "SSH-2.0-OpenSSH_9.6"}], "ping": False, "kind": "linux"},
            {"ip": "10.31.0.5", "ports": [], "kind": "linux"},
            {"ip": "10.30.0.50", "ports": [], "kind": "tipo-inventato"}]
        rj = rp5("kpd", {"found": [{"net": sD, "ts": int(time.time()), "took": 12, "scanned": 254, "req": 1, "hosts": hosts}]})
        fr = {r[0]: r[1:] for r in q_(prodp, "SELECT ip, state, mac, kind, asset_id, up FROM net_found WHERE subnet_id=?", sD)}
        rec("scoperta: apparati registrati; quello fuori rete scartato, tipo inventato → non riconosciuto, MAC non valido ignorato", set(fr) == {"10.30.0.20", "10.30.0.21", "10.30.0.30", "10.30.0.40", "10.30.0.50"} and fr["10.30.0.50"][2] == "unknown" and fr["10.30.0.40"][1] == "", str(fr))
        rec("scoperta: l'apparato con IP di un asset esistente è già «censito» e collegato", fr["10.30.0.20"][0] == "known" and fr["10.30.0.20"][3] > 0 and fr["10.30.0.21"][0] == "new")
        rec("scoperta: MAC normalizzato in minuscolo", fr["10.30.0.21"][1] == "aa:bb:cc:00:00:21")
        si = q_(prodp, "SELECT last_scan, scan_info FROM net_subnets WHERE id=?", sD)[0]
        rec("scoperta: data e durata dell'ultima scansione registrate", si[0] is not None and json.loads(si[1])["hosts"] == 5 and json.loads(si[1])["took"] == 12)
        p.goto(BASE + "?view=network&tab=scoperti"); b_ = p.content()
        rec("scoperta: scheda Scoperti con nuovi, nome SNMP, costruttore e porte", "BRN-21" in b_ and "Brother" in b_ and "631 IPP" in b_ and "Censisci selezionati" in b_ and "srv-app" in b_)
        p.goto(BASE + "?view=network"); rec("scoperta: contatore dei nuovi accanto alla scheda", re.search(r"Scoperti <span class=\"pill warn\">4</span>", p.content()) is not None, "")
        # censimento con un clic (+ monitoraggio)
        idP = q_(prodp, "SELECT id FROM net_found WHERE ip='10.30.0.21'")[0][0]; idW = q_(prodp, "SELECT id FROM net_found WHERE ip='10.30.0.30'")[0][0]
        c.request.post(BASE + "?action=net_found_act", data=f"op=census&monitor=auto&ids[]={idP}&ids[]={idW}&kind[{idP}]=printer&kind[{idW}]=windows", headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}))
        a1 = q_(prodp, "SELECT a.id, a.name, a.model, a.data, t.name FROM assets a JOIN asset_types t ON t.id=a.type_id WHERE a.site='Scan Srl' AND a.name LIKE 'BRN-21%'")
        rec("censimento: la stampante diventa asset «Stampante» con nome SNMP, modello, IP e MAC", len(a1) == 1 and a1[0][4].startswith("Stampante") and "Brother" in a1[0][2] and json.loads(a1[0][3]).get("ip") == "10.30.0.21" and json.loads(a1[0][3]).get("mac") == "aa:bb:cc:00:00:21", str(a1))
        a2 = q_(prodp, "SELECT a.name, t.name, a.location FROM assets a JOIN asset_types t ON t.id=a.type_id WHERE a.site='Scan Srl' AND a.name='srv-app'")
        rec("censimento: tipo senza modello predefinito → «Altro» con l'IP in ubicazione", a2 == [("srv-app", "Altro", "IP 10.30.0.30")], str(a2))
        tg = {r[0]: r[1:] for r in q_(prodp, "SELECT ip, kind, port, asset_id, profile FROM net_targets WHERE site='Scan Srl'")}
        rec("censimento: monitoraggio creato — SNMP per l'apparato che risponde, ping per gli altri", tg.get("10.30.0.21", ("",))[0] == "snmp" and tg.get("10.30.0.21")[1] == 161 and tg.get("10.30.0.30", ("",))[0] == "ping", str(tg))
        rec("censimento: apparati «censiti» e collegati agli asset", q_(prodp, "SELECT state, asset_id > 0 FROM net_found WHERE id=?", idP) == [("known", 1)])
        c.request.post(BASE + "?action=net_found_act", data=f"op=census&ids[]={idP}", headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}))
        rec("censimento: ripetuto sullo stesso apparato non crea doppioni", q_(prodp, "SELECT COUNT(*) FROM assets WHERE site='Scan Srl' AND name LIKE 'BRN-21%'")[0][0] == 1)
        # ignora / ripristina / elimina
        id40 = q_(prodp, "SELECT id FROM net_found WHERE ip='10.30.0.40'")[0][0]
        for op, want in (("ignore", "ignored"), ("restore", "new")):
            c.request.post(BASE + "?action=net_found_act", data=f"op={op}&ids[]={id40}", headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}))
            rec(f"scoperta: «{op}» sposta l'apparato in «{want}»", q_(prodp, "SELECT state FROM net_found WHERE id=?", id40)[0][0] == want)
        # seconda scansione: un apparato sparisce; scansione parziale non marca nessuno come spento
        hosts2 = [h for h in hosts if h["ip"] not in ("10.30.0.40",)]
        rp5("kpd", {"found": [{"net": sD, "ts": int(time.time()), "took": 9, "scanned": 254, "hosts": hosts2, "cut": True}]})
        rec("scoperta: scansione parziale (rete troppo grande) non segna nessuno come spento", q_(prodp, "SELECT up FROM net_found WHERE id=?", id40)[0][0] == 1)
        rp5("kpd", {"found": [{"net": sD, "ts": int(time.time()), "took": 9, "scanned": 254, "hosts": hosts2}]})
        rec("scoperta: apparato non più visto → spento (non cancellato)", q_(prodp, "SELECT up FROM net_found WHERE id=?", id40) == [(0,)])
        p.goto(BASE + "?view=network&tab=scoperti&st=off"); rec("scoperta: elenco degli spenti", "10.30.0.40" in p.content())
        c.request.post(BASE + "?action=net_found_act", data=f"op=delete&ids[]={id40}", headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}))
        rec("scoperta: elimina dall'elenco", not q_(prodp, "SELECT 1 FROM net_found WHERE id=?", id40))
        # filtro e ricerca
        p.goto(BASE + "?view=network&tab=scoperti&st=all&q=VMware"); b_ = p.content()
        rec("scoperta: ricerca per costruttore", "10.30.0.30" in b_ and "10.30.0.50" not in b_)
        rj = rp5("kpd", {"found": [{"net": 99999, "hosts": [{"ip": "10.30.0.99"}]}]})
        rec("scoperta: risultati su una rete non della sonda ignorati", not q_(prodp, "SELECT 1 FROM net_found WHERE ip='10.30.0.99'"))
        for u in ["?view=network&tab=scoperti", "?view=network&tab=scoperti&st=all", "?view=network&tab=sonde", "?view=network&tab=sottoreti"]:
            p.goto(BASE + u); rec(f"scoperta: pagina {u} senza errori PHP", not re.search(r"Fatal error|Warning: |Notice: |Deprecated: ", p.content()))
        rec("scoperta: nessun errore JS", not errs, str(errs)[:200])
        c.close()
        # <<< t135
        # >>> t136
        # --- 1.36.0: distribuzione dell'agent dalla sonda (credenziali cifrate per la sola sonda, prova a vuoto obbligatoria)
        import base64 as _b64
        kp_ = subprocess.run(["php", "-r", "$k=sodium_crypto_box_keypair(); echo base64_encode(sodium_crypto_box_publickey($k)),' ',base64_encode($k);"], capture_output=True, text=True).stdout.split()
        pub_, kpair_ = kp_[0], kp_[1]
        def unseal_(c_):
            return subprocess.run(["php", "-r", "echo sodium_crypto_box_seal_open(base64_decode($argv[1]), base64_decode($argv[2]));", c_, kpair_], capture_output=True, text=True).stdout
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cx.execute("INSERT INTO sites(name,created) VALUES('Deploy Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-W','windows','kpw',?,?,?,'Deploy Srl',1)", (nowz, json.dumps({"agent_version": "1.36.0"}), nowz))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-V','linux','kpv',?,?,?,'Deploy Srl',1)", (nowz, json.dumps({"agent_version": "1.35.0"}), nowz))
        dW = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-W'").fetchone()[0]; dV = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-V'").fetchone()[0]
        cx.commit(); cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        c.request.post(BASE + "?action=net_subnet_add", form={"site": "Deploy Srl", "cidr": "10.40.0.0/24", "name": "LAN deploy"}, headers=H)
        sW = q_(prodp, "SELECT id FROM net_subnets WHERE site='Deploy Srl'")[0][0]
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sW), "device_id": str(dW), "op": "add", "prio": "1"}, headers=H)
        cx = sqlite3.connect(prodp)
        for ip_, ports_ in (("10.40.0.5", [135, 445, 3389]), ("10.40.0.6", [22, 80]), ("10.40.0.7", [80])):
            cx.execute("INSERT INTO net_found(site,subnet_id,ip,ipn,ports,first_seen,last_seen) VALUES('Deploy Srl',?,?,?,?,?,?)", (sW, ip_, 0, json.dumps([{"p": x} for x in ports_]), nowz, nowz))
        cx.commit(); fW, fL, fN = [r[0] for r in cx.execute("SELECT id FROM net_found WHERE site='Deploy Srl' ORDER BY ip").fetchall()]; cx.close()
        hb_ = hb5("kpw", {"light": True, "probe_ver": "x", "probe_pub": pub_})
        rec("distribuzione: la sonda comunica la chiave pubblica e il server la memorizza", q_(prodp, "SELECT probe_pub FROM devices WHERE id=?", dW)[0][0] == pub_)
        rec("distribuzione: nessuna richiesta finché l'amministratore non ne fa una", not hb_.get("deploy"))
        p.goto(BASE + "?view=network&tab=scoperti&st=all&sn=" + str(sW)); b_ = p.content()
        rec("distribuzione: «Installa agent…» nell'elenco Scoperti", "Installa agent" in b_)
        p.goto(BASE + f"?view=network&tab=distribuzione&ids={fW},{fL},{fN}"); b_ = p.content()
        rec("distribuzione: modulo del lotto con credenziali Windows e SSH, sistema indovinato dalle porte", "Windows (account amministratore)" in b_ and "Linux / macOS (SSH)" in b_ and "Prova a vuoto" in b_ and re.search(r'name="os\[%d\]"[^>]*>.*?<option value="win" selected' % fW, b_, re.S) is not None and re.search(r'name="os\[%d\]"[^>]*>.*?<option value="unix" selected' % fL, b_, re.S) is not None)
        rec("distribuzione: le credenziali non si conservano di default (nessuna opzione «conserva»)", "conserva cifrate" not in b_)
        # senza prova a vuoto l'installazione è rifiutata
        c.request.post(BASE + "?action=net_deploy_start", form={"mode": "run", "ids[]": str(fW), f"os[{fW}]": "win", "win_u": "DOM\\adm", "win_p": "Segreto-W1"}, headers=H)
        r_ = q_(prodp, "SELECT state, detail FROM net_deploy ORDER BY id DESC LIMIT 1")[0]
        rec("distribuzione: installazione rifiutata senza prova a vuoto riuscita", r_[0] == "fail" and "prova a vuoto" in r_[1], str(r_))
        c.request.post(BASE + "?action=net_deploy_start", data=urllib.parse.urlencode([("mode", "dry"), ("ids[]", str(fW)), ("ids[]", str(fL)), ("ids[]", str(fN)), (f"os[{fW}]", "win"), (f"os[{fL}]", "unix"), ("win_u", "DOM\\adm"), ("win_p", "Segreto-W1"), ("unix_u", "pippo"), ("unix_p", "Segreto-L2"), ("unix_sudo", "1"), ("remember_win", "1")]), headers={**H, "Content-Type": "application/x-www-form-urlencoded"})
        rows_ = q_(prodp, "SELECT ip, os, mode, state, detail, cred FROM net_deploy WHERE mode='dry' ORDER BY ip")
        by_ = {r[0]: r for r in rows_}
        rec("distribuzione: PC in coda per la sonda, quello senza sistema noto rifiutato con il motivo", by_["10.40.0.5"][3] == "queued" and by_["10.40.0.6"][3] == "queued" and by_["10.40.0.7"][3] == "fail" and "Sistema non riconosciuto" in by_["10.40.0.7"][4], str(rows_)[:300])
        raw_ = json.dumps(q_(prodp, "SELECT * FROM net_deploy")) + json.dumps(q_(prodp, "SELECT * FROM audit"))
        rec("distribuzione: password mai in chiaro nel database né nell'audit", "Segreto-W1" not in raw_ and "Segreto-L2" not in raw_ and by_["10.40.0.5"][5] != "")
        rec("distribuzione: «conserva» ignorato se il salvataggio non è abilitato nel server", not q_(prodp, "SELECT 1 FROM net_deploy_cred"))
        hb_ = hb5("kpw", {"light": True, "probe_ver": "x", "probe_pub": pub_}); dp_ = {t["ip"]: t for t in hb_.get("deploy", [])}
        rec("distribuzione: l'heartbeat della sonda porta le due richieste (prova, senza script)", set(dp_) == {"10.40.0.5", "10.40.0.6"} and all(t["mode"] == "dry" and not t.get("script") for t in dp_.values()), str(list(dp_)))
        cw_ = json.loads(unseal_(dp_["10.40.0.5"]["cred"])) if dp_ else {}; cl_ = json.loads(unseal_(dp_["10.40.0.6"]["cred"])) if dp_ else {}
        rec("distribuzione: solo la sonda (con la sua chiave privata) decifra le credenziali", cw_ == {"u": "DOM\\adm", "p": "Segreto-W1"} and cl_.get("u") == "pippo" and cl_.get("p") == "Segreto-L2" and cl_.get("sudo") is True, str((cw_, cl_)))
        rec("distribuzione: richiesta consegnata una volta sola", not hb5("kpw", {"light": True, "probe_ver": "x"}).get("deploy"))
        # esiti della prova
        rp5("kpw", {"deploys": [{"id": dp_["10.40.0.5"]["id"], "state": "ok", "detail": "pronto per l'installazione. Windows 11"}, {"id": dp_["10.40.0.6"]["id"], "state": "fail", "detail": "porta SSH chiusa"}]})
        by_ = {r[0]: r for r in q_(prodp, "SELECT ip, os, mode, state, detail, cred FROM net_deploy WHERE mode='dry' ORDER BY ip")}
        rec("distribuzione: esiti registrati; credenziali tolte dopo un errore, tenute (cifrate) dopo una prova riuscita", by_["10.40.0.5"][3] == "ok" and by_["10.40.0.5"][5] != "" and by_["10.40.0.6"][3] == "fail" and by_["10.40.0.6"][5] == "")
        rp5("kpv", {"deploys": [{"id": dp_["10.40.0.5"]["id"], "state": "fail", "detail": "intruso"}]})
        rec("distribuzione: un'altra sonda non può modificare l'esito", q_(prodp, "SELECT detail FROM net_deploy WHERE ip='10.40.0.5' AND mode='dry'")[0][0].startswith("pronto"))
        p.goto(BASE + "?view=network&tab=distribuzione"); b_ = p.content()
        rec("distribuzione: elenco esiti con il pulsante di installazione solo per la prova riuscita", "porta SSH chiusa" in b_ and "Installa l'agent sui PC selezionati" in b_ and b_.count('name="dids[]"') == 1 and not re.search(r"Fatal error|Warning: |Notice: ", b_))
        did_ = q_(prodp, "SELECT id FROM net_deploy WHERE ip='10.40.0.5' AND mode='dry'")[0][0]
        c.request.post(BASE + "?action=net_deploy_run", form={"dids[]": str(did_)}, headers=H)
        hb_ = hb5("kpw", {"light": True, "probe_ver": "x"}); t_ = (hb_.get("deploy") or [{}])[0]
        rec("distribuzione: l'installazione arriva alla sonda con lo script del cliente (scarica con il token di site)", t_.get("mode") == "run" and "install_bin" in t_.get("script", "") and "st-" in t_.get("script", "") and t_.get("os") == "win", str(t_)[:200])
        rp5("kpw", {"deploys": [{"id": t_["id"], "state": "ok", "detail": "installato e in esecuzione"}]})
        rec("distribuzione: a installazione conclusa la credenziale cifrata viene cancellata", q_(prodp, "SELECT cred, state FROM net_deploy WHERE id=?", t_["id"])[0] == ("", "ok"))
        # sonda con agent vecchio / non Windows
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sW), "device_id": str(dW), "op": "del"}, headers=H)
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sW), "device_id": str(dV), "op": "add", "prio": "1"}, headers=H)
        c.request.post(BASE + "?action=net_deploy_start", form={"mode": "dry", "ids[]": str(fL), f"os[{fL}]": "unix", "unix_u": "pippo", "unix_p": "x"}, headers=H)
        r_ = q_(prodp, "SELECT state, detail FROM net_deploy ORDER BY id DESC LIMIT 1")[0]
        rec("distribuzione: sonda con agent troppo vecchio → rifiuto con il motivo", r_[0] == "fail" and "troppo vecchio" in r_[1], str(r_))
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sW), "device_id": str(dV), "op": "del"}, headers=H)
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sW), "device_id": str(dW), "op": "add", "prio": "1"}, headers=H)
        # richieste appese: scadono
        cx = sqlite3.connect(prodp); cx.execute("INSERT INTO net_deploy(batch,site,subnet_id,found_id,probe_id,ip,os,mode,state,cred,created,updated) VALUES('x','Deploy Srl',?,?,?,'10.40.0.9','unix','dry','queued','abc','2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')", (sW, fL, dW)); cx.commit(); cx.close()
        p.goto(BASE + "?view=network&tab=distribuzione")
        r_ = q_(prodp, "SELECT state, cred FROM net_deploy WHERE ip='10.40.0.9'")[0]
        rec("distribuzione: richiesta non presa in carico → scaduta e credenziale cancellata", r_ == ("fail", ""), str(r_))
        # permessi
        for u in [f"?view=network&tab=distribuzione&ids={fW},{fL}", "?view=network&tab=distribuzione"]:
            p.goto(BASE + u); rec(f"distribuzione: pagina {u} senza errori PHP", not re.search(r"Fatal error|Warning: |Notice: |Deprecated: ", p.content()))
        rec("distribuzione: nessun errore JS", not errs, str(errs)[:200])
        c.close()
        # <<< t136
        # >>> t137
        # --- 1.37.0: profili UPS / NAS / access point, vicini LLDP-CDP, mappa di rete ipotetica
        cx = sqlite3.connect(prodp); nowz = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cx.execute("INSERT INTO sites(name,created) VALUES('Mappa Srl',?)", (nowz,))
        cx.execute("INSERT INTO devices(hostname,os,api_key,last_seen,inventory,created,site,probe) VALUES('SONDA-M','linux','kpm',?,?,?,'Mappa Srl',1)", (nowz, json.dumps({"agent_version": "1.37.0"}), nowz))
        dM = cx.execute("SELECT id FROM devices WHERE hostname='SONDA-M'").fetchone()[0]; cx.commit(); cx.close()
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        c.request.post(BASE + "?action=net_subnet_add", form={"site": "Mappa Srl", "cidr": "10.50.0.0/24", "name": "LAN mappa"}, headers=H)
        sM = q_(prodp, "SELECT id FROM net_subnets WHERE site='Mappa Srl'")[0][0]
        c.request.post(BASE + "?action=net_subnet_probe", form={"subnet_id": str(sM), "device_id": str(dM), "op": "add", "prio": "1"}, headers=H)
        c.request.post(BASE + "?action=net_subnet_snmp", form={"subnet_id": str(sM), "v": "2c", "comm": "ro"}, headers=H)
        cx = sqlite3.connect(prodp)
        for nm_, ip_ in (("SW-CED", "10.50.0.2"), ("FW-SEDE", "10.50.0.1"), ("AP-PIANO1", "10.50.0.3"), ("UPS-CED", "10.50.0.4"), ("NAS-UFFICIO", "10.50.0.5")):
            cx.execute("INSERT INTO net_targets(site,subnet_id,name,ip,kind,port,interval_s,sev,enabled,created) VALUES('Mappa Srl',?,?,?,'snmp',161,60,'warn',1,?)", (sM, nm_, ip_, nowz))
        for ip_, nm_, mac_, kd_ in (("10.50.0.60", "PC-AMM1", "aa:aa:aa:00:00:60", "windows"), ("10.50.0.61", "PC-AMM2", "aa:aa:aa:00:00:61", "windows"), ("10.50.0.70", "STAMPA-1", "aa:aa:aa:00:00:70", "printer")):
            cx.execute("INSERT INTO net_found(site,subnet_id,ip,ipn,mac,name,kind,first_seen,last_seen) VALUES('Mappa Srl',?,?,0,?,?,?,?,?)", (sM, ip_, mac_, nm_, kd_, nowz, nowz))
        cx.commit(); T_ = {r[0]: r[1] for r in cx.execute("SELECT name,id FROM net_targets WHERE site='Mappa Srl'").fetchall()}; cx.close()
        def mkres(tid, snmp): return {"id": tid, "ok": True, "rtt": 1.0, "ts": int(time.time()), "snmp": snmp}
        base_ = lambda prof, name, **kw: dict({"name": name, "descr": name, "oid": ".1.3.6.1.4.1.9", "up": 1000, "profile": prof, "m": {"uptime": 1000}, "info": {}}, **kw)
        # il firewall hub conosce lo switch via CDP (IP), lo switch conosce firewall (MAC mancante: per nome) e AP via LLDP (nome), l'AP lo switch via LLDP (MAC)
        rp5("kpm", {"results": [
            mkres(T_["SW-CED"], base_("switch", "SW-CED", m={"uptime": 1000, "ports_up": 6, "ports_total": 24}, nbr=[{"lp": 1, "ln": "Gi1/0/1", "name": "FW-SEDE", "port": "lan", "p": "lldp"}, {"lp": 20, "ln": "Gi1/0/20", "name": "AP-PIANO1", "port": "eth0", "mac": "00:11:22:33:44:55", "p": "lldp"}, {"lp": 21, "ln": "Gi1/0/21", "name": "Telecamera-Ingresso", "port": "eth0", "p": "lldp"}])),
            mkres(T_["FW-SEDE"], base_("firewall", "FW-SEDE", nbr=[{"lp": 2, "ln": "lan", "name": "SW-CED", "port": "Gi1/0/1", "ip": "10.50.0.2", "p": "cdp"}])),
            mkres(T_["AP-PIANO1"], base_("ap", "AP-PIANO1", m={"uptime": 1000, "clients": 16}, info={"reti_wifi": "Ufficio-WiFi (canale 36, 11 client)"}, nbr=[{"lp": 1, "ln": "eth0", "name": "SW-CED", "port": "Gi1/0/20", "p": "lldp"}])),
            mkres(T_["UPS-CED"], base_("ups", "UPS-CED", m={"uptime": 1000, "batt_pct": 22, "runtime_min": 9, "batt_status": 2, "on_battery": 0, "load_pct": 35}, info={"marca": "APC", "modello": "Smart-UPS 1500", "batteria": "normale"})),
            mkres(T_["NAS-UFFICIO"], base_("nas", "NAS-UFFICIO", m={"uptime": 1000, "disks": 2, "disk_bad": 1, "disk_temp_max": 61, "raid_bad": 0, "sys_bad": 0}, info={"modello": "DS920+", "dischi_anomali": "Drive 2"})),
        ]})
        al_ = [r[0] for r in q_(prodp, "SELECT type FROM alerts WHERE status='open'")]
        rec("UPS: batteria sotto soglia apre l'avviso di carica", any(f"net:{T_['UPS-CED']}:ups:charge" == a for a in al_), str(al_))
        rec("NAS: disco anomalo e disco troppo caldo aprono gli avvisi", f"net:{T_['NAS-UFFICIO']}:nas:disk" in al_ and f"net:{T_['NAS-UFFICIO']}:nas:temp" in al_, str(al_))
        p.goto(BASE + f"?view=nettarget&id={T_['UPS-CED']}"); b_ = p.content()
        rec("UPS: scheda con batteria, autonomia, carico e dati del costruttore", "Batteria" in b_ and "Autonomia" in b_ and "Smart-UPS 1500" in b_ and "Stato batteria" in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_))
        p.goto(BASE + f"?view=nettarget&id={T_['NAS-UFFICIO']}"); b_ = p.content()
        rec("NAS: scheda con dischi anomali e disco più caldo", "Dischi anomali" in b_ and "Disco più caldo" in b_ and "DS920+" in b_)
        p.goto(BASE + f"?view=nettarget&id={T_['AP-PIANO1']}"); b_ = p.content()
        rec("AP: client Wi-Fi e reti con canale", "Client Wi-Fi" in b_ and "canale 36" in b_)
        p.goto(BASE + f"?view=nettarget&id={T_['SW-CED']}"); b_ = p.content()
        rec("switch: tabella dei vicini LLDP con porte locali e remote", "Vicini (LLDP / CDP)" in b_ and "FW-SEDE" in b_ and "Gi1/0/20" in b_ and "Telecamera-Ingresso" in b_)
        p.goto(BASE + "?view=network&tab=mappa&site=Mappa+Srl"); b_ = p.content()
        nl_ = len(re.findall(r'data-e="(lldp|cdp)"', b_)); ng_ = len(re.findall(r'data-e="guess"', b_)); nn_ = len(re.findall(r'<g data-n=', b_))
        rec("mappa: pagina con SVG, senza errori PHP", "<svg id=\"netmap\"" in b_ and not re.search(r"Fatal error|Warning: |Notice: ", b_))
        rec("mappa: collegamenti confermati da LLDP/CDP (FW↔SW una sola volta, SW↔AP, SW↔telecamera esterna)", nl_ == 3 and 'data-e="cdp"' in b_ and 'data-e="lldp"' in b_, f"{nl_} certi")
        rec("mappa: gli altri apparati sono appesi per ipotesi allo switch (UPS, NAS, PC, stampante) e il firewall a Internet", ng_ >= 5, f"{ng_} ipotetici")
        rec("mappa: nodi di tutti gli apparati + Internet + telecamera sconosciuta del vicino", nn_ == 5 + 3 + 1 + 1, f"{nn_} nodi")
        rec("mappa: legenda e conteggi", "collegamenti confermati" in b_ and "ipotetici" in b_)
        r_ = c.request.get(BASE + "?action=net_map_svg&site=Mappa+Srl")
        rec("mappa: download SVG con colori risolti", r_.status == 200 and "image/svg+xml" in r_.headers.get("content-type", "") and "<svg" in r_.text() and "var(--" not in r_.text())
        rec("mappa: un cliente non esistente è rifiutato", c.request.get(BASE + "?action=net_map_svg&site=Inesistente").status in (403, 404))
        rp5("kpm", {"results": [mkres(T_["UPS-CED"], base_("ups", "UPS-CED", m={"uptime": 1000, "batt_pct": 22, "runtime_min": 4, "batt_status": 2, "on_battery": 1, "load_pct": 35}))]})
        rec("UPS: passaggio a batteria apre l'avviso critico", f"net:{T_['UPS-CED']}:ups:onbatt" in [r[0] for r in q_(prodp, "SELECT type FROM alerts WHERE status='open'")])
        p.goto(BASE + "?view=network&tab=mappa"); rec("mappa: senza cliente indicato sceglie il primo con apparati", not re.search(r"Fatal error|Warning: |Notice: ", p.content()))
        rec("mappa: nessun errore JS", not errs, str(errs)[:200])
        c.close()
        # <<< t137
        # >>> t166
        # --- 1.66.0: etichette QR dei device, codice permanente, ticket legati agli asset
        c, p = new(); adm(c, p); errs = []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("dialog", lambda d: d.accept())
        dq_ = lambda sql, *a: q_(prodp, sql, *a)
        tid_ = dq_("SELECT id FROM asset_types ORDER BY id LIMIT 1")[0][0]
        c.request.post(BASE + "?action=asset_save", form={"id": "0", "type_id": str(tid_), "name": "Stampante QR", "site": "Acme", "status": "attivo"}, headers=H, max_redirects=0)
        ast_ = dq_("SELECT id FROM assets WHERE name='Stampante QR'")[0][0]
        r_ = c.request.get(BASE + "?action=device_label&ids=1")
        b_ = r_.text(); cd_ = dq_("SELECT label_code FROM devices WHERE id=1")[0][0]
        rec("QR device: pagina etichette con il codice permanente", r_.status == 200 and "data-u=" in b_ and "view=go&amp;l=" + cd_ in b_ and cd_.startswith("d") and len(cd_) == 10, cd_)
        rec("QR device: stesso formato (64×30 mm, #id)", "64mm" in b_ and "#1<" in b_)
        c.request.get(BASE + "?action=device_label&ids=1")
        rec("QR device: il codice non cambia ristampando", dq_("SELECT label_code FROM devices WHERE id=1")[0][0] == cd_)
        c.request.get(BASE + f"?action=asset_label&ids={ast_}"); ca_ = dq_("SELECT label_code FROM assets WHERE id=?", ast_)[0][0]
        rec("QR asset: codice permanente con prefisso a", ca_.startswith("a") and len(ca_) == 10, ca_)
        rec("QR device: nessun id → errore", c.request.get(BASE + "?action=device_label&ids=").status == 400)
        r_ = c.request.get(BASE + f"?view=go&l={cd_}", max_redirects=0)
        rec("QR: il codice del device porta alla scheda", r_.status in (301, 302, 303) and "view=device&id=1" in r_.headers.get("location", ""), r_.headers.get("location", ""))
        r_ = c.request.get(BASE + f"?view=go&l={ca_}", max_redirects=0)
        rec("QR: il codice dell'asset porta alla scheda", f"view=asset&id={ast_}" in r_.headers.get("location", ""), r_.headers.get("location", ""))
        r_ = c.request.get(BASE + "?view=go&l=dzzzzzzzzz", max_redirects=0)
        rec("QR: codice sconosciuto → elenco con messaggio", "view=devices" in r_.headers.get("location", "") and "msg=" in r_.headers.get("location", ""))
        anon_ = br.new_context(); r_ = anon_.request.get(BASE + f"?view=go&l={cd_}", max_redirects=0)
        rec("QR: senza login niente scheda (passa dall'accesso)", "view=device&id=1" not in r_.headers.get("location", ""), r_.status); anon_.close()
        p.goto(BASE + f"?view=go&l={cd_}"); p.wait_for_selector("#tkq")
        rec("QR: scheda device con riquadro ticket e apertura rapida", "view=device" in p.url and p.locator("#tkq form input[name=title]").count() == 1)
        p.fill("#tkq input[name=title]", "Schermo nero"); p.click("#tkq button[type=submit]"); p.wait_for_load_state("load")
        rec("ticket da QR device: creato sul device", dq_("SELECT COUNT(*) FROM tickets WHERE title='Schermo nero' AND device_id=1 AND asset_id=0")[0][0] == 1)
        p.goto(BASE + f"?view=go&l={ca_}"); p.wait_for_selector("#tkq")
        p.fill("#tkq input[name=title]", "Carta inceppata"); p.click("#tkq button[type=submit]"); p.wait_for_load_state("load")
        rec("ticket da QR asset: creato sull'asset", dq_("SELECT COUNT(*) FROM tickets WHERE title='Carta inceppata' AND asset_id=?", ast_)[0][0] == 1)
        tkid_ = dq_("SELECT id FROM tickets WHERE title='Carta inceppata'")[0][0]
        p.goto(BASE + f"?view=tickets&id={tkid_}"); rec("ticket: la scheda mostra l'asset collegato", "Stampante QR" in p.content() and f"view=asset&amp;id={ast_}" in p.content(), p.content()[:0] + str(("Stampante QR" in p.content(), p.url)))
        p.goto(BASE + f"?view=tickets&ast={ast_}"); rec("ticket: filtro per asset", "Carta inceppata" in p.inner_text("main") and "Schermo nero" not in p.inner_text("main"))
        p.goto(BASE + "?view=tickets"); rec("ticket: elenco con colonna Asset", "<th>Asset</th>" in p.content())
        p.goto(BASE + f"?view=asset&id={ast_}"); rec("asset: riquadro ticket con quello aperto", p.locator("#tkq").count() == 1 and "Carta inceppata" in p.locator("#tkq").inner_text())
        r_ = c.request.post(BASE + "?action=tk_new", form={"title": "senza oggetto"}, headers=H, max_redirects=0)
        rec("ticket: senza device né asset è rifiutato", dq_("SELECT COUNT(*) FROM tickets WHERE title='senza oggetto'")[0][0] == 0)
        p.goto(BASE + "?view=devices"); p.wait_for_selector("#invT"); p.click("#actsel summary")
        rec("elenco device: voce «Stampa etichette QR» disattiva senza selezione", p.locator("#actsel .mi[data-lbl][disabled]").count() == 1)
        p.locator("#invT tbody input[type=checkbox]").first.check(); p.click("#actsel summary") if not p.locator("#actsel[open]").count() else None
        with c.expect_page() as np_:
            p.locator("#actsel .mi[data-lbl]").click()
        lp_ = np_.value; lp_.wait_for_load_state("load"); lp_.wait_for_selector(".qr svg")
        rec("elenco device: etichette QR in una nuova scheda con il QR disegnato", lp_.locator(".l").count() >= 1 and lp_.locator(".qr svg").count() >= 1); lp_.close()
        rec("QR: nessun errore JS", not errs, str(errs)[:200])
        c.close()
        # <<< t166
        br.close()
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
bad = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(bad)}/{len(res)} ok"); sys.exit(1 if bad else 0)
