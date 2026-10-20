#!/usr/bin/env python3
"""Prova la sonda PowerShell dei backup (serve pwsh; senza, salta). Estrae lo script da server/index.php: si prova il testo che viene davvero distribuito.
Verifica: lettura dei file di log (ultime ore, data nella riga, formato, file più recente), script utente, errori gestiti,
configurazione con apici e caratteri speciali che non esce dal base64."""
import base64, calendar, json, os, re, shutil, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'server', 'index.php'), encoding='utf-8').read()
PW = next((x for x in ('pwsh', 'powershell', '/opt/pwsh/pwsh') if shutil.which(x) or os.path.exists(x)), None)
if not PW: print('pwsh non disponibile: salto'); sys.exit(0)
TPL = re.search(r"function bk_ps\(\): string \{ return <<<'EOPS'\n(.*?)\nEOPS;", SRC, re.S).group(1)
ok = bad = 0
def check(n, c, x=''):
    global ok, bad
    if c: ok += 1; print('  ok   ', n)
    else: bad += 1; print('  FALLITO', n, str(x)[:400])
def run(tools, full=True):
    cfg = base64.b64encode(json.dumps({'full': full, 'tools': tools}).encode()).decode()
    f = os.path.join(tempfile.mkdtemp(), 'p.ps1'); open(f, 'w', encoding='utf-8-sig').write(TPL.replace('@@CFG@@', cfg))
    r = subprocess.run([PW, '-NoProfile', '-File', f], capture_output=True, text=True, timeout=120)
    out = r.stdout.strip()
    m = re.search(r'MYRMM_BK (\{.*\})', out)
    return r.returncode, (json.loads(m.group(1)) if m else None), (r.stdout + r.stderr)
d = tempfile.mkdtemp(); fmt = '%Y-%m-%d %H:%M:%S'
def t(h): return time.strftime(fmt, time.localtime(time.time() - h * 3600))
open(os.path.join(d, 'a.log'), 'w').write(f"{t(70)} Job completed OK old\n{t(5)} Job completed OK recent\n{t(2)} Job FAILED disk full\n{t(1)} noise\n")
open(os.path.join(d, 'b.log'), 'w', encoding='utf-16').write(f"{t(3)} Job completed utf16\n")
lg = lambda role, pat, **k: dict({'type': 'logfile', 'role': role, 'path': os.path.join(d, '*.log'), 'pattern': pat, 'ts_regex': r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', 'ts_format': 'yyyy-MM-dd HH:mm:ss', 'tail_kb': 64, 'files': 3, 'lookback_h': 48}, **k)
code, j, raw = run([{'id': 1, 'checks': [lg('success', 'completed'), lg('failure', 'FAILED'), lg('success', 'nothing-matches'), dict(lg('success', 'x'), path=os.path.join(d, 'none*.zzz'))]}])
check('esce con codice 0 e restituisce JSON', code == 0 and j is not None, raw)
cs = (j or {'tools': [{'checks': []}]})['tools'][0]['checks']
check('file di log: ultima riga di successo (5 ore fa, non quella vecchia)', len(cs) == 4 and cs[0]['ts'] and 'recent' in cs[0]['msg'] or 'utf16' in cs[0]['msg'], cs[:1])
age = lambda s: (time.time() - calendar.timegm(time.strptime(s, '%Y-%m-%dT%H:%M:%SZ'))) / 3600 if s else None
check('data letta dalla riga (formato dato)', cs[0]['ts'] and 2.5 < age(cs[0]['ts']) < 5.5, (cs[0]['ts'], age(cs[0]['ts']) if cs[0]['ts'] else None))
check('riga di fallimento con data 2 ore fa', cs[1]['ts'] and 1.5 < age(cs[1]['ts']) < 2.5 and 'FAILED' in cs[1]['msg'], cs[1])
check('nessuna corrispondenza: ts nullo, senza errore', cs[2]['ts'] is None and cs[2]['err'] == '', cs[2])
check('nessun file: errore descrittivo', cs[3]['ts'] is None and 'nessun file' in cs[3]['err'], cs[3])
check('file UTF-16 letto', any('utf16' in (c.get('msg') or '') for c in [run([{'id': 1, 'checks': [lg('success', 'utf16')]}])[1]['tools'][0]['checks'][0]]))
# senza regex per la data: vale la data di modifica del file
os.utime(os.path.join(d, 'a.log'), (time.time() - 3600 * 7, time.time() - 3600 * 7))
c0 = run([{'id': 1, 'checks': [dict(lg('success', 'completed'), ts_regex='', ts_format='', path=os.path.join(d, 'a.log'))]}])[1]['tools'][0]['checks'][0]
check('senza data nella riga vale la modifica del file', c0['ts'] and 6 < age(c0['ts']) < 8, c0)
c0 = run([{'id': 1, 'checks': [dict(lg('success', 'completed'), lookback_h=1, path=os.path.join(d, 'a.log'))]}])[1]['tools'][0]['checks'][0]
check('file più vecchio della finestra ignorato', c0['ts'] is None, c0)
# espressione non valida e catastrofica
c0 = run([{'id': 1, 'checks': [lg('success', '([unclosed')]}])[1]['tools'][0]['checks'][0]
check('espressione non valida gestita', c0['ts'] is None and 'non valida' in c0['err'], c0)
c0 = run([{'id': 1, 'checks': [lg('success', '(a+)+$')]}])
check('espressione catastrofica non blocca la sonda', c0[0] == 0 and c0[1] is not None, c0[2])
# script utente
sc = run([{'id': 2, 'checks': [{'type': 'script', 'role': 'success', 'body': "'{\"success\":\"2026-01-02T03:04:05Z\",\"fail\":\"2026-01-03T00:00:00Z\",\"msg\":\"ciao d\\u0027uno\"}'"}, {'type': 'script', 'role': 'success', 'body': "Get-Date"}, {'type': 'script', 'role': 'success', 'body': "throw 'boom'"}]}])[1]['tools'][0]['checks']
check('script: oggetto JSON con success/fail/msg', sc[0]['ts'] == '2026-01-02T03:04:05Z' and sc[0]['tsf'] == '2026-01-03T00:00:00Z' and 'ciao' in sc[0]['msg'], sc[0])
check('script: data semplice', sc[1]['ts'] and age(sc[1]['ts']) < 0.1, sc[1])
check('script: errore catturato', sc[2]['ts'] is None and 'boom' in sc[2]['err'], sc[2])
# registro eventi / servizio su Linux: nessun crash, errore gestito
ev = run([{'id': 3, 'checks': [{'type': 'eventlog', 'role': 'success', 'log': 'Application', 'ids': '4, 190', 'text': 'Fail|Error', 'lookback_h': 24}, {'type': 'service', 'name': 'Nope1, Nope2', 'require': 1}, {'type': 'registry', 'path': 'HKLM:\\SOFTWARE\\Nope', 'value': 'x', 'format': 'unix'}]}])
check('eventi, servizio e registro assenti non fanno cadere la sonda', ev[0] == 0 and ev[1] is not None and len(ev[1]['tools'][0]['checks']) == 3, ev[2])
# iniezione: apici e caratteri speciali nei parametri non escono dal base64
inj = "x'; Set-Content -Path '" + os.path.join(d, 'PWNED') + "' -Value 1; '"
run([{'id': 4, 'checks': [lg('success', inj, path=inj), {'type': 'eventlog', 'log': inj, 'provider': inj, 'ids': inj, 'text': inj, 'role': 'success'}, {'type': 'service', 'name': inj}, {'type': 'registry', 'path': inj, 'value': inj}]}])
check('parametri con apici e comandi non vengono eseguiti', not os.path.exists(os.path.join(d, 'PWNED')))
print('\n%d ok, %d falliti' % (ok, bad)); sys.exit(1 if bad else 0)
