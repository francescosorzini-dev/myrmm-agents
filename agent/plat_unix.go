//go:build !windows

package main

// Piattaforme Linux e macOS: i job sono script shell (bash/sh) oppure, se la prima riga è
// un shebang (#!/usr/bin/env pwsh, #!/usr/bin/python3…), eseguiti con quell'interprete.
// L'inventario è raccolto in Go nativo: nessuna dipendenza (niente PowerShell).

import (
	"bufio"
	"context"
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func dataDir() string {
	if d := os.Getenv("MYRMM_DIR"); d != "" {
		return d
	}
	if runtime.GOOS == "darwin" {
		return "/Library/Application Support/myrmm"
	}
	return "/etc/myrmm"
}

func platTag() string { return runtime.GOOS + "/" + goArch() }

func shellPath() string {
	for _, p := range []string{"/bin/bash", "/usr/bin/bash", "/bin/sh"} {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return "/bin/sh"
}

func jobEnv() []string {
	env := os.Environ()
	hasPath, hasHome := false, false
	for _, e := range env {
		hasPath = hasPath || strings.HasPrefix(e, "PATH=")
		hasHome = hasHome || strings.HasPrefix(e, "HOME=")
	}
	if !hasPath {
		env = append(env, "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
	}
	if !hasHome {
		env = append(env, "HOME=/root")
	}
	return env
}

// platCommand prepara lo script: shebang -> file temporaneo eseguibile; altrimenti shell -c.
func platCommand(ctx context.Context, script string) (*exec.Cmd, func()) {
	cleanup := func() {}
	var cmd *exec.Cmd
	if strings.HasPrefix(script, "#!") {
		f, err := os.CreateTemp("", "myrmm-job-*")
		if err == nil {
			_, _ = f.WriteString(script)
			_ = f.Close()
			_ = os.Chmod(f.Name(), 0o700)
			name := f.Name()
			cleanup = func() { _ = os.Remove(name) }
			cmd = exec.CommandContext(ctx, name)
		}
	}
	if cmd == nil {
		cmd = exec.CommandContext(ctx, shellPath(), "-c", script)
	}
	cmd.Env = jobEnv()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true} // gruppo proprio: kill dell'intero albero
	return cmd, cleanup
}

func platKill(cmd *exec.Cmd) error {
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		return cmd.Process.Kill()
	}
	return nil
}

// restartSelf riavvia il servizio col nuovo binario.
func restartSelf() {
	if runtime.GOOS == "linux" {
		if _, err := os.Stat("/run/systemd/system"); err == nil { // systemd è davvero PID 1 (sd_booted)
			c := exec.Command("sh", "-c", "sleep 2; systemctl restart myrmm-agent")
			c.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
			if c.Start() == nil {
				return
			}
		}
	}
	// launchd (KeepAlive) o init che riavvia il servizio: basta uscire
	go func() { time.Sleep(2 * time.Second); os.Exit(0) }()
}

func restartHard() { restartSelf() }

// ---- helper -----------------------------------------------------------------

func sh(timeoutSec int, name string, args ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
	defer cancel()
	out, _ := exec.CommandContext(ctx, name, args...).Output()
	return strings.TrimSpace(string(out))
}

func readFile(p string) string {
	b, _ := os.ReadFile(p)
	return strings.TrimSpace(string(b))
}

func osRelease() map[string]string {
	m := map[string]string{}
	for _, l := range strings.Split(readFile("/etc/os-release"), "\n") {
		if k, v, ok := strings.Cut(l, "="); ok {
			m[k] = strings.Trim(v, `"'`)
		}
	}
	return m
}

func meminfo() (totalKB, availKB float64) {
	for _, l := range strings.Split(readFile("/proc/meminfo"), "\n") {
		f := strings.Fields(l)
		if len(f) < 2 {
			continue
		}
		v, _ := strconv.ParseFloat(f[1], 64)
		switch f[0] {
		case "MemTotal:":
			totalKB = v
		case "MemAvailable:":
			availKB = v
		}
	}
	return
}

func cpuTimes() (idle, total float64) {
	for _, l := range strings.Split(readFile("/proc/stat"), "\n") {
		if !strings.HasPrefix(l, "cpu ") {
			continue
		}
		f := strings.Fields(l)[1:]
		for i, x := range f {
			v, _ := strconv.ParseFloat(x, 64)
			total += v
			if i == 3 || i == 4 { // idle + iowait
				idle += v
			}
		}
		return
	}
	return
}

func cpuPct() float64 {
	if runtime.GOOS == "darwin" {
		out := sh(15, "top", "-l", "2", "-n", "0", "-s", "1")
		m := regexp.MustCompile(`([\d.]+)% idle`).FindAllStringSubmatch(out, -1)
		if len(m) > 0 {
			idle, _ := strconv.ParseFloat(m[len(m)-1][1], 64)
			return float64(int(100 - idle + 0.5))
		}
		return 0
	}
	i1, t1 := cpuTimes()
	time.Sleep(400 * time.Millisecond)
	i2, t2 := cpuTimes()
	if t2 <= t1 {
		return 0
	}
	return float64(int((1-(i2-i1)/(t2-t1))*100 + 0.5))
}

var realFS = map[string]bool{"ext2": true, "ext3": true, "ext4": true, "xfs": true, "btrfs": true, "zfs": true, "f2fs": true,
	"vfat": true, "exfat": true, "ntfs": true, "ntfs3": true, "jfs": true, "reiserfs": true, "apfs": true, "hfs": true}

type volume struct {
	ID, FS     string
	Size, Free float64 // GB
}

func volumes() []volume {
	var out []volume
	stat := func(mp, fs string) {
		var st syscall.Statfs_t
		if syscall.Statfs(mp, &st) != nil || st.Blocks == 0 {
			return
		}
		bs := float64(uint64(st.Bsize))
		if float64(uint64(st.Blocks))*float64(uint64(st.Bsize)) < 1<<30 { // < 1 GB (EFI, immagini): ignorati
			return
		}
		out = append(out, volume{ID: mp, FS: fs, Size: round1(float64(uint64(st.Blocks)) * bs / (1 << 30)), Free: round1(float64(uint64(st.Bavail)) * bs / (1 << 30))})
	}
	if runtime.GOOS == "darwin" {
		stat("/", "apfs")
		return out
	}
	seen := map[string]bool{}
	for _, l := range strings.Split(readFile("/proc/mounts"), "\n") {
		f := strings.Fields(l)
		if len(f) < 4 || !realFS[f[2]] || seen[f[0]] {
			continue
		}
		if ro := "," + f[3] + ","; strings.Contains(ro, ",ro,") { // montaggi in sola lettura (immagini, snap): non interessano
			continue
		}
		seen[f[0]] = true
		stat(f[1], f[2])
	}
	return out
}

func ipv4s() []string {
	var ips []string
	ifs, _ := net.Interfaces()
	for _, i := range ifs {
		if i.Flags&net.FlagUp == 0 || i.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, _ := i.Addrs()
		for _, a := range addrs {
			if ip, _, err := net.ParseCIDR(a.String()); err == nil && ip.To4() != nil && !ip.IsLinkLocalUnicast() {
				ips = append(ips, ip.String())
			}
		}
	}
	return ips
}

func lastBoot() string {
	if runtime.GOOS == "darwin" {
		if m := regexp.MustCompile(`sec = (\d+)`).FindStringSubmatch(sh(5, "sysctl", "-n", "kern.boottime")); m != nil {
			s, _ := strconv.ParseInt(m[1], 10, 64)
			return time.Unix(s, 0).Format(time.RFC3339)
		}
		return ""
	}
	for _, l := range strings.Split(readFile("/proc/stat"), "\n") {
		if strings.HasPrefix(l, "btime ") {
			s, _ := strconv.ParseInt(strings.Fields(l)[1], 10, 64)
			return time.Unix(s, 0).Format(time.RFC3339)
		}
	}
	return ""
}

func loggedUser() string {
	if runtime.GOOS == "darwin" {
		u := sh(5, "stat", "-f", "%Su", "/dev/console")
		if u == "root" {
			return ""
		}
		return u
	}
	if f := strings.Fields(sh(5, "who")); len(f) > 0 {
		return f[0]
	}
	return ""
}

func dmi(name string) string { return readFile("/sys/class/dmi/id/" + name) }

type hw struct{ Man, Model, Serial string }

func hardware() hw {
	if runtime.GOOS == "darwin" {
		serial := ""
		if m := regexp.MustCompile(`"IOPlatformSerialNumber" = "([^"]+)"`).FindStringSubmatch(sh(10, "ioreg", "-c", "IOPlatformExpertDevice", "-d", "2")); m != nil {
			serial = m[1]
		}
		return hw{"Apple", sh(5, "sysctl", "-n", "hw.model"), serial}
	}
	return hw{dmi("sys_vendor"), dmi("product_name"), dmi("product_serial")}
}

func osNames() (name, version, build string) {
	if runtime.GOOS == "darwin" {
		return sh(5, "sw_vers", "-productName") + " " + sh(5, "sw_vers", "-productVersion"), sh(5, "sw_vers", "-productVersion"), sh(5, "sw_vers", "-buildVersion")
	}
	r := osRelease()
	name = r["PRETTY_NAME"]
	if name == "" {
		name = "Linux"
	}
	return name, r["VERSION_ID"], readFile("/proc/sys/kernel/osrelease")
}

func ramGB() (total float64, usedPct float64) {
	if runtime.GOOS == "darwin" {
		b, _ := strconv.ParseFloat(sh(5, "sysctl", "-n", "hw.memsize"), 64)
		total = b
		vm := sh(5, "vm_stat")
		ps := 4096.0
		if m := regexp.MustCompile(`page size of (\d+)`).FindStringSubmatch(vm); m != nil {
			ps, _ = strconv.ParseFloat(m[1], 64)
		}
		var free float64
		for _, k := range []string{"Pages free", "Pages inactive", "Pages speculative"} {
			if m := regexp.MustCompile(k + `:\s+(\d+)`).FindStringSubmatch(vm); m != nil {
				v, _ := strconv.ParseFloat(m[1], 64)
				free += v * ps
			}
		}
		if b > 0 {
			usedPct = float64(int((b-free)/b*100 + 0.5))
		}
		return round1(b / (1 << 30)), usedPct
	}
	t, a := meminfo()
	if t > 0 {
		usedPct = float64(int((t-a)/t*100 + 0.5))
	}
	return round1(t / (1 << 20)), usedPct
}

// ---- inventario leggero (a ogni heartbeat) ---------------------------------

func platInventory() (map[string]any, error) {
	host, _ := os.Hostname()
	name, ver, build := osNames()
	ram, ramPct := ramGB()
	h := hardware()
	var disks []map[string]any
	for _, v := range volumes() {
		disks = append(disks, map[string]any{"DeviceID": v.ID, "size_gb": v.Size, "free_gb": v.Free})
	}
	ips := ipv4s()
	if disks == nil {
		disks = []map[string]any{}
	}
	if ips == nil {
		ips = []string{}
	}
	return map[string]any{
		"hostname": host, "os": name, "os_version": ver, "os_build": build,
		"ram_gb": ram, "cpu": runtime.NumCPU(), "cpu_pct": cpuPct(), "ram_pct": ramPct,
		"manufacturer": h.Man, "model": h.Model, "serial": h.Serial,
		"last_boot": lastBoot(), "logged_user": loggedUser(),
		"disks": disks, "ips": ips,
	}, nil
}

// ---- inventario completo (ogni N ore o su richiesta) -----------------------

func cpuModel() (model string, cores int) {
	if runtime.GOOS == "darwin" {
		c, _ := strconv.Atoi(sh(5, "sysctl", "-n", "hw.physicalcpu"))
		return sh(5, "sysctl", "-n", "machdep.cpu.brand_string"), c
	}
	set := map[string]bool{}
	var phys, core string
	for _, l := range strings.Split(readFile("/proc/cpuinfo"), "\n") {
		k, v, ok := strings.Cut(l, ":")
		if !ok {
			continue
		}
		k, v = strings.TrimSpace(k), strings.TrimSpace(v)
		switch k {
		case "model name", "Model":
			if model == "" {
				model = v
			}
		case "physical id":
			phys = v
		case "core id":
			core = v
			set[phys+"/"+core] = true
		}
	}
	cores = len(set)
	if cores == 0 {
		cores = runtime.NumCPU()
	}
	return
}

func packages() []map[string]any {
	out := []map[string]any{}
	add := func(raw, sep string) {
		for _, l := range strings.Split(raw, "\n") {
			f := strings.Split(l, sep)
			if len(f) >= 2 && f[0] != "" {
				p := ""
				if len(f) > 2 {
					p = f[2]
				}
				out = append(out, map[string]any{"name": f[0], "version": f[1], "publisher": p, "install_date": ""})
			}
		}
	}
	switch {
	case runtime.GOOS == "darwin":
		var sp struct {
			Items []struct {
				Name    string `json:"_name"`
				Version string `json:"version"`
				From    string `json:"obtained_from"`
			} `json:"SPApplicationsDataType"`
		}
		if json.Unmarshal([]byte(sh(120, "system_profiler", "SPApplicationsDataType", "-json")), &sp) == nil {
			for _, i := range sp.Items {
				out = append(out, map[string]any{"name": i.Name, "version": i.Version, "publisher": i.From, "install_date": ""})
			}
		}
	case exists("dpkg-query"):
		add(sh(60, "dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"), "\t")
	case exists("rpm"):
		add(sh(60, "rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\n"), "\t")
	case exists("apk"):
		for _, l := range strings.Split(sh(30, "apk", "info", "-v"), "\n") {
			if i := strings.LastIndex(l, "-"); i > 0 {
				if j := strings.LastIndex(l[:i], "-"); j > 0 {
					out = append(out, map[string]any{"name": l[:j], "version": l[j+1:], "publisher": "", "install_date": ""})
				}
			}
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return strings.ToLower(out[i]["name"].(string)) < strings.ToLower(out[j]["name"].(string))
	})
	return out
}

func exists(bin string) bool { _, err := exec.LookPath(bin); return err == nil }

func services() []map[string]any {
	out := []map[string]any{}
	if runtime.GOOS != "linux" || !exists("systemctl") {
		return out
	}
	run := map[string]bool{}
	for _, l := range strings.Split(sh(20, "systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager", "--plain"), "\n") {
		if f := strings.Fields(l); len(f) > 0 {
			run[f[0]] = true
		}
	}
	for _, l := range strings.Split(sh(20, "systemctl", "list-unit-files", "--type=service", "--state=enabled", "--no-legend", "--no-pager"), "\n") {
		f := strings.Fields(l)
		if len(f) == 0 || strings.HasSuffix(f[0], "@.service") {
			continue
		}
		st := "Stopped"
		if run[f[0]] {
			st = "Running"
		}
		out = append(out, map[string]any{"name": strings.TrimSuffix(f[0], ".service"), "display": f[0], "state": st})
	}
	return out
}

func localUsers() (users, admins []map[string]any) {
	users, admins = []map[string]any{}, []map[string]any{}
	minUID := 1000
	if runtime.GOOS == "darwin" {
		minUID = 500
	}
	if f, err := os.Open("/etc/passwd"); err == nil {
		sc := bufio.NewScanner(f)
		for sc.Scan() {
			p := strings.Split(sc.Text(), ":")
			if len(p) < 7 {
				continue
			}
			uid, _ := strconv.Atoi(p[2])
			login := !strings.HasSuffix(p[6], "nologin") && !strings.HasSuffix(p[6], "false")
			if (uid >= minUID && uid < 60000 && p[0] != "nobody") || p[0] == "root" {
				users = append(users, map[string]any{"Name": p[0], "enabled": login, "last_logon": ""})
			}
		}
		f.Close()
	}
	if runtime.GOOS == "darwin" {
		fields := strings.Fields(strings.TrimPrefix(sh(5, "dscl", ".", "-read", "/Groups/admin", "GroupMembership"), "GroupMembership:"))
		for _, m := range fields {
			admins = append(admins, map[string]any{"member": m, "type": "User"})
		}
		return
	}
	for _, l := range strings.Split(readFile("/etc/group"), "\n") {
		p := strings.Split(l, ":")
		if len(p) == 4 && (p[0] == "sudo" || p[0] == "wheel" || p[0] == "admin") {
			for _, m := range strings.Split(p[3], ",") {
				if m != "" {
					admins = append(admins, map[string]any{"member": m, "type": "User (" + p[0] + ")"})
				}
			}
		}
	}
	return
}

func physicalDisks() []map[string]any {
	out := []map[string]any{}
	if runtime.GOOS != "linux" || !exists("lsblk") {
		return out
	}
	for _, l := range strings.Split(sh(10, "lsblk", "-dn", "-b", "-P", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN,TYPE"), "\n") {
		kv := map[string]string{}
		for _, m := range regexp.MustCompile(`(\w+)="([^"]*)"`).FindAllStringSubmatch(l, -1) {
			kv[m[1]] = m[2]
		}
		if kv["TYPE"] != "disk" {
			continue
		}
		sz, _ := strconv.ParseFloat(kv["SIZE"], 64)
		out = append(out, map[string]any{"model": strings.TrimSpace(kv["MODEL"]), "size_gb": round1(sz / (1 << 30)), "bus": kv["TRAN"], "serial": strings.TrimSpace(kv["SERIAL"])})
	}
	return out
}

func networkInfo() []map[string]any {
	out := []map[string]any{}
	gwDev, gw := "", ""
	if m := regexp.MustCompile(`default via (\S+) dev (\S+)`).FindStringSubmatch(sh(5, "ip", "route", "show", "default")); m != nil {
		gw, gwDev = m[1], m[2]
	}
	var dns []string
	for _, l := range strings.Split(readFile("/etc/resolv.conf"), "\n") {
		if f := strings.Fields(l); len(f) == 2 && f[0] == "nameserver" {
			dns = append(dns, f[1])
		}
	}
	ifs, _ := net.Interfaces()
	for _, i := range ifs {
		if i.Flags&net.FlagUp == 0 || i.Flags&net.FlagLoopback != 0 {
			continue
		}
		var ips []string
		addrs, _ := i.Addrs()
		for _, a := range addrs {
			if ip, _, err := net.ParseCIDR(a.String()); err == nil && ip.To4() != nil && !ip.IsLinkLocalUnicast() {
				ips = append(ips, ip.String())
			}
		}
		if len(ips) == 0 {
			continue
		}
		e := map[string]any{"desc": i.Name, "mac": i.HardwareAddr.String(), "ip": ips, "gw": []string{}, "dns": []string{}, "dhcp": ""}
		if i.Name == gwDev {
			e["gw"] = []string{gw}
			e["dns"] = dns
		}
		out = append(out, e)
	}
	return out
}

func platFullInventory() (map[string]any, error) {
	host, _ := os.Hostname()
	name, ver, build := osNames()
	ram, _ := ramGB()
	h := hardware()
	cpu, cores := cpuModel()
	disks := []map[string]any{}
	for _, v := range volumes() {
		disks = append(disks, map[string]any{"id": v.ID, "size_gb": v.Size, "free_gb": v.Free, "fs": v.FS})
	}
	users, admins := localUsers()
	domain := ""
	if exists("hostname") && runtime.GOOS == "linux" {
		domain = sh(3, "hostname", "-d")
	}
	biosV, biosD, board := dmi("bios_version"), dmi("bios_date"), strings.TrimSpace(dmi("board_vendor")+" "+dmi("board_name"))
	arch := sh(3, "uname", "-m")
	if arch == "" {
		arch = runtime.GOARCH
	}
	return map[string]any{
		"system": map[string]any{"hostname": host, "os": name, "os_version": ver, "os_build": build, "os_arch": arch,
			"install_date": "", "last_boot": lastBoot(), "domain": domain, "part_of_domain": domain != "", "logged_user": loggedUser()},
		"hardware": map[string]any{"manufacturer": h.Man, "model": h.Model, "serial": h.Serial,
			"bios_version": biosV, "bios_date": biosD, "baseboard": board,
			"cpu": cpu, "cpu_cores": cores, "cpu_threads": runtime.NumCPU(), "ram_gb": ram, "ram_modules": []any{}, "gpu": []any{}},
		"disks_physical": physicalDisks(), "disks_logical": disks, "network": networkInfo(),
		"software": packages(), "hotfix": []any{}, "services_auto": services(),
		"local_users": users, "local_admins": admins, "security": unixSecurity(admins),
		"collected_at": time.Now().UTC().Format(time.RFC3339),
	}, nil
}

// platSessions: sessioni utente aperte. Linux: loginctl (stato, blocco, tipo); macOS: utente della console.
func platSessions() []sessInfo {
	if runtime.GOOS == "darwin" {
		if u := loggedUser(); u != "" {
			return []sessInfo{{User: u, State: "attiva", Via: "console"}}
		}
		return nil
	}
	var out []sessInfo
	if exists("loginctl") {
		for _, ln := range strings.Split(sh(5, "loginctl", "list-sessions", "--no-legend"), "\n") {
			f := strings.Fields(ln)
			if len(f) < 3 {
				continue
			}
			props := map[string]string{}
			for _, l := range strings.Split(sh(5, "loginctl", "show-session", f[0], "-p", "Name", "-p", "State", "-p", "Type", "-p", "LockedHint", "-p", "Remote", "-p", "Class"), "\n") {
				if k, v, ok := strings.Cut(l, "="); ok {
					props[k] = strings.TrimSpace(v)
				}
			}
			if props["Class"] != "" && props["Class"] != "user" {
				continue // greeter, lock-screen: non sono utenti
			}
			st := "inattiva"
			switch props["State"] {
			case "active":
				st = "attiva"
			case "closing":
				continue
			}
			if props["LockedHint"] == "yes" {
				st = "bloccata"
			}
			via := "tty"
			switch {
			case props["Remote"] == "yes":
				via = "ssh"
			case props["Type"] == "x11" || props["Type"] == "wayland" || props["Type"] == "mir":
				via = "console"
			}
			name := props["Name"]
			if name == "" {
				name = f[2]
			}
			out = append(out, sessInfo{User: name, State: st, Via: via})
		}
		if len(out) > 0 {
			return out
		}
	}
	for _, ln := range strings.Split(sh(5, "who"), "\n") { // senza systemd-logind
		if f := strings.Fields(ln); len(f) > 0 {
			via := "tty"
			if strings.HasPrefix(ln, f[0]+" pts/") {
				via = "ssh"
			}
			out = append(out, sessInfo{User: f[0], State: "attiva", Via: via})
		}
	}
	return out
}

// platUninstall: rimuove servizio, binario e dati. Gira in un processo staccato; i file si cancellano PRIMA
// dell'arresto del servizio (che uccide anche questo processo).
func platUninstall(exe, data string) {
	q := func(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }
	var sb strings.Builder
	sb.WriteString("sleep 2\n")
	sb.WriteString(q(exe) + " uninstall >/dev/null 2>&1\n")
	if runtime.GOOS == "linux" {
		sb.WriteString("systemctl disable myrmm-agent >/dev/null 2>&1\nrm -f /etc/systemd/system/myrmm-agent.service /lib/systemd/system/myrmm-agent.service /etc/init.d/myrmm-agent\n")
	}
	for _, f := range []string{exe, exe + ".new", exe + ".old"} {
		sb.WriteString("rm -f " + q(f) + "\n")
	}
	sb.WriteString(uninstallCleanData(data))
	sb.WriteString("rmdir " + q(filepath.Dir(exe)) + " >/dev/null 2>&1\n")
	if runtime.GOOS == "linux" {
		sb.WriteString("systemctl daemon-reload >/dev/null 2>&1\nsystemctl stop myrmm-agent >/dev/null 2>&1\n")
	} else {
		sb.WriteString("launchctl remove myrmm-agent >/dev/null 2>&1\nrm -f /Library/LaunchDaemons/myrmm-agent.plist\n")
	}
	c := exec.Command("sh", "-c", sb.String())
	c.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	_ = c.Start()
}

// uninstallCleanData: cancella la cartella dati solo se è quella dedicata (nome "myrmm"), altrimenti solo i file noti.
func uninstallCleanData(data string) string {
	q := func(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }
	if strings.EqualFold(filepath.Base(data), "myrmm") || strings.EqualFold(filepath.Base(data), "myrmm-agent") {
		return "rm -rf " + q(data) + "\n"
	}
	s := ""
	for _, f := range []string{"state.json", "config.json", "enroll-status.txt", "uninstalling.flag"} {
		s += "rm -f " + q(filepath.Join(data, f)) + "\n"
	}
	return s
}

// unixSecurity: prove di sicurezza di Linux/macOS. Solo ciò che si rileva con certezza: amministratori locali, cifratura dei volumi
// (lsblk, Linux) e firewall (ufw, firewalld, nftables). Antivirus e backup non vengono rilevati: restano «da integrare» nel dossier.
func unixSecurity(admins []map[string]any) map[string]any {
	sec := map[string]any{}
	names := []any{}
	for _, a := range admins {
		if n, _ := a["member"].(string); n != "" {
			names = append(names, n)
		}
	}
	sec["local_admins"] = names
	if runtime.GOOS != "linux" {
		return sec
	}
	if exists("lsblk") {
		if vols, ok := lsblkEncryption(sh(10, "lsblk", "-J", "-o", "NAME,TYPE,MOUNTPOINT")); ok && len(vols) > 0 {
			sec["bitlocker"] = map[string]any{"volumes": vols}
		}
	}
	var ufw, fwd, nft string
	if exists("ufw") {
		ufw = sh(5, "ufw", "status")
	}
	if exists("firewall-cmd") {
		fwd = strings.TrimSpace(sh(5, "firewall-cmd", "--state"))
	}
	if exists("nft") {
		nft = sh(5, "nft", "list", "ruleset")
	}
	if a, ok := firewallActive(ufw, fwd, nft); ok {
		sec["firewall"] = map[string]any{"domain": a, "private": a, "public": a}
	}
	return sec
}
