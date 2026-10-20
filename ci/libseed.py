"""Aiuto per le prove: avvia il server PHP su una cartella temporanea, lascia che semini la libreria e restituisce le righe (id, name, description, body, platform, tags, timeout)."""
import json, os, shutil, sqlite3, subprocess, tempfile, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def seeded(port=8797):
    tmp = tempfile.mkdtemp(prefix="myrmm-lib-"); srv = os.path.join(tmp, "server")
    shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data", "update")); os.makedirs(os.path.join(srv, "data"))
    h = subprocess.run(["php", "-r", "echo password_hash('x', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
    cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
    open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
    sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{port}", "-t", srv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    db = os.path.join(srv, "data", "myrmm.sqlite"); rows = []
    try:
        for _ in range(60):
            try: urllib.request.urlopen(f"http://127.0.0.1:{port}/index.php", timeout=2); break
            except Exception as e:
                if getattr(e, "code", 0): break
                time.sleep(.2)
        try: urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/index.php?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{port}"}), timeout=5)
        except Exception: pass
        for _ in range(80):
            try:
                c = sqlite3.connect(db); c.row_factory = sqlite3.Row
                rows = [dict(r) for r in c.execute("SELECT id, name, description, body, platform, tags, timeout FROM scripts ORDER BY id")]
                if rows: break
            except Exception: pass
            time.sleep(.3)
    finally:
        sp.terminate()
    return rows, tmp, db

def php_materialize(items, tmp):
    """items = [(corpo, {VAR: valore}, piattaforma)] → corpi sostituiti come fa il server (materialize())."""
    src = open(os.path.join(ROOT, "server", "index.php"), encoding="utf-8").read()
    a = src.index("class VarUnsafe extends RuntimeException {}"); b = src.index("/**\n * Valuta le schedule scadute")
    open(os.path.join(tmp, "fn.php"), "w", encoding="utf-8").write("<?php\n" + src[a:b])
    open(os.path.join(tmp, "h.php"), "w", encoding="utf-8").write("<?php\nrequire __DIR__ . '/fn.php';\n$in = json_decode(stream_get_contents(STDIN), true);\necho json_encode(array_map(fn($c) => materialize($c[0], $c[1], $c[2] ?? ''), $in), JSON_UNESCAPED_UNICODE);\n")
    r = subprocess.run(["php", os.path.join(tmp, "h.php")], input=json.dumps([[b, v, p] for b, v, p in items]), capture_output=True, text=True, timeout=120)
    if r.returncode: raise SystemExit("php: " + r.stderr[:500])
    return json.loads(r.stdout)
