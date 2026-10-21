#!/usr/bin/env python3
"""Esporta da server/index.php gli script di libreria «myrmm MCP: installa/rimuovi su Windows» in ci/fixtures/, con i segnaposto
{{NOME|linea}} ancora al loro posto: li usa ci/windows_install_test.py (anche nel repository pubblico, che non ha il server).
Uso: python3 ci/export_install_scripts.py [--check]   (--check: esce con 1 se i file esportati non coincidono col server)"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "server", "index.php"), encoding="utf-8").read()
OUT = os.path.join(ROOT, "ci", "fixtures")
FILES = {"mcpWin": "mcp-install-windows.ps1", "mcpRmWin": "mcp-remove-windows.ps1", "mcpDesktopWin": "mcp-desktop-windows.ps1"}
bad = 0
for var, name in FILES.items():
    m = re.search(r"\$%s = <<<'PS'\n(.*?)\nPS;" % var, SRC, re.S)
    assert m, var
    text = m.group(1) + "\n"; p = os.path.join(OUT, name)
    if "--check" in sys.argv:
        cur = open(p, encoding="utf-8").read() if os.path.isfile(p) else None
        if cur != text: print("DIVERSO dal server: ci/fixtures/" + name + " (rilancia ci/export_install_scripts.py)"); bad = 1
    else:
        os.makedirs(OUT, exist_ok=True); open(p, "w", encoding="utf-8", newline="\n").write(text); print("scritto ci/fixtures/" + name)
sys.exit(bad)
