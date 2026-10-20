"""clixml_clean(): estrae la funzione da index.php e la prova con l'errore reale di Start-Service."""
import sys as _s
try: _s.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import re, subprocess, json, pathlib
src = (pathlib.Path(__file__).resolve().parent.parent / "server" / "index.php").read_text(encoding="utf-8")
m = re.search(r"function clixml_clean\(.*?\n}\n", src, re.S)
assert m, "clixml_clean non trovata"
sample = ('#< CLIXML\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04"><S S="Error">'
          "Start-Service : Impossibile avviare il servizio RustDesk sul computer &apos;.&apos;._x000D__x000A_</S>"
          '<S S="Error">At line:48 char:1_x000D__x000A_</S></Objs>')
code = m.group(0) + "\n$t=json_decode(stream_get_contents(STDIN),true);\nforeach($t as $x) echo json_encode(clixml_clean($x)),\"\\n\";\n"
import tempfile, os
tf = os.path.join(tempfile.mkdtemp(), "t.php"); open(tf, "w", encoding="utf-8").write("<?php\n" + code)
out = subprocess.run(["php", tf], input=json.dumps(["ok normale", "pre\n" + sample]), capture_output=True, text=True, encoding="utf-8", errors="replace")
assert out.returncode == 0, out.stderr
a, b = [json.loads(l) for l in out.stdout.splitlines()]
assert a == "ok normale"
assert "CLIXML" not in b and "<" not in b and "_x000" not in b, b
assert "Impossibile avviare il servizio RustDesk sul computer '.'" in b and "At line:48" in b and b.startswith("pre"), b
print("clixml_test OK")
