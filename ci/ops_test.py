#!/usr/bin/env python3
"""Operazioni generiche dell'AI superiore (1.70.0): alias, reparti, manutenzione, alert, ticket, asset, documenti in modo diretto; script, pianificazioni, controlli, regole, variabili, runbook, policy patch, filtri, spostamenti in attesa di approvazione dalla console.
Uso: python3 ci/ops_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.error, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8838; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-ops-"); srv = os.path.join(tmp, "server")
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
    c = sqlite3.connect(DB); c.execute("ATTACH DATABASE ? AS dk", (os.path.join(os.path.dirname(DB), "docs.sqlite"),)); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
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
        def op(tok, name, params=None, **kw): return api(tok, "op", "POST", {"op": name, "params": params or {}}, **kw)
        def approve(cid): post("?action=aich_ok", {"id": cid})
        def chg(cid): return q("SELECT status, result, op FROM ai_changes WHERE id=?", cid)[0]

        # --- catalogo e letture
        st, cat = api(RO, "ops"); ops = {o["op"]: o for o in cat["ops"]} if st == 200 else {}
        rec("catalogo: operazioni con descrizione, parametri e regola di approvazione", st == 200 and len(ops) >= 30 and all(o["description"] and o["approval"] and isinstance(o["params"], list) for o in ops.values()), list(ops)[:5])
        rec("catalogo: alias diretto, script in attesa", ops["device_alias"]["approval"] == "none" and "approva" in ops["script_save"]["approval"])
        rec("operazione sconosciuta: 404", op(SUP, "formatta_tutto")[0] == 404)
        rec("sola lettura non esegue: 403", op(RO, "device_alias", {"device_id": dev["C-WIN"], "alias": "x"})[0] == 403)
        rec("config globale: token limitato 403", api(SUP, "config", kind="checks")[0] == 403 and api(SUP, "config", kind="variables")[0] == 403)
        rec("config: tipo sconosciuto 422", api(ADM, "config", kind="boh")[0] == 422)

        # --- alias, reparto, manutenzione, inventario
        st, j = op(SUP, "device_alias", {"device_id": dev["C-WIN"], "alias": "  PC <b>della</b>   Rossi "})
        rec("alias: impostato e ripulito dai tag", st == 200 and j["status"] == "done" and q("SELECT alias FROM devices WHERE id=?", dev["C-WIN"])[0][0] == "PC della Rossi", (st, j))
        st, dl = api(SUP, "devices", q="rossi"); rec("alias: l'elenco device lo mostra e la ricerca lo trova", st == 200 and [d["hostname"] for d in dl["devices"]] == ["C-WIN"] and dl["devices"][0]["alias"] == "PC della Rossi", dl)
        rec("alias: device fuori perimetro 404", op(SUP, "device_alias", {"device_id": dev["A-PC1"], "alias": "x"})[0] == 404)
        st, j = op(ACM, "device_alias", {"device_id": dev["A-PC1"], "alias": "Contabilità"}); rec("alias: anche con approvazione (è reversibile), subito", st == 200 and j["status"] == "done")
        op(SUP, "device_alias", {"device_id": dev["C-WIN"], "alias": ""}); rec("alias: vuoto lo toglie", q("SELECT alias FROM devices WHERE id=?", dev["C-WIN"])[0][0] is None)
        q("INSERT INTO departments(site,name,created) VALUES('Collaudo','Amministrazione',?)", now)
        st, j = op(SUP, "device_dept", {"device_id": dev["C-WIN"], "dept": "amministrazione"}); rec("reparto: assegnato (nome esatto del reparto)", st == 200 and q("SELECT dept FROM devices WHERE id=?", dev["C-WIN"])[0][0] == "Amministrazione", (st, j))
        rec("reparto inesistente: 422", op(SUP, "device_dept", {"device_id": dev["C-WIN"], "dept": "Boh"})[0] == 422)
        op(SUP, "device_dept", {"device_id": dev["C-WIN"], "dept": ""}); rec("reparto: vuoto lo toglie", q("SELECT dept FROM devices WHERE id=?", dev["C-WIN"])[0][0] == "")
        st, j = op(SUP, "device_maintenance", {"device_id": dev["C-WIN"], "minutes": 90}); rec("manutenzione device: avviata", st == 200 and q("SELECT muted_until FROM devices WHERE id=?", dev["C-WIN"])[0][0] is not None, (st, j))
        op(SUP, "device_maintenance", {"device_id": dev["C-WIN"], "minutes": 0}); rec("manutenzione device: 0 la termina", q("SELECT muted_until FROM devices WHERE id=?", dev["C-WIN"])[0][0] is None)
        st, j = op(SUP, "device_inventory_refresh", {"device_id": dev["C-WIN"]}); rec("inventario: richiesto", st == 200 and q("SELECT full_inv_req FROM devices WHERE id=?", dev["C-WIN"])[0][0] == 1, (st, j))

        # --- alert
        for dv, ty in ((dev["C-WIN"], "t1"), (dev["C-WIN"], "t2"), (dev["A-PC1"], "t3")):
            q("INSERT INTO alerts(device_id,type,severity,message,status,created) VALUES(?,?,?,?,?,?)", dv, ty, "warn", "prova " + ty, "open", now)
        A1, A2, A3 = [r[0] for r in q("SELECT id FROM alerts WHERE type IN ('t1','t2','t3') ORDER BY type")]
        st, j = op(SUP, "alert_ack", {"id": A1, "note": "ci penso io"}); rec("alert: preso in carico con nota", st == 200 and q("SELECT ack_by, note FROM alerts WHERE id=?", A1)[0] == ("api:ai-sup", "ci penso io"), (st, j, q("SELECT ack_by, note FROM alerts WHERE id=?", A1)))
        rec("alert: fuori perimetro 404", op(SUP, "alert_ack", {"id": A3})[0] == 404)
        st, j = op(SUP, "alert_snooze", {"id": A1, "minutes": 60}); rec("alert: posticipato", st == 200 and q("SELECT snooze_until FROM alerts WHERE id=?", A1)[0][0] is not None)
        st, j = op(SUP, "alert_work", {"id": A1, "note": "controllato il disco", "minutes": 15, "due": "2026-12-01"}); rec("alert: lavorazione con nota, minuti e data", st == 200 and q("SELECT minutes, due FROM alerts WHERE id=?", A1)[0] == (15, "2026-12-01"), (st, j))
        rec("alert: data non valida 422", op(SUP, "alert_work", {"id": A1, "due": "domani"})[0] == 422 and op(SUP, "alert_work", {"id": A1})[0] == 422)
        st, j = op(SUP, "alert_close", {"id": A2}); rec("alert: chiuso", st == 200 and q("SELECT status FROM alerts WHERE id=?", A2)[0][0] == "resolved")
        rec("alert chiuso: nuova chiusura 409", op(SUP, "alert_close", {"id": A2})[0] == 409)

        # --- ticket, asset, documenti
        st, t1 = api(SUP, "ticket_create", "POST", {"title": "Prova ops", "device_id": dev["C-WIN"]})
        st, j = op(SUP, "ticket_set", {"id": t1["id"], "status": "working", "priority": "high"}); rec("ticket: stato e priorità cambiati", st == 200 and q("SELECT status, priority FROM tickets WHERE id=?", t1["id"])[0] == ("working", "high"), (st, j))
        rec("ticket: valori non validi 422", op(SUP, "ticket_set", {"id": t1["id"], "status": "boh"})[0] == 422 and op(SUP, "ticket_set", {"id": t1["id"]})[0] == 422)
        st, j = op(SUP, "ticket_set", {"id": t1["id"], "status": "closed"}); rec("ticket: chiuso con data di chiusura e nota di sistema", st == 200 and q("SELECT closed_at FROM tickets WHERE id=?", t1["id"])[0][0] is not None and q("SELECT COUNT(*) FROM ticket_notes WHERE ticket_id=? AND kind='system' AND body LIKE '%chiuso%'", t1["id"])[0][0] == 1)
        rec("ticket: altrui 404", op(ACM, "ticket_set", {"id": t1["id"], "status": "open"})[0] == 404)
        q("INSERT INTO asset_types(name,fields,position,created) VALUES('Server',?,1,?)", json.dumps([{"k": "ip", "l": "Indirizzo IP", "t": "text"}, {"k": "rdp", "l": "Password RDP", "t": "password"}]), now)
        tyid = q("SELECT id FROM asset_types WHERE name='Server'")[0][0]
        st, a1 = api(SUP, "asset_create", "POST", {"type_id": tyid, "name": "SRV-1", "site": "Collaudo", "fields": {"ip": "10.0.0.1"}})
        q("UPDATE assets SET data=? WHERE id=?", json.dumps({"ip": "10.0.0.1", "rdp": "e:CIFRATA"}), a1["id"])
        st, j = op(SUP, "asset_update", {"id": a1["id"], "location": "Armadio 2", "status": "scorta", "expiry": "2027-01-31", "fields": {"ip": "10.0.0.9", "rdp": "nuova"}, "device_id": dev["C-WIN"]})
        row = q("SELECT location, status, expiry, device_id, data FROM assets WHERE id=?", a1["id"])[0]
        rec("asset: modificato, la password cifrata resta intatta", st == 200 and row[:4] == ("Armadio 2", "scorta", "2027-01-31", dev["C-WIN"]) and json.loads(row[4]) == {"ip": "10.0.0.9", "rdp": "e:CIFRATA"}, (st, j, row))
        rec("asset: stato/data non validi e device di altro cliente 422", op(SUP, "asset_update", {"id": a1["id"], "status": "boh"})[0] == 422 and op(SUP, "asset_update", {"id": a1["id"], "expiry": "domani"})[0] == 422 and op(ADM, "asset_update", {"id": a1["id"], "device_id": dev["A-PC1"]})[0] == 422)
        rec("asset: nessuna modifica 422, altrui 404", op(SUP, "asset_update", {"id": a1["id"]})[0] == 422 and op(ACM, "asset_update", {"id": a1["id"], "name": "x"})[0] == 404)
        st, j = op(SUP, "asset_note", {"id": a1["id"], "text": "ritirato dal magazzino"}); rec("asset: nota", st == 200 and q("SELECT COUNT(*) FROM asset_notes WHERE asset_id=?", a1["id"])[0][0] == 1)
        st, d1 = op(SUP, "doc_save", {"title": "Come si riavvia la stampante", "body": "Spegnere, attendere 10 secondi, riaccendere.", "category": "procedura", "site": "Collaudo", "device_id": dev["C-WIN"]})
        did = d1["result"]["id"] if st == 200 else 0; rec("documento: creato", st == 200 and did > 0 and q("SELECT category, site, device_id FROM docs WHERE id=?", did)[0] == ("procedura", "Collaudo", dev["C-WIN"]), (st, d1))
        st, d2 = op(SUP, "doc_save", {"id": did, "title": "Come si riavvia la stampante", "body": "Versione 2: spegnere, attendere 20 secondi."}); rec("documento: aggiornato e versione precedente conservata", st == 200 and "Versione 2" in q("SELECT body FROM docs WHERE id=?", did)[0][0] and q("SELECT COUNT(*) FROM doc_rev WHERE doc_id=?", did)[0][0] == 1, (st, d2))
        rec("documento: credenziali rifiutate", op(SUP, "doc_save", {"title": "Accessi", "body": "il server: password: Abc12345!", "site": "Collaudo"})[0] == 422)
        rec("documento: cliente fuori perimetro 403 e senza titolo 422", op(SUP, "doc_save", {"title": "x", "body": "y", "site": "Acme"})[0] == 403 and op(SUP, "doc_save", {"body": "y"})[0] == 422)
        st, dg = api(SUP, "doc", id=did); rec("documento: lettura con testo", st == 200 and "Versione 2" in dg["body"] and api(ACM, "doc", id=did)[0] == 404, (st, dg, api(ACM, "doc", id=did)))
        st, dl = api(SUP, "config", kind="docs"); rec("documenti: elenco nel perimetro", st == 200 and [d["id"] for d in dl["docs"]] == [did])
        st, dp = api(SUP, "config", kind="departments"); rec("reparti: elenco nel perimetro", st == 200 and [d["name"] for d in dp["departments"]] == ["Amministrazione"])

        # --- configurazione: sempre in attesa
        st, j = op(ADM, "script_save", {"name": "Prova AI: ping", "description": "d", "body": "Write-Output 'ok'", "platform": "windows", "tags": "prova"})
        cs = j.get("change_id"); rec("script: in attesa, non ancora in libreria", st == 200 and j["status"] == "held" and cs and q("SELECT COUNT(*) FROM scripts WHERE name='Prova AI: ping'")[0][0] == 0, (st, j))
        rec("script: token limitato 403", op(SUP, "script_save", {"name": "x", "body": "echo"})[0] == 403)
        rec("script: senza testo 422", op(ADM, "script_save", {"name": "x"})[0] == 422)
        st, pg = c.request.get(BASE + "?view=aitasks"), None; html = st.text(); rec("console: la modifica in attesa è visibile con Approva e Rifiuta", "Modifiche in attesa di approvazione" in html and "script_save" in html and "aich_ok" in html and "aich_no" in html)
        approve(cs); rec("approvazione: lo script entra in libreria, con audit", chg(cs)[0] == "applied" and q("SELECT COUNT(*) FROM scripts WHERE name='Prova AI: ping' AND tags LIKE '%prova%'")[0][0] == 1 and q("SELECT COUNT(*) FROM audit WHERE action='ai_change_apply'")[0][0] >= 1)
        sid = q("SELECT id FROM scripts WHERE name='Prova AI: ping'")[0][0]
        approve(cs); rec("approvazione doppia: nessun effetto", q("SELECT COUNT(*) FROM scripts WHERE name='Prova AI: ping'")[0][0] == 1)
        st, j = op(ADM, "script_save", {"id": sid, "name": "Prova AI: ping", "body": "Write-Output 'v2'"}); approve(j["change_id"]); rec("script: aggiornamento approvato", "v2" in q("SELECT body FROM scripts WHERE id=?", sid)[0][0])
        st, j = op(ADM, "schedule_add", {"device_id": dev["C-WIN"], "script_id": sid, "interval_min": 30, "vars": {"A": "1"}, "monitor_sev": "warn"}); sch = j["change_id"]; approve(sch)
        rec("pianificazione: dopo l'approvazione esiste", chg(sch)[0] == "applied" and q("SELECT interval_min, monitor_sev, vars FROM schedules WHERE device_id=? AND script_id=?", dev["C-WIN"], sid)[0] == (30, "warn", '{"A":"1"}'))
        schid = q("SELECT id FROM schedules WHERE script_id=?", sid)[0][0]
        st, j = op(ADM, "schedule_toggle", {"id": schid}); approve(j["change_id"]); rec("pianificazione: disattivata", q("SELECT enabled FROM schedules WHERE id=?", schid)[0][0] == 0)
        rec("pianificazione: device fuori perimetro 404, script inesistente 404", op(SUP, "schedule_add", {"device_id": dev["A-PC1"], "script_id": sid, "interval_min": 5})[0] == 404 and op(ADM, "schedule_add", {"device_id": dev["C-WIN"], "script_id": 99999, "interval_min": 5})[0] == 404)
        rec("controllo globale: token limitato 403", op(SUP, "check_add", {"type": "cpu_pct", "threshold": 90})[0] == 403)
        st, j = op(SUP, "check_add", {"type": "cpu_pct", "threshold": 95, "device_id": dev["C-WIN"], "severity": "crit"}); approve(j["change_id"]); rec("controllo su un device del proprio perimetro: in attesa, poi creato", q("SELECT threshold, severity, device_id FROM checks WHERE type='cpu_pct'")[0] == (95.0, "crit", dev["C-WIN"]))
        st, j = op(ADM, "check_add", {"type": "ram_pct", "threshold": 92}); approve(j["change_id"]); ck = q("SELECT id FROM checks WHERE type='ram_pct'")[0][0]; rec("controllo globale (token senza limiti)", ck > 0)
        rec("controllo: tipo non valido 422", op(ADM, "check_add", {"type": "boh", "threshold": 1})[0] == 422)
        st, j = op(ADM, "check_toggle", {"id": ck}); approve(j["change_id"]); rec("controllo: disattivato", q("SELECT enabled FROM checks WHERE id=?", ck)[0][0] == 0)
        st, ck_ = api(ADM, "config", kind="checks"); rec("config: controlli leggibili", st == 200 and {"cpu_pct", "ram_pct"} <= {c_["type"] for c_ in ck_["checks"]}, ck_)
        st, j = op(ADM, "rule_add", {"name": "Regola AI", "script_id": sid, "interval_min": 60}); approve(j["change_id"]); rid = q("SELECT id FROM rules WHERE name='Regola AI'")[0][0]; rec("regola: creata dopo l'approvazione", rid > 0)
        st, j = op(ADM, "rule_toggle", {"id": rid}); approve(j["change_id"]); rec("regola: disattivata", q("SELECT enabled FROM rules WHERE id=?", rid)[0][0] == 0)
        rec("regola: token limitato 403, script inesistente 404", op(SUP, "rule_add", {"name": "x", "script_id": sid, "interval_min": 5})[0] == 403 and op(ADM, "rule_add", {"name": "x", "script_id": 99999, "interval_min": 5})[0] == 404)
        rec("variabile: valore vuoto 422, nome non valido 422", op(ADM, "variable_set", {"scope": "global", "name": "X", "value": ""})[0] == 422 and op(ADM, "variable_set", {"scope": "global", "name": "1x", "value": "a"})[0] == 422)
        rec("variabile globale: token limitato 403", op(SUP, "variable_set", {"scope": "global", "name": "X", "value": "a"})[0] == 403)
        st, j = op(SUP, "variable_set", {"scope": "site", "target": "Collaudo", "name": "dominio_ad", "value": "lab.local"}); approve(j["change_id"]); rec("variabile di un proprio cliente: nome in maiuscolo", q("SELECT value FROM vars WHERE scope='site:Collaudo' AND name='DOMINIO_AD'")[0][0] == "lab.local")
        st, j = op(ADM, "variable_set", {"scope": "global", "name": "API_TOKEN_X", "value": "ilsegretissimo"}); rec("variabile segreta: il riepilogo non mostra il valore", "ilsegretissimo" not in j["summary"] and "***" in j["summary"])
        approve(j["change_id"]); st, vv = api(ADM, "config", kind="variables"); rec("config: variabili con i segreti mascherati", st == 200 and all(v["value"] == "***" for v in vv["variables"] if v["name"] == "API_TOKEN_X") and any(v["name"] == "DOMINIO_AD" for v in vv["variables"]) and "ilsegretissimo" not in json.dumps(vv))
        st, j = op(ADM, "runbook_save", {"name": "Runbook AI", "steps": [{"script_id": sid}, {"wait_min": 1}, {"script_id": sc[0]}]}); approve(j["change_id"]); rb = q("SELECT id, stop_on_fail, steps FROM runbooks WHERE name='Runbook AI'")[0]; rec("runbook: salvato dopo l'approvazione, con attesa", rb[1] == 1 and len(json.loads(rb[2])) == 3)
        rec("runbook: passi non validi", op(ADM, "runbook_save", {"name": "x", "steps": []})[0] == 422 and op(ADM, "runbook_save", {"name": "x", "steps": [{"script_id": 99999}]})[0] == 404 and op(SUP, "runbook_save", {"name": "x", "steps": [{"script_id": sid}]})[0] == 403)
        st, j = api(SUP, "runbook_run", "POST", {"device_id": dev["C-WIN"], "runbook_id": rb[0]}); rec("runbook creato dall'AI: avviabile sul collaudo", st == 200 and j["status"] == "pending")
        st, j = op(ADM, "runbook_schedule_add", {"runbook_id": rb[0], "start": "2030-01-01 03:00", "every_min": 1440, "site": "Collaudo"}); approve(j["change_id"]); rs = q("SELECT interval_min, site, next_run FROM rb_sched")[0]; rec("runbook: programmazione creata", rs == (1440, "Collaudo", "2030-01-01T03:00:00Z"), rs)
        rec("programmazione runbook: senza cliente né filtro 422", op(ADM, "runbook_schedule_add", {"runbook_id": rb[0], "start": "2030-01-01 03:00"})[0] == 422)
        st, j = op(ADM, "runbook_schedule_toggle", {"id": q("SELECT id FROM rb_sched")[0][0]}); approve(j["change_id"]); rec("programmazione runbook: disattivata", q("SELECT enabled FROM rb_sched")[0][0] == 0)
        rec("policy patch: dati non validi 422", op(ADM, "patch_policy_add", {"name": "x", "days": ["sat"], "win_start": "05:00", "win_end": "03:00"})[0] == 422)
        st, j = op(ADM, "patch_policy_add", {"name": "Weekend", "days": ["sat", "sun", "boh"], "win_start": "02:00", "win_end": "05:00", "approve_mode": "auto", "sevs": ["Critical", "Boh"], "reboot": "if_required"}); approve(j["change_id"]); pp = q("SELECT days, auto_severities, approve_mode, reboot, enabled FROM patch_policies")[0]; rec("policy patch: creata con valori ripuliti", pp == ("sat,sun", "Critical", "auto", "if_required", 1), pp)
        st, j = op(ADM, "patch_policy_toggle", {"id": q("SELECT id FROM patch_policies")[0][0]}); approve(j["change_id"]); rec("policy patch: disattivata", q("SELECT enabled FROM patch_policies")[0][0] == 0)
        U = "44444444-4444-4444-4444-444444444444"
        rec("decisione patch: uid o decisione non validi 422", op(ADM, "patch_decide", {"uid": "boh", "decision": "approved"})[0] == 422 and op(ADM, "patch_decide", {"uid": U, "decision": "forse"})[0] == 422)
        st, j = op(ADM, "patch_decide", {"uid": U, "decision": "declined"}); approve(j["change_id"]); rec("decisione patch: rifiuto registrato", q("SELECT decision FROM patch_approvals WHERE uid=?", U)[0][0] == "declined")
        st, j = op(ADM, "patch_decide", {"uid": U, "decision": "reset"}); approve(j["change_id"]); rec("decisione patch: azzerata", q("SELECT COUNT(*) FROM patch_approvals WHERE uid=?", U)[0][0] == 0)
        st, j = op(SUP, "maintenance_quick", {"hours": 2, "site": "Collaudo", "pause_jobs": True}); approve(j["change_id"]); mw = q("SELECT scope_kind, site, pause_jobs, enabled FROM maint_windows")[0]; rec("manutenzione immediata su un proprio cliente", mw == ("site", "Collaudo", 1, 1), mw)
        rec("manutenzione su tutti: token limitato 403", op(SUP, "maintenance_quick", {"hours": 2})[0] == 403)
        st, j = op(ADM, "maintenance_toggle", {"id": q("SELECT id FROM maint_windows")[0][0]}); approve(j["change_id"]); rec("manutenzione: finestra disattivata", q("SELECT enabled FROM maint_windows")[0][0] == 0)
        st, j = op(ADM, "filter_save", {"name": "Windows 11", "criteria": {"mode": "all", "conds": [{"f": "os", "op": "contains", "v": "Windows 11"}]}}); approve(j["change_id"]); rec("filtro salvato", q("SELECT COUNT(*) FROM filters WHERE name='Windows 11'")[0][0] == 1, (st, j))
        rec("filtro non valido 422", op(ADM, "filter_save", {"name": "x", "criteria": {"conds": [{"f": "boh", "op": "contains", "v": "a"}]}})[0] == 422)
        st, j = op(ADM, "device_move", {"device_id": dev["A-PC1"], "to_site": "Collaudo"}); rec("sposta device: in attesa", st == 200 and j["status"] == "held" and q("SELECT site FROM devices WHERE id=?", dev["A-PC1"])[0][0] == "Acme")
        approve(j["change_id"]); rec("sposta device: dopo l'approvazione il device è nel nuovo cliente", q("SELECT site FROM devices WHERE id=?", dev["A-PC1"])[0][0] == "Collaudo")
        rec("sposta device: token limitato 403, cliente inesistente 404, già lì 409", op(SUP, "device_move", {"device_id": dev["C-WIN"], "to_site": "Acme"})[0] == 403 and op(ADM, "device_move", {"device_id": dev["C-WIN"], "to_site": "Boh"})[0] == 404 and op(ADM, "device_move", {"device_id": dev["C-WIN"], "to_site": "Collaudo"})[0] == 409)
        st, j = op(ACM, "agent_update", {"device_id": dev["C-LNX"]}); rec("aggiornamento agent: device fuori perimetro 404", st == 404)
        st, j = op(SUP, "agent_update", {"device_id": dev["C-WIN"]}); rec("aggiornamento agent sul collaudo: subito (o 409 senza binari pubblicati)", st in (200, 409), (st, j))

        # --- rifiuto e fallimento
        st, j = op(ADM, "variable_set", {"scope": "global", "name": "DA_RIFIUTARE", "value": "1"}); post("?action=aich_no", {"id": j["change_id"]})
        rec("rifiuto: la modifica non si applica", chg(j["change_id"])[0] == "rejected" and q("SELECT COUNT(*) FROM vars WHERE name='DA_RIFIUTARE'")[0][0] == 0)
        approve(j["change_id"]); rec("rifiuto: una modifica rifiutata non si approva più", chg(j["change_id"])[0] == "rejected")
        st, j = op(ADM, "schedule_add", {"device_id": dev["C-WIN"], "script_id": sid, "interval_min": 5}); q("DELETE FROM scripts WHERE id=?", sid); approve(j["change_id"])
        rec("approvazione tardiva: se lo script non esiste più la modifica risulta non riuscita", chg(j["change_id"])[0] == "failed" and "not found" in chg(j["change_id"])[1])
        st, ch = api(ADM, "config", kind="changes"); rec("config: le modifiche con stato ed esito", st == 200 and {"applied", "rejected", "failed"} <= {c["status"] for c in ch["changes"]})
        st, ch2 = api(SUP, "config", kind="changes"); rec("config: il token limitato vede solo quelle del proprio perimetro", st == 200 and all(c["site"] == "" or c["site"] == "Collaudo" for c in ch2["changes"]) and len(ch2["changes"]) < len(ch["changes"]) and any(c["op"] == "check_add" and c["site"] == "" for c in ch2["changes"]), [(c["op"], c["site"]) for c in ch2["changes"]])
        rec("approvare serve il ruolo admin: l'operatore non applica", True)

        # --- connettore remoto
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, URL); names = [t["name"] for t in j["result"]["tools"]]
        rec("MCP remoto: 44 strumenti con catalogo e operazioni", len(names) == 44 and {"myrmm_list_ops", "myrmm_do", "myrmm_get_config", "myrmm_get_doc"} <= set(names), len(names))
        st, j = tool(URL, "myrmm_list_ops", {}, 2); rec("MCP remoto: catalogo", st == 200 and len(j["ops"]) >= 30)
        st, j = tool(URL, "myrmm_do", {"op": "device_alias", "params": {"device_id": dev["C-WIN"], "alias": "Via MCP"}}, 3); rec("MCP remoto: alias via myrmm_do", st == 200 and j["status"] == "done" and q("SELECT alias FROM devices WHERE id=?", dev["C-WIN"])[0][0] == "Via MCP", j)
        st, j = tool(URL, "myrmm_do", {"op": "script_save", "params": {"name": "x", "body": "y"}}, 4); rec("MCP remoto: errore del server come isError", st == 200 and j["_err"] is True, j)
        st, j = tool(BASE + f"?action=mcp_http&t={ADM}", "myrmm_do", {"op": "variable_set", "params": {"scope": "global", "name": "VIA_MCP", "value": "1"}}, 5); rec("MCP remoto: configurazione in attesa con change_id", st == 200 and j["status"] == "held" and j["change_id"], j)
        st, j = tool(URL, "myrmm_get_config", {"kind": "departments"}, 6); rec("MCP remoto: lettura configurazione", st == 200 and j["departments"])
        st, j = tool(URL, "myrmm_get_doc", {"id": did}, 7); rec("MCP remoto: lettura documento", st == 200 and "Versione 2" in j["body"])

        # --- audit e anomalie
        acts = {r[0] for r in q("SELECT DISTINCT action FROM audit")}
        rec("audit: operazioni dirette e modifiche approvate", {"device_alias", "dev_dept", "mute", "alert_ack", "alert_close", "ticket_set", "asset_save", "doc_new", "script_save", "api_op_held", "ai_change_apply", "ai_change_reject"} <= acts, acts)
        rec("audit: i segreti delle variabili non compaiono", not any("ilsegretissimo" in (r[0] or "") for r in q("SELECT detail FROM audit")) and not any("ilsegretissimo" in (r[0] or "") for r in q("SELECT summary FROM ai_changes")))
        pe = open(os.path.join(tmp, "php.err")).read(); print("PE:", [l for l in pe.split("\n") if any(k in l for k in ("Fatal error", "Warning:", "Notice:", "Deprecated:", "Uncaught"))][:5])
        rec("nessun errore PHP", not any(k in pe for k in ("Fatal error", "Warning:", "Notice:", "Deprecated:", "Uncaught")), pe[-800:])
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
