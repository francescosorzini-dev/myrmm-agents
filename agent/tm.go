package main

// Task manager: elenco processi in tempo reale e terminazione, per Windows, Linux e macOS (solo libreria standard).
// L'elenco viene inviato dentro gli heartbeat leggeri finché la console ha la vista aperta (server: "watch");
// la terminazione è un job firmato "#myrmm-tm\n{json}".

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"strings"
	"sync"
	"time"
)

const tmPrefix = "#myrmm-tm\n"

type rawProc struct {
	PID, PPID int
	Name      string
	User      string
	Cmd       string
	CPU       float64 // secondi di CPU cumulati
	RSS       uint64  // byte
	Threads   int
	Start     int64 // istante di avvio (secondi unix): insieme al PID identifica il processo
	Protected bool  // processo di sistema che non si termina da qui
}

type sysStat struct {
	CPUPct   float64 // -1 = non disponibile (si somma dai processi)
	MemTotal uint64
	MemUsed  uint64
}

type tmKey struct {
	pid   int
	start int64
}

var (
	tmMu     sync.Mutex
	tmPrev   = map[tmKey]float64{}
	tmPrevAt time.Time
)

// tmSample prende un campione: la CPU % di ogni processo è la differenza rispetto al campione precedente
// (percentuale dell'intera macchina, come il Task Manager di Windows).
func tmSample() map[string]any {
	tmMu.Lock()
	defer tmMu.Unlock()
	procs, err := platProcs()
	now := time.Now()
	if err != nil {
		return map[string]any{"t": now.Unix(), "err": err.Error()}
	}
	dt := now.Sub(tmPrevAt).Seconds()
	ncpu := float64(runtime.NumCPU())
	next := make(map[tmKey]float64, len(procs))
	rows := make([]any, 0, len(procs))
	var sum float64
	self := os.Getpid()
	for _, p := range procs {
		k := tmKey{p.PID, p.Start}
		next[k] = p.CPU
		cpu := 0.0
		if prev, ok := tmPrev[k]; ok && dt > 0.2 && !tmPrevAt.IsZero() {
			cpu = (p.CPU - prev) / dt / ncpu * 100
			if cpu < 0 {
				cpu = 0
			}
			if cpu > 100 {
				cpu = 100
			}
		}
		sum += cpu
		prot := 0
		if p.Protected || p.PID == self {
			prot = 1
		}
		cmd := p.Cmd
		if len(cmd) > 160 {
			cmd = cmd[:160]
		}
		rows = append(rows, []any{p.PID, p.PPID, strings.ToValidUTF8(p.Name, "?"), strings.ToValidUTF8(p.User, "?"), round1(cpu), p.RSS, p.Threads, p.Start, strings.ToValidUTF8(cmd, "?"), prot})
	}
	tmPrev, tmPrevAt = next, now
	st := platSys()
	if st.CPUPct < 0 {
		st.CPUPct = sum
		if st.CPUPct > 100 {
			st.CPUPct = 100
		}
	}
	return map[string]any{"t": now.Unix(), "cpu": round1(st.CPUPct), "mt": st.MemTotal, "mu": st.MemUsed, "ncpu": runtime.NumCPU(), "n": len(rows), "p": rows}
}

type tmTarget struct {
	PID   int   `json:"pid"`
	Start int64 `json:"start"`
}

type tmOp struct {
	Op      string     `json:"op"`
	Targets []tmTarget `json:"targets"`
	Tree    bool       `json:"tree"`
}

// tmExec esegue un job del task manager. mode = cfg.TmMode: "rw" (default) | "ro" | "off".
func tmExec(cfg *Config, script string) runResult {
	start := time.Now()
	var o tmOp
	if err := json.Unmarshal([]byte(strings.TrimPrefix(script, tmPrefix)), &o); err != nil {
		return fsFail("richiesta non valida: %v", err)
	}
	mode := strings.ToLower(cfg.TmMode)
	if mode == "off" || (mode == "ro" && o.Op == "kill") {
		return fsFail("task manager %s su questo device (tm_mode=%s nella config dell'agent)", map[bool]string{true: "disattivato", false: "in sola lettura"}[mode == "off"], mode)
	}
	if o.Op != "kill" || len(o.Targets) == 0 || len(o.Targets) > 200 {
		return fsFail("operazione non valida")
	}
	var killed []int
	var failed []map[string]any
	for _, t := range o.Targets {
		if t.PID <= 0 || t.PID == os.Getpid() {
			failed = append(failed, map[string]any{"pid": t.PID, "err": "non consentito"})
			continue
		}
		n, err := platKillProc(t.PID, t.Start, o.Tree)
		if err != nil {
			failed = append(failed, map[string]any{"pid": t.PID, "err": err.Error()})
			continue
		}
		killed = append(killed, t.PID)
		_ = n
	}
	r := fsOK(map[string]any{"killed": killed, "failed": failed})
	if len(killed) == 0 {
		msg := "nessun processo terminato"
		if len(failed) > 0 {
			msg = fmt.Sprintf("pid %v: %v", failed[0]["pid"], failed[0]["err"])
		}
		r = fsFail("%s", msg)
	}
	r.Duration = time.Since(start).Seconds()
	return r
}
