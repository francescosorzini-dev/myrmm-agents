//go:build !windows

package main

import "github.com/kardianos/service"

// La chat e l'icona nella systray esistono solo su Windows.
func trayOn(cfg *Config) bool                                      { return false }
func trayStart(cfg *Config, log service.Logger)                    {}
func trayApply(cfg *Config, mode, impl string, log service.Logger) {}
