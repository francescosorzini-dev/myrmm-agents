package main

// Sonda di rete (1.32): l'agent, promosso dalla console, controlla dalla LAN del cliente gli apparati senza agent
// (ping ICMP, porta TCP). Parla solo in uscita verso il server: riceve l'elenco nell'heartbeat, invia gli esiti in blocco.

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"math/rand"
	"net"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/kardianos/service"
)

type probeTarget struct {
	ID    int      `json:"id"`
	IP    string   `json:"ip"`
	Kind  string   `json:"kind"` // ping | tcp
	Port  int      `json:"port"`
	Every int      `json:"every"`          // secondi
	Snmp  *snmpCfg `json:"snmp,omitempty"` // kind snmp
}

type probeNet struct {
	ID   int      `json:"id"`
	CIDR string   `json:"cidr"`
	Snmp *snmpCfg `json:"snmp,omitempty"` // credenziali della rete: servono a riconoscere gli apparati scoperti
	Scan int      `json:"scan,omitempty"` // richiesta di scansione immediata (contatore)
}

// probeCfg: configurazione ricevuta con l'heartbeat (sostituisce la precedente).
type probeCfg struct {
	On        bool          `json:"on"`
	Ver       string        `json:"ver"`
	Targets   []probeTarget `json:"targets"`
	Nets      []probeNet    `json:"nets"`
	ScanMin   int           `json:"scan_min"`
	ScanPorts []int         `json:"scan_ports"`
}

type probeResult struct {
	ID     int       `json:"id"`
	OK     bool      `json:"ok"`
	RTT    float64   `json:"rtt"` // millisecondi
	Detail string    `json:"detail,omitempty"`
	TS     int64     `json:"ts"`
	Snmp   *snmpData `json:"snmp,omitempty"`
}

var probe struct {
	mu      sync.Mutex
	ver     string
	cfg     probeCfg
	cancel  context.CancelFunc
	results []probeResult
	extra   map[string]any // dati aggiuntivi da inviare con il prossimo report (scoperti, SNMP…)
}

// probeVer: versione della configurazione in uso (” = non sono una sonda); inviata nell'heartbeat.
func probeVer() string { probe.mu.Lock(); defer probe.mu.Unlock(); return probe.ver }

func probeApply(cfg *Config, st State, pc *probeCfg, log service.Logger) {
	if pc == nil {
		return
	}
	probe.mu.Lock()
	defer probe.mu.Unlock()
	if !pc.On {
		if probe.cancel != nil {
			probe.cancel()
			probe.cancel = nil
			_ = log.Infof("sonda: disattivata dalla console")
		}
		probe.ver, probe.cfg, probe.results = "", probeCfg{}, nil
		return
	}
	probe.cfg, probe.ver = *pc, pc.Ver
	if probe.cancel == nil {
		ctx, cancel := context.WithCancel(context.Background())
		probe.cancel = cancel
		go probeRun(ctx, cfg, st, log)
		_ = log.Infof("sonda: attivata (%d apparati)", len(pc.Targets))
	}
}

func probeSnapshot() probeCfg { probe.mu.Lock(); defer probe.mu.Unlock(); return probe.cfg }

const probeFlushEvery = 15 * time.Second

// probeRun: ciclo della sonda. Ogni secondo avvia i controlli scaduti (al massimo 32 insieme) e ogni 15 s invia gli esiti.
func probeRun(ctx context.Context, cfg *Config, st State, log service.Logger) {
	next := map[int]time.Time{}
	busy := map[int]bool{}
	var bmu sync.Mutex
	sem := make(chan struct{}, 32)
	tk := time.NewTicker(time.Second)
	defer tk.Stop()
	lastFlush := time.Now()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tk.C:
		}
		c := probeSnapshot()
		now := time.Now()
		live := map[int]bool{}
		for _, t := range c.Targets {
			live[t.ID] = true
			bmu.Lock()
			due, known := next[t.ID]
			if !known {
				due = now.Add(time.Duration(rand.Intn(3000)) * time.Millisecond) // sfalsa i primi controlli
				next[t.ID] = due
			}
			skip := busy[t.ID] || now.Before(due)
			if !skip {
				busy[t.ID] = true
				every := t.Every
				if every < 15 {
					every = 15
				}
				next[t.ID] = now.Add(time.Duration(every) * time.Second)
			}
			bmu.Unlock()
			if skip {
				continue
			}
			sem <- struct{}{}
			go func(t probeTarget) {
				defer func() { <-sem; bmu.Lock(); busy[t.ID] = false; bmu.Unlock() }()
				r := probeCheck(t)
				probe.mu.Lock()
				if len(probe.results) < 3000 {
					probe.results = append(probe.results, r)
				}
				probe.mu.Unlock()
			}(t)
		}
		snmpExtraTick(ctx, c, now, &bmu, busy, sem)
		bmu.Lock()
		for id := range next { // apparati tolti dalla configurazione
			if !live[id] {
				delete(next, id)
			}
		}
		bmu.Unlock()
		probeScanTick(ctx, cfg, st, log) // scansione periodica della rete (1.35)
		if time.Since(lastFlush) >= probeFlushEvery {
			lastFlush = time.Now()
			probeFlush(cfg, st, log)
		}
	}
}

func probeFlush(cfg *Config, st State, log service.Logger) {
	probe.mu.Lock()
	res, extra := probe.results, probe.extra
	probe.results, probe.extra = nil, nil
	probe.mu.Unlock()
	if len(res) == 0 && len(extra) == 0 {
		return
	}
	body := map[string]any{"results": res}
	for k, v := range extra {
		body[k] = v
	}
	if err := postJSON(cfg.ServerURL+"?action=probe_report", st.APIKey, body, nil); err != nil {
		_ = log.Warningf("sonda: invio esiti: %v", err)
		probe.mu.Lock() // li si ritenta al prossimo giro (senza superare il tetto)
		if len(probe.results)+len(res) <= 3000 {
			probe.results = append(res, probe.results...)
		}
		if probe.extra == nil && extra != nil {
			probe.extra = extra
		}
		probe.mu.Unlock()
	}
}

// probeCheck esegue un controllo. Mai panic: un errore diventa un esito negativo con il motivo.
func probeCheck(t probeTarget) probeResult {
	r := probeResult{ID: t.ID, TS: time.Now().Unix()}
	var d time.Duration
	var err error
	switch t.Kind {
	case "tcp":
		d, err = tcpCheck(t.IP, t.Port, 3*time.Second)
	case "snmp":
		return snmpPoll(t, true)
	default:
		d, err = icmpPing(t.IP, 2*time.Second)
	}
	if err != nil {
		r.Detail = err.Error()
		return r
	}
	r.OK, r.RTT = true, float64(d.Microseconds())/1000
	return r
}

func tcpCheck(ip string, port int, timeout time.Duration) (time.Duration, error) {
	t0 := time.Now()
	c, err := net.DialTimeout("tcp", net.JoinHostPort(ip, strconv.Itoa(port)), timeout)
	if err != nil {
		return 0, errors.New(netErrText(err))
	}
	d := time.Since(t0)
	_ = c.Close()
	return d, nil
}

// netErrText: motivo breve e leggibile di un errore di rete (indipendente dalla lingua del sistema).
func netErrText(err error) string {
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return "nessuna risposta (timeout)"
	}
	s := strings.ToLower(err.Error())
	switch {
	case strings.Contains(s, "refused") || strings.Contains(s, "rifiut"):
		return "connessione rifiutata (porta chiusa)"
	case strings.Contains(s, "unreachable") || strings.Contains(s, "no route"):
		return "rete o host non raggiungibile"
	}
	return "errore: " + err.Error()
}

// icmpPing: eco ICMP. Prima con socket raw (servono privilegi: l'agent gira come servizio), altrimenti con il comando ping di sistema.
func icmpPing(ip string, timeout time.Duration) (time.Duration, error) {
	c, err := net.DialTimeout("ip4:icmp", ip, timeout)
	if err != nil {
		return pingExec(ip, timeout)
	}
	defer c.Close()
	id, seq := uint16(rand.Intn(0xFFFF)), uint16(rand.Intn(0xFFFF))
	pkt := make([]byte, 8+16)
	pkt[0], pkt[1] = 8, 0
	binary.BigEndian.PutUint16(pkt[4:], id)
	binary.BigEndian.PutUint16(pkt[6:], seq)
	copy(pkt[8:], "myrmm-probe-0001")
	binary.BigEndian.PutUint16(pkt[2:], icmpSum(pkt))
	t0 := time.Now()
	_ = c.SetDeadline(t0.Add(timeout))
	if _, err := c.Write(pkt); err != nil {
		return 0, errors.New(netErrText(err))
	}
	buf := make([]byte, 1500)
	for {
		n, err := c.Read(buf)
		if err != nil {
			return 0, errors.New(netErrText(err))
		}
		b := buf[:n]
		if n >= 20 && b[0]>>4 == 4 { // intestazione IP presente (dipende dal sistema)
			ihl := int(b[0]&0x0f) * 4
			if ihl > n {
				continue
			}
			b = b[ihl:]
		}
		if len(b) >= 8 && b[0] == 0 && binary.BigEndian.Uint16(b[4:]) == id && binary.BigEndian.Uint16(b[6:]) == seq {
			return time.Since(t0), nil
		}
		if time.Since(t0) > timeout {
			return 0, errors.New("nessuna risposta (timeout)")
		}
	}
}

func icmpSum(b []byte) uint16 {
	var s uint32
	for i := 0; i+1 < len(b); i += 2 {
		s += uint32(b[i])<<8 | uint32(b[i+1])
	}
	if len(b)%2 == 1 {
		s += uint32(b[len(b)-1]) << 8
	}
	for s>>16 != 0 {
		s = s&0xffff + s>>16
	}
	return ^uint16(s)
}

// pingExec: ripiego con il comando ping del sistema (esito dal codice di uscita: l'output dipende dalla lingua).
func pingExec(ip string, timeout time.Duration) (time.Duration, error) {
	ms := int(timeout / time.Millisecond)
	var args []string
	switch runtime.GOOS {
	case "windows":
		args = []string{"-n", "1", "-w", strconv.Itoa(ms), ip}
	case "darwin":
		args = []string{"-c", "1", "-W", strconv.Itoa(ms), ip}
	default:
		args = []string{"-c", "1", "-W", strconv.Itoa((ms + 999) / 1000), ip}
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout+2*time.Second)
	defer cancel()
	t0 := time.Now()
	out, err := exec.CommandContext(ctx, "ping", args...).CombinedOutput()
	d := time.Since(t0)
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return 0, errors.New("nessuna risposta al ping")
		}
		return 0, fmt.Errorf("ping non eseguibile: %v", err)
	}
	if runtime.GOOS == "windows" && !strings.Contains(strings.ToUpper(string(out)), "TTL=") {
		return 0, errors.New("nessuna risposta al ping") // Windows esce con 0 anche per «host non raggiungibile»
	}
	return d, nil
}

// ---- SNMP: controllo veloce delle voci critiche e scansione apparato su richiesta

var snmpState = struct {
	sync.Mutex
	fast map[int]time.Time
	scan map[int]int
	win  map[int]int // apparato -> credenziale che ha risposto
}{fast: map[int]time.Time{}, scan: map[int]int{}, win: map[int]int{}}

func probeExtraAppend(key string, v any) {
	probe.mu.Lock()
	defer probe.mu.Unlock()
	if probe.extra == nil {
		probe.extra = map[string]any{}
	}
	l, _ := probe.extra[key].([]any)
	if len(l) < 50 {
		probe.extra[key] = append(l, v)
	}
}

func snmpExtraTick(ctx context.Context, c probeCfg, now time.Time, bmu *sync.Mutex, busy map[int]bool, sem chan struct{}) {
	for _, t := range c.Targets {
		if t.Kind != "snmp" || t.Snmp == nil {
			continue
		}
		snmpState.Lock()
		// controllo veloce: solo se c'è qualcosa di critico da seguire e l'intervallo pieno è più lungo
		doFast := false
		if f := t.Snmp.Fast; f >= 10 && len(t.Snmp.Observe) > 0 && t.Every > f {
			if due, ok := snmpState.fast[t.ID]; !ok || !now.Before(due) {
				snmpState.fast[t.ID] = now.Add(time.Duration(f) * time.Second)
				doFast = ok
			}
		}
		doScan := t.Snmp.Scan > 0 && snmpState.scan[t.ID] != t.Snmp.Scan
		if doScan {
			snmpState.scan[t.ID] = t.Snmp.Scan
		}
		snmpState.Unlock()
		bmu.Lock()
		isBusy := busy[t.ID]
		bmu.Unlock()
		if doFast && !isBusy {
			sem <- struct{}{}
			go func(t probeTarget) {
				defer func() { <-sem }()
				r := snmpPoll(t, false)
				probe.mu.Lock()
				if len(probe.results) < 3000 {
					probe.results = append(probe.results, r)
				}
				probe.mu.Unlock()
			}(t)
		}
		if doScan {
			go func(t probeTarget) {
				sem <- struct{}{}
				defer func() { <-sem }()
				probeExtraAppend("walks", snmpScanWalk(t))
			}(t)
		}
	}
}
