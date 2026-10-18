package main

// Gli strumenti MCP: stessi nomi, descrizioni e parametri della versione Python (mcp/myrmm_mcp.py).

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
)

type tool struct {
	name, desc string
	schema     *omap
	run        func(s *server, a *omap) (int, any, error)
	noteAfter  bool // dopo il risultato ricorda che i testi dei device sono dati
}

func tS() *omap { return newMap("type", "string") }
func tI() *omap { return newMap("type", "integer") }
func tB() *omap { return newMap("type", "boolean") }

func obj(req []string, props ...any) *omap {
	r := []any{}
	for _, k := range req {
		r = append(r, k)
	}
	return newMap("type", "object", "properties", newMap(props...), "required", r)
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, _ := x.Float64()
		return f != 0
	case *omap:
		return len(x.keys) > 0
	case []any:
		return len(x) > 0
	}
	return true
}

// toInt: int() di Python su un valore JSON (numeri e testi numerici); altro è un errore.
func toInt(v any) (int, error) {
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return int(i), nil
		}
		f, err := x.Float64()
		if err != nil || math.IsNaN(f) || math.IsInf(f, 0) {
			return 0, fmt.Errorf("numero non valido: %s", x)
		}
		return int(f), nil
	case string:
		i, err := strconv.Atoi(strings.TrimSpace(x))
		if err != nil {
			return 0, fmt.Errorf("numero non valido: %q", x)
		}
		return i, nil
	case bool:
		if x {
			return 1, nil
		}
		return 0, nil
	}
	return 0, fmt.Errorf("numero richiesto")
}

func or(v any, def any) any {
	if v == nil {
		return def
	}
	return v
}

// get restituisce il valore o il predefinito se la chiave manca (una chiave presente con null resta null, come a.get(k, def) di Python).
func get(a *omap, k string, def any) any {
	if v, ok := a.get(k); ok {
		return v
	}
	return def
}

func one(res string, params ...string) func(s *server, a *omap) (int, any, error) {
	return func(s *server, a *omap) (int, any, error) {
		var qs []qp
		for _, k := range params {
			qs = append(qs, qp{k, a.val(k)})
		}
		st, j := s.call(res, "GET", nil, qs...)
		return st, j, nil
	}
}

// waitFor: se il job è in coda, attende fino a 25 secondi l'esito e lo aggiunge come «result».
func waitFor(s *server, a *omap, st int, j any) (int, any, error) {
	m, _ := j.(*omap)
	if st != 200 || m == nil || m.val("status") != "pending" {
		return st, j, nil
	}
	w, err := toInt(get(a, "wait", json.Number("20")))
	if err != nil {
		return 0, nil, err
	}
	if w < 0 {
		w = 0
	}
	if w > 25 {
		w = 25
	}
	if w != 0 {
		st2, r := s.call("job", "GET", nil, qp{"id", m.val("job_id")}, qp{"wait", w})
		if st2 == 200 {
			m.set("result", r)
		}
	}
	return st, j, nil
}

func tools() []tool {
	vars := newMap("type", "object")
	run := func(extra func(a *omap, b *omap)) func(s *server, a *omap) (int, any, error) {
		return func(s *server, a *omap) (int, any, error) {
			b := newMap("device_id", a.val("device_id"))
			extra(a, b)
			b.set("vars", or2(a.val("vars")))
			b.set("dry_run", get(a, "dry_run", true))
			st, j := s.call("run", "POST", b)
			return waitFor(s, a, st, j)
		}
	}
	return []tool{
		{name: "myrmm_guidelines", desc: "Linee guida di myrmm: regole per l'assistente, cosa ha senso per tipo di device, uso dei token. Leggile prima di eseguire qualsiasi cosa.", schema: obj(nil), run: one("guidelines")},
		{name: "myrmm_status", desc: "Mostra chi sono (ruolo, clienti visibili, tipo di scrittura consentita, scadenza del token).", schema: obj(nil), run: one("me")},
		{name: "myrmm_list_sites", desc: "Elenca i clienti visibili e quali sono di collaudo.", schema: obj(nil), run: one("sites")},
		{name: "myrmm_list_devices", desc: "Elenca i device. Filtri: site, q (parte del nome), platform (windows, linux, darwin), online (1 o 0).",
			schema: obj(nil, "site", tS(), "q", tS(), "platform", tS(), "online", tI(), "limit", tI()), run: one("devices", "site", "q", "platform", "online", "limit")},
		{name: "myrmm_get_device", desc: "Scheda di un device: inventario, alert aperti, ultimi job. include: system,hardware,security,software,all.",
			schema: obj([]string{"id"}, "id", tI(), "include", tS()), run: one("device", "id", "include"), noteAfter: true},
		{name: "myrmm_list_alerts", desc: "Alert. status: open (predefinito), resolved, all. Filtri severity (info, warn, crit) e device_id.",
			schema: obj(nil, "status", tS(), "severity", tS(), "device_id", tI(), "limit", tI()), run: one("alerts", "status", "severity", "device_id", "limit")},
		{name: "myrmm_list_scripts", desc: "Script della libreria con piattaforma, etichette e variabili richieste (body=true per il testo). Filtri: tag (una o più etichette separate da virgola, es. \"linux,sicurezza\": servono tutte) e q (parte del nome o della descrizione).",
			schema: obj(nil, "body", tB(), "tag", tS(), "q", tS()), run: func(s *server, a *omap) (int, any, error) {
				var b any
				if truthy(a.val("body")) {
					b = json.Number("1")
				}
				st, j := s.call("scripts", "GET", nil, qp{"body", b}, qp{"tag", a.val("tag")}, qp{"q", a.val("q")})
				return st, j, nil
			}},
		{name: "myrmm_backup_status", desc: "Stato dei backup letto dal software di ogni device.", schema: obj(nil), run: one("backup")},
		{name: "myrmm_run_script", desc: "Esegue uno script di libreria su un device. dry_run è VERO per impostazione predefinita (PowerShell con WhatIf, Linux/macOS con MYRMM_DRYRUN=1: fermano solo i comandi che li rispettano). Sui clienti di collaudo parte subito e attende l'esito; altrove resta in attesa dell'approvazione umana.",
			schema: obj([]string{"device_id", "script_id"}, "device_id", tI(), "script_id", tI(), "vars", vars, "dry_run", tB(), "wait", tI()),
			run:    run(func(a, b *omap) { b.set("script_id", a.val("script_id")) }), noteAfter: true},
		{name: "myrmm_list_drafts", desc: "Elenca le bozze di script (body=true per il testo). Una bozza gira solo sui clienti di collaudo finché una persona non la promuove alla libreria dalla console.",
			schema: obj(nil, "body", tB()), run: func(s *server, a *omap) (int, any, error) {
				var b any
				if truthy(a.val("body")) {
					b = json.Number("1")
				}
				st, j := s.call("drafts", "GET", nil, qp{"body", b})
				return st, j, nil
			}},
		{name: "myrmm_save_draft", desc: "Crea (o, con id, modifica) una bozza di script. platform: windows, unix o any. Richiede un token a scrittura diretta. Non entra in libreria: la promozione la fa una persona.",
			schema: obj([]string{"name", "body"}, "id", tI(), "name", tS(), "description", tS(), "platform", tS(), "timeout", tI(), "body", tS()),
			run: func(s *server, a *omap) (int, any, error) {
				d := newMap()
				for _, k := range []string{"id", "name", "description", "platform", "timeout", "body"} {
					if v := a.val(k); v != nil {
						d.set(k, v)
					}
				}
				st, j := s.call("draft_save", "POST", d)
				return st, j, nil
			}},
		{name: "myrmm_delete_draft", desc: "Elimina una bozza non ancora promossa.", schema: obj([]string{"id"}, "id", tI()),
			run: func(s *server, a *omap) (int, any, error) {
				st, j := s.call("draft_delete", "POST", newMap("id", a.val("id")))
				return st, j, nil
			}},
		{name: "myrmm_run_draft", desc: "Esegue una bozza su un device di un cliente di collaudo (dry_run vero per impostazione predefinita) e attende l'esito.",
			schema: obj([]string{"device_id", "draft_id"}, "device_id", tI(), "draft_id", tI(), "vars", vars, "dry_run", tB(), "wait", tI()),
			run:    run(func(a, b *omap) { b.set("draft_id", a.val("draft_id")) }), noteAfter: true},
		{name: "myrmm_run_inline", desc: "Esegue un testo libero su un device di un cliente di collaudo, senza salvarlo (il testo finisce nel registro di audit). dry_run vero per impostazione predefinita.",
			schema: obj([]string{"device_id", "body"}, "device_id", tI(), "body", tS(), "platform", tS(), "timeout", tI(), "vars", vars, "dry_run", tB(), "wait", tI()),
			run: run(func(a, b *omap) {
				b.set("body", a.val("body"))
				b.set("platform", get(a, "platform", "any"))
				b.set("timeout", get(a, "timeout", json.Number("300")))
			}), noteAfter: true},
		{name: "myrmm_get_job", desc: "Stato e risultato di un job; wait = secondi di attesa del risultato (max 25).", schema: obj([]string{"id"}, "id", tI(), "wait", tI()),
			run: func(s *server, a *omap) (int, any, error) {
				st, j := s.call("job", "GET", nil, qp{"id", a.val("id")}, qp{"wait", get(a, "wait", json.Number("0"))})
				return st, j, nil
			}, noteAfter: true},
		{name: "myrmm_cancel_job", desc: "Annulla una richiesta propria non ancora consegnata.", schema: obj([]string{"job_id"}, "job_id", tI()),
			run: func(s *server, a *omap) (int, any, error) {
				st, j := s.call("cancel", "POST", newMap("job_id", a.val("job_id")))
				return st, j, nil
			}},
		{name: "myrmm_audit", desc: "Ultime voci del registro di audit (solo token senza limite di cliente).", schema: obj(nil, "limit", tI(), "since", tI()), run: one("audit", "limit", "since")},
	}
}

// or2: vars mancante o nullo diventa {} (come `a.get("vars") or {}`).
func or2(v any) any {
	if !truthy(v) {
		return newMap()
	}
	return v
}
