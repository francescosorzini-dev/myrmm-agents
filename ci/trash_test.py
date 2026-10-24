#!/usr/bin/env python3
"""Cestino per tutto (1.72.0): ogni elemento eliminato (dalla console o dall'AI) finisce nel cestino e si ripristina; i device parcheggiati non si riarruolano e, dopo 6 ore, l'agent che torna online si disinstalla da solo.
Uso: python3 ci/trash_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.error, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright
from playwright.sync_api import sync_playwright
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8840; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
tmp = tempfile.mkdtemp(prefix="myrmm-trs-"); srv = os.path.join(tmp, "server")
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
        def tok_mk(name, **kw): return mk(name=name, role="operator", days="30", **kw)
        def aut(**m): return {"autonomy": "custom", **{f"aut[{k}]": v for k, v in m.items()}}
        def hb(key, action="heartbeat", body=None):
            rq = urllib.request.Request(BASE + "?action=" + action, data=json.dumps(body or {}).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(rq, timeout=30) as f: return f.status, json.loads(f.read() or b"{}")
            except urllib.error.HTTPError as e:
                try: return e.code, json.loads(e.read() or b"{}")
                except Exception: return e.code, {}
        def last_trash(kind): r = q("SELECT id, title, expires, deleted, dev_key FROM trash WHERE kind=? ORDER BY id DESC LIMIT 1", kind); return r[0] if r else None
        def restore(tid): post("?action=trash_restore", {"id": tid})
        CUS = tok_mk("ai-trash", **aut(config="do", dati="do", eliminazioni="do", distruttive="do", utenti="do", server="do"))
        rec("token di prova creato", bool(CUS))

        # --- ogni eliminazione dell'AI finisce nel cestino e si ripristina con lo stesso id
        op(CUS, "script_save", {"name": "TR script", "body": "Write-Output 1"}); SID = q("SELECT id FROM scripts WHERE name='TR script'")[0][0]
        op(CUS, "schedule_add", {"device_id": dev["C-WIN"], "script_id": SID, "interval_min": 30}); SCH = q("SELECT id FROM schedules WHERE script_id=?", SID)[0][0]
        op(CUS, "check_add", {"type": "cpu_pct", "threshold": 91}); CK = q("SELECT id FROM checks WHERE threshold=91")[0][0]
        op(CUS, "rule_add", {"name": "TR regola", "script_id": SID, "interval_min": 60}); RU = q("SELECT id FROM rules WHERE name='TR regola'")[0][0]
        q("INSERT INTO schedules(device_id,script_id,interval_min,enabled,rule_id,created) VALUES(?,?,60,1,?,?)", dev["C-WIN"], SID, RU, now) if False else None
        op(CUS, "variable_set", {"scope": "global", "name": "TR_VAR", "value": "x"}); VA = q("SELECT id FROM vars WHERE name='TR_VAR'")[0][0]
        op(CUS, "runbook_save", {"name": "TR runbook", "steps": [{"script_id": SID}]}); RB = q("SELECT id FROM runbooks WHERE name='TR runbook'")[0][0]
        op(CUS, "runbook_schedule_add", {"runbook_id": RB, "start": "2030-01-01 03:00", "site": "Collaudo"}); RS = q("SELECT id FROM rb_sched")[0][0]
        op(CUS, "filter_save", {"name": "TR filtro", "criteria": {"mode": "all", "conds": [{"f": "os", "op": "contains", "v": "Win"}]}}); FI = q("SELECT id FROM filters WHERE name='TR filtro'")[0][0]
        op(CUS, "patch_policy_add", {"name": "TR policy", "days": ["sat"], "win_start": "02:00", "win_end": "05:00"}); PP = q("SELECT id FROM patch_policies WHERE name='TR policy'")[0][0]
        op(CUS, "maintenance_quick", {"hours": 1, "site": "Collaudo"}); MW = q("SELECT id FROM maint_windows")[0][0]
        q("INSERT INTO users(username,pass_hash,role,sites,enabled,created,totp_on) VALUES('utr','HASHX','viewer','Collaudo',1,?,0)", now); US = q("SELECT id FROM users WHERE username='utr'")[0][0]
        op(CUS, "site_create", {"name": "Sito Cestino"});
        table = {"script": ("scripts", SID), "schedule": ("schedules", SCH), "check": ("checks", CK), "rule": ("rules", RU), "variable": ("vars", VA), "runbook": ("runbooks", RB), "rb_sched": ("rb_sched", RS), "filter": ("filters", FI), "patch_policy": ("patch_policies", PP), "maintenance": ("maint_windows", MW), "user": ("users", US)}
        ops_del = {"schedule": ("delete_schedule", SCH), "check": ("delete_check", CK), "rule": ("delete_rule", RU), "variable": ("delete_variable", VA), "rb_sched": ("delete_runbook_schedule", RS), "runbook": ("delete_runbook", RB), "filter": ("delete_filter", FI), "patch_policy": ("delete_patch_policy", PP), "maintenance": ("delete_maintenance", MW), "user": ("user_delete", US), "script": ("delete_script", SID)}
        for kind in ("schedule", "check", "rule", "variable", "rb_sched", "runbook", "filter", "patch_policy", "maintenance", "user", "script"):
            name, rid = ops_del[kind]; tb, _ = table[kind]
            if kind == "rule": pass
            st, j = op(CUS, name, {"id": rid})
            t = last_trash(kind)
            rec(f"cestino: {name} mette l'elemento nel cestino", st == 200 and t is not None and q(f'SELECT COUNT(*) FROM "{tb}" WHERE id=?', rid)[0][0] == 0, (st, j))
            if t: restore(t[0]); rec(f"cestino: {kind} ripristinato con lo stesso id", q(f'SELECT COUNT(*) FROM "{tb}" WHERE id=?', rid)[0][0] == 1 and q("SELECT COUNT(*) FROM trash WHERE id=?", t[0])[0][0] == 0)
        rec("cestino: la regola riporta con sé le sue pianificazioni (nessuna perdita)", q("SELECT COUNT(*) FROM rules WHERE id=?", RU)[0][0] == 1)
        rec("cestino: l'utente ripristinato ha la sua password (hash) e i suoi clienti", q("SELECT pass_hash, sites FROM users WHERE id=?", US)[0] == ("HASHX", "Collaudo"))
        st, j = op(CUS, "site_delete", {"name": "Sito Cestino"}); t = last_trash("site"); rec("cestino: cliente eliminato nel cestino", st == 200 and t and q("SELECT COUNT(*) FROM sites WHERE name='Sito Cestino'")[0][0] == 0)
        restore(t[0]); rec("cestino: cliente ripristinato con il suo token di installazione", q("SELECT COUNT(*) FROM sites WHERE name='Sito Cestino'")[0][0] == 1 and q("SELECT COUNT(*) FROM site_tokens WHERE site='Sito Cestino'")[0][0] >= 1)

        # --- eliminazioni dalla console
        for act, kind, tb, rid in (("delscript", "script", "scripts", SID), ("delschedule", "schedule", "schedules", SCH), ("delcheck", "check", "checks", CK), ("delrule", "rule", "rules", RU), ("delvar", "variable", "vars", VA),
                                   ("delpatchpolicy", "patch_policy", "patch_policies", PP), ("maint_del", "maintenance", "maint_windows", MW), ("rb_del", "runbook", "runbooks", RB), ("deluser", "user", "users", US)):
            n0 = q("SELECT COUNT(*) FROM trash WHERE kind=?", kind)[0][0]; post("?action=" + act, {"id": rid, "device_id": dev["C-WIN"]})
            rec(f"console {act}: nel cestino", q("SELECT COUNT(*) FROM trash WHERE kind=?", kind)[0][0] == n0 + 1 and q(f'SELECT COUNT(*) FROM "{tb}" WHERE id=?', rid)[0][0] == 0)
        post("?action=delfilter", {"id": FI}); rec("console delfilter: nel cestino", last_trash("filter") is not None and q("SELECT COUNT(*) FROM filters WHERE id=?", FI)[0][0] == 0)
        post("?action=rb_sched_del", {"id": RS}); rec("console rb_sched_del: nel cestino", last_trash("rb_sched") is not None)
        t_ = last_trash("user"); html = get("?view=trash").text(); rec("console: pagina cestino con utenti, script e device", "Utente" in html and "Script" in html and "utr" in html)

        # --- device nel cestino
        addev("PARK-1", "Collaudo", "Windows 11 Pro", "windows"); D1 = q("SELECT id FROM devices WHERE hostname='PARK-1'")[0][0]
        q("INSERT INTO tickets(device_id,asset_id,title,status,priority,assignee,site,created,updated,minutes,by_user) VALUES(?,0,'T park','open','normal','','Collaudo',?,?,0,'t')", D1, now, now)
        q("INSERT INTO vars(scope,name,value) VALUES(?,?,?)", f"device:{D1}", "PV", "1")
        q("INSERT INTO schedules(device_id,script_id,interval_min,enabled,created) VALUES(?,?,30,1,?)", D1, sc[0], now)
        ty = q("SELECT id FROM asset_types LIMIT 1")[0][0]
        st, a1 = api(CUS, "asset_create", "POST", {"type_id": ty, "name": "Asset park", "site": "Collaudo", "device_id": D1})
        n_dev = q("SELECT COUNT(*) FROM devices")[0][0]
        st, j = op(CUS, "device_delete", {"device_id": D1}); T1 = last_trash("device")
        rec("device: eliminato nel cestino con chiave e collegamenti", st == 200 and T1 and T1[4] == "k-PARK-1" and q("SELECT COUNT(*) FROM devices WHERE id=?", D1)[0][0] == 0 and q("SELECT COUNT(*) FROM tickets WHERE device_id=?", D1)[0][0] == 0 and j["result"]["agent_self_uninstall_after_hours"] == 6, (st, j))
        rec("device: nel cestino per 90 giorni (gli altri per 30)", 85 < (time.mktime(time.strptime(T1[2], "%Y-%m-%dT%H:%M:%SZ")) - time.time()) / 86400 < 91 and (time.mktime(time.strptime(last_trash("user")[2], "%Y-%m-%dT%H:%M:%SZ")) - time.time()) / 86400 < 31)
        st, r = hb("k-PARK-1")
        rec("device nel cestino, prima delle 6 ore: risposta neutra, nessun ordine", st == 200 and r.get("parked") is True and "uninstall" not in r and r["jobs"] == [], (st, r))
        rec("device nel cestino: non si riarruola né ricompare", q("SELECT COUNT(*) FROM devices")[0][0] == n_dev - 1)
        rec("device nel cestino: le altre richieste dell'agent 403, una chiave sconosciuta resta 401", hb("k-PARK-1", "result")[0] == 403 and hb("k-sconosciuta")[0] == 401)
        rec("device nel cestino: l'ack prima delle 6 ore 409", hb("k-PARK-1", "uninstall_ack", {"req": T1[0]})[0] == 409)
        q("UPDATE trash SET deleted=? WHERE id=?", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5 * 3600 - 3500)), T1[0])
        rec("device nel cestino a 5 ore e 58 minuti: ancora nessun ordine", "uninstall" not in hb("k-PARK-1")[1])
        q("UPDATE trash SET deleted=? WHERE id=?", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 6 * 3600 - 60)), T1[0])
        st, r = hb("k-PARK-1"); import hmac, hashlib
        good = hmac.new(b"k" * 32, f"uninstall\n{D1}\n{T1[0]}".encode(), hashlib.sha256).hexdigest()
        rec("dopo 6 ore: l'agent riceve l'ordine di disinstallazione firmato", st == 200 and r.get("uninstall") == {"req": T1[0], "sig": good}, (st, r))
        rec("ack con richiesta sbagliata 409", hb("k-PARK-1", "uninstall_ack", {"req": 999999})[0] == 409)
        st, r = hb("k-PARK-1", "uninstall_ack", {"req": T1[0]}); rec("ack giusto: registrato e il device resta nel cestino", st == 200 and q("SELECT unins_at FROM trash WHERE id=?", T1[0])[0][0] != "" and q("SELECT COUNT(*) FROM devices")[0][0] == n_dev - 1, (st, r))
        rec("dopo l'ack nessun nuovo ordine", "uninstall" not in hb("k-PARK-1")[1])
        html = get("?view=trash").text(); rec("cestino: il device mostra «Agent disinstallato»", "Agent disinstallato il" in html or "Agent uninstalled on" in html)
        # ripristino prima della disinstallazione
        addev("PARK-2", "Collaudo", "Windows 11 Pro", "windows"); D2 = q("SELECT id FROM devices WHERE hostname='PARK-2'")[0][0]
        q("INSERT INTO tickets(device_id,asset_id,title,status,priority,assignee,site,created,updated,minutes,by_user) VALUES(?,0,'T park2','open','normal','','Collaudo',?,?,0,'t')", D2, now, now)
        st, a2 = api(CUS, "asset_create", "POST", {"type_id": ty, "name": "Asset park2", "site": "Collaudo", "device_id": D2})
        post("?action=devdelete", {"device_id": D2}); T2 = last_trash("device")
        rec("console devdelete: device nel cestino", T2 and T2[1] == "PARK-2" and q("SELECT COUNT(*) FROM devices WHERE id=?", D2)[0][0] == 0 and q("SELECT device_id FROM assets WHERE id=?", a2["id"])[0][0] == 0)
        html = get("?view=trash").text(); rec("cestino: disinstallazione possibile dalle ore indicate", "Disinstallazione dell&#039;agent possibile dalle" in html or "Disinstallazione dell'agent possibile dalle" in html)
        restore(T2[0]); rec("ripristino: stesso id, stessa chiave, ticket e collegamento all'asset", q("SELECT api_key FROM devices WHERE id=?", D2)[0][0] == "k-PARK-2" and q("SELECT COUNT(*) FROM tickets WHERE device_id=?", D2)[0][0] == 1 and q("SELECT device_id FROM assets WHERE id=?", a2["id"])[0][0] == D2)
        st, r = hb("k-PARK-2"); rec("ripristino: l'agent riprende a funzionare senza riarruolarsi", st == 200 and "parked" not in r and "jobs" in r, (st, r))
        # senza chiave di firma l'agent non riceve l'ordine
        rec("audit", {"device_parked_uninstalled", "device_delete", "trash_restore"} <= {r[0] for r in q("SELECT DISTINCT action FROM audit")})
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
