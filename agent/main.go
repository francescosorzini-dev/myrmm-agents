// myrmm-agent — agent di gestione remota (MVP)
//
// Shell del servizio in Go (binario singolo, nessun runtime).
// Comunica SOLO in outbound verso il server su HTTPS (polling),
// esegue i job come PowerShell e ne rimanda i risultati.
//
// Uso:
//
//	myrmm-agent install     installa il servizio (Windows SCM / systemd / launchd)
//	myrmm-agent start|stop|uninstall
//	myrmm-agent run         esegue in foreground (debug)
//	myrmm-agent             (avviato dal SCM) gira come servizio
//
// Config: Windows %ProgramData%\myrmm\config.json · Linux /etc/myrmm/config.json ·
//
//	macOS /Library/Application Support/myrmm/config.json  (vedi config.example.json)
//
// Stato:  state.json nella stessa cartella (device_id + api_key, auto)
package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/kardianos/service"
)

const AgentVersion = "1.70.0"

// ---- config / stato -------------------------------------------------------

type Config struct {
	ServerURL         string `json:"server_url"`          // es. https://rmm.example.com/index.php
	EnrollToken       string `json:"enroll_token"`        // segreto condiviso di arruolamento
	PollSeconds       int    `json:"poll_seconds"`        // intervallo dell'heartbeat completo (con inventario)
	WakeSeconds       *int   `json:"wake_seconds"`        // heartbeat leggero tra due completi per ricevere subito job e richieste della console (default 15, 0 = disattivato)
	JobSigningKey     string `json:"job_signing_key"`     // se valorizzata, i job NON firmati o con firma errata vengono rifiutati
	FullInventoryHour int    `json:"full_inventory_hour"` // ogni quante ore raccogliere l'inventario completo (0 = disattivato, default 12)
	Site              string `json:"site"`                // multi-tenant: sito/cliente (inviato all'enroll)
	TmMode            string `json:"tm_mode"`             // task manager: "rw" (default) | "ro" solo elenco | "off"
	TrayMode          string `json:"tray_mode"`           // Windows: "on" (default) icona nella systray + chat con l'assistenza | "off"
	TrayPort          int    `json:"tray_port"`           // porta locale (127.0.0.1) usata dall'icona; default 47653
	TunnelMode        string `json:"tunnel_mode"`         // tunnel RDP/SSH aperti dalla console: "on" (default) | "off"
	TunnelPorts       []int  `json:"tunnel_ports"`        // porte locali raggiungibili con un tunnel (default 3389, 22, 5900)
	TunnelNet         string `json:"tunnel_net"`          // tunnel verso apparati della LAN (solo se l'agent è una sonda): "on" (default) | "off"
	NetTunnelPorts    []int  `json:"net_tunnel_ports"`    // porte degli apparati raggiungibili con un tunnel (default 22, 80, 443, 3389, 5900, 8080, 8443)
	FsMode            string `json:"fs_mode"`             // file manager: "rw" (default) | "ro" sola lettura | "off" disattivato su questo device
}

type State struct {
	DeviceID int    `json:"device_id"`
	APIKey   string `json:"api_key"`
}

func loadConfig() (*Config, error) {
	b, err := os.ReadFile(filepath.Join(dataDir(), "config.json"))
	if err != nil {
		return nil, fmt.Errorf("config non leggibile (%s): %w", filepath.Join(dataDir(), "config.json"), err)
	}
	// Tollera il BOM UTF-8: Set-Content -Encoding utf8 (PowerShell 5.1) lo aggiunge
	// e romperebbe json.Unmarshal.
	b = bytes.TrimPrefix(b, []byte{0xEF, 0xBB, 0xBF})
	var c Config
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, fmt.Errorf("config.json non valido: %w", err)
	}
	if c.ServerURL == "" || c.EnrollToken == "" {
		return nil, fmt.Errorf("config.json: server_url ed enroll_token sono obbligatori")
	}
	if b, e := os.ReadFile(filepath.Join(dataDir(), "tray.mode")); e == nil { // scelta fatta dalla console: prevale su config.json
		if m := strings.ToLower(strings.TrimSpace(string(b))); m == "on" || m == "off" {
			c.TrayMode = m
		}
	}
	if c.PollSeconds <= 0 {
		c.PollSeconds = 60
	}
	if c.FullInventoryHour == 0 {
		c.FullInventoryHour = 12 // default; usa -1 nel config per disattivarlo
	}
	return &c, nil
}

func statePath() string { return filepath.Join(dataDir(), "state.json") }

func loadState() State {
	var s State
	if b, err := os.ReadFile(statePath()); err == nil {
		_ = json.Unmarshal(b, &s)
	}
	return s
}

func saveState(s State) error {
	if err := os.MkdirAll(dataDir(), 0o755); err != nil {
		return err
	}
	b, _ := json.MarshalIndent(s, "", "  ")
	return os.WriteFile(statePath(), b, 0o600)
}

// ---- HTTP ----------------------------------------------------------------

var httpClient = &http.Client{Timeout: 30 * time.Second}

func postJSON(url, deviceKey string, in any, out any) error {
	body, _ := json.Marshal(in)
	gz := false
	if len(body) > 4096 { // elenchi processi e inventari: compressi (il server li espande, header X-Gzip)
		var zb bytes.Buffer
		zw := gzip.NewWriter(&zb)
		_, _ = zw.Write(body)
		if zw.Close() == nil {
			body, gz = zb.Bytes(), true
		}
	}
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if gz {
		req.Header.Set("X-Gzip", "1")
	}
	if deviceKey != "" {
		req.Header.Set("X-Device-Key", deviceKey)
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(data))
	}
	if out != nil {
		if err := json.Unmarshal(data, out); err != nil {
			snip := strings.Join(strings.Fields(string(data)), " ")
			if len(snip) > 200 {
				snip = snip[:200] + "…"
			}
			return fmt.Errorf("risposta non valida dal server (HTTP %d, inizia con %q): %v", resp.StatusCode, snip, err)
		}
	}
	return nil
}

// ---- protocollo -----------------------------------------------------------

type Job struct {
	ID      int    `json:"id"`
	Script  string `json:"script"`
	Timeout int    `json:"timeout"`
	Sig     string `json:"sig"` // HMAC-SHA256 esadecimale del job (vedi jobSignature)
}

type UpdateInfo struct {
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
	Sig     string `json:"sig"`             // HMAC("update\n<version>\n<sha256>")
	Force   bool   `json:"force,omitempty"` // reinstalla anche se la versione è uguale (richiesta dall'operatore)
}

type heartbeatResp struct {
	Jobs         []Job         `json:"jobs"`
	InventoryNow bool          `json:"inventory_now,omitempty"` // l'operatore chiede subito l'inventario completo
	Cancel       []int         `json:"cancel,omitempty"`        // job da interrompere su richiesta dell'operatore
	Update       *UpdateInfo   `json:"update,omitempty"`
	Fast         bool          `json:"fast,omitempty"`      // console aperta sul file manager / task manager: poll rapido
	Watch        bool          `json:"watch,omitempty"`     // la console guarda i processi: allega l'elenco ai heartbeat
	Chat         *chatResp     `json:"chat,omitempty"`      // messaggi dell'operatore e conferme di quelli dell'utente
	Tunnel       *TunnelOffer  `json:"tunnel,omitempty"`    // la console chiede di aprire un tunnel verso una porta locale
	Deploy       []deployTask  `json:"deploy,omitempty"`    // sonda: PC su cui installare l'agent (richiesta dell'amministratore)
	Probe        *probeCfg     `json:"probe,omitempty"`     // sonda di rete: elenco apparati da controllare (solo se diverso da quello in uso)
	Uninstall    *UninstallReq `json:"uninstall,omitempty"` // l'amministratore ha rimosso il device: disinstalla l'agent
	TrayMode     string        `json:"tray_mode,omitempty"` // "on" | "off": icona e chat decise dalla console (prevale su config.json)
}

var lastUpdateTry time.Time

// Tentativi di auto-update: dopo un errore (server in aggiornamento, rete, download troncato…) si riprova con attese crescenti
// 1, 2, 5, 10, 30, 60 minuti, non più «un tentativo all'ora» per sempre; l'attesa si azzera quando il server pubblica un'altra versione.
var (
	updFails   int
	updNextTry time.Time
	updKey     string
	swappedTo  string    // versione già scritta su disco ma non ancora in esecuzione (riavvio non avvenuto)
	swapAt     time.Time // quando è stato sostituito il file
	restartTry time.Time
	restartN   int
)

var updSteps = []time.Duration{time.Minute, 2 * time.Minute, 5 * time.Minute, 10 * time.Minute, 30 * time.Minute, time.Hour}

func updDelay(fails int) time.Duration {
	if fails < 1 {
		return 0
	}
	if fails > len(updSteps) {
		fails = len(updSteps)
	}
	return updSteps[fails-1]
}

// updFail registra un tentativo fallito e fissa il prossimo.
func updFail() {
	updFails++
	updNextTry = time.Now().Add(updDelay(updFails))
}

// retryPendingRestart: il file nuovo è già al suo posto ma il processo in esecuzione è ancora il vecchio (il riavvio non è
// partito o non è riuscito). A ogni heartbeat, al massimo una volta al minuto, si ritenta il riavvio con metodi sempre più decisi.
func retryPendingRestart(log service.Logger) {
	if swappedTo == "" || swappedTo == AgentVersion || service.Interactive() {
		return
	}
	if jobsRunning() > 0 && time.Since(swapAt) < 20*time.Minute {
		return
	}
	if !restartTry.IsZero() && time.Since(restartTry) < time.Minute {
		return
	}
	restartTry = time.Now()
	restartN++
	updNote = time.Now().UTC().Format("2006-01-02 15:04") + " update " + swappedTo + ": file sostituito, riavvio in corso (tentativo " + strconv.Itoa(restartN) + ")"
	_ = log.Warningf("%s", updNote)
	if restartN >= 3 {
		restartHard()
		return
	}
	restartSelf()
}

var pendingForce *UpdateInfo
var deferSince time.Time // da quando un update attende la fine dei job

// updNote: ultimo esito/motivo dell'auto-update, riportato nell'inventario (visibile in console).
var updNote string

func updNoteF(log service.Logger, isErr bool, format string, a ...any) {
	msg := fmt.Sprintf(format, a...)
	updNote = time.Now().UTC().Format("2006-01-02 15:04") + " " + msg
	if isErr {
		_ = log.Errorf("%s", msg)
	} else {
		_ = log.Warningf("%s", msg)
	}
}

// selfUpdate scarica il nuovo binario, ne verifica SHA-256 e firma HMAC, lo
// sostituisce (Windows permette di rinominare un exe in esecuzione) e riavvia il
// servizio. Richiede job_signing_key: senza firma l'aggiornamento è RIFIUTATO.
// Al massimo un tentativo all'ora, per evitare loop se qualcosa non torna.
func selfUpdate(cfg *Config, st State, u *UpdateInfo, log service.Logger) {
	if u == nil || (u.Version == AgentVersion && !u.Force) {
		return
	}
	if cfg.JobSigningKey == "" {
		updNoteF(log, false, "update %s ignorato: job_signing_key non configurata", u.Version)
		return
	}
	if k := u.Version + "|" + u.SHA256; k != updKey { // altra versione pubblicata: si riparte da zero
		updKey, updFails, updNextTry = k, 0, time.Time{}
	}
	if swappedTo == u.Version && !u.Force {
		return // già sostituito: se ne occupa retryPendingRestart
	}
	if !u.Force && time.Now().Before(updNextTry) {
		updNote = time.Now().UTC().Format("2006-01-02 15:04") + " update " + u.Version + " in attesa: nuovo tentativo alle " + updNextTry.UTC().Format("15:04") + " UTC (dopo " + strconv.Itoa(updFails) + " errori)"
		return
	}
	lastUpdateTry = time.Now()
	mac := hmac.New(sha256.New, []byte(cfg.JobSigningKey))
	fmt.Fprintf(mac, "update\n%s\n%s", u.Version, u.SHA256)
	if !hmac.Equal([]byte(hex.EncodeToString(mac.Sum(nil))), []byte(u.Sig)) {
		updNoteF(log, true, "update %s: firma non valida, RIFIUTATO", u.Version)
		updFail()
		return
	}
	exe, err := os.Executable()
	if err != nil {
		updNoteF(log, false, "update: %v", err)
		updFail()
		return
	}
	req, _ := http.NewRequest(http.MethodGet, cfg.ServerURL+"?action=agent_bin&plat="+platTag(), nil)
	req.Header.Set("X-Device-Key", st.APIKey)
	resp, err := (&http.Client{Timeout: 5 * time.Minute}).Do(req)
	if err != nil {
		updNoteF(log, false, "update: download: %v", err)
		updFail()
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		updNoteF(log, false, "update: download HTTP %d", resp.StatusCode)
		updFail()
		return
	}
	newPath := exe + ".new"
	f, err := os.OpenFile(newPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o755)
	if err != nil {
		updNoteF(log, false, "update: %v", err)
		updFail()
		return
	}
	h := sha256.New()
	_, err = io.Copy(io.MultiWriter(f, h), io.LimitReader(resp.Body, 256<<20))
	f.Close()
	if err != nil || !strings.EqualFold(hex.EncodeToString(h.Sum(nil)), u.SHA256) {
		_ = os.Remove(newPath)
		updNoteF(log, true, "update %s: hash non corrispondente o download incompleto, RIFIUTATO", u.Version)
		updFail()
		return
	}
	oldPath := exe + ".old"
	_ = os.Remove(oldPath)
	if err := os.Rename(exe, oldPath); err != nil {
		_ = os.Remove(newPath)
		updNoteF(log, false, "update: rename: %v", err)
		updFail()
		return
	}
	if err := os.Rename(newPath, exe); err != nil {
		_ = os.Rename(oldPath, exe) // rollback
		updNoteF(log, true, "update: sostituzione fallita, rollback: %v", err)
		updFail()
		return
	}
	updFails, updNextTry = 0, time.Time{}
	swappedTo, swapAt, restartN, restartTry = u.Version, time.Now(), 0, time.Now()
	_ = log.Infof("update %s -> %s installato, riavvio servizio", AgentVersion, u.Version)
	if !service.Interactive() {
		restartSelf()
	}
}

// gatherInventory esegue invScript e restituisce la mappa risultante, con un
// fallback minimale se PowerShell/CIM non è disponibile.
func gatherInventory() map[string]any {
	inv := map[string]any{
		"agent_version": AgentVersion,
		"collected_at":  time.Now().UTC().Format(time.RFC3339),
		"jobs_running":  jobsRunning(),
		"platform":      platTag(),
	}
	if updNote != "" {
		inv["update_note"] = updNote
	}
	defer addSessionInfo(inv)
	if parsed, err := platInventory(); err == nil {
		for k, v := range parsed {
			inv[k] = v
		}
	} else {
		host, _ := os.Hostname()
		inv["hostname"] = host
		inv["os"] = runtime.GOOS
		inv["cpu"] = runtime.NumCPU()
		inv["inventory_error"] = "raccolta inventario fallita: " + err.Error()
	}
	return inv
}

// jobSignature calcola l'HMAC-SHA256 canonico di un job.
// Canonico = "<id>\n<timeout>\n<script>" così l'ordine dei campi non conta.
func jobSignature(key string, id, timeout int, script string) string {
	mac := hmac.New(sha256.New, []byte(key))
	fmt.Fprintf(mac, "%d\n%d\n%s", id, timeout, script)
	return hex.EncodeToString(mac.Sum(nil))
}

// ---- inventario completo --------------------------------------------------

var lastFullInv time.Time // in memoria: al riavvio del servizio si rifà (accettabile)

// maybeFullInventory esegue e invia l'inventario completo se è trascorso
// l'intervallo configurato (o al primo giro dopo l'avvio).
func maybeFullInventory(cfg *Config, st State, log service.Logger) {
	if cfg.FullInventoryHour < 0 {
		return // disattivato
	}
	if !lastFullInv.IsZero() && time.Since(lastFullInv) < time.Duration(cfg.FullInventoryHour)*time.Hour {
		return
	}
	go collectFullInventory(cfg, st, log)
}

var invBusy int32

// collectFullInventory raccoglie e invia l'inventario completo (un solo giro alla volta).
func collectFullInventory(cfg *Config, st State, log service.Logger) {
	if !atomic.CompareAndSwapInt32(&invBusy, 0, 1) {
		return
	}
	defer atomic.StoreInt32(&invBusy, 0)
	_ = log.Infof("inventario completo: raccolta in corso")
	payload, err := platFullInventory()
	if err != nil {
		_ = log.Warningf("inventario completo: raccolta fallita: %v", err)
		return
	}
	if err := postJSON(cfg.ServerURL+"?action=inventory", st.APIKey, map[string]any{"full": payload}, nil); err != nil {
		_ = log.Warningf("inventario completo: invio fallito: %v", err)
		return
	}
	lastFullInv = time.Now()
	_ = log.Infof("inventario completo: inviato")
}

// enroll garantisce device_id + api_key, arruolando se mancano.
func enroll(cfg *Config) (State, error) {
	st := loadState()
	if st.APIKey != "" {
		return st, nil
	}
	host, _ := os.Hostname()
	var out struct {
		DeviceID int    `json:"device_id"`
		APIKey   string `json:"api_key"`
	}
	in := map[string]string{"enroll_token": cfg.EnrollToken, "hostname": host, "os": runtime.GOOS, "site": cfg.Site}
	if err := postJSON(cfg.ServerURL+"?action=enroll", "", in, &out); err != nil {
		return st, fmt.Errorf("enroll fallito: %w", err)
	}
	st = State{DeviceID: out.DeviceID, APIKey: out.APIKey}
	if err := saveState(st); err != nil {
		return st, fmt.Errorf("salvataggio stato fallito: %w", err)
	}
	return st, nil
}

// ---- esecuzione PowerShell ------------------------------------------------

type runResult struct {
	ExitCode int
	Stdout   string
	Stderr   string
	Duration float64
}

func runScript(script string, timeoutSec int, jobID int) runResult {
	if timeoutSec <= 0 {
		timeoutSec = 300
	}
	base, stop := context.WithCancel(context.Background())
	defer stop()
	if jobID > 0 {
		setCancel(jobID, stop)
	}
	ctx, cancel := context.WithTimeout(base, time.Duration(timeoutSec)*time.Second)
	defer cancel()

	cmd, cleanup := platCommand(ctx, script)
	defer cleanup()
	// alla cancellazione/timeout termina l'intero albero di processi
	cmd.Cancel = func() error { return platKill(cmd) }
	cmd.WaitDelay = 10 * time.Second // non restare appesi su pipe tenute aperte dai processi figli

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	start := time.Now()
	err := cmd.Run()
	dur := time.Since(start).Seconds()

	res := runResult{Stdout: stdout.String(), Stderr: stderr.String(), Duration: dur}
	switch {
	case base.Err() != nil:
		res.ExitCode = -4
		res.Stderr += "\n[agent] job interrotto dall'operatore"
	case ctx.Err() == context.DeadlineExceeded:
		res.ExitCode = -2
		res.Stderr += fmt.Sprintf("\n[agent] timeout dopo %ds", timeoutSec)
	case err == nil:
		res.ExitCode = 0
	default:
		if ee, ok := err.(*exec.ExitError); ok {
			res.ExitCode = ee.ExitCode()
		} else {
			res.ExitCode = -1
			res.Stderr += "\n[agent] avvio fallito: " + err.Error()
		}
	}
	return res
}

// ---- ciclo principale -----------------------------------------------------

// ---- esecuzione job concorrente -------------------------------------------

var (
	jobMu   sync.Mutex
	running = map[int]bool{}
	cancels = map[int]context.CancelFunc{}
	jobSem  = make(chan struct{}, 4) // max 4 PowerShell in parallelo
)

func setCancel(id int, f context.CancelFunc) { jobMu.Lock(); cancels[id] = f; jobMu.Unlock() }
func cancelJob(id int) bool {
	jobMu.Lock()
	f := cancels[id]
	jobMu.Unlock()
	if f == nil {
		return false
	}
	f()
	return true
}

func isRunning(id int) bool { jobMu.Lock(); defer jobMu.Unlock(); return running[id] }

func startJob(id int) bool {
	jobMu.Lock()
	defer jobMu.Unlock()
	if running[id] {
		return false
	}
	running[id] = true
	return true
}
func endJob(id int)    { jobMu.Lock(); delete(running, id); delete(cancels, id); jobMu.Unlock() }
func jobsRunning() int { jobMu.Lock(); defer jobMu.Unlock(); return len(running) }

// Poll rapido: finché la console ha il file manager aperto il server risponde fast=true e l'agent
// interroga ogni pochi secondi con heartbeat leggeri (senza inventario).
var (
	fastUntil   time.Time
	lastInvSent time.Time
	lastTick    time.Time
	badKeyCount int // heartbeat consecutivi respinti con "invalid device key"
)

const fastWait = 2 * time.Second

var watchUntil time.Time

func watchActive() bool { return time.Now().Before(watchUntil) }

func fastActive() bool {
	return time.Now().Before(fastUntil) || time.Now().UnixNano() < trayFast.Load()
}

// wakeInterval: ogni quanto l'agent si collega (heartbeat leggero) tra un completo e l'altro.
func wakeInterval(cfg *Config) time.Duration {
	poll := time.Duration(cfg.PollSeconds) * time.Second
	if cfg.WakeSeconds != nil {
		if w := *cfg.WakeSeconds; w <= 0 {
			return poll
		} else if d := time.Duration(w) * time.Second; d < poll {
			return d
		}
		return poll
	}
	if poll > 15*time.Second {
		return 15 * time.Second
	}
	return poll
}

func tick(cfg *Config, st State, log service.Logger) {
	var hb heartbeatResp
	var in map[string]any
	// completo ogni poll_seconds; con file/task manager aperti solo ogni 10 minuti (la raccolta dell'inventario
	// blocca l'agent per secondi: è ciò che rendeva lento il file manager); altrimenti leggero.
	sinceInv := time.Since(lastInvSent)
	full := sinceInv >= time.Duration(cfg.PollSeconds)*time.Second-time.Second
	if fastActive() && sinceInv < 10*time.Minute {
		full = false
	}
	if !full {
		in = map[string]any{"light": true}
		if watchActive() && strings.ToLower(cfg.TmMode) != "off" {
			in["procs"] = tmSample()
		} else if fastActive() {
			in["wait"] = 20 // long-poll: il server risponde appena c'è un job, senza attendere il giro successivo
			if time.Now().UnixNano() < trayFast.Load() {
				in["wait"] = 3 // chat aperta: i messaggi scritti dall'utente non devono attendere la fine di un long-poll lungo
			}
		}
	} else {
		in = map[string]any{"inventory": gatherInventory()}
		lastInvSent = time.Now()
	}
	if !full {
		in["sess"] = sessionSnapshot() // l'inventario completo può mancare per minuti (tunnel, file manager): lo stato sessione no
	}
	if trayOn(cfg) {
		in["chat"] = chatPrepare()
	}
	if m := trayLocalPending(); m != "" {
		in["tray_local"] = m // scelta fatta sul PC con tray-config: il server la adotta
	}
	if pv := probeVer(); pv != "" {
		in["probe_ver"] = pv
		if pk := probePubB64(); pk != "" {
			in["probe_pub"] = pk
		}
	}
	if err := postJSON(cfg.ServerURL+"?action=heartbeat", st.APIKey, in, &hb); err != nil {
		_ = log.Warningf("heartbeat: %v", err)
		if strings.Contains(err.Error(), "invalid device key") {
			badKeyCount++
		}
		return
	}
	badKeyCount = 0
	trayApply(cfg, hb.TrayMode, log)
	if trayOn(cfg) {
		chatHandle(hb.Chat)
		go chatFetchImgs(cfg.ServerURL, st.APIKey) // immagini inviate dall'assistenza (no-op se non ce ne sono)
	}
	if hb.Watch {
		if !watchActive() {
			tmSample() // campione di partenza: il successivo darà le CPU % reali
		}
		watchUntil = time.Now().Add(15 * time.Second)
	} else {
		watchUntil = time.Time{}
	}
	if hb.Fast {
		fastUntil = time.Now().Add(90 * time.Second)
	} else {
		fastUntil = time.Time{}
	}
	probeApply(cfg, st, hb.Probe, log)
	deployHandle(hb.Deploy, log)
	if hb.Uninstall != nil {
		uninstallSelf(cfg, st, hb.Uninstall, log)
	}
	if hb.Tunnel != nil {
		tunnelStart(cfg, st, hb.Tunnel, log)
	}
	for _, job := range hb.Jobs {
		// Verifica firma: se la chiave è configurata, un job non firmato o
		// con firma errata viene RIFIUTATO senza essere eseguito.
		if cfg.JobSigningKey != "" {
			want := jobSignature(cfg.JobSigningKey, job.ID, job.Timeout, job.Script)
			if !hmac.Equal([]byte(want), []byte(job.Sig)) {
				_ = log.Errorf("job #%d: firma non valida, RIFIUTATO", job.ID)
				_ = postJSON(cfg.ServerURL+"?action=result", st.APIKey, map[string]any{
					"job_id": job.ID, "exit_code": -3,
					"stdout": "", "stderr": "[agent] job rifiutato: firma HMAC non valida", "duration": 0,
				}, nil)
				continue
			}
		}
		// Esecuzione in background: un job lungo (es. scansione Windows Update, anche 10+ minuti)
		// non deve bloccare heartbeat né gli altri job.
		if !startJob(job.ID) {
			continue // già in esecuzione: nessuna doppia esecuzione
		}
		go func(job Job) {
			defer endJob(job.ID)
			jobSem <- struct{}{}
			defer func() { <-jobSem }()
			_ = log.Infof("job #%d: eseguo (%d byte)", job.ID, len(job.Script))
			var r runResult
			if strings.HasPrefix(job.Script, fsPrefix) {
				r = fsExec(cfg, st, job.Script)
			} else if strings.HasPrefix(job.Script, tmPrefix) {
				r = tmExec(cfg, job.Script)
			} else if strings.HasPrefix(job.Script, svcPrefix) {
				r = svcExec(cfg, job.Script)
			} else if strings.HasPrefix(job.Script, diagPrefix) {
				r = diagExec()
			} else {
				r = runScript(job.Script, job.Timeout, job.ID)
			}
			out := map[string]any{
				"job_id": job.ID, "exit_code": r.ExitCode,
				"stdout": r.Stdout, "stderr": r.Stderr, "duration": r.Duration,
			}
			if err := postJSON(cfg.ServerURL+"?action=result", st.APIKey, out, nil); err != nil {
				_ = log.Warningf("result job #%d: %v", job.ID, err)
			} else {
				_ = log.Infof("job #%d: exit=%d (%.2fs)", job.ID, r.ExitCode, r.Duration)
			}
		}(job)
	}

	// Interruzioni richieste dall'operatore: se il job non è in esecuzione qui (agent riavviato, job perso)
	// lo si chiude comunque con exit -4, così non resta "sent" per sempre.
	for _, id := range hb.Cancel {
		if cancelJob(id) {
			_ = log.Infof("job #%d: interruzione richiesta", id)
			continue
		}
		if isRunning(id) {
			continue // sta per partire: l'interruzione verrà riproposta al prossimo heartbeat
		}
		_ = postJSON(cfg.ServerURL+"?action=result", st.APIKey, map[string]any{
			"job_id": id, "exit_code": -4, "stdout": "",
			"stderr": "[agent] job non in esecuzione su questo agent: chiuso su richiesta dell'operatore", "duration": 0,
		}, nil)
	}

	// L'auto-update riavvia il servizio e ucciderebbe i job in corso: si rimanda a quando sono finiti.
	// Un update forzato non va perso se ci sono job in corso: si conserva e si applica appena l'agent è libero.
	if hb.Update != nil && hb.Update.Force {
		pendingForce = hb.Update
	}
	wantUpd := hb.Update != nil || pendingForce != nil
	if !wantUpd {
		deferSince = time.Time{}
	}
	if jobsRunning() > 0 && wantUpd {
		if deferSince.IsZero() {
			deferSince = time.Now()
		}
		updNote = time.Now().UTC().Format("2006-01-02 15:04") + " update rimandato: job in esecuzione (" + strconv.Itoa(jobsRunning()) + ")"
	}
	// un job che non finisce mai non deve bloccare per sempre l'aggiornamento: dopo 20 minuti si procede comunque
	stuck := wantUpd && !deferSince.IsZero() && time.Since(deferSince) > 20*time.Minute
	if jobsRunning() == 0 || stuck {
		if stuck {
			_ = log.Warningf("update: %d job in esecuzione da oltre 20 minuti, si procede comunque", jobsRunning())
		}
		u := hb.Update
		if pendingForce != nil {
			u, pendingForce = pendingForce, nil
		}
		selfUpdate(cfg, st, u, log)
	}
	retryPendingRestart(log)
	if hb.InventoryNow {
		go collectFullInventory(cfg, st, log) // richiesta dalla console: subito, senza bloccare il ciclo
	} else {
		maybeFullInventory(cfg, st, log)
	}
}

// ---- integrazione servizio (kardianos) ------------------------------------

type program struct {
	log  service.Logger
	stop chan struct{}
}

func (p *program) Start(s service.Service) error {
	p.stop = make(chan struct{})
	go p.run()
	return nil
}

func (p *program) run() {
	cfg, err := loadConfig()
	if err != nil {
		_ = p.log.Errorf("config: %v", err)
		return
	}
	for uninstalling() { // disinstallazione già confermata ma non portata a termine: niente arruolamento, solo nuovi tentativi
		uninstallRetry(p.log)
		select {
		case <-p.stop:
			return
		case <-time.After(15 * time.Second):
		}
	}
	st, ok := p.ensureEnrolled(cfg)
	if !ok {
		return
	}
	if exe, e := os.Executable(); e == nil {
		_ = os.Remove(exe + ".old") // residuo di un auto-update precedente
	}
	_ = p.log.Infof("agent %s avviato, device #%d, poll %ds", AgentVersion, st.DeviceID, cfg.PollSeconds)
	go tunnelAutoRegister(cfg.ServerURL, p.log) // il «un clic» del tunnel funziona da solo su questo PC
	go trayStart(cfg, st, p.log)                // supervisore delle tray nelle sessioni: mai sul percorso di avvio dell'agent

	tick(cfg, st, p.log) // primo giro subito
	for {
		wait := wakeInterval(cfg)
		if fastActive() {
			wait = fastWait
			if !watchActive() {
				wait = 300 * time.Millisecond // il long-poll del server fa da pausa
			}
		}
		if d := time.Since(lastTick); wait > 0 && fastActive() && d < time.Second { // mai più di un giro al secondo (server senza long-poll)
			if min := time.Second - d; min > wait {
				wait = min
			}
		}
		select {
		case <-p.stop:
			return
		case <-chatWake:
			lastTick = time.Now()
			tick(cfg, st, p.log)
		case <-time.After(wait):
			lastTick = time.Now()
			tick(cfg, st, p.log)
			if badKeyCount >= 3 && uninstalling() { // device già cancellato dal server per la disinstallazione: non si riarruola
				badKeyCount = 0
				uninstallRetry(p.log)
			}
			if badKeyCount >= 3 { // il server non riconosce più la chiave (database sostituito/ripristinato, device eliminato): si arruola di nuovo
				_ = p.log.Warningf("chiave device non riconosciuta dal server per %d volte: riarruolamento", badKeyCount)
				badKeyCount = 0
				_ = os.Remove(statePath())
				if st, ok = p.ensureEnrolled(cfg); !ok {
					return
				}
				_ = p.log.Infof("riarruolato come device #%d", st.DeviceID)
			}
		}
	}
}

// ensureEnrolled arruola (con retry e attesa crescente) finché non riesce; false se il servizio viene fermato.
func (p *program) ensureEnrolled(cfg *Config) (State, bool) {
	// arruolamento con retry (rete/DNS non pronti all'avvio, server temporaneamente giù, token da correggere):
	// l'agent non si ferma più al primo errore e scrive l'ultimo motivo in enroll-status.txt nella cartella dati.
	var st State
	for wait := 15 * time.Second; ; {
		var err error
		st, err = enroll(cfg)
		if err == nil {
			_ = os.Remove(filepath.Join(dataDir(), "enroll-status.txt"))
			return st, true
		}
		_ = p.log.Errorf("%v (nuovo tentativo tra %s)", err, wait)
		_ = os.WriteFile(filepath.Join(dataDir(), "enroll-status.txt"),
			[]byte(time.Now().Format(time.RFC3339)+" "+err.Error()+"\r\nURL: "+cfg.ServerURL+"\r\nNuovo tentativo tra "+wait.String()+"\r\n"), 0o644)
		select {
		case <-p.stop:
			return State{}, false
		case <-time.After(wait):
		}
		if wait < 5*time.Minute {
			wait *= 2
		}
	}
}

func (p *program) Stop(s service.Service) error {
	close(p.stop)
	return nil
}

func main() {
	if len(os.Args) > 1 { // modi che non toccano il servizio: partono subito
		switch os.Args[1] {
		case "tray": // l'icona nella systray, lanciata dal servizio nella sessione dell'utente
			os.Exit(trayMain())
		case "tray-config": // mostra/nasconde l'icona su questo PC (amministratore)
			os.Exit(trayConfigMain(os.Args[2:]))
		}
	}
	svcConfig := &service.Config{
		Name:        "myrmm-agent",
		DisplayName: "myrmm agent",
		Description: "Agent di gestione remota (polling outbound, payload PowerShell/shell).",
	}
	prg := &program{}
	s, err := service.New(prg, svcConfig)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	logger, err := s.Logger(nil)
	if err != nil { // niente syslog/journal (container, hosting minimale): si logga su stderr invece di non partire
		fmt.Fprintln(os.Stderr, "log di sistema non disponibile:", err)
		logger = service.ConsoleLogger
	}
	prg.log = logger

	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "run": // foreground per debug (log su console)
			prg.log = service.ConsoleLogger
			prg.stop = make(chan struct{})
			prg.run()
			return
		case "tunnel": // helper dell'operatore: porta locale -> relay del server -> device
			os.Exit(tunnelClient(os.Args[2:]))
		case "tunnel-register": // helper dell'operatore: registra il collegamento myrmm-tunnel:// (un clic dalla console)
			os.Exit(tunnelRegisterMain(os.Args[2:]))
		case "tunnel-uri": // lanciato dal sistema quando si apre un collegamento myrmm-tunnel://
			os.Exit(tunnelURIMain(os.Args[2:]))
		case "diag": // diagnostica completa, anche senza servizio in esecuzione
			out := collectDiag()
			fmt.Println(out)
			host, _ := os.Hostname()
			p := filepath.Join(dataDir(), fmt.Sprintf("diag-%s-%s.txt", host, time.Now().Format("20060102-150405")))
			if err := os.WriteFile(p, []byte(out), 0o644); err == nil {
				fmt.Println("\nSalvata in:", p)
			}
			return
		default: // install | uninstall | start | stop | restart
			if err := service.Control(s, os.Args[1]); err != nil {
				fmt.Fprintf(os.Stderr, "comando '%s' fallito: %v\n", os.Args[1], err)
				os.Exit(1)
			}
			fmt.Printf("ok: %s\n", os.Args[1])
			return
		}
	}

	if err := s.Run(); err != nil {
		_ = logger.Error(err)
	}
}
