//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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
