package main

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// Avvio del tunnel con un clic dalla console: la pagina del tunnel propone un collegamento myrmm-tunnel://open?...
// che il sistema dell'operatore passa a «agent tunnel-uri». Poiché un collegamento può essere scritto da chiunque
// (anche da una pagina web ostile), l'helper accetta solo server registrati prima dall'operatore con
// «agent tunnel-register -u <URL>» e controlla ogni parametro; il tunnel resta comunque solo su loopback.

const tunnelScheme = "myrmm-tunnel"

var (
	reTunnelID    = regexp.MustCompile(`^[A-Za-z0-9_-]{4,64}$`)
	reTunnelToken = regexp.MustCompile(`^[a-f0-9]{16,128}$`)
	reTunnelUser  = regexp.MustCompile(`^[A-Za-z0-9._][A-Za-z0-9._-]{0,63}$`)
	reTunnelAlias = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)
	reTunnelDest  = regexp.MustCompile(`^[A-Za-z0-9.-]{1,253}:[0-9]{1,5}$`)
)

func normServer(u string) string { return strings.TrimRight(strings.TrimSpace(u), "/") }

// tunnelStateDir: cartella dell'operatore (non quella dell'agent di servizio) con l'helper copiato e l'elenco dei server.
func tunnelStateDir() string {
	d, err := os.UserConfigDir()
	if err != nil || d == "" {
		d = os.TempDir()
	}
	return filepath.Join(d, "myrmm")
}

func tunnelServersFile() string { return filepath.Join(tunnelStateDir(), "tunnel-servers.txt") }

func tunnelServers() []string {
	b, _ := os.ReadFile(tunnelServersFile())
	var out []string
	for _, l := range strings.Split(string(b), "\n") {
		if l = normServer(l); l != "" {
			out = append(out, l)
		}
	}
	return out
}

func tunnelServerAdd(u string) error {
	u = normServer(u)
	pu, err := url.Parse(u)
	if err != nil || (pu.Scheme != "https" && pu.Scheme != "http") || pu.Host == "" {
		return errors.New("URL del server non valido (serve https://…/index.php)")
	}
	for _, s := range tunnelServers() {
		if s == u {
			return nil
		}
	}
	if err := os.MkdirAll(tunnelStateDir(), 0o700); err != nil {
		return err
	}
	f, err := os.OpenFile(tunnelServersFile(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(u + "\n")
	return err
}

// parseTunnelURI converte il collegamento in argomenti di «agent tunnel»; rifiuta tutto ciò che non è previsto.
func parseTunnelURI(raw string, allowed []string) ([]string, error) {
	pu, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || pu.Scheme != tunnelScheme || pu.Host != "open" {
		return nil, errors.New("collegamento non riconosciuto")
	}
	q := pu.Query()
	g := func(k string) string { return q.Get(k) }
	srv := normServer(g("u"))
	okSrv := false
	for _, a := range allowed {
		if a == srv {
			okSrv = true
		}
	}
	if !okSrv {
		return nil, fmt.Errorf("server non registrato su questo PC (%s): esegui prima «agent tunnel-register -u \"%s\"»", srv, srv)
	}
	if !reTunnelID.MatchString(g("id")) || !reTunnelToken.MatchString(g("token")) {
		return nil, errors.New("identificativo o token del tunnel non validi")
	}
	args := []string{"-u", srv, "-id", g("id"), "-token", g("token")}
	listen := g("listen")
	if listen == "" {
		listen = "127.0.0.1:13389"
	}
	host, port, err := net.SplitHostPort(listen)
	if err != nil || (host != "127.0.0.1" && host != "localhost" && host != "::1") || !regexp.MustCompile(`^[0-9]{2,5}$`).MatchString(port) {
		return nil, errors.New("l'indirizzo locale deve essere di loopback")
	}
	switch g("mode") {
	case "rdp":
		args = append(args, "-listen", listen, "-rdp")
	case "vnc":
		args = append(args, "-listen", listen, "-vnc")
	case "ssh":
		if !reTunnelUser.MatchString(g("ssh")) {
			return nil, errors.New("utente SSH non valido")
		}
		args = append(args, "-listen", listen, "-ssh", g("ssh"))
		if a := g("alias"); a != "" {
			if !reTunnelAlias.MatchString(a) {
				return nil, errors.New("alias non valido")
			}
			args = append(args, "-alias", a)
		}
	case "socks":
		if !reTunnelDest.MatchString(g("dest")) {
			return nil, errors.New("destinazione non valida")
		}
		args = append(args, "-socks", listen, "-dest", g("dest"))
		if o := g("open"); o != "" {
			ou, err := url.Parse(o)
			if err != nil || (ou.Scheme != "http" && ou.Scheme != "https") || ou.User != nil {
				return nil, errors.New("indirizzo da aprire non valido")
			}
			h, p := ou.Hostname(), ou.Port()
			if p == "" {
				p = map[string]string{"http": "80", "https": "443"}[ou.Scheme]
			}
			if h+":"+p != g("dest") {
				return nil, errors.New("l'indirizzo da aprire deve coincidere con la destinazione del tunnel")
			}
			args = append(args, "-open", o)
		}
	case "", "none":
		args = append(args, "-listen", listen)
	default:
		return nil, errors.New("modalità non valida")
	}
	return args, nil
}

// tunnelURIMain: «agent tunnel-uri <collegamento>».
func tunnelURIMain(args []string) int {
	if len(args) != 1 {
		fmt.Fprintln(os.Stderr, "uso: agent tunnel-uri myrmm-tunnel://open?…")
		return 2
	}
	a, err := parseTunnelURI(args[0], tunnelServers())
	if err != nil {
		fmt.Fprintln(os.Stderr, "myrmm:", err)
		pauseOnConsole()
		return 2
	}
	rc := tunnelClient(a)
	if rc != 0 {
		pauseOnConsole()
	}
	return rc
}

// tunnelRegisterMain: «agent tunnel-register -u <URL>»: ricorda il server e registra il collegamento myrmm-tunnel:// per questo utente.
func tunnelRegisterMain(args []string) int {
	srv := ""
	for i := 0; i+1 < len(args); i++ {
		if args[i] == "-u" {
			srv = args[i+1]
		}
	}
	if srv == "" {
		fmt.Fprintln(os.Stderr, "uso: agent tunnel-register -u <URL index.php>")
		return 2
	}
	if err := tunnelServerAdd(srv); err != nil {
		fmt.Fprintln(os.Stderr, "myrmm:", err)
		return 1
	}
	exe, err := installTunnelHelper()
	if err != nil {
		fmt.Fprintln(os.Stderr, "myrmm: copia dell'helper:", err)
		return 1
	}
	if err := registerTunnelScheme(exe); err != nil {
		fmt.Fprintln(os.Stderr, "myrmm: registrazione del collegamento:", err)
		return 1
	}
	fmt.Println("Registrato. Dalla pagina del tunnel il pulsante «Avvia sul mio PC» ora lancia l'helper:", exe)
	fmt.Println("Server consentito:", normServer(srv))
	return 0
}

// installTunnelHelper copia questo eseguibile nella cartella dell'operatore, così il collegamento funziona anche se si cancella il download.
func installTunnelHelper() (string, error) {
	self, err := os.Executable()
	if err != nil {
		return "", err
	}
	name := "myrmm-tunnel"
	if isWindows() {
		name += ".exe"
	}
	dst := filepath.Join(tunnelStateDir(), name)
	if sa, _ := filepath.Abs(self); sa == dst {
		return dst, nil
	}
	if err := os.MkdirAll(tunnelStateDir(), 0o700); err != nil {
		return "", err
	}
	b, err := os.ReadFile(self)
	if err != nil {
		return "", err
	}
	tmp := dst + ".new"
	if err := os.WriteFile(tmp, b, 0o700); err != nil {
		return "", err
	}
	_ = os.Remove(dst)
	return dst, os.Rename(tmp, dst)
}
