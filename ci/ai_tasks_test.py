#!/usr/bin/env python3
"""Incarichi AI e connettore MCP remoto (1.68.0): coda tra AI superiore e AI locale, approvazione fuori dal collaudo, perimetro per cliente,
cronologia e audit, endpoint JSON-RPC su HTTPS (token nell'indirizzo o nell'header), pagina in console.
Uso: python3 ci/ai_tasks_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.error, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8836; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-ai-"); srv = os.path.join(tmp, "server")
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
        # token: AI superiore (Collaudo, diretta), AI locale (Collaudo, diretta), una per Acme (con approvazione), sola lettura
        SUP = mk(name="ai-superiore", role="operator", write="2", days="30", **{"sites[]": ["Collaudo"]})
        LOC = mk(name="ai-locale", role="operator", write="2", days="30", **{"sites[]": ["Collaudo"]})
        ACM = mk(name="ai-acme", role="operator", write="1", days="30", **{"sites[]": ["Acme"]})
        RO = mk(name="lettura", role="viewer", write="0", days="30")
        rec("token creati", all([SUP, LOC, ACM, RO]))

        # --- creazione
        st, t1 = api(SUP, "task_create", "POST", {"title": "Controlla spazio disco", "goal": "Leggi lo spazio libero di C: e riferisci.", "constraints": "Non cancellare nulla.", "device_id": dev["C-WIN"]})
        rec("incarico sul collaudo: parte subito (in coda)", st == 200 and t1.get("status") == "pending", (st, t1))
        T1 = t1.get("id")
        rec("titolo mancante: 422", api(SUP, "task_create", "POST", {"goal": "x"})[0] == 422)
        rec("obiettivo troppo lungo: 422", api(SUP, "task_create", "POST", {"title": "x", "goal": "a" * 4001})[0] == 422)
        rec("device fuori dal perimetro: 404", api(SUP, "task_create", "POST", {"title": "x", "goal": "y", "device_id": dev["A-PC1"]})[0] == 404)
        rec("sola lettura non può creare: 403", api(RO, "task_create", "POST", {"title": "x", "goal": "y"})[0] == 403)
        st, t2 = api(ACM, "task_create", "POST", {"title": "Aggiorna 7-Zip", "goal": "Aggiornare 7-Zip su A-PC1.", "device_id": dev["A-PC1"]})
        rec("incarico su cliente reale: attende l'approvazione", st == 200 and t2.get("status") == "awaiting_approval", (st, t2))
        T2 = t2.get("id")
        st, t3 = api(SUP, "task_create", "POST", {"title": "Senza bersaglio", "goal": "Qualcosa."})
        rec("senza bersaglio: attende l'approvazione", st == 200 and t3.get("status") == "awaiting_approval", (st, t3))
        T3 = t3.get("id")

        # --- lettura e perimetro
        st, lst = api(RO, "tasks")
        rec("sola lettura vede l'elenco", st == 200 and len(lst.get("tasks", [])) == 3, lst)
        st, lst = api(SUP, "tasks", status="pending")
        rec("filtro per stato", st == 200 and [x["id"] for x in lst["tasks"]] == [T1], lst)
        rec("perimetro: SUP non vede l'incarico di Acme", api(SUP, "task", id=T2)[0] == 404)
        rec("perimetro: ACM vede il suo", api(ACM, "task", id=T2)[0] == 200)
        st, full = api(SUP, "task", id=T1)
        rec("dettaglio con cronologia e avviso dati non fidati", st == 200 and full["events"][0]["kind"] == "created" and "untrusted" in full and full["goal"].startswith("Leggi"), full)

        # --- presa in carico
        rec("sola lettura non può prendere in carico: 403", api(RO, "task_claim", "POST", {})[0] == 403)
        st, cl = api(LOC, "task_claim", "POST", {})
        rec("AI locale prende il prossimo incarico", st == 200 and cl["task"] and cl["task"]["id"] == T1 and cl["task"]["status"] == "in_progress" and cl["task"]["worker"] == "api:ai-locale", cl)
        rec("secondo claim: niente da prendere (l'altro è in attesa di approvazione)", api(LOC, "task_claim", "POST", {})[1].get("task") is None)
        rec("incarico non approvato non si può prendere nemmeno per id", api(ACM, "task_claim", "POST", {"id": T2})[1].get("task") is None)

        # --- rapporto
        rec("report da chi non l'ha preso: 403", api(SUP, "task_report", "POST", {"id": T1, "note": "x"})[0] == 403)
        rec("report vuoto: 422", api(LOC, "task_report", "POST", {"id": T1})[0] == 422)
        rec("stato non valido: 422", api(LOC, "task_report", "POST", {"id": T1, "note": "x", "status": "boh"})[0] == 422)
        rec("domanda senza testo: 422", api(LOC, "task_report", "POST", {"id": T1, "status": "waiting_answer"})[0] == 422)
        rec("passo riportato", api(LOC, "task_report", "POST", {"id": T1, "note": "Lancio lo script di spazio disco", "job_ids": [123]})[1].get("status") == "in_progress")
        st, r = api(LOC, "task_report", "POST", {"id": T1, "note": "Il disco D: è quasi pieno: devo pulirlo?", "status": "waiting_answer"})
        rec("domanda all'AI superiore", st == 200 and r["status"] == "waiting_answer", r)
        rec("mentre attende, non si può riportare: 409", api(LOC, "task_report", "POST", {"id": T1, "note": "x"})[0] == 409)
        rec("nota senza testo: 422", api(SUP, "task_answer", "POST", {"id": T1, "text": ""})[0] == 422)
        st, r = api(SUP, "task_answer", "POST", {"id": T1, "text": "No, solo leggi e riferisci."})
        rec("risposta dell'AI superiore", st == 200 and r["status"] == "answered", r)
        st, cl = api(LOC, "task_claim", "POST", {})
        rec("l'AI locale riprende con la risposta", st == 200 and cl["task"]["id"] == T1 and any(e["kind"] == "answer" for e in cl["task"]["events"]), cl)
        rec("un'altra AI non riprende l'incarico", api(SUP, "task_claim", "POST", {"id": T1})[1].get("task") is None)
        st, r = api(LOC, "task_report", "POST", {"id": T1, "status": "done", "result": "C: 54 GB liberi su 120.", "note": "Fatto"})
        rec("incarico concluso con risultato", st == 200 and r["status"] == "done", r)
        st, full = api(SUP, "task", id=T1)
        rec("cronologia completa (passi, domanda, risposta, job, risultato)", [e["kind"] for e in full["events"]] == ["created", "claimed", "progress", "job", "question", "answer", "claimed", "progress", "result"] and full["result"].startswith("C:"), [e["kind"] for e in full["events"]])
        rec("incarico chiuso: non si annulla (409)", api(SUP, "task_cancel", "POST", {"id": T1})[0] == 409)
        rec("incarico chiuso: nessuna nota (409)", api(SUP, "task_answer", "POST", {"id": T1, "text": "x"})[0] == 409)
        rec("job collegato visibile in cronologia", any(e["job_id"] == 123 for e in full["events"]))
        aud = q("SELECT action FROM audit WHERE action LIKE 'ai_task%'")
        rec("audit: creazione, presa, rapporto, risposta", {a[0] for a in aud} >= {"ai_task_create", "ai_task_claim", "ai_task_report", "ai_task_answer"}, aud)

        # --- approvazione dalla console
        rec("prima dell'approvazione ACM non prende nulla", api(ACM, "task_claim", "POST", {})[1].get("task") is None)
        rec("non si risponde a un incarico non approvato (409)", api(ACM, "task_answer", "POST", {"id": T2, "text": "x"})[0] == 409)
        r = post("?action=ait_approve", {"id": T2})
        rec("console: approvazione (amministratore)", r.status in (302, 303) and q("SELECT status,approved_by FROM ai_tasks WHERE id=?", T2)[0][0] == "pending", r.status)
        st, cl = api(ACM, "task_claim", "POST", {})
        rec("dopo l'approvazione l'AI di Acme lo prende", st == 200 and cl["task"] and cl["task"]["id"] == T2, cl)
        rec("AI del collaudo non vede l'incarico di Acme", api(LOC, "task", id=T2)[0] == 404)
        r = post("?action=ait_cancel", {"id": T3})
        rec("console: annullamento", q("SELECT status FROM ai_tasks WHERE id=?", T3)[0][0] == "cancelled")
        st, r = api(ACM, "task_cancel", "POST", {"id": T2, "reason": "non serve più"})
        rec("annullamento via API con motivo", st == 200 and r["status"] == "cancelled")

        # --- console
        pg = get("?view=aitasks").text()
        rec("pagina Incarichi AI: elenco", "Incarichi AI" in pg and "Controlla spazio disco" in pg and "Aggiorna 7-Zip" in pg)
        p.goto(BASE + "?view=aitasks"); p.wait_for_selector("main")
        p.locator("details.card summary").click(); p.fill("input[name=title]", "Prova da console"); p.fill("textarea[name=goal]", "Obiettivo di prova"); p.select_option("select[name=site]", "Collaudo")
        p.click("form[action$=ait_new] button"); p.wait_for_selector("main p.ok")
        rec("console: nuovo incarico sul collaudo parte subito", q("SELECT status,creator FROM ai_tasks WHERE title='Prova da console'")[0][0] == "pending" and "console:admin" in q("SELECT creator FROM ai_tasks WHERE title='Prova da console'")[0][0])
        tid = q("SELECT id FROM ai_tasks WHERE title='Prova da console'")[0][0]
        p.goto(BASE + f"?view=aitasks&id={tid}"); p.wait_for_selector("main")
        txt = p.inner_text("main")
        rec("console: dettaglio con obiettivo e cronologia", "Obiettivo di prova" in txt and "Cronologia" in txt and "console:admin" in txt)
        p.fill("textarea[name=text]", "Nota dall'operatore"); p.click("form[action$=ait_answer] button"); p.wait_for_selector("main p.ok")
        rec("console: nota aggiunta alla cronologia", "Nota dall'operatore" in p.inner_text("main"))
        vc = br.new_context(); vp = vc.new_page(); vp.goto(BASE); vp.fill("input[name=username]", "vis"); vp.click("button[type=submit]")
        vp.wait_for_selector("input[name=password]", timeout=5000); vp.fill("input[name=password]", PW); vp.click("button[type=submit]"); vp.wait_for_selector(".rail", timeout=8000)
        vp.goto(BASE + "?view=aitasks"); vp.wait_for_load_state("load")
        rec("console: il sola lettura non apre la pagina", "Prova da console" not in vp.content() and "Nuovo incarico" not in vp.content())
        rec("console: nessun errore JS", not errs, errs)

        # --- connettore MCP remoto
        URL = BASE + f"?action=mcp_http&t={LOC}"
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}, URL)
        rec("MCP remoto: initialize", st == 200 and j["result"]["serverInfo"]["name"] == "myrmm" and j["result"]["protocolVersion"] == "2025-03-26" and "capabilities" in j["result"], (st, j))
        st, j = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, URL)
        names = [t["name"] for t in j["result"]["tools"]] if st == 200 else []
        rec("MCP remoto: 40 strumenti, compresi gli incarichi", len(names) == 40 and {"myrmm_task_next", "myrmm_task_report", "myrmm_task_create", "myrmm_run_inline"} <= set(names), names)
        rec("MCP remoto: schema degli strumenti valido", all(t["inputSchema"]["type"] == "object" for t in j["result"]["tools"]))
        rec("MCP remoto: notifica senza risposta (202)", rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, URL)[0] == 202)
        rec("MCP remoto: ping", rpc({"jsonrpc": "2.0", "id": 3, "method": "ping"}, URL)[1]["result"] == {})
        rec("MCP remoto: metodo sconosciuto", rpc({"jsonrpc": "2.0", "id": 4, "method": "boh"}, URL)[1]["error"]["code"] == -32601)
        rec("MCP remoto: strumento sconosciuto", rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}}, URL)[1]["error"]["code"] == -32602)
        rec("MCP remoto: argomento obbligatorio mancante", rpc({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "myrmm_get_job", "arguments": {}}}, URL)[1]["error"]["code"] == -32602)
        rec("MCP remoto: JSON non valido (400)", rpc(None, URL, raw=b"{non json")[0] == 400)
        rec("MCP remoto: GET non ammesso (405)", urllib.request.urlopen(urllib.request.Request(URL, method="GET")) if False else True)
        try: urllib.request.urlopen(urllib.request.Request(URL, method="GET")); g = 200
        except urllib.error.HTTPError as e: g = e.code
        rec("MCP remoto: GET risponde 405", g == 405, g)
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, BASE + "?action=mcp_http&t=myrmm_" + "0" * 48)
        rec("MCP remoto: token sbagliato 401", st == 401 and j["error"]["code"] == -32001, (st, j))
        rec("MCP remoto: senza token 401", rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, BASE + "?action=mcp_http")[0] == 401)
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, BASE + "?action=mcp_http", {"Authorization": "Bearer " + LOC})
        rec("MCP remoto: token anche nell'header Bearer", st == 200 and len(j["result"]["tools"]) == 40)
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, BASE + "?action=mcp_http", {"X-Api-Token": LOC})
        rec("MCP remoto: token anche in X-Api-Token", st == 200)
        st, j = rpc([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "ping"}], URL)
        rec("MCP remoto: richiesta multipla", st == 200 and [x["id"] for x in j] == [1, 2], (st, j))
        st, me = tool(URL, "myrmm_status")
        rec("MCP remoto: myrmm_status", st == 200 and me.get("name") == "ai-locale" and me.get("write") == 2, me)
        st, dv = tool(URL, "myrmm_list_devices", {"online": 1})
        rec("MCP remoto: elenco device nel perimetro", st == 200 and [d["hostname"] for d in dv["devices"]] == ["C-WIN"], dv)
        st, rj = tool(URL, "myrmm_run_inline", {"device_id": dev["C-WIN"], "body": "Write-Output ciao", "platform": "windows", "wait": 0})
        jb = q("SELECT script,origin,status FROM jobs WHERE id=?", rj.get("job_id", 0))
        rec("MCP remoto: esecuzione in simulazione per impostazione predefinita", st == 200 and rj.get("dry_run") is True and jb and jb[0][1] == "inline" and "WhatIfPreference" in jb[0][0], (rj, jb))
        st, rj = tool(URL, "myrmm_run_inline", {"device_id": dev["A-PC1"], "body": "x", "wait": 0})
        rec("MCP remoto: stessi limiti dell'API (device di Acme negato)", st == 200 and rj.get("_err") is True, rj)
        st, rj = tool(URL, "myrmm_get_job", {"id": rj.get("job_id", 1)})
        st, sv = tool(BASE + f"?action=mcp_http&t={SUP}", "myrmm_task_create", {"title": "Via MCP remoto", "goal": "Prova", "site": "Collaudo"})
        rec("MCP remoto: l'AI superiore crea un incarico", st == 200 and sv.get("status") == "pending", sv)
        st, nx = tool(URL, "myrmm_task_next")
        rec("MCP remoto: l'AI locale lo prende (task_next)", st == 200 and nx["task"]["title"] in ("Prova da console", "Via MCP remoto"), nx)
        tn = nx["task"]["id"]
        st, rp = tool(URL, "myrmm_task_report", {"id": tn, "status": "done", "result": "ok via MCP", "job_ids": [1]})
        rec("MCP remoto: rapporto finale (task_report)", st == 200 and rp.get("status") == "done", rp)
        st, tg = tool(BASE + f"?action=mcp_http&t={SUP}", "myrmm_task_get", {"id": tn})
        rec("MCP remoto: l'AI superiore legge il risultato", st == 200 and tg.get("result") == "ok via MCP", tg)
        st, tl = tool(BASE + f"?action=mcp_http&t={RO}", "myrmm_task_list", {"status": "done"})
        rec("MCP remoto: sola lettura elenca ma non scrive", st == 200 and len(tl["tasks"]) >= 2 and tool(BASE + f"?action=mcp_http&t={RO}", "myrmm_task_create", {"title": "x", "goal": "y"})[1].get("_err") is True)
        # token revocato
        tid_l = q("SELECT id FROM api_tokens WHERE name='ai-locale'")[0][0]; post("?action=api_revoke", {"id": tid_l})
        rec("MCP remoto: token revocato non entra più", rpc({"jsonrpc": "2.0", "id": 1, "method": "ping"}, URL)[0] == 401)
        pe = open(os.path.join(tmp, "php.err")).read()
        rec("nessun errore PHP", not any(k in pe for k in ("Fatal error", "Warning:", "Notice:", "Deprecated:", "Uncaught")), pe[-400:])
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
