package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"testing"
	"time"
)

func signOffer(key string, id string, dev, port int, exp int64) string {
	m := hmac.New(sha256.New, []byte(key))
	fmt.Fprintf(m, "tunnel\n%s\n%d\n%d\n%d", id, dev, port, exp)
	return hex.EncodeToString(m.Sum(nil))
}

func TestTunnelVerify(t *testing.T) {
	cfg := &Config{JobSigningKey: "k"}
	st := State{DeviceID: 7}
	exp := time.Now().Add(time.Hour).Unix()
	good := &TunnelOffer{ID: "abc", Port: 3389, Exp: exp, Sig: signOffer("k", "abc", 7, 3389, exp)}
	if err := tunnelVerify(cfg, st, good); err != nil {
		t.Fatalf("richiesta valida rifiutata: %v", err)
	}
	cases := map[string]*TunnelOffer{
		"firma errata":      {ID: "abc", Port: 3389, Exp: exp, Sig: "00"},
		"porta alterata":    {ID: "abc", Port: 22, Exp: exp, Sig: good.Sig},
		"altro device":      {ID: "abc", Port: 3389, Exp: exp, Sig: signOffer("k", "abc", 8, 3389, exp)},
		"scaduta":           {ID: "abc", Port: 3389, Exp: time.Now().Add(-time.Minute).Unix(), Sig: signOffer("k", "abc", 7, 3389, time.Now().Add(-time.Minute).Unix())},
		"porta non ammessa": {ID: "abc", Port: 445, Exp: exp, Sig: signOffer("k", "abc", 7, 445, exp)},
	}
	for n, o := range cases {
		if tunnelVerify(cfg, st, o) == nil {
			t.Errorf("%s: la richiesta doveva essere rifiutata", n)
		}
	}
	if tunnelVerify(&Config{}, st, good) == nil {
		t.Error("senza job_signing_key la richiesta doveva essere rifiutata")
	}
	if tunnelVerify(&Config{JobSigningKey: "k", TunnelMode: "off"}, st, good) == nil {
		t.Error("con tunnel_mode=off la richiesta doveva essere rifiutata")
	}
	if err := tunnelVerify(&Config{JobSigningKey: "k", TunnelPorts: []int{3389}}, st, good); err != nil {
		t.Errorf("porta in lista rifiutata: %v", err)
	}
}

func TestFrameCodec(t *testing.T) {
	b := encodeFrame(0x01020304, tfData, []byte("ciao"))
	cid, typ, p, ok := decodeFrame(b)
	if !ok || cid != 0x01020304 || typ != tfData || string(p) != "ciao" {
		t.Fatalf("codec: %v %v %q %v", cid, typ, p, ok)
	}
	if _, _, _, ok := decodeFrame([]byte{1, 2}); ok {
		t.Fatal("blocco troppo corto accettato")
	}
}
