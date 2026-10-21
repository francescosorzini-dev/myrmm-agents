package main

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

// Diagnostica: «agent diag» sul PC, oppure dalla console (job #myrmm-diag). Raccoglie tutto ciò che serve a capire
// perché un agent, il collegamento al server, l'icona o la chat non funzionano. Segreti sempre oscurati.
const diagPrefix = "#myrmm-diag\n"

func redact(s string) string {
	if len(s) <= 6 {
		return "***"
	}
	return s[:2] + strings.Repeat("*", 6) + fmt.Sprintf(" (%d car.)", len(s))
}

// runCmd esegue un comando con timeout e ne restituisce l'output (stdout+stderr) senza mai bloccarsi.
func runCmd(timeout time.Duration, name string, args ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
	s := strings.TrimSpace(string(out))
	if ctx.Err() != nil {
		s += "\n[timeout dopo " + timeout.String() + "]"
	} else if err != nil && s == "" {
		s = "errore: " + err.Error()
	}
	return s
}

type diagBuf struct{ b strings.Builder }

func (d *diagBuf) sec(title string)          { fmt.Fprintf(&d.b, "\n==== %s ====\n", title) }
func (d *diagBuf) f(format string, a ...any) { fmt.Fprintf(&d.b, format+"\n", a...) }
func (d *diagBuf) raw(s string) {
	if s != "" {
		d.b.WriteString(strings.TrimRight(s, "\r\n") + "\n")
	}
}

func collectDiag() string {
	var d diagBuf
	start := time.Now()
	host, _ := os.Hostname()
	exe, _ := os.Executable()
	d.f("myrmm diagnostica — %s — %s", host, time.Now().Format(time.RFC3339))
	d.sec("Agent")
	d.f("versione:      %s", AgentVersion)
	d.f("piattaforma:   %s (%s/%s) go %s", platTag(), runtime.GOOS, runtime.GOARCH, runtime.Version())
	d.f("pid:           %d", os.Getpid())
	d.f("eseguibile:    %s", exe)
	if st, err := os.Stat(exe); err == nil {
		d.f("  dimensione %d byte, modificato %s", st.Size(), st.ModTime().Format(time.RFC3339))
		if f, e := os.Open(exe); e == nil {
			h := sha256.New()
			_, _ = io.Copy(h, f)
			f.Close()
			d.f("  sha256 %s", hex.EncodeToString(h.Sum(nil)))
		}
	}
	d.f("cartella dati: %s", dataDir())
	d.f("fuso orario:   %s", time.Now().Format("MST -07:00"))

	d.sec("Configurazione (segreti oscurati)")
	cfg, err := loadConfig()
	if err != nil {
		d.f("ERRORE: %v", err)
	} else {
		d.f("server_url:           %s", cfg.ServerURL)
		d.f("enroll_token:         %s", redact(cfg.EnrollToken))
		d.f("job_signing_key:      %s  %s", redact(cfg.JobSigningKey), map[bool]string{true: "", false: "<-- ASSENTE: niente auto-update, niente disinstallazione, job non firmati"}[cfg.JobSigningKey != ""])
		d.f("poll_seconds:         %d", cfg.PollSeconds)
		if cfg.WakeSeconds != nil {
			d.f("wake_seconds:         %d", *cfg.WakeSeconds)
		} else {
			d.f("wake_seconds:         (default)")
		}
		d.f("site:                 %q", cfg.Site)
		d.f("tm_mode/fs_mode:      %q / %q", cfg.TmMode, cfg.FsMode)
		d.f("tray_mode/tray_port:  %q / %d", cfg.TrayMode, cfg.TrayPort)
	}
	if b, e := os.ReadFile(statePath()); e == nil {
		var s State
		if json.Unmarshal(b, &s) == nil {
			d.f("arruolato:            sì, device #%d, chiave %s", s.DeviceID, redact(s.APIKey))
		} else {
			d.f("state.json illeggibile")
		}
	} else {
		d.f("arruolato:            NO (state.json assente: %v)", e)
	}

	d.sec("File nella cartella dati")
	if ents, e := os.ReadDir(dataDir()); e == nil {
		sort.Slice(ents, func(i, j int) bool { return ents[i].Name() < ents[j].Name() })
		for _, en := range ents {
			if fi, e2 := en.Info(); e2 == nil {
				d.f("%-28s %9d  %s", en.Name(), fi.Size(), fi.ModTime().Format("2006-01-02 15:04:05"))
			}
		}
	} else {
		d.f("non leggibile: %v", e)
	}
	if b, e := os.ReadFile(filepath.Join(dataDir(), "enroll-status.txt")); e == nil {
		d.f("--- enroll-status.txt (ultimo errore di arruolamento) ---")
		d.raw(string(b))
	}

	if cfg != nil {
		diagServer(&d, cfg)
	}

	d.sec("Sessioni utente")
	ss := platSessions()
	if len(ss) == 0 {
		d.f("nessuna sessione utente")
	}
	for _, s := range ss {
		d.f("%-30s %-12s %s", s.User, s.State, s.Via)
	}

	d.sec("Chat e icona nella systray")
	d.f("tray attiva per questa configurazione: %v", trayOn(cfg0(cfg)))
	if b, e := os.ReadFile(filepath.Join(dataDir(), "tray.json")); e == nil {
		d.f("tray.json: %s", strings.TrimSpace(string(b)))
		var tj struct{ Port int }
		if json.Unmarshal(b, &tj) == nil && tj.Port > 0 {
			d.raw(diagLocalAPI(tj.Port))
		}
	} else {
		d.f("tray.json assente: l'API locale non è partita (il servizio si avvia con tray_mode diverso da off?)")
	}
	d.raw(trayDiag())
	if ents, e := os.ReadDir(dataDir()); e == nil {
		for _, en := range ents {
			n := en.Name()
			if n != "chat.json" && !(strings.HasPrefix(n, "chat-") && strings.HasSuffix(n, ".json")) {
				continue
			}
			b, e := os.ReadFile(filepath.Join(dataDir(), n))
			if e != nil {
				continue
			}
			var f struct {
				User      string
				Ack, Read int
				Log       []chatEntry
			}
			if json.Unmarshal(b, &f) != nil {
				continue
			}
			unsent := 0
			for _, en := range f.Log {
				if en.Dir == "user" && !en.Sent {
					unsent++
				}
			}
			d.f("%s (utente %q): %d messaggi, ultimo ricevuto #%d, letto fino a #%d, non ancora inviati al server: %d", n, f.User, len(f.Log), f.Ack, f.Read, unsent)
			for i := max(0, len(f.Log)-5); i < len(f.Log); i++ {
				t := f.Log[i].Text
				if len([]rune(t)) > 60 {
					t = string([]rune(t)[:60]) + "…"
				}
				d.f("   [%s] %s: %s", f.Log[i].TS, f.Log[i].Dir, t)
			}
		}
	}

	d.sec("Sistema e piattaforma")
	d.raw(platDiag())

	d.f("\n(diagnostica completata in %.1f s)", time.Since(start).Seconds())
	return d.b.String()
}

func cfg0(c *Config) *Config {
	if c == nil {
		return &Config{}
	}
	return c
}

func diagServer(d *diagBuf, cfg *Config) {
	d.sec("Collegamento al server")
	u, err := url.Parse(cfg.ServerURL)
	if err != nil || u.Host == "" {
		d.f("server_url non valido: %q", cfg.ServerURL)
		return
	}
	hostname := u.Hostname()
	port := u.Port()
	if port == "" {
		port = map[string]string{"https": "443", "http": "80"}[u.Scheme]
	}
	t0 := time.Now()
	ips, err := net.LookupHost(hostname)
	if err != nil {
		d.f("DNS %s: ERRORE %v", hostname, err)
		return
	}
	d.f("DNS %s -> %s (%.0f ms)", hostname, strings.Join(ips, ", "), float64(time.Since(t0).Milliseconds()))
	t0 = time.Now()
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(hostname, port), 8*time.Second)
	if err != nil {
		d.f("TCP %s:%s: ERRORE %v", hostname, port, err)
	} else {
		d.f("TCP %s:%s: ok (%.0f ms)", hostname, port, float64(time.Since(t0).Milliseconds()))
		conn.Close()
	}
	if u.Scheme == "https" {
		tc, err := tls.DialWithDialer(&net.Dialer{Timeout: 8 * time.Second}, "tcp", net.JoinHostPort(hostname, port), &tls.Config{ServerName: hostname})
		if err != nil {
			d.f("TLS: ERRORE %v   (certificato non valido o intercettazione TLS/proxy?)", err)
		} else {
			cs := tc.ConnectionState()
			if len(cs.PeerCertificates) > 0 {
				c := cs.PeerCertificates[0]
				d.f("TLS: ok, soggetto %q, emesso da %q, scade %s", c.Subject.CommonName, c.Issuer.CommonName, c.NotAfter.Format("2006-01-02"))
				if time.Until(c.NotAfter) < 14*24*time.Hour {
					d.f("   ATTENZIONE: il certificato scade tra meno di 14 giorni")
				}
			}
			tc.Close()
		}
	}
	for _, k := range []string{"HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy"} {
		if v := os.Getenv(k); v != "" {
			d.f("variabile %s=%s", k, v)
		}
	}
	// richiesta applicativa senza chiave: ci aspettiamo 401 "missing device key" da myrmm
	t0 = time.Now()
	req, _ := http.NewRequest(http.MethodGet, cfg.ServerURL+"?action=agent_bin&plat="+platTag(), nil)
	resp, err := httpClient.Do(req)
	if err != nil {
		d.f("HTTP: ERRORE %v", err)
		return
	}
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 300))
	resp.Body.Close()
	d.f("HTTP GET ?action=agent_bin senza chiave: %d in %.0f ms — %s", resp.StatusCode, float64(time.Since(t0).Milliseconds()), strings.TrimSpace(string(body)))
	if resp.StatusCode == 401 && strings.Contains(string(body), "missing device key") {
		d.f("   -> raggiunge davvero l'applicazione myrmm (risposta attesa)")
	} else if resp.StatusCode == 403 || resp.StatusCode == 404 || resp.StatusCode >= 500 {
		d.f("   -> NON è la risposta di myrmm: controlla URL, WAF, regole .htaccess o hosting")
	}
	if ds := resp.Header.Get("Date"); ds != "" {
		if sv, e := http.ParseTime(ds); e == nil {
			skew := time.Since(sv)
			d.f("orologio: differenza dal server %.0f s%s", skew.Seconds(), map[bool]string{true: "   <-- ATTENZIONE: orologio sfasato", false: ""}[skew > 5*time.Minute || skew < -5*time.Minute])
		}
	}
	// stato del collegamento: un heartbeat leggero con la chiave del device
	if b, e := os.ReadFile(statePath()); e == nil {
		var s State
		if json.Unmarshal(b, &s) == nil && s.APIKey != "" {
			var hb heartbeatResp
			t0 = time.Now()
			if e := postJSON(cfg.ServerURL+"?action=heartbeat", s.APIKey, map[string]any{"light": true}, &hb); e != nil {
				d.f("heartbeat con la chiave del device: ERRORE %v", e)
			} else {
				d.f("heartbeat con la chiave del device: ok (%.0f ms), job in coda: %d, aggiornamento proposto: %v, disinstallazione richiesta: %v", float64(time.Since(t0).Milliseconds()), len(hb.Jobs), hb.Update != nil, hb.Uninstall != nil)
			}
		}
	}
}

func diagLocalAPI(port int) string {
	req, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/ping", port), nil)
	resp, err := (&http.Client{Timeout: 4 * time.Second}).Do(req)
	if err != nil {
		return fmt.Sprintf("API locale 127.0.0.1:%d: NON risponde (%v)", port, err)
	}
	defer resp.Body.Close()
	var st struct {
		Online  bool
		Version string
		Users   int
	}
	_ = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&st)
	return fmt.Sprintf("API locale 127.0.0.1:%d: HTTP %d, versione %s, collegato al server: %v, conversazioni: %d", port, resp.StatusCode, st.Version, st.Online, st.Users)
}

// diagExec: esecuzione come job dalla console.
func diagExec() runResult {
	t0 := time.Now()
	out := collectDiag()
	return runResult{ExitCode: 0, Stdout: out, Duration: time.Since(t0).Seconds()}
}
