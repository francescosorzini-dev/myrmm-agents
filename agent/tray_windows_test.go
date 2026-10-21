//go:build windows

package main

import (
	"strings"
	"testing"
	"time"

	"github.com/kardianos/service"
	"golang.org/x/sys/windows"
)

type nopLog struct{}

func (nopLog) Error(v ...interface{}) error              { return nil }
func (nopLog) Warning(v ...interface{}) error            { return nil }
func (nopLog) Info(v ...interface{}) error               { return nil }
func (nopLog) Errorf(f string, a ...interface{}) error   { return nil }
func (nopLog) Warningf(f string, a ...interface{}) error { return nil }
func (nopLog) Infof(f string, a ...interface{}) error    { return nil }

var _ service.Logger = nopLog{}

func TestTrayKeyIsStableAndPerSession(t *testing.T) {
	traySecretFor("api-key-1")
	a := trayKey(2, `PC\Anna`)
	if a != trayKey(2, `pc\anna`) {
		t.Fatal("il nome utente non distingue maiuscole")
	}
	if a == trayKey(3, `PC\Anna`) || a == trayKey(2, `PC\Bruno`) {
		t.Fatal("la chiave deve dipendere da sessione e utente")
	}
	traySecretFor("api-key-2")
	if a == trayKey(2, `PC\Anna`) {
		t.Fatal("la chiave deve dipendere dal segreto del device")
	}
	for _, bad := range []string{"", "1", "abc", "2:", ":x", "9999999999:aa", "2:00"} {
		if _, ok := trayResolve(bad); ok {
			t.Fatalf("%q non doveva essere accettata", bad)
		}
	}
}

func TestTraySupervisor(t *testing.T) {
	t.Setenv("MYRMM_DIR", t.TempDir())
	chatTestReset(t)
	traySecretFor("k")
	trayPortV.Store(4242)
	chatDisabled.Store(false)
	oldL, oldS, oldSince := trayLaunch, trayListSessions, traySince
	defer func() {
		trayLaunch, trayListSessions, traySince = oldL, oldS, oldSince
		trayProcs = map[uint32]*trayProc{}
	}()
	trayProcs = map[uint32]*trayProc{}
	var launched []uint32
	var env []string
	trayLaunch = func(sid uint32, exe string, extra []string) (windows.Handle, uint32, error) {
		launched = append(launched, sid)
		env = extra
		return 0, 100 + sid, nil
	}
	sessions := []wtsSess{{ID: 2, State: uint32(windows.WTSActive), User: `PC\anna`}, {ID: 3, State: uint32(windows.WTSActive), User: `PC\bruno`}, {ID: 4, State: 4, User: `PC\ospite`}}
	trayListSessions = func() []wtsSess { return sessions }
	cfg := &Config{}
	now := time.Now()
	traySince = now // appena partiti: periodo di attesa per le tray già in corso
	traySuperviseOnce(cfg, "C:\\x\\myrmm-agent.exe", nopLog{}, now)
	if len(launched) != 0 {
		t.Fatalf("nei primi secondi non si lancia nulla: %v", launched)
	}
	now = now.Add(40 * time.Second)
	traySuperviseOnce(cfg, "C:\\x\\myrmm-agent.exe", nopLog{}, now)
	if len(launched) != 2 {
		t.Fatalf("una tray per sessione attiva (la disconnessa no): %v", launched)
	}
	joined := strings.Join(env, "|")
	if !strings.Contains(joined, "MYRMM_TRAY_PORT=4242") || !strings.Contains(joined, "MYRMM_TRAY_KEY=") || !strings.Contains(joined, "MYRMM_TRAY_VERSION="+AgentVersion) {
		t.Fatalf("ambiente della tray: %s", joined)
	}
	// la tray di Anna si collega: non si rilancia; quella di Bruno non si collega: si rilancia dopo il ritardo, non subito
	chatMu.Lock()
	chatSession(`PC\anna`).last = now
	chatMu.Unlock()
	launched = nil
	traySuperviseOnce(cfg, "x", nopLog{}, now.Add(5*time.Second))
	if len(launched) != 0 {
		t.Fatalf("niente rilanci immediati: %v", launched)
	}
	traySuperviseOnce(cfg, "x", nopLog{}, now.Add(25*time.Second))
	if len(launched) != 1 || launched[0] != 3 {
		t.Fatalf("solo la sessione di Bruno: %v", launched)
	}
	// Bruno esce dal PC: il suo processo viene dimenticato; l'icona disattivata ferma tutto
	sessions = sessions[:1]
	traySuperviseOnce(cfg, "x", nopLog{}, now.Add(60*time.Second))
	if _, ok := trayProcs[3]; ok {
		t.Fatal("sessione finita: il processo va dimenticato")
	}
	cfg.TrayMode = "off"
	chatDisabled.Store(true)
	launched = nil
	traySuperviseOnce(cfg, "x", nopLog{}, now.Add(300*time.Second))
	if len(launched) != 0 || len(trayProcs) != 0 {
		t.Fatalf("con l'icona disattivata non gira nulla: %v %d", launched, len(trayProcs))
	}
}
