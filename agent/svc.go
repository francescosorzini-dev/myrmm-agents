package main

import (
	"encoding/json"
	"strings"
	"time"
)

// Gestione servizi dalla console (elenco in tempo reale, avvio/arresto/riavvio, tipo di avvio).
// Le richieste arrivano come job con prefisso svcPrefix; la policy locale è tm_mode (come il task manager).
const svcPrefix = "#myrmm-svc\n"

type svcOp struct {
	Op   string `json:"op"`   // list | start | stop | restart | startup
	Name string `json:"name"` // nome del servizio
	Mode string `json:"mode"` // startup: auto | delayed | manual | disabled
}

type svcItem struct {
	N  string `json:"n"`            // nome
	D  string `json:"d,omitempty"`  // descrizione / nome visualizzato
	S  string `json:"s"`            // running | stopped | starting | stopping | paused | other
	St string `json:"st,omitempty"` // avvio: auto | delayed | manual | disabled | static (...)
	P  int    `json:"p,omitempty"`  // PID (0 se fermo)
}

// svcProtected: il servizio dell'agent non si tocca dalla console (taglierebbe il ramo su cui si è seduti).
func svcProtected(name string) bool {
	return strings.Contains(strings.ToLower(name), "myrmm-agent")
}

func svcExec(cfg *Config, script string) runResult {
	var o svcOp
	if err := json.Unmarshal([]byte(strings.TrimPrefix(script, svcPrefix)), &o); err != nil {
		return fsFail("richiesta non valida: %v", err)
	}
	mode := strings.ToLower(cfg.TmMode)
	if mode == "off" {
		return fsFail("gestione servizi disattivata su questo device (tm_mode=off nella config dell'agent)")
	}
	if o.Op != "list" && mode == "ro" {
		return fsFail("il device è in sola lettura (tm_mode=ro nella config dell'agent)")
	}
	switch o.Op {
	case "list":
		start := time.Now()
		items, err := platSvcList()
		if err != nil {
			return fsFail("elenco servizi: %v", err)
		}
		return fsOK(map[string]any{"items": items, "ms": time.Since(start).Milliseconds()})
	case "start", "stop", "restart", "startup":
		if o.Name == "" || len(o.Name) > 256 || strings.ContainsAny(o.Name, "\x00\r\n") {
			return fsFail("nome servizio non valido")
		}
		if svcProtected(o.Name) {
			return fsFail("il servizio dell'agent non si gestisce da qui")
		}
		st, err := platSvcControl(o.Op, o.Name, o.Mode)
		if err != nil {
			return fsFail("%s %s: %v", o.Op, o.Name, err)
		}
		return fsOK(map[string]any{"name": o.Name, "state": st})
	}
	return fsFail("operazione non valida")
}
