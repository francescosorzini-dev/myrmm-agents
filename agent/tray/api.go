package main

// Parte senza interfaccia grafica della tray in Go: dialogo con l'agent locale (127.0.0.1, stesso protocollo della tray
// PowerShell: /state, /send, /img) e preparazione del testo della conversazione. È provata su ogni sistema con i test.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type logEntry struct {
	Dir    string `json:"dir"`
	Author string `json:"author"`
	Text   string `json:"text"`
	TS     string `json:"ts"`
	SrvID  int    `json:"srv_id"`
	CID    string `json:"cid"`
	Sent   bool   `json:"sent"`
	Ticket bool   `json:"ticket"`
	Kind   string `json:"kind"`
	Failed bool   `json:"failed"`
	Img    string `json:"img"`
	Ready  bool   `json:"ready"`
}

type state struct {
	Host    string     `json:"host"`
	Site    string     `json:"site"`
	Version string     `json:"version"`
	Online  bool       `json:"online"`
	Read    int        `json:"read"`
	Log     []logEntry `json:"log"`
}

type client struct {
	base string // http://127.0.0.1:porta
	http *http.Client
}

func newClient(base string) *client {
	return &client{base: base, http: &http.Client{Timeout: 8 * time.Second}}
}

// baseFromDir legge la porta dell'API locale da tray.json (scritto dall'agent).
func baseFromDir(dir string) (string, error) {
	b, err := os.ReadFile(filepath.Join(dir, "tray.json"))
	if err != nil {
		return "", err
	}
	var j struct {
		Port int `json:"port"`
	}
	if json.Unmarshal(b, &j) != nil || j.Port <= 0 || j.Port > 65535 {
		return "", errors.New("tray.json non valido")
	}
	return fmt.Sprintf("http://127.0.0.1:%d", j.Port), nil
}

func (c *client) do(method, path string, body any, timeout time.Duration) ([]byte, error) {
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.base+path, rd)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Myrmm-Tray", "1") // l'agent rifiuta chi non lo porta (pagine web ostile)
	if body != nil {
		req.Header.Set("Content-Type", "application/json; charset=utf-8")
	}
	cl := c.http
	if timeout > 0 {
		cl = &http.Client{Timeout: timeout}
	}
	resp, err := cl.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
	if resp.StatusCode != http.StatusOK {
		return data, fmt.Errorf("agent: HTTP %d", resp.StatusCode)
	}
	return data, nil
}

func (c *client) state(open bool, seen int) (*state, error) {
	o := 0
	if open {
		o = 1
	}
	b, err := c.do("GET", fmt.Sprintf("/state?open=%d&seen=%d", o, seen), nil, 0)
	if err != nil {
		return nil, err
	}
	var s state
	if err := json.Unmarshal(b, &s); err != nil {
		return nil, err
	}
	return &s, nil
}

type sendReq struct {
	Text   string `json:"text"`
	Ticket bool   `json:"ticket,omitempty"`
	Title  string `json:"title,omitempty"`
	Img    string `json:"img,omitempty"`
	Kind   string `json:"kind,omitempty"`
}

func (c *client) send(r sendReq) error {
	_, err := c.do("POST", "/send", r, 60*time.Second)
	return err
}

func (c *client) image(name string) ([]byte, error) {
	return c.do("GET", "/img?n="+name, nil, 15*time.Second)
}

// ---- testo della conversazione ----------------------------------------------------------------

type segment struct {
	Text  string
	Color uint32 // 0xBBGGRR (COLORREF)
	Bold  bool
	Img   string // se non vuoto: al posto del testo va l'anteprima di questa immagine
}

const (
	colMine  = 0x5a5a5a // grigio
	colOp    = 0xeb6325 // blu (RGB 25,63,eb → COLORREF 0xBBGGRR)
	colText  = 0x000000
	colMuted = 0x808080
)

func localWhen(ts string) string {
	t, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		return ""
	}
	return t.Local().Format("02/01 15:04")
}

// renderSegments: la conversazione come testi colorati (intestazione in grassetto + corpo).
func renderSegments(log []logEntry) []segment {
	if len(log) == 0 {
		return []segment{{Text: "Scrivi qui un messaggio per contattare l'assistenza. Per una richiesta formale spunta la casella «Apri una richiesta di assistenza».", Color: colMuted}}
	}
	var out []segment
	for _, e := range log {
		mine := e.Dir == "user"
		who := "Assistenza"
		switch {
		case mine:
			who = "Tu"
		case e.Author != "":
			who = e.Author
		}
		h := who + "  " + localWhen(e.TS)
		if mine && !e.Sent && !e.Failed {
			h += "  (invio...)"
		}
		col := uint32(colOp)
		if mine {
			col = colMine
		}
		out = append(out, segment{Text: h + "\n", Color: col, Bold: true})
		if e.Img != "" {
			switch {
			case e.Failed:
				out = append(out, segment{Text: "(immagine non inviata)\n", Color: colMuted})
			case e.Ready || mine:
				out = append(out, segment{Img: e.Img, Text: "[immagine]"}, segment{Text: "\n"})
			default:
				out = append(out, segment{Text: "(immagine in arrivo...)\n", Color: colMuted})
			}
		}
		if strings.TrimSpace(e.Text) != "" {
			out = append(out, segment{Text: e.Text + "\n", Color: colText})
		}
		out = append(out, segment{Text: "\n", Color: colText})
	}
	return out
}

// signature: cambia solo se cambia qualcosa di visibile (evita di ridisegnare e far saltare lo scorrimento).
func signature(log []logEntry) string {
	var b strings.Builder
	for _, e := range log {
		fmt.Fprintf(&b, "%s|%s|%v|%s|%s|%v|%v\n", e.Dir, e.TS, e.Sent, e.Text, e.Img, e.Ready, e.Failed)
	}
	return b.String()
}

// newestOp: ultimo messaggio dell'assistenza non ancora visto né notificato.
func newestOp(s *state, notified int) (logEntry, bool) {
	var last logEntry
	found := false
	for _, e := range s.Log {
		if e.Dir == "op" && e.SrvID > s.Read && e.SrvID > notified {
			last, found = e, true
		}
	}
	return last, found
}

func maxOpID(log []logEntry) int {
	m := 0
	for _, e := range log {
		if e.Dir == "op" && e.SrvID > m {
			m = e.SrvID
		}
	}
	return m
}
