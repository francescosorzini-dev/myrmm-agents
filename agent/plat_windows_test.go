//go:build windows

package main

import (
	"os"
	"testing"
)

// Scrive lo script di disinstallazione su file, per farlo verificare a PowerShell (vedi ci/run_tests.py e il workflow).
func TestUninstallScript(t *testing.T) {
	out := os.Getenv("MYRMM_TEST_SCRIPT_OUT")
	if out == "" {
		t.Skip("MYRMM_TEST_SCRIPT_OUT non impostata")
	}
	s := uninstallScript(`C:\Program Files\myrmm\agent.exe`, `C:\ProgramData\myrmm`, `C:\Windows\Temp\myrmm-uninstall.log`)
	if err := os.WriteFile(out, append([]byte{0xEF, 0xBB, 0xBF}, []byte(s)...), 0o644); err != nil {
		t.Fatal(err)
	}
}
