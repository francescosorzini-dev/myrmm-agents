package main

// Costruttore dal MAC (primi 3 byte). Elenco ridotto ai costruttori più comuni nelle reti dei clienti: l'indicazione è
// orientativa (un MAC casuale dei telefoni o un costruttore non in elenco restano senza nome).

import "strings"

var ouiVendors = map[string]string{
	"Cisco":             "00000C 000142 000143 00036B 000F23 001A2F 001B54 001E13 002155 0022BD",
	"Apple":             "000393 000A27 000A95 000D93 001124 001451 0016CB 0017F2 0019E3 001B63 001CB3 001D4F 001E52 001EC2 001FF3 002241 002312 00236C 002500 0025BC 002608 0026BB",
	"Intel":             "0002B3 000347 000423 000E0C 001111 0013CE 001500 00166F 0019D1 001B21 001E64 001F3B 0022FA 0024D6 0026C6",
	"Dell":              "000874 000BDB 000D56 000F1F 001143 00123F 001422 0015C5 001AA0 001C23 001E4F 002219 002564 14FEB5 18A99B 246E96 B083FE D4BED9 F8BC12",
	"HP":                "0001E6 0001E7 000A57 001083 001185 001321 0014C2 001560 001635 0017A4 001871 0019BB 001A4B 001B78 001CC4 001E0B 001F29 002264 3CD92B 9457A5 B499BA FC15B4",
	"Microsoft Hyper-V": "00155D",
	"VMware":            "000569 000C29 001C14 005056",
	"VirtualBox":        "080027",
	"QEMU/KVM":          "525400",
	"Xen":               "00163E",
	"Raspberry Pi":      "B827EB DCA632 E45F01 28CDC1 D83ADD 2CCF67",
	"Ubiquiti":          "00156D 002722 0418D6 18E829 245A4C 44D9E7 687251 74ACB9 788A20 802AA8 B4FBE4 DC9FDB E063DA F09FC2 FCECDA",
	"MikroTik":          "000C42 2CC81B 4C5E0C 6C3B6B CC2DE0 D4CA6D E48D8C",
	"Synology":          "001132",
	"QNAP":              "00089B 245EBE",
	"Netgear":           "00095B 000FB5 00146C 00184D 001B2F 001E2A 001F33 00223F 0024B2 002675 20E52A 2C3033 9C3DCF A021B7 C03F0E",
	"TP-Link":           "001D0F 002719 14CC20 50C7BF 60E327 6466B3 8416F9 98DAC4 A0F3C1 C46E1F E894F6 F4F26D",
	"D-Link":            "00055D 000D88 001346 0015E9 001B11 001CF0 001E58 002191 00265A 1CBDB9 28107B 5CD998 B8A386 C8D3A3",
	"Zyxel":             "001349 0019CB 4018B1 B0B2DC",
	"Fortinet":          "00090F 085B0E 906CAC E81CBA",
	"Palo Alto":         "001B17 B40C25",
	"Juniper":           "000585 0010DB 0017CB 002159 2C6BF5 3C8AB0 5C5EAB",
	"Aruba/HPE":         "000B86 001A1E 04BD88 20A6CD 24DEC6 6CF37F 9CB6D0 D8C7C8",
	"Huawei":            "00E0FC 001882 00259E 0819A6 1C1D67 48DB50 70723C 9CC172 E0247F",
	"Samsung":           "0000F0 0007AB 0012FB 001377 001599 001632 0017C9 0018AF 001A8A 001D25 001E7D 002119 0021D1 002339 0024E9 002567 3423BA 5C0A5B",
	"Brother":           "008077 001BA9 30055C",
	"Canon":             "000085 001E8F 2C9EFC",
	"Epson":             "000048 0026AB 64EB8C",
	"Ricoh":             "000074",
	"Kyocera":           "00C0EE",
	"Xerox":             "0000AA",
	"Lexmark":           "000400",
	"APC (UPS)":         "00C0B7",
	"Hikvision":         "2857BE 4419B6 A41437 BCAD28 C056E3",
	"Dahua":             "3CEF8C 4C11BF 9002A9",
	"Axis":              "00408C ACCC8E B8A44F",
	"Sonos":             "000E58 5CAAFD 7828CA B8E937",
	"Google":            "3C5AB4 A47733 F4F5D8",
	"Amazon":            "0C47C9 18742E 34D270 4CEFC0 6837E9 74C246 F0272D FC65DE",
	"Espressif (IoT)":   "240AC4 30AEA4 3C71BF 5CCF7F 807D3A 84CCA8 A4CF12 B4E62D BCDDC2 C82B96 CC50E3 DC4F22 ECFABC",
}

var ouiTable = func() map[string]string {
	m := map[string]string{}
	for v, list := range ouiVendors {
		for _, p := range strings.Fields(list) {
			if len(p) == 6 && isHex(p) {
				m[strings.ToUpper(p)] = v
			}
		}
	}
	return m
}()

func isHex(s string) bool {
	for _, c := range s {
		if !(c >= '0' && c <= '9' || c >= 'A' && c <= 'F' || c >= 'a' && c <= 'f') {
			return false
		}
	}
	return s != ""
}

// macVendor: costruttore dal MAC ("aa:bb:cc:dd:ee:ff"); vuoto se non noto.
func macVendor(mac string) string {
	h := strings.ToUpper(strings.NewReplacer(":", "", "-", "", ".", "").Replace(mac))
	if len(h) < 6 {
		return ""
	}
	if v, ok := ouiTable[h[:6]]; ok {
		return v
	}
	// bit «amministrato localmente»: MAC casuale (privacy dei telefoni e dei PC recenti)
	if b := hexVal(h[1]); b&2 != 0 {
		return "MAC casuale (privacy)"
	}
	return ""
}

func hexVal(c byte) int {
	switch {
	case c >= '0' && c <= '9':
		return int(c - '0')
	case c >= 'A' && c <= 'F':
		return int(c-'A') + 10
	}
	return 0
}
