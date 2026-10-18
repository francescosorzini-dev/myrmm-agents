package main

// SNMP della sonda (1.34): interroga (polling, v2c/v3) gli apparati della LAN. Nessun OID da conoscere:
// la sonda riconosce il tipo di apparato dalla presenza dei MIB standard (stampante, switch, firewall, UPS, NAS, AP)
// e legge solo ciò che serve per quel tipo. Per tutto il resto c'è la «scansione apparato» (walk) da cui scegliere OID da seguire.

import (
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gosnmp/gosnmp"
)

type snmpCustom struct {
	Name string `json:"name"`
	OID  string `json:"oid"`
	Unit string `json:"unit,omitempty"`
}

// snmpCfg: credenziali e opzioni di un apparato (le credenziali arrivano dalla sottorete, cifrate in transito dal TLS dell'agent).
type snmpCfg struct {
	V       string       `json:"v"` // 2c | 3
	Comm    string       `json:"c,omitempty"`
	User    string       `json:"u,omitempty"`
	AuthP   string       `json:"ap,omitempty"` // MD5 | SHA | SHA256 | SHA512
	AuthK   string       `json:"ak,omitempty"`
	PrivP   string       `json:"pp,omitempty"` // DES | AES | AES192 | AES256
	PrivK   string       `json:"pk,omitempty"`
	Ctx     string       `json:"cx,omitempty"` // contesto v3 (di solito vuoto)
	Port    int          `json:"port,omitempty"`
	Profile string       `json:"profile,omitempty"` // auto | generic | printer | switch | firewall | ups | nas | ap
	Observe []int        `json:"obs,omitempty"`     // ifIndex osservati (controllo veloce)
	Custom  []snmpCustom `json:"cust,omitempty"`
	Fast    int          `json:"fast,omitempty"` // secondi del controllo veloce (0 = nessuno)
	Scan    int          `json:"scan,omitempty"` // numero della richiesta di scansione apparato
	CID     int          `json:"cid,omitempty"`  // identificativo della credenziale (per ricordare quale funziona)
	Alts    []snmpCfg    `json:"alts,omitempty"` // altre credenziali da provare, in ordine, se la prima non risponde
}

type snmpIf struct {
	I     int    `json:"i"`
	N     string `json:"n"`
	Alias string `json:"a,omitempty"`
	T     int    `json:"t"`
	Admin int    `json:"ad"`
	Oper  int    `json:"op"`
	Speed uint64 `json:"sp,omitempty"` // bit/s
	In    uint64 `json:"in,omitempty"` // bit/s (calcolati dalla sonda)
	Out   uint64 `json:"out,omitempty"`
	Errs  uint64 `json:"er,omitempty"` // errori totali
}

type snmpSup struct {
	N   string `json:"n"`
	Pct int    `json:"pct"` // -1 = non noto
	Cls int    `json:"cls,omitempty"`
}

type snmpData struct {
	Cid     int                `json:"cid,omitempty"` // credenziale che ha risposto
	Fast    bool               `json:"fast,omitempty"`
	Name    string             `json:"name,omitempty"`
	Descr   string             `json:"descr,omitempty"`
	ObjID   string             `json:"oid,omitempty"`
	Uptime  int64              `json:"up,omitempty"`
	Profile string             `json:"profile,omitempty"` // quello riconosciuto
	M       map[string]float64 `json:"m,omitempty"`       // misure da registrare (cpu, mem, disk, …)
	Info    map[string]string  `json:"info,omitempty"`    // serial, modello, pagine…
	If      []snmpIf           `json:"if,omitempty"`
	Sup     []snmpSup          `json:"sup,omitempty"`
	Alerts  []string           `json:"alerts,omitempty"` // avvisi dell'apparato stesso (stampante)
	Cust    []snmpCustVal      `json:"cust,omitempty"`
	Stor    []snmpStor         `json:"stor,omitempty"`
	Nbr     []snmpNbr          `json:"nbr,omitempty"` // vicini LLDP / CDP (chi è collegato a quale porta)
}

// snmpNbr: un vicino annunciato dall'apparato con LLDP o CDP.
type snmpNbr struct {
	LP    int    `json:"lp"`             // ifIndex della porta locale
	LN    string `json:"ln,omitempty"`   // nome della porta locale
	Name  string `json:"name,omitempty"` // nome del vicino (sysName / deviceId)
	Port  string `json:"port,omitempty"` // porta del vicino
	MAC   string `json:"mac,omitempty"`  // chassis id se è un MAC
	IP    string `json:"ip,omitempty"`
	Descr string `json:"descr,omitempty"`
	Proto string `json:"p"` // lldp | cdp
}

type snmpCustVal struct {
	Name string  `json:"name"`
	V    float64 `json:"v"`
	S    string  `json:"s,omitempty"`
	OK   bool    `json:"ok"`
}

type snmpStor struct {
	N     string `json:"n"`
	Pct   int    `json:"pct"`
	Total uint64 `json:"total"` // byte
	Kind  string `json:"k"`     // ram | disk
}

type snmpWalk struct {
	ID   int        `json:"id"`
	Scan int        `json:"scan"`
	OIDs [][]string `json:"oids"` // [oid, tipo, valore]
	Err  string     `json:"err,omitempty"`
	More bool       `json:"more,omitempty"`
}

const (
	oSysDescr    = ".1.3.6.1.2.1.1.1.0"
	oSysObjID    = ".1.3.6.1.2.1.1.2.0"
	oSysUp       = ".1.3.6.1.2.1.1.3.0"
	oSysName     = ".1.3.6.1.2.1.1.5.0"
	oSysServices = ".1.3.6.1.2.1.1.7.0"
	oIpForward   = ".1.3.6.1.2.1.4.1.0"
	oBridgePorts = ".1.3.6.1.2.1.17.1.2.0"
	oPrtSerial   = ".1.3.6.1.2.1.43.5.1.1.17.1"
	oPrtSupDesc  = ".1.3.6.1.2.1.43.11.1.1.6"
	oPrtSupMax   = ".1.3.6.1.2.1.43.11.1.1.8"
	oPrtSupLvl   = ".1.3.6.1.2.1.43.11.1.1.9"
	oPrtSupCls   = ".1.3.6.1.2.1.43.11.1.1.4"
	oPrtPages    = ".1.3.6.1.2.1.43.10.2.1.4.1.1"
	oPrtAlertSev = ".1.3.6.1.2.1.43.18.1.1.2"
	oPrtAlertDes = ".1.3.6.1.2.1.43.18.1.1.8"
	oHrPrnStatus = ".1.3.6.1.2.1.25.3.5.1.1.1"
	oHrCPU       = ".1.3.6.1.2.1.25.3.3.1.2"
	oHrStor      = ".1.3.6.1.2.1.25.2.3.1"
	oUcdCPUIdle  = ".1.3.6.1.4.1.2021.11.11.0"
	oUcdMemTot   = ".1.3.6.1.4.1.2021.4.5.0"
	oUcdMemAvail = ".1.3.6.1.4.1.2021.4.6.0"
	oUpsMib      = ".1.3.6.1.2.1.33.1.1.1.0"
	oIfTable     = ".1.3.6.1.2.1.2.2.1"
	oIfX         = ".1.3.6.1.2.1.31.1.1.1"
)

var errSNMPStop = errors.New("stop")

// ---- sessione

type snmpSess struct{ g *gosnmp.GoSNMP }

func snmpOpen(ip string, c *snmpCfg) (*snmpSess, error) { return snmpOpenT(ip, c, 3*time.Second, 1) }

func snmpOpenT(ip string, c *snmpCfg, to time.Duration, retries int) (*snmpSess, error) {
	port := c.Port
	if port == 0 {
		port = 161
	}
	g := &gosnmp.GoSNMP{Target: ip, Port: uint16(port), Timeout: to, Retries: retries, MaxRepetitions: 10, Transport: "udp"}
	if c.V == "3" {
		g.Version = gosnmp.Version3
		g.SecurityModel = gosnmp.UserSecurityModel
		g.ContextName = c.Ctx
		usm := &gosnmp.UsmSecurityParameters{UserName: c.User}
		g.MsgFlags = gosnmp.NoAuthNoPriv
		if c.AuthK != "" {
			g.MsgFlags = gosnmp.AuthNoPriv
			usm.AuthenticationPassphrase = c.AuthK
			switch strings.ToUpper(c.AuthP) {
			case "MD5":
				usm.AuthenticationProtocol = gosnmp.MD5
			case "SHA256":
				usm.AuthenticationProtocol = gosnmp.SHA256
			case "SHA512":
				usm.AuthenticationProtocol = gosnmp.SHA512
			default:
				usm.AuthenticationProtocol = gosnmp.SHA
			}
			if c.PrivK != "" {
				g.MsgFlags = gosnmp.AuthPriv
				usm.PrivacyPassphrase = c.PrivK
				switch strings.ToUpper(c.PrivP) {
				case "DES":
					usm.PrivacyProtocol = gosnmp.DES
				case "AES192":
					usm.PrivacyProtocol = gosnmp.AES192
				case "AES256":
					usm.PrivacyProtocol = gosnmp.AES256
				default:
					usm.PrivacyProtocol = gosnmp.AES
				}
			}
		}
		g.SecurityParameters = usm
	} else {
		g.Version = gosnmp.Version2c
		g.Community = c.Comm
	}
	if err := g.Connect(); err != nil {
		return nil, err
	}
	return &snmpSess{g: g}, nil
}

func (s *snmpSess) close() { _ = s.g.Conn.Close() }

func (s *snmpSess) get(oids ...string) (map[string]gosnmp.SnmpPDU, error) {
	out := map[string]gosnmp.SnmpPDU{}
	for i := 0; i < len(oids); i += 20 {
		j := i + 20
		if j > len(oids) {
			j = len(oids)
		}
		r, err := s.g.Get(oids[i:j])
		if err != nil {
			return out, err
		}
		for _, p := range r.Variables {
			if p.Type == gosnmp.NoSuchObject || p.Type == gosnmp.NoSuchInstance || p.Type == gosnmp.Null {
				continue
			}
			out[p.Name] = p
		}
	}
	return out, nil
}

// walk: tabella/sottoalbero, al massimo max variabili.
func (s *snmpSess) walk(oid string, max int) ([]gosnmp.SnmpPDU, error) {
	var out []gosnmp.SnmpPDU
	err := s.g.BulkWalk(oid, func(p gosnmp.SnmpPDU) error {
		if p.Type == gosnmp.EndOfMibView || p.Type == gosnmp.NoSuchObject || p.Type == gosnmp.NoSuchInstance {
			return nil
		}
		out = append(out, p)
		if len(out) >= max {
			return errSNMPStop
		}
		return nil
	})
	if errors.Is(err, errSNMPStop) {
		err = nil
	}
	return out, err
}

// col: colonna di una tabella → indice (parte dopo base) → valore.
func col(pdus []gosnmp.SnmpPDU, base string) map[string]gosnmp.SnmpPDU {
	m := map[string]gosnmp.SnmpPDU{}
	for _, p := range pdus {
		if strings.HasPrefix(p.Name, base+".") {
			m[strings.TrimPrefix(p.Name, base+".")] = p
		}
	}
	return m
}

// ---- conversioni

func pInt(p gosnmp.SnmpPDU) int64 {
	switch v := p.Value.(type) {
	case int:
		return int64(v)
	case int32:
		return int64(v)
	case int64:
		return v
	case uint:
		return int64(v)
	case uint32:
		return int64(v)
	case uint64:
		return int64(v)
	case []byte:
		n, _ := strconv.ParseInt(strings.TrimSpace(string(v)), 10, 64)
		return n
	}
	return 0
}

func pUint(p gosnmp.SnmpPDU) uint64 {
	if n := pInt(p); n > 0 {
		return uint64(n)
	}
	if v, ok := p.Value.(uint64); ok {
		return v
	}
	return 0
}

func pStr(p gosnmp.SnmpPDU) string {
	switch v := p.Value.(type) {
	case string:
		return strings.TrimSpace(v)
	case []byte:
		printable := true
		for _, b := range v {
			if (b < 32 && b != '\n' && b != '\t' && b != '\r') || b > 126 {
				printable = false
				break
			}
		}
		if printable {
			return strings.TrimSpace(string(v))
		}
		var sb strings.Builder
		for i, b := range v {
			if i > 0 {
				sb.WriteByte(':')
			}
			fmt.Fprintf(&sb, "%02x", b)
		}
		return sb.String()
	case nil:
		return ""
	}
	return fmt.Sprint(p.Value)
}

func pFloat(p gosnmp.SnmpPDU) (float64, bool) {
	switch v := p.Value.(type) {
	case int, int32, int64, uint, uint32, uint64:
		return float64(pInt(p)), true
	case float32:
		return float64(v), true
	case float64:
		return v, true
	case []byte:
		f, err := strconv.ParseFloat(strings.TrimSpace(string(v)), 64)
		return f, err == nil
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		return f, err == nil
	}
	return 0, false
}

// ---- riconoscimento del tipo di apparato

// snmpDetect: dal tipo di apparato dalla presenza dei MIB (non dal produttore). ordine: i più specifici per primi.
func snmpDetect(s *snmpSess, descr, objid string, services int64) string {
	d := strings.ToLower(descr)
	if strings.HasPrefix(objid, ".1.3.6.1.2.1.33") || strings.Contains(d, " ups") || strings.Contains(d, "uninterruptible") {
		return "ups"
	}
	if strings.HasPrefix(objid, ".1.3.6.1.4.1.6574") || strings.HasPrefix(objid, ".1.3.6.1.4.1.24681") ||
		strings.Contains(d, "synology") || strings.Contains(d, "qnap") || strings.Contains(d, "readynas") || strings.Contains(d, "truenas") {
		return "nas"
	}
	// presenza dei MIB: una sola GET con più OID, quelli assenti non tornano
	r, _ := s.get(oPrtSerial, ".1.3.6.1.2.1.43.11.1.1.6.1.1", oHrPrnStatus, oUpsMib, oIpForward, oBridgePorts)
	if len(r) > 0 {
		if _, ok := r[oUpsMib]; ok {
			return "ups"
		}
		_, a := r[oPrtSerial]
		_, b := r[".1.3.6.1.2.1.43.11.1.1.6.1.1"]
		_, c := r[oHrPrnStatus]
		if a || b || c {
			return "printer"
		}
	}
	if len(r) == 0 { // alcuni apparati rispondono solo a GETNEXT: prova la sottoalbero stampante
		if p, _ := s.walk(oPrtSupDesc, 1); len(p) > 0 {
			return "printer"
		}
	}
	for _, k := range []string{"access point", "wireless", "wlan", "unifi", "aruba ap", " ap "} {
		if strings.Contains(d, k) {
			return "ap"
		}
	}
	for _, k := range []string{"fortigate", "fortinet", "pfsense", "opnsense", "sonicwall", "sophos", "watchguard", "palo alto", "cisco asa", "firepower", "mikrotik", "routeros", "ubiquiti edge", "vyos", "juniper srx", "zyxel usg", "firewall", "router"} {
		if strings.Contains(d, k) {
			return "firewall"
		}
	}
	fw, _ := r[oIpForward]
	if pInt(fw) == 1 {
		return "firewall"
	}
	if bp, ok := r[oBridgePorts]; ok && pInt(bp) > 0 || services&2 != 0 && services&4 == 0 || strings.Contains(d, "switch") {
		return "switch"
	}
	return "generic"
}

// ---- stato in memoria per i contatori delle interfacce (calcolo dei bit/s)

type ifPrev struct {
	t       time.Time
	in, out uint64
}

var snmpPrev = struct {
	sync.Mutex
	m map[string]ifPrev
}{m: map[string]ifPrev{}}

func ifRate(tid, idx int, in, out uint64, now time.Time) (uint64, uint64) {
	k := fmt.Sprintf("%d/%d", tid, idx)
	snmpPrev.Lock()
	defer snmpPrev.Unlock()
	pr, ok := snmpPrev.m[k]
	snmpPrev.m[k] = ifPrev{now, in, out}
	if !ok {
		return 0, 0
	}
	dt := now.Sub(pr.t).Seconds()
	if dt < 1 || in < pr.in || out < pr.out { // azzeramento del contatore
		return 0, 0
	}
	return uint64(float64(in-pr.in) * 8 / dt), uint64(float64(out-pr.out) * 8 / dt)
}

// ---- interrogazione

// snmpPoll: lettura completa (full) o veloce (solo raggiungibilità, uptime e porte osservate).
// snmpWithWinner mette per prima la credenziale che ha funzionato l'ultima volta.
func snmpWithWinner(t probeTarget) probeTarget {
	if t.Snmp == nil || len(t.Snmp.Alts) == 0 {
		return t
	}
	snmpState.Lock()
	w, ok := snmpState.win[t.ID]
	snmpState.Unlock()
	if !ok || w == t.Snmp.CID {
		return t
	}
	for i, a := range t.Snmp.Alts {
		if a.CID != w {
			continue
		}
		first := *t.Snmp
		first.Alts = nil
		rest := []snmpCfg{first}
		rest = append(rest, t.Snmp.Alts[:i]...)
		rest = append(rest, t.Snmp.Alts[i+1:]...)
		n := a
		n.Port, n.Profile, n.Observe, n.Custom, n.Fast, n.Scan = first.Port, first.Profile, first.Observe, first.Custom, first.Fast, first.Scan
		n.Alts = rest
		t.Snmp = &n
		return t
	}
	return t
}

// snmpPoll prova la credenziale principale e, se non risponde, le alternative della rete/apparato; ricorda quella che funziona.
func snmpPoll(t probeTarget, full bool) probeResult {
	t = snmpWithWinner(t)
	r := snmpPollOne(t, full)
	if t.Snmp == nil {
		return r
	}
	if r.OK {
		if r.Snmp != nil {
			r.Snmp.Cid = t.Snmp.CID
		}
		return r
	}
	for i := range t.Snmp.Alts {
		a := t.Snmp.Alts[i]
		a.Port, a.Profile, a.Observe, a.Custom, a.Fast, a.Scan = t.Snmp.Port, t.Snmp.Profile, t.Snmp.Observe, t.Snmp.Custom, t.Snmp.Fast, t.Snmp.Scan
		a.Alts = nil
		tt := t
		tt.Snmp = &a
		if r2 := snmpPollOne(tt, full); r2.OK {
			snmpState.Lock()
			snmpState.win[t.ID] = a.CID
			snmpState.Unlock()
			if r2.Snmp != nil {
				r2.Snmp.Cid = a.CID
			}
			return r2
		}
	}
	return r
}

func snmpPollOne(t probeTarget, full bool) probeResult {
	r := probeResult{ID: t.ID, TS: time.Now().Unix()}
	c := t.Snmp
	if c == nil {
		r.Detail = "SNMP non configurato"
		return r
	}
	t0 := time.Now()
	s, err := snmpOpen(t.IP, c)
	if err != nil {
		r.Detail = "SNMP: " + err.Error()
		return r
	}
	defer s.close()
	d := &snmpData{Fast: !full}
	g, err := s.get(oSysDescr, oSysObjID, oSysUp, oSysName, oSysServices)
	if err != nil || len(g) == 0 {
		r.Detail = snmpErrText(err, c)
		return r
	}
	r.OK, r.RTT = true, float64(time.Since(t0).Microseconds())/1000
	d.Uptime = pInt(g[oSysUp]) / 100
	if !full {
		d.M = map[string]float64{"uptime": float64(d.Uptime)}
		if len(c.Observe) > 0 {
			var oo []string
			for _, i := range c.Observe {
				oo = append(oo, fmt.Sprintf("%s.8.%d", oIfTable, i), fmt.Sprintf("%s.7.%d", oIfTable, i), fmt.Sprintf("%s.2.%d", oIfTable, i))
			}
			v, _ := s.get(oo...)
			for _, i := range c.Observe {
				d.If = append(d.If, snmpIf{I: i, N: pStr(v[fmt.Sprintf("%s.2.%d", oIfTable, i)]), Oper: int(pInt(v[fmt.Sprintf("%s.8.%d", oIfTable, i)])), Admin: int(pInt(v[fmt.Sprintf("%s.7.%d", oIfTable, i)]))})
			}
		}
		r.Snmp = d
		return r
	}
	d.Name, d.Descr, d.ObjID = pStr(g[oSysName]), pStr(g[oSysDescr]), pStr(g[oSysObjID])
	if len(d.Descr) > 300 {
		d.Descr = d.Descr[:300]
	}
	prof := c.Profile
	if prof == "" || prof == "auto" {
		prof = snmpDetect(s, d.Descr, d.ObjID, pInt(g[oSysServices]))
	}
	d.Profile = prof
	d.M = map[string]float64{"uptime": float64(d.Uptime)}
	d.Info = map[string]string{}
	snmpIfaces(s, t.ID, c, d)
	snmpHost(s, d)
	switch prof {
	case "printer":
		snmpPrinter(s, d)
	case "switch":
		snmpSwitch(d)
	case "firewall":
		snmpFirewall(s, d)
	case "ups":
		snmpUPS(s, d)
	case "nas":
		snmpNAS(s, d)
	case "ap":
		snmpAP(s, d)
	}
	switch prof {
	case "switch", "firewall", "ap", "generic":
		snmpNeighbors(s, d)
	}
	snmpCustoms(s, c, d)
	r.Snmp = d
	return r
}

func snmpErrText(err error, c *snmpCfg) string {
	if err == nil {
		return "SNMP: nessuna risposta (community o utente errati, o SNMP non attivo)"
	}
	s := strings.ToLower(err.Error())
	switch {
	case strings.Contains(s, "timeout") || strings.Contains(s, "request timeout"):
		if c.V == "3" {
			return "SNMP: nessuna risposta (timeout; controlla utente, password e protocolli v3)"
		}
		return "SNMP: nessuna risposta (timeout; controlla community e che SNMP sia attivo sull'apparato)"
	case strings.Contains(s, "refused"):
		return "SNMP: porta rifiutata"
	case strings.Contains(s, "unknown user") || strings.Contains(s, "wrong digest") || strings.Contains(s, "authentication"):
		return "SNMP v3: autenticazione rifiutata (utente o password)"
	}
	return "SNMP: " + err.Error()
}

// snmpIfaces: tabella interfacce con velocità, stato e traffico.
func snmpIfaces(s *snmpSess, tid int, c *snmpCfg, d *snmpData) {
	desc, _ := s.walk(oIfTable+".2", 512)
	if len(desc) == 0 {
		return
	}
	typ, _ := s.walk(oIfTable+".3", 512)
	adm, _ := s.walk(oIfTable+".7", 512)
	opr, _ := s.walk(oIfTable+".8", 512)
	ine, _ := s.walk(oIfTable+".14", 512)
	oue, _ := s.walk(oIfTable+".20", 512)
	nm, _ := s.walk(oIfX+".1", 512)
	hsp, _ := s.walk(oIfX+".15", 512)
	hin, _ := s.walk(oIfX+".6", 512)
	hou, _ := s.walk(oIfX+".10", 512)
	al, _ := s.walk(oIfX+".18", 512)
	spd, _ := s.walk(oIfTable+".5", 512)
	cin, _ := s.walk(oIfTable+".10", 512)
	cou, _ := s.walk(oIfTable+".16", 512)
	cD, cT, cA, cO := col(desc, oIfTable+".2"), col(typ, oIfTable+".3"), col(adm, oIfTable+".7"), col(opr, oIfTable+".8")
	cIE, cOE := col(ine, oIfTable+".14"), col(oue, oIfTable+".20")
	cN, cH, cHI, cHO, cAl := col(nm, oIfX+".1"), col(hsp, oIfX+".15"), col(hin, oIfX+".6"), col(hou, oIfX+".10"), col(al, oIfX+".18")
	cS, cI, cOu := col(spd, oIfTable+".5"), col(cin, oIfTable+".10"), col(cou, oIfTable+".16")
	now := time.Now()
	keys := make([]string, 0, len(cD))
	for k := range cD {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(a, b int) bool { x, _ := strconv.Atoi(keys[a]); y, _ := strconv.Atoi(keys[b]); return x < y })
	var tin, tout uint64
	for _, k := range keys {
		idx, _ := strconv.Atoi(k)
		f := snmpIf{I: idx, N: pStr(cD[k]), T: int(pInt(cT[k])), Admin: int(pInt(cA[k])), Oper: int(pInt(cO[k]))}
		if n, ok := cN[k]; ok && pStr(n) != "" {
			f.N = pStr(n)
		}
		f.Alias = pStr(cAl[k])
		if h, ok := cH[k]; ok && pInt(h) > 0 {
			f.Speed = uint64(pInt(h)) * 1000000
		} else {
			f.Speed = pUint(cS[k])
		}
		in, out := pUint(cHI[k]), pUint(cHO[k])
		if _, ok := cHI[k]; !ok {
			in, out = pUint(cI[k]), pUint(cOu[k])
		}
		f.In, f.Out = ifRate(tid, idx, in, out, now)
		f.Errs = pUint(cIE[k]) + pUint(cOE[k])
		if f.T != 24 { // loopback escluso dal totale
			tin += f.In
			tout += f.Out
		}
		d.If = append(d.If, f)
	}
	d.M["in_bps"], d.M["out_bps"] = float64(tin), float64(tout)
	for _, i := range c.Observe { // traffico delle sole porte osservate, come misure a sé
		for _, f := range d.If {
			if f.I == i {
				d.M[fmt.Sprintf("if%d.in", i)], d.M[fmt.Sprintf("if%d.out", i)] = float64(f.In), float64(f.Out)
			}
		}
	}
}

// snmpHost: CPU, memoria e dischi dal Host-Resources MIB (o dal UCD-SNMP dei sistemi Linux/BSD).
func snmpHost(s *snmpSess, d *snmpData) {
	if cp, _ := s.walk(oHrCPU, 64); len(cp) > 0 {
		var sum float64
		for _, p := range cp {
			sum += float64(pInt(p))
		}
		d.M["cpu"] = math.Round(sum/float64(len(cp))*10) / 10
	} else if g, _ := s.get(oUcdCPUIdle); len(g) > 0 {
		d.M["cpu"] = float64(100 - pInt(g[oUcdCPUIdle]))
	}
	st, _ := s.walk(oHrStor, 400)
	if len(st) > 0 {
		cT, cD, cU, cS, cK := col(st, oHrStor+".2"), col(st, oHrStor+".3"), col(st, oHrStor+".4"), col(st, oHrStor+".5"), col(st, oHrStor+".6")
		worst := -1.0
		for k, tp := range cT {
			kind := ""
			switch strings.TrimPrefix(pStr(tp), ".") {
			case "1.3.6.1.2.1.25.2.1.2":
				kind = "ram"
			case "1.3.6.1.2.1.25.2.1.4":
				kind = "disk"
			default:
				continue
			}
			size, used, unit := pUint(cS[k]), pUint(cK[k]), pUint(cU[k])
			if size == 0 {
				continue
			}
			pct := int(math.Round(float64(used) * 100 / float64(size)))
			d.Stor = append(d.Stor, snmpStor{N: pStr(cD[k]), Pct: pct, Total: size * unit, Kind: kind})
			if kind == "ram" {
				d.M["mem"] = float64(pct)
			} else if float64(pct) > worst {
				worst = float64(pct)
			}
		}
		if worst >= 0 {
			d.M["disk"] = worst
		}
		sort.Slice(d.Stor, func(a, b int) bool { return d.Stor[a].N < d.Stor[b].N })
	}
	if _, ok := d.M["mem"]; !ok {
		if g, _ := s.get(oUcdMemTot, oUcdMemAvail); len(g) == 2 && pInt(g[oUcdMemTot]) > 0 {
			d.M["mem"] = math.Round(100 - float64(pInt(g[oUcdMemAvail]))*100/float64(pInt(g[oUcdMemTot])))
		}
	}
}

// snmpPrinter: toner/materiali di consumo, contatore pagine, matricola, avvisi dell'apparato.
func snmpPrinter(s *snmpSess, d *snmpData) {
	ds, _ := s.walk(oPrtSupDesc, 64)
	mx, _ := s.walk(oPrtSupMax, 64)
	lv, _ := s.walk(oPrtSupLvl, 64)
	cl, _ := s.walk(oPrtSupCls, 64)
	cDs, cMx, cLv, cCl := col(ds, oPrtSupDesc), col(mx, oPrtSupMax), col(lv, oPrtSupLvl), col(cl, oPrtSupCls)
	keys := make([]string, 0, len(cDs))
	for k := range cDs {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	low := 100
	for n, k := range keys {
		pct := -1
		level, max := pInt(cLv[k]), pInt(cMx[k])
		if max > 0 && level >= 0 {
			pct = int(level * 100 / max)
			if pct > 100 {
				pct = 100
			}
		} else if max == -1 || level == -3 { // «qualcosa rimane» (-3) senza una percentuale
			pct = -1
		}
		d.Sup = append(d.Sup, snmpSup{N: pStr(cDs[k]), Pct: pct, Cls: int(pInt(cCl[k]))})
		if pct >= 0 {
			d.M[fmt.Sprintf("sup%d", n+1)] = float64(pct)
			if pct < low {
				low = pct
			}
		}
	}
	if low < 100 {
		d.M["supply_min"] = float64(low)
	}
	if g, _ := s.get(oPrtPages, oPrtSerial, oHrPrnStatus); len(g) > 0 {
		if p, ok := g[oPrtPages]; ok {
			d.M["pages"] = float64(pInt(p))
		}
		if p, ok := g[oPrtSerial]; ok {
			d.Info["serial"] = pStr(p)
		}
		if p, ok := g[oHrPrnStatus]; ok {
			d.Info["state"] = map[int64]string{1: "altro", 2: "sconosciuto", 3: "inattiva", 4: "in stampa", 5: "riscaldamento"}[pInt(p)]
		}
	}
	sv, _ := s.walk(oPrtAlertSev, 40)
	de, _ := s.walk(oPrtAlertDes, 40)
	cSv, cDe := col(sv, oPrtAlertSev), col(de, oPrtAlertDes)
	for k, p := range cSv {
		if pInt(p) == 3 { // critico
			if t := pStr(cDe[k]); t != "" && len(d.Alerts) < 5 {
				d.Alerts = append(d.Alerts, t)
			}
		}
	}
	sort.Strings(d.Alerts)
	d.M["alerts"] = float64(len(d.Alerts))
}

func physIf(f snmpIf) bool {
	return f.T == 6 || f.T == 62 || f.T == 69 || f.T == 117 || f.T == 71 || f.T == 161
}

// snmpSwitch: porte fisiche attive/totali ed errori.
func snmpSwitch(d *snmpData) {
	up, tot := 0, 0
	var errs uint64
	for _, f := range d.If {
		if !physIf(f) || f.Admin == 2 {
			continue
		}
		tot++
		if f.Oper == 1 {
			up++
		}
		errs += f.Errs
	}
	d.M["ports_up"], d.M["ports_total"], d.M["if_errors"] = float64(up), float64(tot), float64(errs)
}

func snmpFirewall(s *snmpSess, d *snmpData) {
	up, tot := 0, 0
	for _, f := range d.If {
		if f.T == 24 || f.Admin == 2 {
			continue
		}
		tot++
		if f.Oper == 1 {
			up++
		}
	}
	d.M["ifs_up"], d.M["ifs_total"] = float64(up), float64(tot)
	if g, _ := s.get(oIpForward); len(g) > 0 {
		d.Info["routing"] = map[int64]string{1: "attivo", 2: "no"}[pInt(g[oIpForward])]
	}
}

// ---- UPS (UPS-MIB, RFC 1628)
func snmpUPS(s *snmpSess, d *snmpData) {
	const u = ".1.3.6.1.2.1.33.1."
	g, _ := s.get(u+"1.1.0", u+"1.2.0", u+"1.3.0", u+"2.1.0", u+"2.2.0", u+"2.3.0", u+"2.4.0", u+"2.5.0", u+"2.7.0", u+"4.1.0", u+"3.2.0")
	if v, ok := g[u+"1.1.0"]; ok {
		d.Info["marca"] = pStr(v)
	}
	if v, ok := g[u+"1.2.0"]; ok {
		d.Info["modello"] = pStr(v)
	}
	if v, ok := g[u+"1.3.0"]; ok {
		d.Info["firmware"] = pStr(v)
	}
	if v, ok := g[u+"2.1.0"]; ok { // 1 sconosciuto, 2 normale, 3 bassa, 4 scarica
		d.M["batt_status"] = float64(pInt(v))
		d.Info["batteria"] = map[int64]string{1: "sconosciuta", 2: "normale", 3: "bassa", 4: "scarica"}[pInt(v)]
	}
	if v, ok := g[u+"2.2.0"]; ok {
		d.M["secs_on_batt"] = float64(pInt(v))
	}
	if v, ok := g[u+"2.3.0"]; ok {
		d.M["runtime_min"] = float64(pInt(v))
	}
	if v, ok := g[u+"2.4.0"]; ok {
		d.M["batt_pct"] = float64(pInt(v))
	}
	if v, ok := g[u+"2.5.0"]; ok {
		d.M["batt_volt"] = float64(pInt(v)) / 10
	}
	if v, ok := g[u+"2.7.0"]; ok {
		d.M["batt_temp"] = float64(pInt(v))
	}
	if v, ok := g[u+"4.1.0"]; ok { // 3 normale (rete), 5 batteria, 4 booster, 6 riduttore, 2 nessuno, 1 altro
		src := pInt(v)
		d.Info["uscita"] = map[int64]string{1: "altro", 2: "nessuna", 3: "rete (normale)", 4: "booster", 5: "batteria", 6: "riduttore"}[src]
		if src == 5 {
			d.M["on_battery"] = 1
		} else {
			d.M["on_battery"] = 0
		}
	}
	if rows, _ := s.walk(u+"4.4.1.5", 8); len(rows) > 0 { // carico % per linea
		var mx int64
		for _, r := range rows {
			if x := pInt(r); x > mx {
				mx = x
			}
		}
		d.M["load_pct"] = float64(mx)
	}
	if rows, _ := s.walk(u+"3.3.1.3", 8); len(rows) > 0 {
		d.M["in_volt"] = float64(pInt(rows[0]))
	}
	if rows, _ := s.walk(u+"4.4.1.2", 8); len(rows) > 0 {
		d.M["out_volt"] = float64(pInt(rows[0]))
	}
}

// ---- NAS: Synology (MIB 6574) e QNAP (MIB 24681, solo stato di base); volumi e dischi li dà già hrStorage
func snmpNAS(s *snmpSess, d *snmpData) {
	const e = ".1.3.6.1.4.1.6574."
	g, _ := s.get(e+"1.1.0", e+"1.2.0", e+"1.3.0", e+"1.4.0", e+"1.5.1.0", e+"1.5.2.0", e+"1.5.3.0")
	if v, ok := g[e+"1.1.0"]; ok { // 1 normale, 2 guasto
		d.M["sys_bad"] = map[bool]float64{true: 1, false: 0}[pInt(v) != 1]
	}
	if v, ok := g[e+"1.2.0"]; ok {
		d.M["temp"] = float64(pInt(v))
	}
	for k, n := range map[string]string{e + "1.5.1.0": "modello", e + "1.5.2.0": "matricola", e + "1.5.3.0": "versione"} {
		if v, ok := g[k]; ok {
			d.Info[n] = pStr(v)
		}
	}
	dk, _ := s.walk(e+"2.1.1", 64)
	if len(dk) > 0 {
		cN, cS, cT := col(dk, e+"2.1.1.2"), col(dk, e+"2.1.1.5"), col(dk, e+"2.1.1.6")
		keys := make([]string, 0, len(cS))
		for k := range cS {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		bad, hot := 0, 0.0
		var names []string
		for _, k := range keys {
			st := pInt(cS[k]) // 1 normale, 2 inizializzato, 3 non inizializzato, 4 partizione di sistema guasta, 5 crashed
			if st >= 4 {
				bad++
				names = append(names, pStr(cN[k]))
			}
			if t := float64(pInt(cT[k])); t > hot {
				hot = t
			}
		}
		d.M["disks"] = float64(len(keys))
		d.M["disk_bad"] = float64(bad)
		if hot > 0 {
			d.M["disk_temp_max"] = hot
		}
		if len(names) > 0 {
			d.Info["dischi_anomali"] = strings.Join(names, ", ")
		}
	}
	rd, _ := s.walk(e+"3.1.1", 32)
	if len(rd) > 0 {
		cN, cS := col(rd, e+"3.1.1.2"), col(rd, e+"3.1.1.3")
		bad := 0
		var names []string
		for k, st := range cS {
			if x := pInt(st); x == 11 || x == 12 || x == 13 || x == 14 || x == 15 { // degradato / guasto
				bad++
				names = append(names, pStr(cN[k]))
			}
		}
		sort.Strings(names)
		d.M["raid_bad"] = float64(bad)
		if len(names) > 0 {
			d.Info["volumi_anomali"] = strings.Join(names, ", ")
		}
	}
}

// ---- Access point: clienti Wi-Fi collegati (UniFi, MikroTik)
func snmpAP(s *snmpSess, d *snmpData) {
	const uv = ".1.3.6.1.4.1.41112.1.6.1.1.1"
	if vp, _ := s.walk(uv, 64); len(vp) > 0 {
		cN, cC, cE, cS := col(vp, uv+".2"), col(vp, uv+".4"), col(vp, uv+".6"), col(vp, uv+".8")
		var tot int64
		var ssid []string
		keys := make([]string, 0, len(cS))
		for k := range cS {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			n := pInt(cS[k])
			tot += n
			lab := pStr(cE[k])
			if lab == "" {
				lab = pStr(cN[k])
			}
			ssid = append(ssid, fmt.Sprintf("%s (canale %d, %d client)", lab, pInt(cC[k]), n))
		}
		d.M["clients"] = float64(tot)
		d.Info["reti_wifi"] = strings.Join(ssid, "; ")
		return
	}
	if rows, _ := s.walk(".1.3.6.1.4.1.14988.1.1.1.3.1.6", 16); len(rows) > 0 { // MikroTik: client per interfaccia wireless
		var tot int64
		for _, r := range rows {
			tot += pInt(r)
		}
		d.M["clients"] = float64(tot)
	}
}

// ---- Vicini LLDP (IEEE 802.1AB) e CDP (Cisco): da chi è collegata ogni porta
const (
	oLldpRem = ".1.0.8802.1.1.2.1.4.1.1"
	oCdpRem  = ".1.3.6.1.4.1.9.9.23.1.2.1.1"
)

func snmpNeighbors(s *snmpSess, d *snmpData) {
	ifn := map[int]string{}
	for _, f := range d.If {
		ifn[f.I] = f.N
	}
	if rows, _ := s.walk(oLldpRem, 600); len(rows) > 0 {
		sub, ch, pid, pds, snm, sds := col(rows, oLldpRem+".4"), col(rows, oLldpRem+".5"), col(rows, oLldpRem+".7"), col(rows, oLldpRem+".8"), col(rows, oLldpRem+".9"), col(rows, oLldpRem+".10")
		keys := make([]string, 0, len(ch))
		for k := range ch {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys { // k = timeMark.localPort.index
			parts := strings.Split(k, ".")
			if len(parts) < 3 {
				continue
			}
			lp, _ := strconv.Atoi(parts[1])
			n := snmpNbr{LP: lp, LN: ifn[lp], Name: pStr(snm[k]), Port: pStr(pid[k]), Descr: pStr(sds[k]), Proto: "lldp"}
			if n.Port == "" {
				n.Port = pStr(pds[k])
			}
			if pInt(sub[k]) == 4 { // chassis id = MAC
				if b, ok := ch[k].Value.([]byte); ok && len(b) == 6 {
					n.MAC = fmt.Sprintf("%02x:%02x:%02x:%02x:%02x:%02x", b[0], b[1], b[2], b[3], b[4], b[5])
				}
			}
			if len(n.Descr) > 100 {
				n.Descr = n.Descr[:100]
			}
			d.Nbr = append(d.Nbr, n)
			if len(d.Nbr) >= 200 {
				return
			}
		}
	}
	if rows, _ := s.walk(oCdpRem, 600); len(rows) > 0 {
		ad, id, po, pl := col(rows, oCdpRem+".4"), col(rows, oCdpRem+".6"), col(rows, oCdpRem+".7"), col(rows, oCdpRem+".8")
		keys := make([]string, 0, len(id))
		for k := range id {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys { // k = ifIndex.deviceIndex
			parts := strings.Split(k, ".")
			lp, _ := strconv.Atoi(parts[0])
			n := snmpNbr{LP: lp, LN: ifn[lp], Name: pStr(id[k]), Port: pStr(po[k]), Descr: pStr(pl[k]), Proto: "cdp"}
			if b, ok := ad[k].Value.([]byte); ok && len(b) == 4 {
				n.IP = fmt.Sprintf("%d.%d.%d.%d", b[0], b[1], b[2], b[3])
			}
			if len(n.Descr) > 100 {
				n.Descr = n.Descr[:100]
			}
			d.Nbr = append(d.Nbr, n)
			if len(d.Nbr) >= 200 {
				return
			}
		}
	}
}

// snmpCustoms: gli OID scelti dall'utente dopo la scansione apparato.
func snmpCustoms(s *snmpSess, c *snmpCfg, d *snmpData) {
	for _, cu := range c.Custom {
		oid := cu.OID
		if !strings.HasPrefix(oid, ".") {
			oid = "." + oid
		}
		v := snmpCustVal{Name: cu.Name}
		if g, err := s.get(oid); err == nil {
			if p, ok := g[oid]; ok {
				if f, ok := pFloat(p); ok {
					v.V, v.OK = f, true
					d.M["c."+cu.Name] = f
				} else {
					v.S, v.OK = pStr(p), true
				}
			}
		}
		d.Cust = append(d.Cust, v)
	}
}

// snmpScanWalk: «scansione apparato» — sottoalberi standard e del produttore, al massimo ~4000 variabili.
func snmpScanWalk(t probeTarget) snmpWalk {
	t = snmpWithWinner(t)
	w := snmpWalk{ID: t.ID, Scan: t.Snmp.Scan}
	s, err := snmpOpen(t.IP, t.Snmp)
	if err != nil {
		w.Err = err.Error()
		return w
	}
	defer s.close()
	left := 4000
	for _, root := range []string{".1.3.6.1.2.1.1", ".1.3.6.1.2.1.25", ".1.3.6.1.2.1.43", ".1.3.6.1.2.1.33", ".1.3.6.1.2.1.31.1.1.1", ".1.3.6.1.4.1"} {
		if left <= 0 {
			w.More = true
			break
		}
		pd, err := s.walk(root, left)
		if err != nil && len(pd) == 0 {
			if root == ".1.3.6.1.2.1.1" {
				w.Err = snmpErrText(err, t.Snmp)
				return w
			}
			continue
		}
		for _, p := range pd {
			v := pStr(p)
			if len(v) > 140 {
				v = v[:140]
			}
			w.OIDs = append(w.OIDs, []string{p.Name, p.Type.String(), v})
		}
		left -= len(pd)
		if left <= 0 {
			w.More = true
		}
	}
	return w
}
