package main

// File manager: operazioni sul filesystem richieste dalla console come job firmati.
// Il "copione" del job è "#myrmm-fs\n" + JSON {"op":…}. Risposta: JSON su stdout, errori su stderr (exit 1).
// Lo scambio file passa dal server (endpoint fs_up / fs_get) con la chiave del device; gli URL non vengono
// mai letti dal job (si usa sempre server_url della config), così un job non può far contattare altri host.

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

const fsPrefix = "#myrmm-fs\n"

const (
	fsMaxEntries = 800       // oltre, l'elenco è troncato (il risultato sta sotto i 256 KB del server)
	fsTailMax    = 96 * 1024 // massimo letto da "tail"
	fsHTTPTimout = 10 * time.Minute
)

type fsOp struct {
	Op        string `json:"op"`
	Path      string `json:"path"`
	To        string `json:"to"`
	Recursive bool   `json:"recursive"`
	Bytes     int64  `json:"bytes"`
	TID       string `json:"tid"`
	MaxBytes  int64  `json:"max"`
	Overwrite bool   `json:"overwrite"`
	SHA256    string `json:"sha256"`
	Size      int64  `json:"size"`
}

type fsEntry struct {
	N string `json:"n"`           // nome
	D bool   `json:"d,omitempty"` // directory
	L bool   `json:"l,omitempty"` // link simbolico
	S int64  `json:"s"`           // dimensione
	M int64  `json:"m"`           // mtime (unix)
	A string `json:"a,omitempty"` // attributi / permessi
}

func fsFail(format string, a ...any) runResult {
	return runResult{ExitCode: 1, Stderr: fmt.Sprintf(format, a...)}
}

func fsOK(v any) runResult {
	b, _ := json.Marshal(v)
	return runResult{ExitCode: 0, Stdout: string(b)}
}

// fsProtected: percorsi che il file manager non tocca mai (cartella dati dell'agent e suo eseguibile).
func fsProtected(p string) bool {
	clean := filepath.Clean(p)
	eq := func(a, b string) bool {
		if runtime.GOOS == "windows" {
			return strings.EqualFold(a, b)
		}
		return a == b
	}
	d := filepath.Clean(dataDir())
	lc := func(x string) string {
		if runtime.GOOS == "windows" {
			return strings.ToLower(x)
		}
		return x
	}
	if eq(clean, d) || strings.HasPrefix(lc(clean)+string(filepath.Separator), lc(d)+string(filepath.Separator)) {
		return true
	}
	if exe, err := os.Executable(); err == nil && eq(clean, filepath.Clean(exe)) {
		return true
	}
	return false
}

func fsIsRoot(p string) bool { c := filepath.Clean(p); return filepath.Dir(c) == c }

func fsRoots() []fsEntry {
	var out []fsEntry
	if runtime.GOOS == "windows" {
		for c := 'A'; c <= 'Z'; c++ {
			r := string(c) + `:\`
			if st, err := os.Stat(r); err == nil {
				out = append(out, fsEntry{N: r, D: true, M: st.ModTime().Unix()})
			}
		}
		return out
	}
	return []fsEntry{{N: "/", D: true}}
}

func fsAbs(p string) (string, error) {
	if p == "" {
		return "", fmt.Errorf("percorso mancante")
	}
	if !filepath.IsAbs(p) {
		return "", fmt.Errorf("serve un percorso assoluto: %q", p)
	}
	return filepath.Clean(p), nil
}

func fsList(path string) runResult {
	if path == "" {
		return fsOK(map[string]any{"path": "", "parent": "", "entries": fsRoots()})
	}
	p, err := fsAbs(path)
	if err != nil {
		return fsFail("%v", err)
	}
	des, err := os.ReadDir(p)
	if err != nil {
		return fsFail("%v", err)
	}
	ents := make([]fsEntry, 0, len(des))
	for _, de := range des {
		e := fsEntry{N: de.Name()}
		if info, err := de.Info(); err == nil {
			e.S, e.M = info.Size(), info.ModTime().Unix()
			e.D = info.IsDir()
			e.A = fsAttr(info)
			if info.Mode()&os.ModeSymlink != 0 {
				e.L = true
				if st, err := os.Stat(filepath.Join(p, de.Name())); err == nil {
					e.D = st.IsDir()
				}
			}
		}
		if e.D {
			e.S = 0
		}
		ents = append(ents, e)
	}
	sort.Slice(ents, func(i, j int) bool {
		if ents[i].D != ents[j].D {
			return ents[i].D
		}
		return strings.ToLower(ents[i].N) < strings.ToLower(ents[j].N)
	})
	total := len(ents)
	if total > fsMaxEntries {
		ents = ents[:fsMaxEntries]
	}
	parent := filepath.Dir(p)
	if parent == p {
		parent = ""
	}
	return fsOK(map[string]any{"path": p, "parent": parent, "entries": ents, "total": total, "truncated": total > len(ents)})
}

func fsAttr(info os.FileInfo) string {
	if runtime.GOOS == "windows" {
		return ""
	}
	return info.Mode().Perm().String()
}

func fsTail(path string, n int64) runResult {
	p, err := fsAbs(path)
	if err != nil {
		return fsFail("%v", err)
	}
	if n <= 0 || n > fsTailMax {
		n = fsTailMax
	}
	f, err := os.Open(p)
	if err != nil {
		return fsFail("%v", err)
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return fsFail("%v", err)
	}
	if st.IsDir() {
		return fsFail("è una cartella")
	}
	off := st.Size() - n
	if off < 0 {
		off = 0
	}
	if _, err := f.Seek(off, io.SeekStart); err != nil {
		return fsFail("%v", err)
	}
	buf, err := io.ReadAll(io.LimitReader(f, n))
	if err != nil {
		return fsFail("%v", err)
	}
	bin := bytes.IndexByte(buf, 0) >= 0
	text := ""
	if !bin {
		text = strings.ToValidUTF8(string(buf), "�")
	}
	return fsOK(map[string]any{"path": p, "size": st.Size(), "offset": off, "binary": bin, "text": text})
}

func fsSHA(path string) (string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, f)
	return hex.EncodeToString(h.Sum(nil)), n, err
}

// fsGet: legge il file e lo carica sul server (la console lo scarica da lì).
func fsGet(cfg *Config, st State, o fsOp) runResult {
	p, err := fsAbs(o.Path)
	if err != nil {
		return fsFail("%v", err)
	}
	info, err := os.Stat(p)
	if err != nil {
		return fsFail("%v", err)
	}
	if info.IsDir() {
		return fsFail("è una cartella: scarica un file")
	}
	if o.MaxBytes > 0 && info.Size() > o.MaxBytes {
		return fsFail("file di %d byte: supera il limite di trasferimento (%d byte)", info.Size(), o.MaxBytes)
	}
	sum, size, err := fsSHA(p)
	if err != nil {
		return fsFail("%v", err)
	}
	f, err := os.Open(p)
	if err != nil {
		return fsFail("%v", err)
	}
	defer f.Close()
	req, _ := http.NewRequest(http.MethodPost, cfg.ServerURL+"?action=fs_up&tid="+url.QueryEscape(o.TID), f)
	req.ContentLength = size
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("X-Device-Key", st.APIKey)
	req.Header.Set("X-Sha256", sum)
	resp, err := (&http.Client{Timeout: fsHTTPTimout}).Do(req)
	if err != nil {
		return fsFail("invio al server fallito: %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if resp.StatusCode != http.StatusOK {
		return fsFail("il server ha rifiutato il file (HTTP %d): %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return fsOK(map[string]any{"path": p, "size": size, "sha256": sum})
}

// fsPut: scarica dal server il file caricato in console e lo scrive in modo atomico.
func fsPut(cfg *Config, st State, o fsOp) runResult {
	dest, err := fsAbs(o.Path)
	if err != nil {
		return fsFail("%v", err)
	}
	if fsProtected(dest) {
		return fsFail("percorso protetto (dati dell'agent)")
	}
	if fi, err := os.Stat(dest); err == nil {
		if fi.IsDir() {
			return fsFail("la destinazione è una cartella")
		}
		if !o.Overwrite {
			return fsFail("il file esiste già (attiva «sovrascrivi»)")
		}
	}
	dir := filepath.Dir(dest)
	if fi, err := os.Stat(dir); err != nil || !fi.IsDir() {
		return fsFail("cartella di destinazione inesistente: %s", dir)
	}
	req, _ := http.NewRequest(http.MethodGet, cfg.ServerURL+"?action=fs_get&tid="+url.QueryEscape(o.TID), nil)
	req.Header.Set("X-Device-Key", st.APIKey)
	resp, err := (&http.Client{Timeout: fsHTTPTimout}).Do(req)
	if err != nil {
		return fsFail("download dal server fallito: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fsFail("il server non fornisce il file (HTTP %d)", resp.StatusCode)
	}
	var rnd [6]byte
	_, _ = rand.Read(rnd[:])
	tmp := filepath.Join(dir, ".myrmm-"+hex.EncodeToString(rnd[:])+".tmp")
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		return fsFail("%v", err)
	}
	h := sha256.New()
	limit := o.MaxBytes
	if limit <= 0 {
		limit = 1 << 30
	}
	n, err := io.Copy(io.MultiWriter(out, h), io.LimitReader(resp.Body, limit+1))
	cerr := out.Close()
	if err == nil {
		err = cerr
	}
	if err != nil {
		_ = os.Remove(tmp)
		return fsFail("scrittura fallita: %v", err)
	}
	if n > limit {
		_ = os.Remove(tmp)
		return fsFail("file oltre il limite di trasferimento")
	}
	if got := hex.EncodeToString(h.Sum(nil)); o.SHA256 != "" && !strings.EqualFold(got, o.SHA256) {
		_ = os.Remove(tmp)
		return fsFail("SHA-256 non corrisponde: trasferimento corrotto, file scartato")
	}
	if o.Size > 0 && n != o.Size {
		_ = os.Remove(tmp)
		return fsFail("dimensione inattesa (%d invece di %d byte)", n, o.Size)
	}
	if runtime.GOOS == "windows" {
		_ = os.Remove(dest) // su Windows rename non sovrascrive
	}
	if err := os.Rename(tmp, dest); err != nil {
		_ = os.Remove(tmp)
		return fsFail("%v", err)
	}
	return fsOK(map[string]any{"path": dest, "size": n})
}

// fsExec esegue un'operazione. mode: "rw" | "ro" | "off" (policy locale dell'agent, config.json: fs_mode).
func fsExec(cfg *Config, st State, script string) runResult {
	start := time.Now()
	var o fsOp
	if err := json.Unmarshal([]byte(strings.TrimPrefix(script, fsPrefix)), &o); err != nil {
		return fsFail("richiesta file non valida: %v", err)
	}
	mode := strings.ToLower(cfg.FsMode)
	if mode == "" {
		mode = "rw"
	}
	if mode == "off" {
		return fsFail("file manager disattivato su questo device (fs_mode=off nella config dell'agent)")
	}
	write := map[string]bool{"mkdir": true, "mv": true, "rm": true, "put": true}
	if write[o.Op] && mode != "rw" {
		return fsFail("il device è in sola lettura (fs_mode=%s nella config dell'agent)", mode)
	}
	var r runResult
	switch o.Op {
	case "ls":
		r = fsList(o.Path)
	case "tail":
		r = fsTail(o.Path, o.Bytes)
	case "get":
		r = fsGet(cfg, st, o)
	case "put":
		r = fsPut(cfg, st, o)
	case "mkdir":
		p, err := fsAbs(o.Path)
		switch {
		case err != nil:
			r = fsFail("%v", err)
		case fsProtected(p):
			r = fsFail("percorso protetto (dati dell'agent)")
		default:
			if err := os.MkdirAll(p, 0o755); err != nil {
				r = fsFail("%v", err)
			} else {
				r = fsOK(map[string]any{"path": p})
			}
		}
	case "mv":
		a, e1 := fsAbs(o.Path)
		b, e2 := fsAbs(o.To)
		switch {
		case e1 != nil:
			r = fsFail("%v", e1)
		case e2 != nil:
			r = fsFail("%v", e2)
		case fsIsRoot(a) || fsProtected(a) || fsProtected(b):
			r = fsFail("percorso protetto")
		default:
			if _, err := os.Lstat(b); err == nil {
				r = fsFail("la destinazione esiste già")
			} else if err := os.Rename(a, b); err != nil {
				r = fsFail("%v", err)
			} else {
				r = fsOK(map[string]any{"path": b})
			}
		}
	case "rm":
		p, err := fsAbs(o.Path)
		switch {
		case err != nil:
			r = fsFail("%v", err)
		case fsIsRoot(p) || fsProtected(p):
			r = fsFail("percorso protetto: non si elimina una radice né i dati dell'agent")
		default:
			fi, err := os.Lstat(p)
			if err != nil {
				r = fsFail("%v", err)
			} else if fi.IsDir() && !o.Recursive {
				if err := os.Remove(p); err != nil {
					r = fsFail("cartella non vuota o non eliminabile: %v", err)
				} else {
					r = fsOK(map[string]any{"path": p})
				}
			} else if fi.IsDir() {
				if err := os.RemoveAll(p); err != nil {
					r = fsFail("%v", err)
				} else {
					r = fsOK(map[string]any{"path": p})
				}
			} else if err := os.Remove(p); err != nil {
				r = fsFail("%v", err)
			} else {
				r = fsOK(map[string]any{"path": p})
			}
		}
	default:
		r = fsFail("operazione sconosciuta: %q", o.Op)
	}
	r.Duration = time.Since(start).Seconds()
	return r
}
