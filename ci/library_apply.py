#!/usr/bin/env python3
"""Esegue su un sistema vero (Linux, macOS o Windows) gli scenari esportati da ci/export_apply.py: script di libreria che MODIFICANO lo stato
(file, registro, firewall, servizi, utenti…), ciascuno seguito da una verifica fatta con comandi nativi. Gli script girano come li fa l'agent.
Uso: python3 ci/library_apply.py CARTELLA      Uscita 1 se qualcosa non va. Con GITHUB_ACTIONS scrive anche le annotazioni."""
import base64, json, os, platform, shutil, subprocess, sys, tempfile
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
d = sys.argv[1]; SYS = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[platform.system()]
KIND = "windows" if SYS == "windows" else "unix"
PFX = "$ProgressPreference='SilentlyContinue'; try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }; "
# l'agent gira come servizio, senza il PSModulePath di PowerShell 7 che il runner passa ai processi figli (romperebbe i moduli di Windows PowerShell 5.1)
ENV = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
ok = bad = 0
def native(code, timeout=300):
    if SYS == "windows":
        enc = base64.b64encode((PFX + code + "\nexit 0").encode("utf-16-le")).decode()
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", enc]
    else:
        f = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8"); f.write(code + "\n"); f.close()
        cmd = ([] if os.geteuid() == 0 else ["sudo", "-n"]) + ["bash", f.name]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=ENV)
    return r.returncode, (r.stdout + r.stderr)
def verify_ps(code):
    """per il codice di verifica PowerShell: «exit 1» esplicito = fallita; la riga finale exit 0 è aggiunta da native()"""
    return native(code)
def run_script(text, timeout=600):
    if SYS == "windows":
        enc = base64.b64encode((PFX + text).encode("utf-16-le")).decode()
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", enc]
    else:
        f = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8"); f.write(text); f.close()
        cmd = ([] if os.geteuid() == 0 else ["sudo", "-n"]) + ["bash", f.name]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=ENV)
    return r.returncode, (r.stdout + r.stderr)
def fail(label, why, out):
    global bad
    bad += 1; print(f"  FALLITO {label}: {why}"); print("          " + out.strip()[:900].replace("\n", "\n          "))
    if os.environ.get("GITHUB_ACTIONS"): print("::error title=%s::%s" % (label.replace(",", ";")[:100], (why + " " + out.strip()[:600]).replace("\r", " ").replace("\n", "%0A")))
for sc in json.load(open(os.path.join(d, "scenari.json"), encoding="utf-8")):
    if sc["os"] != KIND or (sc.get("only") and sc["only"] != SYS): continue
    print("==", sc["nome"]); good = True
    try:
        for i, p in enumerate(sc["passi"], 1):
            if "code" in p:
                rc, out = native(p["code"]) if SYS == "windows" else native(p["code"])
                label = f"{sc['nome']} · passo {i} (verifica)"
                if rc != p.get("rc", 0): fail(label, f"uscita {rc}", out + "\n" + p["code"][:300]); good = False; break
                continue
            label = f"{sc['nome']} · passo {i} ({p['run'][:50]})"
            rc, out = run_script(p["script"])
            why = []
            if rc != p.get("rc", 0): why.append(f"uscita {rc} (attesa {p.get('rc', 0)})")
            why += [f"manca «{s}»" for s in p.get("has", []) if s not in out]
            why += [f"non doveva contenere «{s}»" for s in p.get("hasnot", []) if s in out]
            if why: fail(label, "; ".join(why), out); good = False; break
            print(f"  ok   passo {i}: {p['run'][:60]} (uscita {rc})")
    finally:
        if sc.get("cleanup"):
            try: native(sc["cleanup"])
            except Exception as e: print("  (pulizia non riuscita:", e, ")")
    if good: ok += 1
print(f"\n{SYS}: {ok} scenari riusciti, {bad} falliti")
if os.environ.get("GITHUB_ACTIONS"): print(f"::notice title=Scenari di modifica su {SYS}::{ok} riusciti, {bad} falliti")
sys.exit(1 if bad else 0)
