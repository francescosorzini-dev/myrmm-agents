package main

import (
	"strings"
	"testing"
)

func TestSSHArgs(t *testing.T) {
	got := strings.Join(sshArgs("127.0.0.1:13389", "mario", "myrmm-dev7"), " ")
	want := "-p 13389 -o StrictHostKeyChecking=accept-new -o HostKeyAlias=myrmm-dev7 mario@127.0.0.1"
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
	if g := strings.Join(sshArgs("127.0.0.1:13389", "u", ""), " "); strings.Contains(g, "HostKeyAlias") {
		t.Fatalf("alias vuoto non deve comparire: %q", g)
	}
}

func TestStartSSHRejectsBadUser(t *testing.T) {
	called := false
	for _, u := range []string{"", "-oProxyCommand=x", "a b", "a@b"} {
		startSSH("127.0.0.1:1", u, "", func() { called = true })
	}
	if called {
		t.Fatal("ssh non deve partire con utente non valido")
	}
}
