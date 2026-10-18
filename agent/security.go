package main

import (
	"encoding/json"
	"strings"
	"time"
)

// Prove di sicurezza raccolte dall'agent (antivirus/EDR, cifratura dei dischi, firewall, amministratori locali, backup).
// Lo script o il comando di sistema restituisce valori grezzi; qui vengono interpretati, così la logica si prova senza Windows.
// Schema inviato al server in full_inv["security"]:
//   av{present,name,enabled,updated}, bitlocker{volumes[{mount,protected}]}, firewall{domain,private,public},
//   local_admins[], backup{product,last_success}, tpm{present,ready}. Una chiave assente significa «non rilevato»: il server non la conta.

func asBool(v any) bool {
	switch x := v.(type) {
	case bool:
		return x
	case float64:
		return x != 0
	case string:
		s := strings.ToLower(strings.TrimSpace(x))
		return s == "true" || s == "on" || s == "1" || s == "yes" || s == "active"
	}
	return false
}

func asInt(v any) (int, bool) {
	switch x := v.(type) {
	case float64:
		return int(x), true
	case int:
		return x, true
	}
	return 0, false
}

func asList(v any) []map[string]any {
	switch x := v.(type) {
	case []any:
		out := []map[string]any{}
		for _, e := range x {
			if m, ok := e.(map[string]any); ok {
				out = append(out, m)
			}
		}
		return out
	case map[string]any: // ConvertTo-Json riduce a oggetto un array di un solo elemento
		return []map[string]any{x}
	}
	return nil
}

// avState interpreta productState di SecurityCenter2: 0x1000 = protezione attiva, 0x10 = firme non aggiornate.
func avState(state int) (enabled, updated bool) {
	return state&0xF000 == 0x1000, state&0x10 == 0
}

// normalizeWinSecurity trasforma l'output grezzo dello script Windows nello schema del server.
func normalizeWinSecurity(raw map[string]any, now time.Time) map[string]any {
	out := map[string]any{}
	if raw == nil {
		return out
	}
	if _, ran := raw["av"]; ran {
		av := map[string]any{"present": false, "name": "", "enabled": false, "updated": false}
		best := -1
		for _, p := range asList(raw["av"]) {
			st, ok := asInt(p["state"])
			if !ok {
				continue
			}
			en, up := avState(st)
			score := 0
			if en {
				score += 2
			}
			if up {
				score++
			}
			if score > best {
				best = score
				name, _ := p["name"].(string)
				av = map[string]any{"present": true, "name": name, "enabled": en, "updated": up}
			}
		}
		if d, ok := raw["defender"].(map[string]any); ok && best < 3 && (asBool(d["rtp"]) || asBool(d["enabled"])) {
			age, hasAge := asInt(d["sig_age_days"])
			up := hasAge && age <= 7
			if !av["present"].(bool) || best < 2 || (best == 2 && up) {
				av = map[string]any{"present": true, "name": "Microsoft Defender", "enabled": asBool(d["rtp"]), "updated": up}
			}
		}
		out["av"] = av
	}
	if _, ran := raw["bitlocker"]; ran {
		vols := []any{}
		for _, v := range asList(raw["bitlocker"]) {
			mount, _ := v["mount"].(string)
			vols = append(vols, map[string]any{"mount": mount, "protected": asBool(v["status"])})
		}
		out["bitlocker"] = map[string]any{"volumes": vols}
	}
	if _, ran := raw["firewall"]; ran {
		fw := map[string]any{"domain": false, "private": false, "public": false}
		for _, p := range asList(raw["firewall"]) {
			if n, _ := p["name"].(string); n != "" {
				fw[strings.ToLower(n)] = asBool(p["enabled"])
			}
		}
		out["firewall"] = fw
	}
	if t, ok := raw["tpm"].(map[string]any); ok {
		out["tpm"] = map[string]any{"present": asBool(t["present"]), "ready": asBool(t["ready"])}
	}
	if b, ok := raw["backup"].(map[string]any); ok {
		if ls, _ := b["last_success"].(string); ls != "" {
			p, _ := b["product"].(string)
			out["backup"] = map[string]any{"product": p, "last_success": ls}
		}
	}
	return out
}

// lsblkEncryption: volumi montati e cifratura (un montaggio sotto un nodo di tipo «crypt» è protetto). Entrata: lsblk -J -o NAME,TYPE,MOUNTPOINT.
func lsblkEncryption(js string) ([]any, bool) {
	var d struct {
		Blockdevices []lsblkNode `json:"blockdevices"`
	}
	if json.Unmarshal([]byte(js), &d) != nil || len(d.Blockdevices) == 0 {
		return nil, false
	}
	vols := []any{}
	var walk func(n lsblkNode, enc bool)
	walk = func(n lsblkNode, enc bool) {
		enc = enc || n.Type == "crypt"
		mp := ""
		switch m := n.Mountpoint.(type) {
		case string:
			mp = m
		}
		if mp == "/" || strings.HasPrefix(mp, "/home") || strings.HasPrefix(mp, "/data") || strings.HasPrefix(mp, "/mnt") || strings.HasPrefix(mp, "/srv") {
			vols = append(vols, map[string]any{"mount": mp, "protected": enc})
		}
		for _, c := range n.Children {
			walk(c, enc)
		}
	}
	for _, n := range d.Blockdevices {
		walk(n, false)
	}
	return vols, true
}

type lsblkNode struct {
	Name       string      `json:"name"`
	Type       string      `json:"type"`
	Mountpoint any         `json:"mountpoint"`
	Children   []lsblkNode `json:"children"`
}

// firewallActive interpreta l'output dei comandi di stato del firewall di Linux; ok=false se nessuno è interpretabile.
func firewallActive(ufw, firewalld, nft string) (active, ok bool) {
	if s := strings.ToLower(ufw); strings.Contains(s, "status:") {
		return strings.Contains(s, "status: active"), true
	}
	if s := strings.ToLower(strings.TrimSpace(firewalld)); s == "running" {
		return true, true
	} else if s == "not running" {
		return false, true
	}
	if strings.TrimSpace(nft) != "" {
		return strings.Contains(nft, "chain") && (strings.Contains(nft, "drop") || strings.Contains(nft, "reject")), true
	}
	return false, false
}
