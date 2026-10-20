#!/usr/bin/env python3
"""Esegue sul sistema in cui gira (Linux, macOS o Windows) gli script della libreria esportati da ci/export_library.py e controlla che
  - l'uscita sia tra quelle attese (di solito 0 = tutto bene, 1 = il monitor ha trovato qualcosa),
  - non compaiano errori dell'interprete (comando non trovato, opzione non valida, errore di sintassi, eccezioni PowerShell…),
  - lo script scriva qualcosa.
Gli script girano come li fa l'agent: sh/bash su Linux e macOS (da root, se possibile), powershell.exe -EncodedCommand su Windows.
Uso: python3 ci/library_run.py CARTELLA [--shell bash|sh|dash]      Uscita 1 se qualcosa non va. Con GITHUB_ACTIONS scrive anche le annotazioni."""
import base64, json, os, platform, re, shutil, subprocess, sys, time
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
d = sys.argv[1]; man = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
SYS = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[platform.system()]
shells = [sys.argv[sys.argv.index("--shell") + 1]] if "--shell" in sys.argv else (["bash"] + ([s for s in ("dash",) if shutil.which(s)]) if SYS == "linux" else ["bash", "sh"])
ERR_SH = re.compile(r"command not found|syntax error|Illegal option|illegal option|bad substitution|unbound variable|invalid option|unrecognized option|unknown option|: not found|cannot execute|Segmentation|Bad file descriptor", re.I)
ERR_PS = re.compile(r"is not recognized as the name|CategoryInfo|FullyQualifiedErrorId|ParserError|At line:\d|Cannot bind|Cannot convert|Exception calling|Unexpected token|Missing (closing|expression)|The term '", re.I)
# l'agent gira come servizio, senza il PSModulePath di PowerShell 7 che il runner passa ai processi figli (romperebbe i moduli di Windows PowerShell 5.1)
ENV = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
ok = bad = skipped = 0; fails = []
def run_one(it, sh):
    f = os.path.join(d, it["file"])
    if SYS == "windows":
        script = "$ProgressPreference='SilentlyContinue'; try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }; " + open(f, encoding="utf-8").read()
        enc = base64.b64encode(script.encode("utf-16-le")).decode()
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", enc]
    else:
        cmd = ([] if os.geteuid() == 0 else (["sudo", "-n"] if shutil.which("sudo") else [])) + [sh, f]
    t0 = time.time()
    try: r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=it["timeout"], stdin=subprocess.DEVNULL, env=ENV)
    except subprocess.TimeoutExpired: return None, "", "timeout", time.time() - t0
    return r.returncode, r.stdout, r.stderr, time.time() - t0
for it in man:
    if SYS not in it["os"]: skipped += 1; continue
    for sh in (shells if SYS != "windows" else [None]):
        rc, out, err, dt = run_one(it, sh)
        why = []
        if rc is None: why.append("timeout")
        elif rc not in it["expect"]: why.append(f"uscita {rc} (attese {it['expect']})")
        if rc is not None:
            if not (out.strip() or err.strip()): why.append("nessun output")
            pat = ERR_PS if SYS == "windows" else ERR_SH
            m = pat.search(out + "\n" + err)
            if m: why.append("errore dell'interprete: " + (out + "\n" + err)[max(0, m.start() - 80):m.end() + 120].replace("\n", " | "))
        label = f"{it['name']}" + (f" [{sh}]" if sh else "")
        if why:
            bad += 1; fails.append(label); print(f"  FALLITO {label}: {'; '.join(why)}"); print("          " + (out + err).strip()[:700].replace("\n", "\n          "))
            if os.environ.get("GITHUB_ACTIONS"): print("::error title=%s::%s" % (label.replace(",", ";"), ("; ".join(why) + " " + (out + err).strip()[:500]).replace("\r", " ").replace("\n", "%0A")))
        else:
            ok += 1; print(f"  ok   {label}  ({dt:.1f}s, uscita {rc})")
print(f"\n{SYS}: {ok} ok, {bad} falliti, {skipped} saltati (altro sistema)")
if os.environ.get("GITHUB_ACTIONS"): print(f"::notice title=Libreria script su {SYS}::{ok} riusciti, {bad} falliti, {skipped} saltati")
sys.exit(1 if bad else 0)
