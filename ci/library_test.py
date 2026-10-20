#!/usr/bin/env python3
"""Controlli statici della libreria di script (1.55.0): etichette, documentazione, sintassi e regole di sicurezza.

Gira sul testo che il server semina davvero (php -S + SQLite), non sui file sorgente:
  - generatore: server/index.php combacia con library/ (tools/gen_library.py --check);
  - etichette: tutte nel vocabolario, sistema coerente con la piattaforma, almeno un tipo/rischio/area (anche per gli script storici);
  - script nuovi (library/): sh con bash -n, dash -n, shellcheck (POSIX) e bashlex; PowerShell con il parser di pwsh e un elenco di
    costrutti che Windows PowerShell 5.1 non conosce (ci/ps_analyze.ps1); niente comandi interattivi; segnaposto sempre tra apici;
    gli script che cancellano dati hanno la variabile APPLICA e un'anteprima; dimensione sotto il limite della riga di comando di Windows.
Serve php; pwsh, shellcheck e bashlex sono facoltativi (senza, quella parte salta con un avviso). Uso: python3 ci/library_test.py"""
import json, os, re, shutil, subprocess, sys, tempfile
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, HERE)
import libseed
ok = bad = 0
def check(n, c, x=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  FALLITO", n, str(x)[:700])
def section(t): print("==", t)

PWSH = shutil.which("pwsh"); SHELLCHECK = shutil.which("shellcheck"); DASH = shutil.which("dash"); BASH = shutil.which("bash")
try: import bashlex
except Exception: bashlex = None

section("generatore")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_library.py"), "--check"], capture_output=True, text=True)
check("server/index.php è aggiornato rispetto a library/", r.returncode == 0, r.stdout + r.stderr); print("  " + r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")

section("libreria seminata")
rows, tmp, _ = libseed.seeded()
check("libreria seminata dal server", len(rows) > 150, len(rows)); print("  script in libreria: %d" % len(rows))
names = [x["name"] for x in rows]; check("nomi univoci", len(names) == len(set(names)))
voc_src = open(os.path.join(ROOT, "server", "index.php"), encoding="utf-8").read()
a = voc_src.index("function script_tag_vocab(): array {"); b = voc_src.index("\n}\n", a)
VOC = {g.group(1): re.findall(r"'([a-z0-9-]+)' =>", g.group(2)) for g in re.finditer(r"'(Piattaforma|Tipo|Rischio|Area|Insieme)' => \[(.*?)\],\n", voc_src[a:b], re.S)}
ALL = {t for v in VOC.values() for t in v}
for x in rows:
    tg = [t for t in x["tags"].split(",") if t]; n = x["name"]
    check(f"{n}: etichette nel vocabolario", all(t in ALL for t in tg), tg)
    osx = [t for t in tg if t in VOC["Piattaforma"]]
    exp = {"windows": ["windows"], "unix": None, "any": ["windows", "linux", "macos"]}[x["platform"]]
    check(f"{n}: etichetta di sistema coerente con la piattaforma", bool(osx) and (("windows" in osx) == (x["platform"] in ("windows", "any"))) and (exp is None or sorted(osx) == sorted(exp)), (x["platform"], tg))
    check(f"{n}: ha un'etichetta di rischio", any(t in VOC["Rischio"] for t in tg), tg)
    check(f"{n}: ha un'etichetta di area", any(t in VOC["Area"] for t in tg), tg)
    check(f"{n}: un monitor è di sola lettura", "monitor" not in tg or "sola-lettura" in tg, tg)

# ---- script nuovi -------------------------------------------------------------------------------------------------------------------
gen = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_library.py"), "--list"], capture_output=True, text=True).stdout
newnames = set(re.findall(r"^(?:windows|unix)\s+(.*?)  \[", gen, re.M))
NEW = [x for x in rows if x["name"] in newnames]
section("script nuovi: %d" % len(NEW)); check("la libreria per temi è stata seminata", len(NEW) == len(newnames), (len(NEW), len(newnames)))
by = {}
for x in NEW:
    for t in x["tags"].split(","): by[t] = by.get(t, 0) + 1
print("  per sistema:", {k: by.get(k, 0) for k in ("windows", "linux", "macos")}, " per rischio:", {k: by.get(k, 0) for k in VOC["Rischio"]})

INTER_SH = re.compile(r"(^|[;&|(\s])(read\s+-p|vi|vim|nano|less|more|top|(?<!getent )passwd(?!\s+-|\s*\))|sudo\s+(?!-n))(\s|$)")
for x in NEW:
    n, body, tg = x["name"], x["body"], x["tags"].split(",")
    check(f"{n}: descrizione col tipo di effetto", ("sola-lettura" in tg and "Sola lettura" in x["description"]) or ("modifica" in tg and "Modifica" in x["description"]) or ("distruttivo" in tg and "anteprima" in x["description"] and "APPLICA" in x["description"]), x["description"][-120:])
    check(f"{n}: etichette distruttivo ⇒ variabile APPLICA con anteprima", "distruttivo" not in tg or "{{APPLICA}}" in body, tg)
    # segnaposto sempre tra apici (così il server li protegge nel contesto giusto)
    for m in re.finditer(r"\{\{\s*([A-Z_0-9]+)\s*(?:\|\s*linea\s*)?\}\}", body):
        pre = body[max(0, m.start() - 1):m.start()]
        if body[:m.start()].rsplit("\n", 1)[-1].lstrip().startswith("#"): continue
        check(f"{n}: {{{{{m.group(1)}}}}} tra apici", pre in ("'", '"'), body[max(0, m.start() - 30):m.end() + 5])
    if x["platform"] == "windows":
        check(f"{n}: sotto il limite della riga di comando di Windows ({len(body)} car.)", len(body) <= 9000, len(body))
        check(f"{n}: nessun comando interattivo (Read-Host…)", not re.search(r"(?i)\b(Read-Host|Get-Credential|Out-GridView|Show-Command)\b", body))
    else:
        code = "\n".join(l for l in body.split("\n") if not l.lstrip().startswith("#"))
        check(f"{n}: non interattivo", not INTER_SH.search(code), [l for l in code.split("\n") if INTER_SH.search(l)][:2])
        check(f"{n}: nessuna shebang (la scelta della shell è dell'agent)", not body.startswith("#!"))

section("sh: sintassi")
mat_dir = tempfile.mkdtemp(prefix="myrmm-lt-")
SH = [x for x in NEW if x["platform"] == "unix"]
vals = {}
mats = libseed.php_materialize([(x["body"], {v: "abc" for v in re.findall(r"\{\{\s*([A-Z_0-9]+)", x["body"])}, "unix") for x in SH], mat_dir) if SH else []
for x, m in zip(SH, mats):
    n = x["name"]; f = os.path.join(mat_dir, re.sub(r"\W+", "_", n) + ".sh"); open(f, "w", encoding="utf-8").write(m + "\n")
    for sh in (BASH, DASH):
        if sh:
            r = subprocess.run([sh, "-n", f], capture_output=True, text=True); check(f"{n}: {os.path.basename(sh)} -n", r.returncode == 0, r.stderr)
    if SHELLCHECK:
        r = subprocess.run([SHELLCHECK, "-s", "sh", "-S", "warning", "-e", "SC2034,SC2039,SC3043,SC2181,SC2015,SC2012,SC2155,SC2016,SC1091,SC2086", "-f", "gcc", f], capture_output=True, text=True)
        check(f"{n}: shellcheck", r.returncode == 0, r.stdout[:600])
if not SHELLCHECK: print("  (shellcheck assente: salto)")

section("PowerShell: parser e compatibilità con 5.1")
WIN = [x for x in NEW if x["platform"] == "windows"]
if PWSH and WIN:
    mats = libseed.php_materialize([(x["body"], {v: "abc" for v in re.findall(r"\{\{\s*([A-Z_0-9]+)", x["body"])}, "windows") for x in WIN], mat_dir)
    jin = os.path.join(mat_dir, "ps_in.json"); jout = os.path.join(mat_dir, "ps_out.json")
    json.dump([{"name": x["name"], "body": m} for x, m in zip(WIN, mats)], open(jin, "w", encoding="utf-8"))
    env = dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT="1")
    r = subprocess.run([PWSH, "-NoProfile", "-File", os.path.join(HERE, "ps_analyze.ps1"), jin, jout], capture_output=True, text=True, timeout=600, env=env)
    check("analisi PowerShell eseguita", r.returncode == 0 and os.path.exists(jout), r.stdout + r.stderr)
    if os.path.exists(jout):
        res = json.load(open(jout, encoding="utf-8-sig")); res = [res] if isinstance(res, dict) else res
        check("tutti gli script analizzati", len(res) == len(WIN), (len(res), len(WIN)))
        for e in res:
            pr = e["problems"] if isinstance(e["problems"], list) else ([e["problems"]] if e["problems"] else [])
            check(f"{e['name']}: sintassi e compatibilità 5.1", not pr, pr)
else: print("  (pwsh assente o nessuno script Windows: salto)")

shutil.rmtree(mat_dir, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
print("\n%d ok, %d falliti" % (ok, bad)); sys.exit(1 if bad else 0)
