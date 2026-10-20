//go:build windows

package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
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

// registerTunnelSchemeSystem: HKLM\\Software\\Classes\\myrmm-tunnel (il servizio gira come SYSTEM): vale per ogni utente del PC.
func registerTunnelSchemeSystem(exe string) error {
	want := fmt.Sprintf(`"%s" tunnel-uri "%%1"`, exe)
	if c, err := registry.OpenKey(registry.LOCAL_MACHINE, `Software\Classes\`+tunnelScheme+`\shell\open\command`, registry.QUERY_VALUE); err == nil {
		v, _, _ := c.GetStringValue("")
		c.Close()
		if v == want {
			return nil
		}
	}
	k, _, err := registry.CreateKey(registry.LOCAL_MACHINE, `Software\Classes\`+tunnelScheme, registry.SET_VALUE)
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
	c, _, err := registry.CreateKey(registry.LOCAL_MACHINE, `Software\Classes\`+tunnelScheme+`\shell\open\command`, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer c.Close()
	return c.SetStringValue("", want)
}

// runTunnelDetached: rilancia sé stesso senza finestra e torna subito, così dal browser non compare nessuna console.
func runTunnelDetached(link string) bool {
	if os.Getenv("MYRMM_TUNNEL_BG") != "" {
		return false
	}
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	cmd := exec.Command(exe, "tunnel-uri", link)
	cmd.Env = append(os.Environ(), "MYRMM_TUNNEL_BG=1")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW | windows.DETACHED_PROCESS}
	return cmd.Start() == nil
}

// showTunnelError: senza console l'errore va mostrato in una finestra.
func showTunnelError(msg string) {
	if os.Getenv("MYRMM_TUNNEL_BG") == "" {
		return
	}
	mb := windows.NewLazySystemDLL("user32.dll").NewProc("MessageBoxW")
	t, _ := windows.UTF16PtrFromString("myrmm - tunnel")
	m, _ := windows.UTF16PtrFromString(msg)
	mb.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), 0x10)
}
