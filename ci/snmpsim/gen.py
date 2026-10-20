#!/usr/bin/env python3
"""Genera i dati per snmpsim (apparati finti: stampante, switch, firewall). Uso: gen.py DIR
La community SNMP v2c è il nome del file: printer, switch, firewall."""
import os, sys

def key(o): return [int(x) for x in o.split(".")]

def write(d, name, rows):
    rows = sorted(rows.items(), key=lambda kv: key(kv[0]))
    with open(os.path.join(d, name + ".snmprec"), "w") as f:
        for o, (t, v) in rows: f.write(f"{o}|{t}|{v}\n")

S = "1.3.6.1.2.1."
def system(r, descr, objid, name, up, svc):
    r[S+"1.1.0"] = ("4", descr); r[S+"1.2.0"] = ("6", objid); r[S+"1.3.0"] = ("67", str(up)); r[S+"1.5.0"] = ("4", name); r[S+"1.7.0"] = ("2", str(svc))

def iface(r, i, name, typ, speed_mbps, admin, oper, inb=0, outb=0, errs=0, alias=""):
    for col, t, v in ((1, "2", i), (2, "4", name), (3, "2", typ), (5, "66", min(speed_mbps * 1000000, 4294967295)), (7, "2", admin), (8, "2", oper), (10, "65", inb % 2**32), (14, "65", errs), (16, "65", outb % 2**32), (20, "65", 0)):
        r[f"{S}2.2.1.{col}.{i}"] = (t, str(v))
    r[f"{S}31.1.1.1.1.{i}"] = ("4", name); r[f"{S}31.1.1.1.15.{i}"] = ("66", str(speed_mbps))
    r[f"{S}31.1.1.1.6.{i}"] = ("70", str(inb)); r[f"{S}31.1.1.1.10.{i}"] = ("70", str(outb)); r[f"{S}31.1.1.1.18.{i}"] = ("4", alias)

def hr(r, cpus, ram_pct, disk_pct):
    for i, c in enumerate(cpus, 1): r[f"{S}25.3.3.1.2.{i}"] = ("2", str(c))
    r[S+"25.2.3.1.1.1"] = ("2", "1"); r[S+"25.2.3.1.2.1"] = ("6", "1.3.6.1.2.1.25.2.1.2"); r[S+"25.2.3.1.3.1"] = ("4", "Physical memory"); r[S+"25.2.3.1.4.1"] = ("2", "1024"); r[S+"25.2.3.1.5.1"] = ("2", "4000000"); r[S+"25.2.3.1.6.1"] = ("2", str(40000 * ram_pct))
    r[S+"25.2.3.1.1.2"] = ("2", "2"); r[S+"25.2.3.1.2.2"] = ("6", "1.3.6.1.2.1.25.2.1.4"); r[S+"25.2.3.1.3.2"] = ("4", "/"); r[S+"25.2.3.1.4.2"] = ("2", "4096"); r[S+"25.2.3.1.5.2"] = ("2", "1000000"); r[S+"25.2.3.1.6.2"] = ("2", str(10000 * disk_pct))

def lldp(r, local, idx, name, port, mac, descr):
    """Un vicino LLDP sulla porta locale (lldpRemTable): chassis id = MAC (sottotipo 4)."""
    b = "1.0.8802.1.1.2.1.4.1.1."; k = f"0.{local}.{idx}"
    r[b+"4."+k] = ("2", "4"); r[b+"5."+k] = ("4x", mac.replace(":", "")); r[b+"6."+k] = ("2", "5"); r[b+"7."+k] = ("4", port)
    r[b+"8."+k] = ("4", port); r[b+"9."+k] = ("4", name); r[b+"10."+k] = ("4", descr)

def cdp(r, ifindex, idx, ip4, devid, port, platform):
    b = "1.3.6.1.4.1.9.9.23.1.2.1.1."; k = f"{ifindex}.{idx}"
    r[b+"4."+k] = ("4x", "".join(f"{int(x):02x}" for x in ip4.split("."))); r[b+"6."+k] = ("4", devid); r[b+"7."+k] = ("4", port); r[b+"8."+k] = ("4", platform)

def build(d):
    os.makedirs(d, exist_ok=True)
    # --- stampante
    r = {}; system(r, "HP LaserJet M404dn", "1.3.6.1.4.1.11.2.3.9.1", "STAMPA-UFFICIO", 8640000, 72)
    iface(r, 1, "eth0", 6, 100, 1, 1, 123456789, 987654321)
    for n, (nm, mx, lv, cl) in enumerate([("Black Cartridge HP 58A", 3000, 2400, 3), ("Cyan Toner", 2000, 150, 3), ("Waste toner box", 1000, -3, 4)], 1):
        r[f"{S}43.11.1.1.4.1.{n}"] = ("2", str(cl)); r[f"{S}43.11.1.1.6.1.{n}"] = ("4", nm); r[f"{S}43.11.1.1.8.1.{n}"] = ("2", str(mx)); r[f"{S}43.11.1.1.9.1.{n}"] = ("2", str(lv))
    r[S+"43.5.1.1.17.1"] = ("4", "VNB3K12345"); r[S+"43.10.2.1.4.1.1"] = ("65", "48213"); r[S+"25.3.5.1.1.1"] = ("2", "3")
    r[S+"43.18.1.1.2.1.1"] = ("2", "3"); r[S+"43.18.1.1.8.1.1"] = ("4", "Toner ciano quasi esaurito")
    r["1.3.6.1.4.1.11.2.3.9.4.2.1.1.1.0"] = ("4", "sample-vendor-oid")
    write(d, "printer", r)
    # --- switch 24 porte
    r = {}; system(r, "Managed Gigabit Switch GS-2400 v2.1", "1.3.6.1.4.1.9999.1.24", "SW-CED", 123400000, 2)
    r[S+"17.1.2.0"] = ("2", "24"); r[S+"4.1.0"] = ("2", "2")
    for i in range(1, 25):
        iface(r, i, f"Gi1/0/{i}", 6, 1000, 1, 1 if i in (1, 2, 5, 7, 8, 20) else 2, 1000000 * i, 500000 * i, 3 if i == 5 else 0, "UPLINK-FW" if i == 1 else "")
    iface(r, 25, "Vlan1", 53, 0, 1, 1); r[S+"2.2.1.3.25"] = ("2", "53")
    hr(r, [12], 35, 20)
    lldp(r, 1, 1, "FW-SEDE", "lan", "aa:bb:cc:00:00:01", "FortiGate-60F")
    lldp(r, 20, 1, "AP-PIANO1", "eth0", "00:11:22:33:44:55", "UniFi AP-AC-Pro")
    write(d, "switch", r)
    # --- firewall
    r = {}; system(r, "FortiGate-60F v7.2.4,build1396", "1.3.6.1.4.1.12356.101.1.600", "FW-SEDE", 55500000, 78)
    r[S+"4.1.0"] = ("2", "1")
    iface(r, 1, "wan1", 6, 1000, 1, 1, 9000000000, 1200000000); iface(r, 2, "lan", 6, 1000, 1, 1, 3000000000, 8000000000); iface(r, 3, "dmz", 6, 1000, 1, 2)
    iface(r, 4, "lo", 24, 0, 1, 1)
    hr(r, [10, 30], 55, 91)
    cdp(r, 2, 1, "10.0.0.3", "SW-CED", "GigabitEthernet1/0/1", "cisco WS-C2960")
    write(d, "firewall", r)
    # --- UPS (1.37)
    r = {}; system(r, "Smart-UPS 1500 Network Management Card", "1.3.6.1.4.1.318.1.3.2.3", "UPS-CED", 77700000, 72)
    iface(r, 1, "eth0", 6, 100, 1, 1)
    u = S + "33.1."
    r[u+"1.1.0"] = ("4", "APC"); r[u+"1.2.0"] = ("4", "Smart-UPS 1500"); r[u+"1.3.0"] = ("4", "UPS 09.3")
    r[u+"2.1.0"] = ("2", "2"); r[u+"2.2.0"] = ("2", "0"); r[u+"2.3.0"] = ("2", "42"); r[u+"2.4.0"] = ("2", "97"); r[u+"2.5.0"] = ("2", "272"); r[u+"2.7.0"] = ("2", "27")
    r[u+"3.3.1.3.1"] = ("2", "231"); r[u+"3.2.0"] = ("2", "0")
    r[u+"4.1.0"] = ("2", "3"); r[u+"4.4.1.5.1"] = ("2", "35"); r[u+"4.4.1.2.1"] = ("2", "231")
    write(d, "ups", r)
    # --- NAS (stile Synology, vendor 6574)
    r = {}; system(r, "Linux DS920 4.4.302+ #69057 SMP x86_64 (Synology)", "1.3.6.1.4.1.8072.3.2.10", "NAS-UFFICIO", 99900000, 72)
    iface(r, 1, "eth0", 6, 1000, 1, 1, 5000000000, 2000000000)
    hr(r, [8], 62, 82)
    e = "1.3.6.1.4.1.6574."
    r[e+"1.1.0"] = ("2", "1"); r[e+"1.2.0"] = ("2", "35"); r[e+"1.3.0"] = ("2", "1")  # sistema, temperatura, ventola
    r[e+"1.5.1.0"] = ("4", "DS920+"); r[e+"1.5.2.0"] = ("4", "2010TTT123"); r[e+"1.5.3.0"] = ("4", "DSM 7.2")
    for n, (nm, st, tp) in enumerate([("Drive 1", 1, 34), ("Drive 2", 4, 41)]):
        r[f"{e}2.1.1.1.{n}"] = ("2", str(n)); r[f"{e}2.1.1.2.{n}"] = ("4", nm); r[f"{e}2.1.1.5.{n}"] = ("2", str(st)); r[f"{e}2.1.1.6.{n}"] = ("2", str(tp))
    r[e+"3.1.1.1.0"] = ("2", "0"); r[e+"3.1.1.2.0"] = ("4", "Volume 1"); r[e+"3.1.1.3.0"] = ("2", "1")  # raid: 1 normal, 11 degraded
    write(d, "nas", r)
    # --- access point
    r = {}; system(r, "UniFi AP-AC-Pro 6.5.28 wireless access point", "1.3.6.1.4.1.41112.1.6", "AP-PIANO1", 33300000, 6)
    iface(r, 1, "eth0", 6, 1000, 1, 1, 400000000, 300000000); iface(r, 2, "wlan0", 71, 300, 1, 1, 900000000, 700000000); iface(r, 3, "wlan1", 71, 866, 1, 1, 100000000, 50000000)
    u = "1.3.6.1.4.1.41112.1.6.1.1.1."
    for n, (nm, ch, essid, cl) in enumerate([("ath0", 36, "Ufficio-WiFi", 11), ("ath1", 6, "Ospiti", 5)], 1):
        r[f"{u}2.{n}"] = ("4", nm); r[f"{u}4.{n}"] = ("2", str(ch)); r[f"{u}6.{n}"] = ("4", essid); r[f"{u}8.{n}"] = ("2", str(cl))
    lldp(r, 1, 1, "SW-CED", "Gi1/0/20", "00:11:22:33:44:55", "Managed Gigabit Switch")
    write(d, "ap", r)

if __name__ == "__main__": build(sys.argv[1] if len(sys.argv) > 1 else ".")
