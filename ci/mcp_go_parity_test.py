#!/usr/bin/env python3
"""Il server MCP in Go (mcp/go) deve comportarsi come quello Python (mcp/myrmm_mcp.py): stessi strumenti, stesse richieste
all'API, stesse risposte. Una API finta registra ogni richiesta; si fa girare la stessa sequenza JSON-RPC sui due server e si
confrontano risposte e richieste. In più: configurazione (file con BOM, collegamento simbolico, MYRMM_CONFIG, proxy), --check, --version.
Uso: python3 ci/mcp_go_parity_test.py"""
import json, os, shutil, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "mcp", "myrmm_mcp.py"); GOSRC = os.path.join(ROOT, "mcp", "go")
if not shutil.which("go"): print("go non disponibile: salto"); sys.exit(0)
tmp = tempfile.mkdtemp(prefix="myrmm-mcpgo-"); EXE = os.path.join(tmp, "bin", "myrmm-mcp" + (".exe" if os.name == "nt" else "")); os.makedirs(os.path.dirname(EXE))
b = subprocess.run(["go", "build", "-trimpath", "-o", EXE, "."], cwd=GOSRC, capture_output=True, text=True)
if b.returncode: print("BUILD FALLITA\n" + b.stderr); sys.exit(1)
TOK = "myrmm_" + "a" * 48
res = []
def rec(n, ok, info=""):
    res.append(bool(ok)); print(("OK   " if ok else "FAIL ") + n + (("  [" + str(info)[:600] + "]") if (not ok and info != "") else ""), flush=True)

LOG = []
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _do(self, method):
        n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n) if n else b""
        u = urllib.parse.urlsplit(self.path); q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        try: body = json.loads(raw) if raw else None
        except Exception: body = "NONJSON:" + raw.decode("utf-8", "replace")
        LOG.append({"method": method, "path": u.path, "abs": self.path.startswith("http"), "q": q, "body": body, "tok": self.headers.get("X-Api-Token"), "ct": self.headers.get("Content-Type")})
        r = q.get("r"); code = 200; out = None; ctype = "application/json"
        if self.headers.get("X-Api-Token") != TOK: code, out = 401, {"error": "token non valido"}
        elif r == "me": out = '{"name": "ai-test", "role": "operator", "write_label": "solo collaudo", "z": 1, "a": [1, 2.5, true, null, {}], "vuoto": [], "t": "Perch\\u00e9 \\u20ac \\"ok\\"\\n"}'
        elif r in ("guidelines", "sites", "backup", "audit", "drafts", "scripts", "devices", "device", "alerts", "draft_save", "draft_delete", "cancel"):
            out = {"resource": r, "echo": q, "body": body, "elenco": [{"id": 1, "nome": "è"}, {"id": 2}]}
        elif r == "job":
            out = {"id": int(q.get("id") or 0), "done": True, "output": "ciao dal device", "wait": q.get("wait")}
        elif r == "run":
            d = (body or {}).get("device_id")
            if d == 1: out = {"status": "pending", "job_id": 7}
            elif d == 2: code, out = 403, {"error": "vietato", "dettaglio": "cliente non di collaudo"}
            elif d == 3: out = {"status": "done", "output": "subito"}
            elif d == 4: code, out, ctype = 500, "boom <html>", "text/html"
            elif d == 5: out = ""
            elif d == 6: out = "{non json"
            else: out = {"status": "pending", "job_id": 9}
        else: code, out = 404, {"error": "risorsa sconosciuta"}
        data = out.encode() if isinstance(out, str) else json.dumps(out).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self): self._do("GET")
    def do_POST(self): self._do("POST")
srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/index.php"
clean = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "no_proxy", "all_proxy", "myrmm_url", "myrmm_token", "myrmm_config", "myrmm_proxy")}

def rpc(i, method, params=None): return json.dumps({"jsonrpc": "2.0", "id": i, "method": method, **({"params": params} if params is not None else {})})
def call(i, name, args=None): return rpc(i, "tools/call", {"name": name, **({"arguments": args} if args is not None else {})})
SEQ = [rpc(1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}}),
       '{"jsonrpc":"2.0","method":"notifications/initialized"}', rpc(2, "ping"), rpc(3, "tools/list"), "", "{non json", "[1,2]", '"stringa"',
       call(4, "myrmm_status"), call(5, "myrmm_guidelines"), call(6, "myrmm_list_sites"),
       call(7, "myrmm_list_devices", {"site": "Collaudo", "q": "pc", "platform": "windows", "online": 1, "limit": 5}),
       call(8, "myrmm_list_devices", {"site": "", "q": None}), call(9, "myrmm_get_device", {"id": 12, "include": "system,software"}),
       call(10, "myrmm_list_alerts", {"status": "all", "severity": "crit", "device_id": 3, "limit": 10}),
       call(11, "myrmm_list_scripts"), call(12, "myrmm_list_scripts", {"body": True}), call(13, "myrmm_list_scripts", {"body": False}),
       call(14, "myrmm_backup_status"), call(15, "myrmm_audit", {"limit": 20, "since": 5}),
       call(16, "myrmm_run_script", {"device_id": 1, "script_id": 4, "vars": {"NOME": "x è y", "N": 3}}),
       call(17, "myrmm_run_script", {"device_id": 1, "script_id": 4, "dry_run": False, "wait": 0}),
       call(18, "myrmm_run_script", {"device_id": 1, "script_id": 4, "wait": 99}), call(19, "myrmm_run_script", {"device_id": 1, "script_id": 4, "wait": "3"}),
       call(20, "myrmm_run_script", {"device_id": 2, "script_id": 4}), call(21, "myrmm_run_script", {"device_id": 3, "script_id": 4}),
       call(22, "myrmm_run_script", {"device_id": 4, "script_id": 4}), call(23, "myrmm_run_script", {"device_id": 5, "script_id": 4}),
       call(24, "myrmm_run_script", {"device_id": 6, "script_id": 4}), call(25, "myrmm_run_script", {"device_id": 1, "script_id": 4, "wait": -5}),
       call(26, "myrmm_list_drafts", {"body": True}), call(27, "myrmm_save_draft", {"name": "bozza", "body": "echo ciao", "platform": "unix", "timeout": 60, "description": None}),
       call(28, "myrmm_save_draft", {"id": 3, "name": "n", "body": "b"}), call(29, "myrmm_delete_draft", {"id": 3}),
       call(30, "myrmm_run_draft", {"device_id": 1, "draft_id": 3, "vars": {"A": "1"}}), call(31, "myrmm_run_draft", {"device_id": 1, "draft_id": 3, "dry_run": False, "wait": 2}),
       call(32, "myrmm_run_inline", {"device_id": 1, "body": "echo é"}), call(33, "myrmm_run_inline", {"device_id": 1, "body": "x", "platform": "windows", "timeout": 30, "dry_run": False}),
       call(34, "myrmm_get_job", {"id": 7}), call(35, "myrmm_get_job", {"id": 7, "wait": 10}), call(36, "myrmm_cancel_job", {"job_id": 7}),
       call(37, "nessuno", {}), rpc(38, "metodo/ignoto"), call(39, "myrmm_status", None), rpc("abc", "ping"), rpc(0, "ping"),
       '{"jsonrpc":"2.0","id":null,"method":"ping"}', call(40, "myrmm_get_device", {"id": 12})]

def run(cmd, extra_env=None, lines=SEQ, cwd=None):
    LOG.clear(); env = {**clean, "MYRMM_URL": BASE, "MYRMM_TOKEN": TOK, **(extra_env or {})}
    p = subprocess.run(cmd, input="\n".join(lines) + "\n", capture_output=True, text=True, encoding="utf-8", timeout=120, env=env, cwd=cwd)
    out = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    return out, [dict(x) for x in LOG], p
def norm(log): return [{k: v for k, v in x.items() if k != "abs"} for x in log]

try:
    po, pl, pp = run([sys.executable, PY]); go_, gl, gp = run([EXE])
    rec("Go e Python rispondono a ogni richiesta (stesso numero di risposte)", len(po) == len(go_) and len(po) >= 40, (len(po), len(go_), gp.stderr[:300]))
    rec("stesse richieste all'API (metodo, risorsa, parametri, corpo, token, tipo)", norm(pl) == norm(gl), next(((i, a, b) for i, (a, b) in enumerate(zip(norm(pl), norm(gl))) if a != b), (len(pl), len(gl))))
    diff = [(a.get("id"), a, b) for a, b in zip(po, go_) if a != b and a.get("id") != 24]
    rec("stesse risposte JSON-RPC (strutture uguali)", not diff, diff[:1])
    a24, b24 = next(x for x in po if x.get("id") == 24), next(x for x in go_ if x.get("id") == 24)   # risposta non JSON dal server: cambia solo il testo del parser
    rec("risposta 200 non JSON dal server: isError con messaggio, in entrambi", a24["result"]["isError"] and b24["result"]["isError"] and '"error"' in b24["result"]["content"][0]["text"])
    tx = [(a["id"]) for a, b in zip(po, go_) if a.get("id") != 24 and "result" in a and "content" in a["result"] and a["result"]["content"][0]["text"] != b["result"]["content"][0]["text"]]
    rec("testo dei risultati identico (ordine delle chiavi, rientro, accenti non escapati)", not tx, tx)
    t = next(x for x in go_ if x.get("id") == 4)["result"]["content"][0]["text"]
    rec("ordine delle chiavi del server rispettato e «è/€» in chiaro", t.index('"z"') < t.index('"a"') and "Perché € " in t and '"vuoto": []' in t and "{}" in t, t[:200])
    ti = next(x for x in go_ if x.get("id") == 3)["result"]["tools"]
    rec("44 strumenti con descrizioni e schemi uguali a Python", len(ti) == 44 and ti == next(x for x in po if x.get("id") == 3)["result"]["tools"], len(ti))
    rec("nessuna risposta alle notifiche, ai testi non JSON e alle righe vuote", [x.get("id") for x in go_ if x.get("id") in (None,)] == [] and len(go_) == len(po))
        # scarti voluti, verificati a parte: i booleani nella query
    _, gl2, _ = run([EXE], lines=[call(1, "myrmm_list_devices", {"online": True}), call(2, "myrmm_list_devices", {"online": False})])
    rec("booleani in query: true->1, false->0", [x["q"].get("online") for x in gl2] == ["1", "0"], [x["q"] for x in gl2])
    # connessione rifiutata: errore, non crash
    dead, _, _ = run([EXE], {"MYRMM_URL": "http://127.0.0.1:9/index.php"}, [call(1, "myrmm_status")])
    pdead, _, _ = run([sys.executable, PY], {"MYRMM_URL": "http://127.0.0.1:9/index.php"}, [call(1, "myrmm_status")])
    rec("rete irraggiungibile: isError e messaggio, come Python", dead[0]["result"]["isError"] is True and "error" in dead[0]["result"]["content"][0]["text"] and pdead[0]["result"]["isError"] is True)
    # configurazione mancante
    nocfg, _, _ = run([EXE], {"MYRMM_URL": "", "MYRMM_TOKEN": "", "MYRMM_CONFIG": os.path.join(tmp, "non-esiste.json")}, [call(1, "myrmm_status")])
    rec("senza configurazione: errore chiaro, nessun crash", nocfg[0]["result"]["isError"] is True and "MYRMM_URL e MYRMM_TOKEN non sono impostati" in nocfg[0]["result"]["content"][0]["text"])
    # file di configurazione accanto all'eseguibile, con BOM (PowerShell)
    cfgp = os.path.join(os.path.dirname(EXE), "myrmm-mcp.json"); open(cfgp, "wb").write(b"\xef\xbb\xbf" + json.dumps({"url": BASE, "token": TOK}).encode())
    out, lg, _ = run([EXE], {"MYRMM_URL": "", "MYRMM_TOKEN": ""}, [call(1, "myrmm_status")])
    rec("config accanto all'eseguibile (anche con BOM)", out[0]["result"]["isError"] is False and lg and lg[0]["tok"] == TOK, out)
    if os.name != "nt":
        ln = os.path.join(tmp, "link-mcp"); os.symlink(EXE, ln)
        out, lg, _ = run([ln], {"MYRMM_URL": "", "MYRMM_TOKEN": ""}, [call(1, "myrmm_status")])
        rec("collegamento simbolico (/usr/local/bin): la config si cerca accanto all'eseguibile vero", out[0]["result"]["isError"] is False, out)
    os.remove(cfgp)
    alt = os.path.join(tmp, "alt.json"); open(alt, "w").write(json.dumps({"url": BASE, "token": TOK}))
    out, lg, _ = run([EXE], {"MYRMM_URL": "", "MYRMM_TOKEN": "", "MYRMM_CONFIG": alt}, [call(1, "myrmm_status")])
    rec("MYRMM_CONFIG indica un altro file", out[0]["result"]["isError"] is False)
    out, lg, _ = run([EXE], {"MYRMM_TOKEN": "myrmm_" + "0" * 48}, [call(1, "myrmm_status")])
    rec("token sbagliato: 401 -> isError, messaggio del server", out[0]["result"]["isError"] is True and "token non valido" in out[0]["result"]["content"][0]["text"])
    # proxy dal file di configurazione: la richiesta arriva al «proxy» (qui l'API finta) con indirizzo assoluto
    open(alt, "w").write(json.dumps({"url": "http://rmm.interno.test/index.php", "token": TOK, "proxy": f"http://127.0.0.1:{srv.server_address[1]}"}))
    out, lg, _ = run([EXE], {"MYRMM_URL": "", "MYRMM_TOKEN": "", "MYRMM_CONFIG": alt}, [call(1, "myrmm_status")])
    rec("proxy nella configurazione", out[0]["result"]["isError"] is False and lg and lg[0]["abs"] and lg[0]["tok"] == TOK, (out, lg))
    # --version e --check
    v = subprocess.run([EXE, "--version"], capture_output=True, text=True, env=clean)
    import re
    srvf = os.path.join(ROOT, "server", "index.php")   # nel repo pubblico (solo agent e MCP) non c'è il server: vale la versione dell'agent
    app = re.search(r"const APP_VERSION = '([^']+)'", open(srvf, encoding="utf-8").read()).group(1) if os.path.isfile(srvf) else re.search(r'const AgentVersion = "([^"]+)"', open(os.path.join(ROOT, "agent", "main.go"), encoding="utf-8").read()).group(1)
    rec("--version stampa la versione, uguale a quella del server/agent", v.returncode == 0 and v.stdout.strip() == "myrmm-mcp " + app, (v.stdout, app))
    c = subprocess.run([EXE, "--check"], capture_output=True, text=True, env=dict(clean, MYRMM_URL=BASE, MYRMM_TOKEN=TOK))
    rec("--check: collegamento verificato, exit 0, token mai stampato", c.returncode == 0 and "Collegamento verificato" in c.stdout and "ai-test" in c.stdout and TOK not in c.stdout + c.stderr, (c.returncode, c.stdout))
    c2 = subprocess.run([EXE, "--check"], capture_output=True, text=True, env=dict(clean, MYRMM_URL=BASE, MYRMM_TOKEN="myrmm_" + "0" * 48))
    rec("--check con token errato: exit 5", c2.returncode == 5, (c2.returncode, c2.stdout))
    c3 = subprocess.run([EXE, "--check"], capture_output=True, text=True, env=dict(clean, MYRMM_CONFIG=os.path.join(tmp, "x.json")))
    rec("--check senza configurazione: exit 2", c3.returncode == 2, (c3.returncode, c3.stdout))
    try: c.stdout.encode("ascii"); asc = True
    except Exception: asc = False
    rec("--check scrive solo ASCII (la console di Windows non storpia l'esito)", asc, c.stdout)
    big = call(1, "myrmm_run_inline", {"device_id": 3, "body": "x" * 3_000_000})
    out, lg, _ = run([EXE], lines=[big]); rec("riga JSON-RPC molto lunga (3 MB) gestita", out and out[0]["result"]["isError"] is False and len(lg[0]["body"]["body"]) == 3_000_000)
finally:
    srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
f = res.count(False); print(f"\n{len(res) - f}/{len(res)} ok"); sys.exit(1 if f else 0)
