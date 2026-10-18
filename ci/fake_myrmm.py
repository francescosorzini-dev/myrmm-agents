#!/usr/bin/env python3
"""Server myrmm finto per le prove degli script di installazione dell'MCP (solo libreria standard).
Risponde come index.php a: ?action=api&r=mcp&os=&arch=[&info=1] (eseguibile e hash) e ?action=api&r=me (verifica del token).
Modalità (si cambiano mentre gira): ok | badhash (l'hash annunciato non è quello del file) | denied (401 su tutto).
Uso da altre prove: srv = start(exe_path, token); srv.mode = "badhash"; srv.url; srv.stop()"""
import hashlib, http.server, json, threading, urllib.parse


class _H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        s = self.server.state; s.hits.append(self.path)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if s.mode == "denied" or self.headers.get("X-Api-Token") != s.token: return self._json(401, {"error": "token non valido"})
        r = (q.get("r") or [""])[0]
        if r == "me": return self._json(200, {"name": "prova-ci", "role": "admin", "sites": [], "write": 0, "write_label": "sola lettura", "scripts": "all", "expires": "", "version": "ci"})
        if r == "mcp":
            data = open(s.exe, "rb").read(); sha = hashlib.sha256(data).hexdigest()
            if (q.get("info") or [""])[0]:
                return self._json(200, {"os": "windows", "arch": "amd64", "sha256": ("0" * 64 if s.mode == "badhash" else sha), "size": len(data), "version": "ci"})
            self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self._json(404, {"error": "sconosciuto"})


class Fake:
    def __init__(self, exe, token):
        self.exe, self.token, self.mode, self.hits = exe, token, "ok", []
        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H); self._srv.state = self
        self.port = self._srv.server_address[1]; self.url = "http://127.0.0.1:%d/index.php" % self.port
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def stop(self): self._srv.shutdown(); self._srv.server_close()


def start(exe, token): return Fake(exe, token)
