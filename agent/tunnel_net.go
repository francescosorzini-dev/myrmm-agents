package main

// Tunnel verso gli apparati della LAN passando dalla sonda (1.33).
//
// La sonda apre la connessione verso l'IP dell'apparato SOLO se: la richiesta è firmata dalla console, non è scaduta, l'agent è una sonda,
// l'IP cade in una delle reti che serve ora e la porta è fra quelle ammesse. L'indirizzo di destinazione è quello della richiesta firmata:
// non viene mai letto dai dati del tunnel.
//
// Sul PC dell'operatore l'helper può esporre il tunnel come porta locale (-listen) oppure come proxy locale (-socks): SOCKS5 e HTTP CONNECT
// su loopback, limitati all'unica destinazione del tunnel, così il browser usa l'indirizzo vero dell'apparato e redirect e link funzionano.

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

var defaultNetTunnelPorts = []int{22, 80, 443, 3389, 5900, 8080, 8443}

func tunnelDest(o *TunnelOffer) string {
	if o.Host == "" {
		return net.JoinHostPort("127.0.0.1", strconv.Itoa(o.Port))
	}
	return net.JoinHostPort(o.Host, strconv.Itoa(o.Port))
}

// ipInCIDR: l'IPv4 appartiene alla rete (forma 10.0.0.0/24).
func ipInCIDR(ip, cidr string) bool {
	_, n, err := net.ParseCIDR(cidr)
	p := net.ParseIP(ip)
	return err == nil && p != nil && p.To4() != nil && n.Contains(p)
}

// tunnelNetOK: controlli locali, indipendenti dalla console, per un tunnel verso un apparato.
func tunnelNetOK(cfg *Config, o *TunnelOffer) error {
	if strings.EqualFold(cfg.TunnelNet, "off") {
		return errors.New("tunnel verso gli apparati disattivati su questo device (tunnel_net)")
	}
	if probeVer() == "" {
		return errors.New("questo agent non è una sonda di rete")
	}
	ports := cfg.NetTunnelPorts
	if len(ports) == 0 {
		ports = defaultNetTunnelPorts
	}
	okp := false
	for _, p := range ports {
		if p == o.Port {
			okp = true
		}
	}
	if !okp {
		return fmt.Errorf("porta %d non ammessa per gli apparati (net_tunnel_ports)", o.Port)
	}
	for _, n := range probeSnapshot().Nets {
		if ipInCIDR(o.Host, n.CIDR) {
			return nil
		}
	}
	return fmt.Errorf("%s non è in una rete servita da questa sonda", o.Host)
}

// ---- proxy locale dell'helper -------------------------------------------------------------------

// proxyHandshake: negozia SOCKS5 (CONNECT) o HTTP CONNECT e consente SOLO la destinazione `dest` ("host:porta").
// Dopo il successo la connessione è pronta per inoltrare byte grezzi.
func proxyHandshake(c net.Conn, dest string) error {
	_ = c.SetDeadline(time.Now().Add(15 * time.Second))
	defer func() { _ = c.SetDeadline(time.Time{}) }()
	br := bufio.NewReader(c)
	b0, err := br.Peek(1)
	if err != nil {
		return err
	}
	var perr error
	switch {
	case b0[0] == 5:
		perr = socks5(br, c, dest)
	case b0[0] == 'C':
		perr = httpConnect(br, c, dest)
	default:
		_, _ = io.WriteString(c, "HTTP/1.1 501 Not Implemented\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nmyrmm: usa il browser con un proxy SOCKS5 (o HTTPS) verso questo indirizzo; i proxy HTTP semplici non sono supportati.\r\n")
		return errors.New("richiesta non supportata")
	}
	if perr == nil && br.Buffered() > 0 {
		return errors.New("dati prima della risposta del proxy")
	}
	return perr
}

func sameDest(host string, port int, dest string) bool {
	dh, dp, err := net.SplitHostPort(dest)
	return err == nil && strings.EqualFold(dh, host) && dp == strconv.Itoa(port)
}

func socks5(br *bufio.Reader, c net.Conn, dest string) error {
	h := make([]byte, 2)
	if _, err := io.ReadFull(br, h); err != nil {
		return err
	}
	if _, err := io.CopyN(io.Discard, br, int64(h[1])); err != nil { // metodi proposti: si risponde «nessuna autenticazione»
		return err
	}
	if _, err := c.Write([]byte{5, 0}); err != nil {
		return err
	}
	r := make([]byte, 4)
	if _, err := io.ReadFull(br, r); err != nil {
		return err
	}
	fail := func(code byte, why string) error {
		_, _ = c.Write([]byte{5, code, 0, 1, 0, 0, 0, 0, 0, 0})
		return errors.New(why)
	}
	if r[0] != 5 || r[1] != 1 {
		return fail(7, "solo il comando CONNECT è supportato")
	}
	var host string
	switch r[3] {
	case 1:
		a := make([]byte, 4)
		if _, err := io.ReadFull(br, a); err != nil {
			return err
		}
		host = net.IP(a).String()
	case 3:
		l, err := br.ReadByte()
		if err != nil {
			return err
		}
		a := make([]byte, l)
		if _, err := io.ReadFull(br, a); err != nil {
			return err
		}
		host = string(a)
	default:
		return fail(8, "tipo di indirizzo non supportato")
	}
	pb := make([]byte, 2)
	if _, err := io.ReadFull(br, pb); err != nil {
		return err
	}
	port := int(binary.BigEndian.Uint16(pb))
	if !sameDest(host, port, dest) {
		return fail(2, fmt.Sprintf("destinazione %s:%d non consentita da questo tunnel (solo %s)", host, port, dest))
	}
	_, err := c.Write([]byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0})
	return err
}

func httpConnect(br *bufio.Reader, c net.Conn, dest string) error {
	line, err := br.ReadString('\n')
	if err != nil {
		return err
	}
	f := strings.Fields(line)
	for { // intestazioni fino alla riga vuota
		l, err := br.ReadString('\n')
		if err != nil {
			return err
		}
		if strings.TrimSpace(l) == "" {
			break
		}
	}
	if len(f) < 2 || !strings.EqualFold(f[0], "CONNECT") {
		_, _ = io.WriteString(c, "HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
		return errors.New("solo CONNECT")
	}
	h, ps, err := net.SplitHostPort(f[1])
	p, _ := strconv.Atoi(ps)
	if err != nil || !sameDest(h, p, dest) {
		_, _ = io.WriteString(c, "HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
		return fmt.Errorf("destinazione %s non consentita da questo tunnel (solo %s)", f[1], dest)
	}
	_, err = io.WriteString(c, "HTTP/1.1 200 Connection established\r\n\r\n")
	return err
}

// openBrowserProxy avvia un browser basato su Chromium con un profilo dedicato che usa il proxy locale. I certificati
// autofirmati degli apparati sono la norma: il profilo può raggiungere solo la destinazione del tunnel, quindi l'avviso viene escluso.
func openBrowserProxy(url, socks string) error {
	var cands []string
	switch runtime.GOOS {
	case "windows":
		for _, base := range []string{os.Getenv("ProgramFiles(x86)"), os.Getenv("ProgramFiles"), os.Getenv("LocalAppData")} {
			if base == "" {
				continue
			}
			cands = append(cands, filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"), filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"))
		}
	case "darwin":
		cands = []string{"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"}
	default:
		for _, n := range []string{"google-chrome", "chromium", "chromium-browser", "microsoft-edge"} {
			if p, err := exec.LookPath(n); err == nil {
				cands = append(cands, p)
			}
		}
	}
	for _, exe := range cands {
		if st, err := os.Stat(exe); err != nil || st.IsDir() {
			continue
		}
		prof := filepath.Join(os.TempDir(), "myrmm-proxy-profile")
		return exec.Command(exe, "--proxy-server=socks5://"+socks, "--user-data-dir="+prof, "--no-first-run", "--no-default-browser-check", "--ignore-certificate-errors", url).Start()
	}
	return errors.New("nessun browser Chromium (Edge o Chrome) trovato: configura il proxy SOCKS5 " + socks + " nel tuo browser")
}
