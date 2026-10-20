#!/usr/bin/env python3
"""Esporta gli scenari di ci/apply_scenarios.py con gli script già materializzati (segnaposto sostituiti come fa il server), pronti per ci/library_apply.py.
Uso: python3 ci/export_apply.py CARTELLA"""
import json, os, re, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import libseed, apply_scenarios as A
out = sys.argv[1]
rows, tmp, _ = libseed.seeded(port=8797)
BY = {r["name"]: r for r in rows}
jobs = []; refs = []
for s in A.SCENARI:
    for p in s["passi"]:
        if "run" in p:
            r = BY[p["run"]]  # KeyError = nome sbagliato nello scenario
            vs = {v: "" for v in re.findall(r"\{\{\s*([A-Za-z_]\w*)", r["body"])}
            for k in p.get("vars", {}):
                assert k in vs, f"{p['run']}: variabile {k} inesistente"
            vs.update(p.get("vars", {}))
            jobs.append((r["body"], vs, "windows" if r["platform"] == "windows" else "unix")); refs.append(p)
mats = libseed.php_materialize(jobs, tmp)
for p, m in zip(refs, mats): p["script"] = m
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
json.dump([dict(nome=s["nome"], os="windows" if s["os"] == A.W else "unix", only=s["only"], passi=s["passi"], cleanup=s["cleanup"]) for s in A.SCENARI], open(os.path.join(out, "scenari.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{len(A.SCENARI)} scenari esportati in {out}")
