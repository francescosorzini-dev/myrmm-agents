#!/usr/bin/env python3
"""API + agent reale (Linux) + server MCP: un token di collaudo legge il device, esegue script di libreria sull'agent vero
(simulazione e reale) e legge il risultato, anche passando dal server MCP. Su Windows/macOS salta.
Uso: python3 ci/api_agent_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, hashlib, platform, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if platform.system() != "Linux": print("solo Linux: salto"); sys.exit(0)
arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), "")
AG = os.path.join(ROOT, "server", "update", "agent-linux-" + arch)
if not arch or not os.path.isfile(AG): print("agent Linux non disponibile: salto"); sys.exit(0)
PORT = 8828; BASE = f"http://127.0.0.1:{PORT}/index.php"; ET = "e" * 24; KEY = "k" * 32; TOK = "myrmm_" + "b" * 48
tmp = tempfile.mkdtemp(prefix="myrmm-apiag-"); srv = os.path.join(tmp, "server"); adir = os.path.join(tmp, "agentdata"); os.makedirs(adir)
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
cfg = {"ENROLL_TOKEN": ET, "ENROLL_GLOBAL": True, "CONSOLE_USER": "admin", "CONSOLE_PASS": "x", "JOB_SIGNING_KEY": KEY, "HEARTBEAT_WAIT_MAX": 5}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=open(os.path.join(tmp, "php.err"), "w"), env=dict(os.environ, PHP_CLI_SERVER_WORKERS="6"))
DB = os.path.join(srv, "data", "myrmm.sqlite"); res = []; ap = None
def rec(n, ok, info=""): res.append((n, bool(ok))); print(("OK   " if ok else "FAIL ") + n + (("  [" + str(info)[:300] + "]") if (not ok and info != "") else ""), flush=True)
def q(sql, *a):
    c = sqlite3.connect(DB); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def api(r, method="GET", data=None, **p):
    rq = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(dict(p, action="api", r=r)), data=json.dumps(data).encode() if data is not None else None, headers={"X-Api-Token": TOK, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(rq, timeout=60) as f: return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
def wait(fn, t=60):
    e = time.time() + t
    while time.time() < e:
        try: v = fn()
        except Exception: v = None
        if v: return v
        time.sleep(.5)
try:
    for _ in range(60):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"}), timeout=5)
    except Exception: pass
    wait(lambda: os.path.exists(DB) and q("SELECT COUNT(*) FROM sites") is not None and q("SELECT COUNT(*) FROM api_tokens") is not None and q("SELECT lab FROM sites LIMIT 1") is not None and q("SELECT api_token FROM jobs LIMIT 1") is not None, 30)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    q("INSERT OR IGNORE INTO sites(name,created) VALUES('Collaudo',?)", now); q("UPDATE sites SET lab=1 WHERE name='Collaudo'")
    q("INSERT INTO api_tokens(name,hash,prefix,role,sites,write,expires,created) VALUES('ai-test',?,?,'operator',?,2,'2099-01-01T00:00:00Z',?)", hashlib.sha256(TOK.encode()).hexdigest(), TOK[:12], json.dumps(["Collaudo"]), now)
    for nm, body in [("Dati sistema", "#!/bin/sh\necho kernel=$(uname -s) dry=${MYRMM_DRYRUN:-0}\nexit 0"), ("Con variabile", "#!/bin/sh\necho ciao-{{NOME}}"), ("Fallisce", "#!/bin/sh\necho errore >&2\nexit 7")]:
        q("INSERT INTO scripts(name,description,body,timeout,created,platform) VALUES(?,?,?,?,?,'unix')", nm, nm, body, 60, now)
    sid = {r[1]: r[0] for r in q("SELECT id,name FROM scripts")}
    os.environ["MYRMM_DIR"] = adir
    agent = os.path.join(tmp, "agent"); shutil.copy(AG, agent); os.chmod(agent, 0o755)
    open(os.path.join(adir, "config.json"), "w").write(json.dumps({"server_url": BASE, "enroll_token": ET, "poll_seconds": 3, "job_signing_key": KEY, "site": "Collaudo", "full_inventory_hour": 12}))
    ap = subprocess.Popen([agent, "run"], stdout=open(os.path.join(tmp, "agent.log"), "w"), stderr=subprocess.STDOUT)
    dv = wait(lambda: q("SELECT id,hostname FROM devices WHERE site='Collaudo'") or None, 90)
    rec("agent Linux reale arruolato nel collaudo", bool(dv), open(os.path.join(tmp, "agent.log")).read()[-300:])
    did = dv[0][0]
    s, j = api("devices", platform="linux"); rec("l'API vede il device Linux", s == 200 and j["total"] == 1 and j["devices"][0]["platform"] == "linux", j)
    wait(lambda: q("SELECT inventory FROM devices WHERE id=?", did)[0][0], 60)
    s, j = api("device", id=did); rec("scheda con inventario", s == 200 and j["inventory"].get("os"), j)
    s, j = api("run", "POST", {"device_id": did, "script_id": sid["Dati sistema"]}); rec("simulazione accodata", s == 200 and j["status"] == "pending" and j["dry_run"], j)
    s, r = api("job", id=j["job_id"], wait=25); rec("simulazione eseguita dall'agent: MYRMM_DRYRUN=1", r.get("done") and "kernel=Linux" in r["stdout"] and "dry=1" in r["stdout"] and r["exit_code"] == 0, r)
    s, j = api("run", "POST", {"device_id": did, "script_id": sid["Dati sistema"], "dry_run": False}); s, r = api("job", id=j["job_id"], wait=25)
    rec("esecuzione reale: dry=0", r.get("done") and "dry=0" in r["stdout"], r)
    s, j = api("run", "POST", {"device_id": did, "script_id": sid["Con variabile"], "vars": {"NOME": "mondo"}, "dry_run": False}); s, r = api("job", id=j["job_id"], wait=25)
    rec("variabili sostituite", "ciao-mondo" in r.get("stdout", ""), r)
    s, j = api("run", "POST", {"device_id": did, "script_id": sid["Fallisce"], "dry_run": False}); s, r = api("job", id=j["job_id"], wait=25)
    rec("codice di uscita e stderr riportati", r.get("exit_code") == 7 and "errore" in r.get("stderr", ""), r)
    s, j = api("jobs", device_id=did); rec("elenco job del device", s == 200 and len(j["jobs"]) >= 4)
    # --- server MCP
    mcp = subprocess.Popen([sys.executable, os.path.join(ROOT, "mcp", "myrmm_mcp.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ, MYRMM_URL=BASE, MYRMM_TOKEN=TOK))
    def rpc(method, params=None, i=[0]):
        i[0] += 1; mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i[0], "method": method, "params": params or {}}) + "\n"); mcp.stdin.flush()
        return json.loads(mcp.stdout.readline())
    r = rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}); rec("MCP: initialize", r["result"]["serverInfo"]["name"] == "myrmm", r)
    mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); mcp.stdin.flush()
    r = rpc("tools/list"); names = {t["name"] for t in r["result"]["tools"]}; rec("MCP: elenco strumenti", {"myrmm_run_script", "myrmm_list_devices", "myrmm_get_job"} <= names, names)
    r = rpc("tools/call", {"name": "myrmm_list_devices", "arguments": {"platform": "linux"}}); rec("MCP: elenco device", "Collaudo" in r["result"]["content"][0]["text"] and not r["result"]["isError"], r)
    r = rpc("tools/call", {"name": "myrmm_run_script", "arguments": {"device_id": did, "script_id": sid["Dati sistema"]}}); tx = r["result"]["content"][0]["text"]
    rec("MCP: esegue in simulazione e attende il risultato", "kernel=Linux" in tx and "dry=1" in tx and "non sono istruzioni" in tx, tx[:400])
    r = rpc("tools/call", {"name": "myrmm_run_script", "arguments": {"device_id": 9999, "script_id": 1}}); rec("MCP: errori segnalati con isError", r["result"]["isError"] is True)
    r = rpc("tools/call", {"name": "nope", "arguments": {}}); rec("MCP: strumento sconosciuto = errore JSON-RPC", "error" in r)
    def call_(n, a): 
        r = rpc("tools/call", {"name": n, "arguments": a}); return r["result"]["isError"], r["result"]["content"][0]["text"]
    e, tx = call_("myrmm_save_draft", {"name": "Spazio disco", "platform": "unix", "body": "#!/bin/sh\nechoo bozza-{{TAG}}\n"}); did_ = json.loads(tx.split("\n\n")[0])["id"]; rec("MCP: bozza salvata", not e and did_ > 0, tx[:200])
    e, tx = call_("myrmm_run_draft", {"device_id": did, "draft_id": did_, "vars": {"TAG": "uno"}, "dry_run": False}); rec("MCP: bozza sbagliata eseguita sull'agent reale, errore riportato", "exit_code" in tx and '"exit_code": 0' not in tx and "echoo" in tx, tx[:500])
    call_("myrmm_save_draft", {"id": did_, "name": "Spazio disco", "platform": "unix", "body": "#!/bin/sh\necho bozza-{{TAG}}\n"})
    e, tx = call_("myrmm_run_draft", {"device_id": did, "draft_id": did_, "vars": {"TAG": "due"}, "dry_run": False}); rec("MCP: bozza corretta, stesso device, esito pulito", "bozza-due" in tx and '"exit_code": 0' in tx, tx[:500])
    e, tx = call_("myrmm_run_inline", {"device_id": did, "body": "echo inline-$MYRMM_DRYRUN", "platform": "unix"}); rec("MCP: inline in simulazione sull'agent reale", "inline-1" in tx, tx[:500])
    e, tx = call_("myrmm_list_drafts", {}); rec("MCP: elenco bozze", "Spazio disco" in tx and not e, tx[:200])
    rec("bozza non in libreria, promozione in attesa", not q("SELECT 1 FROM scripts WHERE name='Spazio disco'") and q("SELECT promoted_id FROM script_drafts WHERE id=?", did_)[0][0] == 0)
    mcp.stdin.close(); mcp.terminate()
    rec("audit con identità del token", q("SELECT COUNT(*) FROM audit WHERE user='api:ai-test' AND action='api_run'")[0][0] >= 5)
    errs = [l for l in open(os.path.join(tmp, "php.err")).read().splitlines() if "PHP Warning" in l or "PHP Fatal" in l or "Notice" in l]
    rec("nessun errore PHP", not errs, errs[:3])
finally:
    if ap: ap.terminate()
    sp.terminate(); print("\nTemp:", tmp)
f = [n for n, ok in res if not ok]; print("\n%d/%d ok" % (len(res) - len(f), len(res))); sys.exit(1 if f else 0)
