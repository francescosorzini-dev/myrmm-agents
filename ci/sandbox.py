"""Ambiente isolato per provare gli script di shell: una radice finta (chroot in un mount namespace) con i file di prova al loro posto
(/etc/ssh/sshd_config, /Library/…), comandi finti davanti a quelli veri (/stubbin) e uname a scelta. Il sistema vero non viene toccato.
Richiede root (oppure sudo senza password) e `unshare`; altrimenti available() è False e le prove saltano."""
import os, shutil, stat, subprocess, tempfile, textwrap

def available():
    if not shutil.which("unshare") or not shutil.which("chroot"): return False
    pre = [] if os.geteuid() == 0 else ["sudo", "-n"]
    try: return subprocess.run(pre + ["unshare", "-m", "true"], capture_output=True, timeout=20).returncode == 0
    except Exception: return False

SETUP = r'''
set -e
R="$1"; shift
for d in bin sbin lib lib32 lib64 libx32 usr; do
  if [ -L "/$d" ]; then [ -L "$R/$d" ] || ln -s "$(readlink "/$d")" "$R/$d"
  elif [ "$d" = usr ] && [ -d /usr ]; then
    # /usr in sovrapposizione: i file di prova sotto /usr (es. /usr/libexec/PlistBuddy) vanno nel livello scrivibile e il /usr vero non cambia
    mkdir -p "$R/usr" "$R/.usr-up" "$R/.usr-wk"
    mount -t overlay overlay -o "lowerdir=/usr,upperdir=$R/.usr-up,workdir=$R/.usr-wk" "$R/usr" 2>/dev/null || mount --bind /usr "$R/usr"
  elif [ -d "/$d" ]; then mkdir -p "$R/$d"; mount --bind "/$d" "$R/$d"; fi
done
mkdir -p "$R/proc" "$R/dev" "$R/tmp" "$R/root" "$R/var/tmp"
[ -f "$R/.noproc" ] || mount -t proc proc "$R/proc" 2>/dev/null || true
mount --rbind /dev "$R/dev" 2>/dev/null || true
chmod 1777 "$R/tmp"
exec chroot "$R" /usr/bin/env -i PATH="/stubbin:/allowbin" HOME=/root LANG=C.UTF-8 "$@"
'''

BASE = tuple("sh bash dash env cat cut tr sort uniq head tail wc awk sed grep egrep fgrep find xargs du df ls mkdir rmdir rm mv cp touch date sleep id dd sync tar gzip gunzip mktemp basename dirname tee stat readlink chmod chown ln nproc true false test expr kill nl od expand fold paste comm join rev tac seq yes sha256sum md5sum cmp diff which".split())

class Sandbox:
    def __init__(self, files=None, stubs=None, uname="Linux", arch=None, copy_etc=True, real=(), proc=True):
        self.root = tempfile.mkdtemp(prefix="myrmm-sbx-")
        os.makedirs(self.root + "/stubbin")
        # il PATH dello script contiene SOLO i comandi di base elencati qui, i comandi finti (stubs) e quelli veri richiesti con real=[…]:
        # così «command -v nft» fallisce davvero quando il test vuole un sistema senza nft
        if not proc: open(self.root + "/.noproc", "w").close(); os.makedirs(self.root + "/proc", exist_ok=True)
        os.makedirs(self.root + "/allowbin")
        for c in BASE + tuple(real):
            h = shutil.which(c)
            if h and not os.path.lexists(self.root + "/allowbin/" + c): os.symlink(h, self.root + "/allowbin/" + c)
        if copy_etc:
            shutil.copytree("/etc", self.root + "/etc", symlinks=True, ignore_dangling_symlinks=True, ignore=shutil.ignore_patterns("ssl", "shadow*", "gshadow*", "ssh", "sudoers*", "cron*", "pam.d", "security"))
            if os.path.isdir("/etc/ssl"): shutil.copytree("/etc/ssl", self.root + "/etc/ssl", symlinks=True, ignore_dangling_symlinks=True)
        arch = arch or ("arm64" if uname == "Darwin" else "x86_64")
        self.stub("uname", 'case "$1" in -s|"") echo %s;; -m) echo %s;; -r) echo %s;; -n) echo testhost;; -a) echo "%s testhost 1.0 #1 %s";; *) echo %s;; esac' % (uname, arch, "24.1.0" if uname == "Darwin" else "6.1.0-test", uname, arch, uname))
        for path, content in (files or {}).items(): self.file(path, content)
        for n, b in (stubs or {}).items(): self.stub(n, b)

    def file(self, path, content, mode=None):
        p = self.root + ("/.usr-up" + path[4:] if path.startswith("/usr/") else path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if isinstance(content, str): content = textwrap.dedent(content).lstrip("\n") if content.startswith("\n") else content
        open(p, "wb").write(content.encode() if isinstance(content, str) else content)
        if mode: os.chmod(p, mode)
        return p

    def stub(self, name, body):
        """Comando finto: eseguito in sh; registra la chiamata in /calls.log."""
        p = self.root + "/stubbin/" + name
        open(p, "w").write('#!/bin/sh\necho "%s $*" >> /calls.log\n%s\n' % (name, body))
        os.chmod(p, 0o755)

    def run(self, script, shell="bash", env=None, timeout=120, pre=""):
        f = self.root + "/script.sh"; open(f, "w", encoding="utf-8").write(pre + script + ("\n" if not script.endswith("\n") else ""))
        pfx = [] if os.geteuid() == 0 else ["sudo", "-n"]
        envs = [f"{k}={v}" for k, v in (env or {}).items()]
        cmd = pfx + ["unshare", "-m", "sh", "-c", SETUP, "sandbox", self.root] + envs + [shell, "/script.sh"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        log = ""
        try: log = open(self.root + "/calls.log").read()
        except Exception: pass
        return r.returncode, r.stdout, r.stderr, log

    def read(self, path):
        try: return open(self.root + path, encoding="utf-8", errors="replace").read()
        except Exception: return None

    def exists(self, path): return os.path.lexists(self.root + path)
    def close(self):
        pfx = [] if os.geteuid() == 0 else ["sudo", "-n"]
        subprocess.run(pfx + ["rm", "-rf", self.root], capture_output=True)
