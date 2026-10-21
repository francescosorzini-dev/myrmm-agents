//go:build windows

package main

import (
	"encoding/base64"
	"fmt"
	"image"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Immagini nella chat: screenshot con lo strumento di Windows, scelta di un file, incolla, anteprima prima dell'invio,
// miniature nella conversazione e visualizzatore. Tutto con le API di Windows, nessuno script e nessuna libreria grafica.

var (
	pOpenClipboard    = user32.NewProc("OpenClipboard")
	pCloseClipboard   = user32.NewProc("CloseClipboard")
	pGetClipboardData = user32.NewProc("GetClipboardData")
	pIsClipFormat     = user32.NewProc("IsClipboardFormatAvailable")
	pRegClipFormat    = user32.NewProc("RegisterClipboardFormatW")
	pClipSeq          = user32.NewProc("GetClipboardSequenceNumber")
	pGlobalLock       = kernel32.NewProc("GlobalLock")
	pGlobalUnlock     = kernel32.NewProc("GlobalUnlock")
	pGlobalSize       = kernel32.NewProc("GlobalSize")
	pBeginPaint       = user32.NewProc("BeginPaint")
	pEndPaint         = user32.NewProc("EndPaint")
	pStretchDIBits    = gdi32.NewProc("StretchDIBits")
	pGetSystemMetrics = user32.NewProc("GetSystemMetrics")
	pAdjustWindowRect = user32.NewProc("AdjustWindowRectEx")
	pInvalidateRect   = user32.NewProc("InvalidateRect")
	pDestroyWindow    = user32.NewProc("DestroyWindow")
	pGetOpenFileName  = windows.NewLazySystemDLL("comdlg32.dll").NewProc("GetOpenFileNameW")
	pDragAcceptFiles  = shell32.NewProc("DragAcceptFiles")
)

const (
	cfDIB, cfDIBV5, cfUnicodeText = 8, 17, 13

	wmPaint, wmEraseBkgnd, wmLButtonUp, wmPaste = 0x000F, 0x0014, 0x0202, 0x0302
	wmShotDone, wmViewImg                       = wmApp + 3, wmApp + 4

	idShot, idAttach, idPaste = 106, 107, 108
	idMenuShot                = 202
	idOK, idCancel, idRetry   = 1, 2, 3

	emStreamIn, emGetSel, emCharFromPos = 0x0449, 0x00B0, 0x00D7
	sfRTF, sffSelection                 = 0x0002, 0x8000
)

type paintStruct struct {
	Hdc     uintptr
	Erase   int32
	Rc      rect
	Restore int32
	IncUpd  int32
	Res     [32]byte
}

// EDITSTREAM è dichiarata con impacchettamento a 4 byte (pshpack4.h): su 64 bit il puntatore alla funzione sta all'offset 12, non 16.
type editStream struct {
	Cookie uintptr
	Err    uint32
	CbLo   uint32
	CbHi   uint32
}

type openFileName struct {
	StructSize   uint32
	Owner        windows.HWND
	Instance     windows.Handle
	Filter       *uint16
	CustomFilter *uint16
	MaxCustom    uint32
	FilterIndex  uint32
	File         *uint16
	MaxFile      uint32
	FileTitle    *uint16
	MaxFileTitle uint32
	InitialDir   *uint16
	Title        *uint16
	Flags        uint32
	FileOffset   uint16
	FileExt      uint16
	DefExt       *uint16
	CustData     uintptr
	Hook         uintptr
	Template     *uint16
	Reserved     uintptr
	Reserved2    uint32
	FlagsEx      uint32
}

// ptr: da indirizzo numerico (restituito dalle API) a puntatore, senza l'avviso di go vet.
func ptr(p uintptr) unsafe.Pointer { return *(*unsafe.Pointer)(unsafe.Pointer(&p)) }

// ---- appunti ----------------------------------------------------------------------------------

func clipBytes(format uintptr) []byte {
	h, _, _ := pGetClipboardData.Call(format)
	if h == 0 {
		return nil
	}
	p, _, _ := pGlobalLock.Call(h)
	if p == 0 {
		return nil
	}
	defer pGlobalUnlock.Call(h)
	n, _, _ := pGlobalSize.Call(h)
	if n == 0 || n > 200<<20 {
		return nil
	}
	return append([]byte(nil), unsafe.Slice((*byte)(ptr(p)), int(n))...)
}

func openClip() bool {
	for i := 0; i < 10; i++ {
		if r, _, _ := pOpenClipboard.Call(0); r != 0 {
			return true
		}
		time.Sleep(60 * time.Millisecond)
	}
	return false
}

func fmtPNG() uintptr { r, _, _ := pRegClipFormat.Call(uintptr(unsafe.Pointer(u16("PNG")))); return r }

// clipHasImage: negli appunti c'è un'immagine (e non del testo, che l'incolla normale gestisce da sé).
func clipHasImage() bool {
	has := func(f uintptr) bool { r, _, _ := pIsClipFormat.Call(f); return r != 0 }
	if has(cfUnicodeText) {
		return false
	}
	return has(cfDIB) || has(cfDIBV5) || has(fmtPNG())
}

func clipImage() (*image.RGBA, error) {
	if !openClip() {
		return nil, fmt.Errorf("appunti occupati")
	}
	defer pCloseClipboard.Call()
	if r, _, _ := pIsClipFormat.Call(fmtPNG()); r != 0 {
		if b := clipBytes(fmtPNG()); b != nil {
			if img, err := decodeAny(b); err == nil {
				return scaleTo(img, 1<<14, 1<<14), nil
			}
		}
	}
	var last error = fmt.Errorf("nessuna immagine negli appunti")
	for _, f := range []uintptr{cfDIB, cfDIBV5} {
		if r, _, _ := pIsClipFormat.Call(f); r == 0 {
			continue
		}
		b := clipBytes(f)
		if b == nil {
			continue
		}
		img, err := dibToImage(b)
		if err == nil {
			return img, nil
		}
		last = err
	}
	return nil, last
}

// ---- screenshot -------------------------------------------------------------------------------

var (
	shotBusy bool
	shotMu   sync.Mutex
	shotImg  *image.RGBA
	shotRe   bool
)

// startShot (thread dell'interfaccia): nasconde la chat, apre lo strumento di ritaglio di Windows e aspetta l'immagine negli appunti.
func startShot() {
	if shotBusy {
		return
	}
	shotBusy = true
	shotRe = visible
	if visible {
		hideChat()
	}
	seq0, _, _ := pClipSeq.Call()
	r, _, _ := pShellExecute.Call(0, uintptr(unsafe.Pointer(u16("open"))), uintptr(unsafe.Pointer(u16("ms-screenclip:"))), 0, 0, 1)
	if r <= 32 {
		logf("ms-screenclip: ShellExecute -> %d", r)
		shotBusy = false
		if shotRe {
			showChat()
		}
		messageBox("Non riesco ad aprire lo strumento di cattura di Windows. Usa «Allega immagine» con un file.")
		return
	}
	go func() {
		var img *image.RGBA
		deadline := time.Now().Add(90 * time.Second)
		for time.Now().Before(deadline) {
			time.Sleep(250 * time.Millisecond)
			s, _, _ := pClipSeq.Call()
			if s == seq0 {
				continue
			}
			seq0 = s
			if i, err := clipImage(); err == nil {
				img = i
				break
			}
		}
		shotMu.Lock()
		shotImg = img
		shotMu.Unlock()
		pPostMessage.Call(uintptr(hMain), wmShotDone, 0, 0)
	}()
}

func onShotDone() {
	shotMu.Lock()
	img := shotImg
	shotImg = nil
	shotMu.Unlock()
	shotBusy = false
	if shotRe {
		showChat()
	}
	if img == nil {
		return
	}
	if previewAndSend(img, "shot", true) == idRetry {
		startShot()
	}
}

// ---- file e incolla ---------------------------------------------------------------------------

func doAttach() {
	buf := make([]uint16, 1024)
	filter := windows.StringToUTF16("Immagini (PNG, JPG, GIF)\x00*.png;*.jpg;*.jpeg;*.gif\x00")
	filter = append(filter, 0)
	ofn := openFileName{Owner: hMain, Filter: &filter[0], File: &buf[0], MaxFile: uint32(len(buf)), Title: u16("Scegli un'immagine da inviare"), Flags: 0x00001000 | 0x00000800 | 0x00080000 | 0x4} // FILEMUSTEXIST|PATHMUSTEXIST|EXPLORER|HIDEREADONLY
	ofn.StructSize = uint32(unsafe.Sizeof(ofn))
	if r, _, _ := pGetOpenFileName.Call(uintptr(unsafe.Pointer(&ofn))); r == 0 {
		return
	}
	path := windows.UTF16ToString(buf)
	st, err := os.Stat(path)
	if err != nil || st.Size() > 40<<20 {
		messageBox("Il file non è leggibile o è troppo grande.")
		return
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		messageBox("Il file non è leggibile.")
		return
	}
	img, err := decodeAny(raw)
	if err != nil {
		messageBox("Formato non supportato: scegli un'immagine PNG, JPG o GIF.")
		return
	}
	full := scaleTo(img, 1<<14, 1<<14)
	previewAndSendRaw(full, raw, "file", false)
}

func doPaste() {
	img, err := clipImage()
	if err != nil {
		messageBox("Negli appunti non c'è un'immagine utilizzabile.")
		return
	}
	previewAndSend(img, "file", false)
}

// previewAndSend: mostra l'anteprima e, se l'utente conferma, invia l'immagine (PNG, ridotta se enorme). Restituisce il pulsante premuto.
func previewAndSend(img *image.RGBA, kind string, retry bool) int {
	return previewAndSendRaw(img, nil, kind, retry)
}

func previewAndSendRaw(img *image.RGBA, raw []byte, kind string, retry bool) int {
	res := confirmImage(img, retry)
	if res != idOK {
		return res
	}
	if raw == nil || len(raw) > 12<<20 {
		w := scaleTo(img, 2560, 1600)
		var err error
		if raw, err = encodePNG(w); err != nil {
			messageBox("Impossibile preparare l'immagine.")
			return idCancel
		}
		if len(raw) > 12<<20 {
			if raw, err = encodePNG(scaleTo(img, 1600, 1000)); err != nil || len(raw) > 12<<20 {
				messageBox("L'immagine è troppo grande.")
				return idCancel
			}
		}
	}
	doSendImg(base64.StdEncoding.EncodeToString(raw), kind)
	return idOK
}

// ---- finestra di anteprima / visualizzatore ---------------------------------------------------

type imgWin struct {
	px     []byte
	w, h   int
	ox, oy int
	result *int
	done   *bool
	modal  bool
}

var (
	imgWins    = map[windows.HWND]*imgWin{}
	imgClassOK bool
)

func regImgClass() {
	if imgClassOK {
		return
	}
	imgClassOK = true
	inst, _, _ := pGetModuleHandle.Call(0)
	cursor, _, _ := pLoadCursor.Call(0, 32512)
	bg, _, _ := pGetSysColorBrush.Call(15)
	cls := wndClassEx{WndProc: syscall.NewCallback(imgProc), Instance: windows.Handle(inst), Cursor: windows.Handle(cursor), Background: windows.Handle(bg), ClassName: u16("MyrmmImg"), Icon: hIconOn, IconSm: hIconOn}
	cls.Size = uint32(unsafe.Sizeof(cls))
	pRegisterClassEx.Call(uintptr(unsafe.Pointer(&cls)))
}

func imgProc(h, m, w, l uintptr) uintptr {
	defer guard("imgProc")

	win := imgWins[windows.HWND(h)]
	switch m {
	case wmPaint:
		var ps paintStruct
		hdc, _, _ := pBeginPaint.Call(h, uintptr(unsafe.Pointer(&ps)))
		if win != nil && len(win.px) > 0 {
			bi := bitmapInfoHeader{Size: uint32(unsafe.Sizeof(bitmapInfoHeader{})), Width: int32(win.w), Height: -int32(win.h), Planes: 1, Bits: 32}
			pStretchDIBits.Call(hdc, uintptr(win.ox), uintptr(win.oy), uintptr(win.w), uintptr(win.h), 0, 0, uintptr(win.w), uintptr(win.h), uintptr(unsafe.Pointer(&win.px[0])), uintptr(unsafe.Pointer(&bi)), 0, 0x00CC0020)
		}
		pEndPaint.Call(h, uintptr(unsafe.Pointer(&ps)))
		return 0
	case wmCommand:
		if win != nil && win.modal {
			*win.result = int(w & 0xffff)
			*win.done = true
		}
		return 0
	case wmClose:
		if win != nil && win.modal {
			*win.result = idCancel
			*win.done = true
		} else {
			pDestroyWindow.Call(h)
		}
		return 0
	case wmKeyDown:
		if w == 0x1B { // Esc
			pPostMessage.Call(h, wmClose, 0, 0)
		}
		return 0
	case wmLButtonUp:
		if win != nil && !win.modal {
			pDestroyWindow.Call(h)
		}
		return 0
	case wmDestroy:
		delete(imgWins, windows.HWND(h))
		return 0
	}
	r, _, _ := pDefWindowProc.Call(h, m, w, l)
	return r
}

func runModal(done *bool) {
	var m msg
	for !*done {
		r, _, _ := pGetMessage.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			pPostQuitMessage.Call(0)
			return
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessage.Call(uintptr(unsafe.Pointer(&m)))
	}
}

func screenSize() (int, int) {
	w, _, _ := pGetSystemMetrics.Call(0)
	h, _, _ := pGetSystemMetrics.Call(1)
	return int(w), int(h)
}

// confirmImage: anteprima con «Invia», «Annulla» e (per gli screenshot) «Rifai». Restituisce idOK, idCancel o idRetry.
func confirmImage(src *image.RGBA, retry bool) int {
	regImgClass()
	sw, sh := screenSize()
	view := scaleTo(src, minInt(720, sw-120), minInt(440, sh-260))
	vw, vh := view.Bounds().Dx(), view.Bounds().Dy()
	const pad, labH, btnH, btnW = 12, 28, 32, 110
	cw := maxInt(vw, 3*btnW+2*8) + 2*pad
	ch := pad + labH + vh + pad + btnH + pad
	rc := rect{0, 0, int32(cw), int32(ch)}
	const style = 0x00C00000 | 0x00080000 // WS_CAPTION | WS_SYSMENU
	pAdjustWindowRect.Call(uintptr(unsafe.Pointer(&rc)), style, 0, 0)
	ww, wh := int(rc.Right-rc.Left), int(rc.Bottom-rc.Top)
	inst, _, _ := pGetModuleHandle.Call(0)
	hw, _, _ := pCreateWindowEx.Call(0x00000008, uintptr(unsafe.Pointer(u16("MyrmmImg"))), uintptr(unsafe.Pointer(u16("Anteprima dell'immagine"))), style|wsVisible, uintptr((sw-ww)/2), uintptr((sh-wh)/2), uintptr(ww), uintptr(wh), uintptr(hMain), 0, inst, 0) // WS_EX_TOPMOST
	if hw == 0 {
		return idCancel
	}
	res, done := idCancel, false
	imgWins[windows.HWND(hw)] = &imgWin{px: bgra(view), w: vw, h: vh, ox: (cw - vw) / 2, oy: pad + labH, result: &res, done: &done, modal: true}
	mk := func(class, text string, st uintptr, x, y, w, h int, id uintptr) {
		c, _, _ := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(u16(class))), uintptr(unsafe.Pointer(u16(text))), st|wsChild|wsVisible, uintptr(x), uintptr(y), uintptr(w), uintptr(h), hw, id, inst, 0)
		pSendMessage.Call(c, wmSetFont, hFont, 1)
	}
	mk("STATIC", "Questa immagine verrà inviata all'assistenza. Controlla che non mostri dati riservati.", 0, pad, pad, cw-2*pad, labH, 0)
	x := cw - pad - btnW
	mk("BUTTON", "Invia", bsDefPush|wsTabstop, x, ch-pad-btnH, btnW, btnH, idOK)
	x -= btnW + 8
	mk("BUTTON", "Annulla", bsPush|wsTabstop, x, ch-pad-btnH, btnW, btnH, idCancel)
	if retry {
		x -= btnW + 8
		mk("BUTTON", "Rifai", bsPush|wsTabstop, x, ch-pad-btnH, btnW, btnH, idRetry)
	}
	pEnableWindow.Call(uintptr(hMain), 0)
	pShowWindow.Call(hw, swShow)
	pSetForegroundWnd.Call(hw)
	runModal(&done)
	pEnableWindow.Call(uintptr(hMain), 1)
	pDestroyWindow.Call(hw)
	return res
}

// showViewer: l'immagine a dimensione leggibile; si chiude con un clic o con Esc.
func showViewer(img *image.RGBA) {
	regImgClass()
	sw, sh := screenSize()
	view := scaleTo(img, sw*9/10, sh*8/10)
	vw, vh := view.Bounds().Dx(), view.Bounds().Dy()
	rc := rect{0, 0, int32(vw), int32(vh)}
	const style = 0x00C00000 | 0x00080000
	pAdjustWindowRect.Call(uintptr(unsafe.Pointer(&rc)), style, 0, 0)
	ww, wh := int(rc.Right-rc.Left), int(rc.Bottom-rc.Top)
	inst, _, _ := pGetModuleHandle.Call(0)
	hw, _, _ := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(u16("MyrmmImg"))), uintptr(unsafe.Pointer(u16("Immagine - clic o Esc per chiudere"))), style|wsVisible, uintptr((sw-ww)/2), uintptr((sh-wh)/2), uintptr(ww), uintptr(wh), 0, 0, inst, 0)
	if hw == 0 {
		return
	}
	imgWins[windows.HWND(hw)] = &imgWin{px: bgra(view), w: vw, h: vh}
	pShowWindow.Call(hw, swShow)
	pSetForegroundWnd.Call(hw)
	pSetFocus.Call(hw)
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// ---- miniature nella conversazione ------------------------------------------------------------

type thumbT struct {
	rtf  string
	w, h int
}

var (
	thumbMu   sync.Mutex
	thumbs    = map[string]*thumbT{}
	thumbBusy = map[string]bool{}
	thumbFail = map[string]int{}

	rtfData []byte
	rtfPos  int
	rtfCB   = syscall.NewCallback(rtfRead)

	imgSpans []imgSpan // intervalli di caratteri della conversazione occupati da un'immagine
	viewMu   sync.Mutex
	viewImgP *image.RGBA
)

type imgSpan struct {
	from, to int
	name     string
}

// thumbFor: l'anteprima se già pronta; altrimenti la scarica dall'agent in background e ridisegna la conversazione.
func thumbFor(name string) *thumbT {
	thumbMu.Lock()
	defer thumbMu.Unlock()
	if t := thumbs[name]; t != nil {
		return t
	}
	if thumbBusy[name] || thumbFail[name] >= 3 || cl == nil {
		return nil
	}
	thumbBusy[name] = true
	go func(c *client) {
		defer guard("thumb")
		var t *thumbT
		if b, err := c.image(name); err == nil {
			if img, err := decodeAny(b); err == nil {
				s := scaleTo(img, 260, 170)
				t = &thumbT{rtf: thumbRTF(s), w: s.Bounds().Dx(), h: s.Bounds().Dy()}
			}
		}
		logf("miniatura %s: pronta=%v", name, t != nil)
		thumbMu.Lock()
		thumbBusy[name] = false
		if t != nil {
			thumbs[name] = t
		} else {
			thumbFail[name]++
		}
		thumbMu.Unlock()
		mu.Lock()
		lastSig = "" // forza il ridisegno
		mu.Unlock()
		pPostMessage.Call(uintptr(hMain), wmRefresh, 0, 0)
	}(cl)
	return nil
}

func rtfRead(cookie, buf, cb, pcb uintptr) uintptr {
	defer guard("rtfRead")

	n := len(rtfData) - rtfPos
	if n > int(cb) {
		n = int(cb)
	}
	if n > 0 {
		copy(unsafe.Slice((*byte)(ptr(buf)), n), rtfData[rtfPos:rtfPos+n])
		rtfPos += n
	}
	*(*int32)(ptr(pcb)) = int32(n)
	return 0
}

// insertThumb inserisce l'anteprima alla fine della conversazione e ne ricorda la posizione per il clic.
func insertThumb(name string, t *thumbT) {
	pSendMessage.Call(uintptr(hRich), emSetSel, ^uintptr(0), ^uintptr(0))
	var a, b int32
	pSendMessage.Call(uintptr(hRich), emGetSel, uintptr(unsafe.Pointer(&a)), uintptr(unsafe.Pointer(&b)))
	rtfData, rtfPos = []byte(t.rtf), 0
	es := editStream{CbLo: uint32(rtfCB), CbHi: uint32(uint64(rtfCB) >> 32)}
	// il controllo è di sola lettura: l'inserimento di un'immagine va fatto con la scrittura abilitata
	const emSetReadOnly, wmGetTextLength = 0x00CF, 0x000E
	l0, _, _ := pSendMessage.Call(uintptr(hRich), wmGetTextLength, 0, 0)
	pSendMessage.Call(uintptr(hRich), emSetReadOnly, 0, 0)
	n, _, _ := pSendMessage.Call(uintptr(hRich), emStreamIn, sfRTF|sffSelection, uintptr(unsafe.Pointer(&es)))
	pSendMessage.Call(uintptr(hRich), emSetReadOnly, 1, 0)
	l1, _, _ := pSendMessage.Call(uintptr(hRich), wmGetTextLength, 0, 0)
	logf("miniatura: streamin=%d, testo %d -> %d, errore=%d", n, l0, l1, es.Err)
	{ // c'è un carattere oggetto (U+FFFC)? Serve per capire se RichEdit ha creato l'immagine
		type getTextEx struct {
			cb, flags, codepage uint32
			def, used           uintptr
		}
		buf := make([]uint16, l1+8)
		g := getTextEx{cb: uint32(len(buf) * 2), codepage: 1200}
		pSendMessage.Call(uintptr(hRich), 0x045E, uintptr(unsafe.Pointer(&g)), uintptr(unsafe.Pointer(&buf[0])))
		obj := 0
		for _, ch := range buf {
			if ch == 0xFFFC {
				obj++
			}
		}
		logf("miniatura: caratteri oggetto nel testo = %d", obj)
	}
	var c, d int32
	pSendMessage.Call(uintptr(hRich), emGetSel, uintptr(unsafe.Pointer(&c)), uintptr(unsafe.Pointer(&d)))
	imgSpans = append(imgSpans, imgSpan{from: int(a), to: int(d), name: name})
	logf("miniatura inserita: %s (%d..%d)", name, a, d)
}

// richProc: un clic su un'anteprima apre l'immagine grande.
func richProc(h, m, w, l uintptr) uintptr {
	defer guard("richProc")

	if m == wmLButtonUp {
		pt := point{int32(int16(l & 0xffff)), int32(int16((l >> 16) & 0xffff))}
		idx, _, _ := pSendMessage.Call(h, emCharFromPos, 0, uintptr(unsafe.Pointer(&pt)))
		i := int(int32(idx))
		for _, s := range imgSpans {
			if i >= s.from && i <= s.to {
				openViewer(s.name)
				break
			}
		}
	}
	r, _, _ := pCallWindowProc.Call(origRich, h, m, w, l)
	return r
}

func openViewer(name string) {
	c := cl
	if c == nil {
		return
	}
	go func() {
		b, err := c.image(name)
		if err != nil {
			return
		}
		img, err := decodeAny(b)
		if err != nil {
			return
		}
		viewMu.Lock()
		viewImgP = scaleTo(img, 1<<14, 1<<14)
		viewMu.Unlock()
		pPostMessage.Call(uintptr(hMain), wmViewImg, 0, 0)
	}()
}

func onViewImg() {
	viewMu.Lock()
	img := viewImgP
	viewImgP = nil
	viewMu.Unlock()
	if img != nil {
		showViewer(img)
	}
}

// askShotRequests: l'assistenza ha chiesto uno screenshot: lo si fa solo se l'utente acconsente.
var shotAsked int

func askShot(id int) {
	if id <= shotAsked {
		return
	}
	shotAsked = id
	r, _, _ := pMessageBox.Call(uintptr(hMain), uintptr(unsafe.Pointer(u16("L'assistenza ti chiede uno screenshot per capire il problema. Vuoi farlo ora? Potrai vedere l'immagine prima di inviarla."))), uintptr(unsafe.Pointer(u16("Assistenza"))), 0x24) // YESNO|ICONQUESTION
	if r == 6 {
		startShot()
	}
}

var _ = strings.TrimSpace
