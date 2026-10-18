#!/usr/bin/env python3
"""Cerca segreti e dati riservati in un repository git PRIMA di pubblicarlo: tutta la storia (ogni versione di ogni file, anche
cancellato, binari compresi) più i messaggi e gli autori dei commit. Non stampa mai un segreto intero (primi caratteri + lunghezza).

Uso:  python3 ci/scan_secrets.py REPO [--paths agent mcp/go ...] [--terms FILE] [--allow-path GLOB ...] [--max-mb 50]
  --paths       limita la scansione ai percorsi che pubblicherai (la storia dei soli file indicati)
  --terms FILE  una parola per riga (nomi di clienti, domini interni, host): ogni occorrenza è segnalata. Tieni il file FUORI dal repo.
  --allow-path  percorsi (glob) da non segnalare, ad esempio dati di prova: ci/*_test.py
  Una riga con «scan:ok» è ignorata (valori di prova voluti).
Esce con 1 se resta qualcosa di ALTO o MEDIO, con 0 altrimenti. Gravità: ALTO = chiavi, token, keystore; MEDIO = password assegnate,
indirizzi privati, termini della lista, blocchi base64 lunghi; INFO = e-mail, domini, segnaposto (da guardare, non bloccano)."""
import argparse, collections, fnmatch, os, re, subprocess, sys

HIGH, MED, INFO = "ALTO", "MEDIO", "INFO"
PAT = [  # (gravità, nome, regex su byte)
    (HIGH, "chiave privata", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY")),
    (HIGH, "token GitHub", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    (HIGH, "chiave AWS", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    (HIGH, "token Slack", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    (HIGH, "chiave API Google", re.compile(rb"\bAIza[0-9A-Za-z_\-]{35}\b")),
    (HIGH, "token myrmm", re.compile(rb"\bmyrmm_[0-9a-f]{48}\b")),
    (MED, "segreto assegnato", re.compile(rb"""(?i)\b([\w.-]*(?:password|passwd|secret|token|api[_-]?key|signing[_-]?key|private[_-]?key)[\w.-]*)["']?\s*[:=]\s*["']([^"'\s$<{}][^"'\s]{7,})["']""")),
    (HIGH, "chiave/segreto di myrmm", re.compile(rb"""(?i)\b(job_signing_key|enroll_token|console_pass)\b["']?\s*(?:=>|[:=])\s*["']([^"'\s$<{}][^"'\s]{11,})["']""")),
    (MED, "indirizzo di rete privato", re.compile(rb"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\.?\d)")),
    (MED, "blocco base64 lungo (keystore? file incorporato?)", re.compile(rb"[A-Za-z0-9+/]{400,}={0,2}")),
    (INFO, "indirizzo e-mail", re.compile(rb"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
]
PLACEHOLDER = re.compile(rb"(?i)(\{\{|\$\{|example|changeme|your[_-]|xxxx|\.\.\.|placeholder|<[a-z]|insert|todo|dummy|sample|null|none|false|true|redacted)")
SECRET_FILES = re.compile(r"(?i)\.(jks|keystore|p12|pfx|pem|key|kdbx|ppk|asc)$")
DATA_FILES = re.compile(r"(?i)\.(sqlite3?|db|sql|csv|xlsx?|bak|log|env)$|(^|/)\.env")
IGN_MAIL = re.compile(rb"(?i)@(example\.|anthropic\.com|users\.noreply\.github\.com|localhost)|noreply@")


def git(repo, *a, text=False, check=True):
    p = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=text, errors="replace" if text else None)
    if check and p.returncode: sys.exit("git %s: %s" % (" ".join(a[:3]), (p.stderr if text else p.stderr.decode("utf-8", "replace")).strip()))
    return p.stdout


def redact(b):
    s = b.decode("utf-8", "replace").strip()
    return "%s… (%d car.)" % (s[:5], len(s)) if len(s) > 8 else "*" * len(s)


def scan_bytes(data, where, terms, found, text_ok=True):
    binary = b"\x00" in data[:8192]
    for sev, name, rx in PAT:
        if binary and sev != HIGH: continue
        for m in rx.finditer(data):
            ls = data.rfind(b"\n", 0, m.start()) + 1; le = data.find(b"\n", m.end()); le = len(data) if le < 0 else le
            line = data[ls:le]
            if b"scan:ok" in line: continue
            lineno = data.count(b"\n", 0, m.start()) + 1 if not binary else 0
            sv = sev; val = m.group(0)
            if name == "token myrmm" and len(set(val[6:])) <= 2: sv, name2 = INFO, "token myrmm segnaposto (cifre tutte uguali)"
            else: name2 = name
            if name in ("segreto assegnato", "chiave/segreto di myrmm"):
                val = m.group(2)
                if PLACEHOLDER.search(val) or PLACEHOLDER.search(line[:200]) and name == "segreto assegnato" and re.search(rb"(?i)(placeholder|esempio|example)", line): continue
            if name == "indirizzo e-mail" and IGN_MAIL.search(val): continue
            if name == "indirizzo di rete privato" and (re.search(r"_test\.|(^|/)tests?/|(^|/)testdata/", where) or (val.endswith(b".0") and data[m.end():m.end() + 1] == b"/")):
                sv, name2 = INFO, "indirizzo privato in prove/definizione di rete"   # dati di prova o intervalli (10.0.0.0/8), non host reali
            if name == "blocco base64 lungo (keystore? file incorporato?)" and len(set(val)) < 12: continue
            found.append((sv, name2, where, lineno, redact(val)))
    # la stessa riga già segnalata come chiave di myrmm non si ripete come «segreto assegnato»
    hi = {(w, l) for sv, n, w, l, e in found if n == "chiave/segreto di myrmm"}
    found[:] = [f for f in found if not (f[1] == "segreto assegnato" and (f[2], f[3]) in hi)]
    if not binary and terms:
        low = data.lower()
        for t in terms:
            i = low.find(t)
            while i >= 0:
                ls = data.rfind(b"\n", 0, i) + 1; le = data.find(b"\n", i); le = len(data) if le < 0 else le
                if b"scan:ok" not in data[ls:le]: found.append((MED, "termine riservato «%s»" % t.decode(), where, data.count(b"\n", 0, i) + 1, ""))
                i = low.find(t, i + len(t))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo"); ap.add_argument("--paths", nargs="*", default=[]); ap.add_argument("--terms"); ap.add_argument("--allow-path", nargs="*", default=[]); ap.add_argument("--max-mb", type=int, default=50)
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    git(repo, "rev-parse", "--git-dir")
    terms = [l.strip().lower().encode() for l in open(a.terms, encoding="utf-8") if l.strip() and not l.startswith("#")] if a.terms else []
    spec = ["--"] + a.paths if a.paths else []
    ncommit = len(git(repo, "rev-list", "--all", *spec, text=True).split())
    objs = {}   # blob -> percorsi
    for l in git(repo, "rev-list", "--objects", "--all", *spec, text=True).splitlines():
        if " " in l:
            h, p = l.split(" ", 1); objs.setdefault(h, set()).add(p)
        # i commit/tree senza percorso si ignorano
    # solo blob
    chk = subprocess.run(["git", "-C", repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"], input="\n".join(objs).encode(), capture_output=True).stdout.decode().splitlines()
    blobs = {}
    for l in chk:
        h, t, sz = l.split()
        if t == "blob": blobs[h] = int(sz)
    found = []; skipped = []; nbytes = 0
    for h, sz in blobs.items():
        paths = sorted(objs[h]); label = paths[0] + (" (+%d)" % (len(paths) - 1) if len(paths) > 1 else "") + " [%s]" % h[:7]
        if any(fnmatch.fnmatch(p, g) for p in paths for g in a.allow_path): continue
        for p in paths:
            if SECRET_FILES.search(p): found.append((HIGH, "file di chiavi/certificati nella storia", label, 0, os.path.basename(p)))
            elif DATA_FILES.search(p): found.append((MED, "file di dati/log/database nella storia", label, 0, os.path.basename(p) + " %d KB" % (sz // 1024)))
        if sz > a.max_mb * 1024 * 1024: skipped.append((label, sz)); continue
        data = subprocess.run(["git", "-C", repo, "cat-file", "blob", h], capture_output=True).stdout; nbytes += len(data)
        scan_bytes(data, label, terms, found)
    # messaggi e autori dei commit
    meta = git(repo, "log", "--all", "--format=@@%H%n%an <%ae>%n%cn <%ce>%n%B", *spec)
    for blk in meta.split(b"@@")[1:]:
        h = blk[:7].decode(); scan_bytes(blk[41:], "commit " + h, terms, found)
    authors = collections.Counter(l.decode("utf-8", "replace") for l in git(repo, "log", "--all", "--format=%an <%ae>", *spec).splitlines())
    # riepilogo
    uniq = collections.OrderedDict()
    for sev, name, where, ln, ex in found: uniq.setdefault((sev, name, where, ln, ex), 0); uniq[(sev, name, where, ln, ex)] += 1
    order = {HIGH: 0, MED: 1, INFO: 2}
    print("Repository: %s | commit esaminati: %d | versioni di file: %d | %.1f MB letti" % (repo, ncommit, len(blobs), nbytes / 1e6))
    if a.paths: print("Percorsi: " + ", ".join(a.paths))
    if skipped: print("NON letti perché oltre %d MB: %s" % (a.max_mb, "; ".join("%s %.0f MB" % (l, s / 1e6) for l, s in skipped[:8])))
    cnt = collections.Counter(k[0] for k in uniq)
    info = collections.OrderedDict()
    for sev, name, where, ln, ex in sorted(uniq, key=lambda k: (order[k[0]], k[1], k[2], k[3])):
        if sev == INFO: info.setdefault((name, ex), []).append(where); continue
        print("%-5s %-44s %s%s  %s" % (sev, name, where, (":%d" % ln) if ln else "", ex))
    for (name, ex), wh in info.items():   # le segnalazioni INFO uguali si raggruppano
        print("%-5s %-44s %s  in %d posti (es. %s)" % (INFO, name, ex, len(wh), ", ".join(wh[:2])))
    if authors: print("Autori nella storia: " + "; ".join("%s (%d)" % kv for kv in authors.most_common(6)))
    print("\nRiepilogo: ALTO %d, MEDIO %d, INFO %d" % (cnt[HIGH], cnt[MED], cnt[INFO]))
    sys.exit(1 if cnt[HIGH] or cnt[MED] else 0)


if __name__ == "__main__":
    main()
