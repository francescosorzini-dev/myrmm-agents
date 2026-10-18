//go:build windows

package main

import (
	"fmt"
	"os/exec"
	"sort"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

func svcStateName(s svc.State) string {
	switch s {
	case svc.Running:
		return "running"
	case svc.Stopped:
		return "stopped"
	case svc.StartPending, svc.ContinuePending:
		return "starting"
	case svc.StopPending:
		return "stopping"
	case svc.Paused, svc.PausePending:
		return "paused"
	}
	return "other"
}

func platSvcList() ([]svcItem, error) {
	m, err := mgr.Connect()
	if err != nil {
		return nil, err
	}
	defer m.Disconnect()
	names, err := m.ListServices()
	if err != nil {
		return nil, err
	}
	out := make([]svcItem, 0, len(names))
	for _, n := range names {
		s, err := m.OpenService(n)
		if err != nil {
			continue
		}
		it := svcItem{N: n, S: "other"}
		if c, err := s.Config(); err == nil {
			it.D = c.DisplayName
			switch c.StartType {
			case mgr.StartAutomatic:
				it.St = "auto"
				if c.DelayedAutoStart {
					it.St = "delayed"
				}
			case mgr.StartManual:
				it.St = "manual"
			case mgr.StartDisabled:
				it.St = "disabled"
			default:
				it.St = "static"
			}
		}
		if q, err := s.Query(); err == nil {
			it.S = svcStateName(q.State)
			it.P = int(q.ProcessId)
		}
		s.Close()
		out = append(out, it)
	}
	sort.Slice(out, func(i, j int) bool { return strings.ToLower(out[i].D+out[i].N) < strings.ToLower(out[j].D+out[j].N) })
	return out, nil
}

func svcWait(s *mgr.Service, want svc.State, d time.Duration) (svc.State, error) {
	end := time.Now().Add(d)
	for {
		q, err := s.Query()
		if err != nil {
			return 0, err
		}
		if q.State == want || time.Now().After(end) {
			return q.State, nil
		}
		time.Sleep(400 * time.Millisecond)
	}
}

func platSvcControl(op, name, mode string) (string, error) {
	if op == "startup" {
		arg := map[string]string{"auto": "auto", "delayed": "delayed-auto", "manual": "demand", "disabled": "disabled"}[mode]
		if arg == "" {
			return "", fmt.Errorf("tipo di avvio non valido")
		}
		cmd := exec.Command("sc.exe", "config", name, "start=", arg)
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		if b, err := cmd.CombinedOutput(); err != nil {
			return "", fmt.Errorf("%v: %s", err, strings.TrimSpace(string(b)))
		}
		return mode, nil
	}
	m, err := mgr.Connect()
	if err != nil {
		return "", err
	}
	defer m.Disconnect()
	s, err := m.OpenService(name)
	if err != nil {
		return "", fmt.Errorf("servizio non trovato")
	}
	defer s.Close()
	stop := func() error {
		q, err := s.Query()
		if err != nil {
			return err
		}
		if q.State == svc.Stopped {
			return nil
		}
		if _, err := s.Control(svc.Stop); err != nil {
			return err
		}
		if st, err := svcWait(s, svc.Stopped, 25*time.Second); err != nil || st != svc.Stopped {
			return fmt.Errorf("il servizio non si è fermato entro 25 s")
		}
		return nil
	}
	start := func() error {
		q, err := s.Query()
		if err != nil {
			return err
		}
		if q.State == svc.Running {
			return nil
		}
		if err := s.Start(); err != nil {
			return err
		}
		if st, err := svcWait(s, svc.Running, 25*time.Second); err != nil || st != svc.Running {
			return fmt.Errorf("il servizio non è partito entro 25 s")
		}
		return nil
	}
	switch op {
	case "stop":
		err = stop()
	case "start":
		err = start()
	case "restart":
		if err = stop(); err == nil {
			err = start()
		}
	}
	if err != nil {
		return "", err
	}
	q, err := s.Query()
	if err != nil {
		return "", err
	}
	return svcStateName(q.State), nil
}
