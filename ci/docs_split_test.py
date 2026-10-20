#!/usr/bin/env python3
"""Test della separazione della documentazione in docs.sqlite (1.26): migrazione da un database 1.25 con dati,
backup e ripristino dei due file, ripristino di un backup vecchio. Uso: docs_split_test.py --old <index.php 1.25> --new <server dir>"""
import argparse, glob, http.cookiejar, os, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.parse
PORT = 8797; BASE = f"http://127.0.0.1:{PORT}/index.php"; PW = "prova-docs-1"
ok = 0; ko = 0
def rec(n, c, d=""):
    global ok, ko
    if c: ok += 1
    else: ko += 1
    print(("ok   " if c else "FAIL ") + n + ("" if c else "  " + str(d)), flush=True)
def q(db, sql, a=()):
    c = sqlite3.connect(db, timeout=10)
    try: return c.execute(sql, a).fetchall()
    finally: c.close()
def tables(db): return {r[0] for r in q(db, "select name from sqlite_master where type='table'")}
def start(srv):
    p = subprocess.Popen(["php", "-S", f"127.0.0.1:{PORT}", "-t", srv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try: urllib.request.urlopen(BASE, timeout=2); break
        except Exception as e:
            if hasattr(e, "code"): break
            time.sleep(0.2)
    return p
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
def client():
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect())
    def call(path, data=None):
        rq = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode() if data is not None else None, headers={"Origin": f"http://127.0.0.1:{PORT}"})
        try: return op.open(rq, timeout=60).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e: return e.read().decode("utf-8", "replace")
    call("?action=login", {"username": "admin", "password": PW})
    return call
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--old", required=True); ap.add_argument("--new", required=True); a = ap.parse_args()
    w = tempfile.mkdtemp(prefix="dsplit-"); srv = os.path.join(w, "srv"); data = os.path.join(srv, "data"); os.makedirs(data)
    h = subprocess.run(["php", "-r", f"echo password_hash('{PW}', PASSWORD_DEFAULT);"], capture_output=True, text=True).stdout.strip()
    cfg = "<?php\nreturn " + subprocess.run(["php", "-r", "echo var_export(['ENROLL_TOKEN'=>'t'.str_repeat('x',30),'CONSOLE_USER'=>'admin','CONSOLE_PASS'=>$argv[1],'JOB_SIGNING_KEY'=>str_repeat('k',40)], true);", h], capture_output=True, text=True).stdout + ";\n"
    open(os.path.join(data, "config.php"), "w").write(cfg)
    main_db = os.path.join(data, "myrmm.sqlite"); docs_db = os.path.join(data, "docs.sqlite"); bk = os.path.join(data, "backup")
    # --- 1. database in formato 1.25 con dati
    shutil.copy(a.old, os.path.join(srv, "index.php"))
    p = start(srv)
    try: client()
    finally: p.terminate(); p.wait()
    rec("1.25: i documenti stanno nel database principale", {"docs", "doc_rev", "doc_templates", "doc_import"} <= tables(main_db))
    c = sqlite3.connect(main_db)
    for i in range(1, 41):
        c.execute("insert into docs (site,title,category,body,device_id,pinned,created,updated,by_user,updated_by,review_months) values (?,?,?,?,0,?,?,?,?,?,?)",
                  ("Cliente%d" % (i % 3), "Doc %d" % i, "procedura", "# Doc %d\nè «così» àèìòù" % i, i % 2, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "admin", "admin", 6 if i % 5 == 0 else 0))
        c.execute("insert into doc_rev (doc_id,ts,author,title,body) values (?,?,?,?,?)", (i, "2026-01-01T00:00:00Z", "admin", "Doc %d" % i, "vecchio %d" % i))
    c.execute("insert into doc_import (token,user,created,data) values ('tok','admin',?,'{}')", (int(time.time()),))
    c.commit()
    n_t = c.execute("select count(*) from doc_templates").fetchone()[0]; n_i = c.execute("select count(*) from doc_import").fetchone()[0]
    c.close()
    rec("1.25: dati di prova inseriti", n_t > 0 and n_i == 1)
    # --- 2. aggiornamento a 1.26
    shutil.copy(os.path.join(a.new, "index.php"), os.path.join(srv, "index.php"))
    p = start(srv)
    try:
        call = client(); page = call("?view=docs")
        rec("migrazione: pagina documentazione si apre", "Doc 1" in page or "Doc 40" in page, page[:200])
        rec("migrazione: docs.sqlite creato", os.path.isfile(docs_db))
        rec("migrazione: tabelle tolte dal principale", not ({"docs", "doc_rev", "doc_templates", "doc_import"} & tables(main_db)), tables(main_db))
        rec("migrazione: conteggi identici", (q(docs_db, "select count(*) from docs")[0][0], q(docs_db, "select count(*) from doc_rev")[0][0], q(docs_db, "select count(*) from doc_templates")[0][0], q(docs_db, "select count(*) from doc_import")[0][0]) == (40, 40, n_t, n_i))
        rec("migrazione: contenuto e colonne nuove intatti", q(docs_db, "select body, review_months from docs where id=5")[0] == ("# Doc 5\nè «così» àèìòù", 6))
        page = call("?view=docs&id=7"); rec("migrazione: documento leggibile dalla console", "Doc 7" in page)
        # --- 3. backup: due file abbinati
        call("?action=backupnow", {})
        l = sorted(glob.glob(bk + "/myrmm-*.sqlite")); mains = [f for f in l if not f.endswith(".docs.sqlite")]; dd = [f for f in l if f.endswith(".docs.sqlite")]
        rec("backup: file principale e file documenti abbinati", len(mains) == 1 and len(dd) == 1 and dd[0] == mains[0][:-7] + ".docs.sqlite", l)
        rec("backup: il file documenti contiene i documenti, il principale no", q(dd[0], "select count(*) from docs")[0][0] == 40 and "docs" not in tables(mains[0]))
        bname = os.path.basename(mains[0])
        page = call("?view=system"); rec("backup: elenco mostra i documenti abbinati", bname in page and "Scarica documenti" in page)
        d1 = call("?action=backupdl&f=" + bname + "&docs=1"); rec("backup: download del file documenti", d1.startswith("SQLite format 3"))
        # --- 4. modifica, poi ripristino di entrambi i file
        c = sqlite3.connect(docs_db); c.execute("delete from docs where id<=10"); c.execute("insert into docs (title,body,created,updated) values ('Nuovo','x','a','a')"); c.commit(); c.close()
        c = sqlite3.connect(main_db); c.execute("insert into meta (k,v) values ('segno','dopo') on conflict(k) do update set v=excluded.v"); c.commit(); c.close()
        call("?action=backuprestore", {"f": bname, "confirm": "RIPRISTINA"})
        call("?view=docs")
        rec("ripristino: documenti tornati al momento del backup", q(docs_db, "select count(*) from docs")[0][0] == 40 and not q(docs_db, "select 1 from docs where title='Nuovo'"))
        rec("ripristino: database principale tornato indietro", not q(main_db, "select 1 from meta where k='segno'"))
        rec("ripristino: copia pre-ripristino di entrambi", len(glob.glob(bk + "/*-prerestore.sqlite")) == 1 and len(glob.glob(bk + "/*-prerestore.docs.sqlite")) == 1)
        # --- 6. rotazione/eliminazione portano via anche il file abbinato
        call("?action=backupdel", {"f": bname})
        rec("eliminazione: sparisce anche la copia documenti", not os.path.exists(os.path.join(bk, bname)) and not os.path.exists(os.path.join(bk, bname[:-7] + ".docs.sqlite")), os.listdir(bk))
        # --- 7. database docs.sqlite già popolato + principale vecchio con documenti: nessuna fusione
        c = sqlite3.connect(main_db); c.executescript("create table docs (id integer primary key, title text, body text, created text, updated text); insert into docs values (1,'Intruso','x','a','a');"); c.commit(); c.close()
        call("?view=docs")
        rec("conflitto: dati di docs.sqlite non toccati, vecchio messo da parte", q(docs_db, "select count(*) from docs")[0][0] == 40 and not q(docs_db, "select 1 from docs where title='Intruso'") and "legacy_docs" in tables(main_db) and "docs" not in tables(main_db), tables(main_db))
        # --- 5. backup vecchio (tutto nel principale): i documenti vengono riportati dentro
        old_bk = os.path.join(bk, "myrmm-20250101-000000-manual.sqlite")
        c = sqlite3.connect(old_bk)
        c.executescript("create table docs (id integer primary key autoincrement, site text not null default '', title text not null, category text not null default 'procedura', body text not null default '', device_id integer not null default 0, pinned integer not null default 0, created text not null, updated text not null, by_user text, updated_by text);"
                        "create table devices (id integer primary key); create table jobs (id integer primary key); create table meta (k text primary key, v text);"
                        "insert into docs (title,body,created,updated) values ('Vecchio A','a','c','u'),('Vecchio B','b','c','u');")
        c.commit(); c.close()
        call("?action=backuprestore", {"f": os.path.basename(old_bk), "confirm": "RIPRISTINA"}); call("?view=docs")
        t = [r[0] for r in q(docs_db, "select title from docs order by id")]
        rec("backup 1.25: i documenti sono rimigrati da quel backup", t == ["Vecchio A", "Vecchio B"], t)
        rec("backup 1.25: principale senza tabelle documenti", "docs" not in tables(main_db))
    finally:
        p.terminate(); p.wait()
    print(f"\n{ok} ok, {ko} falliti")
    shutil.rmtree(w, ignore_errors=True)
    sys.exit(1 if ko else 0)
main()
