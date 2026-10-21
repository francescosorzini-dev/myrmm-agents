package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
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
	"sort"
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
	keep := map[string]bool{}
	for _, se := range chatSessions {
		for i := range se.log {
			if se.log[i].Img == "" {
				continue
			}
			if t, err := time.Parse(time.RFC3339, se.log[i].TS); err == nil && time.Since(t) > chatImgKeep {
				se.log[i].Img = ""
				continue
			}
			keep[se.log[i].Img] = true
		}
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

type chatMsg struct {
	ID     int    `json:"id"`
	Author string `json:"author"`
	Text   string `json:"text"`
	TS     string `json:"ts"`
	Img    string `json:"img"`
	Kind   string `json:"kind"`
}

// chatResp: risposta del server alla sezione «chat» dell'heartbeat. Dalla 1.67.0 ogni utente collegato ha la sua conversazione:
// Sessions è indicizzata per nome utente. Msgs/Ok al livello superiore valgono solo per un server precedente (una sola conversazione).
type chatResp struct {
	Msgs     []chatMsg            `json:"msgs"`
	Ok       []string             `json:"ok"`
	Sessions map[string]*chatResp `json:"sessions,omitempty"`
}

// chatDisabled: la console (o il configuratore locale) ha disattivato l'icona: /state lo dice alle tray, che escono.
var chatDisabled atomic.Bool

var trayFast atomic.Int64 // fine (UnixNano) del collegamento rapido richiesto dalla tray

// chatSess: la conversazione di un utente (una sessione Windows). Ogni utente ha il suo file chat-<hash>.json; chat.json è il
// file della versione precedente, adottato dal primo utente che si collega.
type chatSess struct {
	user       string
	ack, read  int // ultimo messaggio dell'operatore ricevuto / visto dall'utente
	log        []chatEntry
	loaded     bool
	last, open time.Time // ultima richiesta della tray / ultima volta che la finestra era aperta
}

var (
	chatMu       sync.Mutex
	chatSessions = map[string]*chatSess{}
	chatWake     = make(chan struct{}, 1)
	hbOK         time.Time // ultimo heartbeat riuscito
	chatMeta     struct{ Host, Site string }
	chatServer   struct{ URL, Key string } // per scaricare su richiesta le immagini dell'assistenza
	chatImgErr   = map[string]string{}     // nome immagine -> ultimo errore di scaricamento
	// chatResolve: da chiave della tray a utente. Windows la sostituisce con la verifica della chiave di sessione; altrove (e nei test) vale «1».
	chatResolve = func(key string) (string, bool) { return "", key == "1" }
)

func sessKey(u string) string { return strings.ToLower(strings.TrimSpace(u)) }

func chatSessFile(u string) string {
	if sessKey(u) == "" {
		return filepath.Join(dataDir(), "chat.json")
	}
	sum := sha256.Sum256([]byte(sessKey(u)))
	return filepath.Join(dataDir(), "chat-"+hex.EncodeToString(sum[:6])+".json")
}

// chatSession restituisce (creandola e caricandola) la conversazione di un utente. Chiamare con chatMu preso.
func chatSession(u string) *chatSess {
	k := sessKey(u)
	if s := chatSessions[k]; s != nil {
		return s
	}
	s := &chatSess{user: strings.TrimSpace(u)}
	chatSessions[k] = s
	f := chatSessFile(u)
	b, err := os.ReadFile(f)
	if err != nil && k != "" { // prima volta per questo utente: adotta la conversazione unica della versione precedente
		legacy := chatSessFile("")
		if lb, e := os.ReadFile(legacy); e == nil {
			b, err = lb, nil
			_ = os.Rename(legacy, legacy+".old")
		}
	}
	if err == nil {
		var fl struct {
			Ack, Read int
			Log       []chatEntry
		}
		if json.Unmarshal(b, &fl) == nil {
			s.ack, s.read, s.log = fl.Ack, fl.Read, fl.Log
		}
	}
	s.loaded = true
	return s
}

func (s *chatSess) saveLocked() {
	if len(s.log) > 200 {
		s.log = s.log[len(s.log)-200:]
	}
	b, _ := json.Marshal(map[string]any{"User": s.user, "Ack": s.ack, "Read": s.read, "Log": s.log})
	f := chatSessFile(s.user)
	_ = os.WriteFile(f+".tmp", b, 0o600)
	_ = os.Rename(f+".tmp", f)
}

// chatLoadAll: all'avvio rilegge le conversazioni salvate, così i messaggi non ancora inviati partono anche se l'utente non è più collegato.
func chatLoadAll() {
	ents, _ := os.ReadDir(dataDir())
	chatMu.Lock()
	defer chatMu.Unlock()
	for _, e := range ents {
		n := e.Name()
		if !strings.HasPrefix(n, "chat-") || !strings.HasSuffix(n, ".json") {
			continue
		}
		if b, err := os.ReadFile(filepath.Join(dataDir(), n)); err == nil {
			var fl struct{ User string }
			if json.Unmarshal(b, &fl) == nil && fl.User != "" {
				chatSession(fl.User)
			}
		}
	}
}

func chatSessionsSorted() []*chatSess {
	out := make([]*chatSess, 0, len(chatSessions))
	for _, s := range chatSessions {
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return sessKey(out[i].user) < sessKey(out[j].user) })
	return out
}

// chatPrepare: campo "chat" da allegare al heartbeat. «sessions» ha una voce per utente; con una sola conversazione si ripetono anche
// ack/read/out al livello superiore, per un server precedente.
func chatPrepare() map[string]any {
	chatMu.Lock()
	defer chatMu.Unlock()
	list := []map[string]any{}
	users := []string{}
	anyTray, anyOpen := false, false
	var one map[string]any
	for _, s := range chatSessionsSorted() {
		out := []map[string]string{}
		for i := range s.log {
			e := s.log[i]
			if e.Dir == "user" && !e.Sent && e.CID != "" {
				m := map[string]string{"cid": e.CID, "text": e.Text}
				if e.Img != "" {
					b, err := os.ReadFile(filepath.Join(chatImgDir(), filepath.Base(e.Img)))
					if e.Tries >= 3 || err != nil { // il server non l'ha accettata (o il file manca): si rinuncia, senza bloccare gli altri messaggi
						s.log[i].Sent, s.log[i].Failed = true, true
						s.saveLocked()
						continue
					}
					s.log[i].Tries++
					m["img"], m["kind"] = base64.StdEncoding.EncodeToString(b), e.Kind
				}
				if e.Ticket {
					m["ticket"] = "1"
					m["title"] = e.Title
				}
				out = append(out, m)
			}
		}
		open := time.Since(s.open) < 20*time.Second
		tray := time.Since(s.last) < 60*time.Second
		anyTray, anyOpen = anyTray || tray, anyOpen || open
		if tray && s.user != "" {
			users = append(users, s.user)
		}
		it := map[string]any{"user": s.user, "ack": s.ack, "read": s.read, "out": out, "open": open}
		list = append(list, it)
		one = it
	}
	res := map[string]any{"sessions": list, "open": anyOpen, "tray": anyTray, "users": users}
	if len(list) <= 1 {
		if one == nil {
			one = map[string]any{"ack": 0, "read": 0, "out": []map[string]string{}}
		}
		res["ack"], res["read"], res["out"] = one["ack"], one["read"], one["out"]
	}
	return res
}

// chatApply applica a una conversazione la parte di risposta che la riguarda. Chiamare con chatMu preso.
func chatApply(s *chatSess, r *chatResp) {
	changed := false
	for _, m := range r.Msgs {
		if m.ID <= s.ack {
			continue
		}
		img := ""
		if m.Img != "" && chatImgName.MatchString(m.Img) {
			img = m.Img // scaricata subito dopo (chatFetchImgs) o alla prima richiesta della tray; il nome è privo di percorsi
		}
		s.log = append(s.log, chatEntry{Dir: "op", Author: m.Author, Text: m.Text, TS: m.TS, SrvID: m.ID, Img: img, Kind: m.Kind})
		s.ack = m.ID
		changed = true
	}
	for _, cid := range r.Ok {
		for i := range s.log {
			if s.log[i].CID == cid && !s.log[i].Sent {
				s.log[i].Sent = true
				changed = true
			}
		}
	}
	if changed {
		s.saveLocked()
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
	if len(r.Sessions) > 0 {
		for u, rr := range r.Sessions {
			if rr != nil {
				chatApply(chatSession(u), rr)
			}
		}
		return
	}
	if len(chatSessions) == 1 { // server precedente: una sola conversazione
		for _, s := range chatSessions {
			chatApply(s, r)
		}
	} else if len(chatSessions) == 0 && (len(r.Msgs) > 0 || len(r.Ok) > 0) {
		chatApply(chatSession(""), r)
	}
}

var chatFetching atomic.Bool

// chatFetchOne scarica dal server un'immagine dell'assistenza; registra il motivo dell'eventuale errore (lo vede la tray).
func chatFetchOne(serverURL, key, n string) error {
	if serverURL == "" || !chatImgName.MatchString(n) {
		return fmt.Errorf("immagine non scaricabile")
	}
	req, err := http.NewRequest(http.MethodGet, serverURL+"?action=chat_img_dev&n="+n, nil)
	if err != nil {
		return err
	}
	req.Header.Set("X-Device-Key", key)
	resp, err := httpClient.Do(req)
	if err != nil {
		chatNoteImgErr(n, "rete: "+err.Error())
		return err
	}
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 6<<20))
	resp.Body.Close()
	switch {
	case resp.StatusCode != http.StatusOK:
		e := fmt.Errorf("il server risponde HTTP %d", resp.StatusCode)
		chatNoteImgErr(n, e.Error())
		return e
	case chatImgType(b) == "":
		e := fmt.Errorf("il server non ha restituito un'immagine (%d byte)", len(b))
		chatNoteImgErr(n, e.Error())
		return e
	}
	if err := os.MkdirAll(chatImgDir(), 0o700); err != nil {
		chatNoteImgErr(n, err.Error())
		return err
	}
	if err := os.WriteFile(filepath.Join(chatImgDir(), n), b, 0o600); err != nil {
		chatNoteImgErr(n, "scrittura: "+err.Error())
		return err
	}
	chatMu.Lock()
	delete(chatImgErr, n)
	chatMu.Unlock()
	return nil
}

func chatNoteImgErr(n, msg string) {
	chatMu.Lock()
	chatImgErr[n] = msg
	chatMu.Unlock()
}

// chatFetchImgs: scarica le immagini dell'assistenza non ancora sul disco (fuori dal lock). Serve anche a mandarle in anticipo: se manca
// qualcosa la tray la chiede comunque all'agent, che la scarica in quel momento.
func chatFetchImgs(serverURL, key string) {
	if !chatFetching.CompareAndSwap(false, true) {
		return
	}
	defer chatFetching.Store(false)
	chatMu.Lock()
	chatServer.URL, chatServer.Key = serverURL, key
	var todo []string
	for _, s := range chatSessions {
		for _, e := range s.log {
			if e.Dir == "op" && e.Img != "" && !chatImgExists(e.Img) {
				todo = append(todo, e.Img)
			}
		}
	}
	chatMu.Unlock()
	for _, n := range todo {
		_ = chatFetchOne(serverURL, key, n)
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
	guard := func(h func(w http.ResponseWriter, r *http.Request, user string)) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			host, _, _ := net.SplitHostPort(r.Host)
			key := r.Header.Get("X-Myrmm-Tray")
			if host != "127.0.0.1" && host != "localhost" || key == "" {
				http.Error(w, "forbidden", http.StatusForbidden) // blocca anche pagine web che tentano il DNS rebinding
				return
			}
			user, ok := chatResolve(key)
			if !ok {
				http.Error(w, "forbidden", http.StatusForbidden) // chiave di sessione sconosciuta
				return
			}
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Header().Set("Cache-Control", "no-store")
			h(w, r, user)
		}
	}
	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) { // senza chiave: solo per la diagnosi dell'agent, nessun dato delle conversazioni
		host, _, _ := net.SplitHostPort(r.Host)
		if host != "127.0.0.1" && host != "localhost" {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		chatMu.Lock()
		n, online := len(chatSessions), time.Since(hbOK) < 3*time.Minute
		chatMu.Unlock()
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(map[string]any{"version": AgentVersion, "online": online, "users": n})
	})
	mux.HandleFunc("/state", guard(func(w http.ResponseWriter, r *http.Request, user string) {
		if chatDisabled.Load() {
			_, _ = w.Write([]byte(`{"disabled":true,"version":"` + AgentVersion + `"}`))
			return
		}
		chatMu.Lock()
		s := chatSession(user)
		s.last = time.Now()
		if r.URL.Query().Get("open") == "1" {
			s.open = time.Now()
			if n, _ := strconv.Atoi(r.URL.Query().Get("seen")); n > s.read {
				s.read = n
				s.saveLocked()
			}
		}
		log := make([]map[string]any, 0, len(s.log))
		for _, e := range s.log {
			m := map[string]any{"dir": e.Dir, "author": e.Author, "text": e.Text, "ts": e.TS, "srv_id": e.SrvID, "cid": e.CID, "sent": e.Sent, "ticket": e.Ticket, "kind": e.Kind, "failed": e.Failed}
			if e.Img != "" {
				// le immagini dell'assistenza sono sempre «pronte»: se non sono ancora sul disco /img le scarica in quel momento
				m["img"], m["ready"] = e.Img, true
				if er := chatImgErr[e.Img]; er != "" {
					m["img_err"] = er
				}
			}
			log = append(log, m)
		}
		rd, online, host, site := s.read, time.Since(hbOK) < 3*time.Minute, chatMeta.Host, chatMeta.Site
		chatMu.Unlock()
		if r.URL.Query().Get("open") == "1" {
			trayFast.Store(time.Now().Add(30 * time.Second).UnixNano()) // finestra aperta: collegamento rapido
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"host": host, "site": site, "version": AgentVersion, "user": user,
			"online": online, "read": rd, "log": log,
		})
	}))
	mux.HandleFunc("/img", guard(func(w http.ResponseWriter, r *http.Request, user string) {
		n := r.URL.Query().Get("n")
		known := false
		chatMu.Lock()
		for _, e := range chatSession(user).log {
			if n != "" && e.Img == n {
				known = true
			}
		}
		url, key := chatServer.URL, chatServer.Key
		chatMu.Unlock()
		if !known || !chatImgName.MatchString(n) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if !chatImgExists(n) { // non ancora scaricata: lo si fa ora e, se non va, si dice perché
			if err := chatFetchOne(url, key, n); err != nil {
				http.Error(w, err.Error(), http.StatusBadGateway)
				return
			}
		}
		b, _ := os.ReadFile(filepath.Join(chatImgDir(), filepath.Base(n)))
		ext := chatImgType(b)
		if ext == "" {
			http.Error(w, "il file non è un'immagine leggibile", http.StatusUnprocessableEntity)
			return
		}
		w.Header().Set("Content-Type", map[string]string{"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}[ext])
		_, _ = w.Write(b)
	}))
	mux.HandleFunc("/send", guard(func(w http.ResponseWriter, r *http.Request, user string) {
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
		s := chatSession(user)
		title := strings.TrimSpace(in.Title)
		if len([]rune(title)) > 140 {
			title = string([]rune(title)[:140])
		}
		s.log = append(s.log, chatEntry{Dir: "user", Text: t, TS: time.Now().UTC().Format(time.RFC3339), CID: fmt.Sprintf("%d-%d", time.Now().UnixNano(), len(s.log)), Ticket: in.Ticket, Title: title, Img: img, Kind: kind})
		s.saveLocked()
		chatMu.Unlock()
		trayFast.Store(time.Now().Add(30 * time.Second).UnixNano())
		chatKick()
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	return mux
}

// chatServe avvia l'API locale su una porta di loopback e ne scrive il numero in tray.json (per la diagnosi: gli utenti non lo leggono,
// la porta la passa il servizio alla tray). Ritorna la porta.
func chatServe(cfg *Config) int {
	chatLoadAll()
	port := cfg.TrayPort
	if port == 0 {
		port = 47653
	}
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		if ln, err = net.Listen("tcp", "127.0.0.1:0"); err != nil {
			return 0
		}
	}
	port = ln.Addr().(*net.TCPAddr).Port
	b, _ := json.Marshal(map[string]any{"port": port})
	_ = os.WriteFile(filepath.Join(dataDir(), "tray.json"), b, 0o644)
	go chatImgClean()
	go func() { _ = (&http.Server{Handler: chatHandler(cfg), ReadHeaderTimeout: 5 * time.Second}).Serve(ln) }()
	return port
}
