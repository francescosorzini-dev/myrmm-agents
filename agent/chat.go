package main

import (
	"bytes"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	_ "image/gif"
	"image/jpeg"
	_ "image/png"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// Chat con l'utente collegato (solo Windows). L'agent fa da ponte: il server consegna i messaggi dell'operatore
// negli heartbeat, l'icona nella systray (tray.ps1, nella sessione dell'utente) li legge da un'API locale
// su 127.0.0.1 e invia le risposte, che l'agent inoltra al server.

type chatEntry struct {
	Dir    string `json:"dir"`              // op (dall'assistenza) | user
	Author string `json:"author,omitempty"` // nome dell'operatore
	Text   string `json:"text"`
	TS     string `json:"ts"`
	SrvID  int    `json:"srv_id,omitempty"` // id sul server (messaggi dell'operatore)
	CID    string `json:"cid,omitempty"`    // id locale (messaggi dell'utente)
	Sent   bool   `json:"sent,omitempty"`   // messaggio dell'utente accettato dal server
	Ticket bool   `json:"ticket,omitempty"` // il messaggio è una richiesta di assistenza (apre un ticket)
	Title  string `json:"title,omitempty"`  // oggetto della richiesta
	Img    string `json:"img,omitempty"`    // immagine allegata: nome del file in chatimg/ (utente: scelto dall'agent; assistenza: nome sul server)
	Kind   string `json:"kind,omitempty"`   // shot (screenshot) | file (immagine scelta) | shotreq (l'assistenza chiede uno screenshot)
	Tries  int    `json:"tries,omitempty"`  // tentativi di invio di un'immagine (oltre 3 si rinuncia: un corpo troppo grande bloccherebbe l'heartbeat)
	Failed bool   `json:"failed,omitempty"` // immagine non inviata
}

const (
	chatImgMax  = 1536 << 10 // 1,5 MB per immagine (la tray la riduce prima)
	chatImgKeep = 30 * 24 * time.Hour
)

var chatImgName = regexp.MustCompile(`^[A-Za-z0-9_-]{1,80}(\.(png|jpg|gif|webp))?$`)

const chatImgRawMax = 14 << 20 // PNG grezzo dalla tray: l'agent lo riduce e lo comprime

// chatImgNormalize: decodifica (PNG, JPEG, GIF), riduce il lato lungo a 1600 px su fondo bianco e ricomprime in JPEG
// fino a stare sotto chatImgMax. La riduzione sta qui e non nello script della tray: gli antivirus segnalano come
// «screenshot tool» gli script PowerShell che catturano e codificano immagini.
func chatImgNormalize(raw []byte) ([]byte, bool) {
	src, _, err := image.Decode(bytes.NewReader(raw))
	if err != nil {
		return nil, false
	}
	side := 1600
	for try := 0; try < 4; try++ {
		out := chatImgScale(src, side)
		for _, q := range []int{80, 65, 50} {
			var buf bytes.Buffer
			if jpeg.Encode(&buf, out, &jpeg.Options{Quality: q}) == nil && buf.Len() <= chatImgMax {
				return buf.Bytes(), true
			}
		}
		side = side * 7 / 10
	}
	return nil, false
}

func chatImgScale(src image.Image, side int) *image.RGBA {
	b := src.Bounds()
	w, h := b.Dx(), b.Dy()
	nw, nh := w, h
	if m := max(w, h); m > side {
		nw, nh = max(1, w*side/m), max(1, h*side/m)
	}
	dst := image.NewRGBA(image.Rect(0, 0, nw, nh))
	draw.Draw(dst, dst.Bounds(), image.NewUniform(color.White), image.Point{}, draw.Src)
	if nw == w && nh == h {
		draw.Draw(dst, dst.Bounds(), src, b.Min, draw.Over)
		return dst
	}
	for y := 0; y < nh; y++ { // media sull'area di origine che copre il pixel di destinazione
		y0, y1 := b.Min.Y+y*h/nh, b.Min.Y+max(y*h/nh+1, (y+1)*h/nh)
		for x := 0; x < nw; x++ {
			x0, x1 := b.Min.X+x*w/nw, b.Min.X+max(x*w/nw+1, (x+1)*w/nw)
			var r, g, bl, n uint32
			for yy := y0; yy < y1; yy++ {
				for xx := x0; xx < x1; xx++ {
					cr, cg, cb, ca := src.At(xx, yy).RGBA() // premoltiplicati: sul bianco si compone da sé
					r, g, bl, n = r+cr+(0xffff-ca), g+cg+(0xffff-ca), bl+cb+(0xffff-ca), n+1
				}
			}
			dst.SetRGBA(x, y, color.RGBA{uint8(r / n >> 8), uint8(g / n >> 8), uint8(bl / n >> 8), 255})
		}
	}
	return dst
}

func chatImgDir() string { return filepath.Join(dataDir(), "chatimg") }

// chatImgType: tipo reale dai primi byte ("" se non è un'immagine ammessa).
func chatImgType(b []byte) string {
	switch {
	case bytes.HasPrefix(b, []byte("\x89PNG\r\n\x1a\n")):
		return "png"
	case bytes.HasPrefix(b, []byte("\xff\xd8\xff")):
		return "jpg"
	case bytes.HasPrefix(b, []byte("GIF8")):
		return "gif"
	case len(b) > 12 && bytes.HasPrefix(b, []byte("RIFF")) && string(b[8:12]) == "WEBP":
		return "webp"
	}
	return ""
}

func chatImgStore(b []byte) (string, bool) {
	ext := chatImgType(b)
	if ext == "" || len(b) > chatImgMax {
		return "", false
	}
	r := make([]byte, 12)
	_, _ = rand.Read(r)
	name := hex.EncodeToString(r) + "." + ext
	if os.MkdirAll(chatImgDir(), 0o700) != nil || os.WriteFile(filepath.Join(chatImgDir(), name), b, 0o600) != nil {
		return "", false
	}
	return name, true
}

// chatImgClean: toglie dal disco le immagini non più citate dalla conversazione e quelle più vecchie di 30 giorni.
func chatImgClean() {
	chatMu.Lock()
	chatLoad()
	keep := map[string]bool{}
	for i := range chatLog {
		if chatLog[i].Img == "" {
			continue
		}
		if t, err := time.Parse(time.RFC3339, chatLog[i].TS); err == nil && time.Since(t) > chatImgKeep {
			chatLog[i].Img = ""
			continue
		}
		keep[chatLog[i].Img] = true
	}
	chatMu.Unlock()
	ents, _ := os.ReadDir(chatImgDir())
	for _, e := range ents {
		if fi, err := e.Info(); err != nil || time.Since(fi.ModTime()) < 2*time.Minute {
			continue // appena scritta: la riga della conversazione potrebbe non esserci ancora
		}
		if !keep[e.Name()] {
			_ = os.Remove(filepath.Join(chatImgDir(), e.Name()))
		}
	}
}

type chatResp struct {
	Msgs []struct {
		ID     int    `json:"id"`
		Author string `json:"author"`
		Text   string `json:"text"`
		TS     string `json:"ts"`
		Img    string `json:"img"`
		Kind   string `json:"kind"`
	} `json:"msgs"`
	Ok []string `json:"ok"`
}

var trayFast atomic.Int64 // fine (UnixNano) del collegamento rapido richiesto dalla tray

var (
	chatMu     sync.Mutex
	chatLog    []chatEntry
	chatAck    int // ultimo messaggio dell'operatore ricevuto dall'agent
	chatRead   int // ultimo messaggio visto dall'utente (finestra aperta)
	chatLoaded bool
	trayLast   time.Time // ultima richiesta della tray
	trayOpen   time.Time // ultima volta che la finestra della chat era aperta
	chatWake   = make(chan struct{}, 1)
	hbOK       time.Time // ultimo heartbeat riuscito
	chatMeta   struct{ Host, Site string }
)

func chatFile() string { return filepath.Join(dataDir(), "chat.json") }

func chatLoad() {
	if chatLoaded {
		return
	}
	chatLoaded = true
	var f struct {
		Ack, Read int
		Log       []chatEntry
	}
	if b, err := os.ReadFile(chatFile()); err == nil && json.Unmarshal(b, &f) == nil {
		chatAck, chatRead, chatLog = f.Ack, f.Read, f.Log
	}
}

func chatSaveLocked() {
	if len(chatLog) > 200 {
		chatLog = chatLog[len(chatLog)-200:]
	}
	b, _ := json.Marshal(map[string]any{"Ack": chatAck, "Read": chatRead, "Log": chatLog})
	_ = os.WriteFile(chatFile()+".tmp", b, 0o600)
	_ = os.Rename(chatFile()+".tmp", chatFile())
}

// chatPrepare: campo "chat" da allegare al heartbeat (nil se la chat non è attiva su questo device).
func chatPrepare() map[string]any {
	chatMu.Lock()
	defer chatMu.Unlock()
	chatLoad()
	out := []map[string]string{}
	for i := range chatLog {
		e := chatLog[i]
		if e.Dir == "user" && !e.Sent && e.CID != "" {
			m := map[string]string{"cid": e.CID, "text": e.Text}
			if e.Img != "" {
				b, err := os.ReadFile(filepath.Join(chatImgDir(), filepath.Base(e.Img)))
				if e.Tries >= 3 || err != nil { // il server non l'ha accettata (o il file manca): si rinuncia, senza bloccare gli altri messaggi
					chatLog[i].Sent, chatLog[i].Failed = true, true
					chatSaveLocked()
					continue
				}
				chatLog[i].Tries++
				m["img"], m["kind"] = base64.StdEncoding.EncodeToString(b), e.Kind
			}
			if e.Ticket {
				m["ticket"] = "1"
				m["title"] = e.Title
			}
			out = append(out, m)
		}
	}
	return map[string]any{
		"ack": chatAck, "read": chatRead, "out": out,
		"open": time.Since(trayOpen) < 20*time.Second,
		"tray": time.Since(trayLast) < 60*time.Second,
	}
}

// chatHandle: applica la risposta del server (nuovi messaggi dell'operatore, conferme dei messaggi inviati).
func chatHandle(r *chatResp) {
	chatMu.Lock()
	defer chatMu.Unlock()
	hbOK = time.Now()
	if r == nil {
		return
	}
	chatLoad()
	changed := false
	for _, m := range r.Msgs {
		if m.ID <= chatAck {
			continue
		}
		img := ""
		if m.Img != "" && chatImgName.MatchString(m.Img) {
			img = m.Img // scaricata subito dopo (chatFetchImgs); il nome è privo di percorsi
		}
		chatLog = append(chatLog, chatEntry{Dir: "op", Author: m.Author, Text: m.Text, TS: m.TS, SrvID: m.ID, Img: img, Kind: m.Kind})
		chatAck = m.ID
		changed = true
	}
	for _, cid := range r.Ok {
		for i := range chatLog {
			if chatLog[i].CID == cid && !chatLog[i].Sent {
				chatLog[i].Sent = true
				changed = true
			}
		}
	}
	if changed {
		chatSaveLocked()
	}
}

var chatFetching atomic.Bool

// chatFetchImgs: scarica dal server le immagini inviate dall'assistenza e non ancora presenti sul disco (fuori dal lock).
func chatFetchImgs(serverURL, key string) {
	if !chatFetching.CompareAndSwap(false, true) {
		return
	}
	defer chatFetching.Store(false)
	chatMu.Lock()
	chatLoad()
	var todo []string
	for _, e := range chatLog {
		if e.Dir == "op" && e.Img != "" && !chatImgExists(e.Img) {
			todo = append(todo, e.Img)
		}
	}
	chatMu.Unlock()
	for _, n := range todo {
		req, err := http.NewRequest(http.MethodGet, serverURL+"?action=chat_img_dev&n="+n, nil)
		if err != nil {
			continue
		}
		req.Header.Set("X-Device-Key", key)
		resp, err := httpClient.Do(req)
		if err != nil {
			continue
		}
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 6<<20))
		resp.Body.Close()
		if resp.StatusCode == http.StatusOK && chatImgType(b) != "" && os.MkdirAll(chatImgDir(), 0o700) == nil {
			_ = os.WriteFile(filepath.Join(chatImgDir(), n), b, 0o600)
		}
	}
	chatImgClean()
}

func chatImgExists(n string) bool {
	_, err := os.Stat(filepath.Join(chatImgDir(), filepath.Base(n)))
	return err == nil
}

func chatKick() {
	select {
	case chatWake <- struct{}{}:
	default:
	}
}

// ---- API locale per la tray ---------------------------------------------------

func chatHandler(cfg *Config) http.Handler {
	mux := http.NewServeMux()
	guard := func(h http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			host, _, _ := net.SplitHostPort(r.Host)
			if (host != "127.0.0.1" && host != "localhost") || r.Header.Get("X-Myrmm-Tray") != "1" {
				http.Error(w, "forbidden", http.StatusForbidden) // blocca anche pagine web che tentano il DNS rebinding
				return
			}
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Header().Set("Cache-Control", "no-store")
			h(w, r)
		}
	}
	mux.HandleFunc("/state", guard(func(w http.ResponseWriter, r *http.Request) {
		chatMu.Lock()
		chatLoad()
		trayLast = time.Now()
		if r.URL.Query().Get("open") == "1" {
			trayOpen = time.Now()
			if n, _ := strconv.Atoi(r.URL.Query().Get("seen")); n > chatRead {
				chatRead = n
				chatSaveLocked()
			}
		}
		log := make([]map[string]any, 0, len(chatLog))
		for _, e := range chatLog {
			m := map[string]any{"dir": e.Dir, "author": e.Author, "text": e.Text, "ts": e.TS, "srv_id": e.SrvID, "cid": e.CID, "sent": e.Sent, "ticket": e.Ticket, "kind": e.Kind, "failed": e.Failed}
			if e.Img != "" {
				m["img"], m["ready"] = e.Img, chatImgExists(e.Img)
			}
			log = append(log, m)
		}
		rd, online, host, site := chatRead, time.Since(hbOK) < 3*time.Minute, chatMeta.Host, chatMeta.Site
		chatMu.Unlock()
		if r.URL.Query().Get("open") == "1" {
			trayFast.Store(time.Now().Add(30 * time.Second).UnixNano()) // finestra aperta: collegamento rapido
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"host": host, "site": site, "version": AgentVersion,
			"online": online, "read": rd, "log": log,
		})
	}))
	mux.HandleFunc("/img", guard(func(w http.ResponseWriter, r *http.Request) {
		n := r.URL.Query().Get("n")
		known := false
		chatMu.Lock()
		chatLoad()
		for _, e := range chatLog {
			if n != "" && e.Img == n {
				known = true
			}
		}
		chatMu.Unlock()
		var b []byte
		if known && chatImgName.MatchString(n) {
			b, _ = os.ReadFile(filepath.Join(chatImgDir(), filepath.Base(n)))
		}
		ext := chatImgType(b)
		if ext == "" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", map[string]string{"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}[ext])
		_, _ = w.Write(b)
	}))
	mux.HandleFunc("/send", guard(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST", http.StatusMethodNotAllowed)
			return
		}
		var in struct {
			Text   string
			Ticket bool
			Title  string
			Img    string // immagine in base64 (screenshot o file scelto, già ridotta dalla tray)
			Kind   string
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 24<<20)).Decode(&in) != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		t := strings.TrimSpace(in.Text)
		if len([]rune(t)) > 2000 {
			t = string([]rune(t)[:2000])
		}
		img, kind := "", ""
		if in.Img != "" {
			raw, err := base64.StdEncoding.DecodeString(in.Img)
			if err != nil || len(raw) > chatImgRawMax {
				http.Error(w, "image too large", http.StatusRequestEntityTooLarge)
				return
			}
			if chatImgType(raw) == "" { // il tipo si controlla prima di decodificare
				http.Error(w, "bad image", http.StatusBadRequest)
				return
			}
			jb, okn := chatImgNormalize(raw)
			if !okn {
				http.Error(w, "image too large", http.StatusRequestEntityTooLarge)
				return
			}
			raw = jb
			name, ok := chatImgStore(raw)
			if !ok {
				http.Error(w, "bad image", http.StatusBadRequest)
				return
			}
			img, kind = name, "file"
			if in.Kind == "shot" {
				kind = "shot"
			}
		}
		if t == "" && img == "" {
			http.Error(w, "empty", http.StatusBadRequest)
			return
		}
		chatMu.Lock()
		chatLoad()
		title := strings.TrimSpace(in.Title)
		if len([]rune(title)) > 140 {
			title = string([]rune(title)[:140])
		}
		chatLog = append(chatLog, chatEntry{Dir: "user", Text: t, TS: time.Now().UTC().Format(time.RFC3339), CID: fmt.Sprintf("%d-%d", time.Now().UnixNano(), len(chatLog)), Ticket: in.Ticket, Title: title, Img: img, Kind: kind})
		chatSaveLocked()
		chatMu.Unlock()
		trayFast.Store(time.Now().Add(30 * time.Second).UnixNano())
		chatKick()
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	return mux
}

// chatServe avvia l'API locale su una porta di loopback e ne scrive il numero in tray.json (leggibile dagli utenti).
func chatServe(cfg *Config) {
	port := cfg.TrayPort
	if port == 0 {
		port = 47653
	}
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		if ln, err = net.Listen("tcp", "127.0.0.1:0"); err != nil {
			return
		}
	}
	port = ln.Addr().(*net.TCPAddr).Port
	b, _ := json.Marshal(map[string]any{"port": port})
	_ = os.WriteFile(filepath.Join(dataDir(), "tray.json"), b, 0o644)
	go chatImgClean()
	go func() { _ = (&http.Server{Handler: chatHandler(cfg), ReadHeaderTimeout: 5 * time.Second}).Serve(ln) }()
}
