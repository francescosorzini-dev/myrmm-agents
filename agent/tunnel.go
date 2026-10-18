package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/kardianos/service"
)

// Tunnel TCP attraverso il server (RDP/SSH/VNC).
//
//	operatore: «agent tunnel» apre 127.0.0.1:<porta> e inoltra i byte al relay del server
//	agent:     dopo una richiesta FIRMATA dalla console apre 127.0.0.1:<porta del device> e inoltra i byte in senso opposto
//
// L'agent si collega SOLO a 127.0.0.1, SOLO a porte ammesse (tunnel_ports) e SOLO con richiesta firmata e non scaduta.

// TunnelOffer: richiesta di apertura nell'heartbeat. Firma: HMAC("tunnel\n<id>\n<device_id>\n<porta>\n<scadenza>").
type TunnelOffer struct {
	ID   string `json:"id"`
	Port int    `json:"port"`
	Exp  int64  `json:"exp"`
	Sig  string `json:"sig"`
	Host string `json:"host,omitempty"` // 1.33: tunnel verso un apparato della LAN (solo sonde); vuoto = 127.0.0.1 del device
}

const tunChunk = 48 * 1024

var tunSeen sync.Map // id dei tunnel già gestiti da questo processo

func tunnelPortOK(cfg *Config, port int) bool {
	ports := cfg.TunnelPorts
	if len(ports) == 0 {
		ports = []int{3389, 22, 5900}
	}
	for _, p := range ports {
		if p == port {
			return true
		}
	}
	return false
}

func tunnelVerify(cfg *Config, st State, o *TunnelOffer) error {
	if cfg.JobSigningKey == "" {
		return errors.New("job_signing_key non configurata")
	}
	if strings.EqualFold(cfg.TunnelMode, "off") {
		return errors.New("tunnel disattivati su questo device (tunnel_mode)")
	}
	mac := hmac.New(sha256.New, []byte(cfg.JobSigningKey))
	if o.Host != "" {
		fmt.Fprintf(mac, "tunnelnet\n%s\n%d\n%s\n%d\n%d", o.ID, st.DeviceID, o.Host, o.Port, o.Exp)
	} else {
		fmt.Fprintf(mac, "tunnel\n%s\n%d\n%d\n%d", o.ID, st.DeviceID, o.Port, o.Exp)
	}
	if !hmac.Equal([]byte(hex.EncodeToString(mac.Sum(nil))), []byte(o.Sig)) {
		return errors.New("firma non valida")
	}
	if time.Now().Unix() >= o.Exp {
		return errors.New("richiesta scaduta")
	}
	if o.Host != "" {
		return tunnelNetOK(cfg, o)
	}
	if !tunnelPortOK(cfg, o.Port) {
		return fmt.Errorf("porta %d non ammessa (tunnel_ports)", o.Port)
	}
	return nil
}

// tunnelStart: chiamata dall'heartbeat; avvia il tunnel una sola volta per id.
func tunnelStart(cfg *Config, st State, o *TunnelOffer, log service.Logger) {
	if _, dup := tunSeen.LoadOrStore(o.ID, true); dup {
		return
	}
	r := newRelay(cfg.ServerURL, o.ID, "ag", "X-Device-Key", st.APIKey)
	if err := tunnelVerify(cfg, st, o); err != nil {
		_ = log.Errorf("tunnel %s RIFIUTATO: %v", o.ID[:8], err)
		_ = r.ctl("failed", "rifiutato dall'agent: "+err.Error())
		return
	}
	go func() {
		_ = log.Infof("tunnel %s: apertura verso %s", o.ID[:8], tunnelDest(o))
		err := tunnelAgentRun(r, o)
		if err != nil {
			_ = log.Warningf("tunnel %s: %v", o.ID[:8], err)
		} else {
			_ = log.Infof("tunnel %s chiuso", o.ID[:8])
		}
	}()
}

// ---- più connessioni nello stesso tunnel ---------------------------------------------------------
// Ogni blocco inviato al relay inizia con un'intestazione di 5 byte: id della connessione (uint32) + tipo (0 dati, 1 apertura, 2 chiusura).
// mstsc, ad esempio, dopo l'accettazione del certificato chiude la prima connessione TCP e ne apre una seconda.
const (
	tfData  = 0
	tfOpen  = 1
	tfClose = 2
)

func encodeFrame(cid uint32, typ byte, p []byte) []byte {
	b := make([]byte, 5+len(p))
	binary.BigEndian.PutUint32(b, cid)
	b[4] = typ
	copy(b[5:], p)
	return b
}

func decodeFrame(b []byte) (cid uint32, typ byte, p []byte, ok bool) {
	if len(b) < 5 {
		return 0, 0, nil, false
	}
	return binary.BigEndian.Uint32(b), b[4], b[5:], true
}

type mux struct {
	r      *relay
	mu     sync.Mutex
	conns  map[uint32]net.Conn
	wg     sync.WaitGroup
	idleAt time.Time // da quando non ci sono connessioni aperte (zero = ce ne sono)
	ever   bool      // c'è stata almeno una connessione
}

func newMux(r *relay) *mux { return &mux{r: r, conns: map[uint32]net.Conn{}, idleAt: time.Now()} }

func (m *mux) add(cid uint32, c net.Conn) {
	m.mu.Lock()
	m.conns[cid] = c
	m.ever = true
	m.idleAt = time.Time{}
	m.mu.Unlock()
}

// drop chiude e dimentica la connessione; true se esisteva.
func (m *mux) drop(cid uint32) bool {
	m.mu.Lock()
	c, ok := m.conns[cid]
	delete(m.conns, cid)
	if len(m.conns) == 0 {
		m.idleAt = time.Now()
	}
	m.mu.Unlock()
	if ok {
		c.Close()
	}
	return ok
}

// idleFor: da quanto tempo non ci sono connessioni (0 se ce ne sono) e se ce n'è mai stata una.
func (m *mux) idleFor() (time.Duration, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.idleAt.IsZero() {
		return time.Since(m.idleAt), m.ever
	}
	return 0, m.ever
}

func (m *mux) closeAll() {
	m.mu.Lock()
	cs := make([]net.Conn, 0, len(m.conns))
	for _, c := range m.conns {
		cs = append(cs, c)
	}
	m.conns = map[uint32]net.Conn{}
	m.mu.Unlock()
	for _, c := range cs {
		c.Close()
	}
	m.wg.Wait()
}

// pump: dalla connessione locale al relay; alla fine invia la chiusura.
func (m *mux) pump(cid uint32, c net.Conn) {
	m.wg.Add(1)
	go func() {
		defer m.wg.Done()
		buf := make([]byte, tunChunk)
		for {
			n, err := c.Read(buf)
			if n > 0 {
				if m.r.send(encodeFrame(cid, tfData, buf[:n])) != nil {
					m.drop(cid)
					return
				}
			}
			if err != nil {
				if m.drop(cid) { // chiusa dal lato locale: avvisa l'altro capo
					_ = m.r.send(encodeFrame(cid, tfClose, nil))
				}
				return
			}
		}
	}()
}

// deliver: un blocco arrivato dal relay verso la connessione locale (dati o chiusura).
func (m *mux) deliver(cid uint32, typ byte, p []byte) {
	m.mu.Lock()
	c := m.conns[cid]
	m.mu.Unlock()
	if c == nil {
		return
	}
	if typ == tfClose {
		m.drop(cid)
		return
	}
	if _, err := c.Write(p); err != nil {
		if m.drop(cid) {
			_ = m.r.send(encodeFrame(cid, tfClose, nil))
		}
	}
}

func tunnelAgentRun(r *relay, o *TunnelOffer) error {
	if err := r.ctl("ready", ""); err != nil {
		return err
	}
	m := newMux(r)
	defer m.closeAll()
	var ack uint64
	connected := false
	for time.Now().Unix() < o.Exp {
		t0 := time.Now()
		frames, closed, _, err := r.recv(ack, 10, true)
		if err != nil {
			if errors.Is(err, errRelayGone) {
				return nil
			}
			time.Sleep(time.Second)
			continue
		}
		if len(frames) == 0 && !closed {
			politePause(t0) // server senza long-poll (TUNNEL_WAIT_MAX=0): niente giri a vuoto
		}
		for _, f := range frames {
			ack = f.id
			cid, typ, p, ok := decodeFrame(f.data)
			if !ok {
				continue
			}
			if typ != tfOpen {
				m.deliver(cid, typ, p)
				continue
			}
			c, derr := net.DialTimeout("tcp", tunnelDest(o), 5*time.Second)
			if derr != nil {
				_ = r.send(encodeFrame(cid, tfClose, nil))
				if !connected {
					_ = r.ctl("failed", fmt.Sprintf("%s non raggiungibile: %s", tunnelDest(o), netErrText(derr)))
					return derr
				}
				continue
			}
			m.add(cid, c)
			m.pump(cid, c)
			if !connected {
				connected = true
				_ = r.ctl("connected", "")
			}
		}
		if closed {
			return nil
		}
	}
	_ = r.ctl("closed", "scaduto")
	return nil
}

// politePause: se una richiesta di attesa è tornata subito a vuoto (server senza long-poll) attende un po' prima della prossima.
func politePause(t0 time.Time) {
	if d := 150*time.Millisecond - time.Since(t0); d > 0 {
		time.Sleep(d)
	}
}

// ---- client del relay (usato da agent e helper) --------------------------------------------------

var errRelayGone = errors.New("tunnel chiuso")

type frame struct {
	id   uint64
	data []byte
}

type relay struct {
	base, id, role, hdrName, hdrVal string
	hc                              *http.Client
}

func newRelay(base, id, role, hdrName, hdrVal string) *relay {
	return &relay{base: base, id: id, role: role, hdrName: hdrName, hdrVal: hdrVal, hc: &http.Client{Timeout: 45 * time.Second}}
}

func (r *relay) url(action string, extra url.Values) string {
	q := url.Values{"action": {action}, "id": {r.id}, "role": {r.role}}
	for k, v := range extra {
		q[k] = v
	}
	sep := "?"
	if strings.Contains(r.base, "?") {
		sep = "&"
	}
	return r.base + sep + q.Encode()
}

func (r *relay) do(method, u string, body []byte) (*http.Response, []byte, error) {
	req, err := http.NewRequest(method, u, bytes.NewReader(body))
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set(r.hdrName, r.hdrVal)
	if method == http.MethodPost {
		req.Header.Set("Content-Type", "application/octet-stream")
	}
	resp, err := r.hc.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	return resp, data, err
}

// send: un blocco verso il lato opposto; con il relay pieno (429) attende e riprova.
func (r *relay) send(b []byte) error {
	for tries := 0; tries < 600; tries++ {
		resp, data, err := r.do(http.MethodPost, r.url("tun_send", nil), b)
		if err != nil {
			time.Sleep(500 * time.Millisecond)
			continue
		}
		switch {
		case resp.StatusCode == http.StatusOK:
			return nil
		case resp.StatusCode == http.StatusTooManyRequests:
			time.Sleep(100 * time.Millisecond)
		case resp.StatusCode == http.StatusGone:
			return errRelayGone
		default:
			return fmt.Errorf("relay: HTTP %d %s", resp.StatusCode, strings.TrimSpace(string(data)))
		}
	}
	return errors.New("relay: troppi tentativi")
}

// recv: blocchi con id > ack (long-poll). closed = tunnel chiuso; opConn = l'operatore ha aperto la connessione.
func (r *relay) recv(ack uint64, wait int, have bool) (frames []frame, closed, opConn bool, err error) {
	h := "0"
	if have {
		h = "1"
	}
	resp, data, err := r.do(http.MethodGet, r.url("tun_recv", url.Values{"ack": {strconv.FormatUint(ack, 10)}, "wait": {strconv.Itoa(wait)}, "have": {h}}), nil)
	if err != nil {
		return nil, false, false, err
	}
	if resp.StatusCode == http.StatusNotFound || resp.StatusCode == http.StatusForbidden {
		return nil, true, false, errRelayGone
	}
	if resp.StatusCode != http.StatusOK {
		return nil, false, false, fmt.Errorf("relay: HTTP %d", resp.StatusCode)
	}
	closed = resp.Header.Get("X-Tun-State") == "closed"
	opConn = resp.Header.Get("X-Tun-Conn") == "1"
	for len(data) >= 12 {
		id := binary.BigEndian.Uint64(data[:8])
		n := int(binary.BigEndian.Uint32(data[8:12]))
		if n < 0 || 12+n > len(data) {
			return nil, false, false, errors.New("relay: risposta troncata")
		}
		frames = append(frames, frame{id: id, data: data[12 : 12+n]})
		data = data[12+n:]
	}
	return frames, closed, opConn, nil
}

func (r *relay) ctl(state, msg string) error {
	b, _ := json.Marshal(map[string]string{"state": state, "msg": msg})
	resp, _, err := r.do(http.MethodPost, r.url("tun_ctl", nil), b)
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("relay ctl: HTTP %d", resp.StatusCode)
	}
	return nil
}

// ---- helper sul PC dell'operatore: «agent tunnel» -------------------------------------------------

func tunnelClient(args []string) int {
	fs := flag.NewFlagSet("tunnel", flag.ContinueOnError)
	server := fs.String("u", "", "URL del server (index.php)")
	id := fs.String("id", "", "id del tunnel")
	token := fs.String("token", "", "token del tunnel")
	listen := fs.String("listen", "127.0.0.1:13389", "indirizzo locale (solo loopback)")
	rdp := fs.Bool("rdp", false, "avvia il client Desktop remoto (Windows: mstsc; macOS: app RDP; Linux: xfreerdp/Remmina)")
	vnc := fs.Bool("vnc", false, "avvia il client VNC / Condivisione schermo (macOS, Linux)")
	sshUser := fs.String("ssh", "", "avvia ssh con questo utente nel terminale e chiude il tunnel all'uscita")
	alias := fs.String("alias", "", "con -ssh: nome fisso con cui ricordare la chiave host del device")
	socks := fs.String("socks", "", "proxy locale SOCKS5/HTTP CONNECT (solo loopback) al posto della porta fissa: per le interfacce web degli apparati")
	dest := fs.String("dest", "", "con -socks: unica destinazione consentita (host:porta)")
	open := fs.String("open", "", "con -socks: avvia un browser Chromium con profilo dedicato verso questo indirizzo")
	wait := fs.Duration("wait", 5*time.Minute, "attesa massima della prima connessione locale")
	grace := fs.Duration("grace", 25*time.Second, "dopo l'ultima connessione chiusa, attesa prima di chiudere il tunnel (i client RDP si ricollegano)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *server == "" || *id == "" || *token == "" {
		fmt.Fprintln(os.Stderr, "uso: agent tunnel -u <URL index.php> -id <id> -token <token> [-listen 127.0.0.1:13389] [-rdp]")
		return 2
	}
	if *socks != "" {
		*listen = *socks
		if *dest == "" {
			fmt.Fprintln(os.Stderr, "con -socks serve -dest host:porta (l'unica destinazione consentita)")
			return 2
		}
	}
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || (host != "127.0.0.1" && host != "localhost" && host != "::1") {
		fmt.Fprintln(os.Stderr, "-listen e -socks devono essere indirizzi di loopback (127.0.0.1): il tunnel non va esposto sulla rete")
		return 2
	}
	r := newRelay(*server, *id, "op", "X-Tunnel-Token", *token)
	if err := r.ctl("listening", ""); err != nil {
		fmt.Fprintln(os.Stderr, "tunnel non raggiungibile (token errato, scaduto o server non raggiungibile):", err)
		return 1
	}
	ln, err := net.Listen("tcp", *listen)
	if err != nil {
		fmt.Fprintln(os.Stderr, "impossibile ascoltare su", *listen+":", err)
		_ = r.ctl("closed", "porta locale occupata")
		return 1
	}
	defer ln.Close()
	if *socks != "" {
		fmt.Println("Proxy pronto su", ln.Addr(), "(SOCKS5 / HTTP CONNECT) verso", *dest, "- imposta questo proxy nel browser. Ctrl+C per chiudere.")
		if *open != "" {
			if err := openBrowserProxy(*open, ln.Addr().String()); err != nil {
				fmt.Fprintln(os.Stderr, err)
			}
		}
	} else {
		fmt.Println("Tunnel pronto su", ln.Addr(), "- collega qui il client (mstsc /v:"+ln.Addr().String()+" oppure ssh -p ... utente@127.0.0.1). Ctrl+C per chiudere.")
	}
	m := newMux(r)
	done := make(chan struct{})
	var once sync.Once
	stop := func() { once.Do(func() { close(done) }) }
	if *socks == "" {
		if *rdp {
			openRDP(ln.Addr().String())
		}
		if *vnc {
			openVNC(ln.Addr().String())
		}
		if *sshUser != "" {
			startSSH(ln.Addr().String(), *sshUser, *alias, stop)
		}
	}

	var cidN atomic.Uint32
	attach := func(c net.Conn) {
		cid := cidN.Add(1)
		m.add(cid, c)
		if r.send(encodeFrame(cid, tfOpen, nil)) != nil {
			m.drop(cid)
			stop()
			return
		}
		_ = r.ctl("connected", "")
		fmt.Println("Connessione", cid, "stabilita.")
		m.pump(cid, c)
	}
	go func() { // connessioni locali -> relay
		for {
			c, aerr := ln.Accept()
			if aerr != nil {
				stop()
				return
			}
			if *socks == "" {
				attach(c)
				continue
			}
			go func(c net.Conn) { // proxy: negoziazione fuori dal ciclo, così un client lento non blocca gli altri
				if herr := proxyHandshake(c, *dest); herr != nil {
					fmt.Fprintln(os.Stderr, "proxy:", herr)
					_ = c.Close()
					return
				}
				attach(c)
			}(c)
		}
	}()
	go func() { // relay -> connessioni locali
		defer stop()
		var ack uint64
		for {
			select {
			case <-done:
				return
			default:
			}
			t0 := time.Now()
			frames, closed, _, rerr := r.recv(ack, 10, true)
			if rerr != nil {
				if errors.Is(rerr, errRelayGone) {
					return
				}
				time.Sleep(time.Second)
				continue
			}
			if len(frames) == 0 && !closed {
				politePause(t0)
			}
			for _, f := range frames {
				ack = f.id
				if cid, typ, p, ok := decodeFrame(f.data); ok {
					m.deliver(cid, typ, p)
				}
			}
			if closed {
				return
			}
		}
	}()
	start := time.Now()
	tick := time.NewTicker(500 * time.Millisecond)
	defer tick.Stop()
loop:
	for {
		select {
		case <-done:
			break loop
		case <-tick.C:
			idle, ever := m.idleFor()
			if !ever && time.Since(start) > *wait {
				fmt.Fprintln(os.Stderr, "nessuna connessione locale entro il tempo massimo: tunnel chiuso")
				break loop
			}
			if ever && idle > *grace {
				break loop
			}
		}
	}
	stop()
	m.closeAll()
	_ = r.ctl("closed", "")
	fmt.Println("Tunnel chiuso.")
	return 0
}
