package main

import (
	"os"
	"strings"
	"testing"
)

const tuSrv = "https://rmm.example.com/index.php"
const tuTok = "0123456789abcdef0123456789abcdef"

func tuLink(extra string) string {
	return "myrmm-tunnel://open?u=" + strings.ReplaceAll(tuSrv, ":", "%3A") + "&id=abc123&token=" + tuTok + extra
}

func TestTunnelURIAccepts(t *testing.T) {
	al := []string{tuSrv}
	for name, c := range map[string]struct {
		link string
		want string
	}{
		"rdp":     {tuLink("&mode=rdp"), "-listen 127.0.0.1:13389 -rdp"},
		"vnc":     {tuLink("&mode=vnc&listen=127.0.0.1:13390"), "-listen 127.0.0.1:13390 -vnc"},
		"ssh":     {tuLink("&mode=ssh&ssh=tecnico&alias=myrmm-d5"), "-ssh tecnico -alias myrmm-d5"},
		"socks":   {tuLink("&mode=socks&listen=127.0.0.1:13380&dest=10.0.0.5:443&open=https%3A%2F%2F10.0.0.5%2F"), "-socks 127.0.0.1:13380 -dest 10.0.0.5:443 -open https://10.0.0.5/"},
		"nessuna": {tuLink(""), "-listen 127.0.0.1:13389"},
	} {
		a, err := parseTunnelURI(c.link, al)
		if err != nil {
			t.Errorf("%s: %v", name, err)
			continue
		}
		j := strings.Join(a, " ")
		if !strings.Contains(j, c.want) || !strings.HasPrefix(j, "-u "+tuSrv+" -id abc123 -token "+tuTok) {
			t.Errorf("%s: %q", name, j)
		}
	}
}

func TestTunnelURIRejects(t *testing.T) {
	al := []string{tuSrv}
	for name, l := range map[string]string{
		"server non registrato":   strings.Replace(tuLink("&mode=rdp"), "rmm.example.com", "evil.example.net", 1),
		"schema diverso":          strings.Replace(tuLink(""), "myrmm-tunnel", "http", 1),
		"host diverso":            strings.Replace(tuLink(""), "//open", "//run", 1),
		"token corto":             "myrmm-tunnel://open?u=" + tuSrv + "&id=abc123&token=abc",
		"token con maiuscole":     strings.Replace(tuLink(""), tuTok, "ABCDEF0123456789ABCDEF", 1),
		"id con caratteri strani": strings.Replace(tuLink(""), "abc123", "a%3Bb", 1),
		"listen non loopback":     tuLink("&mode=rdp&listen=0.0.0.0:13389"),
		"listen lan":              tuLink("&mode=rdp&listen=192.168.1.5:13389"),
		"ssh con opzione":         tuLink("&mode=ssh&ssh=-oProxyCommand%3Dcalc"),
		"ssh con spazio":          tuLink("&mode=ssh&ssh=a%20b"),
		"alias strano":            tuLink("&mode=ssh&ssh=ok&alias=a%20b"),
		"dest strana":             tuLink("&mode=socks&dest=a%3Bb:443"),
		"open diverso da dest":    tuLink("&mode=socks&dest=10.0.0.5:443&open=https%3A%2F%2Fevil.com%2F"),
		"open con file":           tuLink("&mode=socks&dest=10.0.0.5:443&open=file%3A%2F%2F%2Fc%3A%2Fx"),
		"modalita sconosciuta":    tuLink("&mode=exec"),
	} {
		if a, err := parseTunnelURI(l, al); err == nil {
			t.Errorf("%s: accettato %v", name, a)
		}
	}
	if _, err := parseTunnelURI(tuLink("&mode=rdp"), nil); err == nil {
		t.Error("senza server registrati deve rifiutare")
	}
}

func TestTunnelRegisterStoresServer(t *testing.T) {
	d := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", d)
	t.Setenv("APPDATA", d)
	t.Setenv("HOME", d)
	if err := tunnelServerAdd("ftp://x"); err == nil {
		t.Fatal("URL non http(s) accettato")
	}
	if err := tunnelServerAdd(tuSrv + "/"); err != nil {
		t.Fatal(err)
	}
	_ = tunnelServerAdd(tuSrv)
	s := tunnelServers()
	if len(s) != 1 || s[0] != tuSrv {
		t.Fatalf("server: %v", s)
	}
	fi, err := os.Stat(tunnelServersFile())
	if err != nil || fi.Mode().Perm()&0o077 != 0 && !isWindows() {
		t.Fatalf("permessi: %v %v", fi, err)
	}
}

func TestSameServer(t *testing.T) {
	cases := []struct {
		a, b string
		want bool
	}{
		{"https://rmm.example.org/index.php", "https://rmm.example.org", true},
		{"https://rmm.example.org/", "https://RMM.example.org/index.php", true},
		{"https://rmm.example.org/app/index.php", "https://rmm.example.org/app", true},
		{"https://rmm.example.org", "http://rmm.example.org", false},
		{"https://rmm.example.org", "https://evil.example.org", false},
		{"https://rmm.example.org/app", "https://rmm.example.org/other", false},
	}
	for _, c := range cases {
		if got := sameServer(c.a, c.b); got != c.want {
			t.Errorf("sameServer(%q,%q)=%v, atteso %v", c.a, c.b, got, c.want)
		}
	}
}

func TestParseTunnelURIAcceptsSameServerVariants(t *testing.T) {
	raw := "myrmm-tunnel://open?u=https%3A%2F%2Frmm.example.org%2Findex.php&id=abcd1234&token=0123456789abcdef0123&mode=rdp"
	if _, err := parseTunnelURI(raw, []string{"https://rmm.example.org"}); err != nil {
		t.Fatalf("server registrato senza index.php rifiutato: %v", err)
	}
	if _, err := parseTunnelURI(raw, []string{"https://altro.example.org"}); err == nil {
		t.Fatal("server non registrato accettato")
	}
}
