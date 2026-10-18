//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"syscall"
	"unsafe"
)

var (
	kernel32                   = syscall.NewLazyDLL("kernel32.dll")
	psapi                      = syscall.NewLazyDLL("psapi.dll")
	procGetProcessMemoryInfo   = psapi.NewProc("GetProcessMemoryInfo")
	procQueryFullProcessImageW = kernel32.NewProc("QueryFullProcessImageNameW")
	procGetSystemTimes         = kernel32.NewProc("GetSystemTimes")
	procGlobalMemoryStatusEx   = kernel32.NewProc("GlobalMemoryStatusEx")
)

const (
	procQueryLimited = 0x1000
	procTerminate    = 0x0001
	procSynchronize  = 0x00100000
)

type procMemCounters struct {
	CB                         uint32
	PageFaultCount             uint32
	PeakWorkingSetSize         uintptr
	WorkingSetSize             uintptr
	QuotaPeakPagedPoolUsage    uintptr
	QuotaPagedPoolUsage        uintptr
	QuotaPeakNonPagedPoolUsage uintptr
	QuotaNonPagedPoolUsage     uintptr
	PagefileUsage              uintptr
	PeakPagefileUsage          uintptr
}

type memStatusEx struct {
	Length               uint32
	MemoryLoad           uint32
	TotalPhys            uint64
	AvailPhys            uint64
	TotalPageFile        uint64
	AvailPageFile        uint64
	TotalVirtual         uint64
	AvailVirtual         uint64
	AvailExtendedVirtual uint64
}

var (
	winMu     sync.Mutex
	winCache  = map[tmKey][2]string{} // utente, percorso
	sysPrevI  uint64
	sysPrevT  uint64
	critNames = map[string]bool{"system": true, "smss.exe": true, "csrss.exe": true, "wininit.exe": true, "winlogon.exe": true,
		"services.exe": true, "lsass.exe": true, "lsaiso.exe": true, "registry": true, "memory compression": true, "secure system": true, "system idle process": true}
)

func ftU64(f syscall.Filetime) uint64 { return uint64(f.HighDateTime)<<32 | uint64(f.LowDateTime) }

func ftUnix(f syscall.Filetime) int64 { return int64(ftU64(f)/10000000) - 11644473600 }

type winEntry struct {
	pid, ppid, thr int
	name           string
}

func winSnapshot() ([]winEntry, error) {
	snap, err := syscall.CreateToolhelp32Snapshot(syscall.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return nil, err
	}
	defer syscall.CloseHandle(snap)
	var pe syscall.ProcessEntry32
	pe.Size = uint32(unsafe.Sizeof(pe))
	var out []winEntry
	if err := syscall.Process32First(snap, &pe); err != nil {
		return nil, err
	}
	for {
		out = append(out, winEntry{int(pe.ProcessID), int(pe.ParentProcessID), int(pe.Threads), syscall.UTF16ToString(pe.ExeFile[:])})
		if err := syscall.Process32Next(snap, &pe); err != nil {
			break
		}
	}
	return out, nil
}

func winUserOf(h syscall.Handle) string {
	var tok syscall.Token
	if err := syscall.OpenProcessToken(h, syscall.TOKEN_QUERY, &tok); err != nil {
		return ""
	}
	defer tok.Close()
	u, err := tok.GetTokenUser()
	if err != nil {
		return ""
	}
	acct, dom, _, err := u.User.Sid.LookupAccount("")
	if err != nil {
		return ""
	}
	if dom != "" {
		return dom + `\` + acct
	}
	return acct
}

func winPathOf(h syscall.Handle) string {
	buf := make([]uint16, 1024)
	n := uint32(len(buf))
	r, _, _ := procQueryFullProcessImageW.Call(uintptr(h), 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&n)))
	if r == 0 {
		return ""
	}
	return syscall.UTF16ToString(buf[:n])
}

func platProcs() ([]rawProc, error) {
	ents, err := winSnapshot()
	if err != nil {
		return nil, err
	}
	winMu.Lock()
	defer winMu.Unlock()
	seen := map[tmKey][2]string{}
	out := make([]rawProc, 0, len(ents))
	for _, e := range ents {
		p := rawProc{PID: e.pid, PPID: e.ppid, Name: e.name, Threads: e.thr, Protected: e.pid <= 4 || critNames[strings.ToLower(e.name)]}
		if e.pid == 0 {
			p.Name = "System Idle Process"
			out = append(out, p)
			continue
		}
		h, err := syscall.OpenProcess(procQueryLimited, false, uint32(e.pid))
		if err == nil {
			var c, x, k, u syscall.Filetime
			if syscall.GetProcessTimes(h, &c, &x, &k, &u) == nil {
				p.CPU = float64(ftU64(k)+ftU64(u)) / 1e7
				p.Start = ftUnix(c)
			}
			var m procMemCounters
			m.CB = uint32(unsafe.Sizeof(m))
			if r, _, _ := procGetProcessMemoryInfo.Call(uintptr(h), uintptr(unsafe.Pointer(&m)), uintptr(m.CB)); r != 0 {
				p.RSS = uint64(m.WorkingSetSize)
			}
			k2 := tmKey{p.PID, p.Start}
			cv, ok := winCache[k2]
			if !ok {
				cv = [2]string{winUserOf(h), winPathOf(h)}
			}
			seen[k2] = cv
			p.User, p.Cmd = cv[0], cv[1]
			syscall.CloseHandle(h)
		}
		out = append(out, p)
	}
	winCache = seen
	return out, nil
}

func platSys() sysStat {
	var idle, kern, usr syscall.Filetime
	pct := 0.0
	if r, _, _ := procGetSystemTimes.Call(uintptr(unsafe.Pointer(&idle)), uintptr(unsafe.Pointer(&kern)), uintptr(unsafe.Pointer(&usr))); r != 0 {
		i, t := ftU64(idle), ftU64(kern)+ftU64(usr)
		if sysPrevT > 0 && t > sysPrevT {
			pct = (1 - float64(i-sysPrevI)/float64(t-sysPrevT)) * 100
		}
		sysPrevI, sysPrevT = i, t
	}
	var ms memStatusEx
	ms.Length = uint32(unsafe.Sizeof(ms))
	st := sysStat{CPUPct: pct}
	if r, _, _ := procGlobalMemoryStatusEx.Call(uintptr(unsafe.Pointer(&ms))); r != 0 {
		st.MemTotal, st.MemUsed = ms.TotalPhys, ms.TotalPhys-ms.AvailPhys
	}
	return st
}

func winCollect(pid int, ents []winEntry) []int {
	kids := map[int][]int{}
	for _, e := range ents {
		if e.pid != e.ppid {
			kids[e.ppid] = append(kids[e.ppid], e.pid)
		}
	}
	var out []int
	seen := map[int]bool{pid: true}
	var walk func(int)
	walk = func(x int) {
		for _, c := range kids[x] {
			if seen[c] {
				continue
			}
			seen[c] = true
			walk(c)
			out = append(out, c)
		}
	}
	walk(pid)
	return out
}

// platKillProc: TerminateProcess (come "Termina" del Task Manager). Con tree anche i discendenti.
func platKillProc(pid int, start int64, tree bool) (int, error) {
	ents, err := winSnapshot()
	if err != nil {
		return 0, err
	}
	for _, e := range ents {
		if e.pid == pid && (e.pid <= 4 || critNames[strings.ToLower(e.name)]) {
			return 0, errors.New("processo di sistema: terminarlo fermerebbe Windows")
		}
	}
	list := []int{pid}
	if tree {
		list = append(winCollect(pid, ents), pid)
	}
	n := 0
	for _, x := range list {
		if x == os.Getpid() {
			continue
		}
		h, err := syscall.OpenProcess(procTerminate|procQueryLimited, false, uint32(x))
		if err != nil {
			if x == pid {
				return 0, fmt.Errorf("accesso negato o processo inesistente: %v", err)
			}
			continue
		}
		if x == pid && start != 0 {
			var c, e2, k, u syscall.Filetime
			if syscall.GetProcessTimes(h, &c, &e2, &k, &u) == nil {
				if d := ftUnix(c) - start; d < -2 || d > 2 {
					syscall.CloseHandle(h)
					return 0, errors.New("il processo non esiste più (PID riusato)")
				}
			}
		}
		if err := syscall.TerminateProcess(h, 1); err != nil {
			syscall.CloseHandle(h)
			if x == pid {
				return 0, err
			}
			continue
		}
		syscall.CloseHandle(h)
		n++
	}
	return n, nil
}
