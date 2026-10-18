package main

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestCidrHosts(t *testing.T) {
	h, cut := cidrHosts("192.168.1.0/24", 4096)
	if len(h) != 254 || h[0] != "192.168.1.1" || h[253] != "192.168.1.254" || cut {
		t.Fatalf("/24: %d %v %v", len(h), h[0], cut)
	}
	if h, _ := cidrHosts("10.0.0.4/30", 10); len(h) != 2 || h[0] != "10.0.0.5" || h[1] != "10.0.0.6" {
		t.Fatalf("/30: %v", h)
	}
	if h, _ := cidrHosts("10.0.0.7/32", 10); len(h) != 1 || h[0] != "10.0.0.7" {
		t.Fatalf("/32: %v", h)
	}
	if h, cut := cidrHosts("10.0.0.0/16", 100); len(h) != 100 || !cut {
		t.Fatalf("/16 limitata: %d %v", len(h), cut)
	}
	if h, _ := cidrHosts("::1/128", 10); h != nil {
		t.Fatal("IPv6 non supportato")
	}
}

func TestMacVendorAndKind(t *testing.T) {
	for mac, want := range map[string]string{"00:0c:29:aa:bb:cc": "VMware", "B8-27-EB-01-02-03": "Raspberry Pi", "52:54:00:11:22:33": "QEMU/KVM", "10:34:56:78:9a:bc": "", "da:a1:19:00:00:01": "MAC casuale (privacy)"} {
		if got := macVendor(mac); got != want {
			t.Errorf("%s: %q (atteso %q)", mac, got, want)
		}
	}
	cases := []struct {
		h    foundHost
		want string
	}{
		{foundHost{Ports: []foundPort{{P: 9100}, {P: 80}}}, "printer"},
		{foundHost{Snmp: &foundSnmp{Profile: "switch"}, Ports: []foundPort{{P: 22}}}, "switch"},
		{foundHost{Vendor: "Brother"}, "printer"},
		{foundHost{Ports: []foundPort{{P: 445}, {P: 3389}}}, "windows"},
		{foundHost{Ports: []foundPort{{P: 22}}}, "linux"},
		{foundHost{Vendor: "Synology", Ports: []foundPort{{P: 22}, {P: 445}}}, "nas"},
		{foundHost{Vendor: "Hikvision"}, "camera"},
		{foundHost{Vendor: "Ubiquiti", Ports: []foundPort{{P: 22}}}, "net"},
		{foundHost{Vendor: "MAC casuale (privacy)"}, "mobile"},
		{foundHost{Ports: []foundPort{{P: 443}}, Title: "Router login"}, "web"},
		{foundHost{}, "unknown"},
	}
	for i, c := range cases {
		if got := guessKind(&c.h); got != c.want {
			t.Errorf("caso %d: %q (atteso %q)", i, got, c.want)
		}
	}
}

func TestScanNetLoopback(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skip(err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			_, _ = c.Write([]byte("SSH-2.0-OpenSSH_9.6 Ubuntu\r\n"))
			c.Close()
		}
	}()
	web := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("<html><head><title> Stampante  HP LaserJet </title></head></html>"))
	}))
	defer web.Close()
	sp := ln.Addr().(*net.TCPAddr).Port
	wp, _ := strconv.Atoi(web.URL[strings.LastIndex(web.URL, ":")+1:])
	res := scanNet(context.Background(), probeNet{ID: 5, CIDR: "127.0.0.1/32"}, []int{sp, wp, 1})
	if res.Err != "" || res.Net != 5 || res.Scanned != 1 || len(res.Hosts) != 1 {
		t.Fatalf("scansione: %+v", res)
	}
	h := res.Hosts[0]
	if h.IP != "127.0.0.1" || len(h.Ports) != 2 {
		t.Fatalf("porte: %+v", h)
	}
	if got := webTitle("127.0.0.1", wp, "http"); got != "Stampante HP LaserJet" {
		t.Fatalf("titolo: %q", got)
	}
	// annullamento: nessun host
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if r := scanNet(ctx, probeNet{ID: 6, CIDR: "127.0.0.0/30"}, nil); len(r.Hosts) != 0 {
		t.Fatalf("scansione annullata: %+v", r.Hosts)
	}
}

func TestBannerSSH(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:22")
	if ln == nil {
		t.Skip("porta 22 occupata o riservata")
	}
	defer ln.Close()
	go func() {
		c, err := ln.Accept()
		if err == nil {
			_, _ = c.Write([]byte("SSH-2.0-OpenSSH_9.6\r\n"))
			c.Close()
		}
	}()
	if b := portBanner("127.0.0.1", 22); b != "SSH-2.0-OpenSSH_9.6" {
		t.Fatalf("banner: %q", b)
	}
}

func TestScanTickRequested(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skip(err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()
	sp := ln.Addr().(*net.TCPAddr).Port
	probe.mu.Lock()
	probe.cfg = probeCfg{On: true, Nets: []probeNet{{ID: 3, CIDR: "127.0.0.1/32", Scan: 1}}, ScanPorts: []int{sp, 1}}
	probe.extra = nil
	probe.mu.Unlock()
	scanSt.Lock()
	scanSt.running, scanSt.req, scanSt.last = false, map[int]int{}, map[int]time.Time{}
	scanSt.Unlock()
	probeScanTick(context.Background(), &Config{}, State{}, testLogger{})
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		probe.mu.Lock()
		l, _ := probe.extra["found"].([]any)
		probe.mu.Unlock()
		if len(l) == 1 {
			fn := l[0].(foundNet)
			if fn.Net != 3 || len(fn.Hosts) != 1 || len(fn.Hosts[0].Ports) != 1 || fn.Hosts[0].Ports[0].P != sp || fn.Req != 1 {
				t.Fatalf("risultato: %+v", fn)
			}
			// la stessa richiesta non riparte
			probeScanTick(context.Background(), &Config{}, State{}, testLogger{})
			time.Sleep(300 * time.Millisecond)
			probe.mu.Lock()
			l, _ = probe.extra["found"].([]any)
			probe.mu.Unlock()
			if len(l) != 1 {
				t.Fatalf("scansione ripetuta: %d", len(l))
			}
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatal("nessun risultato dalla scansione richiesta")
}
