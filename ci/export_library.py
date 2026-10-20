#!/usr/bin/env python3
"""Esporta gli script della libreria per temi come file pronti da eseguire, per provarli su sistemi veri (ci/library_run.py).
Il testo è quello che il server semina; i segnaposto sono sostituiti come fa il server (materialize) con i valori «#@ sample» dello script
(le variabili senza esempio restano vuote, quindi gli script che cancellano girano in anteprima).
Uso: python3 ci/export_library.py CARTELLA [--all]    (senza --all: solo gli script di sola lettura e quelli con anteprima)"""
import json, os, re, subprocess, sys, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, HERE)
import libseed
out = sys.argv[1]; allx = "--all" in sys.argv
meta = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_library.py"), "--json"], capture_output=True, text=True, check=True).stdout)
rows, tmp, _ = libseed.seeded(port=8796)
rows = [r for r in rows if r["name"] in meta]
items = []
for r in rows:
    m = meta[r["name"]]; tg = m["tags"]
    if not allx and not ("sola-lettura" in tg or ("distruttivo" in tg and "{{APPLICA}}" in r["body"])): continue
    items.append((r, m))
mats = libseed.php_materialize([(r["body"], {v: m["samples"].get(v, "") for v in re.findall(r"\{\{\s*([A-Za-z_]\w*)", r["body"])}, "windows" if r["platform"] == "windows" else "unix") for r, m in items], tmp)
shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
man = []
for i, ((r, m), body) in enumerate(zip(items, mats)):
    ext = "ps1" if r["platform"] == "windows" else "sh"; fn = f"{i:03d}.{ext}"
    open(os.path.join(out, fn), "w", encoding="utf-8", newline="\n").write(body + "\n")
    man.append(dict(file=fn, name=r["name"], os=m["os"], tags=tg, expect=[int(x) for x in m["expect"].split(",")], timeout=min(int(r["timeout"]), 300)))
json.dump(man, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
shutil.rmtree(tmp, ignore_errors=True)
print(f"{len(man)} script esportati in {out}")
