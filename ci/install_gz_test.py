#!/usr/bin/env python3
"""Download compresso dell'agent nello script di installazione: ?action=install_bin&gz=1 restituisce un gzip il cui contenuto ha l'hash del binario.
Uso: python3 ci/install_gz_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, hashlib, gzip, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8841; BASE = f"http://127.0.0.1:{PORT}/index.php"; TOK = "st-" + "ab" * 16
tmp = tempfile.mkdtemp(prefix="myrmm-gz-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", "echo password_hash('x', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
res = []
def rec(n, ok, d=""): res.append(bool(ok)); print(("OK   " if ok else "FAIL ") + n + ((" [" + str(d)[:200] + "]") if not ok and d else ""), flush=True)
def get(u):
    try:
        r = urllib.request.urlopen(u, timeout=60); return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e: return e.code, b"", e.headers
try:
    for _ in range(50):
        try: urllib.request.urlopen(BASE + "?view=login", timeout=5); break
        except urllib.error.HTTPError: break
        except Exception: time.sleep(.2)
    get(f"{BASE}?action=install_bin&t=st-{'0' * 32}&plat=windows/amd64")   # prima richiesta: crea il database
    c = sqlite3.connect(os.path.join(srv, "data", "myrmm.sqlite")); c.execute("INSERT INTO site_tokens(site,token,enabled,created) VALUES('Acme',?,1,'2026-01-01T00:00:00Z')", (TOK,)); c.commit(); c.close()
    u = f"{BASE}?action=install_bin&t={TOK}&plat=windows/amd64"
    s1, raw, hd = get(u); sha = hd.get("X-Sha256", "")
    rec("install_bin: binario intero con il suo hash", s1 == 200 and hashlib.sha256(raw).hexdigest() == sha and len(raw) > 1000, (s1, len(raw)))
    s2, gz, hd2 = get(u + "&gz=1"); inner = gzip.decompress(gz) if s2 == 200 else b""
    rec("install_bin gz: il contenuto decompresso è identico", s2 == 200 and inner == raw)
    rec("install_bin gz: più piccolo dell'originale", len(gz) < len(raw) * 0.8, (len(gz), len(raw)))
    rec("install_bin gz: Content-Length esatto", int(hd2.get("Content-Length", -1)) == len(gz))
    s3, gz2, _ = get(u + "&gz=1"); rec("install_bin gz: seconda richiesta (da cache) identica", s3 == 200 and gz2 == gz)
    s4, _, _ = get(f"{BASE}?action=install_bin&gz=1&t=st-{'0' * 32}&plat=windows/amd64"); rec("install_bin gz: token errato rifiutato", s4 == 403, s4)
    s5, ps, _ = get(f"{BASE}?action=install&t={TOK}"); t5 = ps.decode(errors="replace")
    rec("script di installazione: scarica la versione compressa e la decomprime", "install_bin&gz=1" in t5 and "GZipStream" in t5 and "Get-FileHash" in t5, s5)
    fx = open(os.path.join(ROOT, "ci", "fixtures", "install-fetch-gz.ps1"), encoding="utf-8").read().replace("{{URL}}", f"{BASE}?action=install_bin&gz=1&t={TOK}&plat=windows/amd64").strip()
    rec("script di installazione: contiene esattamente il frammento provato su Windows (fixture)", fx.replace("\r\n", "\n") in t5.replace("\r\n", "\n"), t5[t5.find("scarico"):][:300])
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(res)}/{len(res)} ok"); sys.exit(0 if all(res) else 1)
