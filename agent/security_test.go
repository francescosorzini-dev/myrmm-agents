package main

import (
	"testing"
	"time"
)

func TestAvState(t *testing.T) {
	for _, c := range []struct {
		s      int
		en, up bool
	}{{266240, true, true}, {266256, true, false}, {262144, false, true}, {393472, false, true}, {397312, true, true}} {
		en, up := avState(c.s)
		if en != c.en || up != c.up {
			t.Errorf("state %d: got %v %v want %v %v", c.s, en, up, c.en, c.up)
		}
	}
}

func TestNormalizeWinSecurity(t *testing.T) {
	now := time.Now()
	// terza parte attiva e aggiornata batte Defender spento
	raw := map[string]any{
		"av":        []any{map[string]any{"name": "Windows Defender", "state": float64(393472)}, map[string]any{"name": "Sentinel", "state": float64(266240)}},
		"bitlocker": []any{map[string]any{"mount": "C:", "status": "On"}, map[string]any{"mount": "D:", "status": "Off"}},
		"firewall":  []any{map[string]any{"name": "Domain", "enabled": true}, map[string]any{"name": "Private", "enabled": true}, map[string]any{"name": "Public", "enabled": false}},
		"backup":    map[string]any{"product": "Windows Server Backup", "last_success": "2026-10-13T02:00:00Z"},
	}
	o := normalizeWinSecurity(raw, now)
	av := o["av"].(map[string]any)
	if av["name"] != "Sentinel" || av["enabled"] != true || av["updated"] != true {
		t.Errorf("av: %v", av)
	}
	v := o["bitlocker"].(map[string]any)["volumes"].([]any)
	if len(v) != 2 || v[0].(map[string]any)["protected"] != true || v[1].(map[string]any)["protected"] != false {
		t.Errorf("bitlocker: %v", v)
	}
	fw := o["firewall"].(map[string]any)
	if fw["domain"] != true || fw["public"] != false {
		t.Errorf("fw: %v", fw)
	}
	if o["backup"].(map[string]any)["last_success"] != "2026-10-13T02:00:00Z" {
		t.Errorf("backup: %v", o["backup"])
	}
	// server: nessun SecurityCenter2, Defender attivo con firme di 2 giorni
	o = normalizeWinSecurity(map[string]any{"av": []any{}, "defender": map[string]any{"rtp": true, "sig_age_days": float64(2)}}, now)
	av = o["av"].(map[string]any)
	if av["name"] != "Microsoft Defender" || av["enabled"] != true || av["updated"] != true {
		t.Errorf("defender: %v", av)
	}
	// firme vecchie
	o = normalizeWinSecurity(map[string]any{"av": []any{}, "defender": map[string]any{"rtp": true, "sig_age_days": float64(30)}}, now)
	if o["av"].(map[string]any)["updated"] != false {
		t.Errorf("defender vecchio: %v", o["av"])
	}
	// nessun antivirus
	o = normalizeWinSecurity(map[string]any{"av": []any{}}, now)
	if o["av"].(map[string]any)["present"] != false {
		t.Errorf("assente: %v", o["av"])
	}
	// oggetto singolo (ConvertTo-Json) e script fallito: niente chiavi
	o = normalizeWinSecurity(map[string]any{"av": map[string]any{"name": "X", "state": float64(266240)}}, now)
	if o["av"].(map[string]any)["name"] != "X" {
		t.Errorf("singolo: %v", o["av"])
	}
	if _, ok := o["bitlocker"]; ok {
		t.Error("bitlocker non rilevato non va inviato")
	}
	if len(normalizeWinSecurity(nil, now)) != 0 {
		t.Error("nil")
	}
	// backup senza esito: non inviato
	if _, ok := normalizeWinSecurity(map[string]any{"backup": map[string]any{"product": "x", "last_success": ""}}, now)["backup"]; ok {
		t.Error("backup senza esito")
	}
}

func TestLsblkEncryption(t *testing.T) {
	js := `{"blockdevices":[{"name":"sda","type":"disk","mountpoint":null,"children":[{"name":"sda1","type":"part","mountpoint":"/boot"},{"name":"sda2","type":"part","mountpoint":null,"children":[{"name":"luks","type":"crypt","mountpoint":"/"}]}]},{"name":"sdb","type":"disk","mountpoint":null,"children":[{"name":"sdb1","type":"part","mountpoint":"/data"}]}]}`
	v, ok := lsblkEncryption(js)
	if !ok || len(v) != 2 {
		t.Fatalf("%v %v", v, ok)
	}
	if v[0].(map[string]any)["mount"] != "/" || v[0].(map[string]any)["protected"] != true || v[1].(map[string]any)["mount"] != "/data" || v[1].(map[string]any)["protected"] != false {
		t.Errorf("%v", v)
	}
	if _, ok := lsblkEncryption("non json"); ok {
		t.Error("json non valido")
	}
}

func TestFirewallActive(t *testing.T) {
	cases := []struct {
		u, f, n string
		a, ok   bool
	}{{"Status: active\n", "", "", true, true}, {"Status: inactive", "", "", false, true}, {"", "running", "", true, true}, {"", "not running", "", false, true}, {"", "", "table inet filter {\n chain input { policy drop; }", true, true}, {"", "", "", false, false}}
	for i, c := range cases {
		a, ok := firewallActive(c.u, c.f, c.n)
		if a != c.a || ok != c.ok {
			t.Errorf("caso %d: %v %v", i, a, ok)
		}
	}
}

func TestNormalizeTpm(t *testing.T) {
	o := normalizeWinSecurity(map[string]any{"tpm": map[string]any{"present": true, "ready": false}}, time.Now())
	m, ok := o["tpm"].(map[string]any)
	if !ok || m["present"] != true || m["ready"] != false {
		t.Errorf("tpm: %v", o["tpm"])
	}
	if _, ok := normalizeWinSecurity(map[string]any{}, time.Now())["tpm"]; ok {
		t.Error("tpm non rilevato non va inviato")
	}
}
