package main

import (
	"context"
	"encoding/json"
	"os/exec"
	"runtime"
	"sync"
	"time"

	"github.com/kardianos/service"
)

// deployTask: un PC da raggiungere per installare l'agent (la sonda lavora solo su richiesta dell'amministratore).
type deployTask struct {
	ID     int    `json:"id"`
	IP     string `json:"ip"`
	OS     string `json:"os"`   // win | unix
	Mode   string `json:"mode"` // dry | run
	Cred   string `json:"cred"` // JSON cifrato (sealed box) con la chiave pubblica di questa sonda
	Script string `json:"script,omitempty"`
	URL    string `json:"url"`
}

var deploySt = struct {
	sync.Mutex
	seen map[int]bool
}{seen: map[int]bool{}}

// deployHandle: avvia in coda le richieste ricevute con l'heartbeat (una per volta, ognuna una sola volta).
func deployHandle(tasks []deployTask, log service.Logger) {
	for _, t := range tasks {
		deploySt.Lock()
		dup := deploySt.seen[t.ID]
		deploySt.seen[t.ID] = true
		deploySt.Unlock()
		if dup {
			continue
		}
		go deployQueued(t, log)
	}
}

var deployQueue sync.Mutex

func deployQueued(t deployTask, log service.Logger) {
	deployQueue.Lock()
	defer deployQueue.Unlock()
	state, detail := deployRun(context.Background(), t)
	_ = log.Infof("distribuzione %s %s: %s", t.IP, t.Mode, state)
	probeExtraAppend("deploys", map[string]any{"id": t.ID, "state": state, "detail": detail})
}

func deployRun(ctx context.Context, t deployTask) (state, detail string) {
	raw, err := openSealed(t.Cred)
	if err != nil {
		return "fail", err.Error()
	}
	switch t.OS {
	case "win":
		if runtime.GOOS != "windows" {
			return "fail", "la distribuzione verso Windows richiede una sonda Windows (SMB/WMI)"
		}
		var c winCred
		if json.Unmarshal(raw, &c) != nil || c.U == "" {
			return "fail", "credenziali Windows non valide"
		}
		return deployWindowsPS(ctx, t.IP, &c, t.Mode, t.Script, t.URL, psExePath())
	case "unix":
		var c unixCred
		if json.Unmarshal(raw, &c) != nil || c.U == "" {
			return "fail", "credenziali SSH non valide"
		}
		return deployUnix(ctx, t.IP, &c, t.Mode, t.Script, t.URL)
	}
	return "fail", "tipo di sistema non riconosciuto"
}

func psExePath() string {
	if runtime.GOOS == "windows" {
		return "powershell.exe"
	}
	if p, err := exec.LookPath("pwsh"); err == nil {
		return p
	}
	return "pwsh"
}

var _ = time.Second
