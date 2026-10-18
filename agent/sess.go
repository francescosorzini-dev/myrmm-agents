package main

import (
	"os"
	"strings"
)

// Sessioni utente: chi è collegato e in che stato (attiva, bloccata, disconnessa, inattiva).
// L'elenco lo produce platSessions() (Windows: API WTS; Linux: loginctl; macOS: utente della console).

type sessInfo struct {
	User  string `json:"user"`
	State string `json:"state"` // attiva | bloccata | disconnessa | inattiva
	Via   string `json:"via"`   // console | rdp | ssh | tty | remota
}

var sessRank = map[string]int{"attiva": 4, "bloccata": 3, "inattiva": 2, "disconnessa": 1}

// sessionSnapshot: stato sessione corrente (stesse chiavi dell'inventario). Costa poco: va in ogni heartbeat,
// così lo stato resta aggiornato anche quando l'inventario completo non viene inviato (tunnel, file manager, chat).
func sessionSnapshot() map[string]any {
	list := platSessions()
	var best *sessInfo
	for i := range list {
		if list[i].User == "" {
			continue
		}
		// a parità di stato si preferisce la sessione sulla console
		if best == nil || sessRank[list[i].State] > sessRank[best.State] || (sessRank[list[i].State] == sessRank[best.State] && list[i].Via == "console" && best.Via != "console") {
			best = &list[i]
		}
	}
	if best == nil {
		return map[string]any{"session_state": "nessuna", "session_user": "", "sessions": []sessInfo{}}
	}
	return map[string]any{"session_state": best.State, "session_user": best.User, "sessions": list}
}

// addSessionInfo aggiunge all'inventario session_state / session_user / sessions.
func addSessionInfo(inv map[string]any) {
	snap := sessionSnapshot()
	for k, v := range snap {
		inv[k] = v
	}
	if s, _ := inv["logged_user"].(string); strings.TrimSpace(s) == "" { // server/RDP senza utente sulla console
		if u, _ := snap["session_user"].(string); u != "" {
			inv["logged_user"] = u
		}
	}
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }
