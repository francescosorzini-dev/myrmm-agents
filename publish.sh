#!/usr/bin/env bash
# Pubblica questo repository SOLO se la scansione dei segreti sulla storia che verrà pubblicata è pulita.
# Uso: ./publish.sh https://github.com/<utente>/<repo>.git        (il repository remoto deve esistere ed essere vuoto)
# Facoltativo: SCAN_TERMS=/percorso/termini.txt  (nomi di clienti, domini interni: una parola per riga; il file resta fuori dal repository)
set -euo pipefail
cd "$(dirname "$0")"
REMOTE=${1:?uso: ./publish.sh https://github.com/<utente>/<repo>.git}
[ -z "$(git status --porcelain)" ] || { echo "ci sono modifiche non committate: committa o annulla prima" >&2; exit 1; }
python3 ci/scan_secrets_test.py >/dev/null
echo "== scansione dei segreti su tutta la storia che verrà pubblicata =="
python3 ci/scan_secrets.py . --allow-path ci/scan_secrets_test.py ${SCAN_TERMS:+--terms "$SCAN_TERMS"}
echo
git log --format='%h %an <%ae> %s' | head -20
read -r -p "La scansione è pulita. Pubblico su $REMOTE ? (scrivi: si) " ok
[ "$ok" = si ] || { echo "annullato"; exit 1; }
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE"
git push -u origin main
