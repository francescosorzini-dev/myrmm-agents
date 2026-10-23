#!/usr/bin/env python3
"""Ordini dell'AI superiore (1.69.0): runbook, servizi, riavvio/spegnimento, patch, ticket e asset, pianificazioni e regole in lettura.
Approvazione fuori dal collaudo, riavvio sempre approvato da una persona, perimetro per cliente, password mai esposte, audit, parità sul connettore MCP remoto.
Uso: python3 ci/orders_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.error, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8837; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-ord-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
DB = os.path.join(srv, "data", "myrmm.sqlite")
res = []
def rec(name, ok, info=""):
    res.append((name, bool(ok))); print(("OK   " if ok else "FAIL ") + name + (("  [" + str(info)[:300] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def ts(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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
            if os.path.exists(DB) and sqlite3.connect(DB).execute("SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM sites),(SELECT COUNT(*) FROM ai_tasks),(SELECT COUNT(*) FROM api_tokens)").fetchone(): break
        except Exception: pass
        time.sleep(.3)
    now = ts()
    for n in ("Acme", "Collaudo"): q("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", n, now)
    q("UPDATE sites SET lab=1 WHERE name='Collaudo'")
    def addev(hn, site, os_, osname):
        q("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,full_inv,full_inv_at,created) VALUES(?,?,?,?,?,?,?,?,?)", hn, osname, "k-" + hn, site, now, json.dumps({"os": os_}), json.dumps({"software": [], "system": {"os": os_}}), now, now)
    addev("A-PC1", "Acme", "Windows 10 Pro", "windows"); addev("C-WIN", "Collaudo", "Windows 11 Pro", "windows")
    dev = {r[1]: r[0] for r in q("SELECT id,hostname FROM devices")}
    h2 = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
    q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('vis',?, 'viewer','',1,?,0)", h2, now)
    H = {"Origin": f"http://127.0.0.1:{PORT}"}

    def api(tok, r, method="GET", data=None, hdr="X-Api-Token", **params):
        qs = urllib.parse.urlencode(dict(params, action="api", r=r)); h_ = {hdr: tok} if hdr == "X-Api-Token" else {"Authorization": "Bearer " + tok}
        rq = urllib.request.Request(BASE + "?" + qs, data=json.dumps(data).encode() if data is not None else None, headers=dict(h_, **{"Content-Type": "application/json"}), method=method)
        try:
            with urllib.request.urlopen(rq, timeout=40) as f: return f.status, json.loads(f.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}
    def rpc(msg, url=None, hdr=None, raw=None):
        rq = urllib.request.Request(url or BASE, data=raw if raw is not None else json.dumps(msg).encode(), headers=dict(hdr or {}, **{"Content-Type": "application/json"}), method="POST")
        try:
            with urllib.request.urlopen(rq, timeout=60) as f: b = f.read(); return f.status, (json.loads(b) if b else None)
        except urllib.error.HTTPError as e:
            b = e.read()
            try: return e.code, json.loads(b)
            except Exception: return e.code, None
    def tool(url, name, args=None, i=1, hdr=None):
        st, j = rpc({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}, url, hdr)
        if st != 200 or not j or "result" not in j: return st, j
        return st, dict(json.loads(j["result"]["content"][0]["text"].split("\n\n")[0]), _err=j["result"].get("isError"))

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        c = br.new_context(viewport={"width": 1360, "height": 900}); p = c.new_page()
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        p.wait_for_selector("input[name=password]", timeout=5000); p.fill("input[name=password]", PW); p.click("button[type=submit]"); p.wait_for_selector(".rail", timeout=8000)
        errs = []; p.on("pageerror", lambda e: errs.append("JS: " + str(e))); p.on("dialog", lambda d: d.accept())
        def get(url): return c.request.get(BASE + url)
        def post(url, data): return c.request.post(BASE + url, data=urllib.parse.urlencode(data, doseq=True), headers=dict(H, **{"Content-Type": "application/x-www-form-urlencoded"}), max_redirects=0)
        def mk(**kw):
            c.clear_cookies(name="myrmm_apionce"); post("?action=api_new", kw)

            ck = [x for x in c.cookies() if x["name"] == "myrmm_apionce"]
            return ck[0]["value"] if ck else None
        addev("C-LNX", "Collaudo", "Ubuntu 24.04", "linux")
        dev = {r[1]: r[0] for r in q("SELECT id,hostname FROM devices")}
        SUP = mk(name="ai-sup", role="operator", write="2", days="30", **{"sites[]": ["Collaudo"]})
        ACM = mk(name="ai-acme", role="operator", write="1", days="30", **{"sites[]": ["Acme"]})
        ADM = mk(name="ai-tutti", role="operator", write="1", days="30")
        RO = mk(name="lettura", role="viewer", write="0", days="30")
        rec("token creati", all([SUP, ACM, ADM, RO]))
        URL = BASE + f"?action=mcp_http&t={SUP}"
        sc = [r[0] for r in q("SELECT id FROM scripts WHERE platform IN ('windows','any') ORDER BY id LIMIT 2")]
        q("INSERT INTO runbooks(name,description,steps,stop_on_fail,created,by_user) VALUES('Prova due passi','x',?,1,?,'t')", json.dumps([{"script_id": sc[0], "vars": {}}, {"script_id": sc[1], "vars": {}}]), now)
        q("INSERT INTO runbooks(name,description,steps,stop_on_fail,created,by_user) VALUES('Parte con attesa','x',?,1,?,'t')", json.dumps([{"wait_min": 5}, {"script_id": sc[0], "vars": {}}]), now)
        RB = q("SELECT id FROM runbooks WHERE name='Prova due passi'")[0][0]; RBW = q("SELECT id FROM runbooks WHERE name='Parte con attesa'")[0][0]
        def jobrow(jid): return q("SELECT status, origin, api_token, script FROM jobs WHERE id=?", jid)[0]

        # --- 1. runbook
        st, j = api(RO, "runbooks"); rec("runbook: elenco con passi e nomi script", st == 200 and any(r["name"] == "Prova due passi" and len(r["steps"]) == 2 and r["steps"][0]["script"] for r in j["runbooks"]), j)
        st, j = api(SUP, "runbook_run", "POST", {"device_id": dev["C-WIN"], "runbook_id": RB})
        rec("runbook sul collaudo: parte subito", st == 200 and j["status"] == "pending" and j["steps"] == 2, (st, j))
        r_ = jobrow(j["job_id"]); rec("runbook: il primo passo è del token e della sequenza", r_[0] == "pending" and r_[1].startswith("seq:") and r_[2] > 0, r_)
        st, j2 = api(ACM, "runbook_run", "POST", {"device_id": dev["A-PC1"], "runbook_id": RB})
        rec("runbook su cliente reale: in attesa di approvazione", st == 200 and j2["status"] == "held" and jobrow(j2["job_id"])[0] == "held", (st, j2))
        post("?action=api_hold_ok", {"id": j2["job_id"]}); rec("approvazione umana: il primo passo diventa pending", jobrow(j2["job_id"])[0] == "pending")
        rec("runbook: sola lettura 403", api(RO, "runbook_run", "POST", {"device_id": dev["C-WIN"], "runbook_id": RB})[0] == 403)
        rec("runbook: device fuori perimetro 404", api(SUP, "runbook_run", "POST", {"device_id": dev["A-PC1"], "runbook_id": RB})[0] == 404)
        rec("runbook: inesistente 404", api(SUP, "runbook_run", "POST", {"device_id": dev["C-WIN"], "runbook_id": 9999})[0] == 404)
        rec("runbook che inizia con un'attesa: 422", api(SUP, "runbook_run", "POST", {"device_id": dev["C-WIN"], "runbook_id": RBW})[0] == 422)

        # --- 2. servizi e riavvio
        st, j = api(SUP, "service", "POST", {"device_id": dev["C-WIN"], "service": "Spooler", "op": "restart"})
        rec("servizio: restart sul collaudo parte subito", st == 200 and j["status"] == "pending" and "Restart-Service -Name 'Spooler' -Force" in jobrow(j["job_id"])[3] and jobrow(j["job_id"])[1] == "svc:restart", (st, j))
        st, j = api(SUP, "service", "POST", {"device_id": dev["C-WIN"], "service": "x'; calc; '", "op": "stop"})
        rec("servizio: gli apici sono raddoppiati (nessuna iniezione)", st == 200 and "-Name 'x''; calc; '''" in jobrow(j["job_id"])[3], (st, j))
        rec("servizio: operazione non valida 422", api(SUP, "service", "POST", {"device_id": dev["C-WIN"], "service": "Spooler", "op": "format"})[0] == 422)
        rec("servizio: nome con a capo 422", api(SUP, "service", "POST", {"device_id": dev["C-WIN"], "service": "a\nb", "op": "stop"})[0] == 422)
        rec("servizio: nome vuoto 422", api(SUP, "service", "POST", {"device_id": dev["C-WIN"], "service": "", "op": "stop"})[0] == 422)
        st, j = api(SUP, "service", "POST", {"device_id": dev["C-LNX"], "service": "nginx", "op": "restart"})
        rec("servizio Linux: systemctl con nome tra apici", st == 200 and "systemctl restart 'nginx'" in jobrow(j["job_id"])[3], (st, j))
        st, j = api(ACM, "service", "POST", {"device_id": dev["A-PC1"], "service": "Spooler", "op": "start"})
        rec("servizio su cliente reale: in attesa di approvazione", st == 200 and j["status"] == "held", (st, j))
        rec("servizio: sola lettura 403", api(RO, "service", "POST", {"device_id": dev["C-WIN"], "service": "Spooler", "op": "start"})[0] == 403)
        st, j = api(SUP, "power", "POST", {"device_id": dev["C-WIN"], "op": "reboot", "minutes": 2, "message": "Manutenzione; \"x\""})
        rec("riavvio: SEMPRE in attesa di approvazione, anche sul collaudo", st == 200 and j["status"] == "held" and "shutdown.exe /r /t 120" in jobrow(j["job_id"])[3] and '"x"' not in jobrow(j["job_id"])[3], (st, j))
        st, j = api(SUP, "power", "POST", {"device_id": dev["C-WIN"], "op": "shutdown"}); rec("spegnimento: sempre in attesa", st == 200 and j["status"] == "held" and "/s /t 300" in jobrow(j["job_id"])[3], (st, j))
        st, j = api(SUP, "power", "POST", {"device_id": dev["C-WIN"], "op": "cancel"}); rec("annullamento: parte subito", st == 200 and j["status"] == "pending" and "shutdown.exe /a" in jobrow(j["job_id"])[3], (st, j))
        st, j = api(SUP, "power", "POST", {"device_id": dev["C-LNX"], "op": "reboot", "minutes": 99999}); rec("riavvio Linux: minuti limitati a 1440", st == 200 and "shutdown -r +1440" in jobrow(j["job_id"])[3], (st, j))
        rec("riavvio: operazione non valida 422", api(SUP, "power", "POST", {"device_id": dev["C-WIN"], "op": "halt"})[0] == 422)
        rec("riavvio: sola lettura 403", api(RO, "power", "POST", {"device_id": dev["C-WIN"], "op": "reboot"})[0] == 403)

        # --- 3. patch
        u1, u2, u3 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"
        for u, kb in ((u1, "KB1"), (u2, "KB2"), (u3, "KB3")):
            q("INSERT INTO patches(device_id,uid,kb,title,severity,category,mb,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?)", dev["C-WIN"], u, kb, "Patch " + kb, "Critical", "Security", 10, "available", now, now)
        q("INSERT INTO patch_approvals(uid,decision,kb,title,decided,by_user) VALUES(?,?,?,?,?,?)", u3, "declined", "KB3", "t", now, "t")
        st, j = api(RO, "patches", device_id=dev["C-WIN"]); rec("patch: elenco con decisione", st == 200 and len(j["patches"]) == 3 and {p["decision"] for p in j["patches"]} == {"", "declined"}, j)
        rec("patch: device fuori perimetro 404", api(SUP, "patches", device_id=dev["A-PC1"])[0] == 404)
        st, j = api(SUP, "patch_scan", "POST", {"device_id": dev["C-WIN"]}); rec("scansione patch: parte subito", st == 200 and j["status"] == "pending" and jobrow(j["job_id"])[1] == "patchscan", (st, j))
        rec("scansione patch doppia: 409", api(SUP, "patch_scan", "POST", {"device_id": dev["C-WIN"]})[0] == 409)
        rec("scansione patch su Linux: 422", api(SUP, "patch_scan", "POST", {"device_id": dev["C-LNX"]})[0] == 422)
        st, j = api(SUP, "patch_install", "POST", {"device_id": dev["C-WIN"]})
        rec("installa patch: esclude le rifiutate, le altre risultano in coda", st == 200 and j["patches"] == 2 and j["status"] == "pending" and {r[0] for r in q("SELECT status FROM patches WHERE device_id=? AND uid IN (?,?)", dev["C-WIN"], u1, u2)} == {"queued"} and q("SELECT status FROM patches WHERE uid=? AND device_id=?", u3, dev["C-WIN"])[0][0] == "available", (st, j))
        rec("installa patch doppia: 409", api(SUP, "patch_install", "POST", {"device_id": dev["C-WIN"]})[0] == 409)
        rec("installa patch: niente da installare 422", api(ACM, "patch_install", "POST", {"device_id": dev["A-PC1"]})[0] == 422)
        q("INSERT INTO patches(device_id,uid,kb,title,severity,category,mb,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?)", dev["A-PC1"], u1, "KB1", "P", "Critical", "Security", 1, "available", now, now)
        st, j = api(ACM, "patch_install", "POST", {"device_id": dev["A-PC1"], "uids": [u1, "non-un-guid"]})
        rec("installa patch su cliente reale: in attesa e patch non ancora in coda", st == 200 and j["status"] == "held" and q("SELECT status FROM patches WHERE device_id=?", dev["A-PC1"])[0][0] == "available", (st, j))

        # --- 4. ticket e asset
        st, t1 = api(SUP, "ticket_create", "POST", {"title": "Disco pieno su C-WIN", "device_id": dev["C-WIN"], "priority": "high", "note": "Aperto dall'AI dopo l'alert."})
        rec("ticket: creato su device con codice", st == 200 and t1["id"] and t1["code"] and t1["site"] == "Collaudo", (st, t1))
        rec("ticket: titolo mancante 422", api(SUP, "ticket_create", "POST", {"device_id": dev["C-WIN"]})[0] == 422)
        rec("ticket: senza device né cliente 422", api(SUP, "ticket_create", "POST", {"title": "x"})[0] == 422)
        rec("ticket: device fuori perimetro 404", api(SUP, "ticket_create", "POST", {"title": "x", "device_id": dev["A-PC1"]})[0] == 404)
        rec("ticket: cliente fuori perimetro 403", api(SUP, "ticket_create", "POST", {"title": "x", "site": "Acme"})[0] == 403)
        rec("ticket: sola lettura 403", api(RO, "ticket_create", "POST", {"title": "x", "site": "Collaudo"})[0] == 403)
        st, t2 = api(SUP, "ticket_create", "POST", {"title": "Su cliente", "site": "Collaudo"}); rec("ticket: su un cliente senza device", st == 200, (st, t2))
        st, tl = api(SUP, "tickets"); rec("ticket: elenco aperti", st == 200 and {t["title"] for t in tl["tickets"]} >= {"Disco pieno su C-WIN", "Su cliente"} and any(t["hostname"] == "C-WIN" for t in tl["tickets"]), tl)
        rec("ticket: Acme non vede quelli del collaudo", api(ACM, "tickets")[1]["tickets"] == [] and api(ACM, "ticket", id=t1["id"])[0] == 404)
        st, tg = api(SUP, "ticket", id=t1["id"]); rec("ticket: scheda con le note", st == 200 and tg["priority"] == "high" and any("alert" in n["body"] for n in tg["notes"]), tg)
        st, n_ = api(SUP, "ticket_note", "POST", {"id": t1["id"], "text": "Pulizia eseguita, 12 GB liberati.", "minutes": 7}); rec("ticket: nota con tempo", st == 200 and api(SUP, "ticket", id=t1["id"])[1]["minutes"] == 7, (st, n_))
        rec("ticket: nota vuota 422", api(SUP, "ticket_note", "POST", {"id": t1["id"], "text": " "})[0] == 422)
        rec("ticket: nota su ticket altrui 404", api(ACM, "ticket_note", "POST", {"id": t1["id"], "text": "x"})[0] == 404)
        q("UPDATE tickets SET status='closed' WHERE id=?", t2["id"]); rec("ticket chiuso: nessuna nota (409)", api(SUP, "ticket_note", "POST", {"id": t2["id"], "text": "x"})[0] == 409)
        rec("ticket: filtro chiusi", {t["id"] for t in api(SUP, "tickets", status="closed")[1]["tickets"]} == {t2["id"]})
        q("INSERT INTO asset_types(name,fields,position,created) VALUES('Server',?,1,?)", json.dumps([{"k": "ip", "l": "Indirizzo IP", "t": "text"}, {"k": "rdp", "l": "Password RDP", "t": "password"}, {"k": "garanzia", "l": "Garanzia", "t": "date"}]), now)
        st, ty = api(SUP, "assets", types=1); rec("asset: tipi con campi, senza i campi password", st == 200 and ty["types"][0]["name"] == "Server" and [f["key"] for f in ty["types"][0]["fields"]] == ["ip", "garanzia"], ty)
        tyid = ty["types"][0]["id"]
        st, a1 = api(SUP, "asset_create", "POST", {"type": "server", "name": "SRV-ZANONI", "site": "Collaudo", "serial": "SN1", "expiry": "2027-05-01", "fields": {"ip": "10.0.0.5", "rdp": "segretissima", "garanzia": "boh"}})
        rec("asset: creato (tipo per nome)", st == 200 and a1["id"], (st, a1))
        raw = q("SELECT data FROM assets WHERE id=?", a1["id"])[0][0]; rec("asset: la password inviata non viene salvata", "segretissima" not in raw and "rdp" not in raw and "10.0.0.5" in raw and "garanzia" not in raw, raw)
        q("UPDATE assets SET data=? WHERE id=?", json.dumps({"ip": "10.0.0.5", "rdp": "e:CIFRATA"}), a1["id"])
        st, ag = api(SUP, "asset", id=a1["id"]); rec("asset: la scheda non mostra mai le password", st == 200 and ag["fields"] == {"Indirizzo IP": "10.0.0.5"} and "CIFRATA" not in json.dumps(ag), ag)
        rec("asset: elenco con ricerca", [a["name"] for a in api(SUP, "assets", q="zanoni")[1]["assets"]] == ["SRV-ZANONI"])
        rec("asset: Acme non lo vede", api(ACM, "asset", id=a1["id"])[0] == 404 and api(ACM, "assets")[1]["assets"] == [])
        rec("asset: tipo sconosciuto 422", api(SUP, "asset_create", "POST", {"type": "Boh", "name": "x", "site": "Collaudo"})[0] == 422)
        rec("asset: cliente fuori perimetro 403", api(SUP, "asset_create", "POST", {"type_id": tyid, "name": "x", "site": "Acme"})[0] == 403)
        rec("asset: senza cliente 422", api(SUP, "asset_create", "POST", {"type_id": tyid, "name": "x"})[0] == 422)
        rec("asset: device di altro cliente 422", api(ADM, "asset_create", "POST", {"type_id": tyid, "name": "x", "site": "Acme", "device_id": dev["C-WIN"]})[0] == 422)
        rec("asset: sola lettura 403", api(RO, "asset_create", "POST", {"type_id": tyid, "name": "x", "site": "Collaudo"})[0] == 403)

        # --- 5. pianificazioni e regole
        q("INSERT INTO schedules(device_id,script_id,vars,interval_min,enabled,next_run,created) VALUES(?,?,?,?,1,?,?)", dev["C-WIN"], sc[0], "{}", 60, now, now)
        q("INSERT INTO schedules(device_id,script_id,vars,interval_min,enabled,next_run,created) VALUES(?,?,?,?,1,?,?)", dev["A-PC1"], sc[0], "{}", 30, now, now)
        q("INSERT INTO rules(name,filter_id,script_id,vars,interval_min,monitor_sev,response_script_id,enabled,created) VALUES('Regola prova',0,?, '{}',15,'warn',0,1,?)", sc[0], now)
        st, j = api(SUP, "schedules"); rec("pianificazioni: solo quelle del proprio perimetro", st == 200 and [x["hostname"] for x in j["schedules"]] == ["C-WIN"] and j["schedules"][0]["every_min"] == 60 and j["schedules"][0]["script"], j)
        rec("regole: token limitato a un cliente 403", api(SUP, "rules")[0] == 403)
        st, j = api(ADM, "rules"); rec("regole: token senza limiti le legge", st == 200 and j["rules"][0]["name"] == "Regola prova" and j["rules"][0]["all_devices"], j)
        rec("pianificazioni: sola lettura ammessa", api(RO, "schedules")[0] == 200)

        # --- 6. connettore MCP remoto
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, URL); names = [t["name"] for t in j["result"]["tools"]]
        rec("MCP remoto: 40 strumenti con quelli degli ordini", len(names) == 40 and {"myrmm_run_runbook", "myrmm_service", "myrmm_power", "myrmm_patch_install", "myrmm_create_ticket", "myrmm_create_asset", "myrmm_list_rules"} <= set(names), names)
        st, j = tool(URL, "myrmm_service", {"device_id": dev["C-WIN"], "service": "Spooler", "op": "restart", "wait": 0}, 2); rec("MCP remoto: servizio sul collaudo", st == 200 and j["status"] == "pending" and not j["_err"], j)
        st, j = tool(URL, "myrmm_power", {"device_id": dev["C-WIN"], "op": "reboot"}, 3); rec("MCP remoto: riavvio in attesa di approvazione", st == 200 and j["status"] == "held" and "approval" in j["note"], j)
        st, j = tool(URL, "myrmm_create_ticket", {"title": "Via MCP", "device_id": dev["C-WIN"]}, 4); rec("MCP remoto: apre un ticket", st == 200 and j.get("code"), j)
        st, j = tool(URL, "myrmm_list_runbooks", {}, 5); rec("MCP remoto: elenca i runbook", st == 200 and len(j["runbooks"]) == 2, j)
        st, j = tool(URL, "myrmm_service", {"device_id": dev["C-WIN"], "service": "Spooler", "op": "nope"}, 6); rec("MCP remoto: errore del server riportato come isError", st == 200 and j["_err"] is True, j)
        st, j = tool(BASE + f"?action=mcp_http&t={RO}", "myrmm_power", {"device_id": dev["C-WIN"], "op": "reboot"}, 7); rec("MCP remoto: sola lettura non ordina", st == 200 and j["_err"] is True, j)

        # --- 7. audit e anomalie
        acts = {r[0] for r in q("SELECT DISTINCT action FROM audit")}
        rec("audit: ogni ordine ha la sua voce", {"api_runbook", "api_service", "api_power", "api_patch_scan", "api_patch_install", "api_ticket_new", "api_ticket_note", "api_asset_new"} <= acts, acts)
        rec("audit: le password non compaiono", not any("segretissima" in (r[0] or "") for r in q("SELECT detail FROM audit")))
        pe = open(os.path.join(tmp, "php.err")).read()
        rec("nessun errore PHP", not any(k in pe for k in ("Fatal error", "Warning:", "Notice:", "Deprecated:", "Uncaught")), pe[-600:])
        br.close()
finally:
    try:
        e_ = open(os.path.join(tmp, 'php.err')).read()
        if e_.strip(): print('--- php.err ---\n' + e_[-1500:])
    except Exception: pass
    sp.terminate()
    shutil.rmtree(tmp, ignore_errors=True)
ok = sum(1 for _, o in res if o)
print(f"\n{ok} ok, {len(res) - ok} falliti"); sys.exit(0 if ok == len(res) else 1)
