//go:build !windows

package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"testing"
	"time"

	"golang.org/x/crypto/nacl/box"
	"golang.org/x/crypto/ssh"
)

// fakeSSH: server SSH in-process che esegue «sh -s» in locale (password "pw" per l'utente "tester").
func fakeSSH(t *testing.T) int {
	t.Helper()
	k, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	signer, err := ssh.NewSignerFromKey(k)
	if err != nil {
		t.Fatal(err)
	}
	cfg := &ssh.ServerConfig{PasswordCallback: func(c ssh.ConnMetadata, p []byte) (*ssh.Permissions, error) {
		if c.User() == "tester" && string(p) == "pw" {
			return nil, nil
		}
		return nil, io.EOF
	}}
	cfg.AddHostKey(signer)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				sc, chans, reqs, err := ssh.NewServerConn(c, cfg)
				if err != nil {
					return
				}
				defer sc.Close()
				go ssh.DiscardRequests(reqs)
				for nc := range chans {
					ch, creqs, err := nc.Accept()
					if err != nil {
						continue
					}
					go func() {
						for r := range creqs {
							if r.Type != "exec" {
								_ = r.Reply(false, nil)
								continue
							}
							_ = r.Reply(true, nil)
							in, _ := io.ReadAll(ch)
							cmd := exec.Command("sh", "-s")
							cmd.Stdin = strings.NewReader(string(in))
							o, err := cmd.CombinedOutput()
							_, _ = ch.Write(o)
							code := 0
							if ee, ok := err.(*exec.ExitError); ok {
								code = ee.ExitCode()
							}
							_, _ = ch.SendRequest("exit-status", false, ssh.Marshal(struct{ C uint32 }{uint32(code)}))
							_ = ch.CloseWrite()
							ch.Close()
						}
					}()
				}
			}()
		}
	}()
	return ln.Addr().(*net.TCPAddr).Port
}

func TestDeployUnixDryAndRun(t *testing.T) {
	if runtime.GOOS != "windows" && os.Geteuid() != 0 {
		t.Skip("il test fa girare lo script su questa macchina e richiede root (la parte non-root è coperta dal controllo uid dello script)")
	}
	port := fakeSSH(t)
	ctx := context.Background()
	st, d := deployUnix(ctx, "127.0.0.1", &unixCred{U: "tester", P: "pw", Port: port}, "dry", "", "http://x/")
	if st != "ok" && !(st == "fail" && strings.Contains(d, "curl e wget")) {
		t.Fatalf("dry: %s %q", st, d)
	}
	if st == "ok" && !strings.Contains(d, "pronto per l'installazione") || !strings.Contains(d, "impronta SSH SHA256:") {
		t.Fatalf("dry detail: %s", d)
	}
	st, d = deployUnix(ctx, "127.0.0.1", &unixCred{U: "tester", P: "bad", Port: port}, "dry", "", "")
	if st != "fail" || !strings.Contains(d, "autenticazione") {
		t.Fatalf("password errata: %s %s", st, d)
	}
	st, d = deployUnix(ctx, "127.0.0.1", &unixCred{U: "tester", P: "pw", Port: 1}, "dry", "", "")
	if st != "fail" {
		t.Fatalf("porta chiusa: %s %s", st, d)
	}
	if st, d = deployUnix(ctx, "127.0.0.1", &unixCred{U: "tester", P: "pw", Port: port}, "run", "echo installato-ok; exit 0\n", ""); st == "ok" && !strings.Contains(d, "installato") {
		t.Fatalf("run: %s %s", st, d)
	}
}

func TestSealedRoundTrip(t *testing.T) {
	t.Setenv("MYRMM_DIR", t.TempDir())
	pubB, _ := base64.StdEncoding.DecodeString(probePubB64())
	var pub [32]byte
	copy(pub[:], pubB)
	sealed, err := box.SealAnonymous(nil, []byte(`{"u":"a","p":"s3gr3to"}`), &pub, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	out, err := openSealed(base64.StdEncoding.EncodeToString(sealed))
	if err != nil || string(out) != `{"u":"a","p":"s3gr3to"}` {
		t.Fatalf("%v %s", err, out)
	}
	if _, err := openSealed(base64.StdEncoding.EncodeToString([]byte("rumore rumore rumore rumore rumore"))); err == nil {
		t.Fatal("deve rifiutare dati non cifrati per questa sonda")
	}
}

func TestDeployRunSealedUnix(t *testing.T) {
	if runtime.GOOS != "windows" && os.Geteuid() != 0 {
		t.Skip("il test fa girare lo script su questa macchina e richiede root (la parte non-root è coperta dal controllo uid dello script)")
	}
	t.Setenv("MYRMM_DIR", t.TempDir())
	port := fakeSSH(t)
	pubB, _ := base64.StdEncoding.DecodeString(probePubB64())
	var pub [32]byte
	copy(pub[:], pubB)
	j, _ := json.Marshal(unixCred{U: "tester", P: "pw", Port: port})
	sealed, _ := box.SealAnonymous(nil, j, &pub, rand.Reader)
	st, d := deployRun(context.Background(), deployTask{ID: 1, IP: "127.0.0.1", OS: "unix", Mode: "dry", Cred: base64.StdEncoding.EncodeToString(sealed)})
	if st == "fail" && !strings.Contains(d, "curl e wget") {
		t.Fatalf("%s %s", st, d)
	}
	st, d = deployRun(context.Background(), deployTask{ID: 2, IP: "127.0.0.1", OS: "win", Mode: "dry", Cred: base64.StdEncoding.EncodeToString(sealed)})
	if st != "fail" || !strings.Contains(d, "sonda Windows") {
		t.Fatalf("win da linux: %s %s", st, d)
	}
	_ = time.Second
}
