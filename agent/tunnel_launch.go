package main

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"strings"
)

// sshArgs: argomenti di ssh verso il tunnel locale. Il nome host viene fissato con HostKeyAlias, così la chiave del
// device resta verificata (e riconosciuta alle volte successive) invece di condividere la voce «127.0.0.1».
func sshArgs(addr, user, alias string) []string {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		host, port = "127.0.0.1", "13389"
	}
	a := []string{"-p", port, "-o", "StrictHostKeyChecking=accept-new"}
	if alias != "" {
		a = append(a, "-o", "HostKeyAlias="+alias)
	}
	return append(a, user+"@"+host)
}

// startSSH avvia ssh nel terminale dell'operatore; done() viene chiamata quando ssh termina.
func startSSH(addr, user, alias string, done func()) {
	if strings.ContainsAny(user, " \t\r\n@\"'") || user == "" || strings.HasPrefix(user, "-") {
		fmt.Fprintln(os.Stderr, "-ssh: nome utente non valido")
		return
	}
	p, err := exec.LookPath("ssh")
	if err != nil {
		fmt.Fprintln(os.Stderr, "-ssh: client ssh non trovato; collega il tuo client SSH a", addr)
		return
	}
	c := exec.Command(p, sshArgs(addr, user, alias)...)
	c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := c.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "-ssh:", err)
		return
	}
	go func() { _ = c.Wait(); done() }()
}
