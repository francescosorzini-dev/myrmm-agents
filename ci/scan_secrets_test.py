#!/usr/bin/env python3
"""Lo scanner di segreti deve trovare davvero i segreti (anche cancellati dalla storia), non segnalare i segnaposto e non stampare mai un segreto intero.
Uso: python3 ci/scan_secrets_test.py"""
import os, subprocess, sys, tempfile, shutil, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); SC = os.path.join(ROOT, "ci", "scan_secrets.py")
tmp = tempfile.mkdtemp(prefix="myrmm-scan-"); res = []
def rec(n, ok, info=""): res.append(bool(ok)); print(("OK   " if ok else "FAIL ") + n + (("  [" + str(info)[:500] + "]") if (not ok and info != "") else ""), flush=True)
def g(*a, cwd=None): return subprocess.run(["git", *a], cwd=cwd or tmp, capture_output=True, text=True, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org"))
def scan(*a, repo=None):
    p = subprocess.run([sys.executable, SC, repo or tmp, *a], capture_output=True, text=True); return p.returncode, p.stdout + p.stderr
try:
    rnd = random.Random(7); hx = lambda n: "".join(rnd.choice("0123456789abcdef") for _ in range(n))
    TOK = "myrmm_" + hx(48); PW = "Zx9" + hx(12) + "Qq"; GH = "ghp_" + "".join(rnd.choice("ABCDEFabcdef0123456789") for _ in range(36))
    g("init", "-q", "-b", "main"); os.makedirs(tmp + "/agent"); os.makedirs(tmp + "/server")
    open(tmp + "/agent/ok.go", "w").write('package main\n// nessun segreto qui\nconst v = "1.0"\nvar url = "http://127.0.0.1:8080"\n')
    open(tmp + "/server/privato.php", "w").write("<?php // server riservato, non da pubblicare\n$k = '%s';\n" % TOK)
    g("add", "-A"); g("commit", "-q", "-m", "base")
    rc, out = scan("--paths", "agent"); rec("percorso pulito: nessun risultato bloccante (exit 0)", rc == 0 and "ALTO 0, MEDIO 0" in out, out)
    rc, out = scan(); rec("senza --paths trova il token myrmm in server/", rc == 1 and "token myrmm" in out and "server/privato.php" in out, out)
    rec("non stampa mai il segreto intero", TOK not in out and TOK[6:] not in out, out)
    open(tmp + "/agent/cfg.json", "w").write('{"password": "%s", "note": "x"}\n-----BEGIN RSA PRIVATE KEY-----\nabc\n' % PW)
    open(tmp + "/agent/gh.txt", "w").write("token %s\n" % GH)
    open(tmp + "/agent/rete.txt", "w").write("host 10.20.30.40 e cliente Acme Srl\nvalore di prova password = 'Fixture12345' # scan:ok\n")
    open(tmp + "/agent/firma.jks", "wb").write(os.urandom(300)); open(tmp + "/agent/blob.txt", "w").write("A" + "".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/") for _ in range(600)) + "\n")
    g("add", "-A"); g("commit", "-q", "-m", "con segreti"); 
    for f in ("cfg.json", "gh.txt", "rete.txt", "firma.jks", "blob.txt"): os.remove(tmp + "/agent/" + f)
    g("add", "-A"); g("commit", "-q", "-m", "rimossi (restano nella storia)")
    open(tmp + "/terms.txt", "w").write("Acme Srl\n")
    rc, out = scan("--paths", "agent", "--terms", tmp + "/terms.txt")
    rec("segreti CANCELLATI dal file ma presenti nella storia: trovati", rc == 1 and all(k in out for k in ("chiave privata", "token GitHub", "segreto assegnato", "file di chiavi/certificati nella storia", "blocco base64 lungo", "indirizzo di rete privato")), out)
    rec("termine riservato dalla lista", "termine riservato «acme srl»" in out, out)
    rec("la riga con «scan:ok» è ignorata", "Fixture12345" not in out and out.count("segreto assegnato") == 1, out)
    rec("nessun segreto stampato per intero (password, token GitHub)", PW not in out and GH not in out and GH[4:] not in out)
    open(tmp + "/agent/ph.txt", "w").write("MYRMM_TOKEN=myrmm_" + "a" * 48 + "\npassword = '{{PASSWORD}}'\nsecret: \"changeme-please\"\n")
    g("add", "-A"); g("commit", "-q", "-m", "segnaposto")
    rc, out = scan("--paths", "agent/ph.txt"); rec("segnaposto (cifre tutte uguali, {{VAR}}, changeme): solo INFO, exit 0", rc == 0 and "segnaposto" in out and "ALTO 0, MEDIO 0" in out, out)
    rc, out = scan("--paths", "agent", "--allow-path", "agent/*"); rec("--allow-path esclude i percorsi indicati", rc == 0, out)
    open(tmp + "/agent/config.json", "w").write('{"enroll_token": "Tk-9fQ2xLm7Ab3", "job_signing_key": "Zq!8vNe4Wd2Rp7"}\n'); g("add", "-A"); g("commit", "-q", "-m", "esempio di config con valori veri")
    rc, out = scan("--paths", "agent/config.json"); rec("enroll_token / job_signing_key con valore vero: ALTO (una riga sola per valore)", rc == 1 and out.count("chiave/segreto di myrmm") == 2 and "segreto assegnato" not in out and "Tk-9fQ2" not in out and "Zq!8vNe" not in out, out)
    open(tmp + "/agent/oid.go", "w").write('var oid = ".1.3.6.1.2.1.43.10.2.1.4.1.1"\nvar net = "10.0.0.0/8"\n'); open(tmp + "/agent/x_test.go", "w").write('var h = "192.168.1.10"\n'); open(tmp + "/agent/host.go", "w").write('var h = "192.168.7.20"\n')
    g("add", "-A"); g("commit", "-q", "-m", "ip")
    rc, out = scan("--paths", "agent/oid.go", "agent/x_test.go"); rec("OID SNMP, intervalli di rete e IP in file di prova: solo INFO", rc == 0 and "ALTO 0, MEDIO 0" in out, out)
    rc, out = scan("--paths", "agent/host.go"); rec("un IP privato in codice vero resta MEDIO", rc == 1 and "indirizzo di rete privato" in out, out)
    p = subprocess.run([sys.executable, SC, "/nonexistent-repo"], capture_output=True, text=True); rec("repository inesistente: errore chiaro, non un falso «pulito»", p.returncode != 0 and "ALTO" not in p.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
f = res.count(False); print(f"\n{len(res) - f}/{len(res)} ok"); sys.exit(1 if f else 0)
