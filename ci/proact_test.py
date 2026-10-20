#!/usr/bin/env python3
"""Proattività dei pacchetti (1.61.0): livelli solo monitoraggio / proposti / automatici, classi sicuro / a rischio, osservazione per cliente,
tetto ai tentativi, ticket aperto e chiuso, passaggio di livello, soglia sfumata del disco. Server PHP temporaneo con agent simulato.
Uso: python3 ci/proact_test.py"""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, urllib.request, urllib.error
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8799; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"; H = {"Origin": f"http://127.0.0.1:{PORT}"}
tmp = tempfile.mkdtemp(prefix="myrmm-pro-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = bad = 0
def rec(n, c, x=""):
    global ok, bad
    if c: ok += 1; print("OK  ", n)
    else: bad += 1; print("FALLITO", n, str(x)[:300])
DB = os.path.join(srv, "data", "myrmm.sqlite")
def q(sql, *a):
    c = sqlite3.connect(DB, timeout=20); r = c.execute(sql, a).fetchall(); c.commit(); c.close(); return r
def ex(sql, *a): q(sql, *a)
def api(act, body, key="k1"):
    r = urllib.request.Request(BASE + "?action=" + act, data=json.dumps(body).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read().decode() or "{}")
INV = {"os": "Windows Server 2022", "platform": "windows/amd64", "agent_version": "1.60.0", "cpu_pct": 5, "ram_pct": 10, "ram_gb": 16, "disks": [{"DeviceID": "C:", "size_gb": 200, "free_gb": 150}], "ips": ["10.0.0.5"]}
def hb(key="k1"): return api("heartbeat", {"inventory": INV, "light": False}, key)
try:
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers=H), timeout=5)
    except Exception: pass
    time.sleep(1)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ex("INSERT OR IGNORE INTO sites(name,created) VALUES('Acme',?)", now)
    ex("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('SRV-A','Windows Server 2022','k1','Acme',?, '{}',?)", now, now)
    ex("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES('SRV-B','Windows Server 2022','k2','Beta',?, '{}',?)", now, now)
    ex("INSERT OR IGNORE INTO sites(name,created) VALUES('Beta',?)", now)
    ex("DELETE FROM meta WHERE k LIKE 'tk_%'") if False else None
    hb("k1"); hb("k2")
    with sync_playwright() as pw:
        br = pw.chromium.launch(); c = br.new_context(); p = c.new_page()
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        except Exception: pass
        p.wait_for_selector(".rail")
        def post(act, **form): return c.request.post(BASE + "?action=" + act, form={k: str(v) for k, v in form.items()}, headers=H, max_redirects=0)

        # ---- 1. pacchetti predefiniti: diagnosi, risolutivi e classe
        pid = q("SELECT id FROM packs WHERE name='Windows: base (server e postazioni)'")[0][0]
        def item(s, v=None):
            r = q("SELECT diag_name, response_name, fix_class FROM pack_items WHERE pack_id=? AND script_name=?", pid, s)
            return r[0] if r else None
        it = item("Monitor: spazio libero sui volumi")
        rec("pacchetto base: spazio disco → diagnosi e pulizia sicura dei temporanei", it and it[1] == "Risolutivo: pulizia sicura dei file temporanei" and it[2] == "safe" and it[0], it)
        it = item("Monitor: Windows Firewall attivo"); rec("pacchetto base: firewall → risolutivo «a rischio» (solo proposto)", it and it[1].startswith("Windows: abilita Windows Firewall") and it[2] == "risky", it)
        it = item("Monitor: servizi automatici fermi"); rec("pacchetto base: servizi fermi → avvio servizi, sicuro", it and it[1].startswith("Risolutivo: avvia i servizi") and it[2] == "safe", it)
        it = item("Monitor evento: Windows Update fallito"); rec("pacchetto base: Windows Update fallito è nel pacchetto con reset componenti", it and it[1] == "Windows: reset componenti Windows Update", it)
        it = item("Monitor: salute dischi fisici (SMART)"); rec("pacchetto base: SMART resta senza risolutivo (decide una persona)", it and it[1] == "" and it[2] == "", it)
        ws = q("SELECT id FROM packs WHERE name='Windows workstation'")[0][0]
        rec("pacchetto workstation: monitor dello spooler con risolutivo", q("SELECT response_name FROM pack_items WHERE pack_id=? AND script_name='Monitor: servizio in esecuzione' AND vars LIKE '%Spooler%'", ws) == [("Risolutivo: spooler di stampa (ferma, svuota la coda, riavvia)",)])
        dc = q("SELECT id FROM packs WHERE name='Domain controller'")[0][0]
        rec("domain controller: servizi NTDS/DNS a rischio (solo proposto)", q("SELECT COUNT(*) FROM pack_items WHERE pack_id=? AND fix_class='risky' AND response_name<>''", dc) == [(2,)])
        for nm in ("Risolutivo: pulizia sicura dei file temporanei", "Risolutivo: spooler di stampa (ferma, svuota la coda, riavvia)", "Diagnosi: servizi fermi (dipendenze, account ed eventi recenti)", "Risolutivo Linux: riavvia le unità systemd in errore"):
            rec("libreria: «%s» presente" % nm[:50], q("SELECT COUNT(*) FROM scripts WHERE name=?", nm) == [(1,)])

        # ---- 2. applicazione con livello «automatico»
        post("site_proact", id=q("SELECT id FROM sites WHERE name='Acme'")[0][0], days=0)
        r = post("pack_apply", pack_id=pid, site="Acme", level="auto")
        rules = q("SELECT COUNT(*), SUM(proact='auto') FROM rules WHERE pack_id=? AND pack_scope='Cliente: Acme'", pid)
        rec("applica con «automatici»: tutte le regole nascono con proact=auto", rules[0][0] > 5 and rules[0][0] == rules[0][1], rules)
        rec("regola del disco porta risolutivo, diagnosi e classe", q("SELECT fix_class, response_script_id>0, diag_script_id>0 FROM rules r WHERE pack_id=? AND script_id=(SELECT id FROM scripts WHERE name='Monitor: spazio libero sui volumi')", pid) == [("safe", 1, 1)])
        hb("k1"); time.sleep(.3); hb("k1")
        sch = q("SELECT s.id, sc.name, s.proact, s.fix_class FROM schedules s JOIN scripts sc ON sc.id=s.script_id WHERE s.device_id=(SELECT id FROM devices WHERE api_key='k1')")
        sid = {n: i for i, n, _, _ in sch}
        rec("le schedulazioni del device ereditano proattività e classe", len(sch) > 5 and all(x[2] == "auto" for x in sch), sch[:3])
        did = q("SELECT id FROM devices WHERE api_key='k1'")[0][0]
        def fail(name, msg="Problema"):
            s = sid[name]
            ex("INSERT INTO jobs(device_id,script,timeout,status,created,origin) VALUES(?,?,?,?,?,?)", did, "x", 60, "sent", now, f"schedule:{s}")
            jid = q("SELECT MAX(id) FROM jobs")[0][0]
            api("result", {"job_id": jid, "exit_code": 1, "stdout": msg, "stderr": "", "duration": 1})
            return s
        def ok_(name):
            s = sid[name]
            ex("INSERT INTO jobs(device_id,script,timeout,status,created,origin) VALUES(?,?,?,?,?,?)", did, "x", 60, "sent", now, f"schedule:{s}")
            api("result", {"job_id": q("SELECT MAX(id) FROM jobs")[0][0], "exit_code": 0, "stdout": "OK", "stderr": "", "duration": 1})
        # ---- 3. monitor sicuro, livello automatico: diagnosi + risolutivo partono da soli, ticket aperto
        s = fail("Monitor: spazio libero sui volumi", "Poco spazio: C: libero 6,0 GB su 200 (soglia 20,0 GB)")
        tk = q("SELECT id, status, by_user FROM tickets WHERE device_id=? AND alert_type=?", did, f"script:{s}")
        rec("alert di un monitor sicuro: si apre un ticket anche se le impostazioni ticket sono minime", len(tk) == 1 and tk[0][1] == "open", tk)
        jobs = q("SELECT origin, script FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)
        rec("partono due job nel ticket: diagnosi e risolutivo", len(jobs) == 2, jobs)
        rr = q("SELECT auto_id, mode, state, name FROM remed_runs WHERE device_id=?", did)
        rec("esecuzione registrata come automatica, in verifica, legata alla regola del pacchetto", len(rr) == 1 and rr[0][0] == -s and rr[0][1] == "auto" and rr[0][2] == "running", rr)
        ok_("Monitor: spazio libero sui volumi")
        rr = q("SELECT state FROM remed_runs WHERE device_id=?", did); tk = q("SELECT status FROM tickets WHERE device_id=? AND alert_type=?", did, f"script:{s}")
        rec("alert rientrato: risolto e ticket chiuso da solo (aperto e chiuso)", rr == [("fixed",)] and tk == [("closed",)], (rr, tk))
        # ---- 4. monitor a rischio: solo proposto, mai automatico
        n0 = q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0]
        s2 = fail("Monitor: Windows Firewall attivo", "Firewall DISATTIVATO su: Public")
        n1 = q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0]
        rec("monitor a rischio (firewall) in livello automatico: nessun job, resta proposto", n1 == n0, (n0, n1))
        note = q("SELECT body FROM ticket_notes WHERE ticket_id=(SELECT id FROM tickets WHERE device_id=? AND alert_type=?) AND body LIKE 'Risolutivo disponibile%'", did, f"script:{s2}")
        rec("il ticket riceve la nota «Risolutivo disponibile» con il motivo", len(note) == 1 and "non classificato" in note[0][0], note)
        al = q("SELECT id FROM alerts WHERE device_id=? AND type=? AND status='open'", did, f"script:{s2}")[0][0]
        post("rem_run", alert_id=al, auto_id=-s2, back="?view=alerts")
        rec("rem_run lancia il risolutivo proposto di un pacchetto con un clic", q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0] == n1 + 1 and q("SELECT COUNT(*) FROM remed_runs WHERE alert_id=? AND auto_id=?", al, -s2)[0][0] == 1)
        ok_("Monitor: Windows Firewall attivo")
        # ---- 5. osservazione per cliente: l'automatico resta proposto
        siteid = q("SELECT id FROM sites WHERE name='Acme'")[0][0]
        post("site_proact", id=siteid, days=14, start=1)
        until = q("SELECT proact_obs_until FROM sites WHERE id=?", siteid)[0][0]
        rec("osservazione impostata per 14 giorni", until > time.strftime("%Y-%m-%d", time.gmtime()), until)
        n0 = q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0]
        s3 = fail("Monitor: servizi automatici fermi", "Servizi automatici fermi: Foo")
        n1 = q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0]
        rec("cliente in osservazione: parte solo la diagnosi, il risolutivo resta proposto", n1 == n0 + 1, (n0, n1))
        ok_("Monitor: servizi automatici fermi")
        post("site_proact", id=siteid, days=0, until="")
        # ---- 6. tetto ai tentativi: secondo tentativo, poi si alza la mano
        s4 = fail("Monitor: sincronizzazione orario", "Orologio sfasato di 40s")
        al4 = q("SELECT id FROM alerts WHERE device_id=? AND type=? AND status='open'", did, f"script:{s4}")[0][0]
        ex("UPDATE remed_runs SET due=? WHERE alert_id=? AND state='running'", "2000-01-01T00:00:00Z", al4)
        ex("DELETE FROM meta WHERE k='rb_tick'"); hb("k1")
        rr = q("SELECT state FROM remed_runs WHERE alert_id=? ORDER BY id", al4)
        rec("risolutivo senza effetto: secondo tentativo automatico", rr == [("not_fixed",), ("running",)], rr)
        ex("UPDATE remed_runs SET due=? WHERE alert_id=? AND state='running'", "2000-01-01T00:00:00Z", al4)
        ex("DELETE FROM meta WHERE k='rb_tick'"); hb("k1")
        rr = q("SELECT state FROM remed_runs WHERE alert_id=? ORDER BY id", al4)
        tkp = q("SELECT priority FROM tickets WHERE alert_id=?", al4)
        rec("dopo due tentativi non si rilancia: priorità del ticket alzata", rr == [("not_fixed",), ("not_fixed",)] and tkp and tkp[0][0] in ("high", "crit"), (rr, tkp))
        ok_("Monitor: sincronizzazione orario")
        # ---- 7. livello «proposti»: solo diagnosi automatica
        post("pack_level", pack_id=pid, scope="Cliente: Acme", level="ask"); hb("k1")
        rec("pack_level: tutte le regole passano a «proposti»", q("SELECT COUNT(DISTINCT proact) FROM rules WHERE pack_id=? AND pack_scope='Cliente: Acme'", pid) == [(1,)] and q("SELECT proact FROM schedules WHERE device_id=? LIMIT 1", did) == [("ask",)])
        n0 = q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0]
        fail("Monitor: spazio libero sui volumi", "Poco spazio: C:")
        rec("livello «proposti» su monitor sicuro: parte solo la diagnosi", q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0] == n0 + 1)
        ok_("Monitor: spazio libero sui volumi")
        # ---- 8. solo monitoraggio: nessun job, nessun ticket forzato
        post("pack_level", pack_id=pid, scope="Cliente: Acme", level="off"); hb("k1")
        n0 = q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0]; t0 = q("SELECT COUNT(*) FROM tickets")[0][0]
        fail("Monitor: spazio libero sui volumi", "Poco spazio: C:")
        rec("solo monitoraggio: l'alert si apre ma nessuna diagnosi né risolutivo", q("SELECT COUNT(*) FROM jobs WHERE device_id=? AND origin LIKE 'tk:%'", did)[0][0] == n0)
        ok_("Monitor: spazio libero sui volumi")
        # ---- 9. modifica puntuale di una regola e ritorno al comportamento classico
        rid = q("SELECT id FROM rules WHERE pack_id=? AND script_id=(SELECT id FROM scripts WHERE name='Monitor: spazio libero sui volumi')", pid)[0][0]
        post("rule_proact", id=rid, level="auto", response_script_id=q("SELECT id FROM scripts WHERE name='Windows: pulizia disco approfondita'")[0][0], fix_class="risky", diag_script_id=0, back="?view=rules")
        rec("rule_proact: livello, risolutivo e classe modificati per la singola regola", q("SELECT proact, fix_class, diag_script_id FROM rules WHERE id=?", rid) == [("auto", "risky", 0)])
        post("rule_proact", id=rid, level="", response_script_id=0, diag_script_id=0, back="?view=rules")
        rec("livello «classico» consentito (rimedio a ogni alert)", q("SELECT proact FROM rules WHERE id=?", rid) == [("",)])
        # ---- 10. passaggio di livello riapplicando
        n_rules = q("SELECT COUNT(*) FROM rules WHERE pack_id=?", pid)[0][0]
        post("pack_apply", pack_id=pid, site="Acme", level="auto")
        rec("riapplicare con un altro livello non duplica e riallinea", q("SELECT COUNT(*) FROM rules WHERE pack_id=?", pid)[0][0] == n_rules and q("SELECT COUNT(*) FROM rules WHERE pack_id=? AND proact='auto'", pid)[0][0] == n_rules)
        # ---- 11. interfaccia
        p.goto(BASE + "?view=packs&open=%d" % pid); p.wait_for_selector("main")
        t = p.inner_text("main")
        rec("pagina pacchetti: selettore Proattività e colonne Diagnosi/Risolutivo", "Proattività" in t and "Diagnosi" in t and "solo monitoraggio" in t and "sicuro" in t, t[:200])
        p.goto(BASE + "?view=rules"); p.wait_for_selector("main"); rec("pagina regole: colonna Proattività con modifica", "Proattività" in p.inner_text("main") and p.locator("summary", has_text="modifica").count() > 0)
        p.goto(BASE + "?view=clients"); p.wait_for_selector("main"); rec("pagina clienti: osservazione impostabile", "Proattività" in p.inner_text("main") and p.locator("summary", has_text="imposta").count() > 0)
        br.close()
    # ---- 12. soglia sfumata del disco (PowerShell, se disponibile)
    pw_ = shutil.which("pwsh")
    if pw_:
        body = q("SELECT body FROM scripts WHERE name='Monitor: spazio libero sui volumi'")[0][0]
        rec("monitor disco: la soglia ha minimo e massimo in GB", "SOGLIA_GB_MIN" in body and "SOGLIA_GB_MAX" in body)
        import re
        calc = lambda tot, p_=10, mn=5, mx=100: min(max(tot * p_ / 100, mn), mx)
        rec("soglia sfumata: 60 GB → 6 GB, 4000 GB → 100 GB, 20 GB → 5 GB", calc(60) == 6 and calc(4000) == 100 and calc(20) == 5)
finally:
    sp.terminate()
print(f"\n{ok}/{ok + bad} ok"); sys.exit(1 if bad else 0)
