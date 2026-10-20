package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// PNG 1x1
var tinyPNG, _ = base64.StdEncoding.DecodeString("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

func chatTestReset(t *testing.T) {
	t.Helper()
	d := t.TempDir()
	t.Setenv("MYRMM_DIR", d)
	chatMu.Lock()
	chatLog, chatLoaded, chatAck, chatRead = nil, true, 0, 0
	chatMu.Unlock()
}

func TestChatImgType(t *testing.T) {
	for name, c := range map[string]struct {
		b    []byte
		want string
	}{
		"png":   {tinyPNG, "png"},
		"jpeg":  {[]byte("\xff\xd8\xff\xe0abc"), "jpg"},
		"gif":   {[]byte("GIF89a...."), "gif"},
		"webp":  {[]byte("RIFF\x00\x00\x00\x00WEBPVP8 "), "webp"},
		"exe":   {[]byte("MZ\x90\x00"), ""},
		"html":  {[]byte("<html><script>alert(1)</script>"), ""},
		"svg":   {[]byte("<svg xmlns='http://www.w3.org/2000/svg'/>"), ""},
		"vuoto": {nil, ""},
	} {
		if got := chatImgType(c.b); got != c.want {
			t.Errorf("%s: %q, atteso %q", name, got, c.want)
		}
	}
}

func TestChatImgStoreLimits(t *testing.T) {
	chatTestReset(t)
	if _, ok := chatImgStore([]byte("non e' un'immagine")); ok {
		t.Fatal("un file qualsiasi non deve essere salvato")
	}
	big := append(append([]byte{}, tinyPNG...), bytes.Repeat([]byte{0}, chatImgMax)...)
	if _, ok := chatImgStore(big); ok {
		t.Fatal("oltre il limite non deve essere salvata")
	}
	n, ok := chatImgStore(tinyPNG)
	if !ok || !chatImgName.MatchString(n) || !strings.HasSuffix(n, ".png") {
		t.Fatalf("salvataggio: %q %v", n, ok)
	}
	fi, err := os.Stat(filepath.Join(chatImgDir(), n))
	if err != nil || fi.Size() != int64(len(tinyPNG)) {
		t.Fatalf("file non scritto: %v", err)
	}
}

func TestChatImgNameRejectsPaths(t *testing.T) {
	for _, bad := range []string{"../etc/passwd", "a/b.png", `..\x.png`, "x.exe", "", "a b.png", strings.Repeat("a", 90) + ".png"} {
		if chatImgName.MatchString(bad) {
			t.Errorf("nome accettato per errore: %q", bad)
		}
	}
	if !chatImgName.MatchString("0123abcd.png") {
		t.Error("nome valido rifiutato")
	}
}

func chatReq(t *testing.T, h http.Handler, method, path string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var rd *bytes.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	} else {
		rd = bytes.NewReader(nil)
	}
	r := httptest.NewRequest(method, "http://127.0.0.1:47653"+path, rd)
	r.Header.Set("X-Myrmm-Tray", "1")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func TestChatSendImageAndServe(t *testing.T) {
	chatTestReset(t)
	h := chatHandler(&Config{})
	b64 := base64.StdEncoding.EncodeToString(tinyPNG)
	if w := chatReq(t, h, "POST", "/send", map[string]any{"text": "", "img": b64, "kind": "shot"}); w.Code != 200 {
		t.Fatalf("send immagine: %d %s", w.Code, w.Body.String())
	}
	if w := chatReq(t, h, "POST", "/send", map[string]any{"img": base64.StdEncoding.EncodeToString([]byte("<html>"))}); w.Code != http.StatusBadRequest {
		t.Fatalf("contenuto non immagine: atteso 400, %d", w.Code)
	}
	if w := chatReq(t, h, "POST", "/send", map[string]any{"text": " "}); w.Code != http.StatusBadRequest {
		t.Fatalf("messaggio vuoto: atteso 400, %d", w.Code)
	}
	big := base64.StdEncoding.EncodeToString(append(append([]byte{}, tinyPNG...), bytes.Repeat([]byte{1}, chatImgMax)...))
	if w := chatReq(t, h, "POST", "/send", map[string]any{"img": big}); w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("troppo grande: atteso 413, %d", w.Code)
	}
	chatMu.Lock()
	if len(chatLog) != 1 || chatLog[0].Img == "" || chatLog[0].Kind != "shot" {
		chatMu.Unlock()
		t.Fatalf("log inatteso: %+v", chatLog)
	}
	name := chatLog[0].Img
	chatMu.Unlock()
	// /state espone img e ready
	w := chatReq(t, h, "GET", "/state", nil)
	var st struct{ Log []map[string]any }
	_ = json.Unmarshal(w.Body.Bytes(), &st)
	if len(st.Log) != 1 || st.Log[0]["img"] != name || st.Log[0]["ready"] != true {
		t.Fatalf("state: %s", w.Body.String())
	}
	// /img serve solo immagini citate dalla conversazione
	if w := chatReq(t, h, "GET", "/img?n="+name, nil); w.Code != 200 || w.Header().Get("Content-Type") != "image/png" || !bytes.Equal(w.Body.Bytes(), tinyPNG) {
		t.Fatalf("img: %d %s", w.Code, w.Header().Get("Content-Type"))
	}
	_ = os.WriteFile(filepath.Join(chatImgDir(), "estraneo.png"), tinyPNG, 0o600)
	for _, bad := range []string{"estraneo.png", "../chat.json", "..%2Fchat.json", ""} {
		if w := chatReq(t, h, "GET", "/img?n="+bad, nil); w.Code != http.StatusNotFound {
			t.Errorf("img %q: atteso 404, %d", bad, w.Code)
		}
	}
	// senza intestazione della tray (pagina web ostile): rifiutato
	r := httptest.NewRequest("GET", "http://127.0.0.1:47653/img?n="+name, nil)
	ww := httptest.NewRecorder()
	h.ServeHTTP(ww, r)
	if ww.Code != http.StatusForbidden {
		t.Errorf("senza X-Myrmm-Tray: atteso 403, %d", ww.Code)
	}
}

func TestChatPrepareCarriesImageAndGivesUp(t *testing.T) {
	chatTestReset(t)
	n, _ := chatImgStore(tinyPNG)
	chatMu.Lock()
	chatLog = []chatEntry{{Dir: "user", CID: "c1", Img: n, Kind: "shot", TS: time.Now().UTC().Format(time.RFC3339)}}
	chatMu.Unlock()
	for i := 0; i < 3; i++ {
		out := chatPrepare()["out"].([]map[string]string)
		if len(out) != 1 || out[0]["img"] != base64.StdEncoding.EncodeToString(tinyPNG) || out[0]["kind"] != "shot" {
			t.Fatalf("tentativo %d: %+v", i, out)
		}
	}
	// dopo 3 invii senza conferma si rinuncia: un corpo rifiutato dal server non deve bloccare per sempre gli heartbeat
	if out := chatPrepare()["out"].([]map[string]string); len(out) != 0 {
		t.Fatalf("doveva rinunciare: %+v", out)
	}
	chatMu.Lock()
	defer chatMu.Unlock()
	if !chatLog[0].Failed || !chatLog[0].Sent {
		t.Fatalf("da segnare come non inviata: %+v", chatLog[0])
	}
}

func TestChatHandleOpImageNameValidated(t *testing.T) {
	chatTestReset(t)
	r := &chatResp{}
	r.Msgs = append(r.Msgs, struct {
		ID     int    `json:"id"`
		Author string `json:"author"`
		Text   string `json:"text"`
		TS     string `json:"ts"`
		Img    string `json:"img"`
		Kind   string `json:"kind"`
	}{1, "Op", "ciao", "2026-01-01T00:00:00Z", "ci0123456789abcdef.png", ""}, struct {
		ID     int    `json:"id"`
		Author string `json:"author"`
		Text   string `json:"text"`
		TS     string `json:"ts"`
		Img    string `json:"img"`
		Kind   string `json:"kind"`
	}{2, "Op", "x", "2026-01-01T00:00:00Z", "../../evil", ""})
	chatHandle(r)
	chatMu.Lock()
	defer chatMu.Unlock()
	if len(chatLog) != 2 || chatLog[0].Img != "ci0123456789abcdef.png" || chatLog[1].Img != "" {
		t.Fatalf("log: %+v", chatLog)
	}
}

func TestChatImgCleanRemovesOrphansAndOld(t *testing.T) {
	chatTestReset(t)
	keep, _ := chatImgStore(tinyPNG)
	orph, _ := chatImgStore(tinyPNG)
	old := time.Now().Add(-3 * time.Minute)
	for _, n := range []string{keep, orph} {
		_ = os.Chtimes(filepath.Join(chatImgDir(), n), old, old)
	}
	chatMu.Lock()
	chatLog = []chatEntry{{Dir: "user", CID: "k", Img: keep, TS: time.Now().UTC().Format(time.RFC3339)}}
	chatMu.Unlock()
	chatImgClean()
	if !chatImgExists(keep) || chatImgExists(orph) {
		t.Fatalf("keep=%v orph=%v", chatImgExists(keep), chatImgExists(orph))
	}
	// più vecchia di 30 giorni: il file sparisce e la riga perde il riferimento
	chatMu.Lock()
	chatLog[0].TS = time.Now().Add(-31 * 24 * time.Hour).UTC().Format(time.RFC3339)
	chatMu.Unlock()
	chatImgClean()
	chatMu.Lock()
	defer chatMu.Unlock()
	if chatImgExists(keep) || chatLog[0].Img != "" {
		t.Fatalf("doveva essere eliminata: %+v", chatLog[0])
	}
}
