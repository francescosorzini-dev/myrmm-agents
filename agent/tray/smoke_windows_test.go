//go:build windows

package main

import (
	"bytes"
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
			"log": []map[string]any{{"dir": "op", "img": "ci0123456789abcdef0123456789abcdef", "ready": true, "srv_id": 2, "ts": "2026-10-20T10:00:00Z", "author": "Assistenza"}, {"dir": "op", "text": "ciao dall'assistenza", "srv_id": 1, "ts": "2026-10-20T10:00:00Z", "author": "Assistenza"}}})
	})
	var imgHits int32
	mux.HandleFunc("/img", func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&imgHits, 1)
		b, _ := encodePNG(testImg())
		w.Header().Set("Content-Type", "image/png")
		w.Write(b)
	})
	go http.Serve(ln, mux)
	port := ln.Addr().(*net.TCPAddr).Port
	os.WriteFile(filepath.Join(dir, "tray.json"), []byte(fmt.Sprintf(`{"port":%d}`, port)), 0o644)

	cmd := exec.Command(exe)
	cmd.Env = append(os.Environ(), "MYRMM_DIR="+dir, "TMP="+dir, "TEMP="+dir)
	var out bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &out
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer cmd.Process.Kill()
	exited := make(chan error, 1)
	go func() { exited <- cmd.Wait() }()

	findWnd := windows.NewLazySystemDLL("user32.dll").NewProc("FindWindowW")
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) && atomic.LoadInt32(&hits) == 0 {
		time.Sleep(200 * time.Millisecond)
	}
	if atomic.LoadInt32(&hits) == 0 {
		lg, _ := os.ReadFile(filepath.Join(dir, "myrmm-tray.log"))
		st := "in esecuzione"
		select {
		case e := <-exited:
			st = fmt.Sprintf("USCITA: %v", e)
		default:
		}
		t.Fatalf("la tray non ha mai chiamato /state (processo: %s)\noutput: %s\nlog:\n%s", st, out.String(), lg)
	}
	if atomic.LoadInt32(&guard) == 0 {
		t.Error("manca l'intestazione X-Myrmm-Tray")
	}
	h, _, _ := findWnd.Call(uintptr(unsafe.Pointer(u16("MyrmmTray"))), 0)
	if h == 0 {
		t.Error("finestra MyrmmTray non trovata")
	}

	// apre la chat come farebbe il doppio clic sull'icona: l'anteprima dell'immagine deve essere scaricata e inserita
	pPostMessage.Call(h, wmCommand, idMenuChat, 0)
	until := time.Now().Add(15 * time.Second)
	for time.Now().Before(until) && atomic.LoadInt32(&imgHits) == 0 {
		time.Sleep(200 * time.Millisecond)
	}
	if atomic.LoadInt32(&imgHits) == 0 {
		t.Error("la tray non ha scaricato l'immagine della conversazione")
	}
	ok := false
	for time.Now().Before(until.Add(5*time.Second)) && !ok {
		lg, _ := os.ReadFile(filepath.Join(dir, "myrmm-tray.log"))
		ok = bytes.Contains(lg, []byte("miniatura inserita"))
		time.Sleep(200 * time.Millisecond)
	}
	if !ok {
		lg, _ := os.ReadFile(filepath.Join(dir, "myrmm-tray.log"))
		t.Errorf("miniatura non inserita nella chat. Log:\n%s", lg)
	}

	// la miniatura deve essere DISEGNATA, non solo inserita: si cattura il controllo e si contano i pixel del colore dell'immagine di prova
	// (blu 128 in tutta l'immagine; il testo della chat non ha mai questo valore)
	time.Sleep(1500 * time.Millisecond)
	rich, _, _ := user32.NewProc("FindWindowExW").Call(h, 0, uintptr(unsafe.Pointer(u16("RICHEDIT50W"))), 0)
	if rich == 0 {
		t.Error("controllo RichEdit non trovato")
	} else if n, w, hh, nw := capturedStats(rich); n < 5000 {
		t.Errorf("miniatura non disegnata: %d pixel dell'immagine su un controllo %dx%d (pixel non bianchi: %d)", n, w, hh, nw)
	} else {
		t.Logf("miniatura disegnata: %d pixel", n)
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

// capturedBlue: PrintWindow del controllo in un bitmap a 32 bit; conta i pixel con blu = 128 (colore dell'immagine di prova).
func capturedBlue(hwnd uintptr) (n, w, h int) {
	n, w, h, _ = capturedStats(hwnd)
	return
}

// capturedStats: oltre ai pixel blu = 128 restituisce quanti pixel non sono bianchi (per capire se la cattura funziona).
func capturedStats(hwnd uintptr) (n, w, h, nonWhite int) {
	var rc struct{ L, T, R, B int32 }
	user32.NewProc("GetClientRect").Call(hwnd, uintptr(unsafe.Pointer(&rc)))
	w, h = int(rc.R), int(rc.B)
	if w <= 0 || h <= 0 {
		return
	}
	gdi := windows.NewLazySystemDLL("gdi32.dll")
	dc, _, _ := user32.NewProc("GetDC").Call(0)
	mem, _, _ := gdi.NewProc("CreateCompatibleDC").Call(dc)
	bmp, _, _ := gdi.NewProc("CreateCompatibleBitmap").Call(dc, uintptr(w), uintptr(h))
	gdi.NewProc("SelectObject").Call(mem, bmp)
	user32.NewProc("PrintWindow").Call(hwnd, mem, 1) // PW_CLIENTONLY
	bi := struct {
		Size            uint32
		W, H            int32
		Planes, Bits    uint16
		Comp, SizeImg   uint32
		XPels, YPels    int32
		ClrUsed, ClrImp uint32
	}{Size: 40, W: int32(w), H: -int32(h), Planes: 1, Bits: 32}
	px := make([]byte, w*h*4)
	gdi.NewProc("GetDIBits").Call(mem, bmp, 0, uintptr(h), uintptr(unsafe.Pointer(&px[0])), uintptr(unsafe.Pointer(&bi)), 0)
	for i := 0; i+3 < len(px); i += 4 {
		if px[i] == 128 { // blu (BGRA)
			n++
		}
		if px[i] != 255 || px[i+1] != 255 || px[i+2] != 255 {
			nonWhite++
		}
	}
	gdi.NewProc("DeleteObject").Call(bmp)
	gdi.NewProc("DeleteDC").Call(mem)
	user32.NewProc("ReleaseDC").Call(0, dc)
	return
}
