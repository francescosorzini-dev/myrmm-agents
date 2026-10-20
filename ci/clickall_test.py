#!/usr/bin/env python3
"""Giro completo dei click: visita ogni pagina e ogni scheda, clicca (o tocca) ogni pulsante, scheda, menu e collegamento
innocuo e controlla che non si rompa niente nella grafica né nell'usabilità. Non lancia script: i pulsanti pericolosi
(elimina, disinstalla, riavvia, esci…) sono saltati e le finestre di conferma vengono rifiutate.

Modalità:  phone (Pixel 7, tocco)  |  narrow (desktop stretto 960 px)  |  wide (desktop 1360 px)
Uso: python3 ci/clickall_test.py [phone|narrow|wide]   (senza argomento: tutte e tre, una dopo l'altra)
Controlla dopo ogni clic: errori JS/console/HTTP, errori PHP, pagina vuota, scroll orizzontale (phone/narrow), elementi fuori schermo,
menu e pannelli che si chiudono da soli o escono dallo schermo, elementi coperti da altri (clic impossibile), tastiera su telefono."""
import os, sys, json, time, shutil, sqlite3, subprocess, tempfile, re, urllib.request
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = {"phone": 8796, "narrow": 8797, "wide": 8798}
MODE = sys.argv[1] if len(sys.argv) > 1 else ""
if MODE == "":   # tutte e tre in parallelo come processi separati
    ps = [subprocess.Popen([sys.executable, os.path.abspath(__file__), m]) for m in MODES]
    sys.exit(max(p.wait() for p in ps))
assert MODE in MODES, MODE
PORT = MODES[MODE]; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "Pw-prova-1234567"
OUT = os.environ.get("CLICK_OUT", os.path.join(tempfile.gettempdir(), "myrmm-click")); os.makedirs(OUT, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="myrmm-click-"); srv = os.path.join(tmp, "server")
shutil.copytree(os.path.join(ROOT, "server"), srv, ignore=shutil.ignore_patterns("data")); os.makedirs(os.path.join(srv, "data"))
h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
cfg = {"ENROLL_TOKEN": "t" * 24, "CONSOLE_USER": "admin", "CONSOLE_PASS": h, "JOB_SIGNING_KEY": "k" * 32, "TUNNEL_MODE": "on"}
open(os.path.join(srv, "data", "config.php"), "w").write(subprocess.run(["php", "-r", "echo \"<?php\\nreturn \" . var_export(json_decode($argv[1], true), true) . \";\\n\";", json.dumps(cfg)], capture_output=True, text=True).stdout)
errlog = open(os.path.join(tmp, "php.err"), "w")
sp = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=errlog, env=dict(os.environ, PHP_CLI_SERVER_WORKERS="4"))
problems = []; seen_p = set(); n_clicks = 0; n_pages = 0
DB = os.path.join(srv, "data", "myrmm.sqlite")

def shot(p, tag):
    f = os.path.join(OUT, f"{MODE}-{len(problems):03d}-{re.sub(r'[^A-Za-z0-9]+', '_', tag)[:40]}.png")
    try: p.screenshot(path=f)
    except Exception: f = ""
    return f

ORD_SEEN = set()
ORD_OK = re.compile(r'^(Tutte|Filtri e azioni|Invia prova|Esegui ora|Carica) @ ')   # controllati a mano: azioni di gruppo, interruttori e blocchi distinti nello stesso modulo
def bad(p, where, what):
    k = (where.split(" › ")[0], what[:90])
    if k in seen_p: return
    seen_p.add(k)
    f = shot(p, where) if p else ""
    problems.append(f"[{MODE}] {where}: {what}" + (f"  (immagine: {f})" if f else ""))
    print("PROBLEMA", problems[-1], flush=True)

DENY = re.compile(r"elimin|cancell|rimuov|svuot|disinstall|revoc|logout|esci\b|wipe|purge|delete|\bdel[_&=]|cestino|reset|spegn|riavvi|reboot|shutdown|disabilit|rigenera|ruota|importa|backup|ripristin|restore|download|scarica|export|esporta|\.csv|\.pdf|\.zip|action=(?:logout|dev_move|site_del|user_del)", re.I)

CLOSE = """()=>{document.body.classList.remove("nav");document.querySelectorAll("details[open]").forEach(d=>{d.open=false});document.querySelectorAll(".cb.open").forEach(e=>e.classList.remove("open"));document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape"}))}"""
COLLECT = """(skipChrome)=>{
  var out=[],n=0;document.querySelectorAll('[data-ck]').forEach(function(e){e.removeAttribute('data-ck')});
  var sel='button,summary,a[href],[role=tab],[role=button],input[type=checkbox],input[type=radio],[onclick]';
  document.querySelectorAll(sel).forEach(function(e){
    if(skipChrome&&e.closest('.top,.rail'))return;
    if(e.closest('.cbp,.dpane:not(.on)'))return;
    var r=e.getBoundingClientRect(),cs=getComputedStyle(e);
    if(!(r.width>0&&r.height>0)||cs.visibility==='hidden'||cs.display==='none'||e.disabled)return;
    if(e.tagName==='A'){var hr=e.getAttribute('href')||'';if(/^(https?:|mailto:|tel:|javascript:|#?$)/.test(hr)&&!/^https?:\\/\\/127\\.0\\.0\\.1/.test(hr))return}
    if(e.closest('details:not([open])')&&e.tagName!=='SUMMARY')return;
    var t=(e.innerText||e.value||e.getAttribute('aria-label')||e.title||'').trim().replace(/\\s+/g,' ').slice(0,60);
    var meta=t+' '+(e.getAttribute('href')||'')+' '+(e.getAttribute('formaction')||'')+' '+(e.title||'')+' '+(e.id||'')+' '+(e.name||'')+' '+(e.form?e.form.getAttribute('action')||'':'');
    e.setAttribute('data-ck',n);out.push({n:n,tag:e.tagName,t:t,meta:meta,href:e.getAttribute('href')||'',type:e.type||'',cb:e.classList.contains('cbb')});n++});
  return out}"""

STATE = """()=>{var W=window.innerWidth,m=document.querySelector('main');
  var over=[];document.querySelectorAll('body *').forEach(function(e){var r=e.getBoundingClientRect();if(r.width>0&&r.right>W+1&&getComputedStyle(e).position!=='fixed'){for(var x=e.parentElement,clip=false;x&&x!==document.body;x=x.parentElement){var o=getComputedStyle(x).overflowX;if(o==='auto'||o==='scroll'||o==='hidden'||o==='clip'){clip=true;break}if(x.tagName==='DETAILS'&&!x.open){clip=true;break}}if(!clip&&over.length<3)over.push((e.className||e.tagName)+'')}});
  var pops=[];document.querySelectorAll('.cb.open .cbp,details[open]>.colpop,details[open]>.addp,.drw.on,.pal.on .box,.sitesw[open]>form').forEach(function(e){var r=e.getBoundingClientRect();if(r.width>0&&(r.left<-1||r.right>W+1))pops.push((e.className||e.tagName)+' x:'+Math.round(r.left)+'-'+Math.round(r.right)+' W:'+W)});
  var ord=[];document.querySelectorAll('form').forEach(function(f){var vis=function(e){var r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'};
    var bt=[].slice.call(f.querySelectorAll('button:not([type=button].ic),input[type=submit],button[type=submit],button.btn2,button[type=button]')).filter(function(e){return vis(e)&&!e.closest('.cb')&&!e.closest('summary')&&(e.textContent||e.value||'').trim().length>1});
    var fl=[].slice.call(f.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=search]),select,textarea')).filter(vis);
    for(var i=0;i<bt.length&&ord.length<3;i++){var b=bt[i],br=b.getBoundingClientRect();
      if(fl.some(function(x){var r=x.getBoundingClientRect();return (b.compareDocumentPosition(x)&4)&&r.top>br.bottom+30&&!b.contains(x)&&x.type!=='number'&&(x.type!=='search')})){ord.push((b.textContent||b.value||'').trim().slice(0,30)+' @ '+(f.id||f.getAttribute('action')||'form'));break}}});
  return {ord:ord,sw:document.documentElement.scrollWidth,W:W,main:!!m,txt:m?m.innerText.trim().length:0,bodyH:document.body.scrollHeight,over:over,pops:pops}}"""

try:
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if getattr(e, "code", 0): break
            time.sleep(.2)
    try: urllib.request.urlopen(urllib.request.Request(BASE + "?action=login", data=b"username=x&password=y", headers={"Origin": f"http://127.0.0.1:{PORT}"}), timeout=5)
    except Exception: pass
    for _ in range(50):
        try:
            if os.path.exists(DB) and sqlite3.connect(DB).execute("SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM sites),(SELECT COUNT(*) FROM scripts)").fetchone() is not None: break
        except Exception: pass
        time.sleep(.3)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    def post(body, key):
        urllib.request.urlopen(urllib.request.Request(BASE + "?action=heartbeat", data=json.dumps(body).encode(), headers={"X-Device-Key": key, "Content-Type": "application/json"}), timeout=15).read()
    db = sqlite3.connect(DB)
    for (hn, osn, site), k in zip([("SRV-WIN", "windows", "Acme"), ("PC-WIN", "windows", "Acme"), ("LNX01", "linux", "Beta")], ["k1", "k2", "k3"]):
        db.execute("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,?,?,?,?, '{}',?)", (hn, osn, k, site, now, now))
    for i in range(12):
        db.execute("INSERT INTO devices(hostname,os,api_key,site,last_seen,inventory,created) VALUES(?,?,?,?,?, '{}',?)", (f"PC-{i:02d}", "windows", f"kk{i}", "Acme", now, now))
        db.execute("INSERT INTO assets(type_id,name,site,created,updated) VALUES((SELECT MIN(id) FROM asset_types),?,?,?,?)", (f"Asset {i}", "Acme", now, now))
        db.execute("INSERT OR IGNORE INTO sites(name,created) VALUES(?,?)", (f"Cliente{i}", now))
    db.commit(); db.close()
    inv = lambda os_: {"os": os_, "cpu_pct": 55, "ram_pct": 60, "ram_gb": 16, "cpu": "Xeon", "disks": [{"DeviceID": "C:", "size_gb": 200, "free_gb": 15}], "ips": ["10.0.0.5"], "agent_version": "1.38.3",
                       "software": [{"name": "7-Zip", "version": "23"}], "services": [{"name": "Spooler", "state": "Running"}], "session_state": "attiva", "session_user": "mario"}
    for k, o in zip(["k1", "k2", "k3"], ["Windows Server 2022", "Windows 11", "Ubuntu 22.04"]):
        try: post({"inventory": inv(o)}, k)
        except Exception as e: print("heartbeat", e)
    time.sleep(.5)
    db = sqlite3.connect(DB)
    db.execute("ATTACH DATABASE ? AS dk", (os.path.join(os.path.dirname(DB), "docs.sqlite"),))
    sids = [r[0] for r in db.execute("SELECT id FROM scripts ORDER BY id LIMIT 3")]
    db.execute("INSERT INTO runbooks(name,description,steps,stop_on_fail,created) VALUES('Manutenzione','Prova',?,1,?)", (json.dumps([{"script_id": sids[0], "vars": {}}, {"wait_min": 5}, {"script_id": sids[1], "vars": {}}]), now))
    try: db.execute("INSERT INTO docs(site,title,category,body,created,updated) VALUES('Acme','Procedura di prova','procedura','Testo **di prova**',?,?)", (now, now))
    except Exception as e: print("docs seed", e)
    db.execute("INSERT INTO filters(name,criteria,created) VALUES('Tutti i Windows','{\"mode\":\"and\",\"conds\":[]}',?)", (now,))
    dev_ids = [r[0] for r in db.execute("SELECT id FROM devices ORDER BY id LIMIT 3")]
    db.commit(); db.close()

    views = ["dashboard", "devices", "alerts", "mywork", "assets", "chats", "diag", "assettypes", "scripts", "checks", "patch", "vars", "fields", "deploy", "audit", "users", "clients", "depts", "onboard", "todo",
             "netwiz", "network", "docs", "docs&edit=0", "docs&edit=1", "docs&id=1", "tickets", "filters", "rules", "packs", "run&script=1", "runbooks", "runbooks&new=1", "runbooks&edit=1", "jobs", "maint", "expiry", "report", "sitediag", "profile", "system",
             "trash", "import", "newdevice", "asset&id=1", "chat&device_id=1"]
    for d in dev_ids[:2]: views += [f"device&id={d}", f"tasks&id={d}", f"services&id={d}", f"files&id={d}"]
    views += [f"device&id={dev_ids[2]}"]

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        if MODE == "phone":
            kw = dict(pw.devices["Pixel 7"]); kw.pop("default_browser_type", None); ctx_kw = kw
        elif MODE == "narrow": ctx_kw = {"viewport": {"width": 960, "height": 800}}
        else: ctx_kw = {"viewport": {"width": 1360, "height": 860}}
        c = br.new_context(**ctx_kw); p = c.new_page(); errs = []
        VP0 = p.viewport_size
        p.on("pageerror", lambda e: errs.append("JS: " + str(e)))
        p.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
        p.on("response", lambda r: errs.append(f"HTTP {r.status} {r.url[-80:]}") if r.status >= 400 and "favicon" not in r.url else None)
        p.on("dialog", lambda d: d.dismiss())
        p.goto(BASE); p.fill("input[name=username]", "admin"); p.click("button[type=submit]")
        try: p.wait_for_selector("input[name=password]", timeout=3000); p.fill("input[name=password]", PW); p.click("button[type=submit]")
        except Exception: pass
        p.wait_for_selector(".rail", timeout=8000)
        narrow = MODE in ("phone", "narrow")
        tap = (lambda loc: loc.tap(timeout=2500)) if MODE == "phone" else (lambda loc: loc.click(timeout=2500))

        def page_ok(where, expect_err=False):
            """Controlli dopo un caricamento o un clic."""
            st = p.evaluate(STATE)
            if not st["main"] and "login" not in p.url: bad(p, where, "nessun <main> dopo il clic")
            elif st["txt"] < 5 and "inexistente" not in where: bad(p, where, "contenuto vuoto (la pagina si è svuotata)")
            if st["bodyH"] < 200: bad(p, where, f"pagina collassata (altezza {st['bodyH']})")
            if narrow and st["sw"] > st["W"] + 1: bad(p, where, f"scroll orizzontale ({st['sw']} > {st['W']}): {st['over']}")
            for x in st["pops"]: bad(p, where, "pannello fuori dallo schermo: " + x)
            for x in st["ord"]:
                if not ORD_OK.match(x) and (p.url.split("&")[0], x) not in ORD_SEEN: ORD_SEEN.add((p.url.split("&")[0], x)); bad(p, where, "pulsante sopra ai campi che usa (scomodo): " + x)
            html = p.content()
            m = re.search(r"(Warning|Notice|Fatal error|Deprecated|Parse error|Uncaught)[^<]{0,200}(on line \d+| in /)", html)
            if m: bad(p, where, "errore PHP: " + html[max(0, m.start() - 30):m.start() + 160].replace("\n", " "))
            while errs:
                e = errs.pop(0)
                if expect_err and e.startswith("HTTP"): continue
                bad(p, where, e[:200])

        def after_click(where, c0):
            for _try in range(3):
                try: return after_click0(where, c0)
                except Exception as e:
                    if "context was destroyed" not in str(e) and "navigat" not in str(e): raise
                    p.wait_for_load_state("domcontentloaded"); p.wait_for_timeout(300)

        def after_click0(where, c0):
            """Dopo un clic: errori, stato, menu aperti che devono restare aperti."""
            p.wait_for_timeout(120)
            op = p.evaluate("()=>({cb:!!document.querySelector('.cb.open .cbp'),det:[...document.querySelectorAll('details[open]>.colpop,details[open]>.addp,.sitesw[open]>form')].length})")
            p.wait_for_timeout(500)
            op2 = p.evaluate("()=>({cb:!!document.querySelector('.cb.open .cbp'),det:[...document.querySelectorAll('details[open]>.colpop,details[open]>.addp,.sitesw[open]>form')].length})")
            if (op["cb"] and not op2["cb"]) or op2["det"] < op["det"]: bad(p, where, "il menu si è chiuso da solo subito dopo l'apertura")
            page_ok(where)

        def explore(label, per_page=30, skip_chrome=True, deep_combo=True):
            """Clicca i candidati della pagina corrente."""
            global n_clicks
            start = p.url.split("#")[0]
            cands = p.evaluate(COLLECT, skip_chrome)
            used = set(); k = 0
            for cd in cands:
                key = (cd["tag"], cd["t"][:40], cd["href"].split("&id=")[0][:60])
                if key in used or DENY.search(cd["meta"]): continue
                used.add(key)
                if k >= per_page: break
                k += 1; n_clicks += 1
                where = f"{label} › {cd['tag'].lower()} «{cd['t'][:30]}»"
                loc = p.locator(f'[data-ck="{cd["n"]}"]').first
                try:
                    loc.scroll_into_view_if_needed(timeout=1500)
                    try: tap(loc)
                    except Exception as e1:
                        if "intercepts pointer events" not in str(e1): raise
                        p.evaluate(CLOSE); p.wait_for_timeout(150)   # overlay lasciato aperto dal clic precedente: chiudo e riprovo
                        loc.scroll_into_view_if_needed(timeout=1500); tap(loc)
                except Exception as e:
                    msg = str(e).split("\n")[0][:160]
                    if "intercepts pointer events" in str(e):
                        mm = re.search(r"<([^>]{0,90})>\s*(?:\w+\s*)*intercepts", str(e))
                        bad(p, where, "elemento coperto da un altro (non si può cliccare): " + (mm.group(1) if mm else msg))
                    elif "not stable" in msg or "detached" in msg or "timeout" in msg.lower(): pass
                    else: bad(p, where, "clic impossibile: " + msg)
                    continue
                if cd["cb"] and deep_combo:   # menu a tendina con ricerca: tastiera su telefono = finestra più bassa; il menu deve restare aperto
                    p.wait_for_timeout(200)
                    if not p.evaluate("!!document.querySelector('.cb.open .cbp')"): bad(p, where, "il menu a tendina non si apre")
                    else:
                        vp = p.viewport_size
                        p.set_viewport_size({"width": vp["width"], "height": max(300, int(vp["height"] * .55))}); p.wait_for_timeout(350)
                        if not p.evaluate("!!document.querySelector('.cb.open .cbp')"): bad(p, where, "il menu a tendina si chiude quando compare la tastiera (finestra più bassa)")
                        elif p.evaluate("(()=>{var e=document.querySelector('.cb.open .cbp');var r=e.getBoundingClientRect();return r.left<-1||r.right>innerWidth+1||r.top<-1||r.bottom>innerHeight+1})()"): bad(p, where, "il menu a tendina esce dallo schermo con la tastiera")
                        else:
                            li = p.locator(".cb.open .cbp li[role=option]").nth(1)
                            try: tap(li); p.wait_for_timeout(150)
                            except Exception as e: bad(p, where, "voce del menu non selezionabile: " + str(e).split("\n")[0][:120])
                        p.set_viewport_size(vp)
                after_click(where, None)
                p.evaluate(CLOSE)
                p.evaluate("document.querySelectorAll('#rail details.ngrp').forEach(d=>d.open=true)")   # un clic su un titolo di gruppo lo richiude: riapro per non sfalsare le voci seguenti
                if p.url.split("#")[0] != start:   # è cambiata pagina: torna indietro
                    p.goto(start); p.wait_for_selector("main", timeout=5000)
                    cands2 = p.evaluate(COLLECT, skip_chrome)
                    errs.clear()
                if k % 12 == 0:
                    p.keyboard.press("Escape")

        # --- menu e barra alta (una volta) sul cruscotto
        p.goto(BASE + "?view=dashboard"); p.wait_for_selector("main"); page_ok("dashboard")
        p.evaluate("document.querySelectorAll('#rail details.ngrp').forEach(d=>d.open=true)")   # tutte le voci del menu visibili per il giro
        explore("barra alta e menu", per_page=60, skip_chrome=False, deep_combo=False)
        # --- ogni pagina
        for v in views:
            errs.clear(); n_pages += 1
            p.goto(BASE + "?view=" + v)
            try: p.wait_for_selector("main", timeout=5000)
            except Exception: bad(p, v, "nessun <main>"); continue
            page_ok(v)
            tabs = p.locator(".dnav a:visible")
            if tabs.count():
                for i in range(tabs.count()):
                    try: tap(tabs.nth(i)); p.wait_for_timeout(80)
                    except Exception as e: bad(p, f"{v} scheda {i}", "scheda non cliccabile: " + str(e).split("\n")[0][:120]); continue
                    page_ok(f"{v} scheda {i}"); explore(f"{v} scheda «{(p.locator('.dnav a:visible').nth(i).inner_text() or '').strip()[:18]}»", per_page=12)
            else: explore(v)
        # --- scenario: editor dei runbook, creazione di più passi con la tastiera su telefono
        p.goto(BASE + "?view=runbooks&new=1"); p.wait_for_selector("#rbEd")
        p.fill("#rbEd input[name=name]", "Giro completo");
        for _ in range(3):
            tap(p.locator("#rbAddS")); p.wait_for_timeout(100)
        tap(p.locator("#rbAddW")); p.wait_for_timeout(100)
        sels = p.locator("#rbSteps li select")
        for i in range(sels.count()):
            b = p.locator("#rbSteps li").nth(i).locator(".cbb")
            if not b.count(): continue
            tap(b.first); p.wait_for_timeout(250)
            vp = p.viewport_size; p.set_viewport_size({"width": vp["width"], "height": max(300, int(vp["height"] * .55))}); p.wait_for_timeout(400)
            if not p.evaluate("!!document.querySelector('.cb.open .cbp')"): bad(p, f"editor runbook, passo {i + 1}", "il selettore dello script si chiude appena si apre (tastiera)")
            else:
                try: tap(p.locator(".cb.open .cbp li[role=option]").nth(i + 2)); p.wait_for_timeout(200)
                except Exception as e: bad(p, f"editor runbook, passo {i + 1}", "scelta dello script impossibile: " + str(e).split("\n")[0][:120])
            p.set_viewport_size(vp); p.wait_for_timeout(200)
        page_ok("editor runbook")
        tap(p.locator("#rbEd button[type=submit]")); p.wait_for_load_state("load")
        try: p.wait_for_selector("text=salvato", timeout=4000)
        except Exception: bad(p, "editor runbook", "il salvataggio con più passi non ha dato esito")
        n = sqlite3.connect(DB).execute("SELECT steps FROM runbooks WHERE name='Giro completo'").fetchone()
        if not n or len(json.loads(n[0])) != 4: bad(p, "editor runbook", "runbook salvato con passi sbagliati: " + str(n))
        # --- anteprima laterale, ricerca globale, scorciatoie
        p.goto(BASE + "?view=devices"); p.wait_for_selector("main table")
        tap(p.locator(".top .srch")); p.wait_for_timeout(200)
        if not p.evaluate("document.getElementById('pal').classList.contains('on')"): bad(p, "ricerca globale", "non si apre")
        else:
            p.fill("#palq", "SRV"); p.wait_for_timeout(600); page_ok("ricerca globale"); p.keyboard.press("Escape")
        tap(p.locator("#sitesw summary")) if p.locator("#sitesw summary").count() else None
        if p.locator("#sitesw summary").count():
            p.wait_for_timeout(200); page_ok("selettore clienti"); p.keyboard.press("Escape")
        br.close()
    errlog.flush(); log = open(os.path.join(tmp, "php.err")).read()
    for ln in sorted(set(l for l in log.splitlines() if re.search(r"Warning|Notice|Fatal|Deprecated|Uncaught|Error", l) and "Accepted" not in l and "Closing" not in l))[:20]: problems.append(f"[{MODE}] log PHP: " + ln[:220])
finally:
    sp.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print(f"\n[{MODE}] {n_pages} pagine, {n_clicks} clic, {len(problems)} problemi")
for q in problems: print(" -", q)
sys.exit(1 if problems else 0)
