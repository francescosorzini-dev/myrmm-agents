//go:build windows

package main

import (
	"image"
	"image/color"
	"runtime"
	"testing"
	"time"
	"unsafe"
)

func testImg() *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, 300, 200))
	for y := 0; y < 200; y++ {
		for x := 0; x < 300; x++ {
			img.SetRGBA(x, y, color.RGBA{uint8(x), uint8(y), 128, 255})
		}
	}
	return img
}

// clickWhenReady: attende la finestra delle immagini e preme un pulsante (o la chiude).
func clickWhenReady(t *testing.T, id uintptr, msgID uintptr) {
	find := user32.NewProc("FindWindowW")
	go func() {
		for i := 0; i < 100; i++ {
			time.Sleep(100 * time.Millisecond)
			h, _, _ := find.Call(uintptr(unsafe.Pointer(u16("MyrmmImg"))), 0)
			if h != 0 {
				pPostMessage.Call(h, msgID, id, 0)
				return
			}
		}
	}()
}

func TestConfirmImageButtons(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	hFont = 0
	for _, c := range []struct {
		id   uintptr
		want int
	}{{idOK, idOK}, {idCancel, idCancel}, {idRetry, idRetry}} {
		clickWhenReady(t, c.id, wmCommand)
		if got := confirmImage(testImg(), true); got != c.want {
			t.Errorf("pulsante %d: risultato %d", c.id, got)
		}
	}
	clickWhenReady(t, 0, wmClose) // chiusura dalla X = annulla
	if got := confirmImage(testImg(), false); got != idCancel {
		t.Errorf("chiusura: %d", got)
	}
}

func TestViewerOpensAndCloses(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	showViewer(testImg())
	find := user32.NewProc("FindWindowW")
	h, _, _ := find.Call(uintptr(unsafe.Pointer(u16("MyrmmImg"))), 0)
	if h == 0 {
		t.Fatal("visualizzatore non creato")
	}
	pPostMessage.Call(h, wmLButtonUp, 0, 0)
	var m msg
	for i := 0; i < 5; i++ { // smaltisce i messaggi: WM_LBUTTONUP distrugge la finestra
		if r, _, _ := user32.NewProc("PeekMessageW").Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0, 1); r != 0 {
			pDispatchMessage.Call(uintptr(unsafe.Pointer(&m)))
		}
		time.Sleep(50 * time.Millisecond)
	}
	if h2, _, _ := find.Call(uintptr(unsafe.Pointer(u16("MyrmmImg"))), 0); h2 != 0 {
		t.Error("il visualizzatore non si è chiuso al clic")
	}
}
