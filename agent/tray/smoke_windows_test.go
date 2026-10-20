//go:build windows

package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Prova di fumo su un vero Windows: la tray parte, crea la sua finestra, interroga l'API locale con l'intestazione
// richiesta e una seconda copia esce subito (mutex condiviso con la tray PowerShell).
func TestTraySmoke(t *testing.T) {
	dir := t.TempDir()
	exe := filepath.Join(dir, "myrmm-tray.exe")
	if out, err := exec.Command("go", "build", "-o", exe, ".").CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	var hits, guard int32
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/state", func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		if r.Header.Get("X-Myrmm-Tray") == "1" {
			atomic.AddInt32(&guard, 1)
		}
		json.NewEncoder(w).Encode(map[string]any{"host": "PC-PROVA", "version": "0", "online": true,
			"log": []map[string]any{{"dir": "out", "text": "ciao dall'assistenza", "srv_id": 1, "ts": "2026-10-20T10:00:00Z", "author": "Assistenza"}}})
	})
	go http.Serve(ln, mux)
	port := ln.Addr().(*net.TCPAddr).Port
	os.WriteFile(filepath.Join(dir, "tray.json"), []byte(fmt.Sprintf(`{"port":%d}`, port)), 0o644)

	cmd := exec.Command(exe)
	cmd.Env = append(os.Environ(), "MYRMM_DIR="+dir)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer cmd.Process.Kill()

	findWnd := windows.NewLazySystemDLL("user32.dll").NewProc("FindWindowW")
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) && atomic.LoadInt32(&hits) == 0 {
		time.Sleep(200 * time.Millisecond)
	}
	if atomic.LoadInt32(&hits) == 0 {
		t.Fatal("la tray non ha mai chiamato /state")
	}
	if atomic.LoadInt32(&guard) == 0 {
		t.Error("manca l'intestazione X-Myrmm-Tray")
	}
	h, _, _ := findWnd.Call(uintptr(unsafe.Pointer(u16("MyrmmTray"))), 0)
	if h == 0 {
		t.Error("finestra MyrmmTray non trovata")
	}

	second := exec.Command(exe)
	second.Env = cmd.Env
	if err := second.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- second.Wait() }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		second.Process.Kill()
		t.Error("la seconda copia non è uscita: il mutex non funziona")
	}
}
