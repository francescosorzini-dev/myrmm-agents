#!/usr/bin/env python3
"""Prova gli script Linux/macOS della libreria (RustDesk, SSH, Condivisione schermo, xrdp) con comandi finti.
Gli script vengono estratti da server/index.php, quindi si prova il testo che viene davvero distribuito.
Uso: python3 ci/unix_scripts_test.py [--sh dash]"""
import os, re, stat, subprocess, sys, tempfile, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'server', 'index.php'), encoding='utf-8').read()
SH = sys.argv[sys.argv.index('--sh') + 1] if '--sh' in sys.argv else 'dash'
ok = bad = 0

def script(var):
    m = re.search(r"\$%s = <<<'SH'\n(.*?)\nSH;" % var, SRC, re.S)
    assert m, var
    return m.group(1)

def check(name, cond, extra=''):
    global ok, bad
    if cond: ok += 1; print('  ok   ', name)
    else: bad += 1; print('  FALLITO', name, extra)

def stub(d, name, body):
    p = os.path.join(d, name)
    open(p, 'w').write('#!/bin/sh\n' + body + '\n')
    os.chmod(p, 0o755)

def sandbox(uname='Linux', listen22=False, listen3389=False, listen5900=False):
    d = tempfile.mkdtemp(prefix='myrmm-ut-')
    log = os.path.join(d, 'calls.log')
    for c in ('apt-get', 'dpkg', 'dnf', 'yum', 'zypper', 'xattr', 'open', 'adduser', 'ufw', 'firewall-cmd', 'sleep'):
        stub(d, c, 'echo "%s $*" >> "%s"\n[ "%s" = ufw ] && echo "Status: inactive"\nexit 0' % (c, log, c))
    stub(d, 'id', 'echo 0')
    stub(d, 'uname', 'echo %s' % uname)
    stub(d, 'curl', 'while [ $# -gt 0 ]; do [ "$1" = -o ] && { printf FAKEPKG > "$2"; }; shift; done; exit 0')
    stub(d, 'systemctl', 'echo "systemctl $*" >> "%s"\n[ "$1" = list-unit-files ] && echo "ssh.service enabled"\nexit 0' % log)
    ports = ''.join(['LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n' if listen22 else '', 'LISTEN 0 128 0.0.0.0:3389 0.0.0.0:*\n' if listen3389 else ''])
    stub(d, 'ss', "printf 'State Recv-Q Send-Q Local Peer\\n%s'" % ports.replace('\n', '\\n'))
    stub(d, 'lsof', 'exit %d' % (0 if listen5900 else 1))
    stub(d, 'rustdesk', 'echo "rustdesk $*" >> "%s"\n[ "$1" = --get-id ] && echo 123456789\nexit 0' % log)
    return d, log

def run(d, var, subs, env=None, mode=None):
    body = script(var)
    if mode: body = body.replace('@@MODE@@', mode)
    for k, v in subs.items(): body = body.replace('{{%s}}' % k, v)
    body = re.sub(r'\{\{[A-Z_]+\}\}', '', body)
    f = os.path.join(d, 'run.sh'); open(f, 'w').write(body)
    e = dict(os.environ); e['PATH'] = d + ':' + os.environ['PATH']; e.update(env or {})
    r = subprocess.run([SH, f], capture_output=True, text=True, env=e, timeout=60)
    return r, open(os.path.join(d, 'calls.log')).read() if os.path.exists(os.path.join(d, 'calls.log')) else ''

print('RustDesk · Linux .deb · unattended')
d, _ = sandbox(); conf = os.path.join(d, 'rd.toml')
r, log = run(d, 'uRd', {'DOWNLOAD_URL': 'https://x/rd.deb?v=1', 'RUSTDESK_PASSWORD': 'pw1', 'CONFIG_STRING': 'cfg9'}, {'MYRMM_RD_CONF': conf}, 'unattended')
check('exit 0', r.returncode == 0, r.stderr)
check('ID riportato', 'RUSTDESK_ID=123456789' in r.stdout, r.stdout)
check('modo e password riportati', 'RUSTDESK_MODE=unattended' in r.stdout and 'RUSTDESK_PW=pw1' in r.stdout)
check('config e password applicate', 'rustdesk --config cfg9' in log and 'rustdesk --password pw1' in log, log)
check('apt-get invocato con il .deb', re.search(r'apt-get install -y .*rd\.deb', log) is not None, log)
shutil.rmtree(d)

print('RustDesk · Linux · variabili vuote = valori predefiniti')
d, _ = sandbox(); conf = os.path.join(d, 'rd.toml')
r, log = run(d, 'uRd', {}, {'MYRMM_RD_CONF': conf}, 'unattended')
pw = re.search(r'^RUSTDESK_PW=(\S+)$', r.stdout, re.M)
check('exit 0 senza alcuna variabile', r.returncode == 0, r.stderr)
check('password casuale di 20 caratteri generata e applicata', bool(pw) and len(pw.group(1)) == 20 and ('rustdesk --password ' + pw.group(1)) in log, r.stdout + log)
check('URL predefinito: pacchetto ufficiale rustdesk', re.search(r'apt-get install -y .*rustdesk-[0-9.]+-x86_64\.deb', log) is not None, log)
shutil.rmtree(d)

print('RustDesk · Linux .rpm con dnf · click')
d, _ = sandbox(); conf = os.path.join(d, 'rd.toml')
open(conf, 'w').write("[options]\napprove-mode = 'password'\n")
r, log = run(d, 'uRd', {'DOWNLOAD_URL': 'https://x/rd.rpm', 'RUSTDESK_PASSWORD': 'ignorata'}, {'MYRMM_RD_CONF': conf}, 'click')
check('exit 0', r.returncode == 0, r.stderr)
check('dnf usato', 'dnf install -y' in log, log)
check('modo click, nessuna password', 'RUSTDESK_MODE=click' in r.stdout and 'RUSTDESK_PW' not in r.stdout and '--password' not in log, r.stdout + log)
check('approve-mode riscritto', "approve-mode = 'click'" in open(conf).read(), open(conf).read())
shutil.rmtree(d)

print('RustDesk · errori')
d, _ = sandbox()
r, _ = run(d, 'uRd', {'DOWNLOAD_URL': 'https://x/rd.zip'}, None, 'unattended'); check('formato non supportato rifiutato', r.returncode == 1 and 'non supportato' in r.stderr, r.stderr)
shutil.rmtree(d)

print('RustDesk · macOS .dmg')
d, _ = sandbox('Darwin'); conf = os.path.join(d, 'rd.toml'); apps = os.path.join(d, 'Apps'); os.mkdir(apps)
stub(d, 'hdiutil', 'if [ "$1" = attach ]; then while [ $# -gt 0 ]; do [ "$1" = -mountpoint ] && M="$2"; shift; done; mkdir -p "$M/RustDesk.app/Contents/MacOS"; cp "%s/rustdesk" "$M/RustDesk.app/Contents/MacOS/RustDesk"; fi; exit 0' % d)
r, log = run(d, 'uRd', {'DOWNLOAD_URL': 'https://x/RustDesk.dmg', 'RUSTDESK_PASSWORD': 'pw2'}, {'MYRMM_RD_CONF': conf, 'MYRMM_APPS_DIR': apps}, 'unattended')
check('exit 0', r.returncode == 0, r.stderr + r.stdout)
check('app copiata e ID letto', os.path.exists(os.path.join(apps, 'RustDesk.app/Contents/MacOS/RustDesk')) and 'RUSTDESK_ID=123456789' in r.stdout, r.stdout + r.stderr)
check('nota permessi macOS', 'Registrazione schermo' in r.stdout)
shutil.rmtree(d)

print('SSH')
d, _ = sandbox(listen22=True)
r, log = run(d, 'uSsh', {'AZIONE': 'abilita'}); check('abilita: ok se in ascolto', r.returncode == 0 and 'in_ascolto' in r.stdout, r.stdout + r.stderr)
check('abilita: servizio avviato', 'systemctl enable --now ssh' in log, log)
r, _ = run(d, 'uSsh', {'AZIONE': 'boh'}); check('azione non valida rifiutata', r.returncode == 1)
r, _ = run(d, 'uSsh', {'AZIONE': 'disabilita'}); check('disabilita: errore se ancora in ascolto', r.returncode == 1 and 'ancora in ascolto' in r.stderr, r.stderr)
shutil.rmtree(d)
d, _ = sandbox(listen22=False)
r, _ = run(d, 'uSsh', {'AZIONE': 'abilita'}); check('abilita: errore se non in ascolto', r.returncode == 1, r.stdout)
r, log = run(d, 'uSsh', {'AZIONE': 'disabilita'}); check('disabilita: ok se chiuso', r.returncode == 0 and 'chiuso' in r.stdout and 'disable --now ssh' in log, r.stdout + log)
shutil.rmtree(d)
d, _ = sandbox('Darwin', listen22=True)
stub(d, 'systemsetup', 'echo "systemsetup $*" >> "%s"; exit 0' % os.path.join(d, 'calls.log'))
r, log = run(d, 'uSsh', {'AZIONE': 'abilita'}); check('macOS: systemsetup -setremotelogin on', r.returncode == 0 and 'systemsetup -setremotelogin on' in log, log + r.stderr)
shutil.rmtree(d)

print('Condivisione schermo (macOS)')
d, _ = sandbox('Darwin', listen5900=True); k = os.path.join(d, 'kickstart')
stub(d, 'kickstart', 'echo "kickstart $*" >> "%s"; exit 0' % os.path.join(d, 'calls.log'))
r, log = run(d, 'uVnc', {'AZIONE': 'abilita'}, {'MYRMM_KICKSTART': k}); check('abilita: ok e kickstart -activate', r.returncode == 0 and 'kickstart -activate' in log, r.stderr + log)
r, _ = run(d, 'uVnc', {'AZIONE': 'disabilita'}, {'MYRMM_KICKSTART': k}); check('disabilita: errore se 5900 ancora aperta', r.returncode == 1, r.stdout)
r, _ = run(d, 'uVnc', {'AZIONE': 'abilita'}, {'MYRMM_KICKSTART': '/non/esiste'}); check('kickstart mancante segnalato', r.returncode == 1 and 'kickstart non trovato' in r.stderr, r.stderr)
shutil.rmtree(d)
d, _ = sandbox('Linux'); r, _ = run(d, 'uVnc', {'AZIONE': 'abilita'}); check('rifiutato su Linux', r.returncode == 1 and 'solo per macOS' in r.stderr); shutil.rmtree(d)
d, _ = sandbox('Darwin', listen5900=False); stub(d, 'kickstart', 'exit 0')
r, _ = run(d, 'uVnc', {'AZIONE': 'abilita'}, {'MYRMM_KICKSTART': os.path.join(d, 'kickstart')}); check('porta chiusa dopo abilita: avviso su Accesso completo al disco', r.returncode == 1 and 'Accesso completo al disco' in r.stderr, r.stderr); shutil.rmtree(d)

print('xrdp')
d, _ = sandbox(listen3389=True); stub(d, 'xrdp', 'exit 0')
r, log = run(d, 'uXrdp', {'AZIONE': 'abilita'}); check('abilita: ok', r.returncode == 0 and 'in_ascolto' in r.stdout and 'enable --now xrdp' in log, r.stdout + r.stderr + log)
r, _ = run(d, 'uXrdp', {'AZIONE': 'disabilita'}); check('disabilita: errore se ancora in ascolto', r.returncode == 1, r.stdout)
shutil.rmtree(d)
d, _ = sandbox(listen3389=False)
r, log = run(d, 'uXrdp', {'AZIONE': 'abilita'}); check('xrdp mancante: installa con apt-get e poi fallisce se non esiste', r.returncode == 1 and 'apt-get install -y xrdp' in log, r.stderr + log)
shutil.rmtree(d)

print('\n%d ok, %d falliti' % (ok, bad))
sys.exit(1 if bad else 0)
