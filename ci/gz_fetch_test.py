#!/usr/bin/env python3
"""Windows PowerShell 5.1 vero: il frammento dello script di installazione che scarica l'agent compresso (ci/fixtures/install-fetch-gz.ps1) lo decomprime
byte per byte. Server finto locale. Altrove: salta. Uso: python ci/gz_fetch_test.py"""
import gzip, hashlib, http.server, os, subprocess, sys, tempfile, threading
if os.name != "nt": print("Windows richiesto: salto"); sys.exit(0)
HERE = os.path.dirname(os.path.abspath(__file__))
data = os.urandom(300000) + b"MZ" * 200000
z = gzip.compress(data, 9)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length", str(len(z))); self.end_headers(); self.wfile.write(z)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
frag = open(os.path.join(HERE, "fixtures", "install-fetch-gz.ps1"), encoding="utf-8").read().replace("{{URL}}", f"http://127.0.0.1:{srv.server_address[1]}/a")
out = os.path.join(tempfile.mkdtemp(), "agent.exe")
ps = f"$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $tmp='{out}'\n{frag}\n(Get-FileHash $tmp -Algorithm SHA256).Hash"
r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps], capture_output=True, text=True, timeout=240)
good = hashlib.sha256(data).hexdigest().lower() in r.stdout.lower() and not os.path.exists(out + ".gz")
print(("OK   " if good else "FAIL ") + "Windows PowerShell: scarica, decomprime e l'hash coincide e il .gz temporaneo sparisce")
if not good: print((r.stdout + r.stderr)[-600:]); print("::error title=gz_fetch::%s" % (r.stdout + r.stderr)[-300:].replace("\n", "%0A"))
sys.exit(0 if good else 1)
