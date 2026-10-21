//go:build windows

// myrmm-tray: icona nella systray e finestra di chat con l'assistenza (Windows), senza PowerShell.
// Parla solo con l'agent locale (127.0.0.1). Interfaccia con le API di Windows (user32/shell32/richedit), nessuna libreria grafica.
package tray

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	user32   = windows.NewLazySystemDLL("user32.dll")
	shell32  = windows.NewLazySystemDLL("shell32.dll")
	kernel32 = windows.NewLazySystemDLL("kernel32.dll")
	gdi32    = windows.NewLazySystemDLL("gdi32.dll")

	pRegisterClassEx       = user32.NewProc("RegisterClassExW")
	pCreateWindowEx        = user32.NewProc("CreateWindowExW")
	pDefWindowProc         = user32.NewProc("DefWindowProcW")
	pGetMessage            = user32.NewProc("GetMessageW")
	pTranslateMessage      = user32.NewProc("TranslateMessage")
	pDispatchMessage       = user32.NewProc("DispatchMessageW")
	pPostMessage           = user32.NewProc("PostMessageW")
	pSendMessage           = user32.NewProc("SendMessageW")
	pPostQuitMessage       = user32.NewProc("PostQuitMessage")
	pShowWindow            = user32.NewProc("ShowWindow")
	pIsWindowVisible       = user32.NewProc("IsWindowVisible")
	pSetForegroundWnd      = user32.NewProc("SetForegroundWindow")
	pSetFocus              = user32.NewProc("SetFocus")
	pMoveWindow            = user32.NewProc("MoveWindow")
	pGetClientRect         = user32.NewProc("GetClientRect")
	pSetTimer              = user32.NewProc("SetTimer")
	pLoadCursor            = user32.NewProc("LoadCursorW")
	pCreatePopupMenu       = user32.NewProc("CreatePopupMenu")
	pAppendMenu            = user32.NewProc("AppendMenuW")
	pTrackPopupMenu        = user32.NewProc("TrackPopupMenu")
	pDestroyMenu           = user32.NewProc("DestroyMenu")
	pGetCursorPos          = user32.NewProc("GetCursorPos")
	pGetWindowTextLen      = user32.NewProc("GetWindowTextLengthW")
	pGetWindowText         = user32.NewProc("GetWindowTextW")
	pSetWindowText         = user32.NewProc("SetWindowTextW")
	pEnableWindow          = user32.NewProc("EnableWindow")
	pGetKeyState           = user32.NewProc("GetKeyState")
	pSetWindowLongPtr      = user32.NewProc("SetWindowLongPtrW")
	pCallWindowProc        = user32.NewProc("CallWindowProcW")
	pCreateIconIndir       = user32.NewProc("CreateIconIndirect")
	pMessageBox            = user32.NewProc("MessageBoxW")
	pShellNotifyIcon       = shell32.NewProc("Shell_NotifyIconW")
	pGetModuleHandle       = kernel32.NewProc("GetModuleHandleW")
	pCreateMutex           = kernel32.NewProc("CreateMutexW")
	pCreateFont            = gdi32.NewProc("CreateFontW")
	pCreateBitmap          = gdi32.NewProc("CreateBitmap")
	pCreateDIBSection      = gdi32.NewProc("CreateDIBSection")
	pGetDC                 = user32.NewProc("GetDC")
	pReleaseDC             = user32.NewProc("ReleaseDC")
	pGetSysColorBrush      = user32.NewProc("GetSysColorBrush")
	pLoadLibrary           = kernel32.NewProc("LoadLibraryW")
	pRegisterWindowMessage = user32.NewProc("RegisterWindowMessageW")
	pShellExecute          = shell32.NewProc("ShellExecuteW")
)

const (
	wmCreate     = 0x0001
	wmDestroy    = 0x0002
	wmSize       = 0x0005
	wmClose      = 0x0010
	wmSetFont    = 0x0030
	wmKeyDown    = 0x0100
	wmChar       = 0x0102
	wmCommand    = 0x0111
	wmTimer      = 0x0113
	wmLButtonDbl = 0x0203
	wmRButtonUp  = 0x0205
	wmGetMinMax  = 0x0024
	wmApp        = 0x8000
	wmTray       = wmApp + 1 // messaggio dell'icona
	wmRefresh    = wmApp + 2 // nuovo stato dall'agent

	wsChild      = 0x40000000
	wsVisible    = 0x10000000
	wsOverlapped = 0x00CF0000 // WS_OVERLAPPEDWINDOW (senza WS_VISIBLE)
	wsTabstop    = 0x00010000
	wsVScroll    = 0x00200000
	wsBorder     = 0x00800000
	wsExClient   = 0x00000200

	esMultiline   = 0x0004
	esAutoVScroll = 0x0040
	esAutoHScroll = 0x0080
	esReadOnly    = 0x0800
	bsPush        = 0x0000
	bsDefPush     = 0x0001
	bsAutoCheck   = 0x0003

	swHide    = 0
	swShow    = 5
	swRestore = 9

	emSetSel       = 0x00B1
	emReplaceSel   = 0x00C2
	emSetCharFmt   = 0x0444
	emSetBkColor   = 0x0443
	emSetLimit     = 0x00C5
	emSetEventMask = 0x0445
	scfSelection   = 0x0001
	cfmColor       = 0x40000000
	cfmBold        = 0x00000001
	cfmSize        = 0x80000000
	cfmFace        = 0x20000000
	cfeBold        = 0x0001
	wmVScroll      = 0x0115
	sbBottom       = 7

	bmGetCheck = 0x00F0
	bnClicked  = 0

	nimAdd, nimModify, nimDelete         = 0, 1, 2
	nifMessage, nifIcon, nifTip, nifInfo = 0x1, 0x2, 0x4, 0x10
	niifInfo                             = 0x1

	idSend     = 101
	idTicket   = 102
	idSubject  = 103
	idInput    = 104
	idRich     = 105
	idMenuChat = 201
	timerPoll  = 1

	gwlpWndProc = -4
)

type wndClassEx struct {
	Size       uint32
	Style      uint32
	WndProc    uintptr
	ClsExtra   int32
	WndExtra   int32
	Instance   windows.Handle
	Icon       windows.Handle
	Cursor     windows.Handle
	Background windows.Handle
	MenuName   *uint16
	ClassName  *uint16
	IconSm     windows.Handle
}

type point struct{ X, Y int32 }
type rect struct{ Left, Top, Right, Bottom int32 }
type msg struct {
	HWnd    windows.HWND
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	Pt      point
}
type minMaxInfo struct {
	Reserved, MaxSize, MaxPosition, MinTrack, MaxTrack point
}
type charFormat struct {
	Size           uint32
	Mask           uint32
	Effects        uint32
	Height         int32
	Offset         int32
	TextColor      uint32
	CharSet        byte
	PitchAndFamily byte
	FaceName       [32]uint16
}
type notifyIconData struct {
	Size            uint32
	HWnd            windows.HWND
	ID              uint32
	Flags           uint32
	CallbackMessage uint32
	Icon            windows.Handle
	Tip             [128]uint16
	State           uint32
	StateMask       uint32
	Info            [256]uint16
	TimeoutVersion  uint32
	InfoTitle       [64]uint16
	InfoFlags       uint32
	GUIDItem        windows.GUID
	BalloonIcon     windows.Handle
}
type iconInfo struct {
	IsIcon   uint32
	XHotspot uint32
	YHotspot uint32
	Mask     windows.Handle
	Color    windows.Handle
}
type bitmapInfoHeader struct {
	Size          uint32
	Width, Height int32
	Planes, Bits  uint16
	Compression   uint32
	SizeImage     uint32
	XPels, YPels  int32
	ClrUsed       uint32
	ClrImportant  uint32
}

func u16(s string) *uint16 { p, _ := windows.UTF16PtrFromString(s); return p }

var (
	cl         *client
	hMain      windows.HWND
	hRich      windows.HWND
	hInput     windows.HWND
	hSend      windows.HWND
	hShot      windows.HWND
	hAttach    windows.HWND
	origRich   uintptr
	hTicket    windows.HWND
	hSubject   windows.HWND
	hFont      uintptr
	hIconOn    windows.Handle
	hIconOff   windows.Handle
	origEdit   uintptr
	editProcCB uintptr

	mu           sync.Mutex
	cur          *state // ultimo stato ricevuto dall'agent
	curErr       bool
	lastSig      string
	seen         int // ultimo messaggio dell'assistenza visto con la finestra aperta
	notified     int
	online       = -1
	iconOK       bool
	loggedNoBase bool
	opts         Options
	lastGood     = time.Now() // ultima risposta dell'agent: se tace per troppo tempo la tray esce
	wmTaskbar    uintptr
	visible      bool
)

// La finestra e il ciclo dei messaggi devono stare sullo stesso thread del sistema: senza questo il goroutine
// principale può migrare tra un thread e l'altro e le SendMessage verso la propria finestra restano appese.
func init() { runtime.LockOSThread() }

// Main: icona nella systray e finestra di chat; parte dall'agent (sottocomando «tray») nella sessione dell'utente.
// dpiInit rende il processo «system DPI aware»: senza, Windows ingrandisce a bitmap la finestra (testo sfocato e «enorme») e lo screenshot cattura solo la parte alta a sinistra dello schermo.
var dpi = 96

func dpiInit() {
	if p := user32.NewProc("SetProcessDpiAwarenessContext"); p.Find() == nil {
		p.Call(^uintptr(1)) // DPI_AWARENESS_CONTEXT_SYSTEM_AWARE (-2)
	} else {
		user32.NewProc("SetProcessDPIAware").Call()
	}
	if g := user32.NewProc("GetDpiForSystem"); g.Find() == nil {
		if d, _, _ := g.Call(); d >= 96 {
			dpi = int(d)
		}
	}
}

// sc converte pixel a 96 dpi in pixel reali.
func sc(n int) int { return (n*dpi + 48) / 96 }

func Main(o Options) {
	opts = o
	dpiInit()
	// stesso nome del mutex della tray PowerShell: le due non possono girare insieme
	h, _, merr := pCreateMutex.Call(0, 0, uintptr(unsafe.Pointer(u16(`Local\myrmm-tray`))))
	if h == 0 || merr == windows.ERROR_ALREADY_EXISTS {
		return
	}
	openLog()
	logf("avvio, exe=%s", os.Args[0])
	dir := o.Dir
	if dir == "" {
		dir = os.Getenv("MYRMM_DIR")
	}
	if dir == "" {
		if exe, err := os.Executable(); err == nil {
			dir = filepath.Dir(exe)
		}
	}
	// RichEdit crea le immagini come oggetti OLE: senza OleInitialize sul thread della finestra lo spazio viene riservato ma non si disegna nulla
	r, _, _ := windows.NewLazySystemDLL("ole32.dll").NewProc("OleInitialize").Call(0)
	logf("OleInitialize -> 0x%x", r)
	pLoadLibrary.Call(uintptr(unsafe.Pointer(u16("msftedit.dll"))))
	hFont, _, _ = pCreateFont.Call(uintptr(-sc(18)), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, uintptr(unsafe.Pointer(u16("Segoe UI")))) // -18 = ~10pt
	hIconOn, hIconOff = makeIcon(0x2563eb), makeIcon(0x787878)

	inst, _, _ := pGetModuleHandle.Call(0)
	cursor, _, _ := pLoadCursor.Call(0, 32512)
	bg, _, _ := pGetSysColorBrush.Call(15) // COLOR_BTNFACE
	cls := wndClassEx{Style: 0, WndProc: syscall.NewCallback(wndProc), Instance: windows.Handle(inst), Cursor: windows.Handle(cursor), Background: windows.Handle(bg), ClassName: u16("MyrmmTray"), Icon: hIconOn, IconSm: hIconOn}
	cls.Size = uint32(unsafe.Sizeof(cls))
	pRegisterClassEx.Call(uintptr(unsafe.Pointer(&cls)))
	hw, _, _ := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(u16("MyrmmTray"))), uintptr(unsafe.Pointer(u16("Assistenza"))), wsOverlapped, 0x80000000, 0x80000000, uintptr(sc(460)), uintptr(sc(580)), 0, 0, inst, 0)
	hMain = windows.HWND(hw)
	logf("finestra creata: %v, dir=%s", hw != 0, dir)
	buildControls(inst)
	logf("controlli creati")

	setBase := func() bool {
		if cl != nil {
			return true
		}
		b, err := baseFromDir(dir)
		if err != nil {
			return false
		}
		cl = newClient(b)
		return true
	}
	_ = setBase
	wmTaskbar, _, _ = pRegisterWindowMessage.Call(uintptr(unsafe.Pointer(u16("TaskbarCreated"))))
	addIcon()
	pSetTimer.Call(uintptr(hMain), timerPoll, 3000, 0)
	go poller(dir)

	var m msg
	for {
		r, _, _ := pGetMessage.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			break
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessage.Call(uintptr(unsafe.Pointer(&m)))
	}
	removeIcon()
}

func buildControls(inst uintptr) {
	mk := func(class string, text string, style uintptr, id uintptr) windows.HWND {
		h, _, _ := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(u16(class))), uintptr(unsafe.Pointer(u16(text))), style|wsChild|wsVisible, 0, 0, 10, 10, uintptr(hMain), id, inst, 0)
		pSendMessage.Call(h, wmSetFont, hFont, 1)
		return windows.HWND(h)
	}
	hRich = mk("RICHEDIT50W", "", wsVScroll|esMultiline|esReadOnly|esAutoVScroll|wsBorder, idRich)
	setOleCallback(uintptr(hRich))
	pSendMessage.Call(uintptr(hRich), emSetBkColor, 0, 0xffffff)
	hTicket = mk("BUTTON", "Apri una richiesta di assistenza (ticket)", bsAutoCheck|wsTabstop, idTicket)
	hSubject = mk("EDIT", "", wsBorder|esAutoHScroll|wsTabstop, idSubject)
	pSendMessage.Call(uintptr(hSubject), emSetLimit, 140, 0)
	pShowWindow.Call(uintptr(hSubject), swHide)
	hInput = mk("EDIT", "", wsBorder|esMultiline|esAutoVScroll|wsVScroll|wsTabstop, idInput)
	pSendMessage.Call(uintptr(hInput), emSetLimit, 2000, 0)
	hSend = mk("BUTTON", "Invia", bsDefPush|wsTabstop, idSend)
	hShot = mk("BUTTON", "Screenshot", bsPush|wsTabstop, idShot)
	hAttach = mk("BUTTON", "Allega immagine...", bsPush|wsTabstop, idAttach)
	origRich, _, _ = pSetWindowLongPtr.Call(uintptr(hRich), uintptr(^uint(3)), syscall.NewCallback(richProc))
	editProcCB = syscall.NewCallback(editProc)
	origEdit, _, _ = pSetWindowLongPtr.Call(uintptr(hInput), uintptr(^uint(3)), editProcCB) // GWLP_WNDPROC = -4
}

// editProc: Invio invia, Maiusc+Invio va a capo.
func editProc(h, m, w, l uintptr) uintptr {
	defer guard("editProc")

	if m == wmKeyDown && w == 0x0D {
		if s, _, _ := pGetKeyState.Call(0x10); int16(s) >= 0 {
			pPostMessage.Call(uintptr(hMain), wmCommand, idSend, 0)
			return 0
		}
	}
	if m == wmPaste && clipHasImage() { // incolla un'immagine: anteprima e invio
		pPostMessage.Call(uintptr(hMain), wmCommand, idPaste, 0)
		return 0
	}
	if m == wmChar && w == 0x0D {
		if s, _, _ := pGetKeyState.Call(0x10); int16(s) >= 0 {
			return 0
		}
	}
	r, _, _ := pCallWindowProc.Call(origEdit, h, m, w, l)
	return r
}

func wndProc(h, m, w, l uintptr) uintptr {
	defer guard("wndProc")

	switch m {
	case wmSize:
		doLayout()
		return 0
	case wmGetMinMax:
		mm := (*minMaxInfo)(*(*unsafe.Pointer)(unsafe.Pointer(&l)))
		mm.MinTrack = point{360, 380}
		return 0
	case wmClose:
		hideChat()
		return 0
	case wmDestroy:
		pPostQuitMessage.Call(0)
		return 0
	case wmCommand:
		id := w & 0xffff
		switch id {
		case idSend:
			doSend()
		case idTicket:
			doLayout()
		case idMenuChat:
			showChat()
		case idShot, idMenuShot:
			startShot()
		case idAttach:
			doAttach()
		case idPaste:
			doPaste()
		}
		return 0
	case wmShotDone:
		onShotDone()
		return 0
	case wmViewImg:
		onViewImg()
		return 0
	case wmTimer:
		if !iconOK { // Explorer può non essere pronto all'accesso: si riprova finché l'icona non è stata aggiunta
			addIcon()
		}
		return 0
	case wmRefresh:
		refresh()
		return 0
	case wmTray:
		switch l & 0xffff {
		case wmLButtonDbl:
			showChat()
		case wmRButtonUp:
			popupMenu()
		case 0x405: // NIN_BALLOONUSERCLICK
			showChat()
		}
		return 0
	}
	if wmTaskbar != 0 && m == wmTaskbar { // Explorer riavviato: l'icona va ricreata
		iconOK, online = false, -1
		addIcon()
		return 0
	}
	r, _, _ := pDefWindowProc.Call(h, m, w, l)
	return r
}

func doLayout() {
	var rc rect
	pGetClientRect.Call(uintptr(hMain), uintptr(unsafe.Pointer(&rc)))
	W, H := int(rc.Right), int(rc.Bottom)
	pad, btnW, chkH, subjH := sc(8), sc(84), sc(22), sc(24)
	ticket := checked(hTicket)
	inputH := sc(70)
	barH := sc(26)
	bottom := H - pad
	// in basso: [input | invia], sopra la barra con Screenshot e Allega immagine
	pMoveWindow.Call(uintptr(hInput), uintptr(pad), uintptr(bottom-inputH), uintptr(W-3*pad-btnW), uintptr(inputH), 1)
	pMoveWindow.Call(uintptr(hSend), uintptr(W-pad-btnW), uintptr(bottom-inputH), uintptr(btnW), uintptr(inputH), 1)
	pMoveWindow.Call(uintptr(hShot), uintptr(pad), uintptr(bottom-inputH-barH-sc(4)), uintptr(sc(110)), uintptr(barH), 1)
	pMoveWindow.Call(uintptr(hAttach), uintptr(pad+sc(118)), uintptr(bottom-inputH-barH-sc(4)), uintptr(sc(150)), uintptr(barH), 1)
	y := bottom - inputH - barH - 4 - pad
	if ticket {
		pShowWindow.Call(uintptr(hSubject), swShow)
		y -= subjH
		pMoveWindow.Call(uintptr(hSubject), uintptr(pad), uintptr(y), uintptr(W-2*pad), uintptr(subjH), 1)
		y -= sc(4)
	} else {
		pShowWindow.Call(uintptr(hSubject), swHide)
	}
	y -= chkH
	pMoveWindow.Call(uintptr(hTicket), uintptr(pad), uintptr(y), uintptr(W-2*pad), uintptr(chkH), 1)
	pMoveWindow.Call(uintptr(hRich), 0, 0, uintptr(W), uintptr(y-sc(4)), 1)
}

func checked(h windows.HWND) bool {
	r, _, _ := pSendMessage.Call(uintptr(h), bmGetCheck, 0, 0)
	return r == 1
}

func getText(h windows.HWND) string {
	n, _, _ := pGetWindowTextLen.Call(uintptr(h))
	if n == 0 {
		return ""
	}
	buf := make([]uint16, n+1)
	pGetWindowText.Call(uintptr(h), uintptr(unsafe.Pointer(&buf[0])), n+1)
	return strings.ReplaceAll(windows.UTF16ToString(buf), "\r\n", "\n")
}

func setText(h windows.HWND, s string) {
	pSetWindowText.Call(uintptr(h), uintptr(unsafe.Pointer(u16(s))))
}

func showChat() {
	visible = true
	pShowWindow.Call(uintptr(hMain), swShow)
	pShowWindow.Call(uintptr(hMain), swRestore)
	pSetForegroundWnd.Call(uintptr(hMain))
	pSetFocus.Call(uintptr(hInput))
	doLayout()
	go pollOnce()
}

func hideChat() { visible = false; pShowWindow.Call(uintptr(hMain), swHide) }

func doSend() { doSendImg("", "") }

// doSendImg invia il testo scritto (e, se c'è, l'immagine in base64) con la richiesta di assistenza eventualmente spuntata.
func doSendImg(img, kind string) {
	t := strings.TrimSpace(getText(hInput))
	if (t == "" && img == "") || cl == nil {
		return
	}
	req := sendReq{Text: t, Img: img, Kind: kind}
	if checked(hTicket) {
		ti := strings.TrimSpace(getText(hSubject))
		if ti == "" {
			messageBox("Scrivi l'oggetto della richiesta.")
			return
		}
		req.Ticket, req.Title = true, ti
	}
	pEnableWindow.Call(uintptr(hSend), 0)
	go func(c *client) {
		err := c.send(req)
		pEnableWindow.Call(uintptr(hSend), 1)
		if err != nil {
			logf("invio: %v", err)
			messageBox("Impossibile inviare il messaggio: riprova tra poco.")
			return
		}
		// svuota solo a invio riuscito
		setText(hInput, "")
		if req.Ticket {
			pSendMessage.Call(uintptr(hTicket), 0x00F1, 0, 0) // BM_SETCHECK
			setText(hSubject, "")
			pPostMessage.Call(uintptr(hMain), wmSize, 0, 0)
		}
		pollOnce()
	}(cl)
}

func messageBox(s string) {
	pMessageBox.Call(uintptr(hMain), uintptr(unsafe.Pointer(u16(s))), uintptr(unsafe.Pointer(u16("Assistenza"))), 0x40)
}

// ---- stato dall'agent -----------------------------------------------------------------------

func poller(dir string) {
	for {
		if cl == nil && opts.Base != "" {
			cl = newClientKey(opts.Base, opts.Key)
			logf("API locale: %s (sessione con chiave)", opts.Base)
		}
		if cl == nil {
			if b, err := baseFromDir(dir); err == nil {
				cl = newClient(b)
				logf("API locale: %s", b)
			} else if !loggedNoBase {
				loggedNoBase = true
				logf("tray.json non leggibile in %s: %v", dir, err)
			}
		}
		pollOnce()
		d := 5 * time.Second
		if visible {
			d = 2 * time.Second
		}
		time.Sleep(d)
	}
}

func pollOnce() {
	c := cl
	if c == nil {
		setOnline(false)
		return
	}
	mu.Lock()
	sn := seen
	mu.Unlock()
	st, err := c.state(visible, sn)
	mu.Lock()
	if err != nil {
		if !curErr {
			logf("/state: %v", err)
		}
		curErr = true
		gone := time.Since(lastGood) > 75*time.Second
		mu.Unlock()
		if gone && opts.Base != "" { // servizio fermo da troppo: non resto a bloccare l'eseguibile (aggiornamenti) né a mostrare un'icona morta
			logf("agent non raggiungibile da oltre un minuto: esco (il servizio mi rilancia quando torna)")
			quitNow()
		}
		setOnline(false)
		return
	}
	curErr = false
	cur = st
	lastGood = time.Now()
	mu.Unlock()
	if st.Disabled {
		logf("l'icona è stata disattivata dalla console: esco")
		quitNow()
	}
	if opts.Version != "" && st.Version != "" && st.Version != opts.Version {
		logf("l'agent è passato alla versione %s (io sono la %s): esco, il servizio mi rilancia", st.Version, opts.Version)
		quitNow()
	}
	pPostMessage.Call(uintptr(hMain), wmRefresh, 0, 0)
}

// refresh gira sul thread dell'interfaccia: aggiorna icona, notifiche e conversazione.
func refresh() {
	mu.Lock()
	st := cur
	mu.Unlock()
	if st == nil {
		return
	}
	setOnline(st.Online)
	for _, e := range st.Log {
		if e.Dir == "op" && e.Kind == "shotreq" && e.SrvID > st.Read && e.SrvID > shotAsked {
			askShot(e.SrvID)
			break
		}
	}
	if visible {
		mu.Lock()
		seen = maxOpID(st.Log)
		mu.Unlock()
		renderChat(st.Log)
		return
	}
	if e, ok := newestOp(st, notified); ok {
		notified = e.SrvID
		t := e.Text
		if t == "" && e.Img != "" {
			t = "Ti ha inviato un'immagine."
		}
		if r := []rune(t); len(r) > 120 {
			t = string(r[:120]) + "..."
		}
		balloon("Assistenza", t)
	}
}

func renderChat(log []logEntry) {
	sig := signature(log)
	mu.Lock()
	same := sig == lastSig
	lastSig = sig
	mu.Unlock()
	if same {
		return
	}
	setText(hRich, "")
	imgSpans = imgSpans[:0]
	for _, s := range renderSegments(log) {
		if s.Img != "" {
			if t := thumbFor(s.Img); t != nil {
				insertThumb(s.Img, t)
				continue
			}
			if thumbFailed(s.Img) {
				appendClickable(s.Img, segment{Text: "[immagine: clic qui per aprirla]\n", Color: colOp, Bold: true})
				continue
			}
			s = segment{Text: "(immagine in caricamento...)", Color: colMuted}
		}
		appendStyled(s)
	}
	pSendMessage.Call(uintptr(hRich), wmVScroll, sbBottom, 0)
}

func appendStyled(s segment) {
	pSendMessage.Call(uintptr(hRich), emSetSel, ^uintptr(0), ^uintptr(0))
	var cf charFormat
	cf.Size = uint32(unsafe.Sizeof(cf))
	cf.Mask = cfmColor | cfmBold | cfmSize | cfmFace
	cf.TextColor = s.Color
	if s.Bold {
		cf.Effects = cfeBold
	}
	cf.Height = 180 // 9 pt in twips/10... (1/20 pt): 200 = 10 pt
	if !s.Bold {
		cf.Height = 200
	}
	copy(cf.FaceName[:], windows.StringToUTF16("Segoe UI"))
	pSendMessage.Call(uintptr(hRich), emSetCharFmt, scfSelection, uintptr(unsafe.Pointer(&cf)))
	pSendMessage.Call(uintptr(hRich), emReplaceSel, 0, uintptr(unsafe.Pointer(u16(strings.ReplaceAll(s.Text, "\n", "\r")))))
}

// ---- icona e menu ---------------------------------------------------------------------------

func addIcon() {
	var nd notifyIconData
	nd.Size = uint32(unsafe.Sizeof(nd))
	nd.HWnd, nd.ID = hMain, 1
	nd.Flags = nifMessage | nifIcon | nifTip
	nd.CallbackMessage = wmTray
	nd.Icon = hIconOff
	copy(nd.Tip[:], windows.StringToUTF16("myrmm"))
	r, _, e := pShellNotifyIcon.Call(nimAdd, uintptr(unsafe.Pointer(&nd)))
	iconOK = r != 0
	logf("Shell_NotifyIcon(ADD) -> %d (%v)", r, e)
}

// quitNow: uscita dal thread del poller (toglie l'icona, altrimenti resterebbe fino al passaggio del mouse).
func quitNow() {
	removeIcon()
	os.Exit(0)
}

func removeIcon() {
	var nd notifyIconData
	nd.Size = uint32(unsafe.Sizeof(nd))
	nd.HWnd, nd.ID = hMain, 1
	pShellNotifyIcon.Call(nimDelete, uintptr(unsafe.Pointer(&nd)))
}

func setOnline(on bool) {
	v := 0
	if on {
		v = 1
	}
	if online == v {
		return
	}
	online = v
	var nd notifyIconData
	nd.Size = uint32(unsafe.Sizeof(nd))
	nd.HWnd, nd.ID = hMain, 1
	nd.Flags = nifIcon | nifTip
	tip := "myrmm - server non raggiungibile"
	nd.Icon = hIconOff
	if on {
		nd.Icon, tip = hIconOn, "myrmm - collegato"
	}
	copy(nd.Tip[:], windows.StringToUTF16(tip))
	pShellNotifyIcon.Call(nimModify, uintptr(unsafe.Pointer(&nd)))
}

func balloon(title, text string) {
	var nd notifyIconData
	nd.Size = uint32(unsafe.Sizeof(nd))
	nd.HWnd, nd.ID = hMain, 1
	nd.Flags = nifInfo
	nd.InfoFlags = niifInfo
	copy(nd.InfoTitle[:], windows.StringToUTF16(title))
	copy(nd.Info[:], windows.StringToUTF16(text))
	pShellNotifyIcon.Call(nimModify, uintptr(unsafe.Pointer(&nd)))
}

func popupMenu() {
	menu, _, _ := pCreatePopupMenu.Call()
	defer pDestroyMenu.Call(menu)
	mu.Lock()
	st := cur
	mu.Unlock()
	head, ver, stat := "myrmm", "Agent", "Server non raggiungibile"
	if st != nil {
		head, ver = "myrmm - "+st.Host, "Agent v"+st.Version
		if st.Online {
			stat = "Collegato al server"
		}
	}
	for _, t := range []string{head, ver, stat} {
		pAppendMenu.Call(menu, 0x2|0x1, 0, uintptr(unsafe.Pointer(u16(t)))) // MF_GRAYED|MF_DISABLED... (0x1 | 0x2)
	}
	pAppendMenu.Call(menu, 0x800, 0, 0) // separatore
	pAppendMenu.Call(menu, 0, idMenuChat, uintptr(unsafe.Pointer(u16("Contatta l'assistenza..."))))
	pAppendMenu.Call(menu, 0, idMenuShot, uintptr(unsafe.Pointer(u16("Invia uno screenshot..."))))
	var pt point
	pGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
	pSetForegroundWnd.Call(uintptr(hMain))
	pTrackPopupMenu.Call(menu, 0, uintptr(pt.X), uintptr(pt.Y), 0, uintptr(hMain), 0)
	pPostMessage.Call(uintptr(hMain), 0, 0, 0)
}

// makeIcon: cerchio colorato con una «m» bianca, disegnato a pixel (nessun file di risorse).
func makeIcon(rgb uint32) windows.Handle {
	const n = 32
	glyph := []string{ // «m» 9x6 ingrandita 2x
		"#.##.##..",
		"##..#..#.",
		"#...#...#",
		"#...#...#",
		"#...#...#",
		"#...#...#",
	}
	pix := make([]uint32, n*n)
	mask := make([]byte, n*n/8)
	cx, cy, r := 15.5, 15.5, 15.0
	for y := 0; y < n; y++ {
		for x := 0; x < n; x++ {
			dx, dy := float64(x)-cx, float64(y)-cy
			if dx*dx+dy*dy <= r*r {
				pix[y*n+x] = 0xff000000 | (rgb>>16&0xff)<<0 | (rgb>>8&0xff)<<8 | (rgb&0xff)<<16
			}
		}
	}
	for gy, row := range glyph {
		for gx, ch := range row {
			if ch != '#' {
				continue
			}
			for dy := 0; dy < 2; dy++ {
				for dx := 0; dx < 2; dx++ {
					x, y := 7+gx*2+dx+0, 10+gy*2+dy
					if x < n && y < n {
						pix[y*n+x] = 0xffffffff
					}
				}
			}
		}
	}
	bi := bitmapInfoHeader{Size: uint32(unsafe.Sizeof(bitmapInfoHeader{})), Width: n, Height: -n, Planes: 1, Bits: 32}
	dc, _, _ := pGetDC.Call(0)
	var bits unsafe.Pointer
	color, _, _ := pCreateDIBSection.Call(dc, uintptr(unsafe.Pointer(&bi)), 0, uintptr(unsafe.Pointer(&bits)), 0, 0)
	pReleaseDC.Call(0, dc)
	if color == 0 || bits == nil {
		return 0
	}
	copy(unsafe.Slice((*uint32)(bits), n*n), pix)
	m, _, _ := pCreateBitmap.Call(n, n, 1, 1, uintptr(unsafe.Pointer(&mask[0])))
	ii := iconInfo{IsIcon: 1, Mask: windows.Handle(m), Color: windows.Handle(color)}
	ic, _, _ := pCreateIconIndir.Call(uintptr(unsafe.Pointer(&ii)))
	return windows.Handle(ic)
}

var _ = fmt.Sprint

// log di diagnosi: %TEMP%\myrmm-tray.log (si azzera oltre 200 KB)
var logFile *os.File

func openLog() {
	p := filepath.Join(os.TempDir(), "myrmm-tray.log")
	if st, err := os.Stat(p); err == nil && st.Size() > 200<<10 {
		os.Remove(p)
	}
	logFile, _ = os.OpenFile(p, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
}

func logf(f string, a ...any) {
	if logFile != nil {
		fmt.Fprintf(logFile, "%s %s\n", time.Now().Format("2006-01-02 15:04:05"), fmt.Sprintf(f, a...))
	}
}

// guard registra nel log un panic avvenuto in una funzione chiamata da Windows (altrimenti il processo muore senza lasciare traccia).
func guard(where string) {
	if r := recover(); r != nil {
		logf("PANIC in %s: %v\n%s", where, r, debug.Stack())
	}
}
