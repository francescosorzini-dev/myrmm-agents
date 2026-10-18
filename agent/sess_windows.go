//go:build windows

package main

import (
	"strings"
	"syscall"
	"unicode/utf16"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	wtsapi            = windows.NewLazySystemDLL("wtsapi32.dll")
	procWTSQuerySess  = wtsapi.NewProc("WTSQuerySessionInformationW")
	procWTSFreeMemory = wtsapi.NewProc("WTSFreeMemory")
)

const (
	wtsUserName   = 5
	wtsDomainName = 7
)

func wtsString(session uint32, class uintptr) string {
	var buf *uint16
	var n uint32
	r, _, _ := procWTSQuerySess.Call(0, uintptr(session), class, uintptr(unsafe.Pointer(&buf)), uintptr(unsafe.Pointer(&n)))
	if r == 0 || buf == nil {
		return ""
	}
	defer procWTSFreeMemory.Call(uintptr(unsafe.Pointer(buf)))
	return syscall.UTF16ToString((*[1 << 12]uint16)(unsafe.Pointer(buf))[: n/2 : n/2])
}

// lockedSessions: sessioni in cui gira LogonUI.exe (schermata di blocco o di accesso).
func lockedSessions() map[uint32]bool {
	out := map[uint32]bool{}
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return out
	}
	defer windows.CloseHandle(snap)
	var pe windows.ProcessEntry32
	pe.Size = uint32(unsafe.Sizeof(pe))
	for err = windows.Process32First(snap, &pe); err == nil; err = windows.Process32Next(snap, &pe) {
		if strings.EqualFold(string(utf16.Decode(pe.ExeFile[:clen(pe.ExeFile[:])])), "LogonUI.exe") {
			var sid uint32
			if windows.ProcessIdToSessionId(pe.ProcessID, &sid) == nil {
				out[sid] = true
			}
		}
	}
	return out
}

func clen(b []uint16) int {
	for i, c := range b {
		if c == 0 {
			return i
		}
	}
	return len(b)
}

func platSessions() []sessInfo {
	var p *windows.WTS_SESSION_INFO
	var n uint32
	if err := windows.WTSEnumerateSessions(0, 0, 1, &p, &n); err != nil || p == nil {
		return nil
	}
	defer windows.WTSFreeMemory(uintptr(unsafe.Pointer(p)))
	items := (*[1 << 10]windows.WTS_SESSION_INFO)(unsafe.Pointer(p))[:n:n]
	var locked map[uint32]bool
	var out []sessInfo
	for _, it := range items {
		if it.SessionID == 0 {
			continue // sessione dei servizi
		}
		user := wtsString(it.SessionID, wtsUserName)
		if user == "" {
			continue // sessione di ascolto / schermata di accesso senza utente
		}
		if dom := wtsString(it.SessionID, wtsDomainName); dom != "" {
			user = dom + `\` + user
		}
		st := "inattiva"
		switch it.State {
		case windows.WTSActive:
			st = "attiva"
		case 4: // WTSDisconnected
			st = "disconnessa"
		}
		if st == "attiva" {
			if locked == nil {
				locked = lockedSessions()
			}
			if locked[it.SessionID] {
				st = "bloccata"
			}
		}
		via := "rdp"
		name := windows.UTF16PtrToString(it.WindowStationName)
		if strings.EqualFold(name, "Console") || (name == "" && st == "disconnessa") {
			via = "console"
		}
		out = append(out, sessInfo{User: user, State: st, Via: via})
	}
	return out
}
