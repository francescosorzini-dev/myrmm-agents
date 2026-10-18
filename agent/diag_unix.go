//go:build !windows

package main

import "runtime"

func platDiag() string {
	var s string
	s += "uname: " + runCmd(5e9, "uname", "-a") + "\n"
	if runtime.GOOS == "linux" {
		s += "\n--- systemctl status myrmm-agent ---\n" + runCmd(8e9, "systemctl", "status", "myrmm-agent", "--no-pager", "-l") + "\n"
		s += "\n--- journalctl (ultime 40 righe) ---\n" + runCmd(8e9, "journalctl", "-u", "myrmm-agent", "-n", "40", "--no-pager") + "\n"
		s += "\n--- loginctl list-sessions ---\n" + runCmd(5e9, "loginctl", "list-sessions", "--no-legend") + "\n"
	} else {
		s += "\n--- launchctl list (myrmm) ---\n" + runCmd(5e9, "sh", "-c", "launchctl list | grep -i myrmm") + "\n"
		s += "\n--- log (ultime 40 righe) ---\n" + runCmd(8e9, "sh", "-c", "log show --last 15m --predicate 'process == \"myrmm-agent\"' 2>/dev/null | tail -40") + "\n"
	}
	s += "\n--- spazio disco ---\n" + runCmd(5e9, "df", "-h", dataDir()) + "\n"
	return s
}
