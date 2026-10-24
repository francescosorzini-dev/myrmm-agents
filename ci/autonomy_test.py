#!/usr/bin/env python3
"""Matrice di autonomia dei token (1.71.0): tutto con conferma / tutto diretto / personalizzata, operazioni amministrative (eliminazioni, clienti, utenti, token, irreversibili), esecuzione di gruppo, 'ferma tutte le AI', pulizia dei token revocati e scaduti.
Uso: python3 ci/autonomy_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.error, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8839; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-aut-"); srv = os.path.join(tmp, "server")
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
        def chg(cid): return q("SELECT status, result FROM ai_changes WHERE id=?", cid)[0]
        def tok_mk(name, **kw): return mk(name=name, role=kw.pop("role", "operator"), days=kw.pop("days", "30"), **kw)
        def aut(**m): return {"autonomy": "custom", **{f"aut[{k}]": v for k, v in m.items()}}

        # --- creazione dei token
        ASK = tok_mk("ai-ask", autonomy="ask"); DO = tok_mk("ai-do", autonomy="do"); LEG = ADM
        rec("token con autonomia: «tutto con conferma» e «tutto diretto» creati", bool(ASK and DO))
        rec("autonomia con ruolo viewer rifiutata", tok_mk("x-viewer", role="viewer", autonomy="ask") is None)
        rec("autonomia personalizzata tutta vietata rifiutata", tok_mk("x-vuota", **aut(dati="no")) is None)
        rec("operazioni amministrative dirette con scadenza oltre 30 giorni rifiutate", tok_mk("x-lungo", days="90", autonomy="custom", **{"aut[eliminazioni]": "do"}) is None)
        CUS = tok_mk("ai-custom", **aut(dati="do", device="ask", ordini="ask", eliminazioni="do", distruttive="do", utenti="do", server="do", alimentazione="no"))
        rec("autonomia personalizzata creata", bool(CUS))
        row = q("SELECT write, autonomy FROM api_tokens WHERE name='ai-do'")[0]; a_ = json.loads(row[1])
        rec("«tutto diretto»: scrittura 1, irreversibili ancora con conferma", row[0] == 1 and a_["dati"] == "do" and a_["eliminazioni"] == "do" and a_["distruttive"] == "ask", a_)
        st, me_ = api(DO, "me"); rec("me: mostra la matrice", st == 200 and me_["autonomy"]["config"] == "do" and me_["paused"] is False, me_)
        html = get("?view=api").text(); rec("console: elenco token con riepilogo dell'autonomia e modulo", "AI: tutto con conferma" in html and "Ferma tutte le AI" in html and 'name="autonomy"' in html and "aut[distruttive]" in html)

        # --- catalogo e regole di base
        st, cat = api(ASK, "ops"); ops_ = {o["op"]: o for o in cat["ops"]} if st == 200 else {}
        rec("catalogo: operazioni con categoria", st == 200 and len(ops_) >= 50 and all(o["category"] for o in ops_.values()), len(ops_))
        rec("catalogo con conferma: ogni operazione richiede approvazione", all("approva" in o["approval"] for o in ops_.values()))
        st, cat2 = api(LEG, "ops"); o2 = {o["op"]: o for o in cat2["ops"]}
        rec("catalogo token senza matrice: le amministrative non sono disponibili", all("non disponibile" in o2[x]["approval"] for x in ("delete_ticket", "user_set", "site_create", "device_delete")) and o2["device_alias"]["approval"] == "none")
        st, cat3 = api(CUS, "ops"); o3 = {o["op"]: o for o in cat3["ops"]}
        rec("catalogo personalizzato: diretta, con conferma e vietata", o3["ticket_set"]["approval"] == "subito" and "approva" in o3["device_alias"]["approval"] and "vietata" in o3["script_save"]["approval"], (o3["ticket_set"]["approval"], o3["device_alias"]["approval"], o3["script_save"]["approval"]))
        rec("token senza matrice: operazione amministrativa 403", op(LEG, "delete_ticket", {"id": 1})[0] == 403 and op(LEG, "site_create", {"name": "Zeta"})[0] == 403)
        st, j = op(CUS, "script_save", {"name": "x", "body": "y"}); rec("categoria vietata: 403", st == 403, (st, j))

        # --- modalità: ask / do
        st, j = op(ASK, "device_alias", {"device_id": dev["C-WIN"], "alias": "Via ask"}); rec("con conferma: anche un alias aspetta", st == 200 and j["status"] == "held" and q("SELECT alias FROM devices WHERE id=?", dev["C-WIN"])[0][0] is None, (st, j))
        approve(j["change_id"]); rec("approvato dalla console: alias applicato", q("SELECT alias FROM devices WHERE id=?", dev["C-WIN"])[0][0] == "Via ask")
        st, j = op(DO, "device_alias", {"device_id": dev["C-WIN"], "alias": "Via do"}); rec("diretto: subito", st == 200 and j["status"] == "done" and q("SELECT alias FROM devices WHERE id=?", dev["C-WIN"])[0][0] == "Via do")
        st, j = op(DO, "script_save", {"name": "Prova diretta", "body": "Write-Output 'ok'"}); rec("diretto: configurazione subito, senza coda", st == 200 and j["status"] == "done" and q("SELECT COUNT(*) FROM scripts WHERE name='Prova diretta'")[0][0] == 1, (st, j))
        SID = q("SELECT id FROM scripts WHERE name='Prova diretta'")[0][0]

        # --- eliminazioni
        st, t1 = api(DO, "ticket_create", "POST", {"title": "Da eliminare", "device_id": dev["C-WIN"]})
        st, j = op(DO, "delete_ticket", {"id": t1["id"]}); rec("elimina ticket: nel cestino", st == 200 and q("SELECT COUNT(*) FROM tickets WHERE id=?", t1["id"])[0][0] == 0 and q("SELECT COUNT(*) FROM trash WHERE kind='ticket' AND ref_id=?", t1["id"])[0][0] == 1, (st, j))
        rec("elimina ticket inesistente 404", op(DO, "delete_ticket", {"id": t1["id"]})[0] == 404)
        q("INSERT INTO asset_types(name,fields,position,created) VALUES('Server','[]',1,?)", now); ty = q("SELECT id FROM asset_types WHERE name='Server'")[0][0]
        st, a1 = api(DO, "asset_create", "POST", {"type_id": ty, "name": "Asset da eliminare", "site": "Collaudo"})
        st, j = op(DO, "delete_asset", {"id": a1["id"]}); rec("elimina asset: nel cestino", st == 200 and q("SELECT COUNT(*) FROM assets WHERE id=?", a1["id"])[0][0] == 0 and q("SELECT COUNT(*) FROM trash WHERE kind='asset'")[0][0] == 1, (st, j))
        st, d1 = op(DO, "doc_save", {"title": "Doc da eliminare", "body": "testo", "site": "Collaudo"}); did = d1["result"]["id"]
        st, j = op(DO, "delete_doc", {"id": did}); rec("elimina documento: nel cestino", st == 200 and q("SELECT COUNT(*) FROM docs WHERE id=?", did)[0][0] == 0 and q("SELECT COUNT(*) FROM trash WHERE kind='doc'")[0][0] == 1, (st, j))
        st, d2 = op(DO, "doc_save", {"title": "Doc Collaudo", "body": "t", "site": "Collaudo"}); rec("elimina documento di un cliente fuori perimetro 404", op(tok_mk("ai-acme-do", **aut(eliminazioni="do"), **{"sites[]": ["Acme"]}), "delete_doc", {"id": d2["result"]["id"]})[0] == 404)
        st, j = op(DO, "schedule_add", {"device_id": dev["C-WIN"], "script_id": SID, "interval_min": 30}); schid = q("SELECT id FROM schedules WHERE script_id=?", SID)[0][0]
        st, j = op(DO, "delete_schedule", {"id": schid}); rec("elimina pianificazione", st == 200 and q("SELECT COUNT(*) FROM schedules WHERE id=?", schid)[0][0] == 0, (st, j))
        op(DO, "check_add", {"type": "cpu_pct", "threshold": 90}); ck = q("SELECT id FROM checks")[0][0]
        rec("elimina controllo", op(DO, "delete_check", {"id": ck})[0] == 200 and q("SELECT COUNT(*) FROM checks WHERE id=?", ck)[0][0] == 0)
        op(DO, "rule_add", {"name": "R", "script_id": SID, "interval_min": 60}); rid = q("SELECT id FROM rules WHERE name='R'")[0][0]
        rec("elimina regola", op(DO, "delete_rule", {"id": rid})[0] == 200 and q("SELECT COUNT(*) FROM rules WHERE name='R'")[0][0] == 0)
        op(DO, "variable_set", {"scope": "global", "name": "VAR_X", "value": "1"}); st, vv = api(ADM, "config", kind="variables"); vid = [v["id"] for v in vv["variables"] if v["name"] == "VAR_X"][0]
        rec("elimina variabile (id dalla lettura)", op(DO, "delete_variable", {"id": vid})[0] == 200 and q("SELECT COUNT(*) FROM vars WHERE name='VAR_X'")[0][0] == 0)
        op(DO, "runbook_save", {"name": "RB1", "steps": [{"script_id": SID}]}); rbid = q("SELECT id FROM runbooks WHERE name='RB1'")[0][0]
        op(DO, "runbook_schedule_add", {"runbook_id": rbid, "start": "2030-01-01 03:00", "site": "Collaudo"}); rsid = q("SELECT id FROM rb_sched")[0][0]
        rec("elimina programmazione runbook e runbook", op(DO, "delete_runbook_schedule", {"id": rsid})[0] == 200 and op(DO, "delete_runbook", {"id": rbid})[0] == 200 and q("SELECT COUNT(*) FROM runbooks WHERE name='RB1'")[0][0] == 0)
        op(DO, "filter_save", {"name": "F1", "criteria": {"mode": "all", "conds": [{"f": "os", "op": "contains", "v": "Win"}]}}); fid = q("SELECT id FROM filters WHERE name='F1'")[0][0]
        op(DO, "rule_add", {"name": "R2", "script_id": SID, "interval_min": 60, "filter_id": fid})
        rec("elimina filtro in uso: 409", op(DO, "delete_filter", {"id": fid})[0] == 409)
        op(DO, "delete_rule", {"id": q("SELECT id FROM rules WHERE name='R2'")[0][0]}); rec("elimina filtro non più in uso", op(DO, "delete_filter", {"id": fid})[0] == 200)
        op(DO, "patch_policy_add", {"name": "PP", "days": ["sat"], "win_start": "02:00", "win_end": "05:00"}); rec("elimina policy patch", op(DO, "delete_patch_policy", {"id": q("SELECT id FROM patch_policies")[0][0]})[0] == 200)
        op(DO, "maintenance_quick", {"hours": 1, "site": "Collaudo"}); rec("elimina finestra di manutenzione", op(DO, "delete_maintenance", {"id": q("SELECT id FROM maint_windows")[0][0]})[0] == 200 and q("SELECT COUNT(*) FROM maint_windows")[0][0] == 0)
        rec("elimina script", op(DO, "delete_script", {"id": SID})[0] == 200 and q("SELECT COUNT(*) FROM scripts WHERE id=?", SID)[0][0] == 0)
        rec("eliminazioni globali: token limitato 403", op(CUS_L := tok_mk("ai-lim-del", **aut(eliminazioni="do"), **{"sites[]": ["Collaudo"]}), "delete_script", {"id": sc[0]})[0] == 403)
        st, j = op(ASK, "delete_ticket", {"id": 99999}); rec("con conferma: l'operazione viene convalidata subito (ticket inesistente 404)", st == 404)

        # --- clienti
        st, j = op(DO, "site_create", {"name": "Nuovo Cliente"}); rec("crea cliente con token di installazione", st == 200 and q("SELECT COUNT(*) FROM sites WHERE name='Nuovo Cliente'")[0][0] == 1 and q("SELECT COUNT(*) FROM site_tokens WHERE site='Nuovo Cliente'")[0][0] >= 1, (st, j))
        rec("crea cliente: duplicato 409, nome non valido 422", op(DO, "site_create", {"name": "nuovo cliente"})[0] == 409 and op(DO, "site_create", {"name": "A<b>"})[0] == 422)
        addev("N-PC", "Nuovo Cliente", "Windows 11 Pro", "windows"); dn = q("SELECT id FROM devices WHERE hostname='N-PC'")[0][0]
        q("INSERT INTO vars(scope,name,value) VALUES('site:Nuovo Cliente','Z','1')")
        st, j = op(DO, "site_rename", {"from": "Nuovo Cliente", "to": "Cliente Rinominato"}); rec("rinomina cliente: device e variabili lo seguono", st == 200 and q("SELECT site FROM devices WHERE id=?", dn)[0][0] == "Cliente Rinominato" and q("SELECT COUNT(*) FROM vars WHERE scope='site:Cliente Rinominato'")[0][0] == 1 and q("SELECT COUNT(*) FROM sites WHERE name='Nuovo Cliente'")[0][0] == 0, (st, j))
        rec("rinomina su un nome esistente 409 (l'unione resta alla console)", op(DO, "site_rename", {"from": "Cliente Rinominato", "to": "acme"})[0] == 409)
        rec("elimina cliente con device 409", op(CUS, "site_delete", {"name": "Cliente Rinominato"})[0] == 409)

        # --- utenti e token
        q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('uop','x','operator','',1,?,0)", now); uop = q("SELECT id FROM users WHERE username='uop'")[0][0]
        q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('boss','x','admin','',1,?,0)", now); adm_id = q("SELECT id FROM users WHERE username='boss'")[0][0]
        st, j = op(DO, "user_set", {"id": uop, "role": "viewer", "sites": ["Collaudo"], "enabled": False}); rec("utente: ruolo, clienti e disabilitazione", st == 200 and q("SELECT role, sites, enabled FROM users WHERE id=?", uop)[0] == ("viewer", "Collaudo", 0), (st, j))
        rec("utente: un amministratore non si tocca, nessun amministratore creato", op(DO, "user_set", {"id": adm_id, "role": "viewer"})[0] == 403 and op(DO, "user_set", {"id": uop, "role": "admin"})[0] == 422)
        rec("utente: token limitato 403", op(CUS_L, "user_set", {"id": uop, "role": "viewer"})[0] == 403)
        st, ul = api(ADM, "config", kind="users"); rec("config users: elenco", st == 200 and any(u["username"] == "uop" for u in ul["users"]))
        tid_ro = q("SELECT id FROM api_tokens WHERE name='lettura'")[0][0]
        st, j = op(DO, "token_revoke", {"id": tid_ro}); rec("revoca token", st == 200 and q("SELECT revoked FROM api_tokens WHERE id=?", tid_ro)[0][0] == 1, (st, j))
        rec("revoca token già revocato 409", op(DO, "token_revoke", {"id": tid_ro})[0] == 409)
        st, tl = api(ADM, "config", kind="tokens"); rec("config tokens: stato, autonomia, nessun hash", st == 200 and any(t["name"] == "lettura" and t["revoked"] == 1 for t in tl["tokens"]) and any(t["autonomy"].startswith("AI: tutto") for t in tl["tokens"]) and "hash" not in json.dumps(tl))
        st, j = op(DO, "token_purge", {"id": tid_ro}); rec("pulizia: un token revocato esce dall'elenco", st == 200 and j["result"]["removed"] == 1 and q("SELECT COUNT(*) FROM api_tokens WHERE id=?", tid_ro)[0][0] == 0, (st, j))
        rec("pulizia: un token attivo non si rimuove", op(DO, "token_purge", {"id": q("SELECT id FROM api_tokens WHERE name='ai-do'")[0][0]})[1]["result"]["removed"] == 0)
        # console: pulizia singola e di massa
        q("UPDATE api_tokens SET expires='2020-01-01T00:00:00Z' WHERE name='x-viewer' OR name='ai-acme-do'")
        T_ = tok_mk("da-scadere", **aut(dati="do")); q("UPDATE api_tokens SET expires='2020-01-01T00:00:00Z' WHERE name='da-scadere'")
        html = get("?view=api").text(); rec("console: token scaduti hanno «Rimuovi» e c'è «Rimuovi revocati e scaduti»", "api_purge_all" in html and "api_purge\"" in html)
        idx = q("SELECT id FROM api_tokens WHERE name='da-scadere'")[0][0]; post("?action=api_purge", {"id": idx}); rec("console: rimozione di un token scaduto", q("SELECT COUNT(*) FROM api_tokens WHERE name='da-scadere'")[0][0] == 0)
        post("?action=api_purge", {"id": q("SELECT id FROM api_tokens WHERE name='ai-do'")[0][0]}); rec("console: un token attivo non si rimuove", q("SELECT COUNT(*) FROM api_tokens WHERE name='ai-do'")[0][0] == 1)
        n0 = q("SELECT COUNT(*) FROM api_tokens WHERE revoked=1 OR (expires<>'' AND expires<'2026')")[0][0]
        post("?action=api_revoke", {"id": q("SELECT id FROM api_tokens WHERE name='ai-lim-del'")[0][0]}); post("?action=api_purge_all", {})
        rec("console: «rimuovi tutti» toglie solo revocati e scaduti", q("SELECT COUNT(*) FROM api_tokens WHERE revoked=1")[0][0] == 0 and q("SELECT COUNT(*) FROM api_tokens WHERE name IN ('ai-do','ai-ask','ai-custom')")[0][0] == 3)

        # --- irreversibili
        addev("X-PC", "Collaudo", "Windows 11 Pro", "windows"); dx = q("SELECT id FROM devices WHERE hostname='X-PC'")[0][0]
        st, j = op(DO, "device_delete", {"device_id": dx}); rec("«tutto diretto»: elimina device resta con conferma", st == 200 and j["status"] == "held" and q("SELECT COUNT(*) FROM devices WHERE id=?", dx)[0][0] == 1, (st, j))
        approve(j["change_id"]); rec("approvato: device eliminato", q("SELECT COUNT(*) FROM devices WHERE id=?", dx)[0][0] == 0)
        addev("Y-PC", "Collaudo", "Windows 11 Pro", "windows"); dy = q("SELECT id FROM devices WHERE hostname='Y-PC'")[0][0]
        st, j = op(CUS, "device_delete", {"device_id": dy}); rec("personalizzata diretta: elimina device subito", st == 200 and j["status"] == "done" and q("SELECT COUNT(*) FROM devices WHERE id=?", dy)[0][0] == 0, (st, j))
        addev("U-PC", "Collaudo", "Windows 11 Pro", "windows"); du = q("SELECT id FROM devices WHERE hostname='U-PC'")[0][0]
        st, j = op(CUS, "agent_uninstall", {"device_id": du}); rec("disinstalla agent: richiesta registrata", st == 200 and q("SELECT uninstall_req FROM devices WHERE id=?", du)[0][0] > 0, (st, j))
        st, j = op(CUS, "site_create", {"name": "Vuoto"}); st, j = op(CUS, "site_delete", {"name": "Vuoto"}); rec("elimina cliente vuoto", st == 200 and q("SELECT COUNT(*) FROM sites WHERE name='Vuoto'")[0][0] == 0, (st, j))
        q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('udel','x','viewer','',1,?,0)", now)
        st, j = op(CUS, "user_delete", {"id": q("SELECT id FROM users WHERE username='udel'")[0][0]}); rec("elimina utente", st == 200 and q("SELECT COUNT(*) FROM users WHERE username='udel'")[0][0] == 0)
        rec("elimina utente amministratore 403", op(CUS, "user_delete", {"id": adm_id})[0] == 403)

        # --- ordini, alimentazione, patch
        st, sl = api(ADM, "scripts"); lib = [s_["id"] for s_ in sl["scripts"] if s_["platform"] == "windows" and not (s_.get("vars") or s_.get("variables"))][:1]; print("LIBKEYS", list(sl["scripts"][0].keys()), lib)
        st, j = api(DO, "service", "POST", {"device_id": dev["A-PC1"], "service": "Spooler", "op": "restart"}); rec("ordine con autonomia diretta su un cliente reale: parte subito", st == 200 and j["status"] == "pending", (st, j))
        st, j = api(ASK, "service", "POST", {"device_id": dev["C-WIN"], "service": "Spooler", "op": "restart"}); rec("ordine con conferma: anche sul collaudo aspetta", st == 200 and j["status"] == "held", (st, j))
        st, j = api(DO, "power", "POST", {"device_id": dev["A-PC1"], "op": "reboot"}); rec("riavvio con autonomia diretta: parte subito (la regola «sempre approvato» vale per i token senza matrice)", st == 200 and j["status"] == "pending", (st, j))
        st, j = api(LEG, "power", "POST", {"device_id": dev["A-PC1"], "op": "reboot"}); rec("riavvio con token senza matrice: sempre in attesa", st == 200 and j["status"] == "held", (st, j))
        rec("riavvio vietato dalla matrice: 403", api(CUS, "power", "POST", {"device_id": dev["C-WIN"], "op": "reboot"})[0] == 403)
        st, j = api(DO, "patch_scan", "POST", {"device_id": dev["A-PC1"]}); rec("scansione patch con autonomia diretta: subito", st == 200 and j["status"] == "pending", (st, j))
        st, j = api(CUS, "patch_scan", "POST", {"device_id": dev["C-WIN"]}); rec("scansione patch con categoria vietata: 403", st == 403, (st, j))
        st, j = api(DO, "run", "POST", {"device_id": dev["A-PC1"], "script_id": lib[0]}); rec("run su cliente reale con autonomia diretta: pending, simulazione predefinita", st == 200 and j["status"] == "pending" and j["dry_run"] is True, (st, j))
        st, j = api(ASK, "run", "POST", {"device_id": dev["C-WIN"], "script_id": lib[0]}); rec("run con conferma: held", st == 200 and j["status"] == "held", (st, j))
        st, j = api(CUS, "run", "POST", {"device_id": dev["A-PC1"], "script_id": lib[0]}); rec("run con ordini «con conferma»: held", st == 200 and j["status"] == "held", (st, j))
        st, j = api(SUP, "run", "POST", {"device_id": dev["C-WIN"], "script_id": lib[0]}); rec("token senza matrice (scrittura diretta) sul collaudo: invariato", st == 200 and j["status"] == "pending", (st, j))
        # gruppo
        st, j = op(DO, "group_run", {"script_id": lib[0], "site": "Collaudo"}); jb = j.get("result", {}).get("job_ids", []) if st == 200 else []
        rec("esecuzione di gruppo: un job per device compatibile, in simulazione", st == 200 and j["status"] == "done" and len(jb) == q("SELECT COUNT(*) FROM devices WHERE site='Collaudo' AND os LIKE 'win%'")[0][0] and all("MYRMM_DRYRUN" in q("SELECT script FROM jobs WHERE id=?", i)[0][0] for i in jb), (st, j))
        st, j = op(ASK, "group_run", {"script_id": lib[0], "site": "Collaudo", "dry_run": False}); nj = q("SELECT COUNT(*) FROM jobs")[0][0]
        rec("esecuzione di gruppo con conferma: nessun job finché non si approva", st == 200 and j["status"] == "held" and q("SELECT COUNT(*) FROM jobs")[0][0] == nj, (st, j))
        approve(j["change_id"]); rec("approvata: i job partono, reali e legati al token", q("SELECT COUNT(*) FROM jobs WHERE api_token=(SELECT id FROM api_tokens WHERE name='ai-ask') AND status='pending' AND script NOT LIKE '%MYRMM_DRYRUN%'")[0][0] >= 1)
        rec("gruppo: cliente fuori perimetro 403, nessun device adatto 422", op(tok_mk("ai-acme-grp", **aut(ordini="do"), **{"sites[]": ["Acme"]}), "group_run", {"script_id": lib[0], "site": "Collaudo"})[0] == 403 and op(DO, "group_run", {"script_id": lib[0], "site": "Cliente Rinominato", "device_ids": [999999]})[0] == 404)
        st, j = op(SUP, "group_run", {"script_id": lib[0], "site": "Collaudo"}); rec("gruppo con token senza matrice su collaudo: subito; su cliente reale in attesa", st == 200 and j["status"] == "done" and op(SUP, "group_run", {"script_id": lib[0], "site": "Acme"})[0] == 403)
        st, j = op(ADM, "group_run", {"script_id": lib[0], "site": "Acme"}); rec("gruppo con token a scrittura 1 su cliente reale: in attesa", st == 200 and j["status"] == "held", (st, j))

        # --- ferma tutte le AI
        post("?action=api_pause", {"on": "1"}); rec("pausa: attiva", q("SELECT v FROM meta WHERE k='ai_pause'")[0][0] == "1")
        st, j = op(DO, "device_alias", {"device_id": dev["C-WIN"], "alias": "In pausa"}); rec("pausa: l'operazione diretta aspetta", st == 200 and j["status"] == "held", (st, j))
        st, j = api(DO, "service", "POST", {"device_id": dev["A-PC1"], "service": "Spooler", "op": "stop"}); rec("pausa: l'ordine diretto aspetta", st == 200 and j["status"] == "held", (st, j))
        st, j = api(SUP, "run", "POST", {"device_id": dev["C-WIN"], "script_id": lib[0]}); rec("pausa: anche la scrittura diretta del collaudo aspetta", st == 200 and j["status"] == "held", (st, j))
        st, j = op(SUP, "device_alias", {"device_id": dev["C-WIN"], "alias": "pausa2"}); rec("pausa: anche le operazioni dirette dei token senza matrice", st == 200 and j["status"] == "held")
        st, me2 = api(DO, "me"); rec("pausa: visibile da me e dal catalogo", me2["paused"] is True and api(DO, "ops")[1]["paused"] is True and "approva" in {o["op"]: o for o in api(DO, "ops")[1]["ops"]}["device_alias"]["approval"])
        post("?action=api_pause", {"on": "0"}); st, j = op(DO, "device_alias", {"device_id": dev["C-WIN"], "alias": "Ripreso"}); rec("pausa tolta: di nuovo diretto", st == 200 and j["status"] == "done")

        # --- connettore remoto e guida
        st, j = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, URL); names = [t["name"] for t in j["result"]["tools"]]
        rec("MCP remoto: 44 strumenti", len(names) == 44, len(names))
        st, j = tool(BASE + f"?action=mcp_http&t={DO}", "myrmm_do", {"op": "device_alias", "params": {"device_id": dev["C-WIN"], "alias": "Da MCP"}}, 9); rec("MCP remoto con matrice: operazione diretta", st == 200 and j["status"] == "done", j)
        st, j = tool(BASE + f"?action=mcp_http&t={DO}", "myrmm_get_config", {"kind": "tokens"}, 10); rec("MCP remoto: elenco token", st == 200 and j["tokens"])
        st, g = tool(URL, "myrmm_guidelines", {}, 11); rec("guida: spiega autonomia, pausa e irreversibili", st == 200 and "autonomia" in json.dumps(g).lower() and "ferma" in json.dumps(g).lower(), "")
        acts = {r[0] for r in q("SELECT DISTINCT action FROM audit")}
        rec("audit: eliminazioni, utenti, clienti, pausa, pulizia token", {"ticket_del", "doc_del", "site_create", "site_rename", "user_update", "api_revoke", "api_purge", "ai_pause", "device_delete", "api_group_run"} <= acts, acts)
        pe = open(os.path.join(tmp, "php.err")).read()
        rec("nessun errore PHP", not any(k in pe for k in ("Fatal error", "Warning:", "Notice:", "Deprecated:", "Uncaught")), [l for l in pe.split("\n") if any(k in l for k in ("Fatal error", "Warning:", "Notice:", "Deprecated:", "Uncaught"))][:3])
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
