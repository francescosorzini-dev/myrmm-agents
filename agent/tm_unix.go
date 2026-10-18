//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

var (
	uidNames   = map[uint32]string{}
	cmdCache   = map[tmKey]string{}
	cacheMu    sync.Mutex
	bootUnix   int64
	prevIdle   float64
	prevTotal  float64
	passwdOnce sync.Once
)

func loadPasswd() {
	for _, l := range strings.Split(readFile("/etc/passwd"), "\n") {
		f := strings.Split(l, ":")
		if len(f) > 2 {
			if id, err := strconv.ParseUint(f[2], 10, 32); err == nil {
				if _, ok := uidNames[uint32(id)]; !ok {
					uidNames[uint32(id)] = f[0]
				}
			}
		}
	}
}

func uidName(u uint32) string {
	passwdOnce.Do(loadPasswd)
	if n, ok := uidNames[u]; ok {
		return n
	}
	return strconv.FormatUint(uint64(u), 10)
}

func btime() int64 {
	if bootUnix != 0 {
		return bootUnix
	}
	for _, l := range strings.Split(readFile("/proc/stat"), "\n") {
		if strings.HasPrefix(l, "btime ") {
			bootUnix, _ = strconv.ParseInt(strings.Fields(l)[1], 10, 64)
		}
	}
	return bootUnix
}

func platProcs() ([]rawProc, error) {
	if runtime.GOOS == "darwin" {
		return darwinProcs()
	}
	ents, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	pg := uint64(os.Getpagesize())
	const hz = 100.0
	var out []rawProc
	seen := map[tmKey]bool{}
	for _, e := range ents {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		b, err := os.ReadFile("/proc/" + e.Name() + "/stat")
		if err != nil {
			continue // processo terminato nel frattempo
		}
		s := string(b)
		lp, rp := strings.IndexByte(s, '('), strings.LastIndexByte(s, ')')
		if lp < 0 || rp < lp {
			continue
		}
		rest := strings.Fields(s[rp+1:])
		if len(rest) < 22 {
			continue
		}
		ppid, _ := strconv.Atoi(rest[1])
		ut, _ := strconv.ParseFloat(rest[11], 64)
		st, _ := strconv.ParseFloat(rest[12], 64)
		thr, _ := strconv.Atoi(rest[17])
		stt, _ := strconv.ParseInt(rest[19], 10, 64)
		rss, _ := strconv.ParseUint(rest[21], 10, 64)
		p := rawProc{PID: pid, PPID: ppid, Name: s[lp+1 : rp], CPU: (ut + st) / hz, RSS: rss * pg, Threads: thr, Start: btime() + int64(float64(stt)/hz)}
		if fi, err := os.Stat("/proc/" + e.Name()); err == nil {
			if sys, ok := fi.Sys().(*syscall.Stat_t); ok {
				p.User = uidName(sys.Uid)
			}
		}
		k := tmKey{pid, p.Start}
		seen[k] = true
		cacheMu.Lock()
		cmd, ok := cmdCache[k]
		cacheMu.Unlock()
		if !ok {
			if c, err := os.ReadFile("/proc/" + e.Name() + "/cmdline"); err == nil {
				cmd = strings.TrimSpace(strings.ReplaceAll(string(c), "\x00", " "))
			}
			cacheMu.Lock()
			cmdCache[k] = cmd
			cacheMu.Unlock()
		}
		p.Cmd = cmd
		// thread del kernel (senza cmdline, figli di kthreadd) e init: non si toccano
		p.Protected = pid == 1 || pid == 2 || ppid == 2 || cmd == ""
		out = append(out, p)
	}
	cacheMu.Lock()
	for k := range cmdCache {
		if !seen[k] {
			delete(cmdCache, k)
		}
	}
	cacheMu.Unlock()
	return out, nil
}

// darwinProcs: macOS non ha /proc, si usa ps (due chiamate: nome breve e riga di comando).
func darwinProcs() ([]rawProc, error) {
	out := sh(15, "ps", "-axww", "-o", "pid=,ppid=,user=,rss=,cputime=,etime=,comm=")
	args := map[int]string{}
	for _, l := range strings.Split(sh(15, "ps", "-axww", "-o", "pid=,args="), "\n") {
		f := strings.Fields(l)
		if len(f) < 2 {
			continue
		}
		pid, _ := strconv.Atoi(f[0])
		args[pid] = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(l), f[0]))
	}
	now := time.Now().Unix()
	var res []rawProc
	for _, l := range strings.Split(out, "\n") {
		f := strings.Fields(l)
		if len(f) < 7 {
			continue
		}
		pid, _ := strconv.Atoi(f[0])
		ppid, _ := strconv.Atoi(f[1])
		rss, _ := strconv.ParseUint(f[3], 10, 64)
		name := filepath.Base(strings.Join(f[6:], " "))
		res = append(res, rawProc{PID: pid, PPID: ppid, User: f[2], RSS: rss * 1024, CPU: psClock(f[4]), Start: (now - int64(psClock(f[5]))) / 3 * 3,
			Name: name, Cmd: args[pid], Protected: pid <= 1 || name == "launchd" || name == "kernel_task"})
	}
	return res, nil
}

// psClock: "[[dd-]hh:]mm:ss[.cc]" -> secondi.
func psClock(s string) float64 {
	days := 0.0
	if i := strings.IndexByte(s, '-'); i > 0 {
		days, _ = strconv.ParseFloat(s[:i], 64)
		s = s[i+1:]
	}
	t := 0.0
	for _, p := range strings.Split(s, ":") {
		v, _ := strconv.ParseFloat(p, 64)
		t = t*60 + v
	}
	return days*86400 + t
}

func platSys() sysStat {
	if runtime.GOOS == "darwin" {
		tot, usedPct := ramGB()
		return sysStat{CPUPct: -1, MemTotal: uint64(tot * (1 << 30)), MemUsed: uint64(tot * (1 << 30) * usedPct / 100)}
	}
	idle, total := cpuTimes()
	pct := 0.0
	if total > prevTotal && prevTotal > 0 {
		pct = (1 - (idle-prevIdle)/(total-prevTotal)) * 100
	}
	prevIdle, prevTotal = idle, total
	t, a := meminfo()
	return sysStat{CPUPct: pct, MemTotal: uint64(t * 1024), MemUsed: uint64((t - a) * 1024)}
}

func procStartMatches(pid int, start int64) bool {
	procs, err := platProcs()
	if err != nil {
		return false
	}
	for _, p := range procs {
		if p.PID == pid {
			d := p.Start - start
			if d < 0 {
				d = -d
			}
			return d <= 3
		}
	}
	return false
}

func descendants(pid int, procs []rawProc) []int {
	kids := map[int][]int{}
	for _, p := range procs {
		kids[p.PPID] = append(kids[p.PPID], p.PID)
	}
	var out []int
	var walk func(int)
	walk = func(x int) {
		for _, c := range kids[x] {
			walk(c)
			out = append(out, c)
		}
	}
	walk(pid)
	return out
}

func alive(pid int) bool { return syscall.Kill(pid, 0) == nil }

// platKillProc: SIGTERM, poi SIGKILL dopo 3 s se il processo non esce. Verifica che il PID sia ancora lo stesso processo.
func platKillProc(pid int, start int64, tree bool) (int, error) {
	if pid <= 2 {
		return 0, errors.New("processo di sistema")
	}
	if start != 0 && !procStartMatches(pid, start) {
		return 0, errors.New("il processo non esiste più (o il PID è stato riusato)")
	}
	list := []int{pid}
	if tree {
		if procs, err := platProcs(); err == nil {
			list = append(descendants(pid, procs), pid)
		}
	}
	n := 0
	for _, x := range list {
		if x == os.Getpid() {
			continue
		}
		if err := syscall.Kill(x, syscall.SIGTERM); err != nil {
			if x == pid {
				return 0, fmt.Errorf("%v", err)
			}
			continue
		}
		n++
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && alive(pid) {
		time.Sleep(150 * time.Millisecond)
	}
	if alive(pid) {
		sort.Sort(sort.Reverse(sort.IntSlice(list)))
		for _, x := range list {
			if x != os.Getpid() {
				_ = syscall.Kill(x, syscall.SIGKILL)
			}
		}
	}
	return n, nil
}
