package main

// Scoperta della rete (1.35): come Advanced IP Scanner / NetScan / Angry IP Scanner, ma dalla sonda e a intervalli
// impostati per singola sonda. Per ogni rete servita: ping sweep, tabella ARP (MAC e costruttore), nome DNS, porte
// standard aperte, titolo delle pagine web, banner SSH/FTP/SMTP e — se la rete ha le credenziali — identificazione SNMP.

import (
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/kardianos/service"
)

type foundPort struct {
	P   int    `json:"p"`
	Svc string `json:"s,omitempty"`
	Ban string `json:"b,omitempty"`
}

type foundSnmp struct {
	Cid     int    `json:"cid,omitempty"` // credenziale che ha risposto
	Name    string `json:"name,omitempty"`
	Descr   string `json:"descr,omitempty"`
	Obj     string `json:"oid,omitempty"`
	Profile string `json:"profile,omitempty"`
}

type foundHost struct {
	IP     string      `json:"ip"`
	MAC    string      `json:"mac,omitempty"`
	Vendor string      `json:"vendor,omitempty"`
	Name   string      `json:"name,omitempty"`
	Title  string      `json:"title,omitempty"`
	Ping   bool        `json:"ping,omitempty"`
	RTT    float64     `json:"rtt,omitempty"`
	Ports  []foundPort `json:"ports,omitempty"`
	Snmp   *foundSnmp  `json:"snmp,omitempty"`
	Kind   string      `json:"kind,omitempty"`
}

type foundNet struct {
	Net     int         `json:"net"`
	TS      int64       `json:"ts"`
	Took    int         `json:"took"` // secondi
	Scanned int         `json:"scanned"`
	Req     int         `json:"req,omitempty"`
	Cut     bool        `json:"cut,omitempty"` // rete troppo grande: scansionata solo in parte
	Hosts   []foundHost `json:"hosts"`
	Err     string      `json:"err,omitempty"`
}

var scanSt = struct {
	sync.Mutex
	running bool
	last    map[int]time.Time
	req     map[int]int
}{last: map[int]time.Time{}, req: map[int]int{}}

const scanMaxHosts = 4096

// probeScanTick: avvia (una alla volta) la scansione periodica o richiesta dalla console.
func probeScanTick(ctx context.Context, cfg *Config, st State, log service.Logger) {
	c := probeSnapshot()
	if len(c.Nets) == 0 {
		return
	}
	scanSt.Lock()
	if scanSt.running {
		scanSt.Unlock()
		return
	}
	var pick *probeNet
	for i := range c.Nets {
		n := c.Nets[i]
		if n.Scan > 0 && scanSt.req[n.ID] != n.Scan {
			pick = &n
			break
		}
		if c.ScanMin > 0 {
			last, ok := scanSt.last[n.ID]
			if !ok { // prima volta: parte dopo circa 90 s dall'avvio, per non pesare sul primo contatto
				scanSt.last[n.ID] = time.Now().Add(-time.Duration(c.ScanMin)*time.Minute + 90*time.Second)
			} else if time.Since(last) >= time.Duration(c.ScanMin)*time.Minute {
				pick = &n
				break
			}
		}
	}
	if pick == nil {
		scanSt.Unlock()
		return
	}
	scanSt.running = true
	scanSt.last[pick.ID] = time.Now()
	scanSt.req[pick.ID] = pick.Scan
	scanSt.Unlock()
	ports := c.ScanPorts
	go func(n probeNet) {
		defer func() { scanSt.Lock(); scanSt.running = false; scanSt.Unlock() }()
		defer func() {
			if r := recover(); r != nil {
				_ = log.Warningf("scansione rete %s: errore interno: %v", n.CIDR, r)
			}
		}()
		_ = log.Infof("scansione rete %s avviata (%d porte da cercare)", n.CIDR, len(ports))
		res := scanNet(ctx, n, ports)
		_ = log.Infof("scansione rete %s: %d apparati in %d s", n.CIDR, len(res.Hosts), res.Took)
		probeExtraAppend("found", res)
	}(*pick)
}

// cidrHosts: indirizzi utilizzabili (senza rete e broadcast per le reti ≥ /30), al massimo max.
func cidrHosts(cidr string, max int) ([]string, bool) {
	ip, nw, err := net.ParseCIDR(cidr)
	if err != nil || ip.To4() == nil {
		return nil, false
	}
	ones, bits := nw.Mask.Size()
	base := ipToU32(nw.IP.To4())
	size := uint64(1) << uint(bits-ones)
	var first, last uint64 = 0, size - 1
	if size > 2 {
		first, last = 1, size-2
	}
	var out []string
	for i := first; i <= last; i++ {
		if len(out) >= max {
			return out, true
		}
		out = append(out, u32ToIP(base+uint32(i)))
	}
	return out, false
}

func ipToU32(ip net.IP) uint32 {
	return uint32(ip[0])<<24 | uint32(ip[1])<<16 | uint32(ip[2])<<8 | uint32(ip[3])
}
func u32ToIP(v uint32) string { return fmt.Sprintf("%d.%d.%d.%d", v>>24, v>>16&255, v>>8&255, v&255) }

// parallel esegue fn su tutti gli elementi con al massimo conc attività insieme.
func parallel(ctx context.Context, items []string, conc int, fn func(string)) {
	sem := make(chan struct{}, conc)
	var wg sync.WaitGroup
	for _, it := range items {
		if ctx.Err() != nil {
			break
		}
		sem <- struct{}{}
		wg.Add(1)
		go func(it string) {
			defer func() { <-sem; wg.Done() }()
			fn(it)
		}(it)
	}
	wg.Wait()
}

var quickPorts = []int{22, 80, 443, 445, 3389}

func scanNet(ctx context.Context, n probeNet, ports []int) foundNet {
	t0 := time.Now()
	res := foundNet{Net: n.ID, TS: t0.Unix(), Req: n.Scan}
	hosts, cut := cidrHosts(n.CIDR, scanMaxHosts)
	if len(hosts) == 0 {
		res.Err = "rete non valida: " + n.CIDR
		return res
	}
	res.Cut, res.Scanned = cut, len(hosts)
	if len(ports) == 0 {
		ports = []int{21, 22, 23, 25, 53, 80, 110, 135, 139, 161, 389, 443, 445, 515, 631, 993, 1433, 3306, 3389, 5900, 8080, 8443, 9100}
	}
	var mu sync.Mutex
	found := map[string]*foundHost{}
	get := func(ip string) *foundHost {
		mu.Lock()
		defer mu.Unlock()
		h := found[ip]
		if h == nil {
			h = &foundHost{IP: ip}
			found[ip] = h
		}
		return h
	}
	inNet := func(ip string) bool { return ipInCIDR(ip, n.CIDR) }
	// 1) ping sweep
	parallel(ctx, hosts, 96, func(ip string) {
		if d, err := icmpPing(ip, 900*time.Millisecond); err == nil {
			h := get(ip)
			mu.Lock()
			h.Ping, h.RTT = true, float64(d.Microseconds())/1000
			mu.Unlock()
		}
	})
	// 2) ARP: trova anche chi non risponde al ping (firewall del PC) ma ha risposto a livello 2
	arp := readARP()
	for ip := range arp {
		if inNet(ip) {
			get(ip)
		}
	}
	// 3) chi non ha risposto: sondaggio rapido delle porte più comuni (reti fino a 1024 indirizzi)
	if len(hosts) <= 1024 {
		var silent []string
		mu.Lock()
		for _, ip := range hosts {
			if found[ip] == nil {
				silent = append(silent, ip)
			}
		}
		mu.Unlock()
		parallel(ctx, silent, 128, func(ip string) {
			for _, p := range quickPorts {
				if _, err := tcpCheck(ip, p, 500*time.Millisecond); err == nil {
					get(ip)
					return
				}
			}
		})
	}
	mu.Lock()
	var alive []string
	for ip := range found {
		alive = append(alive, ip)
	}
	mu.Unlock()
	sort.Slice(alive, func(a, b int) bool {
		return ipToU32(net.ParseIP(alive[a]).To4()) < ipToU32(net.ParseIP(alive[b]).To4())
	})
	if len(alive) > 1024 {
		alive, res.Cut = alive[:1024], true
	}
	// 4) porte standard + dettagli di ogni apparato
	parallel(ctx, alive, 24, func(ip string) {
		h := get(ip)
		var op []foundPort
		var pmu sync.Mutex
		var wg sync.WaitGroup
		sem := make(chan struct{}, 24)
		for _, p := range ports {
			wg.Add(1)
			sem <- struct{}{}
			go func(p int) {
				defer func() { <-sem; wg.Done() }()
				if _, err := tcpCheck(ip, p, 800*time.Millisecond); err == nil {
					pmu.Lock()
					op = append(op, foundPort{P: p, Svc: portService(p)})
					pmu.Unlock()
				}
			}(p)
		}
		wg.Wait()
		sort.Slice(op, func(a, b int) bool { return op[a].P < op[b].P })
		for i := range op {
			if b := portBanner(ip, op[i].P); b != "" {
				if isWebPort(op[i].P) {
					if h.Title == "" {
						h.Title = b
					}
				} else {
					op[i].Ban = b
				}
			}
		}
		h.Ports = op
		h.Name = reverseDNS(ip)
		if n.Snmp != nil && n.Snmp.V != "" {
			h.Snmp = snmpIdentify(ip, n.Snmp)
		}
	})
	// 5) MAC (ARP riletta dopo il traffico generato) e costruttore, tipo probabile
	arp = readARP()
	for _, ip := range alive {
		h := found[ip]
		if m := arp[ip]; m != "" {
			h.MAC, h.Vendor = m, macVendor(m)
		}
		h.Kind = guessKind(h)
		res.Hosts = append(res.Hosts, *h)
	}
	res.Took = int(time.Since(t0).Seconds())
	return res
}

func isWebPort(p int) bool {
	switch p {
	case 80, 8080, 443, 8443, 5000, 5001, 8000, 8081, 9443:
		return true
	}
	return false
}

func portService(p int) string {
	return map[int]string{21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3", 135: "RPC/WMI", 139: "NetBIOS", 161: "SNMP", 389: "LDAP", 443: "HTTPS", 445: "SMB", 515: "LPD", 631: "IPP", 993: "IMAPS", 1433: "SQL Server", 3306: "MySQL", 3389: "RDP", 5900: "VNC", 8080: "HTTP alt", 8443: "HTTPS alt", 9100: "stampa RAW"}[p]
}

var titleRe = regexp.MustCompile(`(?is)<title[^>]*>(.*?)</title>`)

// portBanner: SSH/FTP/SMTP → prima riga; web → titolo della pagina (o intestazione Server).
func portBanner(ip string, p int) string {
	switch p {
	case 22, 21, 25, 110:
		c, err := net.DialTimeout("tcp", net.JoinHostPort(ip, strconv.Itoa(p)), 800*time.Millisecond)
		if err != nil {
			return ""
		}
		defer c.Close()
		_ = c.SetReadDeadline(time.Now().Add(1200 * time.Millisecond))
		b := make([]byte, 160)
		k, _ := c.Read(b)
		return cleanBanner(string(b[:k]))
	case 80, 8080, 443, 8443, 5000, 5001, 8000, 8081, 9443:
		scheme := "http"
		if p == 443 || p == 8443 || p == 5001 || p == 9443 {
			scheme = "https"
		}
		return webTitle(ip, p, scheme)
	}
	return ""
}

// webTitle: titolo della pagina iniziale (o intestazione Server / realm) di un servizio web.
func webTitle(ip string, p int, scheme string) string {
	cl := &http.Client{Timeout: 2500 * time.Millisecond, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, DisableKeepAlives: true, DialContext: (&net.Dialer{Timeout: 900 * time.Millisecond}).DialContext}}
	rs, err := cl.Get(scheme + "://" + net.JoinHostPort(ip, strconv.Itoa(p)) + "/")
	if err != nil {
		return ""
	}
	defer rs.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(rs.Body, 16384))
	if m := titleRe.FindSubmatch(body); m != nil {
		if t := cleanBanner(string(m[1])); t != "" {
			return t
		}
	}
	if s := rs.Header.Get("Server"); s != "" {
		return cleanBanner(s)
	}
	if a := rs.Header.Get("Www-Authenticate"); a != "" {
		if i := strings.Index(strings.ToLower(a), "realm="); i >= 0 {
			return cleanBanner(strings.Trim(a[i+6:], `" `))
		}
	}
	return ""
}

func cleanBanner(s string) string {
	s = strings.Join(strings.Fields(strings.Map(func(r rune) rune {
		if r < 32 || r == 127 {
			return ' '
		}
		return r
	}, s)), " ")
	if len(s) > 100 {
		s = s[:100]
	}
	return s
}

func reverseDNS(ip string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 1200*time.Millisecond)
	defer cancel()
	names, err := net.DefaultResolver.LookupAddr(ctx, ip)
	if err != nil || len(names) == 0 {
		return ""
	}
	return strings.TrimSuffix(names[0], ".")
}

// snmpIdentify: nome, descrizione e tipo di apparato via SNMP (risposta rapida: un solo tentativo).
func snmpIdentify(ip string, c *snmpCfg) *foundSnmp {
	if f := snmpIdentifyOne(ip, c); f != nil {
		f.Cid = c.CID
		return f
	}
	for i := range c.Alts {
		if f := snmpIdentifyOne(ip, &c.Alts[i]); f != nil {
			f.Cid = c.Alts[i].CID
			return f
		}
	}
	return nil
}

func snmpIdentifyOne(ip string, c *snmpCfg) *foundSnmp {
	cc := *c
	cc.Profile = ""
	s, err := snmpOpenT(ip, &cc, 900*time.Millisecond, 0)
	if err != nil {
		return nil
	}
	defer s.close()
	g, err := s.get(oSysDescr, oSysObjID, oSysName, oSysServices)
	if err != nil || len(g) == 0 {
		return nil
	}
	f := &foundSnmp{Name: pStr(g[oSysName]), Descr: pStr(g[oSysDescr]), Obj: pStr(g[oSysObjID])}
	if len(f.Descr) > 200 {
		f.Descr = f.Descr[:200]
	}
	f.Profile = snmpDetect(s, f.Descr, f.Obj, pInt(g[oSysServices]))
	return f
}

// readARP: tabella ARP del sistema (IP → MAC), solo voci complete.
func readARP() map[string]string {
	out := map[string]string{}
	if b, err := os.ReadFile("/proc/net/arp"); err == nil {
		for _, l := range strings.Split(string(b), "\n")[1:] {
			f := strings.Fields(l)
			if len(f) >= 4 && f[2] != "0x0" && f[3] != "00:00:00:00:00:00" {
				out[f[0]] = strings.ToLower(f[3])
			}
		}
		return out
	}
	arg := []string{"-an"}
	if runtime.GOOS == "windows" {
		arg = []string{"-a"}
	}
	o, err := exec.Command("arp", arg...).Output()
	if err != nil {
		return out
	}
	re := regexp.MustCompile(`(\d{1,3}(?:\.\d{1,3}){3}).*?([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})`)
	for _, l := range strings.Split(string(o), "\n") {
		if strings.Contains(l, "incomplete") {
			continue
		}
		if m := re.FindStringSubmatch(l); m != nil {
			mac := strings.ToLower(strings.ReplaceAll(m[2], "-", ":"))
			parts := strings.Split(mac, ":")
			for i, p := range parts {
				if len(p) == 1 {
					parts[i] = "0" + p
				}
			}
			mac = strings.Join(parts, ":")
			if mac != "ff:ff:ff:ff:ff:ff" && !strings.HasPrefix(mac, "01:00:5e") {
				out[m[1]] = mac
			}
		}
	}
	return out
}

// guessKind: tipo probabile dell'apparato da SNMP, porte, costruttore e pagina web. Orientativo.
func guessKind(h *foundHost) string {
	if h.Snmp != nil && h.Snmp.Profile != "" && h.Snmp.Profile != "generic" {
		return h.Snmp.Profile
	}
	has := map[int]bool{}
	for _, p := range h.Ports {
		has[p.P] = true
	}
	v := strings.ToLower(h.Vendor)
	t := strings.ToLower(h.Title + " " + h.Name)
	if has[9100] || has[631] || has[515] || strings.Contains(v, "brother") || strings.Contains(v, "canon") || strings.Contains(v, "epson") || strings.Contains(v, "ricoh") || strings.Contains(v, "kyocera") || strings.Contains(v, "xerox") || strings.Contains(v, "lexmark") ||
		strings.Contains(t, "printer") || strings.Contains(t, "stampante") || strings.Contains(t, "laserjet") {
		return "printer"
	}
	switch {
	case strings.Contains(v, "synology") || strings.Contains(v, "qnap") || strings.Contains(t, "synology") || strings.Contains(t, "qnap"):
		return "nas"
	case strings.Contains(v, "apc") || strings.Contains(t, " ups"):
		return "ups"
	case strings.Contains(v, "hikvision") || strings.Contains(v, "dahua") || strings.Contains(v, "axis") || has[554]:
		return "camera"
	case strings.Contains(v, "fortinet") || strings.Contains(v, "palo alto") || strings.Contains(t, "fortigate") || strings.Contains(t, "pfsense") || strings.Contains(t, "opnsense") || strings.Contains(t, "sonicwall"):
		return "firewall"
	case strings.Contains(v, "mikrotik") || strings.Contains(v, "cisco") || strings.Contains(v, "juniper") || strings.Contains(v, "aruba") || strings.Contains(v, "ubiquiti") || strings.Contains(v, "netgear") || strings.Contains(v, "tp-link") || strings.Contains(v, "d-link") || strings.Contains(v, "zyxel") || strings.Contains(v, "huawei"):
		if has[3389] || has[445] {
			return "windows"
		}
		return "net"
	case strings.Contains(v, "vmware") || strings.Contains(v, "hyper-v") || strings.Contains(v, "qemu") || strings.Contains(v, "virtualbox") || strings.Contains(v, "xen"):
		if has[3389] || has[445] {
			return "windows"
		}
		return "vm"
	case strings.Contains(v, "espressif") || strings.Contains(v, "sonos") || strings.Contains(v, "amazon") || strings.Contains(v, "google"):
		return "iot"
	case strings.Contains(v, "raspberry"):
		return "linux"
	case has[3389] || has[135] || has[445] && !has[22]:
		return "windows"
	case has[22]:
		return "linux"
	case strings.Contains(v, "apple"):
		return "apple"
	case strings.Contains(v, "casuale"):
		return "mobile"
	case has[80] || has[443] || has[8080] || has[8443]:
		return "web"
	}
	return "unknown"
}
