// Eseguibile di prova della tray (non viene distribuito): in produzione la tray è il sottocomando «tray» dell'agent.
// Usa le stesse variabili d'ambiente che imposta il servizio: MYRMM_TRAY_PORT, MYRMM_TRAY_KEY, MYRMM_DIR (cartella con tray.json).
package main

import (
	"fmt"
	"os"

	"myrmm-agent/tray"
)

func main() {
	o := tray.Options{Key: os.Getenv("MYRMM_TRAY_KEY"), Dir: os.Getenv("MYRMM_DIR")}
	if p := os.Getenv("MYRMM_TRAY_PORT"); p != "" {
		o.Base = fmt.Sprintf("http://127.0.0.1:%s", p)
	}
	tray.Main(o)
}
