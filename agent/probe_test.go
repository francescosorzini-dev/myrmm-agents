package main

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

func TestTCPCheck(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()
	port := l.Addr().(*net.TCPAddr).Port
	if d, err := tcpCheck("127.0.0.1", port, time.Second); err != nil || d < 0 {
		t.Fatalf("porta aperta: d=%v err=%v", d, err)
	}
	l2, _ := net.Listen("tcp", "127.0.0.1:0")
	closed := l2.Addr().(*net.TCPAddr).Port
	l2.Close()
	if _, err := tcpCheck("127.0.0.1", closed, time.Second); err == nil {
		t.Fatal("porta chiusa: atteso errore")
	} else if err.Error() != "connessione rifiutata (porta chiusa)" {
		t.Fatalf("messaggio inatteso: %v", err)
	}
}

func TestICMPSum(t *testing.T) {
	// pacchetto d'esempio: la somma di controllo del pacchetto completo deve dare 0
	p := []byte{8, 0, 0, 0, 0x12, 0x34, 0x00, 0x01, 'a', 'b', 'c', 'd'}
	s := icmpSum(p)
	p[2], p[3] = byte(s>>8), byte(s)
	if icmpSum(p) != 0 {
		t.Fatalf("checksum errata: %x", icmpSum(p))
	}
}

func TestPingLoopback(t *testing.T) {
	d, err := icmpPing("127.0.0.1", 2*time.Second)
	if err != nil {
		t.Skipf("ping non disponibile in questo ambiente: %v", err)
	}
	if d < 0 || d > time.Second { // su Windows il timer ha risoluzione ~15 ms: 0 è un valore valido per il loopback
		t.Fatalf("rtt inatteso %v", d)
	}
}

// La sonda controlla gli apparati ricevuti, invia gli esiti in blocco e li dichiara negativi con il motivo.
func TestProbeRunReports(t *testing.T) {
	l, _ := net.Listen("tcp", "127.0.0.1:0")
	defer l.Close()
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()
	l2, _ := net.Listen("tcp", "127.0.0.1:0")
	closedPort := l2.Addr().(*net.TCPAddr).Port
	l2.Close()

	var mu sync.Mutex
	var got []probeResult
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var in struct {
			Results []probeResult `json:"results"`
		}
		_ = json.Unmarshal(b, &in)
		mu.Lock()
		got = append(got, in.Results...)
		mu.Unlock()
		if r.Header.Get("X-Device-Key") != "k" {
			w.WriteHeader(401)
			return
		}
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer srv.Close()
	cfg := &Config{ServerURL: srv.URL}
	pc := &probeCfg{On: true, Ver: "v1", Targets: []probeTarget{
		{ID: 1, IP: "127.0.0.1", Kind: "tcp", Port: l.Addr().(*net.TCPAddr).Port, Every: 15},
		{ID: 2, IP: "127.0.0.1", Kind: "tcp", Port: closedPort, Every: 15},
	}}
	probeApply(cfg, State{APIKey: "k"}, pc, testLogger{})
	defer probeApply(cfg, State{}, &probeCfg{On: false}, testLogger{})
	if probeVer() != "v1" {
		t.Fatal("versione non registrata")
	}
	deadline := time.Now().Add(25 * time.Second)
	for time.Now().Before(deadline) {
		time.Sleep(500 * time.Millisecond)
		mu.Lock()
		n := len(got)
		mu.Unlock()
		if n >= 2 {
			break
		}
	}
	mu.Lock()
	defer mu.Unlock()
	byID := map[int]probeResult{}
	for _, r := range got {
		byID[r.ID] = r
	}
	if r, ok := byID[1]; !ok || !r.OK || r.RTT < 0 {
		t.Fatalf("apparato 1: %+v", byID[1])
	}
	if r, ok := byID[2]; !ok || r.OK || r.Detail == "" {
		t.Fatalf("apparato 2: %+v", byID[2])
	}
	probeApply(cfg, State{}, &probeCfg{On: false}, testLogger{})
	if probeVer() != "" {
		t.Fatal("la sonda disattivata deve azzerare la versione")
	}
}

type testLogger struct{}

func (testLogger) Error(v ...interface{}) error              { return nil }
func (testLogger) Warning(v ...interface{}) error            { return nil }
func (testLogger) Info(v ...interface{}) error               { return nil }
func (testLogger) Errorf(f string, a ...interface{}) error   { return nil }
func (testLogger) Warningf(f string, a ...interface{}) error { return nil }
func (testLogger) Infof(f string, a ...interface{}) error    { return nil }
