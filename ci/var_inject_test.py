#!/usr/bin/env python3
"""Iniezione tramite le variabili {{NOME}} degli script (1.54.2): un valore ostile non deve mai diventare codice.

1) Casi mirati per contesto (PowerShell e sh): apici singoli, virgolette, here-string/here-document, commenti, sottoespressioni, codice.
2) TUTTI gli script della libreria, così come vengono seminati dal server: ogni variabile riceve una serie di valori ostili e lo script
   materializzato viene analizzato (PowerShell: albero sintattico di pwsh; sh: bashlex, se installato; altrimenti dash -n). Il numero di comandi
   e di istruzioni deve restare quello del valore innocuo, e non devono comparire errori di sintassi nuovi: un valore che entra in una
   stringa resta una stringa. Se un valore non può entrare in sicurezza lo script diventa un rifiuto («myrmm: script non eseguito»).
Serve php; pwsh e bashlex sono facoltativi (senza, quella parte salta). Uso: python3 ci/var_inject_test.py"""
import json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "server", "index.php"), encoding="utf-8").read()
ok = bad = 0
def check(n, c, x=""):
    global ok, bad
    if c: ok += 1; print("  ok   ", n)
    else: bad += 1; print("  FALLITO", n, str(x)[:600])

PWSH = shutil.which("pwsh") or shutil.which("powershell")
try:
    import bashlex
except Exception:
    bashlex = None
tmp = tempfile.mkdtemp(prefix="myrmm-vi-")

# ---- funzioni da prova: estratte dal server --------------------------------------------------------------------------------------
a = SRC.index("class VarUnsafe extends RuntimeException {}")
b = SRC.index("/**\n * Valuta le schedule scadute")
open(os.path.join(tmp, "fn.php"), "w", encoding="utf-8").write("<?php\n" + SRC[a:b])
open(os.path.join(tmp, "h.php"), "w", encoding="utf-8").write(
    "<?php\nrequire __DIR__ . '/fn.php';\n$in = json_decode(stream_get_contents(STDIN), true);\n"
    "echo json_encode(array_map(fn($c) => materialize($c[0], $c[1], $c[2] ?? ''), $in), JSON_UNESCAPED_UNICODE);\n")
def mat(items):
    r = subprocess.run(["php", os.path.join(tmp, "h.php")], input=json.dumps(items), capture_output=True, text=True, timeout=120)
    if r.returncode: raise SystemExit("php: " + r.stderr[:500])
    return json.loads(r.stdout)
def one(body, **v): return mat([[body, v, ""]])[0]

# ---- 1) casi mirati --------------------------------------------------------------------------------------------------------------
print("== casi mirati")
P = "'; Invoke-Pwned1; '"
check("ps: 'X' raddoppia gli apici", one("$a = '{{X}}'\n", X=P) == "$a = '''; Invoke-Pwned1; '''\n")
check("ps: apici tipografici raddoppiati", one("$a = '{{X}}'\n", X="a\u2019b") == "$a = 'a\u2019\u2019b'\n")
check("ps: \"X\" protegge ` $ \"", one('$a = "{{X}}"\n', X='a$(x)`"b') == '$a = "a`$(x)``"b"\n'.replace('``"', '```"'))
check("ps: \"X\" virgolette tipografiche", one('$a = "{{X}}"\n', X="\u201d; x") == '$a = "`\u201d; x"\n')
check("ps: valore semplice nel codice resta com'è", one("$s = {{X}}\n", X="90") == "$s = 90\n")
check("ps: valore ostile nel codice diventa stringa", one("$s = {{X}}\n", X="1; Invoke-Pwned1") == "$s = '1; Invoke-Pwned1'\n")
check("ps: valore vuoto nel codice", one("$s = {{X}}\n", X="") == "$s = ''\n")
check("ps: commento: a capo diventano spazi", one("# {{X}}\nOK\n", X="a\nInvoke-Pwned1") == "# a Invoke-Pwned1\nOK\n")
check("ps: commento a blocco non si chiude", one("<# {{X}} #>\n", X="x #> Invoke-Pwned1 <#") == "<# x # > Invoke-Pwned1 <# #>\n")
check("ps: here-string letterale, a capo → spazio", one("$a = @'\n{{X}}\n'@\n", X="a\nb") == "$a = @'\na b\n'@\n")
r = one("$a = @'\n{{X}}\n'@\n", X="'@\nInvoke-Pwned1")
check("ps: here-string, valore che la chiude → script rifiutato", r.startswith("Write-Output 'myrmm: script non eseguito") and "Pwned" not in r.split("\n")[1], r)
check("ps: sottoespressione dentro virgolette: apici interni", one('"x $(Get-A \'{{X}}\') y"\n', X="a'b") == '"x $(Get-A \'a\'\'b\') y"\n')
check("ps: dopo una stringa si torna al codice", one("$a = 'x' ; $b = {{X}}\n", X="1; Invoke-Pwned1") == "$a = 'x' ; $b = '1; Invoke-Pwned1'\n")
check("ps: '' dentro una stringa non la chiude", one("$a = 'it''s {{X}}'\n", X="'") == "$a = 'it''s '''\n")
check("ps: backtick-apice non apre una stringa", one("Write-Output `'{{X}}\n", X="a b") == "Write-Output `''a b'\n")
check("sh: 'X' → '\\''", one("#!/bin/sh\nA='{{X}}'\n", X="a'; touch /tmp/pwn; '") == "#!/bin/sh\nA='a'\\''; touch /tmp/pwn; '\\'''\n")
check("sh: \"X\" protegge $ ` \" \\", one('#!/bin/sh\nA="{{X}}"\n', X='$(x)`y`"\\') == '#!/bin/sh\nA="\\$(x)\\`y\\`\\"\\\\"\n')
check("sh: codice, valore semplice", one("#!/bin/sh\nsystemctl restart {{X}}\n", X="nginx") == "#!/bin/sh\nsystemctl restart nginx\n")
check("sh: codice, valore ostile tra apici", one("#!/bin/sh\nsystemctl restart {{X}}\n", X="a; touch /tmp/pwn") == "#!/bin/sh\nsystemctl restart 'a; touch /tmp/pwn'\n")
check("sh: heredoc letterale, a capo → spazio", one("#!/bin/sh\ncat <<'EOF'\n{{X}}\nEOF\n", X="a\nb") == "#!/bin/sh\ncat <<'EOF'\na b\nEOF\n")
r = one("#!/bin/sh\ncat <<'EOF'\n{{X}}\nEOF\n", X="EOF")
check("sh: heredoc, valore uguale al delimitatore → rifiutato", "myrmm: script non eseguito" in r and "cat" not in r, r)
check("sh: heredoc non quotato protegge $ ` \\", one("#!/bin/sh\ncat <<EOF\nA={{X}}\nEOF\n", X="$(x)`y`") == "#!/bin/sh\ncat <<EOF\nA=\\$(x)\\`y\\`\nEOF\n")
check("sh: commento, a capo → spazio", one("#!/bin/sh\n# {{X}}\necho ok\n", X="a\ntouch /tmp/pwn") == "#!/bin/sh\n# a touch /tmp/pwn\necho ok\n")
check("sh: dopo il heredoc si torna al codice", one("#!/bin/sh\ncat <<'EOF'\nx\nEOF\nrm {{X}}\n", X="a b") == "#!/bin/sh\ncat <<'EOF'\nx\nEOF\nrm 'a b'\n")
check("sh: sottoshell dentro virgolette", one('#!/bin/sh\necho "$(cat \'{{X}}\')"\n', X="a'b") == '#!/bin/sh\necho "$(cat \'a\'\\\'\'b\')"\n')
check("{{NOME|linea}} toglie gli a capo prima del resto", one("$a = '{{X|linea}}'\n", X="a\r\nb") == "$a = 'a b'\n")
check("i valori non vengono riesaminati ({{...}} dentro un valore)", one("$a = '{{X}}'\n", X="{{Y}}", Y="zz") == "$a = '{{Y}}'\n")
check("script senza placeholder: invariato", one("Write-Output 'ciao'\n") == "Write-Output 'ciao'\n")

# ---- 2) tutta la libreria --------------------------------------------------------------------------------------------------------
print("== libreria completa")
PORT = 8799; srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data", "update")); os.makedirs(os.path.join(srv, "data"))
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": subprocess.run(["php", "-r", "echo password_hash('x', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip(), "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
DB = os.path.join(srv, "data", "myrmm.sqlite")
rows = []
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/index.php", timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/index.php?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"}), timeout=5)
    except Exception: pass
    for _ in range(60):
        try:
            rows = sqlite3.connect(DB).execute("SELECT id, name, body, platform FROM scripts ORDER BY id").fetchall()
            if rows: break
        except Exception: pass
        time.sleep(.3)
finally:
    sp.terminate()
check("libreria seminata dal server", len(rows) > 30, len(rows))
print("  script in libreria: %d" % len(rows))

PAYLOADS = [
    "'; Invoke-Pwned1; '", '"; Invoke-Pwned1; "', "$(Invoke-Pwned1)", "`$(Invoke-Pwned1)`", "\u2019; Invoke-Pwned1; \u2019", "\u201d; Invoke-Pwned1; \u201c",
    "a\nInvoke-Pwned1\nb", "'@\nInvoke-Pwned1\n'@", '"@; Invoke-Pwned1', "; Invoke-Pwned1 ;", "x | Invoke-Pwned1", "x & Invoke-Pwned1", "x && Invoke-Pwned1",
    "$(touch /tmp/pwn)", "`touch /tmp/pwn`", "x' ; touch /tmp/pwn ; '", 'x" ; touch /tmp/pwn ; "', "EOF", "PS", "SH", "\nEOF\ntouch /tmp/pwn", "x\\", "#", "x #> Invoke-Pwned1 <# y",
    "}; Invoke-Pwned1; {", ") ; Invoke-Pwned1 ; (", "-Force", "..\\..\\x", "a b c",
]
BENIGN = "abc"
def vars_of(body): return sorted(set(re.findall(r"\{\{\s*([A-Za-z_]\w*)\s*(?:\|\s*linea\s*)?\}\}", body)))
items = []; meta = []
for sid, name, body, plat in rows:
    vs = vars_of(body)
    if not vs: continue
    for kind in (["windows", "unix"] if plat == "any" else [plat]):
        sh = body.startswith("#!") or kind == "unix"
        items.append([body, {v: BENIGN for v in vs}, kind]); meta.append((sid, name, "benigno", sh))
        for i, pl in enumerate(PAYLOADS):
            items.append([body, {v: pl for v in vs}, kind]); meta.append((sid, name, i, sh))
res = mat(items)
print("  materializzazioni: %d (script con variabili: %d)" % (len(res), len({m[0] for m in meta})))
from collections import Counter
REFUSED = "myrmm: script non eseguito"

# PowerShell: albero sintattico
AST = r'''param($In, $Out)
$items = Get-Content -Raw -Encoding UTF8 $In | ConvertFrom-Json
$o = @()
foreach ($it in $items) {
  $t = $null; $e = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseInput($it.text, [ref]$t, [ref]$e)
  $cmds = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true))
  $sts = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.StatementAst] }, $true))
  $names = @($cmds | ForEach-Object { $_.GetCommandName() })
  $o += [pscustomobject]@{ k = $it.k; cmds = $cmds.Count; sts = $sts.Count; err = @($e).Count; pwned = [bool]($names -match 'Pwned') }
}
$o | ConvertTo-Json -Compress -AsArray | Set-Content -Encoding UTF8 $Out
'''
ps_idx = [i for i, m in enumerate(meta) if not m[3]]
def ps_audit(res, quiet=False):
    """Analizza con pwsh gli script PowerShell materializzati. Ritorna (violazioni, rifiutati)."""
    inf = os.path.join(tmp, "in.json"); outf = os.path.join(tmp, "out.json"); scr = os.path.join(tmp, "ast.ps1")
    open(scr, "w", encoding="utf-8-sig").write(AST)
    open(inf, "w", encoding="utf-8").write(json.dumps([{"k": i, "text": res[i]} for i in ps_idx]))
    r = subprocess.run([PWSH, "-NoProfile", "-File", scr, inf, outf], capture_output=True, text=True, timeout=1500)
    if r.returncode: print(r.stdout[-500:], r.stderr[-500:])
    ast = {d["k"]: d for d in json.load(open(outf, encoding="utf-8-sig"))}
    base = {(meta[i][0], meta[i][3]): ast[i] for i in ps_idx if meta[i][2] == "benigno"}
    nrefused = nbad = 0; shown = 0
    for i in ps_idx:
        sid, name, pl, _ = meta[i]
        if pl == "benigno": continue
        if res[i].startswith("Write-Output '" + REFUSED): nrefused += 1; continue
        d, bs = ast[i], base[(sid, False)]
        if d["pwned"] or d["cmds"] != bs["cmds"] or d["sts"] != bs["sts"] or d["err"] > bs["err"]:
            nbad += 1
            if shown < 8 and not quiet: shown += 1; print("  ! %s · valore %r: comandi %d/%d istruzioni %d/%d errori %d/%d pwned=%s" % (name, PAYLOADS[pl], d["cmds"], bs["cmds"], d["sts"], bs["sts"], d["err"], bs["err"], d["pwned"]))
    return nbad, nrefused
if PWSH and ps_idx:
    nbad, nrefused = ps_audit(res)
    check("PowerShell: nessun valore ostile diventa codice (%d script, %d rifiutati)" % (len({m[0] for m in meta if not m[3]}), nrefused), nbad == 0, "%d violazioni" % nbad)
    # controllo negativo: con la vecchia sostituzione testuale il test DEVE trovare violazioni (altrimenti non misura niente)
    open(os.path.join(tmp, "fn.php"), "w", encoding="utf-8").write("<?php\nfunction materialize($b, $v, $p = '') { return preg_replace_callback('/\\{\\{\\s*([A-Za-z_]\\w*)\\s*(\\|\\s*linea\\s*)?\\}\\}/', fn($m) => (string)($v[$m[1]] ?? ''), $b); }\n")
    naive = mat(items)
    nb, _ = ps_audit(naive, quiet=True)
    check("controllo negativo: la vecchia sostituzione testuale viene smascherata (%d violazioni su PowerShell)" % nb, nb > 100, nb)
else:
    print("  pwsh non disponibile: salto la parte PowerShell")

# sh: bashlex
def count_sh(text):
    def walk(n):
        c = 0
        if getattr(n, "kind", "") == "command": c += 1
        for k in ("parts", "list", "command", "output"):
            v = getattr(n, k, None)
            if isinstance(v, list): c += sum(walk(x) for x in v if hasattr(x, "kind"))
            elif hasattr(v, "kind"): c += walk(v)
        return c
    # bashlex non conosce tutto: si passa per riga logica; se non analizza, None
    try: parts = bashlex.parse(text)
    except Exception: return None
    return sum(walk(p) for p in parts)
sh_idx = [i for i, m in enumerate(meta) if m[3]]
if bashlex and sh_idx:
    base = {}; skipped = set()
    for i in sh_idx:
        if meta[i][2] == "benigno":
            c = count_sh(res[i])
            if c is None: skipped.add(meta[i][0])
            else: base[meta[i][0]] = c
    nbad = nrefused = nchk = 0; shown = 0
    for i in sh_idx:
        sid, name, pl, _ = meta[i]
        if pl == "benigno" or sid in skipped: continue
        if REFUSED in res[i]: nrefused += 1; continue
        c = count_sh(res[i]); nchk += 1
        if c is None or c != base[sid]:
            nbad += 1
            if shown < 8: shown += 1; print("  ! %s · valore %r: comandi %s/%s" % (name, PAYLOADS[pl], c, base[sid]))
    from collections import Counter
    rf = Counter(PAYLOADS[meta[i][2]] for i in sh_idx if meta[i][2] != "benigno" and REFUSED in res[i])
    print("  rifiuti sh per valore: " + "; ".join("%r ×%d" % kv for kv in rf.most_common()))
    check("sh: nessun valore ostile diventa codice (%d script analizzati, %d non analizzabili da bashlex, %d rifiutati)" % (len(base), len(skipped), nrefused), nbad == 0, "%d violazioni" % nbad)
elif sh_idx:
    print("  bashlex non installato: salto l'analisi degli script sh (pip install bashlex)")
BASH = shutil.which("bash")
def sh_dynamic(res, quiet=False):
    """Esegue ogni script sh materializzato con PATH vuoto: ogni comando esterno «non esiste» e viene solo registrato (command_not_found_handle).
    Se un valore ostile è diventato codice, il comando iniettato (Invoke-Pwned1, touch) compare nel registro. Nulla gira davvero."""
    d = tempfile.mkdtemp(prefix="myrmm-dyn-"); log = os.path.join(d, "log")
    open(os.path.join(d, "h.sh"), "w").write('command_not_found_handle() { printf "%s\\n" "$1" >> "' + log + '"; return 0; }\n')
    nbad = nrun = 0; shown = 0
    for i in sh_idx:
        sid, name, pl, _ = meta[i]
        if pl == "benigno" or REFUSED in res[i]: continue
        f = os.path.join(d, "s.sh"); open(f, "w").write(res[i]); open(log, "w").close(); nrun += 1
        try: subprocess.run([BASH, "--norc", f], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6, cwd=d,
                            env={"PATH": "/nonexistent", "BASH_ENV": os.path.join(d, "h.sh"), "HOME": d, "LANG": "C"})
        except subprocess.TimeoutExpired: pass
        got = open(log).read()
        if re.search(r"Pwned|^touch$", got, re.M):
            nbad += 1
            if shown < 8 and not quiet: shown += 1; print("  ! eseguito un comando iniettato: %s · valore %r" % (name, PAYLOADS[pl]))
    return nbad, nrun
if BASH and sh_idx:
    nbad, nrun = sh_dynamic(res)
    check("sh (prova dinamica, tutti gli script): nessun comando iniettato viene eseguito (%d esecuzioni)" % nrun, nbad == 0, "%d violazioni" % nbad)
    open(os.path.join(tmp, "fn.php"), "w", encoding="utf-8").write("<?php\nfunction materialize($b, $v, $p = '') { return preg_replace_callback('/\\{\\{\\s*([A-Za-z_]\\w*)\\s*(\\|\\s*linea\\s*)?\\}\\}/', fn($m) => (string)($v[$m[1]] ?? ''), $b); }\n")
    nb, _ = sh_dynamic(mat(items), quiet=True)
    check("controllo negativo sh: la vecchia sostituzione testuale viene smascherata (%d violazioni)" % nb, nb > 20, nb)
dash = shutil.which("bash") or shutil.which("sh")   # l'agent usa bash quando c'è (plat_unix.go)
if dash and sh_idx:   # sintassi: un valore ostile non deve rompere lo script (apici non chiusi, ecc.)
    nbad = 0; shown = 0
    for i in sh_idx:
        sid, name, pl, _ = meta[i]
        if REFUSED in res[i]: continue
        r = subprocess.run([dash, "-n"], input=res[i], capture_output=True, text=True)
        if r.returncode:
            nbad += 1
            if shown < 5: shown += 1; print("  ! sintassi sh %s · valore %r: %s" % (name, pl if pl == "benigno" else PAYLOADS[pl], r.stderr.strip()[:120]))
    check("sh: gli script restano sintatticamente validi con valori ostili", nbad == 0, "%d violazioni" % nbad)

print("\n%d ok, %d falliti" % (ok, bad)); sys.exit(1 if bad else 0)
