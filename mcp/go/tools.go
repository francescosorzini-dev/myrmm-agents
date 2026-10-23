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
		{name: "myrmm_task_create", desc: "AI superiore: scrive un incarico per un'AI che lavora sui device. title breve, goal = cosa ottenere e come capire che è fatto, constraints = cosa NON fare. Con device_id o site. Sul collaudo parte subito; altrove aspetta l'approvazione di un amministratore.",
			schema: obj([]string{"title", "goal"}, "title", tS(), "goal", tS(), "constraints", tS(), "site", tS(), "device_id", tI()), run: post("task_create", "title", "goal", "constraints", "site", "device_id"), noteAfter: false},
		{name: "myrmm_task_list", desc: "Elenca gli incarichi. status: uno o più stati separati da virgola (awaiting_approval, pending, in_progress, waiting_answer, answered, done, failed, cancelled).",
			schema: obj(nil, "status", tS(), "limit", tI()), run: one("tasks", "status", "limit"), noteAfter: true},
		{name: "myrmm_task_get", desc: "Un incarico con tutta la cronologia (passi, domande, risposte, job, risultato).",
			schema: obj([]string{"id"}, "id", tI()), run: one("task", "id"), noteAfter: true},
		{name: "myrmm_task_answer", desc: "Risponde alla domanda dell'AI che lavora sull'incarico (status waiting_answer) o aggiunge una nota/istruzione a un incarico aperto.",
			schema: obj([]string{"id", "text"}, "id", tI(), "text", tS()), run: post("task_answer", "id", "text"), noteAfter: true},
		{name: "myrmm_task_cancel", desc: "Annulla un incarico aperto.",
			schema: obj([]string{"id"}, "id", tI(), "reason", tS()), run: post("task_cancel", "id", "reason")},
		{name: "myrmm_task_next", desc: "AI locale: prende in carico il prossimo incarico (prima quelli che hanno ricevuto risposta). Risponde {task:null} se non c'è nulla. Poi lavora con gli altri strumenti e riporta con myrmm_task_report.",
			schema: obj(nil, "id", newMap("type", "integer", "description", "facoltativo: un incarico preciso")), run: post("task_claim", "id"), noteAfter: true},
		{name: "myrmm_task_report", desc: "AI locale: riporta su un incarico preso in carico. note = passo o domanda; status: in_progress (predefinito), waiting_answer (serve una decisione: fermati), done, failed; result = riassunto finale; job_ids = job lanciati.",
			schema: obj([]string{"id"}, "id", tI(), "note", tS(), "status", tS(), "result", tS(), "job_ids", newMap("type", "array", "items", tI())), run: post("task_report", "id", "note", "status", "result", "job_ids"), noteAfter: true},
		{name: "myrmm_list_runbooks", desc: "Runbook (sequenze di script) che si possono avviare, con i passi e se questo token può usarli.",
			schema: obj(nil), run: one("runbooks")},
		{name: "myrmm_run_runbook", desc: "Avvia un runbook su un device. Sul collaudo parte subito; altrove aspetta l'approvazione di una persona (che autorizza tutto il runbook). Attende l'esito del primo passo.",
			schema: obj([]string{"device_id", "runbook_id"}, "device_id", tI(), "runbook_id", tI(), "wait", tI()), run: ord("runbook_run", true, "device_id", "runbook_id"), noteAfter: true},
		{name: "myrmm_service", desc: "Azione su un servizio del device: op = start, stop, restart, auto, manual, disabled; service = nome del servizio (Windows), unità systemd (Linux) o etichetta launchd (macOS).",
			schema: obj([]string{"device_id", "service", "op"}, "device_id", tI(), "service", tS(), "op", tS(), "wait", tI()), run: ord("service", true, "device_id", "service", "op"), noteAfter: true},
		{name: "myrmm_power", desc: "Riavvio, spegnimento programmato (minutes, predefinito 5) o annullamento (cancel). Riavvio e spegnimento aspettano SEMPRE l'approvazione di una persona in console, anche sul collaudo.",
			schema: obj([]string{"device_id", "op"}, "device_id", tI(), "op", newMap("type", "string", "description", "reboot, shutdown o cancel"), "minutes", tI(), "message", tS()), run: ord("power", false, "device_id", "op", "minutes", "message")},
		{name: "myrmm_list_patches", desc: "Patch note di un device (stato, gravità, decisione di approvazione) dall'ultima scansione.",
			schema: obj([]string{"device_id"}, "device_id", tI(), "limit", tI()), run: one("patches", "device_id", "limit"), noteAfter: true},
		{name: "myrmm_patch_scan", desc: "Avvia la scansione patch su un device Windows con agent.",
			schema: obj([]string{"device_id"}, "device_id", tI(), "wait", tI()), run: ord("patch_scan", true, "device_id"), noteAfter: true},
		{name: "myrmm_patch_install", desc: "Installa le patch note (tutte quelle non rifiutate, oppure solo le uids indicate). Nessun riavvio automatico.",
			schema: obj([]string{"device_id"}, "device_id", tI(), "uids", newMap("type", "array", "items", tS())), run: ord("patch_install", false, "device_id", "uids")},
		{name: "myrmm_list_tickets", desc: "Ticket. status: open (predefinito), closed, all. Filtri: device_id, site, q (nel titolo).",
			schema: obj(nil, "status", tS(), "device_id", tI(), "site", tS(), "q", tS(), "limit", tI()), run: one("tickets", "status", "device_id", "site", "q", "limit"), noteAfter: true},
		{name: "myrmm_get_ticket", desc: "Un ticket con le ultime note.",
			schema: obj([]string{"id"}, "id", tI()), run: one("ticket", "id"), noteAfter: true},
		{name: "myrmm_create_ticket", desc: "Apre un ticket su un device (device_id) o su un cliente (site). priority: low, normal, high, crit. note = prima nota.",
			schema: obj([]string{"title"}, "title", tS(), "device_id", tI(), "site", tS(), "priority", tS(), "note", tS()), run: post("ticket_create", "title", "device_id", "site", "priority", "note")},
		{name: "myrmm_add_ticket_note", desc: "Aggiunge una nota interna a un ticket aperto (minutes = tempo dedicato, facoltativo).",
			schema: obj([]string{"id", "text"}, "id", tI(), "text", tS(), "minutes", tI()), run: post("ticket_note", "id", "text", "minutes")},
		{name: "myrmm_list_assets", desc: "Asset (apparati, licenze, contratti…). Filtri: site, type_id, q (nome, seriale, modello). Con types=true elenca i tipi e i loro campi.",
			schema: obj(nil, "site", tS(), "type_id", tI(), "q", tS(), "types", tB(), "limit", tI()), run: func(s *server, a *omap) (int, any, error) {
				var t any
				if truthy(a.val("types")) {
					t = json.Number("1")
				}
				st, j := s.call("assets", "GET", nil, qp{"site", a.val("site")}, qp{"type_id", a.val("type_id")}, qp{"q", a.val("q")}, qp{"types", t}, qp{"limit", a.val("limit")})
				return st, j, nil
			}, noteAfter: true},
		{name: "myrmm_get_asset", desc: "Scheda di un asset (le password non vengono mai mostrate).",
			schema: obj([]string{"id"}, "id", tI()), run: one("asset", "id"), noteAfter: true},
		{name: "myrmm_create_asset", desc: "Crea un asset: type o type_id, name, site (o device_id), facoltativi location, serial, model, status (attivo, scorta, dismesso), purchased e expiry (AAAA-MM-GG), fields {chiave: valore} per i campi del tipo. Le password le inserisce una persona dalla console.",
			schema: obj([]string{"name"}, "type", tS(), "type_id", tI(), "name", tS(), "site", tS(), "device_id", tI(), "location", tS(), "serial", tS(), "model", tS(), "status", tS(), "purchased", tS(), "expiry", tS(), "fields", newMap("type", "object")),
			run:    post("asset_create", "type", "type_id", "name", "site", "device_id", "location", "serial", "model", "status", "purchased", "expiry", "fields")},
		{name: "myrmm_list_schedules", desc: "Pianificazioni di script sui device e di runbook (sola lettura).",
			schema: obj(nil, "limit", tI()), run: one("schedules", "limit")},
		{name: "myrmm_list_rules", desc: "Regole di monitoraggio e risposta automatica (sola lettura, solo token senza limiti di cliente).",
			schema: obj(nil), run: one("rules")},
	}
}

// ord: ordine che può partire subito (collaudo): dopo l'accodamento attende l'esito.
func ord(res string, wait bool, keys ...string) func(s *server, a *omap) (int, any, error) {
	p := post(res, keys...)
	return func(s *server, a *omap) (int, any, error) {
		st, j, err := p(s, a)
		if err != nil || !wait {
			return st, j, err
		}
		return waitFor(s, a, st, j)
	}
}

// post: POST di una risorsa con i soli parametri indicati (quelli presenti e non vuoti).
func post(res string, keys ...string) func(s *server, a *omap) (int, any, error) {
	return func(s *server, a *omap) (int, any, error) {
		d := newMap()
		for _, k := range keys {
			if v := a.val(k); v != nil {
				if t, ok := v.(string); ok && t == "" {
					continue
				}
				d.set(k, v)
			}
		}
		st, j := s.call(res, "POST", d)
		return st, j, nil
	}
}

// or2: vars mancante o nullo diventa {} (come `a.get("vars") or {}`).
func or2(v any) any {
	if !truthy(v) {
		return newMap()
	}
	return v
}
