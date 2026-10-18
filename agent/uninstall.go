package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/kardianos/service"
)

// UninstallReq: richiesta di auto-disinstallazione, firmata dal server con la stessa chiave dei job.
// Arriva solo se un amministratore ha scelto «Rimuovi e disinstalla» per questo device: un agent che il server
// semplicemente non riconosce NON si disinstalla mai (si riarruola).
type UninstallReq struct {
	Req int64  `json:"req"` // istante della richiesta (fa parte della firma)
	Sig string `json:"sig"` // HMAC("uninstall\n<device_id>\n<req>")
}

var lastUninstallTry time.Time

// uninstallFlag: scritto dopo la conferma al server. Finché esiste, l'agent NON si riarruola (il server ha già cancellato il device)
// e ritenta la rimozione: una disinstallazione fallita a metà non deve far «risorgere» il device.
func uninstallFlag() string { return filepath.Join(dataDir(), "uninstalling.flag") }

func uninstalling() bool { _, err := os.Stat(uninstallFlag()); return err == nil }

// uninstallRetry: rilancia la rimozione (al massimo una volta al minuto).
func uninstallRetry(log service.Logger) {
	if !lastUninstallTry.IsZero() && time.Since(lastUninstallTry) < time.Minute {
		return
	}
	lastUninstallTry = time.Now()
	exe, err := os.Executable()
	if err != nil {
		return
	}
	_ = log.Warningf("disinstallazione già confermata ma l'agent è ancora attivo: nuovo tentativo di rimozione")
	platUninstall(exe, dataDir())
}

func uninstallSelf(cfg *Config, st State, u *UninstallReq, log service.Logger) {
	if cfg.JobSigningKey == "" {
		updNoteF(log, false, "disinstallazione ignorata: job_signing_key non configurata")
		return
	}
	mac := hmac.New(sha256.New, []byte(cfg.JobSigningKey))
	fmt.Fprintf(mac, "uninstall\n%d\n%d", st.DeviceID, u.Req)
	if !hmac.Equal([]byte(hex.EncodeToString(mac.Sum(nil))), []byte(u.Sig)) {
		updNoteF(log, true, "disinstallazione: firma non valida, RIFIUTATA")
		return
	}
	if service.Interactive() {
		_ = log.Warningf("disinstallazione richiesta ma l'agent gira in primo piano (run): ignorata")
		return
	}
	if !lastUninstallTry.IsZero() && time.Since(lastUninstallTry) < time.Minute {
		return
	}
	lastUninstallTry = time.Now()
	// conferma al server: da qui il device sparisce dall'elenco. Se la conferma non passa, non si tocca nulla.
	if err := postJSON(cfg.ServerURL+"?action=uninstall_ack", st.APIKey, map[string]any{"req": u.Req}, nil); err != nil {
		_ = log.Warningf("disinstallazione: conferma al server fallita (%v), riprovo al prossimo contatto", err)
		return
	}
	_ = log.Infof("disinstallazione confermata dal server: rimozione di servizio, binario e dati")
	_ = os.WriteFile(uninstallFlag(), []byte(time.Now().UTC().Format(time.RFC3339)), 0o644)
	exe, err := os.Executable()
	if err != nil {
		_ = log.Errorf("disinstallazione: %v", err)
		return
	}
	platUninstall(exe, dataDir())
}
