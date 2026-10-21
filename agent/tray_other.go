//go:build !windows

package main

import (
	"fmt"
	"os"

	"github.com/kardianos/service"
)

// La chat e l'icona nella systray esistono solo su Windows.
func trayOn(cfg *Config) bool                                { return false }
func trayStart(cfg *Config, st State, log service.Logger)    {}
func trayApply(cfg *Config, mode string, log service.Logger) {}
func trayLocalPending() string                               { return "" }
func trayDiag() string                                       { return "" }
func trayMain() int {
	fmt.Fprintln(os.Stderr, "la tray esiste solo per Windows")
	return 1
}
func trayConfigMain(args []string) int { return trayMain() }
