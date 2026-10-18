package main

// Distribuzione verso PC Windows dalla sonda Windows: SMB (ADMIN$) + WMI/DCOM, tramite lo script PowerShell incorporato.

import (
	"bufio"
	"bytes"
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

//go:embed deploy_win.ps1
var deployWinPS string

type winCred struct {
	U string `json:"u"`
	P string `json:"p"`
}

// psResult: ultima riga MYRMM_RESULT dell'uscita dello script e ultimo passo raggiunto.
func parsePSOutput(out string) (state, detail, step string, ok bool) {
	sc := bufio.NewScanner(strings.NewReader(out))
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		l := strings.TrimSpace(sc.Text())
		switch {
		case strings.HasPrefix(l, "MYRMM_STEP "):
			step = strings.TrimPrefix(l, "MYRMM_STEP ")
		case strings.HasPrefix(l, "MYRMM_RESULT "):
			var r struct {
				OK     bool   `json:"ok"`
				State  string `json:"state"`
				Detail string `json:"detail"`
			}
			if json.Unmarshal([]byte(strings.TrimPrefix(l, "MYRMM_RESULT ")), &r) == nil {
				state, detail, ok = r.State, r.Detail, true
			}
		}
	}
	return
}

// deployWindowsPS: solo su sonda Windows. L'account arriva dall'ambiente, mai dalla riga di comando.
func deployWindowsPS(ctx context.Context, ip string, c *winCred, mode, script, serverURL string, psExe string) (state, detail string) {
	dir, err := os.MkdirTemp("", "myrmm-dep-")
	if err != nil {
		return "fail", "cartella temporanea: " + err.Error()
	}
	defer os.RemoveAll(dir)
	main := filepath.Join(dir, "deploy.ps1")
	if err := os.WriteFile(main, []byte("\xef\xbb\xbf"+deployWinPS), 0o600); err != nil {
		return "fail", err.Error()
	}
	env := append(os.Environ(), "MYRMM_DEP_IP="+ip, "MYRMM_DEP_U="+c.U, "MYRMM_DEP_P="+c.P, "MYRMM_DEP_MODE="+mode, "MYRMM_DEP_URL="+serverURL)
	if mode == "run" {
		sp := filepath.Join(dir, "install.ps1")
		if err := os.WriteFile(sp, []byte("\xef\xbb\xbf"+script), 0o600); err != nil {
			return "fail", err.Error()
		}
		env = append(env, "MYRMM_DEP_SCRIPT="+sp)
	}
	to := 2 * time.Minute
	if mode == "run" {
		to = 12 * time.Minute
	}
	cctx, cancel := context.WithTimeout(ctx, to)
	defer cancel()
	cmd := exec.CommandContext(cctx, psExe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", main)
	cmd.Env = env
	var out bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &out
	err = cmd.Run()
	state, detail, step, ok := parsePSOutput(out.String())
	if ok {
		return state, strings.ReplaceAll(detail, c.P, "***")
	}
	if cctx.Err() != nil {
		return "fail", fmt.Sprintf("tempo scaduto durante «%s»", step)
	}
	msg := strings.ReplaceAll(tailLines(out.String(), 3), c.P, "***")
	if err != nil {
		return "fail", fmt.Sprintf("PowerShell: %v %s", err, msg)
	}
	return "fail", "risposta non riconosciuta: " + msg
}
