//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

func isWindows() bool { return false }

func pauseOnConsole() {}

// registerTunnelScheme: Linux con xdg (file .desktop dell'utente). Su macOS un collegamento personalizzato richiede un'app
// impacchettata: non c'è, si usa il comando mostrato nella pagina del tunnel.
func registerTunnelScheme(exe string) error {
	if runtime.GOOS != "linux" {
		return errors.New("su questo sistema il collegamento con un clic non è disponibile: usa il comando mostrato nella pagina del tunnel")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	dir := filepath.Join(home, ".local", "share", "applications")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	desk := fmt.Sprintf("[Desktop Entry]\nType=Application\nName=myrmm tunnel\nExec=%q tunnel-uri %%u\nTerminal=true\nNoDisplay=true\nMimeType=x-scheme-handler/%s;\n", exe, tunnelScheme)
	if err := os.WriteFile(filepath.Join(dir, "myrmm-tunnel.desktop"), []byte(desk), 0o644); err != nil {
		return err
	}
	if p, err := exec.LookPath("xdg-mime"); err == nil {
		_ = exec.Command(p, "default", "myrmm-tunnel.desktop", "x-scheme-handler/"+tunnelScheme).Run()
	}
	return nil
}

// registerTunnelSchemeSystem: Linux, per tutti gli utenti (il servizio gira come root): file .desktop di sistema e applicazione predefinita.
func registerTunnelSchemeSystem(exe string) error {
	if runtime.GOOS != "linux" {
		return nil
	}
	desk := fmt.Sprintf("[Desktop Entry]\nType=Application\nName=myrmm tunnel\nExec=%q tunnel-uri %%u\nTerminal=true\nNoDisplay=true\nMimeType=x-scheme-handler/%s;\n", exe, tunnelScheme)
	p := "/usr/share/applications/myrmm-tunnel.desktop"
	if b, err := os.ReadFile(p); err == nil && string(b) == desk {
		return nil
	}
	if err := os.WriteFile(p, []byte(desk), 0o644); err != nil {
		return err
	}
	if q, err := exec.LookPath("update-desktop-database"); err == nil {
		_ = exec.Command(q, "/usr/share/applications").Run()
	}
	// predefinito per tutti gli utenti, se non hanno una scelta propria
	const ml = "/etc/xdg/mimeapps.list"
	b, _ := os.ReadFile(ml)
	line := "x-scheme-handler/" + tunnelScheme + "=myrmm-tunnel.desktop"
	if !strings.Contains(string(b), line) {
		s := string(b)
		if !strings.Contains(s, "[Default Applications]") {
			s += "[Default Applications]\n"
		}
		s = strings.Replace(s, "[Default Applications]\n", "[Default Applications]\n"+line+"\n", 1)
		return os.WriteFile(ml, []byte(s), 0o644)
	}
	return nil
}

func runTunnelDetached(string) bool { return false }

func showTunnelError(string) {}
