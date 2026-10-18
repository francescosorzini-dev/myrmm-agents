//go:build !windows

package main

import (
	"context"
	"fmt"
	"os/exec"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

func svcRun(timeout time.Duration, name string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	b, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
	if err != nil {
		return string(b), fmt.Errorf("%v: %s", err, strings.TrimSpace(string(b)))
	}
	return string(b), nil
}

func platSvcList() ([]svcItem, error) {
	if runtime.GOOS == "darwin" {
		out, err := svcRun(15*time.Second, "launchctl", "list")
		if err != nil {
			return nil, err
		}
		var items []svcItem
		for i, l := range strings.Split(out, "\n") {
			f := strings.Fields(l)
			if i == 0 || len(f) < 3 {
				continue
			}
			it := svcItem{N: f[2], S: "stopped"}
			if pid, err := strconv.Atoi(f[0]); err == nil && pid > 0 {
				it.S, it.P = "running", pid
			}
			items = append(items, it)
		}
		sort.Slice(items, func(i, j int) bool { return items[i].N < items[j].N })
		return items, nil
	}
	if _, err := exec.LookPath("systemctl"); err != nil {
		return nil, fmt.Errorf("systemctl non disponibile (sistema senza systemd)")
	}
	out, err := svcRun(20*time.Second, "systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager", "--plain")
	if err != nil {
		return nil, err
	}
	enabled := map[string]string{}
	if uf, err := svcRun(20*time.Second, "systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"); err == nil {
		for _, l := range strings.Split(uf, "\n") {
			if f := strings.Fields(l); len(f) >= 2 {
				enabled[f[0]] = f[1]
			}
		}
	}
	var items []svcItem
	for _, l := range strings.Split(out, "\n") {
		f := strings.Fields(l)
		if len(f) < 4 || !strings.HasSuffix(f[0], ".service") || f[1] == "not-found" {
			continue
		}
		it := svcItem{N: f[0], S: "other"}
		if len(f) > 4 {
			it.D = strings.Join(f[4:], " ")
		}
		switch f[2] {
		case "active":
			it.S = "running"
			if f[3] == "exited" {
				it.S = "stopped" // oneshot completato
			}
		case "inactive", "failed":
			it.S = "stopped"
			if f[2] == "failed" {
				it.S = "failed"
			}
		case "activating", "reloading":
			it.S = "starting"
		case "deactivating":
			it.S = "stopping"
		}
		it.St = map[string]string{"enabled": "auto", "enabled-runtime": "auto", "disabled": "disabled", "static": "static", "masked": "disabled", "indirect": "static", "generated": "static", "alias": "static"}[enabled[f[0]]]
		if it.St == "" {
			it.St = enabled[f[0]]
		}
		if it.S == "running" {
			if o, err := svcRun(5*time.Second, "systemctl", "show", "-p", "MainPID", "--value", f[0]); err == nil {
				it.P, _ = strconv.Atoi(strings.TrimSpace(o))
			}
		}
		items = append(items, it)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].N < items[j].N })
	return items, nil
}

func platSvcControl(op, name, mode string) (string, error) {
	if runtime.GOOS == "darwin" {
		target := "system/" + name
		var err error
		switch op {
		case "start":
			_, err = svcRun(25*time.Second, "launchctl", "kickstart", target)
		case "stop":
			_, err = svcRun(25*time.Second, "launchctl", "kill", "SIGTERM", target)
		case "restart":
			_, err = svcRun(25*time.Second, "launchctl", "kickstart", "-k", target)
		default:
			err = fmt.Errorf("tipo di avvio non gestibile su macOS da qui")
		}
		if err != nil {
			return "", err
		}
		time.Sleep(time.Second)
		return "", nil
	}
	var err error
	switch op {
	case "start", "stop", "restart":
		_, err = svcRun(40*time.Second, "systemctl", op, name)
	case "startup":
		switch mode {
		case "auto", "delayed":
			_, err = svcRun(20*time.Second, "systemctl", "enable", name)
		case "manual", "disabled":
			_, err = svcRun(20*time.Second, "systemctl", "disable", name)
		default:
			err = fmt.Errorf("tipo di avvio non valido")
		}
		return mode, err
	}
	if err != nil {
		return "", err
	}
	o, _ := svcRun(5*time.Second, "systemctl", "is-active", name)
	return strings.TrimSpace(o), nil
}
