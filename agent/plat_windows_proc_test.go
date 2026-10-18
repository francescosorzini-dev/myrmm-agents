//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

// Esperimento diagnostico: come si comporta un PowerShell staccato con varie combinazioni di flag e di stdio.
// Scrive i risultati in MYRMM_TEST_MATRIX_OUT (usato dal workflow CI).
func TestDetachedPowerShell(t *testing.T) {
	out := os.Getenv("MYRMM_TEST_MATRIX_OUT")
	if out == "" {
		t.Skip("MYRMM_TEST_MATRIX_OUT non impostata")
	}
	dir := t.TempDir()
	var rep strings.Builder
	type variant struct {
		name  string
		flags uint32
		file  bool
		hide  bool
		real  bool
	}
	for _, v := range []variant{
		{"A flags=0 stdio=file", 0, true, false, false},
		{"B DETACHED|NEWPG stdio=file", 0x8 | 0x200, true, false, false},
		{"C DETACHED|NEWPG stdio=nil", 0x8 | 0x200, false, false, false},
		{"D NEWPG stdio=file", 0x200, true, false, false},
		{"E DETACHED stdio=file", 0x8, true, false, false},
		{"G NO_WINDOW|NEWPG stdio=file", 0x08000000 | 0x200, true, false, false},
		{"H NO_WINDOW|NEWPG stdio=file, script reale con percorsi finti", 0x08000000 | 0x200, true, false, true},
		{"F DETACHED|NEWPG stdio=file, script reale con percorsi finti", 0x8 | 0x200, true, false, true},
	} {
		mark := filepath.Join(dir, fmt.Sprintf("m-%c.txt", v.name[0]))
		script := fmt.Sprintf("'ok '+$PID | Out-File -Append '%s'", mark)
		if v.real {
			script = uninstallScript(filepath.Join(dir, "x", "agent.exe"), filepath.Join(dir, "d"), mark)
		}
		cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodePowerShell(script))
		cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: v.flags, HideWindow: v.hide}
		var f *os.File
		if v.file {
			f, _ = os.Create(filepath.Join(dir, "o-"+v.name[:1]+".txt"))
			cmd.Stdout, cmd.Stderr = f, f
		}
		st := time.Now()
		err := cmd.Start()
		if err == nil {
			err = cmd.Wait()
		}
		_, e2 := os.Stat(mark)
		so := ""
		if f != nil {
			f.Close()
			b, _ := os.ReadFile(f.Name())
			so = string(b)
		}
		fmt.Fprintf(&rep, "%s: err=%v durata=%v marker=%v out=%q\n", v.name, err, time.Since(st).Round(time.Millisecond), e2 == nil, so)
	}
	_ = os.WriteFile(out, []byte(rep.String()), 0o644)
	t.Log(rep.String())
}
