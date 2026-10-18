package main

import "os/exec"

// openRDP avvia il client Desktop remoto di Windows verso l'indirizzo locale del tunnel.
func openRDP(addr string) {
	_ = exec.Command("mstsc.exe", "/v:"+addr).Start()
}

// openVNC: Windows non ha un client VNC di sistema; indica l'indirizzo da usare.
func openVNC(addr string) {
	println("(-vnc: Windows non ha un client VNC integrato) collega il tuo client VNC a", addr)
}
