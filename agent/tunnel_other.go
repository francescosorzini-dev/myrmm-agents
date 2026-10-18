//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
)

// openRDP apre un client Desktop remoto verso l'indirizzo locale del tunnel (macOS: file .rdp; Linux: xfreerdp o Remmina).
func openRDP(addr string) {
	switch runtime.GOOS {
	case "darwin":
		f, err := os.CreateTemp("", "myrmm-*.rdp")
		if err != nil {
			fmt.Println("(-rdp: impossibile creare il file .rdp:", err, ") collega il client RDP a", addr)
			return
		}
		fmt.Fprintf(f, "full address:s:%s\r\nprompt for credentials:i:1\r\nauthentication level:i:0\r\n", addr)
		f.Close()
		if exec.Command("open", f.Name()).Start() != nil {
			fmt.Println("(-rdp: serve l'app «Windows App / Microsoft Remote Desktop») collega il client RDP a", addr)
		}
	default:
		if p, err := exec.LookPath("xfreerdp"); err == nil {
			_ = exec.Command(p, "/v:"+addr, "/cert:ignore", "+clipboard").Start()
		} else if p, err := exec.LookPath("remmina"); err == nil {
			_ = exec.Command(p, "-c", "rdp://"+addr).Start()
		} else {
			fmt.Println("(-rdp: installa xfreerdp o Remmina) collega il client RDP a", addr)
		}
	}
}

// openVNC apre il client VNC predefinito (macOS: Condivisione schermo) verso l'indirizzo locale del tunnel.
func openVNC(addr string) {
	var c *exec.Cmd
	if runtime.GOOS == "darwin" {
		c = exec.Command("open", "vnc://"+addr)
	} else if p, err := exec.LookPath("xdg-open"); err == nil {
		c = exec.Command(p, "vnc://"+addr)
	}
	if c == nil || c.Start() != nil {
		fmt.Println("(-vnc: nessun client trovato) collega il client VNC a", addr)
	}
}
