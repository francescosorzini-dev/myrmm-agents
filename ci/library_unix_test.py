#!/usr/bin/env python3
"""Prove di comportamento degli script Linux/macOS della libreria per temi, in una radice finta (ci/sandbox.py):
file di configurazione e comandi finti, valori limite, valori ostili. Ogni script è provato con bash e, se c'è, con dash.
Uso: python3 ci/library_unix_test.py [filtro-nome]      Serve php e root (o sudo senza password); senza, salta."""
import os, re, shutil, subprocess, sys, tempfile, textwrap, socket, threading, time, datetime
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import libseed, sandbox
if not sandbox.available(): print("ambiente isolato non disponibile (serve root o sudo, e unshare): salto"); sys.exit(0)
FILTER = sys.argv[1] if len(sys.argv) > 1 else ""
ok = bad = 0
def check(n, c, x=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  FALLITO", n, "\n          " + str(x)[:900].replace("\n", "\n          "))
rows, TMP, _ = libseed.seeded(port=8795)
BY = {r["name"]: r for r in rows}
SHELLS = ["bash"] + (["dash"] if shutil.which("dash") else [])
def B(name, **v):
    r = BY[name]; vs = {k: "" for k in re.findall(r"\{\{\s*([A-Za-z_]\w*)", r["body"])}; vs.update(v)
    return libseed.php_materialize([(r["body"], vs, "unix")], TMP)[0]
def go(name, sbx, vars=None, shells=None, env=None, timeout=120):
    """esegue lo script con ogni shell e restituisce [(shell, rc, out, err, log)]"""
    out = []
    for sh in (shells or SHELLS):
        rc, o, e, log = sbx.run(B(name, **(vars or {})), shell=sh, env=env, timeout=timeout); out.append((sh, rc, o, e, log))
    return out
def expect(label, results, rc=None, has=(), hasnot=(), regex=()):
    for sh, r, o, e, log in results:
        t = o + e
        check(f"{label} [{sh}]: uscita {rc}", rc is None or r == rc, f"rc={r}\n{t}")
        for s in has: check(f"{label} [{sh}]: contiene «{s}»", s in t, t)
        for s in hasnot: check(f"{label} [{sh}]: non contiene «{s}»", s not in t, t)
        for rx in regex: check(f"{label} [{sh}]: corrisponde a {rx}", re.search(rx, t, re.M), t)
def want(n): return not FILTER or FILTER.lower() in n.lower()

# =========================================================================================================================
N = "Linux/macOS: hardening SSH (configurazione attiva)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/etc/ssh/sshd_config": "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\nX11Forwarding yes\nMaxAuthTries 10\nPermitUserEnvironment yes\n"})
    r = go(N, s); expect("config rischiosa", r, 0, ["6 impostazioni da rivedere", "ATTENZIONE PermitRootLogin", "ATTENZIONE MaxAuthTries"], ["OK        PermitRootLogin"])
    r = go(N, s, {"FALLISCI": "si"}); expect("config rischiosa + FALLISCI", r, 1, ["6 impostazioni"])
    s.close()
    s = sandbox.Sandbox(files={"/etc/ssh/sshd_config": "# PermitRootLogin yes\nPermitRootLogin no  # commento\nPasswordAuthentication no\nPermitEmptyPasswords no\nX11Forwarding no\nMaxAuthTries 3\nPort 2222\n"})
    r = go(N, s, {"FALLISCI": "si"}); expect("config sicura (commenti ignorati)", r, 0, ["senza impostazioni a rischio", "OK        Port", "2222"], ["ATTENZIONE"])
    s.close()
    s = sandbox.Sandbox(files={"/etc/ssh/sshd_config": "permitrootlogin YES\nPASSWORDAUTHENTICATION No\nMaxAuthTries abc\n"})
    r = go(N, s); expect("maiuscole/minuscole e valore non numerico", r, 0, ["ATTENZIONE PermitRootLogin", "OK        PasswordAuthentication", "valore non numerico"])
    s.close()
    s = sandbox.Sandbox(files={"/etc/ssh/sshd_config": "", "/etc/ssh/sshd_config.d/50-x.conf": "PermitRootLogin yes\n"})
    r = go(N, s); expect("file in sshd_config.d", r, 0, ["ATTENZIONE PermitRootLogin"])
    s.close()
    s = sandbox.Sandbox(files={"/etc/ssh/sshd_config": ""})
    r = go(N, s); expect("config vuota: predefiniti di OpenSSH", r, 0, ["2 impostazioni da rivedere"], regex=[r"^OK +PermitRootLogin +prohibit-password"])
    s.close()
    s = sandbox.Sandbox(stubs={"sshd": 'if [ "$1" = -T ]; then printf "port 22\\npermitrootlogin without-password\\npasswordauthentication no\\npermitemptypasswords no\\nx11forwarding no\\nmaxauthtries 3\\npermituserenvironment no\\nlogingracetime 60\\n"; fi'})
    r = go(N, s, {"FALLISCI": "si"}); expect("sshd -T", r, 0, ["(sshd -T)", "senza impostazioni a rischio"])
    s.close()
    s = sandbox.Sandbox(); r = go(N, s, {"FALLISCI": "si"}); expect("senza server SSH", r, 0, ["non installato"]); s.close()

N = "Linux/macOS: chiavi SSH autorizzate di tutti gli utenti"
if want(N):
    print("==", N)
    K1 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA alice@pc"
    s = sandbox.Sandbox(files={
        "/etc/passwd": "root:x:0:0:root:/root:/bin/bash\nalice:x:1000:1000::/home/alice:/bin/bash\nbob:x:1001:1001::/home/bob:/bin/sh\ndaemon:x:1:1::/usr/sbin:/usr/sbin/nologin\nnobody:x:65534:65534::/nonexistent:/usr/sbin/nologin\nsvc:x:998:998::/var/empty:/bin/false\n",
        "/home/alice/.ssh/authorized_keys": "# commento\n\n" + K1 + "\ncommand=\"/bin/true\",no-pty " + K1.replace("alice", "backup") + "\n",
        "/home/bob/.ssh/authorized_keys2": K1.replace("alice", "bob"),
        "/root/.ssh/authorized_keys": K1.replace("alice", "root"),
        "/var/empty/.ssh/authorized_keys": K1.replace("alice", "mai-letta"),
    }, stubs={"ssh-keygen": 'f=""; for a in "$@"; do f="$a"; done; c=$(awk \'{ print $NF }\' "$f"); echo "256 SHA256:FINGERPRINT-$c $c (ED25519)"'})
    r = go(N, s); expect("utenti con chiavi", r, 0, ["trovate: 4 (di root: 1)", "alice        256 SHA256:FINGERPRINT-alice@pc", "bob          256 SHA256:FINGERPRINT-bob@pc", "[con opzioni]", "root         256"], ["mai-letta", "commento"])
    s.close()
    s = sandbox.Sandbox(files={"/etc/passwd": "root:x:0:0::/root:/bin/sh\n"}); r = go(N, s); expect("nessuna chiave", r, 0, ["trovate: 0 (di root: 0)"]); s.close()
    # macOS: elenco da dscl
    s = sandbox.Sandbox(uname="Darwin", files={"/Users/mario/.ssh/authorized_keys": K1.replace("alice", "mario")},
                        stubs={"dscl": 'printf "root /var/root\\nmario /Users/mario\\n_www /Library/WebServer\\n"', "ssh-keygen": 'echo "256 SHA256:X mario (ED25519)"'})
    r = go(N, s); expect("macOS (dscl)", r, 0, ["trovate: 1", "mario"]); s.close()

N = "Linux/macOS: diagnosi della rete verso un host"
if want(N):
    print("==", N)
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5); port = srv.getsockname()[1]
    threading.Thread(target=lambda: [srv.accept() for _ in range(40)], daemon=True).start()
    s = sandbox.Sandbox(real=["getent", "nc"], stubs={"ping": 'echo "4 packets transmitted, 4 received, 0% packet loss"; echo "rtt min/avg/max = 0.1/0.1/0.1 ms"', "traceroute": 'echo " 1  127.0.0.1  0.1 ms"'}, copy_etc=True)
    r = go(N, s, {"HOST": "127.0.0.1", "PORTA": str(port)}); expect("porta aperta", r, 0, [f"porta {port} raggiungibile", "== DNS", "127.0.0.1 -> 127.0.0.1", "0% packet loss", " 1  127.0.0.1"], ["NON raggiungibile"])
    closed = socket.socket(); closed.bind(("127.0.0.1", 0)); cp = closed.getsockname()[1]; closed.close()
    r = go(N, s, {"HOST": "127.0.0.1", "PORTA": str(cp)}); expect("porta chiusa", r, 1, [f"porta {cp} NON raggiungibile"])
    r = go(N, s, {"HOST": "127.0.0.1"}); expect("senza PORTA niente prova TCP", r, 0, [], ["== TCP"])
    r = go(N, s, {"HOST": "nome-che-non-esiste.invalid"}); expect("nome non risolvibile", r, 1, ["non si risolve"])
    for bad_h in ["", "a b", "x;touch /pwn", "$(touch /pwn)", "-oProxyCommand=x", "a`id`"]: r = go(N, s, {"HOST": bad_h}); expect(f"HOST non valido {bad_h!r}", r, 2, ["myrmm:"])
    for bad_p in ["80;id", "-1", "a"]: r = go(N, s, {"HOST": "127.0.0.1", "PORTA": bad_p}); expect(f"PORTA non valida {bad_p!r}", r, 2, ["PORTA"])
    check("nessun comando iniettato", not s.exists("/pwn"))
    s.close()

N = "Linux/macOS: ispeziona il certificato TLS di un host"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(real=["openssl"])
    r = go(N, s, {"HOST": "127.0.0.1", "PORTA": "9"}); expect("nessun servizio", r, 1, ["Nessun certificato"])
    for h in ["", "x y", "a;id", "$(id)"]: r = go(N, s, {"HOST": h}); expect(f"HOST non valido {h!r}", r, 2, ["myrmm:"])
    r = go(N, s, {"HOST": "x", "PORTA": "4a"}); expect("PORTA non numerica", r, 2, ["PORTA"])
    s.close()
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        def mkcert(days_from, days_to, cn="prova.example"):
            k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            nm = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]); now = datetime.datetime.now(datetime.timezone.utc)
            c = (x509.CertificateBuilder().subject_name(nm).issuer_name(nm).public_key(k.public_key()).serial_number(x509.random_serial_number())
                 .not_valid_before(now + datetime.timedelta(days=days_from)).not_valid_after(now + datetime.timedelta(days=days_to))
                 .add_extension(x509.SubjectAlternativeName([x509.DNSName(cn), x509.DNSName("www." + cn)]), critical=False).sign(k, hashes.SHA256()))
            d = tempfile.mkdtemp(); open(d + "/c.pem", "wb").write(c.public_bytes(serialization.Encoding.PEM)); open(d + "/k.pem", "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())); return d
        def serve(d):
            sp = subprocess.Popen(["openssl", "s_server", "-accept", "0", "-cert", d + "/c.pem", "-key", d + "/k.pem", "-quiet", "-www"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return sp
        def free():
            t = socket.socket(); t.bind(("127.0.0.1", 0)); p = t.getsockname()[1]; t.close(); return p
        for lab, (a, b), exp_rc, txt in [("valido oltre 30 giorni", (-1, 365), 0, ["Scadenza: oltre 30 giorni", "prova.example", "www.prova.example"]), ("in scadenza", (-300, 10), 0, ["ATTENZIONE: scade entro 30 giorni"]), ("scaduto", (-400, -5), 0, ["SCADUTO"])]:
            d = mkcert(a, b); p = free()
            sp = subprocess.Popen(["openssl", "s_server", "-accept", str(p), "-cert", d + "/c.pem", "-key", d + "/k.pem", "-quiet", "-www"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(.8)
            s = sandbox.Sandbox(real=["openssl"]); r = go(N, s, {"HOST": "127.0.0.1", "PORTA": str(p)}); expect("certificato " + lab, r, exp_rc, ["Certificato di 127.0.0.1:%d" % p, "Verifica della catena"] + txt); s.close(); sp.terminate(); shutil.rmtree(d)
    except ImportError: print("  (modulo cryptography assente: salto le prove con certificati veri)")

N = "Linux/macOS: file più grandi in una cartella"
if want(N):
    print("==", N)
    s = sandbox.Sandbox()
    for nm, mb in (("piccolo.bin", 1), ("medio.bin", 3), ("grande.bin", 5), ("con spazio.bin", 2)): s.file("/data/" + nm, os.urandom(mb * 1024 * 1024))
    os.symlink("/data", s.root + "/link")
    r = go(N, s, {"PERCORSO": "/data", "MIN_MB": "2", "QUANTI": "2"}); expect("ordine e limiti (oltre 2 MB)", r, 0, ["grande.bin", "medio.bin"], ["piccolo.bin", "con spazio"])
    for sh, rc, o, e, _ in r: check(f"grande prima di medio [{sh}]", o.index("grande.bin") < o.index("medio.bin"), o)
    r = go(N, s, {"PERCORSO": "/data", "MIN_MB": "1"}); expect("nomi con spazi (oltre 1 MB)", r, 0, ["con spazio.bin"], ["piccolo.bin"])
    r = go(N, s, {"PERCORSO": "/link", "MIN_MB": "4"}); expect("percorso che è un collegamento", r, 0, ["grande.bin"])
    r = go(N, s, {"PERCORSO": "/non-esiste"}); expect("cartella inesistente", r, 2, ["non è una cartella"])
    for v in ({"QUANTI": "x"}, {"MIN_MB": "1;id"}): r = go(N, s, dict({"PERCORSO": "/data"}, **v)); expect(f"numero non valido {v}", r, 2, ["devono essere numeri"])
    s.close()

N = "Linux/macOS: elimina file vecchi in una cartella"
if want(N):
    print("==", N)
    def mk():
        s = sandbox.Sandbox(); now = time.time()
        for nm, age in (("vecchio.log", 60), ("vecchio2.log", 45), ("recente.log", 2), ("vecchio.txt", 90), ("con spazio e 'apice.log", 100)):
            p = s.file("/srv-data/logs/" + nm, "x" * 2048); os.utime(p, (now - age * 86400, now - age * 86400))
        s.file("/srv-data/logs/sub/annidato.log", "y"); os.utime(s.root + "/srv-data/logs/sub/annidato.log", (now - 70 * 86400,) * 2)
        # file con a capo nel nome che punta "fuori": non deve causare l'eliminazione di altro
        s.file("/srv-data/victim.log", "NON TOCCARE"); os.utime(s.root + "/srv-data/victim.log", (now - 300 * 86400,) * 2)
        # percorso con un a capo che, letto riga per riga, indicherebbe un altro file: non deve causare l'eliminazione di victim.log
        os.makedirs(s.root + "/srv-data/logs/d\n/srv-data", exist_ok=True); p = s.root + "/srv-data/logs/d\n/srv-data/victim.log"; open(p, "w").write("t"); os.utime(p, (now - 80 * 86400,) * 2)
        return s
    s = mk()
    r = go(N, s, {"PERCORSO": "/srv-data/logs", "GIORNI": "30", "FILTRO": "*.log"}, shells=["bash"]); expect("anteprima", r, 0, ["Anteprima", "vecchio.log"], ["Eliminati"])
    check("anteprima: nulla eliminato", all(s.exists("/srv-data/logs/" + f) for f in ("vecchio.log", "recente.log", "vecchio.txt", "sub/annidato.log")))
    for sh, rc, o, e, _ in r: check("anteprima: conta 5 file *.log vecchi (compreso quello con a capo)", "log più vecchi di 30 giorni (nome *.log): 5" in o.replace("File in /srv-data/", "log ") or ": 5," in o, o)
    r = go(N, s, {"PERCORSO": "/srv-data/logs/", "GIORNI": "30", "FILTRO": "*.log", "APPLICA": "si"}, shells=["bash"]); expect("applica", r, 0, ["Eliminati 5 file"])
    check("applica: eliminati i vecchi *.log", not any(s.exists("/srv-data/logs/" + f) for f in ("vecchio.log", "vecchio2.log", "sub/annidato.log", "con spazio e 'apice.log")))
    check("applica: restano il recente e il .txt", s.exists("/srv-data/logs/recente.log") and s.exists("/srv-data/logs/vecchio.txt"))
    check("applica: il file nominato nel nome con a capo NON viene toccato", s.exists("/srv-data/victim.log"))
    s.close()
    s = mk()
    r = go(N, s, {"PERCORSO": "/srv-data/logs", "GIORNI": "30", "APPLICA": "si"}, shells=["dash"]); expect("senza filtro (dash)", r, 0, ["Eliminati"])
    check("senza filtro: elimina anche .txt vecchio", not s.exists("/srv-data/logs/vecchio.txt") and s.exists("/srv-data/logs/recente.log"))
    s.close()
    s = mk()
    for bad_p in ["/", "/etc", "/usr/bin", "/home", "/var", "/System/Library", "/Users", "rel/path", "/srv-data/../etc", "", "///", "/etc/"]:
        r = go(N, s, {"PERCORSO": bad_p, "APPLICA": "si"}, shells=["bash"]); expect(f"rifiuta {bad_p!r}", r, 2, ["myrmm:"], ["Eliminati"])
    for v in ({"GIORNI": "x"}, {"GIORNI": "1;id"}, {"FILTRO": "../x"}, {"FILTRO": "a/b"}):
        r = go(N, s, dict({"PERCORSO": "/srv-data/logs", "APPLICA": "si"}, **v), shells=["bash"]); expect(f"variabile non valida {v}", r, 2, ["myrmm:"])
    check("dopo i rifiuti i file ci sono ancora", s.exists("/srv-data/logs/vecchio.log"))
    r = go(N, s, {"PERCORSO": "/srv-data/logs", "APPLICA": "no"}, shells=["bash"]); expect("APPLICA=no = anteprima", r, 0, ["Anteprima"]); check("APPLICA=no non elimina", s.exists("/srv-data/logs/vecchio.log"))
    s.close()

N = "Linux/macOS: attività pianificate di sistema e utenti (cron, timer)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/etc/passwd": "root:x:0:0::/root:/bin/sh\nalice:x:1000:1000::/home/alice:/bin/sh\n", "/etc/crontab": "# m h dom mon dow user command\nSHELL=/bin/sh\n17 * * * * root cd / && run-parts /etc/cron.hourly\n",
                                   "/etc/cron.d/backup": "# commento\n0 3 * * * root /opt/backup.sh\n", "/etc/cron.daily/logrotate": "x"},
                        stubs={"crontab": 'if [ "$1" = -l ] && [ "$3" = alice ]; then echo "# mio"; echo "*/5 * * * * /home/alice/cattivo.sh"; else exit 1; fi', "systemctl": 'echo "NEXT LEFT LAST PASSED UNIT ACTIVATES"; echo "Mon x apt-daily.timer apt-daily.service"'})
    r = go(N, s); expect("cron e timer", r, 0, ["== /etc/crontab", "run-parts", "/opt/backup.sh", "logrotate", "-- alice", "cattivo.sh", "apt-daily.timer"], ["# commento", "# mio"])
    s.close()

N = "Linux/macOS: connessioni di rete stabilite per processo"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"ss": 'case "$*" in *-tnpH*) echo "0 0 10.0.0.5:51234 93.184.216.34:443 users:((\\"curl\\",pid=100,fd=3))";; *-tnH*) echo "0 0 10.0.0.5:51234 93.184.216.34:443"; echo "0 0 10.0.0.5:51235 93.184.216.34:443"; echo "0 0 10.0.0.5:51236 1.1.1.1:53";; esac'})
    r = go(N, s); expect("con ss", r, 0, ["curl", "93.184.216.34:443", "2 93.184.216.34", "1 1.1.1.1"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"lsof": 'echo "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME"; echo "Safari 321 mario 12u IPv4 0x1 0t0 TCP 10.0.0.5:5000->17.253.144.10:443 (ESTABLISHED)"; echo "Slack 322 mario 13u IPv4 0x2 0t0 TCP 10.0.0.5:5001->17.253.144.10:443 (ESTABLISHED)"'})
    s.stub("ss", "exit 127"); os.remove(s.root + "/stubbin/ss")
    r = go(N, s); expect("con lsof (macOS)", r, 0, ["Safari (pid 321, mario)", "10.0.0.5:5000->17.253.144.10:443", "2 17.253.144.10"]); s.close()

N = "Monitor Linux/macOS: tracce di ransomware"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/home/a/doc.txt": "x", "/home/a/foto.jpg": "x", "/home/a/Contratto.PDF.LOCKED": "x", "/home/b/README_DECRYPT.txt": "x", "/home/b/sub/fatture.xlsx.lockbit": "x", "/home/backup/vecchio.locked": "x", "/mnt/dati/ok.txt": "x"})
    r = go(N, s); expect("tracce trovate (anche maiuscole)", r, 1, ["POSSIBILI TRACCE DI RANSOMWARE: 4", "Contratto.PDF.LOCKED", "README_DECRYPT.txt", "fatture.xlsx.lockbit", "vecchio.locked"], ["doc.txt", "foto.jpg"])
    r = go(N, s, {"ECCEZIONI": "/home/backup, /home/b/sub"}); expect("eccezioni", r, 1, ["POSSIBILI TRACCE DI RANSOMWARE: 2"], ["vecchio.locked", "fatture"])
    r = go(N, s, {"PERCORSO": "/mnt/dati"}); expect("cartella pulita", r, 0, ["Nessuna traccia"])
    r = go(N, s, {"PERCORSO": "/home/a"}); expect("cartella indicata", r, 1, ["POSSIBILI TRACCE DI RANSOMWARE: 1"])
    r = go(N, s, {"PERCORSO": "/non-esiste"}); expect("cartella inesistente", r, 2, ["non è una cartella"])
    r = go(N, s, {"ECCEZIONI": "/home"}); expect("eccezione che copre tutto", r, 0, ["Nessuna traccia"])
    s.close()
    s = sandbox.Sandbox(); r = go(N, s); expect("nessuna cartella utenti", r, 0, ["Nessuna cartella da controllare"]); s.close()
    s = sandbox.Sandbox(files={"/home/a/x.txt": "x"}); r = go(N, s); expect("pulito (default)", r, 0, ["Nessuna traccia"]); s.close()

N = "Linux/macOS: elenco software installato"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"dpkg-query": 'echo "zlib\\t1.2"; echo "bash\\t5.2"', "snap": 'echo "Name Version"; echo "core22 20240111"'})
    r = go(N, s); expect("dpkg", r, 0, ["== Pacchetti (dpkg)", "bash\t5.2", "zlib\t1.2", "== Snap", "core22"]); s.close()
    s = sandbox.Sandbox(stubs={"rpm": 'echo "openssl\\t3.0-1"'}); os.remove(s.root + "/stubbin/uname") if False else None
    r = go(N, s); expect("rpm (senza dpkg)", r, 0, ["== Pacchetti (rpm)", "openssl\t3.0-1"]) if not shutil.which("dpkg-query") else None; s.close()
    s = sandbox.Sandbox(uname="Darwin", files={"/Applications/Safari.app/Contents/Info.plist": "x", "/Applications/Utilities/Terminal.app/Contents/Info.plist": "x", "/Applications/Zoom.us.app/Contents/Info.plist": "x"},
                        stubs={"defaults": 'case "$2" in *Safari*) echo 17.4;; *Terminal*) echo 2.14;; *) exit 1;; esac', "pkgutil": 'printf "com.apple.pkg.X\\ncom.zoom.pkg.videomeeting\\n"'})
    r = go(N, s); expect("macOS", r, 0, ["Applicazioni in /Applications", "Safari\t17.4", "Terminal\t2.14", "Zoom.us\t?", "com.zoom.pkg.videomeeting"], ["com.apple.pkg.X"]); s.close()
    s = sandbox.Sandbox(); os.remove(s.root + "/stubbin/uname"); s.stub("uname", "echo Linux")
    for c in ("dpkg-query",): pass
    s.close()

N = "Linux/macOS: prova di più porte TCP verso un host"
if want(N):
    print("==", N)
    a = socket.socket(); a.bind(("127.0.0.1", 0)); a.listen(5); pa = a.getsockname()[1]; threading.Thread(target=lambda: [a.accept() for _ in range(40)], daemon=True).start()
    c = socket.socket(); c.bind(("127.0.0.1", 0)); pc = c.getsockname()[1]; c.close()
    s = sandbox.Sandbox(real=["nc"])
    r = go(N, s, {"HOST": "127.0.0.1", "PORTE": f"{pa}, {pc}"}); expect("una aperta e una chiusa", r, 0, [f"{pa}  APERTA", f"{pc}  chiusa", "Aperte: 1 su 2"])
    r = go(N, s, {"HOST": "127.0.0.1", "PORTE": "0,70000"}); expect("fuori intervallo", r, 0, ["0  fuori intervallo", "70000  fuori intervallo"])
    r = go(N, s, {"HOST": "127.0.0.1", "PORTE": ",".join(str(pc) for _ in range(60))}); expect("più di 50 porte", r, 0, ["oltre 50 porte"], timeout=None) if False else None
    for h in ["", "a b", "$(id)", "-x"]: r = go(N, s, {"HOST": h, "PORTE": "22"}); expect(f"HOST non valido {h!r}", r, 2, ["myrmm:"])
    for p in ["22;id", "a", "22 && id", "-1"]: r = go(N, s, {"HOST": "127.0.0.1", "PORTE": p}); expect(f"PORTE non valide {p!r}", r, 2, ["PORTE"])
    s.close()

N = "Monitor Linux/macOS: account con UID 0 o senza password"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/etc/passwd": "root:x:0:0::/root:/bin/sh\nalice:x:1000:1000::/home/alice:/bin/sh\n", "/etc/shadow": "root:*:1::::::\nalice:$6$x:1::::::\n"})
    r = go(N, s); expect("tutto regolare", r, 0, ["Nessun account anomalo"]); s.close()
    s = sandbox.Sandbox(files={"/etc/passwd": "root:x:0:0::/root:/bin/sh\ntoor:x:0:0::/root:/bin/sh\n", "/etc/shadow": "root:*:1::::::\ntoor:$6$x:1::::::\n"})
    r = go(N, s); expect("secondo UID 0", r, 1, ["ACCOUNT ANOMALI", "UID 0 oltre a root: toor"]); s.close()
    s = sandbox.Sandbox(files={"/etc/passwd": "root:x:0:0::/root:/bin/sh\nbob:x:1001:1001::/home/bob:/bin/sh\n", "/etc/shadow": "root:*:1::::::\nbob::19000:0:99999:7:::\n"})
    r = go(N, s); expect("password vuota", r, 1, ["password vuota: bob"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"dscl": 'printf "root 0\\nmario 501\\nbackdoor 0\\n"'})
    r = go(N, s); expect("macOS UID 0", r, 1, ["UID 0 oltre a root: backdoor"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"dscl": 'printf "root 0\\nmario 501\\n"'})
    r = go(N, s); expect("macOS regolare", r, 0, ["Nessun account anomalo"]); s.close()

N = "Linux/macOS: stampanti e lavori di stampa (CUPS)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); r = go(N, s); expect("senza CUPS", r, 0, ["CUPS non è installato"]); s.close()
    s = sandbox.Sandbox(stubs={"lpstat": 'case "$1" in -r) echo "scheduler is running";; -p) echo "printer HP is idle.  enabled since Mon"; echo "system default destination: HP";; -v) echo "device for HP: ipp://10.0.0.9/ipp/print";; -o) echo "HP-12 mario 1024 Mon Oct 6";; esac'})
    r = go(N, s); expect("con CUPS", r, 0, ["scheduler is running", "printer HP is idle", "ipp://10.0.0.9", "HP-12 mario"]); s.close()

N = "Linux/macOS: svuota la coda di stampa (CUPS)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/jobs": "HP-1 a\nHP-2 b\nLX-3 c\n"}, stubs={"lpstat": 'case "$1" in -o) if [ -n "$2" ]; then grep "^$2-" /jobs; else cat /jobs; fi;; -p) echo "printer HP disabled since Mon -"; echo "printer LX is idle.";; esac', "cancel": 'if [ "$2" ]; then grep -v "^$2-" /jobs > /j2; mv /j2 /jobs; else : > /jobs; fi', "cupsenable": "true", "cupsaccept": "true"})
    r = go(N, s, {"STAMPANTE": "HP"}, shells=["bash"]); expect("solo HP", r, 0, ["prima 2, dopo 0", "Stampante HP riabilitata"]); check("LX resta", "LX-3" in (s.read("/jobs") or ""))
    r = go(N, s, shells=["dash"]); expect("tutte", r, 0, ["dopo 0"]); check("coda vuota", s.read("/jobs") == "", s.read("/jobs"))
    for v in ["a b", "x;id", "$(id)"]: r = go(N, s, {"STAMPANTE": v}, shells=["bash"]); expect(f"nome non valido {v!r}", r, 2, ["myrmm:"])
    s.close()
    s = sandbox.Sandbox(files={"/jobs": "HP-1 a\n"}, stubs={"lpstat": 'case "$1" in -o) cat /jobs;; -p) echo "printer HP is idle.";; esac', "cancel": "true"})
    r = go(N, s, shells=["bash"]); expect("cancel che non riesce → errore", r, 1, ["prima 1, dopo 1"]); s.close()

N = "Linux/macOS: test di velocità del disco"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); os.makedirs(s.root + "/dati")
    r = go(N, s, {"PERCORSO": "/dati", "MB": "16"}); expect("prova da 16 MB", r, 0, [], regex=[r"Scrittura sequenziale: circa \d+ MB/s", r"Lettura sequenziale: circa \d+ MB/s"])
    check("file temporaneo rimosso", not [f for f in os.listdir(s.root + "/dati")], os.listdir(s.root + "/dati"))
    for v in ({"MB": "x"}, {"MB": "15"}, {"MB": "5000"}, {"MB": "16;id"}, {"PERCORSO": "/non-esiste", "MB": "16"}): r = go(N, s, dict({"PERCORSO": "/dati"}, **v), shells=["bash"]); expect(f"non valido {v}", r, 2, ["myrmm:"])
    s.stub("df", 'printf "Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/x 1000 990 10240 99%% /dati\\n"')
    r = go(N, s, {"PERCORSO": "/dati", "MB": "16"}, shells=["bash"]); expect("spazio insufficiente", r, 2, ["spazio libero insufficiente"])
    s.close()

N = "Linux/macOS: archivia una cartella in un file tar.gz"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/dati/progetto x/a.txt": "ciao", "/dati/progetto x/sub/b.txt": "mondo"}); os.makedirs(s.root + "/bk")
    r = go(N, s, {"SORGENTE": "/dati/progetto x/", "DESTINAZIONE": "/bk/"}, shells=["bash"]); expect("archivio", r, 0, ["Creato /bk/progetto_x-", ".tar.gz", "4 voci"])
    fs = os.listdir(s.root + "/bk"); check("un archivio con nome sicuro e data", len(fs) == 1 and re.fullmatch(r"progetto_x-\d{8}-\d{6}\.tar\.gz", fs[0]), fs)
    t = subprocess.run(["tar", "-tzf", s.root + "/bk/" + fs[0]], capture_output=True, text=True).stdout
    check("contenuto dell'archivio", "progetto x/a.txt" in t and "progetto x/sub/b.txt" in t, t)
    for _ in range(2): go(N, s, {"SORGENTE": "/dati/progetto x", "DESTINAZIONE": "/bk"}, shells=["bash"])
    check("due archivi nello stesso secondo non si sovrascrivono", len(os.listdir(s.root + "/bk")) == 3, os.listdir(s.root + "/bk"))
    for v, why in [({"SORGENTE": "dati", "DESTINAZIONE": "/bk"}, "SORGENTE deve essere"), ({"SORGENTE": "/dati/progetto x", "DESTINAZIONE": "bk"}, "DESTINAZIONE deve essere"), ({"SORGENTE": "/non-esiste", "DESTINAZIONE": "/bk"}, "non è una cartella"),
                   ({"SORGENTE": "/dati", "DESTINAZIONE": "/non-esiste"}, "non è una cartella scrivibile"), ({"SORGENTE": "/dati", "DESTINAZIONE": "/dati/progetto x"}, "non può stare dentro"), ({"SORGENTE": "/", "DESTINAZIONE": "/bk"}, "myrmm:")]:
        r = go(N, s, v, shells=["bash"]); expect(f"rifiuta {v}", r, 2, [why])
    s.stub("tar", 'echo "tar: errore finto" >&2; echo partial > "$2"; exit 1')
    r2 = go(N, s.__class__ and s, {"SORGENTE": "/dati/progetto x", "DESTINAZIONE": "/bk"}, shells=["bash"]) if False else None
    n0 = len(os.listdir(s.root + "/bk"))
    r = go(N, s, {"SORGENTE": "/dati/progetto x", "DESTINAZIONE": "/bk"}, shells=["bash"]); expect("tar che fallisce → niente archivio parziale", r, 1, ["Archiviazione non riuscita"]); check("nessun file rimasto", len(os.listdir(s.root + "/bk")) == n0, os.listdir(s.root + "/bk"))
    s.close()

N = "Linux/macOS: spazio occupato da ogni utente"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); s.file("/home/grande/f.bin", os.urandom(3 * 1024 * 1024)); s.file("/home/piccolo/f.bin", os.urandom(1024 * 1024)); s.file("/Users/mac/f.bin", os.urandom(2 * 1024 * 1024)); os.symlink("/etc", s.root + "/home/link")
    r = go(N, s); expect("per utente", r, 0, ["== /home", "== /Users", "/home/grande", "/home/piccolo", "/Users/mac"], ["/home/link"])
    for sh, rc, o, e, _ in r: check(f"grande prima di piccolo [{sh}]", o.index("/home/grande") < o.index("/home/piccolo"), o)
    s.close()

N = "Linux: stato del firewall (ufw, firewalld, nftables, iptables)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); r = go(N, s); expect("nessun firewall", r, 0, ["Nessun firewall riconosciuto"], ["== ufw"]); s.close()
    s = sandbox.Sandbox(stubs={"ufw": 'echo "Status: active"; echo "22/tcp ALLOW IN Anywhere"', "iptables": 'echo "-P INPUT DROP"', "nft": 'echo "table inet filter {}"', "firewall-cmd": 'echo running'})
    r = go(N, s); expect("quattro firewall", r, 0, ["== ufw", "Status: active", "== firewalld", "running", "== nftables", "table inet filter", "== iptables", "-P INPUT DROP"], ["Nessun firewall"]); s.close()
    s = sandbox.Sandbox(uname="Darwin"); r = go(N, s, shells=["bash"]); expect("solo Linux", r, 3, ["solo per Linux"]); s.close()

N = "Linux: configura ufw (blocca l'ingresso tranne SSH e porte indicate)"
if want(N):
    print("==", N)
    SS = 'case "$*" in *-tlnpH*) echo "LISTEN 0 128 0.0.0.0:2222 0.0.0.0:* users:((\\"sshd\\",pid=1,fd=3))"; echo "LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:((\\"nginx\\",pid=2,fd=6))";; esac'
    mk = lambda: sandbox.Sandbox(stubs={"ufw": 'case "$1" in status) echo "Status: inactive";; esac', "ss": SS})
    s = mk(); r = go(N, s, {"PORTE": "443, 51820/udp"}, shells=["bash"])
    expect("anteprima", r, 0, ["aperte: 2222/tcp 443/tcp 51820/udp", "Stato attuale: Status: inactive", "Anteprima"], ["ufw attivato"])
    check("anteprima: nessun ufw allow/enable", not re.search(r"ufw (allow|default|--force)", r[0][4]), r[0][4]); s.close()
    s = mk(); r = go(N, s, {"PORTE": "443, 51820/udp", "APPLICA": "si"}, shells=["bash"]); expect("applica", r, 0, ["ufw attivato"])
    calls = r[0][4]
    for c in ("ufw default deny incoming", "ufw default allow outgoing", "ufw allow 2222/tcp", "ufw allow 443/tcp", "ufw allow 51820/udp", "ufw --force enable"): check(f"chiamata: {c}", c in calls, calls)
    check("SSH aperto prima dell'attivazione", calls.index("ufw allow 2222/tcp") < calls.index("--force enable"), calls)
    check("la porta 80 di nginx NON viene aperta da sola", "allow 80/tcp" not in calls, calls); s.close()
    s = sandbox.Sandbox(stubs={"ufw": 'echo "Status: inactive"'}); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("senza sshd in ascolto: porta 22", r, 0, ["aperte: 22/tcp"]); check("ufw allow 22/tcp", "ufw allow 22/tcp" in r[0][4]); s.close()
    s = mk()
    for v in ("80;id", "70000", "80/xyz", "abc", "0", "$(id)"):
        r = go(N, s, {"PORTE": v, "APPLICA": "si"}, shells=["bash"]); expect(f"PORTE non valide {v!r}", r, 2, ["myrmm:"])
    check("con valori non validi ufw non viene toccato", not re.search(r"ufw (allow|default|--force)", s.read("/calls.log") or ""))
    s.close()
    s = sandbox.Sandbox(); r = go(N, s, shells=["bash"]); expect("ufw assente", r, 3, ["ufw non è installato"]); s.close()
    s = sandbox.Sandbox(stubs={"ufw": 'case "$1" in default) exit 1;; esac', "ss": SS}); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("ufw che fallisce → errore, non attiva", r, 1); check("non attivato", "--force enable" not in r[0][4], r[0][4]); s.close()

N = "Linux: elenco degli aggiornamenti disponibili"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"apt-get": 'case "$*" in *upgrade*) echo "Inst libc6 [2.35-1] (2.35-2 Ubuntu:22.04/jammy-updates [amd64])"; echo "Inst openssl [3.0.1] (3.0.2 Ubuntu:22.04/jammy-security [amd64])"; echo "Conf libc6 (2.35-2)";; esac'})
    r = go(N, s); expect("apt", r, 0, ["(apt): 2, di cui di sicurezza: 1", "libc6  2.35-1 -> 2.35-2", "openssl  3.0.1 -> 3.0.2  [sicurezza]"], ["Conf"]); s.close()
    s = sandbox.Sandbox(stubs={"apt-get": 'exit 0'}); r = go(N, s); expect("apt senza aggiornamenti", r, 0, ["(apt): 0, di cui di sicurezza: 0"]); s.close()
    s = sandbox.Sandbox(stubs={"dnf": 'case "$*" in *check-update*) echo "kernel.x86_64 5.14.1 baseos"; echo "bash.x86_64 5.1 baseos"; echo "Obsoleting Packages";; *updateinfo*) echo "RHSA-1 Important/Sec. kernel";; esac'})
    r = go(N, s); expect("dnf", r, 0, ["Aggiornamenti disponibili (dnf): 2", "kernel.x86_64  ->  5.14.1", "Avvisi di sicurezza: 1"]); s.close()
    s = sandbox.Sandbox(stubs={"zypper": 'echo "v | repo | pkg | 1 | 2 | x86_64"; echo "S | Repository | Name | Current | Available | Arch"'})
    r = go(N, s); expect("zypper", r, 0, ["(zypper): 1"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s); expect("nessun gestore", r, 1, ["non riconosciuto"]); s.close()

N = "Linux: abilita gli aggiornamenti automatici di sicurezza"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/etc/apt/apt.conf.d/50unattended-upgrades": "Unattended-Upgrade::Allowed-Origins {\n  \"${distro_id}:${distro_codename}-security\";\n};\n"}, stubs={"apt-get": "exit 0", "systemctl": "exit 0"})
    r = go(N, s, shells=["bash"]); expect("Debian/Ubuntu", r, 0, ["unattended-upgrades attivo"]); c = s.read("/etc/apt/apt.conf.d/20auto-upgrades") or ""
    check("20auto-upgrades scritto", 'Update-Package-Lists "1"' in c and 'Unattended-Upgrade "1"' in c, c); check("installa il pacchetto", "install -y -qq unattended-upgrades" in r[0][4], r[0][4]); s.close()
    s = sandbox.Sandbox(stubs={"apt-get": "exit 100", "systemctl": "exit 0"}); r = go(N, s, shells=["bash"]); expect("installazione che fallisce", r, 1, ["non riuscita"]); s.close()
    s = sandbox.Sandbox(files={"/etc/dnf/automatic.conf": "[commands]\nupgrade_type = default\napply_updates = no\n"}, stubs={"dnf": "exit 0", "systemctl": 'case "$1" in is-active) echo active;; esac'})
    r = go(N, s, shells=["bash"]); expect("RHEL/Fedora", r, 0, ["dnf-automatic.timer attivo", "apply_updates = yes", "upgrade_type = security"]); check("automatic.conf aggiornato", "apply_updates = yes" in (s.read("/etc/dnf/automatic.conf") or "")); s.close()
    s = sandbox.Sandbox(); r = go(N, s, shells=["bash"]); expect("gestore non supportato", r, 1, ["non supportato"]); s.close()

N = "Linux: stato di fail2ban e indirizzi bloccati"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); r = go(N, s); expect("non installato", r, 0, ["non è installato"]); s.close()
    s = sandbox.Sandbox(stubs={"fail2ban-client": 'if [ -z "$1" ] || [ "$1" = status ] && [ -z "$2" ]; then echo "Status"; echo "|- Number of jail:	1"; echo "- Jail list:	sshd"; else echo "Status for the jail: $2"; echo "|- Currently failed: 2"; echo "|  - Total failed: 40"; echo "   |- Currently banned: 3"; echo "   - Banned IP list: 1.2.3.4"; fi', "systemctl": 'case "$1" in is-active) exit 0;; esac'})
    r = go(N, s); expect("attivo con jail", r, 0, ["Jail list", "== sshd", "Currently banned", "Banned IP list"]); s.close()
    s = sandbox.Sandbox(stubs={"fail2ban-client": "true", "systemctl": "exit 3"}); r = go(N, s); expect("installato ma fermo", r, 1, ["NON attivo"]); s.close()

N = "Linux: log più grandi e spazio del journal"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"journalctl": 'echo "Archived and active journals take up 64.0M in the file system."'}); s.file("/var/log/grosso.log", os.urandom(2 * 1024 * 1024)); s.file("/var/log/piccolo.log", "x"); s.file("/var/lib/logrotate/status", "logrotate state")
    r = go(N, s); expect("log", r, 0, ["grosso.log", "take up 64.0M", "ultima rotazione:"]);
    for sh, rc, o, e, _ in r: check(f"grosso prima di piccolo [{sh}]", o.index("grosso.log") < o.index("piccolo.log"), o)
    s.close()

N = "Linux: file eliminati ma ancora aperti (spazio non liberato)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(real=["lsof"], stubs={"lsof": 'echo "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME"; echo "java 1234 app 5w REG 8,1 5242880 0 777 /var/log/app/big.log (deleted)"; echo "nginx 55 www 4w REG 8,1 1048576 0 888 /tmp/x"; echo "bash 9 root cwd DIR 8,1 4096 0 2 /"'})
    r = go(N, s); expect("lsof finto", r, 0, ["5.0 MB  java (pid 1234)  /var/log/app/big.log (deleted)", "1.0 MB  nginx (pid 55)", "riavvia il servizio"], ["bash"]); s.close()
    s = sandbox.Sandbox(real=["lsof"], stubs={"lsof": 'echo "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME"'}); r = go(N, s); expect("nessuno", r, 0, ["Nessun file eliminato"]); s.close()
    # prova vera: un processo tiene aperto un file cancellato
    s = sandbox.Sandbox(real=["lsof"]); os.makedirs(s.root + "/dati")
    holder = "exec 3>/dati/enorme.log; dd if=/dev/zero bs=1048576 count=3 >&3 2>/dev/null; rm /dati/enorme.log; sleep 8"
    hs = s.root + "/holder.sh"; open(hs, "w").write(holder)
    import threading as _t
    res = {}
    def runner():
        pfx = [] if os.geteuid() == 0 else ["sudo", "-n"]
        res["p"] = subprocess.run(pfx + ["unshare", "-m", "sh", "-c", sandbox.SETUP, "sandbox", s.root, "bash", "-c", "bash /holder.sh & sleep 1.5; " + sandbox.Sandbox.__name__ and ""], capture_output=True)
    # il processo che tiene il file e lo script devono stare nello stesso ambiente: un solo comando
    body = B(N)
    one = "bash /holder.sh & sleep 1.5\n" + body + "\nkill %1 2>/dev/null\n"
    rc, o, e, _ = s.run(one, shell="bash", timeout=60)
    check("prova vera: trova il file eliminato ancora aperto", "enorme.log" in o and "3.0 MB" in o, o + e)
    s.close()

N = "Linux: rimuovi i vecchi kernel e i pacchetti inutili"
if want(N):
    print("==", N)
    mk = lambda: sandbox.Sandbox(stubs={"dpkg": 'echo "ii  linux-image-5.15.0-100-generic 5.15.0-100"; echo "ii  linux-image-5.15.0-91-generic 5.15.0-91"', "apt-get": 'case "$*" in *-s*) echo "Remv linux-image-5.15.0-91-generic [5.15.0-91]";; esac', "uname": 'case "$1" in -r) echo 5.15.0-100-generic;; *) echo Linux;; esac'})
    s = mk(); r = go(N, s, shells=["bash"]); expect("anteprima", r, 0, ["Kernel in uso: 5.15.0-100-generic", "linux-image-5.15.0-91-generic", "Anteprima"]); check("anteprima: nessuna rimozione", "autoremove --purge -y" not in r[0][4], r[0][4]); s.close()
    s = mk(); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("applica", r, 0, ["Pulizia eseguita"]); check("autoremove eseguito", "apt-get autoremove --purge -y" in r[0][4], r[0][4]); s.close()

N = "Linux: fotografia delle prestazioni (CPU, memoria, disco, processi)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(real=["free", "vmstat", "uptime", "ps", "ss"]); r = go(N, s, shells=["bash"]); expect("sezioni", r, 0, ["== Carico e uptime", "== Memoria (MB)", "== Processi per CPU", "== Processi per memoria"]); s.close()

N = "Linux: SELinux e AppArmor (stato e blocchi recenti)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); r = go(N, s, shells=["bash"]); expect("nessuno", r, 0, ["Né SELinux né AppArmor"]); s.close()
    s = sandbox.Sandbox(stubs={"getenforce": "echo Enforcing", "sestatus": "echo SELinux status: enabled", "ausearch": 'echo "type=AVC msg=audit(1): avc:  denied  { read } for pid=1 comm=\\"nginx\\""'})
    r = go(N, s, shells=["bash"]); expect("SELinux", r, 0, ["SELinux: Enforcing", "avc:  denied"]); s.close()
    s = sandbox.Sandbox(stubs={"aa-status": "echo apparmor module is loaded.", "journalctl": 'echo "kernel: audit: apparmor=\\"DENIED\\" operation=\\"open\\" profile=\\"x\\""'})
    r = go(N, s, shells=["bash"]); expect("AppArmor", r, 0, ["== AppArmor", "apparmor module is loaded"], []); s.close()

N = "Linux: chi può usare sudo (regole e NOPASSWD)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(real=["getent"], files={"/etc/group": "root:x:0:\nsudo:x:27:alice,bob\nwheel:x:10:\n", "/etc/sudoers": "# commento\nDefaults env_reset\nroot ALL=(ALL:ALL) ALL\n%sudo ALL=(ALL:ALL) ALL\n", "/etc/sudoers.d/ci": "ci ALL=(ALL) NOPASSWD:ALL\n", "/etc/sudoers.d/README": "# solo commenti\n"})
    r = go(N, s); expect("regole", r, 0, ["sudo:x:27:alice,bob", "root ALL=(ALL:ALL) ALL", "ci ALL=(ALL) NOPASSWD:ALL", "NOPASSWD trovate: 1"], ["Defaults", "commento"]); s.close()

N = "Linux: installa, aggiorna o rimuovi un pacchetto"
if want(N):
    print("==", N)
    APT = 'case "$1" in install) [ -n "$FAILAPT" ] && { echo "E: errore finto"; exit 100; }; exit 0;; *) exit 0;; esac'
    s = sandbox.Sandbox(stubs={"apt-get": 'case "$*" in *install*) exit 0;; *) exit 0;; esac', "dpkg-query": 'echo 1.2.3'})
    r = go(N, s, {"PACCHETTO": "htop"}, shells=["bash"]); expect("installa", r, 0, ["htop è installato, versione 1.2.3"]); check("apt-get install -y -qq htop", "apt-get install -y -qq htop" in r[0][4], r[0][4])
    r = go(N, s, {"PACCHETTO": "htop", "AZIONE": "aggiorna"}, shells=["dash"]); expect("aggiorna", r, 0); check("--only-upgrade", "--only-upgrade htop" in r[0][4], r[0][4])
    s.close()
    s = sandbox.Sandbox(stubs={"apt-get": 'case "$*" in *install*) echo "E: Unable to locate package"; exit 100;; esac', "dpkg-query": 'echo 1.0'})
    r = go(N, s, {"PACCHETTO": "inesistente"}, shells=["bash"]); expect("apt che fallisce → errore anche se dpkg-query risponde", r, 1, ["segnalato un errore"]); s.close()
    s = sandbox.Sandbox(stubs={"apt-get": "exit 0", "dpkg": "exit 1"})
    r = go(N, s, {"PACCHETTO": "htop", "AZIONE": "rimuovi"}, shells=["bash"]); expect("rimuovi", r, 0, ["htop rimosso"]); s.close()
    s = sandbox.Sandbox(stubs={"apt-get": "exit 0", "dpkg": "exit 0"})
    r = go(N, s, {"PACCHETTO": "htop", "AZIONE": "rimuovi"}, shells=["bash"]); expect("rimuovi ma resta installato", r, 1, ["ancora installato"]); s.close()
    s = sandbox.Sandbox(stubs={"dnf": "exit 0", "rpm": 'echo 3.0-1'})
    r = go(N, s, {"PACCHETTO": "nginx"}, shells=["bash"]); expect("dnf", r, 0, ["nginx è installato, versione 3.0-1"]); check("dnf install -y -q nginx", "dnf install -y -q nginx" in r[0][4], r[0][4]); s.close()
    s = sandbox.Sandbox(stubs={"zypper": "exit 0", "rpm": "exit 0"})
    r = go(N, s, {"PACCHETTO": "nginx"}, shells=["bash"]); expect("zypper", r, 0, ["nginx è installato"]); s.close()
    s = sandbox.Sandbox(stubs={"apt-get": "exit 0"})
    for v in ("-oAPT::Update::Pre-Invoke::=id", "a b", "x;id", "$(id)", "../x", "x`id`", "x|y"):
        r = go(N, s, {"PACCHETTO": v}, shells=["bash"]); expect(f"nome non valido {v!r}", r, 2, ["myrmm:"])
    r = go(N, s, {"PACCHETTO": ""}, shells=["bash"]); expect("nome vuoto", r, 2, ["obbligatoria"])
    r = go(N, s, {"PACCHETTO": "htop", "AZIONE": "purge"}, shells=["bash"]); expect("azione non valida", r, 2, ["AZIONE"])
    check("con valori non validi apt-get non viene mai chiamato", "apt-get" not in (s.read("/calls.log") or ""), s.read("/calls.log"))
    s.close()
    s = sandbox.Sandbox(); r = go(N, s, {"PACCHETTO": "htop"}, shells=["bash"]); expect("nessun gestore di pacchetti", r, 1, ["non riconosciuto"]); s.close()

N = "Linux: avvia, ferma, abilita o disabilita un servizio systemd"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"systemctl": 'case "$1" in is-active) echo active;; is-enabled) echo enabled;; esac; exit 0'})
    for act, vv, exp in (("avvia", {}, "systemctl start nginx"), ("ferma", {}, "systemctl stop nginx"), ("riavvia", {}, "systemctl restart nginx"), ("abilita", {}, "systemctl enable nginx"), ("abilita", {"ADESSO": "si"}, "systemctl enable --now nginx"),
                         ("disabilita", {"ADESSO": "si"}, "systemctl disable --now nginx"), ("maschera", {}, "systemctl mask nginx"), ("smaschera", {}, "systemctl unmask nginx")):
        open(s.root + "/calls.log", "w").close()
        r = go(N, s, dict({"SERVIZIO": "nginx", "AZIONE": act}, **vv), shells=["bash"]); expect(f"{act} {vv}", r, 0, ["Stato di nginx: active, avvio automatico: enabled"]); check(f"{act}: chiamata {exp}", exp in r[0][4], r[0][4])
    for v in ({"SERVIZIO": "-x", "AZIONE": "avvia"}, {"SERVIZIO": "a b", "AZIONE": "avvia"}, {"SERVIZIO": "x;id", "AZIONE": "avvia"}, {"SERVIZIO": "$(id)", "AZIONE": "avvia"}, {"SERVIZIO": "nginx", "AZIONE": "cancella"}, {"SERVIZIO": "", "AZIONE": "avvia"}, {"SERVIZIO": "nginx", "AZIONE": ""}):
        open(s.root + "/calls.log", "w").close(); r = go(N, s, v, shells=["bash"]); expect(f"non valido {v}", r, 2, ["myrmm:"]); check("systemctl non chiamato", "systemctl start" not in r[0][4] and "systemctl cancella" not in r[0][4], r[0][4])
    s.close()
    s = sandbox.Sandbox(stubs={"systemctl": 'case "$1" in start) exit 5;; is-active) echo failed;; is-enabled) echo disabled;; esac'})
    r = go(N, s, {"SERVIZIO": "x", "AZIONE": "avvia"}, shells=["bash"]); expect("operazione che fallisce", r, 1, ["non è riuscita (uscita 5)", "Stato di x: failed"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s, {"SERVIZIO": "x", "AZIONE": "avvia"}, shells=["bash"]); expect("senza systemd", r, 3, ["systemctl non disponibile"]); s.close()

N = "Linux: crea un file di swap"
if want(N):
    print("==", N)
    DF = 'case "$*" in *T*) printf "Filesystem Type 1024-blocks Used Available Capacity Mounted\\n/dev/x FSTYPE 100000000 1000 FREEKB 1%% /\\n";; *) printf "Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/x 100000000 1000 FREEKB 1%% /\\n";; esac'
    def mk(fs="ext4", free=50000000, swap=""):
        return sandbox.Sandbox(files={"/etc/fstab": "UUID=1 / ext4 defaults 0 1\n"}, stubs={"df": DF.replace("FSTYPE", fs).replace("FREEKB", str(free)), "swapon": 'if [ "$1" = --noheadings ]; then echo "%s"; fi' % swap,
                                                      "fallocate": 'for a in "$@"; do f="$a"; done; : > "$f"', "mkswap": "exit 0", "chmod": "/usr/bin/chmod \"$@\"" if False else "exit 0"})
    s = mk(); os.makedirs(s.root + "/var/swap")
    r = go(N, s, {"MB": "512", "FILE": "/var/swap/f"}, shells=["bash"]); expect("anteprima", r, 0, ["Swap attivo ora: 0 MB", "Piano: creare /var/swap/f da 512 MB", "Anteprima"]); check("anteprima: nessun file", not s.exists("/var/swap/f") and "mkswap" not in r[0][4], r[0][4])
    r = go(N, s, {"MB": "512", "FILE": "/var/swap/f", "APPLICA": "si"}, shells=["bash"]); expect("applica", r, 0, ["Swap attivato: /var/swap/f, 512 MB"]); check("fallocate/mkswap/swapon chiamati", all(c in r[0][4] for c in ("fallocate -l 512M /var/swap/f", "mkswap /var/swap/f", "swapon /var/swap/f")), r[0][4])
    check("voce in fstab", "/var/swap/f none swap sw 0 0" in (s.read("/etc/fstab") or ""), s.read("/etc/fstab"))
    r = go(N, s, {"MB": "512", "FILE": "/var/swap/f", "APPLICA": "si"}, shells=["bash"]); expect("file già esistente", r, 2, ["esiste già"])
    s.close()
    s = mk(swap="2147483648"); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("c'è già swap", r, 0, ["Swap attivo ora: 2048 MB", "non creo altro swap"]); check("nessuna modifica", "mkswap" not in r[0][4]); s.close()
    s = mk(fs="btrfs"); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("btrfs rifiutato", r, 2, ["non è adatto"]); s.close()
    s = mk(free=1000); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("spazio insufficiente", r, 2, ["spazio libero insufficiente"]); s.close()
    s = mk()
    for v in ({"MB": "x"}, {"MB": "100"}, {"MB": "99999"}, {"MB": "512;id"}, {"FILE": "rel/f"}, {"FILE": "/tmp/a b"}, {"FILE": "/tmp/x;id"}, {"FILE": "/tmp/$(id)"}, {"FILE": "/non/esiste/f"}):
        r = go(N, s, dict({"MB": "512", "APPLICA": "si"}, **v), shells=["bash"]); expect(f"non valido {v}", r, 2, ["myrmm:"])
    s.close()
    s = mk(); os.makedirs(s.root + "/var/swap"); s.stub("mkswap", "exit 1")
    r = go(N, s, {"MB": "512", "FILE": "/var/swap/f", "APPLICA": "si"}, shells=["bash"]); expect("mkswap che fallisce → file rimosso", r, 1); check("file rimosso", not s.exists("/var/swap/f")); check("fstab non modificato", "/var/swap/f" not in (s.read("/etc/fstab") or "")); s.close()

N = "Linux: imposta il fuso orario e attiva la sincronizzazione dell'ora"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"timedatectl": 'case "$1" in set-timezone|set-ntp) exit 0;; *) echo "Time zone: Europe/Rome"; echo "System clock synchronized: yes";; esac'})
    r = go(N, s, shells=["bash"]); expect("predefinito Europe/Rome", r, 0, ["Time zone"]); check("set-timezone Europe/Rome + set-ntp true", "timedatectl set-timezone Europe/Rome" in r[0][4] and "timedatectl set-ntp true" in r[0][4], r[0][4])
    r = go(N, s, {"FUSO": "America/New_York"}, shells=["dash"]); check("fuso indicato", "set-timezone America/New_York" in r[0][4], r[0][4])
    for v in ("Mondo/Nowhere", "../etc/passwd", "/etc/passwd", "a b", "Europe/Rome;id", "$(id)"):
        open(s.root + "/calls.log", "w").close(); r = go(N, s, {"FUSO": v}, shells=["bash"]); expect(f"fuso non valido {v!r}", r, 2, ["myrmm:"]); check("timedatectl non chiamato", "set-timezone" not in r[0][4])
    s.close()
    s = sandbox.Sandbox(); r = go(N, s, {"FUSO": "Europe/Rome"}, shells=["bash"]); expect("senza timedatectl: collegamento a /etc/localtime", r, 0, ["Fuso orario impostato: Europe/Rome"]); check("/etc/localtime punta al fuso", os.path.realpath(s.root + "/etc/localtime").endswith("Europe/Rome")); s.close()

N = "Monitor Linux: configurazione del web server valida (nginx, Apache)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(); r = go(N, s); expect("nessun web server", r, 0, ["Nessun web server"]); s.close()
    s = sandbox.Sandbox(stubs={"nginx": 'echo "nginx: configuration file /etc/nginx/nginx.conf test is successful" >&2'}); r = go(N, s); expect("nginx valido", r, 0, ["nginx: configurazione valida"]); s.close()
    s = sandbox.Sandbox(stubs={"nginx": 'echo "nginx: [emerg] unexpected \\"}\\" in /etc/nginx/conf.d/x.conf:9" >&2; exit 1'}); r = go(N, s); expect("nginx errato", r, 1, ["CONFIGURAZIONE WEB NON VALIDA", "unexpected", "x.conf:9"]); s.close()
    s = sandbox.Sandbox(stubs={"apache2ctl": 'echo "Syntax error on line 12 of /etc/apache2/sites-enabled/a.conf" >&2; exit 1'}); r = go(N, s); expect("Apache errato", r, 1, ["Apache (apache2ctl)", "Syntax error on line 12"]); s.close()
    s = sandbox.Sandbox(stubs={"apachectl": "echo Syntax OK >&2", "nginx": "exit 0"}); r = go(N, s); expect("entrambi validi", r, 0, ["nginx: configurazione valida", "Apache (apachectl): configurazione valida"]); s.close()

N = "Monitor Linux: database attivi (MySQL, MariaDB, PostgreSQL)"
if want(N):
    print("==", N)
    SYS = lambda act, units: sandbox.Sandbox(stubs={"systemctl": 'case "$1" in list-unit-files) case "$2" in %s) echo "$2 enabled";; esac;; list-units) :;; is-active) case "$3$2" in %s) [ "$1" = is-active ] && { [ "$2" = --quiet ] && exit 0; echo active; exit 0; };; esac; case "$2" in --quiet) shift;; esac; case " %s " in *" $2 "*) [ "$2" != "$3" ] && exit 0; exit 0;; esac; echo inactive; exit 3;; esac' % (units, "NOPE", act)})
    def mk(active, units="mariadb.service|postgresql.service"):
        return sandbox.Sandbox(stubs={"systemctl": ('case "$1" in list-unit-files) case "$2" in %s) echo "$2 enabled";; esac;; list-units) :;; is-active) shift; [ "$1" = --quiet ] && shift; case " %s " in *" $1 "*) echo active; exit 0;; esac; echo inactive; exit 3;; esac' % (units, active))})
    s = mk("mariadb postgresql"); r = go(N, s); expect("tutti attivi", r, 0, ["Database attivi: mariadb postgresql"]); s.close()
    s = mk("mariadb"); r = go(N, s); expect("PostgreSQL fermo", r, 1, ["DATABASE NON ATTIVO: postgresql(inactive)", "attivi: mariadb"]); s.close()
    s = mk(""); r = go(N, s, {"SERVIZI": "mysql, mariadb"}); expect("servizi indicati", r, 1, ["mysql(inactive)", "mariadb(inactive)"]); s.close()
    s = mk("x"); r = go(N, s, {"SERVIZI": "x"}); expect("servizio indicato attivo", r, 0, ["Database attivi: x"]); s.close()
    s = mk("", units="NONE"); r = go(N, s); expect("nessun database installato", r, 0, ["Nessun servizio database installato"]); s.close()
    s = mk(""); 
    for v in ("x;id", "$(id)", "a b&c"): r = go(N, s, {"SERVIZI": v}, shells=["bash"]); expect(f"SERVIZI non validi {v!r}", r, 2, ["myrmm:"])
    s.close()
    s = sandbox.Sandbox(); r = go(N, s); expect("senza systemd", r, 0, ["systemctl non disponibile"]); s.close()

N = "Linux: backup dei database locali (MySQL/MariaDB e PostgreSQL)"
if want(N):
    print("==", N)
    BIG = 'i=0; while [ $i -lt 40 ]; do echo "INSERT INTO t VALUES ($i, abcdefghijklmnopqrstuvwxyz);"; i=$((i+1)); done'
    s = sandbox.Sandbox(stubs={"mysqldump": BIG, "pg_dumpall": BIG, "su": 'shift; shift; eval "$@"' if False else 'while [ $# -gt 0 ]; do case "$1" in -c) shift; eval "$1"; exit;; esac; shift; done', "id": 'if [ "$1" = -u ]; then echo 0; else exit 0; fi'}, real=[]); os.makedirs(s.root + "/bk")
    r = go(N, s, {"DESTINAZIONE": "/bk/"}, shells=["bash"]); expect("due motori", r, 0, ["MySQL/MariaDB: /bk/mysql-", "PostgreSQL: /bk/postgresql-"])
    fs = sorted(os.listdir(s.root + "/bk")); check("due file .sql.gz", len(fs) == 2 and all(f.endswith(".sql.gz") for f in fs), fs)
    import gzip as _gz
    check("il dump è un gzip valido con il contenuto", b"INSERT INTO t VALUES (3" in _gz.open(s.root + "/bk/" + fs[0]).read(), fs)
    check("permessi 600 (contiene dati)", all(oct(os.stat(s.root + "/bk/" + f).st_mode & 0o777) == "0o600" for f in fs), [oct(os.stat(s.root + "/bk/" + f).st_mode & 0o777) for f in fs])
    s.stub("mysqldump", 'echo "mysqldump: Got error: 1045: Access denied" >&2; exit 2')
    for f in os.listdir(s.root + "/bk"): os.remove(s.root + "/bk/" + f)
    r = go(N, s, {"DESTINAZIONE": "/bk"}, shells=["bash"]); expect("mysqldump che fallisce", r, 1, ["MySQL/MariaDB: dump NON riuscito", "Access denied", "PostgreSQL: /bk/postgresql-"]); check("niente file parziale di MySQL", not [f for f in os.listdir(s.root + "/bk") if f.startswith("mysql")], os.listdir(s.root + "/bk"))
    for v in ("rel", "", "/non-esiste"): r = go(N, s, {"DESTINAZIONE": v}, shells=["bash"]); expect(f"DESTINAZIONE non valida {v!r}", r, 2, ["myrmm:"])
    s.close()
    s = sandbox.Sandbox(); os.makedirs(s.root + "/bk"); r = go(N, s, {"DESTINAZIONE": "/bk"}, shells=["bash"]); expect("nessun database", r, 0, ["Nessun database locale"]); s.close()

N = "Monitor Linux: container Docker non sani o in riavvio continuo"
if want(N):
    print("==", N)
    mk = lambda unh="", rest="", exi="", n="3", info=0: sandbox.Sandbox(stubs={"docker": 'case "$1" in info) exit %d;; ps) case "$*" in *health=unhealthy*) printf "%%s" "%s";; *status=restarting*) printf "%%s" "%s";; *"-a"*) printf "%%s" "%s";; *-q*) for i in $(seq %s); do echo c$i; done;; esac;; esac' % (info, unh, rest, exi, n)})
    s = mk(); r = go(N, s); expect("tutto bene", r, 0, ["Container attivi: 3, nessun problema", "MYRMM_METRIC container_attivi=3"]); s.close()
    s = mk(unh="web\n", rest="worker\n", exi="job1 Exited (1) 2 hours ago\njob2 Exited (137) 1 hour ago\n"); r = go(N, s); expect("problemi", r, 1, ["CONTAINER CON PROBLEMI", "unhealthy: web", "in riavvio continuo: worker", "usciti con errore: job1,job2"]); s.close()
    s = mk(info=1); r = go(N, s); expect("daemon non risponde", r, 1, ["non risponde"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s); expect("Docker non installato", r, 0, ["non è installato"]); s.close()

N = "Linux: account che non accedono da molto tempo"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/etc/passwd": "root:x:0:0::/root:/bin/bash\nalice:x:1000:1000::/home/alice:/bin/bash\nbob:x:1001:1001::/home/bob:/bin/sh\ncarol:x:1002:1002::/home/carol:/usr/sbin/nologin\nsvc:x:999:999::/x:/bin/bash\n"},
                        stubs={"lastlog": 'echo "Username Port From Latest"; echo "root pts/0 1.2.3.4 Mon Jan  1 10:00:00 +0100 2024"; echo "alice pts/0 5.6.7.8 Tue Feb  2 09:00:00 +0100 2024"; echo "bob **Never logged in**"; echo "carol **Never logged in**"; echo "svc **Never logged in**"'})
    r = go(N, s); expect("account dormienti", r, 0, ["senza accessi da almeno 90 giorni: 2", "alice  ->  pts/0 5.6.7.8 Tue Feb 2 09:00:00 +0100 2024", "bob  ->  **Never logged in**"], ["carol", "root", "svc"]); 
    check("lastlog chiamato con -b 90", "lastlog -b 90" in r[0][4], r[0][4]); r = go(N, s, {"GIORNI": "30"}, shells=["bash"]); check("-b 30", "lastlog -b 30" in r[0][4], r[0][4])
    for v in ("x", "1;id", "-5"): r = go(N, s, {"GIORNI": v}, shells=["bash"]); expect(f"GIORNI non valido {v!r}", r, 2, ["GIORNI"])
    s.close()
    s = sandbox.Sandbox(files={"/etc/passwd": "alice:x:1000:1000::/home/alice:/bin/bash\n"}, stubs={"lastlog": 'echo "Username Port From Latest"'}); r = go(N, s); expect("nessuno", r, 0, ["lunghi periodi: 0"] if False else ["giorni: 0"]); s.close()

N = "Linux: blocca o sblocca un account utente"
if want(N):
    print("==", N)
    mk = lambda: sandbox.Sandbox(real=["getent", "id"], files={"/etc/passwd": "root:x:0:0::/root:/bin/bash\nalice:x:1000:1000::/home/alice:/bin/bash\nroot2:x:0:0::/root:/bin/bash\n", "/home/alice/.ssh/authorized_keys": "ssh-ed25519 AAAA x\n", "/home/alice/.ssh/authorized_keys2": "ssh-ed25519 BBBB y\n"},
                                   stubs={"usermod": "exit 0", "chage": "exit 0", "passwd": 'echo "alice L 2024-01-01 0 99999 7 -1"', "loginctl": "exit 0", "pkill": "exit 0"})
    s = mk(); r = go(N, s, {"UTENTE": "alice"}, shells=["bash"]); expect("blocca", r, 0, ["Account alice bloccato"]); c = r[0][4]; check("usermod -L alice + chage -E 0", "usermod -L alice" in c and "chage -E 0 alice" in c, c)
    check("senza opzioni le chiavi restano", s.exists("/home/alice/.ssh/authorized_keys") and "loginctl" not in c and "pkill" not in c, c)
    r = go(N, s, {"UTENTE": "alice", "TERMINA": "si", "SSH_ANCHE": "si"}, shells=["bash"]); expect("blocca con sessioni e chiavi", r, 0, ["Sessioni e processi di alice terminati", "Chiavi SSH disattivate"]); c = r[0][4]
    check("sessioni chiuse", "loginctl terminate-user alice" in c and "pkill -KILL -u alice" in c, c)
    check("chiavi rinominate", s.exists("/home/alice/.ssh/authorized_keys.bloccato") and s.exists("/home/alice/.ssh/authorized_keys2.bloccato") and not s.exists("/home/alice/.ssh/authorized_keys"))
    r = go(N, s, {"UTENTE": "alice", "AZIONE": "sblocca"}, shells=["dash"]); expect("sblocca", r, 0, ["Account alice sbloccato", "Chiavi SSH ripristinate"]); check("chiavi ripristinate", s.exists("/home/alice/.ssh/authorized_keys") and not s.exists("/home/alice/.ssh/authorized_keys.bloccato")); check("usermod -U", "usermod -U alice" in r[0][4], r[0][4])
    for v, why in (({"UTENTE": "root2"}, "UID 0"), ({"UTENTE": "root"}, "UID 0"), ({"UTENTE": "nessuno"}, "non esiste"), ({"UTENTE": ""}, "obbligatoria"), ({"UTENTE": "-x"}, "non valido"), ({"UTENTE": "a b"}, "non valido"), ({"UTENTE": "alice;id"}, "non valido"), ({"UTENTE": "alice", "AZIONE": "cancella"}, "AZIONE")):
        open(s.root + "/calls.log", "w").close(); r = go(N, s, v, shells=["bash"]); expect(f"rifiuta {v}", r, 2, [why]); check("nulla è stato modificato", "usermod" not in r[0][4] and "chage" not in r[0][4], r[0][4])
    s.close()

N = "Linux: forza la rotazione dei log (logrotate)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(files={"/etc/logrotate.conf": "weekly\n"}, stubs={"logrotate": 'echo "rotating pattern"; exit 0', "df": 'printf "Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/x 1000 10 2048 1%% /var\\n"'})
    r = go(N, s, shells=["bash"]); expect("rotazione", r, 0, ["rotating pattern", "prima 2 MB, dopo 2 MB"]); check("logrotate -f", "logrotate -f /etc/logrotate.conf" in r[0][4], r[0][4]); s.close()
    s = sandbox.Sandbox(files={"/etc/logrotate.conf": "weekly\n"}, stubs={"logrotate": 'echo "error: bad config"; exit 1', "df": 'printf "x\\n/dev/x 1000 10 2048 1%% /var\\n"'}); r = go(N, s, shells=["bash"]); expect("logrotate con errori", r, 1, ["segnalato errori (uscita 1)"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s, shells=["bash"]); expect("logrotate assente", r, 3, ["non è installato"]); s.close()

N = "Monitor Linux: file system montati in sola lettura"
if want(N):
    print("==", N)
    M = "/dev/sda1 / ext4 rw,relatime 0 0\n/dev/sdb1 /data xfs ro,relatime 0 0\n/dev/sdc1 /mnt/archivio ext4 ro 0 0\n/dev/loop0 /snap/core/1 squashfs ro 0 0\n/dev/sr0 /media/cd iso9660 ro 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/sdd1 /backup btrfs rw,ro_foo 0 0\n"
    s = sandbox.Sandbox(proc=False, files={"/proc/mounts": M}, stubs={"dmesg": 'echo "EXT4-fs error (device sdb1): ext4_find_entry"'}); r = go(N, s); expect("due ro", r, 1, ["FILE SYSTEM IN SOLA LETTURA", "/data (xfs)", "/mnt/archivio (ext4)", "EXT4-fs error"], ["squashfs", "iso9660", "/backup"]); 
    r = go(N, s, {"ECCEZIONI": "/mnt/archivio, /data"}); expect("eccezioni", r, 0, ["lettura e scrittura"]); r = go(N, s, {"ECCEZIONI": "/mnt/archivio"}); expect("eccezione parziale", r, 1, ["/data (xfs)"], ["/mnt/archivio"]); s.close()
    s = sandbox.Sandbox(proc=False, files={"/proc/mounts": "/dev/sda1 / ext4 rw 0 0\n"}); r = go(N, s); expect("tutto rw", r, 0, ["lettura e scrittura"]); s.close()

N = "Monitor Linux: troppe connessioni TCP o descrittori di file in uso"
if want(N):
    print("==", N)
    def mk(conn, fd_used, fd_max):
        return sandbox.Sandbox(proc=False, files={"/proc/sys/fs/file-nr": f"{fd_used}\t0\t{fd_max}\n"}, stubs={"ss": 'i=0; while [ $i -lt %d ]; do echo "0 0 1.1.1.1:$i 2.2.2.2:80"; i=$((i+1)); done' % conn})
    s = mk(10, 100, 1000); r = go(N, s); expect("tutto basso", r, 0, ["Connessioni TCP: 10, descrittori di file: 10%", "MYRMM_METRIC connessioni_tcp=10", "MYRMM_METRIC descrittori_file_pct=10"]); s.close()
    s = mk(6000, 100, 1000); r = go(N, s); expect("troppe connessioni", r, 1, ["RISORSE DI RETE/FILE ELEVATE", "connessioni TCP 6000 (soglia 5000)"]); r = go(N, s, {"SOGLIA_CONN": "7000"}); expect("soglia alzata", r, 0); s.close()
    s = mk(10, 900, 1000); r = go(N, s); expect("troppi descrittori", r, 1, ["descrittori di file 90% (soglia 80%)"]); r = go(N, s, {"SOGLIA_FD": "95"}); expect("soglia FD alzata", r, 0); s.close()
    s = mk(10, 100, 1000)
    for v in ({"SOGLIA_CONN": "x"}, {"SOGLIA_FD": "1;id"}): r = go(N, s, v, shells=["bash"]); expect(f"non valido {v}", r, 2, ["numeri"])
    s.close()


# ======================================================================= macOS (comandi finti) ============================
D = dict(uname="Darwin")
N = "macOS: audit di sicurezza (FileVault, SIP, Gatekeeper, firewall, accessi remoti)"
if want(N):
    print("==", N)
    FWP = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    good = {"fdesetup": 'echo "FileVault is On."', "csrutil": 'echo "System Integrity Protection status: enabled."', "spctl": 'echo "assessments enabled"',
            "netstat": 'true', "defaults": 'exit 1'}
    s = sandbox.Sandbox(stubs=good, **D)
    s.file(FWP, '#!/bin/sh\ncase "$1" in --getglobalstate) echo "Firewall is enabled. (State = 1)";; --getstealthmode) echo "Stealth mode enabled";; esac\n', 0o755)
    r = go(N, s, {"FALLISCI": "si"}); expect("Mac a posto", r, 0, ["nessuna impostazione da rivedere", "OK         FileVault"], ["ATTENZIONE"]); s.close()
    badst = dict(good); badst.update({"fdesetup": 'echo "FileVault is Off."', "csrutil": 'echo "System Integrity Protection status: disabled."', "spctl": 'echo "assessments disabled"',
        "netstat": 'echo "tcp4 0 0 *.22 *.* LISTEN"; echo "tcp4 0 0 *.5900 *.* LISTEN"',
        "defaults": 'case "$*" in *autoLoginUser*) echo mario;; *GuestEnabled*) echo 1;; *AutomaticCheckEnabled*) echo 0;; *CriticalUpdateInstall*) echo 0;; *) exit 1;; esac'})
    s = sandbox.Sandbox(stubs=badst, **D)
    s.file(FWP, '#!/bin/sh\ncase "$1" in --getglobalstate) echo "Firewall is disabled. (State = 0)";; --getstealthmode) echo "Stealth mode disabled";; esac\n', 0o755)
    r = go(N, s); expect("Mac con problemi", r, 0, ["impostazioni da rivedere", "ATTENZIONE FileVault", "ATTENZIONE SIP", "ATTENZIONE Gatekeeper", "ATTENZIONE Firewall", "attivo per mario", "abilitato", "disattivato", "disattivata"])
    r = go(N, s, {"FALLISCI": "si"}); expect("Mac con problemi + FALLISCI", r, 1)
    r = go(N, s, {"FALLISCI": "no"}); expect("FALLISCI=no", r, 0)
    s.close()
    s = sandbox.Sandbox(**D); r = go(N, s); expect("senza strumenti (comandi assenti)", r, 0, ["impostazioni da rivedere"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s, shells=["bash"]); expect("su Linux: rifiutato", r, 3, ["solo per macOS"]); s.close()

N = "macOS: abilita il firewall applicativo"
if want(N):
    print("==", N)
    FWP = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    FW = '#!/bin/sh\necho "fw $*" >> /fw.log\ncase "$1" in --getglobalstate) echo "Firewall is enabled. (State = 1)";; --getstealthmode) echo "Stealth mode enabled";; esac\n'
    s = sandbox.Sandbox(**D); s.file(FWP, FW, 0o755)
    r = go(N, s, shells=["bash"]); expect("attiva con modalità invisibile", r, 0, ["enabled"]); L = s.read("/fw.log") or ""
    check("firewall: global on e stealth on", "--setglobalstate on" in L and "--setstealthmode on" in L, L)
    s.close()
    s = sandbox.Sandbox(**D); s.file(FWP, FW, 0o755)
    r = go(N, s, {"INVISIBILE": "no"}, shells=["bash"]); expect("senza modalità invisibile", r, 0); L = s.read("/fw.log") or ""
    check("firewall: stealth non toccato", "--setstealthmode on" not in L and "--setglobalstate on" in L, L); s.close()
    s = sandbox.Sandbox(stubs={"id": 'echo 501'}, **D); s.file(FWP, FW, 0o755); r = go(N, s, shells=["bash"]); expect("senza root", r, 3, ["root"]); s.close()
    s = sandbox.Sandbox(**D); r = go(N, s, shells=["bash"]); expect("socketfilterfw assente", r, 3); s.close()

N = "macOS: installa gli aggiornamenti software"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"softwareupdate": 'echo "Software Update Tool"; echo "No new software available."'}, **D)
    r = go(N, s); expect("nessun aggiornamento", r, 0, ["Nessun aggiornamento"]); s.close()
    SU = 'if [ "$1" = --list ]; then echo "* Label: macOS 14.7.1-23H222"; echo "   Title: macOS Sonoma, Version: 14.7.1, Recommended: YES, Action: restart"; else echo "Done. Restart required"; fi'
    s = sandbox.Sandbox(stubs={"softwareupdate": SU}, **D)
    r = go(N, s, shells=["bash"]); expect("aggiorna senza riavviare", r, 0, ["Aggiornamenti disponibili", "serve un riavvio"]); L = s.read("/calls.log") or ""
    check("senza -R", "--install --all" in L and "--install --all -R" not in L, L)
    r = go(N, s, {"RIAVVIA": "si"}, shells=["bash"]); expect("con riavvio", r, 0); check("-R passato", "--install --all -R" in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'if [ "$1" = --list ]; then echo "* Label: x"; else echo "errore di rete"; exit 3; fi'}, **D)
    r = go(N, s, shells=["bash"]); expect("errore di softwareupdate", r, 1, ["errore (uscita 3)"]); s.close()
    s = sandbox.Sandbox(stubs={"id": 'echo 501', "softwareupdate": 'true'}, **D); r = go(N, s, shells=["bash"]); expect("senza root", r, 3); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'true'}, **D); r = go(N, s, {"RIAVVIA": "si; touch /PWNED"}, shells=["bash"]); check("RIAVVIA ostile non esegue nulla", not s.exists("/PWNED") and "-R" not in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()

N = "macOS: stato MDM e profili di configurazione"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"profiles": 'case "$*" in *enrollment*) echo "Enrolled via DEP: Yes"; echo "MDM enrollment: Yes (User Approved)";; *) echo "_computerlevel[1] attribute: profileIdentifier: com.acme.mdm";; esac', "pgrep": 'exit 0'}, **D)
    r = go(N, s); expect("Mac gestito", r, 0, ["Enrolled via DEP: Yes", "com.acme.mdm", "mdmclient è in esecuzione"]); s.close()
    s = sandbox.Sandbox(stubs={"profiles": 'echo "There are no configuration profiles installed"', "pgrep": 'exit 1'}, **D)
    r = go(N, s); expect("Mac non gestito", r, 0, ["no configuration profiles", "non è in esecuzione"]); s.close()

N = "macOS: Time Machine (destinazioni e ultimo backup)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"defaults": 'echo 1', "tmutil": 'case "$1" in destinationinfo) echo "Name : Backup1";; latestbackup) echo "/Volumes/Backup1/Backups.backupdb/mac/2026-10-01-120000";; listbackups) echo a; echo b;; listlocalsnapshots) echo "com.apple.TimeMachine.2026-10-17-100000.local";; esac'}, **D)
    r = go(N, s); expect("TM configurato", r, 0, ["Backup1", "2026-10-01-120000", "com.apple.TimeMachine.2026-10-17"], regex=[r"Backup elencati\n2"]); s.close()

N = "Monitor macOS: backup Time Machine recente"
if want(N):
    print("==", N)
    import datetime as _dt
    def tm(days_ago):
        d = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
        return sandbox.Sandbox(stubs={"tmutil": 'echo "/Volumes/B/Backups.backupdb/mac/%s"' % d.strftime("%Y-%m-%d-%H%M%S")}, **D)
    for age, lim, rc in ((0, "3", 0), (3, "3", 0), (4, "3", 1), (40, "3", 1), (40, "60", 0), (400, "3", 1)):
        s = tm(age); r = go(N, s, {"GIORNI": lim}); expect(f"backup di {age} giorni, limite {lim}", r, rc, [f"MYRMM_METRIC giorni_dall_ultimo_backup={age}"]); s.close()
    for date_, now_ in (("2024-02-28-100000", "2024-03-01"), ("2023-12-31-230000", "2024-01-01"), ("2023-02-28-100000", "2023-03-01")):
        a = _dt.date.fromisoformat(date_[:10]); b = _dt.date.fromisoformat(now_)
        s = sandbox.Sandbox(stubs={"tmutil": 'echo "/V/mac/%s"' % date_, "date": 'echo "%s"' % b.strftime("%Y %m %d")}, **D)
        r = go(N, s, {"GIORNI": "100"}, shells=["bash"]); expect(f"date {date_[:10]} → {now_}", r, 0, [f"giorni_dall_ultimo_backup={(b - a).days}"]); s.close()
    s = sandbox.Sandbox(stubs={"tmutil": 'echo "No backups found"'}, **D); r = go(N, s); expect("nessun backup", r, 1, ["NESSUN BACKUP"]); s.close()
    s = sandbox.Sandbox(stubs={"tmutil": 'exit 1'}, **D); r = go(N, s); expect("tmutil in errore", r, 1, ["NESSUN BACKUP"]); s.close()
    s = sandbox.Sandbox(stubs={"tmutil": 'echo x'}, **D)
    for v in ("x", "1;id", "-5", "1 2"): r = go(N, s, {"GIORNI": v}, shells=["bash"]); expect(f"GIORNI non valido {v!r}", r, 2, ["numero"])
    s.close()

N = "macOS: utenti locali, amministratori e Secure Token"
if want(N):
    print("==", N)
    DS = 'case "$*" in *"-list /Users UniqueID") printf "root 0\\nmario 501\\nluca 502\\n_spotlight 89\\ndaemon 1\\n";; *"-read /Groups/admin"*) echo "GroupMembership: root mario";; *"-read /Users/mario"*) echo "NFSHomeDirectory: /Users/mario";; *"-read /Users/luca"*) echo "NFSHomeDirectory: /Users/luca";; esac'
    s = sandbox.Sandbox(stubs={"dscl": DS, "sysadminctl": 'echo "2024 sysadminctl[1:2] Secure token is ENABLED for user $2"; case "$2" in luca) echo "Secure token is DISABLED for user luca";; esac', "last": 'echo "mario  console  Mon Oct 12 09:00"'}, **D)
    r = go(N, s); expect("utenti", r, 0, ["Amministratori (gruppo admin): root mario", "mario"], ["_spotlight", "daemon"], regex=[r"^mario +AMMINISTRATORE", r"^luca +utente"]); s.close()

N = "macOS: agenti e daemon di avvio non Apple"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(**D)
    s.file("/usr/libexec/PlistBuddy", '#!/bin/sh\nf="$3"\nl=$(basename "$f" .plist)\ncase "$2" in *:Label) echo "$l";; *:ProgramArguments:0) echo "/opt/$l/bin";; *:Program) exit 1;; esac\n', 0o755)
    for f in ("/Library/LaunchDaemons/com.vendor.agent.plist", "/Library/LaunchDaemons/com.apple.thing.plist", "/Library/LaunchAgents/org.x.helper.plist", "/Users/mario/Library/LaunchAgents/it.mio.job.plist"): s.file(f, "x")
    r = go(N, s); expect("elenco non Apple", r, 0, ["com.vendor.agent  ->  /opt/com.vendor.agent/bin", "org.x.helper", "it.mio.job", "Elementi esaminati: 4"], ["com.apple.thing  ->"]); s.close()
    s = sandbox.Sandbox(**D); r = go(N, s); expect("nessun agente", r, 0, ["Elementi esaminati: 0"]); s.close()

N = "macOS: pulizia di cache e rapporti di errore vecchi"
if want(N):
    print("==", N)
    OLDF = ("/Library/Caches/vecchio.bin", "/Users/mario/Library/Caches/com.x/vecchia.db", "/Users/mario/Library/Logs/DiagnosticReports/crash1.ips", "/Users/mario/Documents/importante.docx")
    def cache_sbx():
        s = sandbox.Sandbox(**D)
        for f in OLDF: s.file(f, "A" * 3000)
        s.file("/Library/Caches/nuovo.bin", "B" * 3000)
        old = time.time() - 90 * 86400
        for f in OLDF: os.utime(s.root + f, (old, old))
        return s
    s = cache_sbx(); r = go(N, s, {"GIORNI": "30"}, shells=["bash"]); expect("anteprima", r, 0, ["Totale recuperabile", "Anteprima"])
    check("anteprima: nulla eliminato", all(s.exists(f) for f in OLDF + ("/Library/Caches/nuovo.bin",)), "")
    r = go(N, s, {"GIORNI": "30", "APPLICA": "si"}, shells=["bash"]); expect("applica", r, 0, ["Pulizia eseguita"])
    check("vecchi eliminati", not any(s.exists(f) for f in OLDF[:3]), "")
    check("nuovi e documenti intatti", s.exists("/Library/Caches/nuovo.bin") and s.exists(OLDF[3]), "")
    s.close()
    s = cache_sbx(); r = go(N, s, {"GIORNI": "100", "APPLICA": "si"}, shells=["bash"]); expect("nessun file abbastanza vecchio", r, 0, ["circa 0 MB"]); check("tutto intatto", s.exists(OLDF[0]), ""); s.close()
    s = cache_sbx()
    for v in ("x", "0", "-1", "3;id", "1 2"): r = go(N, s, {"GIORNI": v, "APPLICA": "si"}, shells=["bash"]); expect(f"GIORNI non valido {v!r}", r, 2)
    check("GIORNI ostile: nulla eliminato", s.exists(OLDF[0]), ""); s.close()

N = "macOS: ricostruisci l'indice di Spotlight"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"mdutil": 'echo "/: Indexing enabled."'}, **D); r = go(N, s, shells=["bash"]); expect("reindicizza", r, 0, ["Indexing enabled"]); check("mdutil -E /", "mdutil -E /" in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()
    s = sandbox.Sandbox(stubs={"mdutil": 'true', "id": 'echo 501'}, **D); r = go(N, s, shells=["bash"]); expect("senza root", r, 3); s.close()

N = "macOS: svuota la cache DNS"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"dscacheutil": 'true', "killall": 'exit 0'}, **D); r = go(N, s); expect("svuota", r, 0, ["mDNSResponder riavviato"]); s.close()
    s = sandbox.Sandbox(stubs={"dscacheutil": 'true', "killall": 'exit 1'}, **D); r = go(N, s, shells=["bash"]); expect("mDNSResponder assente", r, 0, ["non era in esecuzione"]); s.close()
    s = sandbox.Sandbox(stubs={"dscacheutil": 'exit 1', "killall": 'true'}, **D); r = go(N, s, shells=["bash"]); expect("dscacheutil fallisce", r, 1); s.close()

N = "macOS: verifica il volume di sistema"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"diskutil": 'echo "The volume / appears to be OK"'}, **D); r = go(N, s); expect("volume ok", r, 0, ["Verifica superata"]); s.close()
    s = sandbox.Sandbox(stubs={"diskutil": 'echo "Error: -69845"; exit 1'}, **D); r = go(N, s, shells=["bash"]); expect("volume con errori", r, 1, ["VERIFICA NON SUPERATA"]); s.close()
    s = sandbox.Sandbox(stubs={"diskutil": 'true'}, **D)
    for v in ("-x", "/non/esiste"): r = go(N, s, {"VOLUME": v}, shells=["bash"]); expect(f"VOLUME {v}", r, 2)
    r = go(N, s, {"VOLUME": "/tmp"}, shells=["bash"]); expect("VOLUME esistente", r, 0); check("diskutil chiamato con /tmp", "verifyVolume /tmp" in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()

N = "macOS: configurazione di rete (servizi, DNS, proxy, Wi-Fi)"
if want(N):
    print("==", N)
    NS = 'case "$1" in -listallnetworkservices) echo "An asterisk (*) denotes that a network service is disabled."; echo "Wi-Fi"; echo "*Thunderbolt Bridge";; -getinfo) echo "DHCP Configuration"; echo "IP address: 10.0.0.5"; echo "Router: 10.0.0.1";; -getdnsservers) echo "1.1.1.1";; -getwebproxy) echo "Enabled: No";; -getsecurewebproxy) echo "Enabled: No";; -getautoproxyurl) echo "URL: (null)";; -getairportnetwork) echo "Current Wi-Fi Network: Ufficio";; esac'
    s = sandbox.Sandbox(stubs={"networksetup": NS}, **D); r = go(N, s); expect("rete", r, 0, ["== Wi-Fi", "== Thunderbolt Bridge", "IP address: 10.0.0.5", "DNS: 1.1.1.1", "Ufficio"]); s.close()

N = "macOS: imposta i server DNS di un servizio di rete"
if want(N):
    print("==", N)
    NS = 'case "$1" in -listallnetworkservices) echo "An asterisk (*) denotes that a network service is disabled."; echo "Wi-Fi"; echo "Ethernet USB";; -getdnsservers) echo "1.1.1.1";; esac'
    s = sandbox.Sandbox(stubs={"networksetup": NS}, **D)
    r = go(N, s, {"DNS": "1.1.1.1, 9.9.9.9"}, shells=["bash"]); expect("due DNS", r, 0); check("setdnsservers Wi-Fi 1.1.1.1 9.9.9.9", "-setdnsservers Wi-Fi 1.1.1.1 9.9.9.9" in (s.read("/calls.log") or ""), s.read("/calls.log"))
    r = go(N, s, {"DNS": "", "SERVIZIO": "Ethernet USB"}, shells=["bash"]); expect("DNS automatici", r, 0); check("Empty", "-setdnsservers Ethernet USB Empty" in (s.read("/calls.log") or ""), s.read("/calls.log"))
    r = go(N, s, {"DNS": "2606:4700:4700::1111"}, shells=["bash"]); expect("IPv6", r, 0)
    n0 = (s.read("/calls.log") or "").count("-setdnsservers")
    for v in ("1.1.1", "1.1.1.1.1", "256.1.1.1", "a.b.c.d", "1.1.1.1;id", "$(id)", "1.1.1.1 && x", "abc", "1.1.1.-1", "1..1.1"):
        r = go(N, s, {"DNS": v}, shells=["bash"]); expect(f"DNS non valido {v!r}", r, 2, ["non è un indirizzo IP valido"])
    r = go(N, s, {"SERVIZIO": "Inesistente"}, shells=["bash"]); expect("servizio inesistente", r, 2, ["non esiste"])
    check("nessuna modifica per valori non validi", (s.read("/calls.log") or "").count("-setdnsservers") == n0, s.read("/calls.log"))
    s.close()

N = "macOS: imposta il nome del computer"
if want(N):
    print("==", N)
    SC = 'case "$1" in --get) echo "VecchioMac";; --set) echo "$2=$3" >> /set.log;; esac'
    s = sandbox.Sandbox(stubs={"scutil": SC, "dscacheutil": 'true'}, **D); r = go(N, s, {"NOME": "Mac di Mario-01"}, shells=["bash"]); expect("nome valido", r, 0, ["VecchioMac"])
    L = s.read("/set.log") or ""; check("nomi impostati", "ComputerName=Mac di Mario-01" in L and "HostName=Mac-di-Mario-01" in L and "LocalHostName=Mac-di-Mario-01" in L, L); s.close()
    s = sandbox.Sandbox(stubs={"scutil": SC, "dscacheutil": 'true'}, **D)
    for v in ("", "a;b", "a$(id)", "a'b", "a\"b", "è", "a" * 61, "a`id`", "a|b"): r = go(N, s, {"NOME": v}, shells=["bash"]); expect(f"NOME non valido {v[:12]!r}", r, 2)
    check("nulla impostato", not s.exists("/set.log"), s.read("/set.log")); s.close()

N = "macOS: snapshot locali di Time Machine (elenco ed eliminazione)"
if want(N):
    print("==", N)
    TM = 'case "$1" in listlocalsnapshotdates) echo "Snapshot dates for all disks:"; echo "2026-10-16-100000"; echo "2026-10-17-100000";; deletelocalsnapshots) echo "del $2" >> /del.log;; esac'
    s = sandbox.Sandbox(stubs={"tmutil": TM}, **D)
    r = go(N, s, shells=["bash"]); expect("elenco", r, 0, ["Snapshot locali: 2", "2026-10-16-100000", "Anteprima"]); check("anteprima: nulla eliminato", not s.exists("/del.log"), "")
    r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("elimina", r, 0, ["Eliminati 2 snapshot su 2"]); L = s.read("/del.log") or ""; check("eliminati entrambi", "del 2026-10-16-100000" in L and "del 2026-10-17-100000" in L, L); s.close()
    s = sandbox.Sandbox(stubs={"tmutil": 'case "$1" in listlocalsnapshotdates) echo "Snapshot dates for all disks:";; esac'}, **D); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("nessuno snapshot", r, 0, ["Snapshot locali: 0", "Niente da eliminare"]); s.close()
    s = sandbox.Sandbox(stubs={"tmutil": TM.replace('echo "del $2" >> /del.log', 'exit 1')}, **D); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("eliminazione fallita", r, 1, ["Eliminati 0 snapshot su 2"]); s.close()

N = "macOS: rimuovi l'attributo di quarantena da un'app o cartella"
if want(N):
    print("==", N)
    XA = 'if [ "$1" = -l ]; then if [ -f "$2" ] && [ ! -f /q.removed ]; then echo "com.apple.quarantine: 0083;x"; fi; elif [ "$1" = -dr ]; then : > /q.removed; fi'
    s = sandbox.Sandbox(stubs={"xattr": XA}, **D); s.file("/Applications/Mia.app/Contents/x", "x")
    r = go(N, s, {"PERCORSO": "/Applications/Mia.app/"}, shells=["bash"]); expect("rimuove", r, 0, ["Attributi di quarantena: prima 1, dopo 0"]); s.close()
    s = sandbox.Sandbox(stubs={"xattr": 'if [ "$1" = -l ]; then [ -f "$2" ] && echo "com.apple.quarantine: 1"; fi'}, **D); s.file("/Applications/Mia.app/Contents/x", "x")
    r = go(N, s, {"PERCORSO": "/Applications/Mia.app"}, shells=["bash"]); expect("non rimovibile", r, 1, ["non si sono potuti rimuovere"]); s.close()
    s = sandbox.Sandbox(stubs={"xattr": 'true'}, **D); s.file("/Applications/Mia.app/x", "x")
    for v in ("", "relativo/app", "/Applications/../etc", "/System/Library", "/usr/bin", "/", "/Library", "/Users", "/private/etc", "/Applications/Inesistente.app"):
        r = go(N, s, {"PERCORSO": v}, shells=["bash"]); expect(f"PERCORSO non ammesso {v!r}", r, 2)
    check("xattr -dr mai chiamato", "-dr" not in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()

N = "macOS: installa un pacchetto .pkg o .dmg da un indirizzo"
if want(N):
    print("==", N)
    import hashlib
    HSH = hashlib.sha256(b"PAYLOAD-pkg").hexdigest()
    def inst_sbx(rc_installer=0):
        return sandbox.Sandbox(stubs={
            "curl": 'o=""; while [ $# -gt 0 ]; do case "$1" in -o) o=$2; shift;; esac; shift; done; printf "PAYLOAD-pkg" > "$o"',
            "shasum": 'sha256sum "$3"', "installer": 'echo "installer: ok"; exit %d' % rc_installer,
            "hdiutil": 'case "$1" in attach) mp=""; while [ $# -gt 0 ]; do [ "$1" = -mountpoint ] && mp=$2; shift; done; mkdir -p "$mp/Mia.app";; detach) echo detached >> /hd.log;; esac',
            "ditto": 'echo "ditto $1 $2" >> /ditto.log'}, **D)
    s = inst_sbx(); r = go(N, s, {"URL": "https://example.com/p/a.pkg", "SHA256": HSH}, shells=["bash"]); expect("pkg con hash giusto", r, 0, ["SHA-256 verificata", "Pacchetto installato"]); s.close()
    s = inst_sbx(); r = go(N, s, {"URL": "https://example.com/p/a.pkg", "SHA256": "0" * 64}, shells=["bash"]); expect("hash sbagliato", r, 1, ["non combacia"]); check("installer non chiamato", "installer" not in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()
    s = inst_sbx(); r = go(N, s, {"URL": "https://example.com/p/a.pkg?x=1"}, shells=["bash"]); expect("pkg senza hash, con query", r, 0, ["Pacchetto installato"]); s.close()
    s = inst_sbx(1); r = go(N, s, {"URL": "https://example.com/p/a.pkg"}, shells=["bash"]); expect("installer fallisce", r, 1, ["non riuscita"]); s.close()
    s = inst_sbx(); r = go(N, s, {"URL": "https://example.com/p/a.dmg", "SHA256": HSH.upper()}, shells=["bash"]); expect("dmg con app", r, 0, ["App Mia.app copiata"]); check("ditto chiamato", "/Applications/Mia.app" in (s.read("/ditto.log") or ""), s.read("/ditto.log")); check("immagine smontata", "detached" in (s.read("/hd.log") or ""), s.read("/hd.log")); s.close()
    s = inst_sbx()
    for v in ("", "http://example.com/a.pkg", "ftp://x/a.pkg", "https://example.com/a.zip", "https://x/a.pkg;id", "https://x/a.pkg$(id)", "https://x/a pkg.pkg", "https://x/a.pkg`id`", "https://x/a.pkg'", "file:///etc/a.pkg"):
        r = go(N, s, {"URL": v}, shells=["bash"]); expect(f"URL non valido {v!r}", r, 2)
    for v in ("abc", "g" * 64, "a" * 63, "a" * 65, "1;id"):
        r = go(N, s, {"URL": "https://example.com/a.pkg", "SHA256": v}, shells=["bash"]); expect(f"SHA256 non valido {v[:10]!r}", r, 2)
    check("curl mai chiamato per valori non validi", "curl" not in (s.read("/calls.log") or ""), s.read("/calls.log")); s.close()

N = "macOS: installa Rosetta 2 (Mac con Apple silicon)"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"softwareupdate": 'echo installing; : > /rosetta', "arch": 'test -f /rosetta'}, arch="arm64", **D); r = go(N, s, shells=["bash"]); expect("installa", r, 0, ["Rosetta 2 installata"]); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'true', "arch": 'exit 0'}, arch="arm64", **D); r = go(N, s, shells=["bash"]); expect("già installata", r, 0, ["già installata"]); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'true', "arch": 'exit 1'}, arch="x86_64", **D); r = go(N, s, shells=["bash"]); expect("Mac Intel", r, 0, ["non serve"]); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'true', "arch": 'exit 1'}, arch="arm64", **D); r = go(N, s, shells=["bash"]); expect("installazione senza effetto", r, 1); s.close()

N = "macOS: imposta il fuso orario e la sincronizzazione dell'ora"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(stubs={"systemsetup": 'true'}, **D); s.file("/var/db/timezone/zoneinfo/Europe/Rome", "x"); s.file("/var/db/timezone/zoneinfo/America/New_York", "x")
    r = go(N, s, shells=["bash"]); expect("predefinito Rome", r, 0, ["Fuso orario: Europe/Rome"]); r = go(N, s, {"FUSO": "America/New_York"}, shells=["bash"]); expect("New York", r, 0, ["Fuso orario: America/New_York"])
    for v in ("Mars/Olympus", "../../etc/passwd", "/etc/passwd", "Europe/Rome;id", "$(id)", "Europe Rome"):
        r = go(N, s, {"FUSO": v}, shells=["bash"]); expect(f"FUSO non valido {v!r}", r, 2)
    s.close()


# ---- macOS blocco 2 ----
N = "Monitor macOS: protezioni di sicurezza attive"
if want(N):
    print("==", N)
    FWP = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    def mkp(fv=True, fw=True, gk=True, sip=True):
        s = sandbox.Sandbox(stubs={"fdesetup": 'echo "FileVault is %s."' % ("On" if fv else "Off"), "spctl": 'echo "assessments %s"' % ("enabled" if gk else "disabled"),
                                   "csrutil": 'echo "System Integrity Protection status: %s."' % ("enabled" if sip else "disabled")}, **D)
        s.file(FWP, '#!/bin/sh\necho "Firewall is %s."\n' % ("enabled" if fw else "disabled"), 0o755); return s
    s = mkp(); r = go(N, s); expect("tutto attivo", r, 0, ["protezioni_mancanti=0", "Tutte le protezioni"]); s.close()
    s = mkp(fv=False, sip=False); r = go(N, s); expect("FileVault e SIP spenti", r, 1, ["PROTEZIONI NON ATTIVE: FileVault SIP", "protezioni_mancanti=2"])
    r = go(N, s, {"CONTROLLI": "firewall, gatekeeper"}); expect("controllo solo firewall/gatekeeper", r, 0); r = go(N, s, {"CONTROLLI": "FileVault"}); expect("maiuscole", r, 1, ["FileVault"]); s.close()
    s = mkp(fw=False, gk=False); r = go(N, s); expect("firewall e Gatekeeper spenti", r, 1, ["firewall Gatekeeper"]); s.close()
    s = mkp()
    for v in ("rete", "filevault;id", "$(id)", "file vault!"): r = go(N, s, {"CONTROLLI": v}, shells=["bash"]); expect(f"CONTROLLI non valido {v!r}", r, 2)
    s.close()

N = "Monitor macOS: aggiornamenti software in sospeso"
if want(N):
    print("==", N)
    LST = 'echo "Software Update Tool"; echo "Finding available software"; echo "Software Update found the following new or updated software:"; echo "* Label: macOS 14.7.1-23H222"; echo "\\tTitle: macOS Sonoma 14.7.1, Version: 14.7.1, Size: 1GiB, Recommended: YES, Action: restart,"; echo "* Label: Safari17-1"; echo "\\tTitle: Safari, Version: 17.1, Size: 100KiB, Recommended: NO,"'
    s = sandbox.Sandbox(stubs={"softwareupdate": LST}, **D); r = go(N, s, shells=["bash"]); expect("due aggiornamenti", r, 1, ["IN SOSPESO: 2", "aggiornamenti_in_sospeso=2"])
    r = go(N, s, {"SOLO_SICUREZZA": "si"}, shells=["bash"]); expect("solo raccomandati", r, 1, ["IN SOSPESO: 1"]); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'echo "No new software available."'}, **D); r = go(N, s); expect("nessuno", r, 0, ["aggiornamenti_in_sospeso=0", "Nessun aggiornamento"]); s.close()
    s = sandbox.Sandbox(stubs={"softwareupdate": 'echo "Network error"; exit 1'}, **D); r = go(N, s, shells=["bash"]); expect("softwareupdate in errore", r, 1, ["non ha risposto"]); s.close()

N = "Monitor macOS: spazio libero sul volume dati"
if want(N):
    print("==", N)
    def dfs(total_gb, free_gb): return sandbox.Sandbox(stubs={"df": 'echo "Filesystem 1024-blocks Used Available Capacity Mounted"; echo "/dev/disk3s5 %d 0 %d 0%% /System/Volumes/Data"' % (total_gb * 1048576, free_gb * 1048576)}, **D)
    s = dfs(500, 200); s.file("/System/Volumes/Data/x", "x"); r = go(N, s); expect("tanto spazio", r, 0, ["spazio_libero_pct=40", "spazio_libero_gb=200"]); s.close()
    s = dfs(500, 30); s.file("/System/Volumes/Data/x", "x"); r = go(N, s); expect("6% libero", r, 1, ["SPAZIO INSUFFICIENTE"]); r = go(N, s, {"MIN_PERCENTUALE": "5"}); expect("soglia % abbassata", r, 0); s.close()
    s = dfs(2000, 150); s.file("/System/Volumes/Data/x", "x"); r = go(N, s); expect("7% ma 150 GB", r, 1, ["SPAZIO INSUFFICIENTE"]); r = go(N, s, {"MIN_PERCENTUALE": "5"}); expect("soglia % abbassata", r, 0); s.close()
    s = dfs(100, 8); s.file("/System/Volumes/Data/x", "x"); r = go(N, s, {"MIN_PERCENTUALE": "5"}); expect("8 GB < 10 GB", r, 1); r = go(N, s, {"MIN_PERCENTUALE": "5", "MIN_GB": "5"}); expect("soglia GB abbassata", r, 0); s.close()
    s = dfs(100, 50)
    for v in ({"MIN_PERCENTUALE": "x"}, {"MIN_GB": "1;id"}, {"MIN_PERCENTUALE": "101"}, {"MIN_GB": "-1"}): r = go(N, s, v, shells=["bash"]); expect(f"non valido {v}", r, 2)
    s.close()
    s = sandbox.Sandbox(stubs={"df": 'echo hdr'}, **D); s.file("/System/Volumes/Data/x", "x"); r = go(N, s, shells=["bash"]); expect("df illeggibile", r, 1, ["Impossibile leggere"]); s.close()

N = "Monitor macOS: kernel panic recenti"
if want(N):
    print("==", N)
    s = sandbox.Sandbox(**D); s.file("/Library/Logs/DiagnosticReports/Kernel_2026-10-17.panic", "x"); s.file("/Library/Logs/DiagnosticReports/App.crash", "x")
    old = time.time() - 40 * 86400; s.file("/Library/Logs/DiagnosticReports/vecchio.panic", "x"); os.utime(s.root + "/Library/Logs/DiagnosticReports/vecchio.panic", (old, old))
    r = go(N, s); expect("un panic recente", r, 1, ["kernel_panic=1", "KERNEL PANIC", "Kernel_2026-10-17.panic"], ["vecchio.panic", "App.crash"]); r = go(N, s, {"GIORNI": "60"}); expect("finestra larga", r, 1, ["kernel_panic=2"]); s.close()
    s = sandbox.Sandbox(**D); s.file("/Library/Logs/DiagnosticReports/App.crash", "x"); r = go(N, s); expect("nessun panic", r, 0, ["kernel_panic=0"]); s.close()
    s = sandbox.Sandbox(**D)
    for v in ("x", "0", "1;id", "-3"): r = go(N, s, {"GIORNI": v}, shells=["bash"]); expect(f"GIORNI non valido {v!r}", r, 2)
    s.close()

N = "Monitor macOS: pressione di memoria e swap"
if want(N):
    print("==", N)
    def mem(free, swap): return sandbox.Sandbox(stubs={"memory_pressure": 'echo "The system has 17179869184 (1048576 pages with a page size of 16384)."; echo "System-wide memory free percentage: %d%%"' % free, "sysctl": 'echo "total = 4096.00M  used = %d.50M  free = 100.00M  (encrypted)"' % swap}, **D)
    s = mem(40, 100); r = go(N, s); expect("tutto bene", r, 0, ["memoria_libera_pct=40", "swap_usato_mb=100"]); s.close()
    s = mem(5, 100); r = go(N, s); expect("poca memoria", r, 1, ["memoria libera 5% (minimo 10%)"]); r = go(N, s, {"MIN_LIBERA": "3"}); expect("soglia abbassata", r, 0); s.close()
    s = mem(50, 8000); r = go(N, s); expect("molto swap", r, 1, ["swap usato 8000 MB"]); r = go(N, s, {"MAX_SWAP_MB": "9000"}); expect("soglia swap alzata", r, 0); s.close()
    s = mem(2, 9000); r = go(N, s); expect("entrambi", r, 1, ["memoria libera 2%", "swap usato 9000"]); s.close()
    s = sandbox.Sandbox(stubs={"memory_pressure": 'true', "sysctl": 'true'}, **D); r = go(N, s, shells=["bash"]); expect("memory_pressure muto", r, 1, ["Impossibile"]); 
    for v in ({"MIN_LIBERA": "x"}, {"MAX_SWAP_MB": "1;id"}): r = go(N, s, v, shells=["bash"]); expect(f"non valido {v}", r, 2)
    s.close()

N = "Monitor macOS: riavvio non eseguito da troppo tempo"
if want(N):
    print("==", N)
    def up(days): return sandbox.Sandbox(stubs={"sysctl": 'echo "{ sec = %d, usec = 123456 } Mon Oct  1 10:00:00 2026"' % (int(time.time()) - days * 86400 - 600)}, **D)
    for d, lim, rc in ((1, "30", 0), (30, "30", 0), (31, "30", 1), (200, "30", 1), (200, "365", 0)):
        s = up(d); r = go(N, s, {"GIORNI": lim}, shells=["bash"]); expect(f"{d} giorni, limite {lim}", r, rc, [f"giorni_senza_riavvio={d}"]); s.close()
    s = sandbox.Sandbox(stubs={"sysctl": 'exit 1'}, **D); r = go(N, s, shells=["bash"]); expect("sysctl in errore", r, 1); 
    for v in ("x", "1;id", "-2"): r = go(N, s, {"GIORNI": v}, shells=["bash"]); expect(f"GIORNI non valido {v!r}", r, 2)
    s.close()

N = "macOS: errori recenti nel registro di sistema"
if want(N):
    print("==", N)
    LG = 'echo "Timestamp Ty Process"; echo "2026-10-17 10:00:00 E kernel: disk0 timeout"; echo "2026-10-17 10:00:01 E Safari: network lost"; echo "2026-10-17 10:00:02 F mds: crash"'
    s = sandbox.Sandbox(stubs={"log": LG}, **D); r = go(N, s, shells=["bash"]); expect("errori", r, 0, ["4 righe", "kernel: disk0 timeout", "mds: crash"]); check("log show --last 30m", "show --last 30m" in (s.read("/calls.log") or ""), s.read("/calls.log"))
    r = go(N, s, {"FILTRO": "safari", "MINUTI": "5"}, shells=["bash"]); expect("filtro", r, 0, ["1 righe", "Safari: network lost", "«safari»"], ["kernel:"])
    r = go(N, s, {"FILTRO": "xyz"}, shells=["bash"]); expect("filtro senza risultati", r, 0, ["0 righe"])
    for v in ({"MINUTI": "x"}, {"MINUTI": "0"}, {"MINUTI": "2000"}, {"MINUTI": "5;id"}, {"FILTRO": "a;b"}, {"FILTRO": "$(id)"}, {"FILTRO": "a'b"}, {"FILTRO": "a`id`"}):
        r = go(N, s, v, shells=["bash"]); expect(f"non valido {v}", r, 2)
    s.close()
    s = sandbox.Sandbox(stubs={"log": 'echo "boom"; exit 1'}, **D); r = go(N, s, shells=["bash"]); expect("log show fallisce", r, 1, ["non è riuscito"]); s.close()

N = "macOS: disabilita o riabilita un account locale"
if want(N):
    print("==", N)
    def acc(admins="root mario luca", disabled=()):
        DSC = ('case "$*" in *"-read /Users/mario UniqueID"*) echo "UniqueID: 501";; *"-read /Users/luca UniqueID"*) echo "UniqueID: 502";; *"-read /Users/_www UniqueID"*) echo "UniqueID: 70";; *"-read /Users/root UniqueID"*) echo "UniqueID: 0";; '
               '*"-read /Groups/admin"*) echo "GroupMembership: %s";; esac' % admins)
        PW = 'case "$*" in *-getpolicy*) case "$2" in %s) echo "isDisabled=1";; *) echo "isDisabled=0";; esac;; *) echo "pw $*" >> /pw.log;; esac' % ("|".join(disabled) or "NONE_")
        return sandbox.Sandbox(stubs={"dscl": DSC, "pwpolicy": PW}, **D)
    s = acc(); r = go(N, s, {"UTENTE": "luca"}, shells=["bash"]); expect("disabilita", r, 0, ["disabilitato"]); check("pwpolicy -disableuser", "-u luca -disableuser" in (s.read("/pw.log") or ""), s.read("/pw.log"))
    r = go(N, s, {"UTENTE": "luca", "AZIONE": "abilita"}, shells=["bash"]); expect("abilita", r, 0, ["riabilitato"]); check("pwpolicy -enableuser", "-u luca -enableuser" in (s.read("/pw.log") or ""), s.read("/pw.log")); s.close()
    s = acc(admins="root mario"); r = go(N, s, {"UTENTE": "mario"}, shells=["bash"]); expect("ultimo amministratore", r, 2, ["ultimo amministratore"]); check("nulla disabilitato", not s.exists("/pw.log"), ""); s.close()
    s = acc(disabled=("luca",)); r = go(N, s, {"UTENTE": "mario"}, shells=["bash"]); expect("l'altro admin è già disabilitato", r, 2, ["ultimo amministratore"]); s.close()
    s = acc(); r = go(N, s, {"UTENTE": "mario"}, shells=["bash"]); expect("c'è un altro admin attivo", r, 0, ["disabilitato"]); s.close()
    s = acc()
    for v, rc in (("root", 2), ("_www", 2), ("nessuno", 2), ("", 2), ("a b", 2), ("a;id", 2), ("-x", 2), (".x", 2), ("$(id)", 2), ("a/b", 2)):
        r = go(N, s, {"UTENTE": v}, shells=["bash"]); expect(f"UTENTE {v!r}", r, rc)
    r = go(N, s, {"UTENTE": "luca", "AZIONE": "cancella"}, shells=["bash"]); expect("AZIONE non valida", r, 2)
    check("nessun pwpolicy per valori non validi", not s.exists("/pw.log"), s.read("/pw.log")); s.close()
    s = sandbox.Sandbox(stubs={"id": 'echo 501'}, **D); r = go(N, s, {"UTENTE": "luca"}, shells=["bash"]); expect("senza root", r, 3); s.close()

N = "macOS: rimuovi un account locale"
if want(N):
    print("==", N)
    def acc2(admins="root mario luca", console="mario"):
        DSC = ('case "$3" in /Groups/admin) echo "GroupMembership: %s";; /Users/mario|/Users/luca|/Users/_www) [ "$3" != /Users/_www ] && [ -f /deleted ] && exit 1; '
               'case "$4" in UniqueID) case "$3" in /Users/mario) echo "UniqueID: 501";; /Users/luca) echo "UniqueID: 502";; *) echo "UniqueID: 70";; esac;; NFSHomeDirectory) echo "NFSHomeDirectory: $3";; *) echo x;; esac;; *) exit 1;; esac' % admins)
        s = sandbox.Sandbox(stubs={"dscl": DSC, "sysadminctl": '[ "$1" = -deleteUser ] && : > /deleted; echo "sysadminctl $*" >> /sa.log', "stat": 'echo %s' % console}, **D)
        s.file("/Users/luca/doc.txt", "A" * 2048); return s
    s = acc2(); r = go(N, s, {"UTENTE": "luca"}, shells=["bash"]); expect("anteprima", r, 0, ["Account: luca (UID 502)", "Anteprima", "-secure"]); check("anteprima: non eliminato", not s.exists("/sa.log"), s.read("/sa.log")); s.close()
    s = acc2(); r = go(N, s, {"UTENTE": "luca", "APPLICA": "si"}, shells=["bash"]); expect("elimina", r, 0, ["eliminato (opzione -secure)"]); check("sysadminctl -deleteUser luca -secure", "-deleteUser luca -secure" in (s.read("/sa.log") or ""), s.read("/sa.log")); s.close()
    s = acc2(); r = go(N, s, {"UTENTE": "luca", "APPLICA": "si", "TIENI_CARTELLA": "si"}, shells=["bash"]); expect("tiene cartella", r, 0, ["-keepHome"]); s.close()
    s = acc2(console="luca"); r = go(N, s, {"UTENTE": "luca", "APPLICA": "si"}, shells=["bash"]); expect("utente collegato", r, 2, ["collegato"]); check("nulla eliminato", not s.exists("/sa.log"), ""); s.close()
    s = acc2(admins="root luca mario", console="root"); r = go(N, s, {"UTENTE": "mario", "APPLICA": "si"}, shells=["bash"]); expect("elimina un admin con un altro admin", r, 0); s.close()
    s = acc2(admins="root luca", console="root"); r = go(N, s, {"UTENTE": "luca", "APPLICA": "si"}, shells=["bash"]); expect("ultimo admin", r, 2, ["ultimo amministratore"]); check("nulla eliminato", not s.exists("/sa.log"), ""); s.close()
    s = acc2()
    for v in ("root", "_www", "nessuno", "", "a b", "a;id", "-x", ".x", "$(id)", "a/b", "luca;rm -rf /"):
        r = go(N, s, {"UTENTE": v, "APPLICA": "si"}, shells=["bash"]); expect(f"UTENTE {v!r}", r, 2)
    check("sysadminctl mai chiamato", not s.exists("/sa.log"), s.read("/sa.log")); s.close()
    s = sandbox.Sandbox(stubs={"id": 'echo 501'}, **D); r = go(N, s, {"UTENTE": "luca", "APPLICA": "si"}, shells=["bash"]); expect("senza root", r, 3); s.close()

# ---- blocco 5: ispirati a ComStore ----
N = "Monitor Linux/macOS: salute della batteria (usura e cicli)"
if want(N):
    print("==", N)
    sp = lambda cyc, mx, cond="Normal": f'printf "Power:\\n  Battery Information:\\n      Cycle Count: {cyc}\\n      Condition: {cond}\\n      Maximum Capacity: {mx}%%\\n"'
    s = sandbox.Sandbox(uname="Darwin", stubs={"system_profiler": sp(120, 95)}); r = go(N, s); expect("macOS sana", r, 0, ["usura 5%", "cicli di carica 120", "batteria_usura_pct=5", "batteria_cicli=120"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"system_profiler": sp(950, 60, "Service Recommended")}); r = go(N, s); expect("macOS usurata", r, 1, ["usura 40% (soglia 30%)", "condizione «Service Recommended»"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"system_profiler": sp(1200, 95)}); r = go(N, s); expect("macOS cicli", r, 1, ["cicli 1200 (soglia 1000)"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"system_profiler": sp(1200, 95)}); r = go(N, s, {"SOGLIA_CICLI": "2000", "SOGLIA_USURA": "3"}); expect("soglie personalizzate", r, 1, ["usura 5% (soglia 3%)"], ["cicli 1200 (soglia"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"system_profiler": 'echo "Power:"'}); r = go(N, s); expect("macOS senza batteria", r, 0, ["Nessuna batteria", "usura_pct=-1"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"system_profiler": 'printf "Cycle Count: 10\\n"', "ioreg": 'printf "\\"MaxCapacity\\" = 4000\\n\\"DesignCapacity\\" = 5000\\n"'}); r = go(N, s); expect("macOS senza percentuale: ioreg", r, 0, ["usura 20%"]); s.close()
    BP = "/sys/class/power_supply/BAT0/"
    s = sandbox.Sandbox(files={BP + "cycle_count": "300\n", BP + "energy_full": "40000000\n", BP + "energy_full_design": "50000000\n", BP + "status": "Discharging\n"}); r = go(N, s); expect("Linux energy", r, 0, ["usura 20%", "cicli di carica 300", "stato Discharging"]); s.close()
    s = sandbox.Sandbox(files={BP + "charge_full": "2000\n", BP + "charge_full_design": "4000\n"}); r = go(N, s); expect("Linux charge: usura 50%", r, 1, ["usura 50% (soglia 30%)"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s); expect("Linux senza batteria", r, 0, ["Nessuna batteria"]); s.close()
    s = sandbox.Sandbox()
    for v in ({"SOGLIA_USURA": "0"}, {"SOGLIA_USURA": "100"}, {"SOGLIA_USURA": "x"}, {"SOGLIA_CICLI": "-1"}, {"SOGLIA_CICLI": "1;id"}, {"SOGLIA_USURA": "$(id)"}):
        r = go(N, s, v, shells=["bash"]); expect(f"non valido {v}", r, 2)
    s.close()

N = "Monitor Linux/macOS: stato SMART dei dischi"
if want(N):
    print("==", N)
    dl = 'printf "/dev/disk0 (internal, physical):\\n   #: TYPE NAME\\n/dev/disk1 (synthesized):\\n/dev/disk2 (external, physical):\\n"'
    di = lambda a, b: 'case "$2" in /dev/disk0) echo "   SMART Status: %s";; /dev/disk2) echo "   SMART Status: %s";; esac' % (a, b)
    s = sandbox.Sandbox(uname="Darwin", stubs={"diskutil": 'if [ "$1" = list ]; then ' + dl + '; else ' + di("Verified", "Not Supported") + '; fi'}); r = go(N, s); expect("macOS ok", r, 0, ["/dev/disk0: SMART verificato", "/dev/disk2: SMART non disponibile", "controllati: 2, con problemi: 0", "dischi_smart_ko=0"], ["disk1"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"diskutil": 'if [ "$1" = list ]; then ' + dl + '; else ' + di("Failing", "Verified") + '; fi'}); r = go(N, s); expect("macOS guasto", r, 1, ["/dev/disk0: SMART Failing", "dischi_smart_ko=1", "copia dei dati"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s); expect("Linux senza smartctl", r, 0, ["smartctl non è installato", "dischi_smart_ko=-1"]); s.close()
    def smart(devs, res):
        c = 'if [ "$1" = --scan ]; then printf "' + "".join(f"{d} -d scsi # {d}\\n" for d in devs) + '"; exit 0; fi\n'
        for d, (out, rc) in res.items(): c += f'if [ "$2" = {d} ]; then echo "{out}"; exit {rc}; fi\n'
        return c + 'exit 1\n'
    P_ = "SMART overall-health self-assessment test result: PASSED"
    s = sandbox.Sandbox(stubs={"smartctl": smart(["/dev/sda", "/dev/nvme0"], {"/dev/sda": (P_, 0), "/dev/nvme0": ("SMART overall-health self-assessment test result: PASSED", 0)})}); r = go(N, s); expect("Linux ok", r, 0, ["/dev/sda: SMART PASSED", "/dev/nvme0: SMART PASSED", "con problemi: 0"]); s.close()
    s = sandbox.Sandbox(stubs={"smartctl": smart(["/dev/sda", "/dev/sdb"], {"/dev/sda": (P_, 0), "/dev/sdb": ("SMART overall-health self-assessment test result: FAILED!", 8)})}); r = go(N, s); expect("Linux guasto", r, 1, ["/dev/sdb: SMART FAILED", "dischi_smart_ko=1"]); s.close()
    s = sandbox.Sandbox(stubs={"smartctl": smart(["/dev/vda"], {"/dev/vda": ("SMART support is: Unavailable - device lacks SMART capability.", 4)})}); r = go(N, s); expect("Linux disco virtuale", r, 0, ["SMART non disponibile", "senza SMART: 1"]); s.close()
    s = sandbox.Sandbox(stubs={"smartctl": smart(["/dev/sda"], {"/dev/sda": ("boh", 8)})}); r = go(N, s); expect("Linux bit 8 dello stato", r, 1, ["stato disco"]); s.close()
    s = sandbox.Sandbox(stubs={"smartctl": smart([], {})}); r = go(N, s); expect("Linux nessun disco", r, 0, ["controllati: 0"]); s.close()

N = "Monitor Linux/macOS: software presente o assente"
if want(N):
    print("==", N)
    dp = 'printf "ii nginx 1.24\\nii openssh-server 9.2\\nrc vecchio 1.0\\n"'
    s = sandbox.Sandbox(stubs={"dpkg-query": dp}); r = go(N, s, {"NOME": "nginx"}); expect("Linux presente", r, 0, ["«nginx» risulta installato", "nginx 1.24", "software_presente=1"]); s.close()
    s = sandbox.Sandbox(stubs={"dpkg-query": dp}); r = go(N, s, {"NOME": "nginx", "MODO": "assente"}); expect("presente ma deve mancare", r, 1, ["non dovrebbe essere installato"]); s.close()
    s = sandbox.Sandbox(stubs={"dpkg-query": dp}); r = go(N, s, {"NOME": "apache2", "MODO": "assente"}); expect("assente come richiesto", r, 0, ["non risulta installato", "software_presente=0"]); s.close()
    s = sandbox.Sandbox(stubs={"dpkg-query": dp}); r = go(N, s, {"NOME": "apache2"}); expect("manca ma deve esserci", r, 1, ["dovrebbe essere installato"]); s.close()
    s = sandbox.Sandbox(stubs={"dpkg-query": dp}); r = go(N, s, {"NOME": "vecchio"}); expect("pacchetto rimosso (rc) non conta", r, 1); s.close()
    s = sandbox.Sandbox(stubs={"rpm": 'printf "httpd-2.4.57-1.el9.x86_64\\n"'}); r = go(N, s, {"NOME": "HTTPD"}); expect("rpm, maiuscole", r, 0, ["httpd-2.4.57"]); s.close()
    s = sandbox.Sandbox(stubs={"mytool": 'true'}); r = go(N, s, {"NOME": "mytool"}); expect("comando nel PATH", r, 0, ["comando:"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", files={"/Applications/Google Chrome.app/Contents/Info.plist": "x"}); r = go(N, s, {"NOME": "Google Chrome"}); expect("macOS app", r, 0, ["Google Chrome.app"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", files={"/Applications/Slack.app/Contents/Info.plist": "x"}); r = go(N, s, {"NOME": "TeamViewer", "MODO": "assente"}); expect("macOS app assente", r, 0, ["non risulta installato"]); s.close()
    s = sandbox.Sandbox(uname="Darwin", stubs={"pkgutil": 'echo com.teamviewer.pkg'}); r = go(N, s, {"NOME": "teamviewer", "MODO": "assente"}); expect("macOS pkgutil", r, 1, ["com.teamviewer.pkg"]); s.close()
    s = sandbox.Sandbox()
    for v in ({"NOME": ""}, {"NOME": "a;id"}, {"NOME": "$(id)"}, {"NOME": "-x"}, {"NOME": "a'b"}, {"NOME": "x" * 101}, {"NOME": "nginx", "MODO": "boh"}):
        r = go(N, s, v, shells=["bash"]); expect(f"non valido {str(v)[:40]}", r, 2)
    s.close()

N = "Linux/macOS: riavvio programmato con avviso agli utenti"
if want(N):
    print("==", N)
    sh = {"shutdown": 'echo "shutdown $*" >> /sd.log'}
    s = sandbox.Sandbox(stubs=sh); r = go(N, s); expect("anteprima", r, 0, ["Anteprima", "fra 10 minuti", "APPLICA=si"]); check("niente shutdown", not s.exists("/sd.log"), ""); s.close()
    s = sandbox.Sandbox(stubs=sh); r = go(N, s, {"APPLICA": "si", "MINUTI": "30", "MESSAGGIO": "Manutenzione alle 22: salvare."}, shells=["bash"]); expect("riavvio", r, 0, ["Riavvio pianificato fra 30 minuti"]); check("shutdown -r +30 con messaggio", s.read("/sd.log").strip() == "shutdown -r +30 Manutenzione alle 22: salvare.", s.read("/sd.log")); s.close()
    s = sandbox.Sandbox(stubs=sh); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("messaggio predefinito", r, 0); check("+10", "shutdown -r +10 Il computer" in s.read("/sd.log"), s.read("/sd.log")); s.close()
    s = sandbox.Sandbox(stubs=sh); r = go(N, s, {"AZIONE": "annulla"}); expect("annulla anteprima", r, 0, ["Anteprima"]); check("niente", not s.exists("/sd.log"), ""); s.close()
    s = sandbox.Sandbox(stubs=sh); r = go(N, s, {"AZIONE": "annulla", "APPLICA": "si"}, shells=["bash"]); expect("annulla", r, 0, ["annullato"]); check("shutdown -c", s.read("/sd.log").startswith("shutdown -c"), s.read("/sd.log")); s.close()
    s = sandbox.Sandbox(stubs={"shutdown": 'exit 1'}); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("shutdown fallisce", r, 1, ["non è riuscito"]); s.close()
    s = sandbox.Sandbox(stubs=sh, uname="Darwin"); r = go(N, s, {"APPLICA": "si", "MINUTI": "5"}, shells=["bash"]); expect("macOS", r, 0, ["fra 5 minuti"]); s.close()
    s = sandbox.Sandbox(stubs=sh)
    for v in ({"MINUTI": "0"}, {"MINUTI": "1441"}, {"MINUTI": "x"}, {"MINUTI": "-5"}, {"MINUTI": "5;id"}, {"AZIONE": "boh"}, {"MESSAGGIO": "a;reboot"}, {"MESSAGGIO": "$(id)"}, {"MESSAGGIO": "a'b"}, {"MESSAGGIO": "`id`"}, {"MESSAGGIO": "x" * 201}):
        v = dict(v, APPLICA="si"); r = go(N, s, v, shells=["bash"]); expect(f"non valido {str(v)[:40]}", r, 2)
    check("shutdown mai chiamato", not s.exists("/sd.log"), s.read("/sd.log") if s.exists("/sd.log") else ""); s.close()
    s = sandbox.Sandbox(stubs=dict(sh, id='echo 1000')); r = go(N, s, {"APPLICA": "si"}, shells=["bash"]); expect("senza root", r, 3); s.close()

N = "Monitor Linux/macOS: ClamAV (installazione, database e demone)"
if want(N):
    print("==", N)
    import time as _t
    now = int(_t.time())
    cl = {"clamscan": 'echo "ClamAV 1.0.5/27000/Mon"'}
    def dbf(days): return {"/var/lib/clamav/daily.cvd": "x", "/var/lib/clamav/main.cvd": "x"}
    s = sandbox.Sandbox(); r = go(N, s); expect("non installato", r, 0, ["non è installato", "clamav_db_giorni=-1"]); s.close()
    s = sandbox.Sandbox(); r = go(N, s, {"OBBLIGATORIO": "si"}); expect("obbligatorio", r, 1, ["obbligatorio"]); s.close()
    s = sandbox.Sandbox(stubs=cl, files=dbf(0)); r = go(N, s); expect("database fresco", r, 0, ["Versione: ClamAV 1.0.5", "aggiornato 0 giorni fa", "clamav_db_giorni=0"]); s.close()
    s = sandbox.Sandbox(stubs=cl, files=dbf(0)); s.run("touch -d '10 days ago' /var/lib/clamav/daily.cvd /var/lib/clamav/main.cvd"); r = go(N, s); expect("database vecchio", r, 1, ["aggiornato 10 giorni fa", "massimo 3"]); s.close()
    s = sandbox.Sandbox(stubs=cl, files=dbf(0)); s.run("touch -d '10 days ago' /var/lib/clamav/daily.cvd /var/lib/clamav/main.cvd"); r = go(N, s, {"GIORNI": "30"}); expect("soglia personalizzata", r, 0); s.close()
    s = sandbox.Sandbox(stubs=cl, files={"/var/lib/clamav/readme": "x"}); r = go(N, s); expect("nessun database", r, 1, ["esegui freshclam"]); s.close()
    s = sandbox.Sandbox(stubs=cl); r = go(N, s); expect("cartella assente", r, 1, ["non trovata"]); s.close()
    s = sandbox.Sandbox(stubs=dict(cl, systemctl='case "$2" in clamav-daemon) echo active;; clamav-freshclam) echo inactive;; *) echo unknown;; esac'), files=dbf(0)); r = go(N, s); expect("servizi", r, 0, ["Servizio clamav-daemon: active", "Servizio clamav-freshclam: inactive"], ["clamd@scan"]); s.close()
    s = sandbox.Sandbox(stubs=cl, uname="Darwin", files={"/opt/homebrew/share/clamav/daily.cld": "x"}); r = go(N, s); expect("macOS Homebrew", r, 0, ["/opt/homebrew/share/clamav"]); s.close()
    s = sandbox.Sandbox()
    for v in ("0", "366", "x", "-1", "3;id", "$(id)"): r = go(N, s, {"GIORNI": v}, shells=["bash"]); expect(f"GIORNI {v!r}", r, 2)
    s.close()

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d ok, %d falliti" % (ok, bad)); sys.exit(1 if bad else 0)
