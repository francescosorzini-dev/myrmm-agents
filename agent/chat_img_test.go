package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"image"
	"image/color"
	"image/png"
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
	chatSessions = map[string]*chatSess{}
	chatImgErr = map[string]string{}
	chatServer.URL, chatServer.Key = "", ""
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
	big := base64.StdEncoding.EncodeToString(append(append([]byte{}, tinyPNG...), bytes.Repeat([]byte{1}, chatImgRawMax)...))
	if w := chatReq(t, h, "POST", "/send", map[string]any{"img": big}); w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("troppo grande: atteso 413, %d", w.Code)
	}
	chatMu.Lock()
	if len(chatSession("").log) != 1 || chatSession("").log[0].Img == "" || chatSession("").log[0].Kind != "shot" || !strings.HasSuffix(chatSession("").log[0].Img, ".jpg") {
		chatMu.Unlock()
		t.Fatalf("log inatteso: %+v", chatSession("").log)
	}
	name := chatSession("").log[0].Img
	chatMu.Unlock()
	// /state espone img e ready
	w := chatReq(t, h, "GET", "/state", nil)
	var st struct{ Log []map[string]any }
	_ = json.Unmarshal(w.Body.Bytes(), &st)
	if len(st.Log) != 1 || st.Log[0]["img"] != name || st.Log[0]["ready"] != true {
		t.Fatalf("state: %s", w.Body.String())
	}
	// /img serve solo immagini citate dalla conversazione
	if w := chatReq(t, h, "GET", "/img?n="+name, nil); w.Code != 200 || w.Header().Get("Content-Type") != "image/jpeg" || chatImgType(w.Body.Bytes()) != "jpg" {
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
	chatSession("").log = []chatEntry{{Dir: "user", CID: "c1", Img: n, Kind: "shot", TS: time.Now().UTC().Format(time.RFC3339)}}
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
	if !chatSession("").log[0].Failed || !chatSession("").log[0].Sent {
		t.Fatalf("da segnare come non inviata: %+v", chatSession("").log[0])
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
	if len(chatSession("").log) != 2 || chatSession("").log[0].Img != "ci0123456789abcdef.png" || chatSession("").log[1].Img != "" {
		t.Fatalf("log: %+v", chatSession("").log)
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
	chatSession("").log = []chatEntry{{Dir: "user", CID: "k", Img: keep, TS: time.Now().UTC().Format(time.RFC3339)}}
	chatMu.Unlock()
	chatImgClean()
	if !chatImgExists(keep) || chatImgExists(orph) {
		t.Fatalf("keep=%v orph=%v", chatImgExists(keep), chatImgExists(orph))
	}
	// più vecchia di 30 giorni: il file sparisce e la riga perde il riferimento
	chatMu.Lock()
	chatSession("").log[0].TS = time.Now().Add(-31 * 24 * time.Hour).UTC().Format(time.RFC3339)
	chatMu.Unlock()
	chatImgClean()
	chatMu.Lock()
	defer chatMu.Unlock()
	if chatImgExists(keep) || chatSession("").log[0].Img != "" {
		t.Fatalf("doveva essere eliminata: %+v", chatSession("").log[0])
	}
}

func TestChatImgNormalizeResizesBigScreens(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 3840, 2160))
	for y := 0; y < 2160; y += 7 {
		for x := 0; x < 3840; x++ {
			src.Set(x, y, color.RGBA{uint8(x), uint8(y), 90, 255})
		}
	}
	var pb bytes.Buffer
	if err := png.Encode(&pb, src); err != nil {
		t.Fatal(err)
	}
	out, ok := chatImgNormalize(pb.Bytes())
	if !ok || len(out) > chatImgMax || chatImgType(out) != "jpg" {
		t.Fatalf("normalize: ok=%v len=%d", ok, len(out))
	}
	im, _, err := image.Decode(bytes.NewReader(out))
	if err != nil || im.Bounds().Dx() != 1600 || im.Bounds().Dy() != 900 {
		t.Fatalf("dimensioni: %v %v", im.Bounds(), err)
	}
	if _, ok := chatImgNormalize([]byte("\x89PNG\r\n\x1a\nrotto")); ok {
		t.Fatal("un PNG corrotto non deve passare")
	}
}

// ---- conversazioni per utente (1.67.0) ----

func TestChatSessionsPerUserAreSeparate(t *testing.T) {
	chatTestReset(t)
	chatResolve = func(k string) (string, bool) {
		switch k {
		case "ka":
			return `PC\anna`, true
		case "kb":
			return `PC\bruno`, true
		}
		return "", false
	}
	defer func() { chatResolve = func(k string) (string, bool) { return "", k == "1" } }()
	h := chatHandler(&Config{})
	send := func(key, text string) int {
		b, _ := json.Marshal(map[string]any{"text": text})
		r := httptest.NewRequest("POST", "http://127.0.0.1:1/send", bytes.NewReader(b))
		r.Header.Set("X-Myrmm-Tray", key)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w.Code
	}
	if send("ka", "ciao da Anna") != 200 || send("kb", "ciao da Bruno") != 200 || send("kb", "e ancora Bruno") != 200 {
		t.Fatal("invio")
	}
	if send("kx", "intruso") != http.StatusForbidden {
		t.Fatal("chiave sconosciuta: atteso 403")
	}
	chatMu.Lock()
	a, b := len(chatSession(`PC\anna`).log), len(chatSession(`PC\bruno`).log)
	chatMu.Unlock()
	if a != 1 || b != 2 {
		t.Fatalf("anna=%d bruno=%d", a, b)
	}
	p := chatPrepare()
	ss := p["sessions"].([]map[string]any)
	if len(ss) != 2 || ss[0]["user"] != `PC\anna` || ss[1]["user"] != `PC\bruno` || len(ss[1]["out"].([]map[string]string)) != 2 {
		t.Fatalf("sessions: %+v", ss)
	}
	if _, legacy := p["out"]; legacy {
		t.Fatal("con due utenti non si ripetono i campi del server precedente")
	}
	// i file sono separati e si rileggono all'avvio
	chatSessions = map[string]*chatSess{}
	chatLoadAll()
	chatMu.Lock()
	n := len(chatSessions)
	b2 := len(chatSession(`pc\BRUNO`).log) // il nome utente non distingue maiuscole
	chatMu.Unlock()
	if n != 2 || b2 != 2 {
		t.Fatalf("rilettura: %d sessioni, bruno=%d", n, b2)
	}
}

func TestChatHandleRoutesBySession(t *testing.T) {
	chatTestReset(t)
	chatMu.Lock()
	chatSession(`PC\anna`)
	chatSession(`PC\bruno`)
	chatMu.Unlock()
	mk := func(id int, tx string) chatMsg {
		return chatMsg{ID: id, Author: "Op", Text: tx, TS: "2026-01-01T00:00:00Z"}
	}
	chatHandle(&chatResp{Sessions: map[string]*chatResp{
		`PC\anna`:  {Msgs: []chatMsg{mk(5, "per Anna")}},
		`PC\bruno`: {Msgs: []chatMsg{mk(5, "per Bruno"), mk(6, "ancora")}},
	}})
	chatMu.Lock()
	defer chatMu.Unlock()
	a, b := chatSession(`PC\anna`), chatSession(`PC\bruno`)
	if len(a.log) != 1 || a.log[0].Text != "per Anna" || a.ack != 5 || len(b.log) != 2 || b.ack != 6 {
		t.Fatalf("anna=%+v bruno=%+v", a.log, b.log)
	}
}

func TestChatLegacyFileAdoptedByFirstUser(t *testing.T) {
	chatTestReset(t)
	_ = os.WriteFile(chatSessFile(""), []byte(`{"Ack":7,"Read":3,"Log":[{"dir":"op","text":"vecchio","ts":"2026-01-01T00:00:00Z","srv_id":7}]}`), 0o600)
	chatMu.Lock()
	s := chatSession(`PC\anna`)
	got := len(s.log) == 1 && s.ack == 7 && s.read == 3
	other := chatSession(`PC\bruno`)
	empty := len(other.log) == 0
	chatMu.Unlock()
	if !got || !empty {
		t.Fatal("la conversazione della versione precedente va al primo utente, non al secondo")
	}
	if _, err := os.Stat(chatSessFile("") + ".old"); err != nil {
		t.Fatal("il file vecchio andava rinominato")
	}
}

func TestChatImgFetchOnDemandAndReason(t *testing.T) {
	chatTestReset(t)
	n := "ci0123456789abcdef0123456789abcdef"
	ok := true
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Device-Key") != "K" || r.URL.Query().Get("n") != n {
			http.Error(w, "no", 403)
			return
		}
		if !ok {
			http.Error(w, "non trovata", 404)
			return
		}
		_, _ = w.Write(tinyPNG)
	}))
	defer srv.Close()
	chatMu.Lock()
	chatSession("").log = []chatEntry{{Dir: "op", SrvID: 1, Img: n, TS: time.Now().UTC().Format(time.RFC3339)}}
	chatServer.URL, chatServer.Key = srv.URL, "K"
	chatMu.Unlock()
	h := chatHandler(&Config{})
	// 1) il server rifiuta: la tray riceve 502 con il motivo, /state lo riporta
	ok = false
	w := chatReq(t, h, "GET", "/img?n="+n, nil)
	if w.Code != http.StatusBadGateway || !strings.Contains(w.Body.String(), "404") {
		t.Fatalf("atteso 502 con il motivo: %d %s", w.Code, w.Body.String())
	}
	st := chatReq(t, h, "GET", "/state", nil).Body.String()
	if !strings.Contains(st, `"img_err"`) || !strings.Contains(st, `"ready":true`) {
		t.Fatalf("state senza motivo: %s", st)
	}
	// 2) il server risponde: l'immagine si scarica nel momento della richiesta e l'errore sparisce
	ok = true
	w = chatReq(t, h, "GET", "/img?n="+n, nil)
	if w.Code != 200 || chatImgType(w.Body.Bytes()) != "png" || !chatImgExists(n) {
		t.Fatalf("scaricamento su richiesta: %d", w.Code)
	}
	if strings.Contains(chatReq(t, h, "GET", "/state", nil).Body.String(), `"img_err"`) {
		t.Fatal("l'errore doveva sparire")
	}
}

func TestChatDisabledStateAndPing(t *testing.T) {
	chatTestReset(t)
	h := chatHandler(&Config{})
	chatDisabled.Store(true)
	defer chatDisabled.Store(false)
	if b := chatReq(t, h, "GET", "/state", nil).Body.String(); !strings.Contains(b, `"disabled":true`) {
		t.Fatalf("state: %s", b)
	}
	r := httptest.NewRequest("GET", "http://127.0.0.1:1/ping", nil) // senza chiave: solo versione e conteggio
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), AgentVersion) {
		t.Fatalf("ping: %d %s", w.Code, w.Body.String())
	}
	r = httptest.NewRequest("GET", "http://evil.example/ping", nil)
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusForbidden {
		t.Fatalf("ping da host non locale: %d", w.Code)
	}
}
