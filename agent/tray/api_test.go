package tray

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBaseFromDir(t *testing.T) {
	d := t.TempDir()
	if _, err := baseFromDir(d); err == nil {
		t.Fatal("senza tray.json deve fallire")
	}
	_ = os.WriteFile(filepath.Join(d, "tray.json"), []byte(`{"port":47653}`), 0o644)
	if b, err := baseFromDir(d); err != nil || b != "http://127.0.0.1:47653" {
		t.Fatalf("%q %v", b, err)
	}
	_ = os.WriteFile(filepath.Join(d, "tray.json"), []byte(`{"port":99999}`), 0o644)
	if _, err := baseFromDir(d); err == nil {
		t.Fatal("porta fuori intervallo accettata")
	}
}

func TestClientStateAndSend(t *testing.T) {
	var gotHdr, gotBody string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotHdr = r.Header.Get("X-Myrmm-Tray")
		switch r.URL.Path {
		case "/state":
			_ = json.NewEncoder(w).Encode(map[string]any{"host": "PC1", "version": "1.64", "online": true, "read": 1, "log": []map[string]any{{"dir": "op", "author": "Anna", "text": "ciao", "ts": "2026-10-20T10:00:00Z", "srv_id": 2}}})
		case "/send":
			b, _ := io.ReadAll(r.Body)
			gotBody = string(b)
			_, _ = w.Write([]byte(`{"ok":true}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	c := newClient(srv.URL)
	s, err := c.state(true, 0)
	if err != nil || s.Host != "PC1" || len(s.Log) != 1 || gotHdr != "1" {
		t.Fatalf("state: %+v %v hdr=%q", s, err, gotHdr)
	}
	if err := c.send(sendReq{Text: "aiuto", Ticket: true, Title: "Stampante"}); err != nil || !strings.Contains(gotBody, `"ticket":true`) || !strings.Contains(gotBody, `"title":"Stampante"`) {
		t.Fatalf("send: %v %s", err, gotBody)
	}
	if _, err := c.image("x.png"); err == nil {
		t.Fatal("404 deve essere un errore")
	}
}

func TestRenderSegments(t *testing.T) {
	if r := renderSegments(nil); len(r) != 1 || !strings.Contains(r[0].Text, "Scrivi qui") {
		t.Fatalf("vuota: %+v", r)
	}
	log := []logEntry{
		{Dir: "op", Author: "Anna", Text: "buongiorno", TS: "2026-10-20T10:00:00Z", SrvID: 3},
		{Dir: "user", Text: "salve", TS: "2026-10-20T10:01:00Z"},
		{Dir: "user", Img: "a.jpg", TS: "2026-10-20T10:02:00Z", Sent: true},
		{Dir: "op", Img: "b.jpg", Ready: false, TS: "2026-10-20T10:03:00Z", SrvID: 4},
		{Dir: "user", Img: "c.jpg", Failed: true, TS: "2026-10-20T10:04:00Z"},
	}
	all := ""
	for _, s := range renderSegments(log) {
		all += s.Text
	}
	for _, want := range []string{"Anna", "buongiorno", "Tu", "(invio...)", "[immagine]", "(immagine in arrivo...)", "(immagine non inviata)"} {
		if !strings.Contains(all, want) {
			t.Errorf("manca %q in %q", want, all)
		}
	}
}

func TestSignatureAndNewest(t *testing.T) {
	a := []logEntry{{Dir: "op", Text: "x", SrvID: 5}}
	b := []logEntry{{Dir: "op", Text: "x", SrvID: 5, Ready: true, Img: "i"}}
	if signature(a) == signature(b) {
		t.Fatal("la firma deve cambiare quando l'immagine diventa pronta")
	}
	s := &state{Read: 3, Log: []logEntry{{Dir: "op", SrvID: 2}, {Dir: "op", SrvID: 5}, {Dir: "user"}}}
	if e, ok := newestOp(s, 0); !ok || e.SrvID != 5 {
		t.Fatalf("newest: %+v %v", e, ok)
	}
	if _, ok := newestOp(s, 5); ok {
		t.Fatal("già notificato")
	}
	if maxOpID(s.Log) != 5 {
		t.Fatal("maxOpID")
	}
}
