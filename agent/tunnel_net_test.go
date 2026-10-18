package main

import (
	"bufio"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"net"
	"strings"
	"testing"
	"time"
)

func signNet(key string, id string, dev int, host string, port int, exp int64) string {
	m := hmac.New(sha256.New, []byte(key))
	fmt.Fprintf(m, "tunnelnet\n%s\n%d\n%s\n%d\n%d", id, dev, host, port, exp)
	return hex.EncodeToString(m.Sum(nil))
}

func TestTunnelNetVerify(t *testing.T) {
	cfg := &Config{JobSigningKey: "k"}
	st := State{DeviceID: 7}
	exp := time.Now().Add(time.Minute).Unix()
	o := &TunnelOffer{ID: "abcdefgh12345678", Port: 443, Exp: exp, Host: "10.7.0.1"}
	o.Sig = signNet("k", o.ID, 7, o.Host, o.Port, exp)
	// non è una sonda
	if err := tunnelVerify(cfg, st, o); err == nil || !strings.Contains(err.Error(), "non è una sonda") {
		t.Fatalf("atteso rifiuto (non sonda): %v", err)
	}
	probeApply(&Config{ServerURL: "http://127.0.0.1:1"}, State{}, &probeCfg{On: true, Ver: "x", Nets: []probeNet{{ID: 1, CIDR: "10.7.0.0/24"}}}, testLogger{})
	defer probeApply(cfg, st, &probeCfg{On: false}, testLogger{})
	if err := tunnelVerify(cfg, st, o); err != nil {
		t.Fatalf("richiesta valida rifiutata: %v", err)
	}
	// firma sull'host: cambiare l'host la invalida
	o2 := *o
	o2.Host = "10.7.0.2"
	if err := tunnelVerify(cfg, st, &o2); err == nil || !strings.Contains(err.Error(), "firma") {
		t.Fatalf("host alterato: %v", err)
	}
	// rete non servita
	o3 := &TunnelOffer{ID: o.ID, Port: 443, Exp: exp, Host: "10.8.0.1"}
	o3.Sig = signNet("k", o3.ID, 7, o3.Host, o3.Port, exp)
	if err := tunnelVerify(cfg, st, o3); err == nil || !strings.Contains(err.Error(), "non è in una rete servita") {
		t.Fatalf("rete non servita: %v", err)
	}
	// porta non ammessa
	o4 := &TunnelOffer{ID: o.ID, Port: 23, Exp: exp, Host: "10.7.0.1"}
	o4.Sig = signNet("k", o4.ID, 7, o4.Host, o4.Port, exp)
	if err := tunnelVerify(cfg, st, o4); err == nil || !strings.Contains(err.Error(), "non ammessa") {
		t.Fatalf("porta 23: %v", err)
	}
	// scaduta
	o5 := &TunnelOffer{ID: o.ID, Port: 443, Exp: time.Now().Add(-time.Second).Unix(), Host: "10.7.0.1"}
	o5.Sig = signNet("k", o5.ID, 7, o5.Host, o5.Port, o5.Exp)
	if err := tunnelVerify(cfg, st, o5); err == nil || !strings.Contains(err.Error(), "scaduta") {
		t.Fatalf("scaduta: %v", err)
	}
	// disattivati sul device
	off := &Config{JobSigningKey: "k", TunnelNet: "off"}
	if err := tunnelVerify(off, st, o); err == nil || !strings.Contains(err.Error(), "tunnel_net") {
		t.Fatalf("tunnel_net off: %v", err)
	}
	// il vecchio formato di firma (senza host) non vale per una richiesta con host
	m := hmac.New(sha256.New, []byte("k"))
	fmt.Fprintf(m, "tunnel\n%s\n%d\n%d\n%d", o.ID, 7, o.Port, exp)
	o6 := *o
	o6.Sig = hex.EncodeToString(m.Sum(nil))
	if err := tunnelVerify(cfg, st, &o6); err == nil {
		t.Fatal("la firma senza host non deve valere")
	}
	// porte personalizzate
	cp := &Config{JobSigningKey: "k", NetTunnelPorts: []int{23}}
	if err := tunnelVerify(cp, st, o4); err != nil {
		t.Fatalf("porta 23 con net_tunnel_ports: %v", err)
	}
}

func hs(t *testing.T, client func(c net.Conn), dest string) error {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	done := make(chan struct{})
	go func() { client(b); close(done) }()
	err := proxyHandshake(a, dest)
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("il client di prova non ha terminato")
	}
	return err
}

func socksReq(c net.Conn, atyp byte, host string, port int) []byte {
	c.Write([]byte{5, 1, 0})
	r := make([]byte, 2)
	c.Read(r)
	req := []byte{5, 1, 0, atyp}
	if atyp == 1 {
		req = append(req, net.ParseIP(host).To4()...)
	} else {
		req = append(req, byte(len(host)))
		req = append(req, host...)
	}
	req = binary.BigEndian.AppendUint16(req, uint16(port))
	c.Write(req)
	rep := make([]byte, 10)
	c.Read(rep)
	return rep
}

func TestProxySocks5(t *testing.T) {
	var rep []byte
	err := hs(t, func(c net.Conn) { rep = socksReq(c, 1, "10.7.0.1", 443) }, "10.7.0.1:443")
	if err != nil || rep[1] != 0 {
		t.Fatalf("socks5 IPv4 consentito: err=%v rep=%v", err, rep)
	}
	err = hs(t, func(c net.Conn) { rep = socksReq(c, 3, "10.7.0.1", 443) }, "10.7.0.1:443")
	if err != nil {
		t.Fatalf("socks5 con nome/IP testuale: %v", err)
	}
	err = hs(t, func(c net.Conn) { rep = socksReq(c, 1, "10.7.0.9", 443) }, "10.7.0.1:443")
	if err == nil || rep[1] != 2 {
		t.Fatalf("altro host deve essere negato: err=%v rep=%v", err, rep)
	}
	err = hs(t, func(c net.Conn) { rep = socksReq(c, 1, "10.7.0.1", 80) }, "10.7.0.1:443")
	if err == nil || rep[1] != 2 {
		t.Fatalf("altra porta deve essere negata: err=%v rep=%v", err, rep)
	}
}

func TestProxyHTTPConnect(t *testing.T) {
	var resp string
	do := func(line string) error {
		return hs(t, func(c net.Conn) {
			fmt.Fprintf(c, "%s\r\nHost: x\r\n\r\n", line)
			resp, _ = bufio.NewReader(c).ReadString('\n')
		}, "10.7.0.1:443")
	}
	if err := do("CONNECT 10.7.0.1:443 HTTP/1.1"); err != nil || !strings.Contains(resp, "200") {
		t.Fatalf("CONNECT consentito: %v %q", err, resp)
	}
	if err := do("CONNECT 10.7.0.1:8080 HTTP/1.1"); err == nil || !strings.Contains(resp, "403") {
		t.Fatalf("CONNECT su altra porta: %v %q", err, resp)
	}
	if err := do("CONNECT evil.example:443 HTTP/1.1"); err == nil {
		t.Fatal("CONNECT verso altro host deve fallire")
	}
	err := hs(t, func(c net.Conn) {
		fmt.Fprintf(c, "GET http://10.7.0.1/ HTTP/1.1\r\n\r\n")
		resp, _ = bufio.NewReader(c).ReadString('\n')
	}, "10.7.0.1:443")
	if err == nil || !strings.Contains(resp, "501") {
		t.Fatalf("proxy HTTP semplice non supportato: %v %q", err, resp)
	}
}

func TestIPInCIDR(t *testing.T) {
	if !ipInCIDR("10.7.0.200", "10.7.0.0/24") || ipInCIDR("10.7.1.1", "10.7.0.0/24") || ipInCIDR("::1", "10.0.0.0/8") || ipInCIDR("x", "10.0.0.0/8") {
		t.Fatal("ipInCIDR")
	}
}
