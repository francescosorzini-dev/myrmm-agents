package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
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
}

type chatResp struct {
	Msgs []struct {
		ID     int    `json:"id"`
		Author string `json:"author"`
		Text   string `json:"text"`
		TS     string `json:"ts"`
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
	for _, e := range chatLog {
		if e.Dir == "user" && !e.Sent && e.CID != "" {
			m := map[string]string{"cid": e.CID, "text": e.Text}
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
		chatLog = append(chatLog, chatEntry{Dir: "op", Author: m.Author, Text: m.Text, TS: m.TS, SrvID: m.ID})
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
		log := append([]chatEntry{}, chatLog...)
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
	mux.HandleFunc("/send", guard(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST", http.StatusMethodNotAllowed)
			return
		}
		var in struct {
			Text   string
			Ticket bool
			Title  string
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&in) != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		t := strings.TrimSpace(in.Text)
		if t == "" {
			http.Error(w, "empty", http.StatusBadRequest)
			return
		}
		if len([]rune(t)) > 2000 {
			t = string([]rune(t)[:2000])
		}
		chatMu.Lock()
		chatLoad()
		title := strings.TrimSpace(in.Title)
		if len([]rune(title)) > 140 {
			title = string([]rune(title)[:140])
		}
		chatLog = append(chatLog, chatEntry{Dir: "user", Text: t, TS: time.Now().UTC().Format(time.RFC3339), CID: fmt.Sprintf("%d-%d", time.Now().UnixNano(), len(chatLog)), Ticket: in.Ticket, Title: title})
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
	go func() { _ = (&http.Server{Handler: chatHandler(cfg), ReadHeaderTimeout: 5 * time.Second}).Serve(ln) }()
}
