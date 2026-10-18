package main

// Distribuzione verso Linux/macOS via SSH (da qualsiasi sonda). Con la password si lavora come root oppure con sudo.

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

type unixCred struct {
	U    string `json:"u"`
	P    string `json:"p"`
	Key  string `json:"key,omitempty"` // chiave privata PEM (facoltativa)
	Sudo bool   `json:"sudo,omitempty"`
	Port int    `json:"port,omitempty"`
}

// sshDial: connessione con password / tastiera interattiva / chiave. La chiave host è accettata e riportata (prima connessione).
func sshDial(ip string, c *unixCred, to time.Duration) (*ssh.Client, string, error) {
	var auth []ssh.AuthMethod
	if c.Key != "" {
		if sg, err := ssh.ParsePrivateKey([]byte(c.Key)); err == nil {
			auth = append(auth, ssh.PublicKeys(sg))
		} else {
			return nil, "", fmt.Errorf("chiave privata non valida: %v", err)
		}
	}
	if c.P != "" {
		auth = append(auth, ssh.Password(c.P), ssh.KeyboardInteractive(func(_, _ string, qs []string, _ []bool) ([]string, error) {
			a := make([]string, len(qs))
			for i := range a {
				a[i] = c.P
			}
			return a, nil
		}))
	}
	if len(auth) == 0 {
		return nil, "", fmt.Errorf("nessuna password o chiave indicata")
	}
	var fp string
	port := c.Port
	if port == 0 {
		port = 22
	}
	cfg := &ssh.ClientConfig{User: c.U, Auth: auth, Timeout: to, ClientVersion: "SSH-2.0-myrmm-probe",
		HostKeyCallback: func(_ string, _ net.Addr, k ssh.PublicKey) error { fp = ssh.FingerprintSHA256(k); return nil }}
	cl, err := ssh.Dial("tcp", net.JoinHostPort(ip, strconv.Itoa(port)), cfg)
	if err != nil {
		return nil, "", err
	}
	return cl, fp, nil
}

func sshErrText(err error) string {
	s := err.Error()
	switch {
	case strings.Contains(s, "unable to authenticate") || strings.Contains(s, "no supported methods"):
		return "autenticazione SSH rifiutata (utente o password errati, o accesso con password disattivato sul target)"
	case strings.Contains(s, "refused"):
		return "porta SSH chiusa"
	case strings.Contains(s, "i/o timeout") || strings.Contains(s, "timed out"):
		return "SSH non risponde (timeout)"
	}
	return "SSH: " + s
}

// lockedBuf: stdout e stderr della sessione SSH sono copiati da due goroutine diverse: la scrittura va serializzata.
type lockedBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuf) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}
func (l *lockedBuf) String() string { l.mu.Lock(); defer l.mu.Unlock(); return l.b.String() }

// sshRun esegue uno script sh sul target (stdin) e restituisce l'uscita. Con sudo la password precede lo script su stdin.
func sshRun(ctx context.Context, cl *ssh.Client, script string, sudo bool, pass string, to time.Duration) (string, int, error) {
	s, err := cl.NewSession()
	if err != nil {
		return "", -1, err
	}
	defer s.Close()
	out := &lockedBuf{}
	s.Stdout, s.Stderr = out, out
	var in io.Reader
	cmd := "sh -s"
	if sudo {
		cmd = "sudo -S -p '' sh -s"
		in = io.MultiReader(strings.NewReader(pass+"\n"), strings.NewReader(script))
	} else {
		in = strings.NewReader(script)
	}
	s.Stdin = in
	done := make(chan error, 1)
	go func() { done <- s.Run(cmd) }()
	select {
	case err = <-done:
	case <-time.After(to):
		_ = s.Signal(ssh.SIGKILL)
		return out.String(), -1, fmt.Errorf("tempo scaduto dopo %s", to)
	case <-ctx.Done():
		return out.String(), -1, ctx.Err()
	}
	if err != nil {
		if ee, ok := err.(*ssh.ExitError); ok {
			return out.String(), ee.ExitStatus(), nil
		}
		return out.String(), -1, err
	}
	return out.String(), 0, nil
}

// unixDryScript: solo letture. Stampa chiave=valore.
const unixDryScript = `
echo "os=$(uname -s 2>/dev/null)"; echo "arch=$(uname -m 2>/dev/null)"; echo "uid=$(id -u 2>/dev/null)"
echo "host=$(hostname 2>/dev/null)"
if command -v curl >/dev/null 2>&1; then echo "dl=curl"; elif command -v wget >/dev/null 2>&1; then echo "dl=wget"; else echo "dl=none"; fi
if command -v systemctl >/dev/null 2>&1; then echo "init=systemd"; elif [ "$(uname -s)" = Darwin ]; then echo "init=launchd"; else echo "init=altro"; fi
echo "disk_kb=$(df -k /opt 2>/dev/null | awk 'NR==2{print $4}')"
if [ -x /opt/myrmm/myrmm-agent ]; then echo "agent=installato"; else echo "agent=no"; fi
`

func kv(out string) map[string]string {
	m := map[string]string{}
	for _, l := range strings.Split(out, "\n") {
		if i := strings.Index(l, "="); i > 0 && !strings.ContainsAny(l[:i], " \t") {
			m[strings.TrimSpace(l[:i])] = strings.TrimSpace(l[i+1:])
		}
	}
	return m
}

// deployUnix: prova a vuoto (solo letture, senza modifiche) o installazione.
func deployUnix(ctx context.Context, ip string, c *unixCred, mode, script, serverURL string) (state, detail string) {
	cl, fp, err := sshDial(ip, c, 8*time.Second)
	if err != nil {
		return "fail", sshErrText(err)
	}
	defer cl.Close()
	out, _, err := sshRun(ctx, cl, unixDryScript, false, "", 30*time.Second)
	if err != nil {
		return "fail", "SSH: " + err.Error()
	}
	m := kv(out)
	if m["os"] != "Linux" && m["os"] != "Darwin" {
		return "fail", "sistema non supportato: " + m["os"]
	}
	sudo := false
	if m["uid"] != "0" {
		if !c.Sudo {
			return "fail", "l'utente non è root: attiva «usa sudo» o indica root"
		}
		sudo = true
		o2, code, err := sshRun(ctx, cl, "echo OK\n", true, c.P, 20*time.Second)
		if err != nil || code != 0 || !strings.Contains(o2, "OK") {
			return "fail", "sudo rifiutato per l'utente " + c.U + " (password errata o utente non in sudoers)"
		}
	}
	info := fmt.Sprintf("%s %s · %s · utente %s%s · scaricamento con %s · init %s · spazio libero %s MB · impronta SSH %s",
		m["os"], m["arch"], m["host"], c.U, map[bool]string{true: " (sudo)", false: " (root)"}[sudo], m["dl"], m["init"], kbToMB(m["disk_kb"]), fp)
	if m["dl"] == "none" {
		return "fail", "mancano curl e wget sul target. " + info
	}
	if m["agent"] == "installato" {
		return "skip", "agent già installato. " + info
	}
	if mode == "dry" {
		return "ok", "pronto per l'installazione. " + info
	}
	out, code, err := sshRun(ctx, cl, script, sudo, c.P, 6*time.Minute)
	if err != nil {
		return "fail", "installazione: " + err.Error()
	}
	tail := tailLines(out, 4)
	if code != 0 {
		return "fail", fmt.Sprintf("installazione terminata con errore %d: %s", code, tail)
	}
	if strings.Contains(out, "non ancora arruolato") {
		return "ok", "installato, ma non ancora arruolato (il target non raggiunge il server?): " + tail
	}
	return "ok", "installato e arruolato. " + tail
}

func kbToMB(s string) string {
	n, _ := strconv.Atoi(s)
	return strconv.Itoa(n / 1024)
}

func tailLines(s string, n int) string {
	ls := strings.Split(strings.TrimSpace(s), "\n")
	if len(ls) > n {
		ls = ls[len(ls)-n:]
	}
	return strings.Join(ls, " | ")
}
