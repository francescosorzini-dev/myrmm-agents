//go:build windows

package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"unicode/utf16"
	"unsafe"

	"github.com/kardianos/service"
	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"

	"myrmm-agent/tray"
)

// Dalla 1.67.0 la tray non è più un secondo eseguibile con un'attività pianificata: è il sottocomando «tray» dell'agent stesso
// (myrmm-agent.exe tray). Il servizio la avvia nella sessione di ogni utente collegato, con il token di quell'utente (WTSQueryUserToken +
// CreateProcessAsUser), e la ferma se la console la disattiva. Nessun file dell'agent serve all'utente: porta locale e chiave della
// sessione arrivano alla tray come variabili d'ambiente del processo (la cartella dati è riservata a SYSTEM e agli amministratori).

func trayOn(cfg *Config) bool { return !strings.EqualFold(cfg.TrayMode, "off") }

var (
	traySecret   atomic.Value
	trayPortV    atomic.Int32
	trayLocalMu  sync.Mutex
	trayLocalSet string // scelta fatta in locale (tray-config) non ancora confermata dal server
)

func traySecretFor(apiKey string) { traySecret.Store(sha256.Sum256([]byte("myrmm-tray|" + apiKey))) }

// trayKey: chiave della sessione, ricalcolabile dal servizio anche dopo un riavvio (le tray già in corso restano valide).
func trayKey(sid uint32, user string) string {
	sec, _ := traySecret.Load().([32]byte)
	m := hmac.New(sha256.New, sec[:])
	fmt.Fprintf(m, "%d|%s", sid, strings.ToLower(user))
	return fmt.Sprintf("%d:%s", sid, hex.EncodeToString(m.Sum(nil)[:16]))
}

func wtsUserOf(sid uint32) string {
	u := wtsString(sid, wtsUserName)
	if u == "" {
		return ""
	}
	if d := wtsString(sid, wtsDomainName); d != "" {
		return d + `\` + u
	}
	return u
}

func trayResolve(key string) (string, bool) {
	i := strings.IndexByte(key, ':')
	if i <= 0 {
		return "", false
	}
	n, err := strconv.ParseUint(key[:i], 10, 32)
	if err != nil {
		return "", false
	}
	sid := uint32(n)
	user := wtsUserOf(sid)
	if user == "" {
		return "", false
	}
	if !hmac.Equal([]byte(trayKey(sid, user)), []byte(key)) {
		return "", false
	}
	return user, true
}

// trayApply: la console ha scelto «on» o «off» per questo device: si ricorda la scelta (file tray.mode, prevale su config.json)
// e le tray escono o ripartono entro pochi secondi, senza riavviare il servizio.
func trayApply(cfg *Config, mode string, log service.Logger) {
	m := strings.ToLower(strings.TrimSpace(mode))
	if m != "on" && m != "off" {
		return
	}
	trayLocalMu.Lock()
	if trayLocalSet != "" { // una scelta locale non ancora arrivata al server prevale; quando il server la conferma si torna a seguirlo
		if m == trayLocalSet {
			trayLocalSet = ""
		}
		trayLocalMu.Unlock()
		return
	}
	trayLocalMu.Unlock()
	setTrayMode(cfg, m, log, "su richiesta della console")
}

func setTrayMode(cfg *Config, m string, log service.Logger, why string) {
	cur := "on"
	if !trayOn(cfg) {
		cur = "off"
	}
	if m == cur {
		return
	}
	if err := os.WriteFile(filepath.Join(dataDir(), "tray.mode"), []byte(m), 0o644); err != nil {
		_ = log.Warningf("tray: %v", err)
	}
	cfg.TrayMode = m
	chatDisabled.Store(m == "off")
	_ = log.Infof("tray: %s %s", map[string]string{"on": "attivata", "off": "disattivata"}[m], why)
}

// trayLocalChange: scelta fatta sul PC con «myrmm-agent.exe tray-config»: il servizio la vede nel file e la comunica alla console
// nel prossimo heartbeat (campo tray_local), così il server resta allineato.
func trayLocalPending() string {
	trayLocalMu.Lock()
	defer trayLocalMu.Unlock()
	return trayLocalSet
}

// ---- elenco sessioni -----------------------------------------------------------------------------

type wtsSess struct {
	ID    uint32
	State uint32
	User  string
}

func wtsSessions() []wtsSess {
	var p *windows.WTS_SESSION_INFO
	var n uint32
	if err := windows.WTSEnumerateSessions(0, 0, 1, &p, &n); err != nil || p == nil {
		return nil
	}
	defer windows.WTSFreeMemory(uintptr(unsafe.Pointer(p)))
	items := (*[1 << 10]windows.WTS_SESSION_INFO)(unsafe.Pointer(p))[:n:n]
	var out []wtsSess
	for _, it := range items {
		if it.SessionID == 0 {
			continue
		}
		if u := wtsUserOf(it.SessionID); u != "" {
			out = append(out, wtsSess{ID: it.SessionID, State: uint32(it.State), User: u})
		}
	}
	return out
}

// ---- supervisore -----------------------------------------------------------------------------------

type trayProc struct {
	h       windows.Handle
	pid     uint32
	user    string
	started time.Time
	tries   int
	next    time.Time // non rilanciare prima di
	lastErr string
}

var (
	trayMu           sync.Mutex
	trayProcs        = map[uint32]*trayProc{}
	traySince        = time.Now()
	trayLaunch       = traySpawn
	trayListSessions = wtsSessions
)

func (p *trayProc) alive() bool {
	if p.h == 0 {
		return false
	}
	r, _ := windows.WaitForSingleObject(p.h, 0)
	return r == uint32(windows.WAIT_TIMEOUT)
}

func (p *trayProc) kill() {
	if p.h != 0 {
		_ = windows.TerminateProcess(p.h, 0)
		_ = windows.CloseHandle(p.h)
		p.h = 0
	}
}

func envBlock(env []string) *uint16 {
	var b []uint16
	for _, e := range env {
		b = append(b, utf16.Encode([]rune(e))...)
		b = append(b, 0)
	}
	b = append(b, 0)
	return &b[0]
}

// traySpawn avvia «<exe> tray» nella sessione sid con il token dell'utente, sul desktop interattivo e senza finestra di console.
func traySpawn(sid uint32, exe string, extra []string) (windows.Handle, uint32, error) {
	var tok windows.Token
	if err := windows.WTSQueryUserToken(sid, &tok); err != nil {
		return 0, 0, fmt.Errorf("WTSQueryUserToken: %w", err)
	}
	defer tok.Close()
	var ptok windows.Token
	if err := windows.DuplicateTokenEx(tok, windows.MAXIMUM_ALLOWED, nil, windows.SecurityIdentification, windows.TokenPrimary, &ptok); err != nil {
		return 0, 0, fmt.Errorf("DuplicateTokenEx: %w", err)
	}
	defer ptok.Close()
	env, err := ptok.Environ(false)
	if err != nil {
		return 0, 0, fmt.Errorf("ambiente dell'utente: %w", err)
	}
	env = append(env, extra...)
	cmd, _ := windows.UTF16PtrFromString(`"` + exe + `" tray`)
	app, _ := windows.UTF16PtrFromString(exe)
	dir, _ := windows.UTF16PtrFromString(filepath.Dir(exe))
	desk, _ := windows.UTF16PtrFromString(`winsta0\default`)
	si := windows.StartupInfo{Desktop: desk}
	si.Cb = uint32(unsafe.Sizeof(si))
	var pi windows.ProcessInformation
	if err := windows.CreateProcessAsUser(ptok, app, cmd, nil, nil, false, windows.CREATE_UNICODE_ENVIRONMENT|windows.CREATE_NO_WINDOW, envBlock(env), dir, &si, &pi); err != nil {
		return 0, 0, fmt.Errorf("CreateProcessAsUser: %w", err)
	}
	_ = windows.CloseHandle(pi.Thread)
	return pi.Process, pi.ProcessId, nil
}

// traySeenRecently: la tray della sessione ha chiamato l'API locale di recente.
func traySeenRecently(user string, within time.Duration) bool {
	chatMu.Lock()
	defer chatMu.Unlock()
	s := chatSessions[sessKey(user)]
	return s != nil && time.Since(s.last) < within
}

func traySuperviseOnce(cfg *Config, exe string, log service.Logger, now time.Time) {
	// scelta fatta in locale con tray-config: il file cambia, il server viene avvisato nel prossimo heartbeat
	if b, err := os.ReadFile(filepath.Join(dataDir(), "tray.mode")); err == nil {
		if m := strings.ToLower(strings.TrimSpace(string(b))); (m == "on" || m == "off") && m != map[bool]string{true: "on", false: "off"}[trayOn(cfg)] {
			cfg.TrayMode = m
			chatDisabled.Store(m == "off")
			trayLocalMu.Lock()
			trayLocalSet = m
			trayLocalMu.Unlock()
			_ = log.Infof("tray: %s dal configuratore locale", map[string]string{"on": "attivata", "off": "disattivata"}[m])
		}
	}
	trayMu.Lock()
	defer trayMu.Unlock()
	live := map[uint32]wtsSess{}
	if trayOn(cfg) {
		for _, s := range trayListSessions() {
			if s.State == uint32(windows.WTSActive) || s.State == uint32(windows.WTSConnected) {
				live[s.ID] = s
			}
		}
	}
	for sid, p := range trayProcs { // sessioni finite, utente cambiato, tray disattivata: il processo si ferma
		if s, ok := live[sid]; !ok || !strings.EqualFold(s.User, p.user) {
			p.kill()
			delete(trayProcs, sid)
		} else if !p.alive() {
			p.h = 0
		}
	}
	if now.Sub(traySince) < 25*time.Second { // appena partiti: le tray già in corso (avvio precedente dell'agent) si riconnettono da sole
		return
	}
	port := int(trayPortV.Load())
	if port == 0 {
		return
	}
	for sid, s := range live {
		if traySeenRecently(s.User, 30*time.Second) {
			if p := trayProcs[sid]; p != nil {
				p.tries, p.lastErr = 0, ""
			}
			continue
		}
		p := trayProcs[sid]
		if p == nil {
			p = &trayProc{user: s.User}
			trayProcs[sid] = p
		}
		if p.alive() && now.Sub(p.started) < 90*time.Second {
			continue // appena lanciata: si dà il tempo di collegarsi
		}
		if now.Before(p.next) {
			continue
		}
		p.kill()
		h, pid, err := trayLaunch(sid, exe, []string{"MYRMM_TRAY_PORT=" + strconv.Itoa(port), "MYRMM_TRAY_KEY=" + trayKey(sid, s.User), "MYRMM_TRAY_VERSION=" + AgentVersion})
		p.tries++
		p.started = now
		wait := time.Duration(1<<uint(min(p.tries, 6))) * 10 * time.Second // 20 s, 40 s … fino a circa 10 minuti se non si collega mai
		p.next = now.Add(wait)
		if err != nil {
			p.lastErr = err.Error()
			_ = log.Warningf("tray: avvio per %s (sessione %d) fallito: %v", s.User, sid, err)
			continue
		}
		p.h, p.pid, p.lastErr = h, pid, ""
		_ = log.Infof("tray: avviata per %s (sessione %d, pid %d)", s.User, sid, pid)
	}
}

func trayDiag() string {
	trayMu.Lock()
	defer trayMu.Unlock()
	var b strings.Builder
	fmt.Fprintf(&b, "tray: porta locale %d, disattivata=%v\n", trayPortV.Load(), chatDisabled.Load())
	for _, s := range wtsSessions() {
		fmt.Fprintf(&b, "  sessione %d: %s, stato %d", s.ID, s.User, s.State)
		if p := trayProcs[s.ID]; p != nil {
			fmt.Fprintf(&b, ", processo %d vivo=%v tentativi=%d", p.pid, p.alive(), p.tries)
			if p.lastErr != "" {
				fmt.Fprintf(&b, ", ultimo errore: %s", p.lastErr)
			}
		}
		fmt.Fprintf(&b, ", tray collegata di recente: %v\n", traySeenRecently(s.User, 30*time.Second))
	}
	return b.String()
}

// trayStart: avvia l'API locale (sempre: serve anche a dire alle tray «disattivata») e il supervisore delle tray; toglie ciò che
// installavano le versioni fino alla 1.66 (attività pianificata, chiave Run, myrmm-tray.exe, tray.ps1).
func trayStart(cfg *Config, st State, log service.Logger) {
	host, _ := os.Hostname()
	chatMu.Lock()
	chatMeta.Host, chatMeta.Site = host, cfg.Site
	chatMu.Unlock()
	traySecretFor(st.APIKey)
	chatResolve = trayResolve
	chatDisabled.Store(!trayOn(cfg))
	trayPortV.Store(int32(chatServe(cfg)))
	go trayLegacyCleanup(log)
	exe, err := os.Executable()
	if err != nil {
		_ = log.Warningf("tray: %v", err)
		return
	}
	for {
		traySuperviseOnce(cfg, exe, log, time.Now())
		time.Sleep(10 * time.Second)
	}
}

const runKeyPath = `SOFTWARE\Microsoft\Windows\CurrentVersion\Run`

func trayLegacyCleanup(log service.Logger) {
	dir := dataDir()
	mark := filepath.Join(dir, "tray.v2")
	if _, err := os.Stat(mark); err == nil {
		return
	}
	if k, err := registry.OpenKey(registry.LOCAL_MACHINE, runKeyPath, registry.SET_VALUE); err == nil {
		_ = k.DeleteValue("myrmm-tray")
		k.Close()
	}
	const script = `$ErrorActionPreference='SilentlyContinue'
Stop-ScheduledTask -TaskName 'myrmm-tray'; Unregister-ScheduledTask -TaskName 'myrmm-tray' -Confirm:$false
Get-Process -Name 'myrmm-tray' | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {$_.CommandLine -like '*myrmm*tray.ps1*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}`
	_ = psDetached(script)
	for _, f := range []string{"tray.hash", "tray.ps1", "myrmm-tray.exe", "myrmm-tray.exe.new"} {
		_ = os.Remove(filepath.Join(dir, f))
	}
	_ = os.WriteFile(mark, []byte("1"), 0o644)
	_ = log.Infof("tray: rimosse l'attività pianificata e il vecchio eseguibile (ora la tray è un sottocomando dell'agent)")
}

func psq(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

func psDetached(script string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodePowerShell(script))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}

// trayMain: «myrmm-agent.exe tray», lanciato dal servizio nella sessione dell'utente.
func trayMain() int {
	port := os.Getenv("MYRMM_TRAY_PORT")
	key := os.Getenv("MYRMM_TRAY_KEY")
	if port == "" || key == "" {
		fmt.Fprintln(os.Stderr, "la tray la avvia il servizio myrmm-agent: non si lancia a mano")
		return 2
	}
	tray.Main(tray.Options{Base: "http://127.0.0.1:" + port, Key: key, Version: AgentVersion})
	return 0
}

// trayConfigMain: «myrmm-agent.exe tray-config status|show|hide» (da amministratore, anche con uno script dalla console): decide se
// l'icona compare sui PC. La scelta resta in tray.mode, il servizio la applica in pochi secondi e la comunica al server.
func trayConfigMain(args []string) int {
	mode := "status"
	if len(args) > 0 {
		mode = strings.ToLower(args[0])
	}
	f := filepath.Join(dataDir(), "tray.mode")
	cur := "on"
	if c, err := loadConfig(); err == nil && !trayOn(c) {
		cur = "off"
	}
	switch mode {
	case "status":
		fmt.Printf("icona nella systray: %s\n", map[string]string{"on": "visibile (attiva)", "off": "nascosta (disattivata)"}[cur])
		return 0
	case "show", "on":
		mode = "on"
	case "hide", "off":
		mode = "off"
	default:
		fmt.Fprintln(os.Stderr, "uso: myrmm-agent.exe tray-config status|show|hide")
		return 2
	}
	if err := os.WriteFile(f, []byte(mode), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "scrittura di %s fallita (servono i diritti di amministratore): %v\n", f, err)
		return 1
	}
	fmt.Printf("icona nella systray: %s. Il servizio la applica entro 15 secondi e lo comunica alla console.\n", map[string]string{"on": "sarà mostrata", "off": "sarà nascosta"}[mode])
	return 0
}
