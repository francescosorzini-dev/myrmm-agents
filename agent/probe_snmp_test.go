package main

import (
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

func simTarget(t *testing.T, comm string, c snmpCfg) probeTarget {
	p := os.Getenv("SNMPSIM_PORT")
	if p == "" {
		t.Skip("SNMPSIM_PORT non impostata (snmpsim non avviato)")
	}
	port, _ := strconv.Atoi(p)
	c.V, c.Comm, c.Port = "2c", comm, port
	return probeTarget{ID: 900, IP: "127.0.0.1", Kind: "snmp", Every: 60, Snmp: &c}
}

func TestSnmpPrinter(t *testing.T) {
	r := snmpPoll(simTarget(t, "printer", snmpCfg{Profile: "auto"}), true)
	if !r.OK || r.Snmp == nil {
		t.Fatalf("poll: %+v", r)
	}
	d := r.Snmp
	if d.Profile != "printer" || d.Name != "STAMPA-UFFICIO" || d.Info["serial"] != "VNB3K12345" || d.M["pages"] != 48213 {
		t.Fatalf("dati: %+v", d)
	}
	if len(d.Sup) != 3 || d.Sup[0].Pct != 80 || d.Sup[1].Pct != 7 || d.Sup[2].Pct != -1 || d.M["supply_min"] != 7 {
		t.Fatalf("materiali: %+v", d.Sup)
	}
	if len(d.Alerts) != 1 || d.M["alerts"] != 1 || d.Uptime != 86400 {
		t.Fatalf("avvisi/uptime: %+v %d", d.Alerts, d.Uptime)
	}
}

func TestSnmpSwitchAndFirewall(t *testing.T) {
	r := snmpPoll(simTarget(t, "switch", snmpCfg{Profile: "auto", Observe: []int{1, 3}}), true)
	d := r.Snmp
	if !r.OK || d.Profile != "switch" || d.M["ports_total"] != 24 || d.M["ports_up"] != 6 || d.M["if_errors"] != 3 || len(d.If) != 25 {
		t.Fatalf("switch: %+v %+v", r, d)
	}
	if d.If[0].Alias != "UPLINK-FW" || d.If[0].Speed != 1000000000 {
		t.Fatalf("if: %+v", d.If[0])
	}
	f := snmpPoll(simTarget(t, "switch", snmpCfg{Observe: []int{1, 3}}), false)
	if !f.OK || !f.Snmp.Fast || len(f.Snmp.If) != 2 || f.Snmp.If[0].Oper != 1 || f.Snmp.If[1].Oper != 2 {
		t.Fatalf("veloce: %+v", f.Snmp)
	}
	r = snmpPoll(simTarget(t, "firewall", snmpCfg{}), true)
	d = r.Snmp
	if !r.OK || d.Profile != "firewall" || d.M["cpu"] != 20 || d.M["mem"] != 55 || d.M["disk"] != 91 || d.M["ifs_up"] != 2 || d.M["ifs_total"] != 3 {
		t.Fatalf("firewall: %+v", d)
	}
}

func TestSnmpCustomScanAndErrors(t *testing.T) {
	tg := simTarget(t, "printer", snmpCfg{Custom: []snmpCustom{{Name: "pagine", OID: "1.3.6.1.2.1.43.10.2.1.4.1.1"}, {Name: "vendor", OID: "1.3.6.1.4.1.11.2.3.9.4.2.1.1.1.0"}, {Name: "assente", OID: "1.3.6.1.4.1.99.1.0"}}, Scan: 1})
	d := snmpPoll(tg, true).Snmp
	if len(d.Cust) != 3 || !d.Cust[0].OK || d.Cust[0].V != 48213 || d.M["c.pagine"] != 48213 || d.Cust[1].S != "sample-vendor-oid" || d.Cust[2].OK {
		t.Fatalf("custom: %+v", d.Cust)
	}
	w := snmpScanWalk(tg)
	if w.Err != "" || len(w.OIDs) < 20 {
		t.Fatalf("walk: %d %s", len(w.OIDs), w.Err)
	}
	bad := tg
	c := *tg.Snmp
	c.Comm = "sbagliata"
	bad.Snmp = &c
	t0 := time.Now()
	r := snmpPoll(bad, true)
	if r.OK || r.Detail == "" {
		t.Fatalf("community errata accettata: %+v", r)
	}
	t.Log("errore:", r.Detail, time.Since(t0))
}

func TestIfRate(t *testing.T) {
	now := time.Now()
	if a, b := ifRate(7, 1, 1000, 2000, now); a != 0 || b != 0 {
		t.Fatal("prima lettura senza velocità")
	}
	a, b := ifRate(7, 1, 1000+12500, 2000+25000, now.Add(10*time.Second))
	if a != 10000 || b != 20000 {
		t.Fatalf("bit/s: %d %d", a, b)
	}
	if a, b := ifRate(7, 1, 5, 5, now.Add(20*time.Second)); a != 0 || b != 0 {
		t.Fatal("contatore azzerato")
	}
}

func TestSnmpV3(t *testing.T) {
	tg := simTarget(t, "", snmpCfg{Profile: "auto"})
	c := *tg.Snmp
	c.V, c.User, c.AuthP, c.AuthK, c.PrivP, c.PrivK = "3", "simulator", "MD5", "auctoritas", "DES", "privatus"
	c.Port, c.Ctx = tg.Snmp.Port, "printer"
	tg.Snmp = &c
	// snmpsim sceglie i dati dal contesto v3: senza contesto usa il file "public"
	r := snmpPoll(tg, true)
	if !r.OK {
		t.Fatalf("v3: %+v", r)
	}
	c.AuthK = "sbagliata1"
	r = snmpPoll(tg, true)
	if r.OK || r.Detail == "" {
		t.Fatalf("v3 con password errata accettato: %+v", r)
	}
	t.Log(r.Detail)
}

func TestSnmpIdentify(t *testing.T) {
	tg := simTarget(t, "printer", snmpCfg{})
	f := snmpIdentify("127.0.0.1", tg.Snmp)
	if f == nil || f.Profile != "printer" || f.Name != "STAMPA-UFFICIO" || !strings.Contains(f.Descr, "LaserJet") {
		t.Fatalf("identificazione: %+v", f)
	}
	bad := *tg.Snmp
	bad.Comm = "no"
	if f := snmpIdentify("127.0.0.1", &bad); f != nil {
		t.Fatalf("community errata: %+v", f)
	}
}

func TestSnmpUPS(t *testing.T) {
	r := snmpPoll(simTarget(t, "ups", snmpCfg{}), true)
	d := r.Snmp
	if !r.OK || d == nil || d.Profile != "ups" || d.Info["marca"] != "APC" || d.Info["modello"] != "Smart-UPS 1500" {
		t.Fatalf("ups: %+v %+v", r, d)
	}
	if d.M["batt_pct"] != 97 || d.M["runtime_min"] != 42 || d.M["batt_status"] != 2 || d.M["on_battery"] != 0 || d.M["load_pct"] != 35 || d.M["batt_volt"] != 27.2 || d.M["batt_temp"] != 27 {
		t.Fatalf("misure UPS: %+v", d.M)
	}
}

func TestSnmpNAS(t *testing.T) {
	r := snmpPoll(simTarget(t, "nas", snmpCfg{}), true)
	d := r.Snmp
	if !r.OK || d == nil || d.Profile != "nas" || d.Info["modello"] != "DS920+" || d.Info["matricola"] != "2010TTT123" {
		t.Fatalf("nas: %+v %+v", r, d)
	}
	if d.M["disks"] != 2 || d.M["disk_bad"] != 1 || d.Info["dischi_anomali"] != "Drive 2" || d.M["raid_bad"] != 0 || d.M["temp"] != 35 || d.M["disk_temp_max"] != 41 || d.M["sys_bad"] != 0 {
		t.Fatalf("misure NAS: %+v %+v", d.M, d.Info)
	}
	if d.M["mem"] != 62 || d.M["disk"] != 82 {
		t.Fatalf("host: %+v", d.M)
	}
}

func TestSnmpAPAndNeighbors(t *testing.T) {
	r := snmpPoll(simTarget(t, "ap", snmpCfg{}), true)
	d := r.Snmp
	if !r.OK || d == nil || d.Profile != "ap" || d.M["clients"] != 16 || !strings.Contains(d.Info["reti_wifi"], "Ufficio-WiFi (canale 36, 11 client)") {
		t.Fatalf("ap: %+v %+v", r, d)
	}
	if len(d.Nbr) != 1 || d.Nbr[0].Name != "SW-CED" || d.Nbr[0].Port != "Gi1/0/20" || d.Nbr[0].MAC != "00:11:22:33:44:55" || d.Nbr[0].LP != 1 || d.Nbr[0].LN != "eth0" || d.Nbr[0].Proto != "lldp" {
		t.Fatalf("lldp ap: %+v", d.Nbr)
	}
	sw := snmpPoll(simTarget(t, "switch", snmpCfg{}), true).Snmp
	if len(sw.Nbr) != 2 || sw.Nbr[0].Name != "FW-SEDE" || sw.Nbr[0].LN != "Gi1/0/1" || sw.Nbr[1].Name != "AP-PIANO1" || sw.Nbr[1].MAC != "00:11:22:33:44:55" || sw.Nbr[1].LP != 20 {
		t.Fatalf("lldp switch: %+v", sw.Nbr)
	}
	fw := snmpPoll(simTarget(t, "firewall", snmpCfg{}), true).Snmp
	if len(fw.Nbr) != 1 || fw.Nbr[0].Proto != "cdp" || fw.Nbr[0].Name != "SW-CED" || fw.Nbr[0].IP != "10.0.0.3" || fw.Nbr[0].Port != "GigabitEthernet1/0/1" || fw.Nbr[0].LP != 2 {
		t.Fatalf("cdp firewall: %+v", fw.Nbr)
	}
}

// Credenziali multiple: la prima è sbagliata, la seconda risponde; viene ricordata e riportata con il suo cid.
func TestSnmpAlternateCredentials(t *testing.T) {
	tg := simTarget(t, "printer", snmpCfg{Profile: "auto"})
	wrong := *tg.Snmp
	wrong.Comm, wrong.CID = "sbagliata", 11
	right := *tg.Snmp
	right.CID = 22
	wrong.Alts = []snmpCfg{right}
	tg.ID = 987
	tg.Snmp = &wrong
	r := snmpPoll(tg, true)
	if !r.OK || r.Snmp == nil || r.Snmp.Cid != 22 {
		t.Fatalf("alternativa non usata: %+v", r)
	}
	// al giro dopo la credenziale giusta va per prima (nessun timeout sulla sbagliata)
	t0 := time.Now()
	r = snmpPoll(tg, false)
	if !r.OK || r.Snmp.Cid != 22 {
		t.Fatalf("vincitrice non ricordata: %+v", r)
	}
	if time.Since(t0) > 2*time.Second {
		t.Fatalf("troppo lento: riprovata la credenziale sbagliata (%v)", time.Since(t0))
	}
	// il riconoscimento degli apparati scoperti prova le alternative
	f := snmpIdentify(tg.IP, &wrong)
	if f == nil || f.Cid != 22 {
		t.Fatalf("identify: %+v", f)
	}
}
