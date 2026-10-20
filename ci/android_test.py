#!/usr/bin/env python3
"""Android Enterprise (Android Management API) contro un Google simulato, 1.47.0.
Uso: python3 ci/android_test.py"""
import calendar, os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, threading, base64, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8818; MP = 8819; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-and-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32, "AMAPI_BASE": f"http://127.0.0.1:{MP}/v1"}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
PRIV = subprocess.run(["php", "-r", "$k=openssl_pkey_new(['private_key_bits'=>2048]); openssl_pkey_export($k,$o); echo $o; echo '|||'; echo openssl_pkey_get_details($k)['key'];"], capture_output=True, text=True).stdout.split("|||")
SA = {"type": "service_account", "project_id": "proj-test", "client_email": "svc@proj-test.iam.gserviceaccount.com", "private_key": PRIV[0], "token_uri": f"http://127.0.0.1:{MP}/token"}
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite")
res = []; LOG = []   # (metodo, percorso, corpo)
JWT = {}

def iso(sec): return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + sec))
DEVS1 = [{"name": "enterprises/LC001/devices/d111aaa", "state": "ACTIVE", "ownership": "COMPANY_OWNED", "managementMode": "DEVICE_OWNER", "policyCompliant": True,
          "lastStatusReportTime": iso(-600), "lastPolicySyncTime": iso(-7200), "enrollmentTokenData": json.dumps({"s": "Acme", "d": "", "l": "Telefono di Mario"}),
          "hardwareInfo": {"manufacturer": "Google", "model": "Pixel 8", "serialNumber": "SER123"}, "softwareInfo": {"androidVersion": "14", "securityPatchLevel": "2026-09-05"},
          "memoryInfo": {"totalRam": "8589934592", "totalInternalStorage": "137438953472"}, "networkInfo": {"imei": "35000000000001"}, "userName": "enterprises/LC001/users/1"}]
DEVS2 = [{"name": "enterprises/LC001/devices/d222bbb", "state": "ACTIVE", "ownership": "PERSONALLY_OWNED", "managementMode": "PROFILE_OWNER", "policyCompliant": False,
          "lastStatusReportTime": iso(-60 * 60 * 30), "hardwareInfo": {"manufacturer": "samsung", "model": "SM-A546B"}, "softwareInfo": {"androidVersion": "13"}}]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _do(self, m):
        n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n).decode() if n else ""
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
        if u.path == "/token":
            a = urllib.parse.parse_qs(raw).get("assertion", [""])[0]; parts = a.split(".")
            if len(parts) != 3: return self._send(400, {"error": "bad"})
            pad = lambda s: s + "=" * (-len(s) % 4)
            JWT["claims"] = json.loads(base64.urlsafe_b64decode(pad(parts[1]))); JWT["head"] = json.loads(base64.urlsafe_b64decode(pad(parts[0])))
            try:
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding
                pub = serialization.load_pem_public_key(PRIV[1].encode())
                pub.verify(base64.urlsafe_b64decode(pad(parts[2])), (parts[0] + "." + parts[1]).encode(), padding.PKCS1v15(), hashes.SHA256()); JWT["sig"] = True
            except ImportError: JWT["sig"] = None
            except Exception: JWT["sig"] = False
            JWT["n"] = JWT.get("n", 0) + 1
            return self._send(200, {"access_token": "tok123", "expires_in": 3600})
        if self.headers.get("Authorization") != "Bearer tok123": return self._send(401, {"error": {"message": "unauthenticated"}})
        body = json.loads(raw) if raw else None; LOG.append((m, u.path, body, {k: v[0] for k, v in qs.items()}))
        p = u.path
        if m == "POST" and p == "/v1/signupUrls": return self._send(200, {"name": "signupUrls/S1", "url": f"http://127.0.0.1:{MP}/signup?s=1"})
        if m == "POST" and p == "/v1/enterprises": return self._send(200, {"name": "enterprises/LC001"})
        if m == "GET" and p == "/v1/enterprises/LC001": return self._send(200, {"name": "enterprises/LC001"})
        if m == "PATCH" and "/policies/" in p: return self._send(200, {})
        if m == "POST" and p.endswith("/enrollmentTokens"): return self._send(200, {"name": "enterprises/LC001/enrollmentTokens/1", "value": "TOKABC" + str(len([x for x in LOG if x[1].endswith('enrollmentTokens')])), "qrCode": json.dumps({"android.app.extra.PROVISIONING_DEVICE_ADMIN_COMPONENT_NAME": "com.google.android.apps.work.clouddpc/.receivers.CloudDeviceAdminReceiver"}), "expirationTimestamp": iso(86400)})
        if m == "GET" and p == "/v1/enterprises/LC001/devices": return self._send(200, {"devices": DEVS2, "nextPageToken": ""} if qs.get("pageToken") == ["p2"] else {"devices": DEVS1, "nextPageToken": "p2"})
        if m == "POST" and p.endswith(":issueCommand"): return self._send(200, {"name": "operations/1"})
        return self._send(404, {"error": {"message": "non trovato " + p}})
    def do_GET(self): self._do("GET")
    def do_POST(self): self._do("POST")
    def do_PATCH(self): self._do("PATCH")
mock = ThreadingHTTPServer(("127.0.0.1", MP), H); threading.Thread(target=mock.serve_forever, daemon=True).start()

def rec(name, ok, info=""):
    res.append((name, bool(ok))); print(("OK   " if ok else "FAIL ") + name + (("  [" + str(info)[:240] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def calls(m, suffix): return [x for x in LOG if x[0] == m and x[1].endswith(suffix)]

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
    with sync_playwright() as pw:
        br = pw.chromium.launch(); cx = br.new_context(viewport={"width": 1360, "height": 900}); p = cx.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append("JS: " + str(e)))
        p.on("dialog", lambda d: d.accept())
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail", timeout=8000)
        def post(act, **form):
            r = cx.request.post(BASE + "?action=" + act, form=form, max_redirects=0); return r
        def page(url=""): p.goto(BASE + "?view=android" + url); p.wait_for_selector("main"); return p.content()
        html = page()
        rec("pagina Android: non collegato", "Non collegato" in html and "1. Collegamento a Google" in html)
        rec("non collegato: la scheda dell'APK con il QR di scarico è comunque visibile", 'id="apkqr_dl"' in html and "App myrmm per Android (senza Google)" in html and "action=mobile_apk" in html and "Scollega Android Enterprise" not in html)
        r = post("amapi_save", sa="{non json", ent="")
        rec("JSON non valido rifiutato", "err=" in (r.headers.get("location") or ""), r.headers.get("location"))
        r = post("amapi_save", sa=json.dumps(SA), ent="")
        html = page()
        rec("service account salvato: nessun segreto in pagina", SA["client_email"] in html and "BEGIN PRIVATE KEY" not in html and "BEGIN RSA" not in html)
        stored = q("SELECT v FROM meta WHERE k='amapi:sa'")[0][0]
        rec("service account cifrato a riposo", "private_key" not in stored and "BEGIN" not in stored)
        html = page()
        p.click("text=Crea enterprise con Google")
        try: p.wait_for_url(re.compile(rf"^http://127\.0\.0\.1:{MP}/signup"), timeout=8000)
        except Exception: pass
        rec("crea enterprise: il browser arriva su Google (CSP form-action)", p.url.startswith(f"http://127.0.0.1:{MP}/signup"), p.url)
        sg = calls("POST", "/v1/signupUrls")
        rec("signupUrls: progetto e callback", sg and sg[0][3].get("projectId") == "proj-test" and "action=amapi_cb&st=" in sg[0][3].get("callbackUrl", ""), sg)
        rec("JWT: intestazione RS256, claim e firma", JWT.get("head", {}).get("alg") == "RS256" and JWT["claims"]["iss"] == SA["client_email"] and JWT["claims"]["scope"].endswith("androidmanagement") and JWT["claims"]["aud"] == SA["token_uri"] and JWT.get("sig") in (True, None), (JWT.get("head"), JWT.get("claims"), JWT.get("sig")))
        cb = sg[0][3]["callbackUrl"]
        anon = br.new_context(); ar = anon.request   # niente cookie di sessione: come il ritorno da Google (SameSite=Strict)
        r = ar.get(cb.replace("st=", "st=sbagliato") + "&enterpriseToken=ET1")
        rec("ritorno da Google con stato errato: rifiutato", r.status == 400 and not calls("POST", "/v1/enterprises"), r.status)
        r = ar.get(cb + "&enterpriseToken=ET1")
        rec("ritorno da Google senza sessione: pagina di passaggio, enterprise non ancora creata", r.status == 200 and "amapi_finish" in r.text() and not calls("POST", "/v1/enterprises"), (r.status, r.text()[:120]))
        r = ar.get(cb + "&enterpriseToken=ET1")
        rec("stato monouso: secondo ritorno rifiutato", r.status == 400, r.status)
        anon.close()
        p.goto(BASE + "?action=amapi_finish"); p.wait_for_load_state()
        ent = calls("POST", "/v1/enterprises")
        rec("completamento in console: enterprise creata", ent and ent[0][3].get("signupUrlName") == "signupUrls/S1" and ent[0][3].get("enterpriseToken") == "ET1" and q("SELECT v FROM meta WHERE k='amapi:ent'")[0][0] == "enterprises/LC001", ent)
        r = post("amapi_save", sa="", ent="enterprises/NOPE")
        rec("enterprise non valida per Google: non salvata", "err=" in (r.headers.get("location") or "") and q("SELECT v FROM meta WHERE k='amapi:ent'")[0][0] == "enterprises/LC001", r.headers.get("location"))
        pol = [x for x in LOG if x[0] == "PATCH"]
        rec("criteri aziendali e personali inviati", {x[1].rsplit("/", 1)[1] for x in pol} == {"myrmm-company", "myrmm-byod"}, pol)
        rec("token OAuth in cache: una sola autenticazione finora", JWT.get("n") == 1, JWT.get("n"))
        html = page()
        rec("pagina collegata", "Collegato" in html and "enterprises/LC001" in html and "3. Aggiungi telefono" in html)

        r = post("amapi_policy", company="{rotto", byod="{}")
        rec("criteri JSON non valido rifiutato", "err=" in (r.headers.get("location") or ""))
        n0 = len(pol)
        r = post("amapi_policy", company='{"statusReportingSettings":{"softwareInfoEnabled":true},"passwordRequirements":{"passwordMinimumLength":6}}', byod="{}")
        pc = [x for x in LOG if x[0] == "PATCH" and x[1].endswith("myrmm-company")][-1]
        rec("criteri salvati e inviati", pc[2].get("passwordRequirements", {}).get("passwordMinimumLength") == 6, pc)

        r = post("amapi_token", mode="company", site="Acme", label="Telefono di Mario", hours="24")
        tk = calls("POST", "/enrollmentTokens")[-1]
        rec("token aziendale: criteri, uso personale vietato, dati cliente", tk[2]["policyName"] == "enterprises/LC001/policies/myrmm-company" and tk[2]["allowPersonalUsage"] == "PERSONAL_USAGE_DISALLOWED" and tk[2]["oneTimeOnly"] is True and tk[2]["duration"] == "86400s" and json.loads(tk[2]["additionalData"])["s"] == "Acme", tk)
        html = page()
        rec("pagina: QR e istruzioni del telefono aziendale", 'id="amqr"' in html and "6 volte" in html and "TOKABC1" in html)
        r = post("amapi_token", mode="byod", site="Acme", label="", hours="2")
        tk = calls("POST", "/enrollmentTokens")[-1]
        rec("token personale: uso personale consentito, 2 ore", tk[2]["allowPersonalUsage"] == "PERSONAL_USAGE_ALLOWED" and tk[2]["duration"] == "7200s" and tk[2]["policyName"].endswith("myrmm-byod"), tk)
        html = page()
        rec("pagina: istruzioni del work profile", "Android Device Policy" in html and "work profile" in html and "6 volte" not in html.split("Codice di arruolamento")[0].split("<ol>")[-1])
        r = post("amapi_token", mode="company", site="Inesistente", label="", hours="1")
        rec("cliente inesistente rifiutato", "err=" in (r.headers.get("location") or ""))

        post("amapi_sync")
        rows = q("SELECT id,hostname,site,mobile_id,mobile_min,last_seen,inventory FROM devices WHERE mobile_id LIKE 'amapi:%' ORDER BY mobile_id")
        rec("sincronizzazione: due telefoni (con pagina successiva)", len(rows) == 2 and [x[3] for x in rows] == ["amapi:d111aaa", "amapi:d222bbb"], rows)
        a = rows[0]; ia = json.loads(a[6])
        rec("telefono aziendale: nome, cliente, finestra", a[1] == "Telefono di Mario" and a[2] == "Acme" and a[4] == 360, a[:5])
        rec("inventario Android mappato", ia.get("os") == "Android 14" and ia.get("model") == "Pixel 8" and ia.get("ram_gb") == 8.0 and ia.get("ownership") == "Aziendale" and ia.get("security_patch") == "2026-09-05" and ia.get("compliant") == "sì" and ia.get("serial") == "SER123", ia)
        b = rows[1]; ib = json.loads(b[6])
        rec("telefono personale: nome automatico, work profile, non conforme", b[1].startswith("samsung SM-A546B-") and b[2] == "" and ib.get("ownership") == "Personale (work profile)" and ib.get("compliant") == "no", (b[1], ib))
        rec("ultimo contatto da lastStatusReportTime", a[5] and abs(calendar.timegm(time.strptime(a[5], "%Y-%m-%dT%H:%M:%SZ")) - (time.time() - 600)) < 120, a[5])
        ck = q("SELECT threshold,param FROM checks WHERE type='offline_min' AND device_id=?", a[0])
        rec("soglia offline propria: 720 min", ck == [(720.0, "mobile")], ck)
        post("amapi_sync")
        rec("seconda sincronizzazione: nessun duplicato", q("SELECT COUNT(*) FROM devices WHERE mobile_id LIKE 'amapi:%'")[0][0] == 2)

        p.goto(BASE + f"?view=device&id={a[0]}"); p.wait_for_selector("main"); html = p.content()
        rec("scheda: online (contatto 10 min fa), comandi Google, niente agent", 'class="pill ok">online' in html and "Blocca schermo" in html and "Ripristina (wipe)" in html and "Task manager" not in html and "Inventario completo ora" not in html and "Android Enterprise" in html)
        p.goto(BASE + f"?view=device&id={b[0]}"); p.wait_for_selector("main"); html = p.content()
        rec("scheda: contatto 30 h fa risulta offline", 'class="pill err">offline' in html)
        r = cx.request.post(BASE + "?action=amapi_cmd&cmd=LOCK", form={"device_id": str(a[0])}, max_redirects=0)
        cm = calls("POST", "/devices/d111aaa:issueCommand")
        rec("blocco schermo inviato a Google", cm and cm[-1][2] == {"type": "LOCK"} and "msg=" in (r.headers.get("location") or ""), cm)
        r = cx.request.post(BASE + "?action=amapi_cmd&cmd=FORMAT", form={"device_id": str(a[0])}, max_redirects=0)
        rec("comando non consentito rifiutato", len(calls("POST", ":issueCommand")) == 1 and "msg=Comando+non+riuscito" in (r.headers.get("location") or ""), r.headers.get("location"))
        r = cx.request.post(BASE + "?action=amapi_cmd&cmd=WIPE", form={"device_id": str(a[0])}, max_redirects=0)
        rec("wipe inviato (admin)", calls("POST", "/devices/d111aaa:issueCommand")[-1][2] == {"type": "WIPE"})
        rec("audit dei comandi", q("SELECT COUNT(*) FROM audit WHERE action='amapi_cmd'")[0][0] == 3)
        html = page("")
        rec("pagina: 2 telefoni gestiti", ">2<" in html and "telefoni gestiti" in html)
        rec("pagina: link diretto al modulo quota Google", 'href="https://goo.gle/android-enterprise-response"' in html and "iam-admin/quotas?service=androidmanagement.googleapis.com" in html and "permissible-usage" in html)
        html = page("&err=" + urllib.parse.quote("The organization has reached its usage limits (HTTP 400)"))
        rec("errore di quota: riquadro con il modulo e l'ID progetto", "Serve la quota dispositivi di Google" in html and "goo.gle/android-enterprise-response" in html)
        sites_ = [r[0] for r in q("SELECT name FROM sites")]; ps = sites_[0] if sites_ else "Acme"
        html = page("&prep=1&psite=" + urllib.parse.quote(ps) + "&pname=Tel+prova&pos=android&pint=30")
        m_ = re.search(r'"id": "(ph-[0-9a-f]{20})"', html.replace("&quot;", '"')); tk_ = q("SELECT token FROM site_tokens WHERE site=? AND enabled=1 LIMIT 1", ps)
        rec("APK: due QR, scarico e configurazione", 'id="apkqr_dl"' in html and "1. Scarica l'APK" in html and "2. Configura l'app" in html)
        rec("APK: passi, QR e link di configurazione con il token del cliente", "App myrmm per Android" in html and 'id="apkqr"' in html and "action=mobile_setup" in html and (tk_[0][0] in html) and "Salva e avvia" in html)
        ap_ = urllib.request.urlopen(BASE + "?action=mobile_apk", timeout=15); bb_ = ap_.read()
        rec("APK scaricabile dal server, senza accesso alla console", ap_.status == 200 and ap_.headers.get("Content-Type") == "application/vnd.android.package-archive" and bb_[:2] == b"PK" and len(bb_) > 10000 and "action=mobile_apk" in html, (ap_.status, len(bb_)))
        rec("check-in pronto: JSON con token del cliente e id generato", bool(m_) and bool(tk_) and tk_[0][0] in html and "HTTP Shortcuts" in html and "Tel prova" in html, html[html.find("Alternativa"):][:300])
        if m_ and tk_:
            rq_ = urllib.request.Request(BASE + "?action=mobile_checkin", data=json.dumps({"token": tk_[0][0], "id": m_.group(1), "name": "Tel prova", "os": "android", "interval_min": 30}).encode(), headers={"Content-Type": "application/json"})
            rr_ = json.loads(urllib.request.urlopen(rq_, timeout=15).read())
            rec("il check-in con i dati generati registra il telefono", rr_.get("ok") is True and q("SELECT COUNT(*) FROM devices WHERE mobile_id=?", m_.group(1))[0][0] == 1, rr_)
        html = page("&err=" + urllib.parse.quote("Scegli un cliente."))
        rec("altri errori: nessun riquadro quota", "Serve la quota dispositivi di Google" not in html)
        html = page(""); rec("collegato: pulsante per scollegare con l'opzione sui telefoni", "Scollega Android Enterprise" in html and "elimina anche i telefoni importati" in html)
        nph = q("SELECT COUNT(*) FROM devices WHERE mobile_id LIKE 'amapi:%'")[0][0]
        r = post("amapi_disconnect")
        rec("scollega: rimosse chiave, enterprise, criteri e stato", q("SELECT COUNT(*) FROM meta WHERE k LIKE 'amapi:%'")[0][0] == 0, q("SELECT k FROM meta WHERE k LIKE 'amapi:%'"))
        rec("scollega senza opzione: i telefoni restano", q("SELECT COUNT(*) FROM devices WHERE mobile_id LIKE 'amapi:%'")[0][0] == nph and nph > 0)
        html = page(""); rec("dopo lo scollegamento: non collegato, scheda APK ancora presente", "Non collegato" in html and 'id="apkqr_dl"' in html and "Scollega Android Enterprise" not in html)
        rec("scollegamento nell'audit", q("SELECT COUNT(*) FROM audit WHERE action='amapi_disconnect'")[0][0] == 1)
        r = post("amapi_save", sa=json.dumps(SA), ent="enterprises/LC123"); r = post("amapi_disconnect", purge="1")
        rec("scollega con opzione: telefoni importati eliminati", q("SELECT COUNT(*) FROM devices WHERE mobile_id LIKE 'amapi:%'")[0][0] == 0 and q("SELECT COUNT(*) FROM meta WHERE k LIKE 'amapi:%'")[0][0] == 0)
        rec("nessun errore JS", not errs, errs[:3]); br.close()
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    bad = sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught", l)))[:10]
    rec("nessun errore PHP", not bad, bad)
finally:
    sp.terminate(); mock.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
f = [n for n, ok in res if not ok]
print(f"\n{len(res) - len(f)}/{len(res)} ok")
sys.exit(1 if f else 0)
