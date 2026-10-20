//go:build windows

package main

import (
	"bufio"
	"fmt"
	"os"

	"golang.org/x/sys/windows/registry"
)

func isWindows() bool { return true }

// registerTunnelScheme: HKCU\Software\Classes\myrmm-tunnel (nessun diritto di amministratore).
func registerTunnelScheme(exe string) error {
	k, _, err := registry.CreateKey(registry.CURRENT_USER, `Software\Classes\`+tunnelScheme, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer k.Close()
	if err := k.SetStringValue("", "URL:myrmm tunnel"); err != nil {
		return err
	}
	if err := k.SetStringValue("URL Protocol", ""); err != nil {
		return err
	}
	c, _, err := registry.CreateKey(registry.CURRENT_USER, `Software\Classes\`+tunnelScheme+`\shell\open\command`, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer c.Close()
	return c.SetStringValue("", fmt.Sprintf(`"%s" tunnel-uri "%%1"`, exe))
}

// pauseOnConsole: la finestra aperta dal collegamento si chiuderebbe subito: dopo un errore aspetta un tasto.
func pauseOnConsole() {
	fmt.Fprintln(os.Stderr, "\nPremi Invio per chiudere.")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
}
