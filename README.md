# myrmm v1.68.0 — manuale

RMM (Remote Monitoring & Management) leggero per gestire flotte di PC e server di più clienti, pensato per
girare su un **hosting condiviso Apache/PHP con SQLite**: nessun processo sempre attivo, nessun cron,
nessuna porta inbound sui client. Server e agent hanno **la stessa versione** (`APP_VERSION` in
`server/index.php` = `AgentVersion` in `agent/main.go`).

Indice (rete: §8.24–8.29, console riorganizzata e onboarding: §8.30–8.36, prova guidata della distribuzione §14.5): 1 Architettura · 2 Installazione server · 3 Installazione agent · 4 Uso della console ·
5 Monitor e alert · 6 Script, variabili, regole · 7 Patch management · 8 Utenti e ruoli ·
9 Controllo remoto (RustDesk) · 10 — · 11 Aggiornamento dell'agent · 12 Sicurezza ·
13 Manutenzione e backup · 14 Risoluzione problemi · 15 Limiti noti · 16 File · 17 Cronologia

---

## 1. Architettura

```
 Endpoint Windows                           Server (Apache/PHP + SQLite)
 ┌────────────────────┐   HTTPS outbound    ┌─────────────────────────────┐
 │ myrmm-agent.exe    │ ── enroll ────────▶ │ ?action=enroll              │
 │ (servizio, Go)     │ ── heartbeat ─────▶ │ ?action=heartbeat           │
 │ ogni N secondi:    │ ◀─ job firmati ──── │   + regole, patch, schedule │
 │  inventario        │ ── result ────────▶ │ ?action=result              │
 │  esegue PowerShell │ ── inventory ─────▶ │ ?action=inventory           │
 └────────────────────┘ ◀─ update firmato ─ │ ?action=agent_bin           │
                                            │ console web (viewer/oper/admin)
                                            └─────────────────────────────┘
```

- Solo traffico **outbound su 443**; compatibile con NAT e firewall dei clienti.
- **Payload**: PowerShell su Windows (`-EncodedCommand`, nessun problema di quoting); shell (bash/sh, o shebang) su Linux/macOS. Gli script della libreria hanno una piattaforma (Windows / Linux-macOS / qualsiasi) e il server non li accoda su device di un'altra piattaforma.
- Tutto è guidato dal **heartbeat**: regole, patch e schedulazioni si valutano lì (modello "lazy").
- Auth agent: token di arruolamento → `api_key` per device (`X-Device-Key`).
- Ogni job è **firmato HMAC-SHA256**; l'agent rifiuta job con firma errata.

## 2. Installazione server

Requisiti: Apache + PHP 8.1+ con PDO SQLite, HTTPS.

1. Carica `index.php`, `.htaccess` e la cartella `update/` (es. in `https://rmm.example.com/`). **Non modificare nulla.**
2. Crea un file vuoto `setup.allow` accanto a `index.php` (FTP o File Manager). Senza, il wizard non parte: nessun altro può configurare il server al posto tuo.
3. Apri l'URL: il **wizard di primo avvio** chiede dove tenere i dati e l'utente admin. Genera da solo `ENROLL_TOKEN` e `JOB_SIGNING_KEY`, scrive `config.php`, crea il database e cancella `setup.allow`.
4. Accedi. La pagina **Deploy** mostra i comandi/pacchetti già compilati con i tuoi valori.

Finché non esiste `config.php`, gli endpoint degli agent rispondono 503 e la console mostra solo il wizard.

### 2.1 Dove stanno i dati

Il wizard offre tre posizioni per `config.php`, database SQLite e backup:

| Scelta | Cartella |
|---|---|
| fuori dalla webroot (consigliata) | `<genitore della webroot>/myrmm-data/` |
| accanto a `index.php` | `data/` (protetta da `.htaccess`) |
| percorso a scelta | quello indicato; il suo percorso è salvato in `config.path` accanto a `index.php` |

`config.php` si cerca in quest'ordine: variabile d'ambiente `MYRMM_CONFIG`, `config.path`, `<genitore webroot>/myrmm-data/config.php`, `data/config.php`.

**Spostare il database dopo l'installazione**: copia `myrmm.sqlite` (più `-wal`/`-shm` se presenti, a servizio fermo) nella nuova cartella e imposta in `config.php` `'DB_PATH' => '/nuovo/percorso/myrmm.sqlite'` (e, se vuoi, `'BACKUP_DIR'`). In alternativa fai un backup dalla console e ripristinalo.

### 2.2 Chiavi di config.php

`config.php` è un `return [ … ];` PHP: se servito per errore dal web non mostra nulla. Ogni chiave omessa usa il valore predefinito.

| Chiave | Significato |
|---|---|
| `ENROLL_TOKEN`, `ENROLL_GLOBAL` | token globale di arruolamento (valido solo se `ENROLL_GLOBAL` è true) |
| `CONSOLE_USER` / `CONSOLE_PASS` | admin **integrato** (accesso di emergenza); la password si cambia dal Profilo |
| `CONSOLE_TOTP_SECRET` | 2FA dell'admin integrato (si attiva dal Profilo) |
| `JOB_SIGNING_KEY` | chiave HMAC di job e update (uguale a `job_signing_key` dell'agent) |
| `DB_PATH`, `BACKUP_DIR`, `BACKUP_KEEP` | database, cartella e numero dei backup automatici |
| `CONSOLE_ALLOW` | elenco IP/CIDR autorizzati alla console (vuoto = tutti) |
| `SESSION_IDLE_MIN` | scadenza sessione per inattività |
| `HEARTBEAT_WAIT_MAX` | secondi massimi di long-poll dell'heartbeat rapido (default 20; `0` se l'hosting ha pochi processi PHP) |
| `TUNNEL_MODE` | tunnel RDP/SSH: `on` (default) / `off` |
| `TUNNEL_PORTS` | porte del device raggiungibili con un tunnel (default `[3389, 22, 5900]`) |
| `TUNNEL_WAIT_MAX`, `TUNNEL_IDLE_SEC`, `TUNNEL_MAX_MIN` | attesa massima delle richieste di relay (15 s), inattività oltre la quale il tunnel si chiude (600 s), durata massima (480 min) |
| `TM_MODE` | task manager: `rw` elenco e termina / `ro` solo elenco / `off`; si cambia anche da *Sistema* |
| `FS_MAX_MB`, `FS_MODE` | file manager: limite per file in MB (default 25, mai oltre i limiti PHP dell'hosting) e modalità `rw` / `ro` / `off`; si cambiano anche da *Sistema* |
| `ALERT_DISK_FREE_PCT`, `ALERT_OFFLINE_MIN` | soglie dei check seedati |
| `ALERT_EMAIL_TO`, `ALERT_WEBHOOK_URL` | notifiche alert (vuote = disattivate) |
| `METRICS_MODE`, `METRICS_INTERVAL_MIN`, `METRICS_RAW_DAYS`, `METRICS_HOURLY_DAYS`, `METRICS_DAILY_DAYS` | metriche e retention (§8.5); modificabili anche da Sistema → Impostazioni |
| `RETENTION_DAYS`, `RESULT_MAX_BYTES` | conservazione dati (0 = mai) e tetto stdout/stderr |
| `JOB_REDELIVER_MIN`, `JOB_MAX_ATTEMPTS` | riconsegna job "sent" (0 = at-most-once) |
| `RL_MAX_FAILS`, `RL_WINDOW_MIN` | blocco IP dopo N login/enroll falliti in M minuti |
| `PATCH_TZ`, `RUSTDESK_WEB_URL` | fuso delle patch; client web RustDesk |

**Migrazione da versioni <1.7**: carica il nuovo `index.php`, crea `setup.allow` e passa dal wizard (scegli un nuovo admin e **riusa la stessa `JOB_SIGNING_KEY`**: dopo il wizard modifica `config.php` con la tua chiave, altrimenti gli agent rifiuteranno i job; se vuoi tenere il database, imposta `DB_PATH` sul vecchio file).

## 3. Installazione agent

Binario Go statico, nessun runtime. Piattaforme: **Windows x64**, **Linux x64/ARM64**, **macOS Intel/Apple Silicon**.

### 3.1 Pacchetto per site (consigliato)

In **Deploy → Pacchetti di installazione per site** crei un token per cliente (`st-…`). Lo script che ne deriva contiene già server, chiave e token:
chi installa non scrive nulla, e il device finisce **sempre** in quel site (decide il token, non il PC). Per ogni cliente il riquadro mostra:

- **Windows** (PowerShell come amministratore): `irm '<server>?action=install&t=<token>' | iex`
- **Linux / macOS** (root): `curl -fsSL '<server>?action=install&os=sh&t=<token>' | sudo sh`
- **Pacchetto offline**: ZIP per cliente con `myrmm-agent.exe`, i binari Linux/macOS, `install.ps1`, `install.sh`, `Installa.cmd` (doppio clic, chiede l'elevazione), `config.json` già incluso negli script. Per USB, GPO, Intune, o PC che non devono scaricare dal server.
- **Altri strumenti di distribuzione (RMM, GPO, Intune)**: definisci la variabile d'ambiente `MYRMM_TOKEN` con il token del cliente ed esegui **un solo script universale** (corpo nel riquadro): legge la variabile e installa. Vale per tutti i clienti. Se lo strumento non propaga le variabili come variabili d'ambiente, valorizzala al lancio.
- "Crea per i N site senza token" genera i token per tutti i site già presenti tra i device.

Gli script sono **idempotenti** (se l'agent c'è già non fanno nulla; `MYRMM_FORCE=1` reinstalla), verificano lo **SHA-256** del binario scaricato, limitano i permessi di `config.json` (SYSTEM e Administrators su Windows; 0600 root su Linux/macOS), installano il servizio e attendono l'arruolamento (con avviso se il server non è raggiungibile). I token si disattivano singolarmente senza toccare gli agent già installati.
Il download del binario passa da `?action=install_bin` (token valido, limite tentativi come l'arruolamento).

Cartelle: Windows `C:\Program Files\myrmm`, dati in `%ProgramData%\myrmm` · Linux/macOS binario in `/opt/myrmm`, dati in `/etc/myrmm` (Linux) o `/Library/Application Support/myrmm` (macOS). Servizio: SCM / systemd / launchd.

### 3.2 A mano

```powershell
# 1. copia myrmm-agent.exe in C:\Program Files\myrmm\
# 2. scrivi la config (NIENTE BOM: usa WriteAllText, non Set-Content -Encoding utf8)
New-Item -ItemType Directory -Force "$env:ProgramData\myrmm" | Out-Null
$cfg = @'
{ "server_url":"https://rmm.example.com/index.php",
  "enroll_token":"<TOKEN DI SITE oppure ENROLL_TOKEN>",
  "poll_seconds":60,
  "job_signing_key":"<JOB_SIGNING_KEY>",
  "full_inventory_hour":12 }
'@
[IO.File]::WriteAllText("$env:ProgramData\myrmm\config.json", $cfg)
# 3. servizio
& 'C:\Program Files\myrmm\myrmm-agent.exe' install
& 'C:\Program Files\myrmm\myrmm-agent.exe' start
```

Comandi: `install` · `uninstall` · `start` · `stop` · `restart` · `run` (foreground, log su console, per debug).
Stato (`device_id`, `api_key`) in `state.json` accanto al config. Il device compare in console entro un `poll_seconds`.

Campi di `config.json`: `server_url`, `enroll_token` (obbligatori); `poll_seconds` (60, heartbeat completo con inventario); `wake_seconds` (15, heartbeat leggero tra due completi: job e richieste della console partono entro questo tempo; 0 = solo `poll_seconds`); `job_signing_key`
(se vuota l'agent esegue anche job non firmati e **rifiuta gli auto-update**); `full_inventory_hour` (12; `-1` = disattivato);
`site` (solo con il token globale; con un token di site viene ignorato).

### 3.3 Linux e macOS

- **Job**: script shell (`bash -c`; se la prima riga è uno shebang, `#!/usr/bin/env pwsh`, `#!/usr/bin/python3`…, l'interprete indicato). Albero di processi terminato su interruzione/timeout. Gli script di libreria con piattaforma *Linux/macOS* (informazioni, aggiornamento pacchetti apt/dnf/yum/zypper, riavvio, riavvio servizio systemd, monitor disco/servizio/carico) sono nel seed; i tuoi li crei con piattaforma "Linux / macOS". Le azioni rapide sui servizi usano `systemctl` su Linux.
- **Inventario** nativo (nessuna dipendenza): OS, RAM/CPU %, dischi (filesystem reali ≥ 1 GB, esclusi quelli in sola lettura), IP, seriale/modello (DMI su Linux, `ioreg` su macOS), utente collegato, ultimo avvio. Completo: pacchetti installati (dpkg/rpm/apk; applicazioni su macOS), servizi systemd abilitati con stato, rete, dischi fisici, utenti locali e amministratori.
- **Auto-update**: il server offre a ogni agent il binario della sua piattaforma (`agent-linux-amd64`, …). Riavvio via `systemctl restart` (systemd) o uscita con riavvio da launchd.
- **Non c'è**: patch management (resta Windows Update), controllo servizi su macOS, monitor di sistema Linux oltre ai tre dei seed. macOS è compilato ma **non collaudato su un Mac**: provalo su un device prima di distribuirlo.

**Distribuzione di massa con un altro strumento** (alternativa manuale): vedi 3.1. Se l'EDR blocca l'exe, crea una regola di esclusione.

**Compilazione** (Go 1.22+): `./release.sh` (Linux/macOS/WSL) verifica che le versioni coincidano, compila **tutte e cinque** le piattaforme in `dist/` e prepara
`server/update/` (`agent.exe` per Windows, `agent-<os>-<arch>` per gli altri, `version.txt`). A mano: `cd agent && GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -ldflags "-s -w" -o myrmm-agent .`
In `go.mod` la riga `replace golang.org/x/sys` serve solo in ambienti dove `golang.org` non è raggiungibile: rimuovila altrove.

## 4. Uso della console

Menu (le voci dipendono dal ruolo): **dashboard** · **device** · **script** · **check** · **patch** · **alert** · **filtri** · **regole** ·
**variabili** · **deploy** · **utenti** · **audit**.

**Cerca negli elenchi** (dalla 1.26.2): in tutti i campi Cerca sopra un elenco o un menu a selezione compare l'elenco delle sole voci che corrispondono. Il simbolo `%` vale «qualsiasi cosa»: `ping` trova le voci che contengono ping, `%on%win%` trova «Monitor Windows» e «Monitor SolarWinds». Invio sceglie la prima voce trovata, Esc annulla la ricerca.

- **Clienti** (admin): elenco dei clienti (site) con device, online, alert, stato del token e ultimo contatto. **Nuovo cliente** avvia la procedura guidata: (1) nome, referente e note, (2) comandi di installazione già pronti per Windows e Linux/macOS (più ZIP offline), con attesa in tempo reale del primo device, (3) riepilogo e prossimi passi (variabili, regole, utenti limitati al cliente). Il cliente esiste da subito nei selettori, anche senza device; si elimina solo se non ha device. Il nome non si cambia dopo la creazione.
- **Dashboard**: device totali/online/offline, alert critici/warning, job 24h e falliti, alert aperti. Il riquadro **Flotta** mostra un'etichetta per device (stato + hostname) raggruppata per site; il pulsante **Compatta** passa alla griglia di quadratini (hostname nel tooltip). La scelta resta memorizzata nel browser.
- **Device** (vista unica, ex Device + Inventory): tabella di tutti i device con stato, hostname, site, utente, OS, modello, seriale, RAM, CPU%, RAM%, disco, IP, boot, agent, patch, alert, RustDesk, ultimo contatto e campi personalizzati; ordinamento a clic, colonne a scelta (memorizzate nel browser). Barra strumenti: ricerca testuale veloce, **selettore cliente/site** ("(senza site)" per i non assegnati), **filtro salvato**, **software installato** (Invio: restano solo i device con quel software, con elenco nome/versione), filtri rapidi (offline, con alert, patch da applicare, agent da aggiornare), CSV (device e software). Selezionate più righe (la casella in testa seleziona quelle visibili): **Inventario completo**, **Scansiona/Applica patch**, **Aggiorna agent**, **Imposta campo** e il riquadro **Esegui uno script sui device selezionati** (conta Windows/Linux/Mac e compatibili, salta gli altri, chiede conferma e torna alla vista con l'esito; gli admin possono renderlo ricorrente con monitor e script di risposta). Rispetta i site assegnati all'utente. `?view=inventory` resta valido e porta alla stessa vista.
- **Servizi** (pulsante nella pagina device, operator): elenco **in tempo reale** di tutti i servizi del device (Windows: Gestione servizi; Linux: systemd; macOS: launchd) con stato, tipo di avvio e PID, ricerca e filtri (in esecuzione, fermi, in errore, automatici ma fermi), aggiornamento automatico ogni 5 s. Per ogni servizio: Avvia / Ferma / Riavvia (con conferma) e cambio del tipo di avvio (Windows: automatico, ritardato, manuale, disabilitato; Linux: abilitato/disabilitato). Il servizio dell'agent è protetto. Segue la policy `TM_MODE` (rw / ro solo elenco / off) e `tm_mode` nella config dell'agent. Le azioni finiscono nell'Audit.
- **Pagine a sezioni (dalla 1.15.1)**: Sistema, Script, Pacchetti, Profilo, Deploy, Manutenzione, Campi, Utenti, Variabili, Scadenze, Check, Patch, Regole e Filtri mostrano le loro sezioni come schede a sinistra; il contatore sulla scheda indica gli elementi da guardare.
- **Pagina device** (dalla 1.15.0): in alto stato online/offline, cliente e reparto; a sinistra le **schede** che aprono una sezione per volta (su telefono diventano una barra orizzontale):
  **Panoramica** (stato, sistema, utente collegato, versione agent, inventario sintetico, azioni rapide) · **Salute e patch** (controlli automatici, patch Windows; il contatore mostra cosa richiede attenzione) ·
  **Alert** (storico e note di presa in carico) · **Accesso remoto** (sessione utente, tunnel RDP/SSH, RustDesk, chat) · **Azioni rapide** (diagnostica a un clic, servizi, riavvio/spegnimento, manutenzione) ·
  **Script e job** (script di libreria, nuovo job PowerShell, schedulazioni, storico con stdout/stderr; il contatore indica i job in corso) · **Hardware e software** (inventario completo) ·
  **Cliente e dati** (cliente, reparto, campi personalizzati, asset, variabili effettive) · **Agent** (revoca, disinstallazione, eliminazione, solo admin).
  La scheda aperta si ricorda per ogni device (anche dopo un'azione che ricarica la pagina) ed è indirizzabile con `#t=job`; con la tastiera ↑/↓ si scorre tra le schede. Le schede senza contenuto non compaiono.
- **Audit**: ogni azione (utente, azione, dettaglio, IP, ora).

**Ricerca globale** (`Ctrl K` o `/`): cerca in **tutto l'inventory** dei device nel tuo perimetro: hostname, site, OS, ID RustDesk e qualunque valore dell'inventario leggero e completo (IP, MAC, utente collegato, produttore, modello, seriale, software e versioni, servizi, utenti locali, dischi…). Ogni risultato indica il campo che ha coinciso (`network › ip: 10.0.4.23`). Vale anche per valori parziali (`10.0.4.`) e per i MAC in qualunque formato (`02-fc-00…`, `02fc00…`). Prima i valori uguali alla ricerca, poi quelli che iniziano con essa, poi gli altri. Rispetta i site assegnati all'utente.

## 4.1 File manager, servizi, riavvio e spegnimento (dalla 1.8.0)

**File manager** (solo admin; pulsante *File manager* nella pagina del device, vale per Windows, Linux e macOS):
- naviga dischi e cartelle, **apre** i file di testo (ultimi 64 KB), **scarica**, **carica**, crea cartelle, rinomina, elimina (le cartelle piene chiedono conferma doppia);
- le operazioni sono job firmati HMAC eseguiti nativamente dall'agent (non script) e finiscono nell'audit; non compaiono nello storico job;
- con la scheda aperta il server dice all'agent di interrogare ogni 2 s con heartbeat leggeri (senza inventario): la **prima** risposta può richiedere fino a un battito, poi è quasi immediato. Chiusa la scheda, dopo ~2 minuti si torna al poll normale;
- i file passano dal server in una cartella `transfers/` accanto al database (negata al web, svuotata dopo 2 ore). Ogni trasferimento è verificato con SHA-256;
- **limite**: `FS_MAX_MB` (default 25 MB, regolabile da *Sistema*). Il limite effettivo è il minore tra `FS_MAX_MB`, `upload_max_filesize` e `post_max_size` di PHP: *Sistema* mostra il valore reale e avvisa se l'hosting è più stretto;
- una richiesta non raccolta dall'agent entro 5 minuti scade e **non** viene mai eseguita in ritardo;
- protezioni: non si eliminano radici né la cartella dati dell'agent, i caricamenti sono atomici (file temporaneo + rename) e non sovrascrivono senza consenso.
- **Policy per device**: `"fs_mode": "ro"` (sola lettura) oppure `"off"` in `config.json` dell'agent; il server può inoltre impostare `FS_MODE` globale.

**Task manager** (operator; pulsante *Task manager* nella pagina del device; Windows, Linux, macOS):
- elenco processi **in tempo reale**: CPU % (dell'intera macchina), memoria, thread, utente, comando; totali CPU/RAM con grafico degli ultimi ~2 minuti; filtro, ordinamento per colonna, **raggruppamento per applicazione** (somma le istanze: utile per decidere cosa buttare giù) e pausa;
- **Termina** per singolo processo o **Termina tutti** per applicazione, con opzione "anche i processi figli". Windows: `TerminateProcess` come il Task Manager. Linux/macOS: SIGTERM, poi SIGKILL dopo 3 s se il processo non esce;
- la terminazione è un job firmato verificato su **PID + istante di avvio** (se il PID è stato riusato nel frattempo non colpisce un altro processo) ed è scritta nell'audit;
- i processi di sistema (Windows: System, smss, csrss, wininit, winlogon, services, lsass…; Linux: init e thread del kernel) e l'agent stesso non si possono terminare da qui;
- tecnicamente: finché la pagina è aperta il server chiede all'agent di allegare l'elenco (compresso) ai heartbeat leggeri ogni ~2 s; il server tiene solo l'ultimo elenco per device (nessuna tabella che cresce). La prima volta la risposta può richiedere fino a un minuto. Chiusa la pagina l'invio si ferma entro 15 s;
- per device: `"tm_mode": "ro"` (solo elenco) oppure `"off"` in `config.json` dell'agent.

**Servizi** (operator): scheda *Servizi* del device, con suggerimenti dai nomi nell'inventario completo. Start / Stop / Restart e tipo di avvio (automatico, manuale, disabilitato) su Windows (`Set-Service`), Linux (`systemctl`, "disabilitato" = disable + mask) e macOS (`launchctl`, etichetta del job).

**Riavvio e spegnimento** (operator): scheda *Riavvio e spegnimento*, con preavviso da 1 minuto a 1 ora, messaggio per l'utente e *Annulla programmato*. Windows `shutdown.exe /r|/s /t`, Linux/macOS `shutdown -r|-h +N`. Il conto alla rovescia parte quando l'agent riceve il job.

## 5. Monitor e alert

Due meccanismi, entrambi con **dedup** (un solo alert aperto per device+tipo, chiuso da solo quando la condizione rientra):

1. **Check integrati** (pagina *check*): disco libero % (per volume o tutti), CPU %, RAM %, offline (minuti). Globali o per device;
   per il disco si valutano **tutti** i check applicabili con la severità peggiore. Disco/CPU/RAM a ogni heartbeat, offline al caricamento della console.
2. **Monitor con script** (un monitor basato su script): in una schedulazione, regola o "Esegui su più device" scegli una
   gravità (`info`/`warn`/`crit`). **Exit code ≠ 0 = alert** (messaggio = prima riga di stdout), exit 0 = risolto. Si tengono solo gli ultimi 10 risultati per monitor.

**Rimedio automatico**: a ogni monitor/check disco-CPU-RAM puoi associare uno script che parte quando l'alert **si apre** (una volta per alert,
pausa di 10 minuti per device+script). Il job è visibile nella pagina *alert*.

**Notifiche** all'apertura, configurabili da **Sistema → «Notifiche: email (SMTP), Telegram, Teams, webhook»** (dalla 1.16.0) con pulsante *Prova* per ogni canale e gravità minima per canale: **email** (SMTP con SSL/STARTTLS e password cifrata a riposo; senza host SMTP usa `mail()`), **Telegram** (token del bot + *Cerca gruppi*: elenca le chat che hanno scritto al bot e ne copia l'ID), **Microsoft Teams** (webhook del canale, adaptive card) e **webhook JSON** generico (campo `text`, compatibile Slack). L'ultimo esito di ogni canale è visibile in pagina. Le chiavi di `config.php` `ALERT_EMAIL_TO` / `ALERT_WEBHOOK_URL` restano valide come valori iniziali.
In **manutenzione** un device non apre alert né invia notifiche.

Monitor pronti in libreria: servizio, processo, antivirus/Defender, BitLocker, salute dischi (SMART), riavvio in sospeso, errori nel registro eventi,
ping, porta TCP, dimensione cartella, software vietato. Dalla 1.10.8 anche: spazio libero volumi, RAM, CPU, certificati in scadenza, firewall, orologio/NTP, servizi automatici fermi, accessi falliti, età dell'ultimo file di backup, ultimo update Windows, amministratori locali non previsti, trust di dominio; su Linux: memoria, inode, riavvio necessario, unit systemd in errore, aggiornamenti in sospeso, certificato TLS, porta, ping, NTP, SSH falliti, backup recente.

## 6. Script, variabili, filtri, regole

- **Selettore clienti** (barra alta, se i clienti sono almeno due): uno, più d'uno o tutti (1.38.2, sezione 8.38); «Tutti i clienti» toglie il filtro.
- **Libreria script** (`script`; cerca per nome/descrizione/variabile e filtra per categoria; dalla 1.10.8 circa 170 script pronti, vedi sotto): PowerShell riusabili con placeholder `{{NOME}}`. La sostituzione è **testuale**: metti tu il quoting
  (es. `-Name '{{SERVIZIO}}'`). Per i valori numerici usa il pattern `if ('{{X}}') { [int]'{{X}}' } else { 14 }` per avere un default.
  18 script seedati (deploy, RustDesk x2, riavvio servizio, coda di stampa, pulizia, aggiornamenti Windows, 11 monitor); i seed si aggiungono per nome e non toccano le tue modifiche.
- **Variabili** (`variabili`): globali, per **site** o per **device**; precedenza *valore esplicito > device > site > globale*. Sempre disponibili `HOSTNAME`, `SITE`, `DEVICE_ID`.
- **Schedulazioni** (pagina device): script + intervallo in minuti (+ monitor e rimedio). Valutate al heartbeat; se il device è offline parte un solo catch-up.
- **Esegui su più device** (pagina *script*): bersaglio = site, nome, solo online, filtro salvato; esecuzione **una tantum** (operator) o **ricorrente/monitor** (admin).
- **Filtri** (`filtri`, admin): gruppi **dinamici** costruiti a condizioni, con anteprima dei device prima di salvare.
  - Ogni condizione = campo + operatore + valore, con **NON** per negarla; il filtro richiede *tutte* le condizioni o *almeno una*.
  - Campi: stato del device (hostname, site, OS, piattaforma, online/offline, minuti dall'ultimo contatto, alert aperti, manutenzione, riavvio richiesto, giorni dall'arruolamento, versione agent, ID RustDesk), **inventario leggero** (RAM, CPU, dischi, IP, utente, modello, seriale, ultimo avvio…), **inventario completo** (software e versione, hotfix, servizi automatici, utenti locali, amministratori, BIOS, GPU, dominio, rete, dischi fisici e volumi…), i tuoi **campi personalizzati** e *"appartiene al filtro"* (filtri annidati, anche negati). Il percorso libero (`inv:` / `full:`) raggiunge qualunque chiave dell'inventario.
  - Operatori: contiene, uguale, inizia/finisce con, regex, vuoto, `>` `<` `≥` `≤`, versione inferiore/superiore a (confronto numerico: 10.2 < 10.10), data più vecchia/recente di N giorni (anche `12h`, `45m`) o in scadenza entro N giorni.
  - Sulle liste (software, dischi, servizi…) la condizione vale se **almeno un elemento** la soddisfa; con *+ stesso elemento* si impongono altre proprietà sullo **stesso** elemento (servizio `Spooler` **e** stato `Stopped`; Chrome **e** versione < 100).
  - I filtri esistenti si modificano; quelli salvati con le versioni precedenti continuano a funzionare. Si applicano in Device (menu "filtro salvato", anche nel CSV), Esegui su più device, regole e policy patch.
- **Campi personalizzati** (`campi`, admin): informazioni aggiuntive per device (ubicazione, reparto, contratto, scadenza garanzia, responsabile…).
  - Tipi: testo, numero, data, sì/no, elenco; fino a 60. La chiave (minuscole, cifre, `_`) non cambia; etichetta, tipo, voci e ordine sì.
  - Valori: dalla scheda del device (operator), **in blocco** dalla vista Device (selezioni le righe → *Imposta campo*) o per filtro (pagina *Campi*), oppure **da script**: una riga `MYRMM_FIELD:nome=valore` nello stdout imposta il campo del device che ha eseguito il job (anche schedulato o monitor); i valori non validi per il tipo sono ignorati. Esempio: `Write-Output "MYRMM_FIELD:dominio=$env:USERDOMAIN"`.
  - Uso: colonne in Device (visibili di default se *colonna visibile*; si nascondono dal selettore Colonne), colonne nel CSV, condizioni nei filtri, ricerca globale, e variabili negli script `{{CF_NOME}}` (maiuscolo).
- **Regole** (`regole`, admin): uno script/monitor (con rimedio) applicato a un filtro **in modo dinamico**: i device nuovi o che entrano nel filtro ricevono la schedulazione al primo contatto (entro 5 min), quelli che escono la perdono.

### Script in libreria (1.10.8)

Windows — **Informazioni e inventario**: informazioni sistema, software installato, stato attivazione licenza, utenti locali, amministratori locali (con controllo), sessioni utente, hotfix installate, condivisioni SMB, porte in ascolto con processo, attività pianificate non Microsoft, stampanti, ultimi riavvii/crash, accessi falliti 24 h.
**Azioni**: disinstalla software (silenzioso), crea/reimposta utente locale, abilita/disabilita utente, chiudi sessioni disconnesse, messaggio agli utenti, riavvia/spegni con avviso e annulla, rinomina computer, fuso orario e ora, alimentazione sempre attiva, disabilita avvio rapido, RDP on/off, firewall on, disabilita SMBv1, gpupdate, pulizia disco approfondita, rimozione profili inattivi (anteprima di default), Defender firme + scansione, punto di ripristino.
**Riparazione**: svuota DNS, reset stack di rete, riavvio adattatori, reset componenti Windows Update, DISM + SFC, test connettività.
Linux/macOS: porte in ascolto, directory più pesanti, processi per memoria, utenti/sudo/ultimi accessi, crea utente con chiave SSH, hostname, pulizia log e cache pacchetti, pulizia Docker, sincronizza ora, aggiornamenti macOS.
**Monitor del registro eventi (1.10.9)** — ognuno accetta `MINUTI` (finestra) e `SOGLIA` (numero minimo di eventi); se il registro non esiste (ruolo non installato) restituiscono OK. Pronti: riavvio inatteso/crash (41, 6008), BugCheck, servizio terminato (7031/7034), errori disco/NTFS, crash applicazioni, errori Application e System, Windows Update fallito, account bloccato (4740), nuovi utenti/gruppi privilegiati, nuovo servizio installato (7045), registro eventi cancellato (1102/104), Directory Service, DFS Replication, DNS Server, Netlogon, Hyper-V (VMMS e Worker), Failover Cluster, Windows Server Backup, Veeam, minacce Defender, W32Time, spooler di stampa. Per qualsiasi altro caso c'è **«Monitor evento: ricerca libera»** con filtri `LOG`, `ID_EVENTO`, `LIVELLO`, `ORIGINE`, `TESTO`. Gli eventi di sicurezza richiedono l'audit attivo: usa «Windows: abilita audit accessi e account».
Altri monitor Windows: task pianificati falliti, uptime massimo, dispositivi in errore, update in sospeso, attivazione Windows, shadow copy recente, memoria di un processo, dimensione/presenza file, share UNC, DNS, URL HTTP, Hyper-V (VM ferme, replica, checkpoint vecchi), cluster, replica AD, DHCP, IIS. Utility: cerca negli eventi, esporta EVTX, dimensione registri, accessi RDP riusciti, ruoli e funzionalità, processi per memoria, cache browser.
Linux: pattern nel journal/log, errori journal, OOM killer, errori disco nel kernel, SMART, RAID/ZFS, container Docker, processo, mount point, URL, certificati Let's Encrypt, uptime, swap, coda Postfix, zombie; utility journal, stato dischi, Docker, certbot, riavvio solo se necessario.
Gli script modificati da te non vengono sovrascritti agli aggiornamenti; quelli nuovi compaiono da soli al primo accesso dopo l'upload di `index.php`. Le variabili `{{NOME}}` si compilano al lancio; molte hanno un default (indicato nella descrizione).

### Esegui su…, Attività, Pacchetti di monitor (1.10.11)

- **Esegui su…** (pulsante nella libreria script): scegli i bersagli (cliente, nome contiene, solo online, filtro salvato), compila le variabili e lancia **subito** o in modo **ricorrente/monitor** (admin). Un'anteprima in tempo reale mostra quanti e quali device verranno colpiti e quanti sono esclusi perché il sistema operativo non è adatto allo script. Dopo l'invio si arriva ad *Attività*.
- **Attività** (*Operazioni*): cronologia dei job di tutta la flotta (nascosti di default quelli del file/task manager) con ricerca, filtro per esito (falliti, in coda, riusciti) ed export CSV. Rispetta il selettore cliente.
- **Pacchetti** (*Operazioni*, admin): insiemi di monitor pronti con intervallo, gravità e variabili. Inclusi: *Windows base*, *Windows Server*, *Windows workstation*, *Domain controller*, *Host Hyper-V / cluster*, *Linux server*. **Applica** a un cliente, a un filtro o a tutti: ogni controllo diventa una **regola dinamica** (anche i device installati dopo la ricevono). Se due pacchetti contengono lo stesso monitor non viene duplicato; gli script non adatti all'OS vengono saltati; **Rimuovi** toglie il pacchetto da un ambito e cancella le schedulazioni derivate. I pacchetti si possono modificare (aggiungi/togli controlli) o crearne di propri; quelli predefiniti vengono creati una volta sola.
- **Clienti → rinomina**: cambia il nome di un cliente aggiornando device, token, variabili, utenti limitati e filtri; se il nome esiste già, spunta *unisci* per fondere i due clienti.
- **Dashboard**: tabella *Clienti* (device, online/offline, critici, warning, patch, ultimo contatto) ordinata per problemi; un clic seleziona il cliente.
- **CSV**: Alert (aperti o storico), Attività, Inventario, Software.

### Manutenzione, gestione alert, report, scadenze, pulizia, diagnostica (1.10.12)

- **Manutenzione** (admin): finestre una tantum o settimanali (giorni + orario, anche a cavallo della mezzanotte, nel fuso `PATCH_TZ`) per tutti i device, un cliente o un filtro; pulsanti «1/2/4/8/24 h» per manutenzione immediata. Durante la finestra non si aprono nuovi alert né notifiche (quelli già aperti restano); il device mostra l'avviso in scheda e in inventario.
- **Alert**: colonna *Gestione*: **prendi in carico** (con nota), **posticipa** 4 h / 24 h (non conta più nel badge e nella dashboard fino alla scadenza), **chiudi** a mano. In carico/nota compaiono anche nell'export CSV.
- **Report mensile** (Clienti → Report): disponibilità stimata dagli alert offline, alert per gravità/tipo, device con più alert, operazioni, patch, parco macchine, pacchetti applicati, scadenze entro 90 giorni. «Stampa / salva PDF» usa lo stile di stampa.
- **Scadenze** (operatore): licenze, garanzie, certificati, domini, contratti per cliente; compaiono in dashboard in «Da guardare» e nel report; export CSV.
- **Dati e pulizia** (Sistema): conservazione in giorni (`RETENTION_DAYS`), «Pulisci ora» e compattazione opzionale del database (con backup `prerestore` prima).
- **Diagnostica rapida** (scheda device): un clic per info sistema, errori recenti, processi, rete, porte, sessioni/utenti; il risultato appare nella scheda in pochi secondi.

### Report con grafici, email mensile, fine supporto, diagnostica per cliente (1.10.13)

- **Report mensile**: ora con grafici (alert per giorno e gravità, tipi, device più problematici, andamento a 6 mesi, disponibilità per mese) e **confronto con il mese precedente** (▲/▼ su disponibilità, alert, tempo di risoluzione).
- **Report via email** (Sistema → «Report mensile via email»): indirizzi separati da virgola. Il primo giorno del mese, al primo passaggio di un agent, parte un'email HTML per ogni cliente (mese precedente); «Invia per email» nel report e «Invia ora…» in Sistema lo fanno a richiesta. Usa `mail()` del server come le notifiche.
- **Dashboard**: tessere *Disponibilità 30 g* e *MTTR 30 g*; grafici degli alert per gravità negli ultimi 14 giorni, sistemi operativi, alert aperti per cliente.
- **Fine supporto dei sistemi operativi** (Scadenze, report, «Da guardare»): calcolato dall'inventario (Windows 7/8/10, Server 2008–2022, Ubuntu, Debian, CentOS 7); date indicative del supporto standard.
- **Diagnostica del cliente** (Clienti → Diagnostica): una verifica su tutti i device online del cliente, esito per macchina con output espandibile.
- **Manutenzione con pausa**: opzione per sospendere anche gli script schedulati (i monitor continuano) e l'installazione delle patch; riprendono a fine finestra.
- **Storico alert e note** nella scheda device: ultimi 20 alert con chi li ha presi in carico e le note.

### Script documentati (1.10.14)

- Ogni script della libreria ha ora una **descrizione estesa** (cosa fa, se è sola lettura o se modifica il sistema, avvertenze) e un'**intestazione di commento nel codice** con la spiegazione di ogni variabile.
- Nell'elenco **Script**, accanto a ogni script, c'è ogni variabile con *obbligatoria/opzionale*, default e spiegazione. Gli stessi suggerimenti compaiono sotto i campi nei form «Esegui su…», regole, schedulazioni, «Esegui script dalla libreria» e nella pagina di esecuzione.
- **Per i tuoi script**: aggiungi nel corpo righe di commento nel formato `# @var NOME (obbligatoria|opzionale, default X): spiegazione`. Vengono lette da myrmm e mostrate come sopra; per le variabili senza riga `@var` si usa il glossario generico se il nome è noto.
- Gli script di libreria vengono aggiornati automaticamente solo se non li hai modificati; quelli che hai modificato restano come sono.

### Raccolta inventario (1.10.15)

Dieci script «Raccolta …» (Windows e Linux/macOS: sicurezza, sistema e hardware, rete, batteria, speedtest) scrivono lo stato reale dei device nei **campi personalizzati** stampando righe `MYRMM_FIELD:chiave=valore`. I 48 campi del catalogo si creano da soli alla prima raccolta (o tutti insieme da **Campi → Crea i campi mancanti**); il limite campi è salito a 100.

- **Sicurezza**: BitLocker/LUKS/FileVault (+ chiave di ripristino), TPM, Secure Boot, antivirus, età firme Defender, firewall, UAC, RDP, SMBv1, SSH root, SELinux/AppArmor/SIP, amministratori locali, Windows attivato, ultimo aggiornamento, riavvio in sospeso, aggiornamenti in attesa.
- **Sistema**: modello, seriale, BIOS, CPU, RAM, GPU, tipo dispositivo, disco di sistema (totale/libero/tipo), sistema operativo, kernel, data installazione, uptime, ultimo utente, dominio/Entra ID, hypervisor, fuso orario, programmi installati, Office.
- **Rete**: IP locale e gateway, DNS, cavo/Wi-Fi (SSID), IP pubblico.
- **Batteria**: stato e carica, salute (% della capacità di progetto), cicli. Sui desktop «Nessuna batteria».
- **Speedtest** (Cloudflare, flusso singolo, valore indicativo): download, upload, latenza, data. Variabili `MB_DOWN` (25) e `MB_UP` (10).

I pacchetti **Raccolta inventario** (giornaliero; hardware settimanale) e **Speedtest connessione** (settimanale, ~35 MB per test) si applicano da *Pacchetti* a un cliente o filtro: ogni device riceve solo gli script adatti al suo sistema. La dashboard mostra il pannello **Conformità flotta** (quanti device non conformi per controllo) e in «Da guardare» le batterie sotto il 60% e i portatili senza cifratura. I valori sono usabili in filtri, colonne e come `{{CF_NOME}}`.

### Controlli sui campi → alert (1.10.16)

In **Campi → Controlli sui campi** definisci condizioni sul valore di un campo (è uguale / diverso / minore / maggiore / contiene / non contiene / è vuoto), con gravità e, se vuoi, un filtro. Quando una raccolta (o qualunque script con `MYRMM_FIELD`) porta il valore in condizione si apre un alert `Nome controllo: Campo = valore`, con notifiche, manutenzione, silenziamento e storico come per i monitor; quando il valore rientra l'alert si chiude da solo. I numeri si confrontano come numeri, i Sì/No si scrivono «si»/«no». Senza dato non si segnala (tranne «è vuoto»). Creando, attivando o disattivando un controllo tutti i device vengono rivalutati. «Aggiungi i consigliati» crea in un colpo: disco non cifrato, firewall spento, firme antivirus oltre 7 giorni, SMBv1, batteria sotto il 60%, disco di sistema sotto 10 GB liberi, uptime oltre 60 giorni, download sotto 10 Mbps. Modificare a mano un campo dalla scheda del device non rivaluta i controlli: succede alla raccolta successiva.

### Alert in carico, spostamenti, reparti, ripristino script (1.10.18)

- **Alert → «lavorazione…»**: su ogni alert aperto (operator) puoi assegnarlo a un altro utente (o toglierlo), aggiungere una nota, registrare **tempo dedicato** (minuti, a mano, cumulabile) e una **data prevista di fine lavori**: tutto facoltativo. Ogni voce resta nel **Registro di lavorazione** della scheda del device (autore e orario). In *Alert* i filtri «Tutti / In carico a me / Non assegnati»; la nuova vista **In carico** raggruppa gli alert per operatore (non assegnati in evidenza, date scadute, tempo totale) e mostra il tempo registrato negli ultimi 30 giorni per operatore e cliente. La dashboard ha il contatore «Non in carico» e il **report mensile** la tabella «Tempo dedicato agli alert».
- **Sposta device fra clienti** (admin): da *Device* seleziona le righe → «Sposta in cliente», oppure dalla scheda del device («Cliente e reparto»). Cambiano cliente, regole e pacchetti applicati (al primo contatto); lo storico resta del device. Il reparto si mantiene solo se esiste con lo stesso nome nel nuovo cliente.
- **Reparti**: etichetta dentro il cliente, gestita in **Clienti → Reparti** (crea, rinomina, elimina). Si assegna in blocco da *Device* («Imposta reparto»), dalla scheda, oppure **installando con il token del reparto** (i nuovi device arrivano già etichettati; comando e ZIP nella pagina Reparti). Colonna «Reparto» in Device, nome nel tooltip della Flotta, campo «Reparto» nei filtri e variabile `{{REPARTO}}`.
- **Libreria script**: gli script del pacchetto modificati da te mostrano il tag «modificato»; in «modifica» il pulsante **Ripristina versione originale** (admin) riporta corpo, descrizione, timeout e piattaforma a quelli del pacchetto.

## 7. Patch management

Pagina *patch*. Windows Update via COM (nessun modulo esterno).

1. **Policy** (admin): target (un filtro o tutti), **finestra** (giorni + ora di inizio/fine nel fuso `PATCH_TZ`, non attraversa la mezzanotte),
   **approvazione** manuale oppure automatica per severità (Critical/Important/Moderate/Low, più opzione "senza severità"), **riavvio** mai / se richiesto (preavviso 10 min).
2. **Scansione** ogni 12 ore e dopo ogni installazione → elenco patch mancanti per device e per flotta.
3. **Approvazione** per singola patch (approva / rifiuta / azzera): vale per tutta la flotta. Una patch rifiutata non si installa mai, nemmeno in automatico.
4. **Installazione**: una volta per finestra, solo le patch approvate. Esito per patch; alert `patch_failed` se qualcosa fallisce.
5. Un device **senza policy non viene toccato**. "Scansiona ora" è nella pagina device (operator).

Consiglio: prima di estendere una policy, provala su un device con approvazione manuale e una finestra breve.

## 8. Utenti e ruoli

| Ruolo | Può fare |
|---|---|
| `viewer` | dashboard, device, alert (sola lettura) |
| `operator` | + job, azioni su servizi, manutenzione, "scansiona ora", esecuzione una tantum su più device, CSV; vede script, check, patch |
| `admin` | tutto: script, schedulazioni, check, variabili, filtri, regole, policy/approvazioni patch, utenti, audit, deploy |

Gli utenti si creano in *utenti* (password ≥ 10 caratteri, `password_hash`). Ogni utente può essere **limitato a uno o più site**: vede solo i loro device,
alert, dashboard ed export. L'admin integrato (`CONSOLE_USER/PASS`) funziona sempre. Le POST con Origin/Referer di un altro host sono rifiutate (anti-CSRF).

## 8.1 Asset senza agent (1.11.0)

Menu **Asset**: inventario di tutto ciò che non ha un agent (SIM, stampanti, switch, access point, firewall, telefoni, NAS, licenze, domini/certificati…).

- **Tipi**: generici e modificabili da *Asset → Tipi* (admin). Alla prima apertura vengono creati 10 tipi precompilati; ogni tipo ha campi propri (testo, numero, data, URL, testo lungo, **password**).
- **Scheda asset**: nome, cliente, reparto, ubicazione, stato, seriale, modello, acquisto, scadenza, device collegati (uno principale e quanti altri servono, §8.39), indirizzi/campi del tipo, note con data e autore, allegati (§8.39), documenti collegati.
- **Password**: cifrate nel database (AES-256-GCM), mai presenti nell'HTML; si rivelano con "Mostra" e ogni visualizzazione è registrata nell'audit. Chi può vedere l'asset (in base al perimetro clienti) vede le password, qualunque sia il ruolo; solo operatori e admin modificano.
- **Scadenze**: la scadenza dell'asset compare in Scadenze e nella dashboard.
- **Device collegato**: la scheda del device mostra gli asset collegati.
- **CSV**: import ed export dalla pagina Asset.
- **Ricerca**: gli asset compaiono nella ricerca globale (Ctrl+K) per nome, seriale, indirizzi, ubicazione ecc. (le password non sono ricercabili).
- **Etichette QR**: «Etichetta QR» nella scheda, o «Stampa etichette QR di questo elenco» nella lista (fino a 200). Pagina stampabile 64×30 mm con QR, nome, tipo, cliente/reparto e seriale; il QR apre la scheda dell'asset (serve il login). Ogni stampa è registrata nell'Audit.

## 8.2 Sessione utente e disinstallazione dell'agent (1.11.1)

**Sessione utente.** L'agent riporta chi è collegato e in che stato: *attiva*, *bloccata* (schermata di blocco), *disconnessa* (sessione RDP/console scollegata ma ancora aperta), *inattiva* (Linux: sessione aperta ma non in primo piano) o *nessuna*. Windows usa le API di sessione (anche per i server con solo RDP), Linux `loginctl` (con ripiego su `who`), macOS l'utente della console. La scheda del device mostra stato, utente e le altre sessioni; l'elenco Device ha le colonne **Sessione** e **Ultimo utente** e i filtri «online, nessuno collegato» e «sessione bloccata o disconnessa». L'**ultimo utente visto** resta memorizzato anche quando nessuno è collegato. Nei filtri e nelle regole: campi `Sessione utente` e `Ultimo utente visto`.

**Rimuovi e disinstalla agent** (solo admin, scheda del device › *Accesso dell'agent*). Segna il device «in disinstallazione»; al contatto successivo l'agent verifica la firma (stessa `job_signing_key` dei job: senza chiave non esegue), conferma al server, poi ferma ed elimina servizio, binario e dati; il server elimina il device con il suo storico (gli asset collegati restano, scollegati). Si può annullare finché l'agent non si è collegato. Se il PC è spento o dismesso usa **Elimina solo dall'elenco**, che non tocca l'agent (se il PC è ancora acceso si riarruola). Un agent che il server non riconosce *non* si disinstalla mai: si riarruola.

## 8.3 Chat con l'utente e icona nella systray (1.12.0, solo Windows)

**Icona.** Sui PC Windows il servizio dell'agent avvia l'icona in ogni sessione utente attiva, con i diritti di quell'utente (dalla 1.67.0: nessuna attività pianificata e nessun programma a parte, §8.66). L'icona «m» nella systray è blu se l'agent è collegato al server, grigia altrimenti; il menu mostra nome del device, versione dell'agent e stato del collegamento, più **Contatta l'assistenza…**. Per disattivare tutto su un device: scheda del device › **Assistenza utente** › *Disattiva icona e chat* (o dal menu **Assistenza utenti → Icona sui PC**) (dalla 1.26.1: arriva al PC entro un minuto, senza riavvii, e si riattiva con lo stesso pulsante; la scelta della console prevale su `config.json`); oppure `"tray_mode": "off"` nella config dell'agent. Se dopo l'installazione l'icona non compare perché nessun utente ha ancora fatto l'accesso, la diagnostica lo segnala come informazione, non come avviso. La porta locale (default 47653, solo 127.0.0.1) si cambia con `tray_port`.

**Chat.** Dal menu **Assistenza utenti** (operatori e admin) o dalla scheda del device › *Assistenza utente* › *Apri chat*; dall'elenco Alert il pulsante **Chat con l'utente** apre la conversazione già collegata a quell'alert. L'utente riceve una notifica e risponde dalla finestra «Assistenza». Ogni messaggio dell'operatore mostra lo stato: *in attesa* (non ancora preso dall'agent), *consegnato* (sul PC), *letto* (finestra aperta). Con la finestra aperta, da una parte o dall'altra, l'agent passa al collegamento rapido (pochi secondi di latenza); altrimenti il messaggio arriva al contatto successivo (di norma entro 15 s). Se nessuno è collegato al PC il messaggio resta in coda e viene mostrato al prossimo accesso. Il menu Chat mostra un contatore delle conversazioni con messaggi non letti.

**Screenshot e immagini** (1.63.0): l'utente può inviare uno screenshot (sempre con anteprima e conferma), allegare o incollare un'immagine; l'assistenza può allegare, incollare, trascinare immagini o chiedere uno screenshot, e condividerle su device e ticket — vedi §8.62.

**Archiviare e collegare agli alert.** *Archivia conversazione* la sposta nelle archiviate (un nuovo messaggio la riapre). Se la chat è collegata a un alert, l'archiviazione aggiunge la trascrizione (ultimi 60 messaggi) come nota di lavorazione dell'alert. Il collegamento si cambia dal menu «Alert collegato».

**Sicurezza.** L'API locale ascolta solo su 127.0.0.1, rifiuta richieste senza l'intestazione dedicata o con un host diverso (niente accesso da pagine web) ed espone soltanto la conversazione; non dà accesso a job, chiavi o file. Su server con più utenti collegati (RDP) la conversazione è una sola per device e la vedono tutti gli utenti di quel server. I testi dell'utente e dell'operatore sono conservati nel database; nell'Audit compare solo che un messaggio è stato inviato, non il contenuto.

## 8.4 Tunnel RDP / SSH attraverso il server (1.14.0)

Per collegarti con il **tuo account** al Desktop remoto (o a SSH/VNC) di un device senza aprire porte né VPN: il device e il tuo PC si collegano in uscita al server, che fa da relay.

1. Scheda del device › riquadro **Tunnel** › scegli la porta (3389 Desktop remoto, 22 SSH, 5900 VNC) › **Apri tunnel**. Serve il ruolo *operator*; il device deve essersi collegato negli ultimi 10 minuti.
2. La pagina del tunnel mostra un comando da eseguire **sul tuo PC** (PowerShell): scarica prima l'helper dalla stessa pagina (è lo stesso `agent`, non installa nulla).
   `.\agent.exe tunnel -u "https://…/index.php" -id <id> -token <token> -listen 127.0.0.1:13389 -rdp`
3. Con `-rdp` l'helper apre `mstsc` verso `127.0.0.1:13389` (oppure scarica il file `.rdp` dalla pagina, o collega `mstsc /v:127.0.0.1:13389`; per SSH: `ssh -p 13389 utente@127.0.0.1`). Accedi con il tuo account di Windows: il login (NLA) avviene tra il tuo client e il device, **il server non vede le credenziali**.

Sicurezza:
- l'apertura è una richiesta **firmata** (stessa chiave dei job): l'agent la rifiuta se la firma è errata, se è scaduta, se la porta non è nella sua lista (`tunnel_ports` nel `config.json` dell'agent; `"tunnel_mode": "off"` disattiva i tunnel su quel device) e si collega **solo a 127.0.0.1** del device;
- l'helper accetta solo indirizzi di loopback e un'unica connessione; il token del tunnel vale solo per quel tunnel (nel server resta solo il suo hash) e non compare negli URL;
- un tunnel si chiude da solo dopo 10 minuti senza traffico, a fine durata, se nessuno si collega entro 5 minuti, o con «Chiudi tunnel». Apertura, collegamento e chiusura (con il traffico) sono nel registro di audit.

Limiti: il relay è PHP su hosting condiviso, quindi la latenza è quella di un giro HTTP (decine o centinaia di millisecondi): va bene per amministrare, meno per lavori grafici. Il tunnel regge più connessioni (mstsc, dopo l'accettazione del certificato, chiude la prima e ne apre un'altra): si chiude quando l'ultima è terminata da 25 secondi (`-grace` dell'helper), con Ctrl+C o dalla console. Il Desktop remoto deve essere attivo sul device (libreria script: «Windows: abilita/disabilita Desktop remoto (RDP)»).

### 8.4.1 Tunnel e controllo remoto su Linux e macOS (1.37.1)

Il tunnel funziona già su ogni piattaforma (l'agent è lo stesso); mancava la preparazione del device e il lancio dei client. Ora:

| Per collegarti a… | Prepara il device con lo script (libreria) | Porta del tunnel | Comando mostrato nella pagina del tunnel |
|---|---|---|---|
| **Linux via SSH** | *Linux/macOS: abilita/disabilita SSH (per i tunnel)* | 22 | `… -listen 127.0.0.1:13389 -ssh <utente> -alias myrmm-d<id>` |
| **Linux, desktop** | *Linux: abilita/disabilita desktop remoto (xrdp)* | 3389 | `… -rdp` (xfreerdp o Remmina) |
| **macOS via SSH** | *Linux/macOS: abilita/disabilita SSH (per i tunnel)* (Login remoto) | 22 | come Linux |
| **macOS, schermo** | *macOS: abilita/disabilita Condivisione schermo (VNC)* | 5900 | `… -vnc` (apre Condivisione schermo) |

- **Helper dell'operatore** (qualunque sistema, anche Linux/macOS): `-ssh <utente>` avvia `ssh` nel tuo terminale sul tunnel e chiude il tunnel all'uscita; la pagina del tunnel chiede l'utente e compone il comando. `-alias` fissa un nome per la chiave host (`HostKeyAlias`), così la chiave del device viene verificata e ricordata e non si mescola con quella di altri device su `127.0.0.1`; la prima volta viene accettata (`accept-new`). `-vnc` apre il client VNC (macOS: Condivisione schermo; Linux: `xdg-open vnc://`). `-rdp` ora funziona anche su macOS (app «Windows App / Microsoft Remote Desktop», tramite un file `.rdp` temporaneo) e Linux.
- **Scheda del device**: il riquadro Tunnel propone la porta giusta per sistema (3389 Windows, 5900 macOS, 22 Linux) e indica quale script serve.
- **Gli script cambiano il sistema solo se richiesto** e verificano il risultato: dopo «abilita» controllano che la porta sia davvero in ascolto, dopo «disabilita» che sia chiusa; altrimenti terminano con errore (il job risulta fallito). Aprono la porta anche su `ufw`/`firewalld` se attivi.
- **Limiti onesti**: gli script sono provati con comandi finti (`ci/unix_scripts_test.py`, sia con `dash` sia con `bash`), non su macOS reale. Su macOS recenti l'attivazione della Condivisione schermo (`kickstart`) e l'uso di RustDesk richiedono permessi di privacy (Accesso completo al disco per l'agent, Registrazione schermo e Accessibilità per RustDesk) che si concedono a mano o con un profilo MDM: lo script lo segnala se la porta non si apre. xrdp apre una sessione grafica separata e richiede un ambiente desktop sul server; su RHEL/Rocky serve EPEL.

## 8.5 Metriche e grafici (1.16.0)

Ogni device ha la scheda **Metriche** con un grafico per serie (CPU, RAM, ogni volume, più i valori dei monitor script), intervallo a scelta (24 ore, 7, 30, 90 giorni, 1 anno): linea della media e fascia min–max; i buchi (device spento) interrompono la linea.

- **Da heartbeat**: CPU %, RAM % e occupazione % di ogni disco, un campione ogni `METRICS_INTERVAL_MIN` minuti (default 5).
- **Da script**: ogni riga `MYRMM_METRIC nome=valore [unità]` nello stdout di un job (anche monitor o schedulato) aggiunge un campione, ad es. `Write-Output "MYRMM_METRIC latenza_ms=12,5 ms"`. Nome fino a 60 caratteri, valore numerico (virgola ammessa), massimo 200 serie per device. Le righe `MYRMM_METRIC` non diventano mai il messaggio dell'alert.
- **Monitor della libreria**: spazio libero volumi (% e GB), RAM, CPU media, ping (ms e perdita), scarto NTP, accessi falliti, età backup, età ultimo update, uptime, aggiornamenti mancanti, età shadow copy, memoria processo, dimensione file e cartella; su Linux disco, RAM, inode, load, swap, aggiornamenti. Gli script non modificati si aggiornano da soli; quelli personalizzati restano come sono (aggiungi tu le righe `MYRMM_METRIC`).
- **Database separato** `metrics.sqlite` accanto a `myrmm.sqlite` (WAL, `auto_vacuum` incrementale): non entra nei backup e non appesantisce il database principale. Tre livelli: **grezzi** `METRICS_RAW_DAYS` (7), **medie orarie** min/media/max `METRICS_HOURLY_DAYS` (90), **medie giornaliere** `METRICS_DAILY_DAYS` (400). L'aggregazione e la pulizia girano nel lavoro orario. A regime sono circa 1–1,5 MB per device (CPU, RAM e due dischi): 100 device ≈ 150 MB, senza crescita oltre la retention. Si può cancellare il file in qualsiasi momento: ricomincia da zero. Eliminando un device se ne cancellano anche le metriche.
- Impostazioni in **Sistema → Impostazioni → Metriche**; `METRICS_MODE=off` le disattiva del tutto.

## 8.7 Ricerca (1.19.0)

La barra in alto (Ctrl K o «/») cerca nell'inventory (device, IP, MAC, utente, seriale, software), negli asset, nelle pagine e, dalla 1.19.0, nei **filtri salvati** («Filtro · nome» → elenco device filtrato) nei **runbook** e negli **script della libreria** (apre «Esegui su…»). Ogni menu a tendina con almeno 8 voci ha accanto un campo **Cerca…**: filtra le voci mentre scrivi, **Invio** sceglie la prima corrispondenza, la freccia giù passa al menu. Restano esclusi i menu in alto (cliente) e quelli con gruppi.

## 8.6 Job: tipi, ricerca, sequenze e runbook (1.17.0)

Nella scheda **Script e job** del device ogni job porta un'etichetta: **manuale** (lanciato dalla console, anche da libreria o in sequenza), **schedulato**, **monitor** (schedulazione con gravità: è lo script di controllo che apre/chiude alert) o **sistema** (patch, regole, rimedi). Il menu *Tipo* sopra l'elenco filtra per tipo, in aggiunta a «solo falliti». L'elenco delle schedulazioni si chiama *Schedulazioni e monitor* e mostra prima i monitor.

**Esegui script dalla libreria**: il campo *Cerca script* filtra l'elenco per nome mentre scrivi (si vedono solo gli script adatti al sistema del device). *Esegui ora* lancia lo script una volta.

**Sequenza**: *Aggiungi alla sequenza* mette lo script selezionato, con le variabili compilate, in una lista ordinabile (↑ ↓ ×; fino a 20 passi, anche lo stesso script più volte). *Avvia sequenza* accoda **un solo job alla volta**: il passo successivo parte quando l'agent ha riportato il risultato del precedente. Con *fermati al primo errore* (default) un exit code diverso da 0 o un job interrotto chiude la sequenza; senza, si prosegue comunque. I passi sono job normali con origine «sequenza #N passo k» (tipo *manuale*); l'avvio finisce nell'audit. Se il device resta offline la sequenza aspetta. Tabella `job_seq`.

**Runbook (1.18.0)**: una sequenza si salva con un nome (*Salva come runbook*; stesso nome = aggiorna) e si ricarica dal menu *Runbook salvati* della scheda Script e job. La pagina **Runbook** (menu Operazioni) elenca i passi di ciascuno e li avvia su **più device** con la stessa selezione di «Esegui su…» (cliente/site, nome contiene, filtro, solo online) e anteprima dei device colpiti; i device su cui un passo non è adatto al sistema operativo sono saltati. Ogni device riceve la sua sequenza indipendente (job_seq). Le variabili dei passi sono quelle salvate nel runbook; i campi vuoti si risolvono con le variabili del device. Ruolo operator. Tabella `runbooks`.

## 8.8 Prova di carico (1.20.0)

In **Sistema → Prova di carico** un pulsante simula una flotta di device sintetici e misura quanto regge il server (e l'hosting).

- **Cosa fa**: crea fino a 1000 device fittizi (sito «(prova di carico)», silenziati, nessun alert) e, dal tuo browser, invia heartbeat completi, inventari e risultati di job con l'agent simulato; contemporaneamente naviga la console come uno o più operatori e misura i tempi di pagina.
- **Profili**: «normale» (contatto ogni 15 s), «intenso» (ogni 5 s) e «scalata» (aumenta il ritmo a gradini fino a trovare il limite).
- **Risultato**: verdetto in parole semplici (quanti device equivalenti regge con p95 sotto 1 s e senza errori), tabella per gradino (richieste/s, p50/p95/p99, errori), grafici, crescita del database e report JSON scaricabile. Un benchmark separato misura scrittura su disco, CPU, lettura e JSON del server.
- **Pulizia**: i device sintetici sono eliminati a fine prova (anche con «Interrompi»); se la pagina si chiude, ci pensa la manutenzione oraria.
- **Solo admin**. Il carico è reale: sulle risorse condivise usa durate brevi e fuori orario.
- Il test ha rivelato e fatto correggere un difetto reale: con molti contatti simultanei alcune richieste fallivano con «database is locked» (cursori di lettura rimasti aperti prima di una scrittura, transazioni non immediate). Ora le transazioni di scrittura partono con `BEGIN IMMEDIATE`; in prova locale 300 device a 15 s: 0 errori.

## 8.9 Scheduler dei runbook, attese e calendario (1.21.0)

- **Passo «attendi»**: nel costruttore di sequenze (scheda *Script e job* del device) accanto a «Aggiungi alla sequenza» c'è «Aggiungi attesa (min)». Dopo il passo precedente la sequenza aspetta quel tempo (da 1 minuto a 7 giorni) e riprende da sola al contatto successivo del device. Le attese si salvano nei runbook.
- **Runbook programmati** (*Runbook → Programma*): scegli cliente e/o filtro, la prima esecuzione (nel tuo fuso orario) e se ripetere ogni N ore, giorni o settimane (0 = una volta sola). Alla scadenza il runbook parte su ogni device del bersaglio; un device che ha già quel runbook in corso viene saltato. La prossima esecuzione è fissata prima dell'avvio, quindi niente doppioni. Si può sospendere, riattivare o eliminare.
- **Calendario**: la scheda «Programmazioni e calendario» in *Runbook* elenca le programmazioni (prossima e ultima esecuzione, quanti device) e gli script programmati sui device nei prossimi 7 giorni (i monitor sono esclusi).
- **Sequenza ferma**: se una sequenza non avanza da oltre 6 ore (device offline, job mai consegnato) parte una sola notifica sui canali configurati.
- Lo scheduler è mosso dai contatti degli agent (al massimo una volta al minuto): con la flotta spenta non parte nulla, e le esecuzioni mancate partono al primo contatto utile.

## 8.10 Scadenza dei job non consegnati (1.22.0)

Per impostazione predefinita un job resta in coda e parte appena il device torna raggiungibile (invariato). Se invece sai che quel lavoro ha senso solo entro un certo tempo (un correttivo su macchine spente per settimane, per esempio) puoi dargli una **scadenza**:

- Il menu «**scade se non consegnato in…**» (mai · 1 ora · 4 ore · 12 ore · 24 ore · 3 giorni · 7 giorni) è presente in: *Esegui script dalla libreria* e *Nuovo job* sul device, «Esegui sui selezionati» e «Esegui su più device», *Runbook → Avvia su…* e *Runbook → Programma*. Il valore predefinito è «mai».
- Il tempo parte dall'accodamento. Se in quel tempo il device non contatta il server, il job passa a **scaduto** e non viene più consegnato, nemmeno quando il device ritorna. Un job già consegnato (in esecuzione) non scade: la scadenza riguarda solo ciò che non è mai partito.
- **Sequenze e runbook**: la scadenza vale per ogni passo, contato da quando il passo viene accodato. Se un passo scade la sequenza si chiude e non parte il successivo. Nelle programmazioni ricorrenti ogni esecuzione ha la propria scadenza.
- La chiusura avviene al contatto del device (prima della consegna) e, per i device spenti, dallo scheduler (una volta al minuto, innescato dai contatti degli altri agent).
- Nella scheda del device il job in coda mostra «scade …» (ora UTC); a scadenza compare il pill «scaduto». In *Attività* c'è il filtro «Scaduti».

## 8.11 Ticket (1.23.0)

Menu **Ticket** (sotto *Alert*). I ticket vivono nell'RMM, collegati a un device e al suo cliente.

- **Dagli alert**: un alert che si apre crea un ticket sul device (priorità: crit → critica, warn → alta, info → bassa). Un solo ticket aperto per device e tipo di alert: se l'alert si riapre, il ticket esistente riceve una nota. Quando l'alert **rientra** il ticket si **chiude da solo**, con nota. In *Impostazioni e azioni automatiche* (admin) si può disattivare l'apertura automatica o alzare la gravità minima (predefinita: warn).
- **A mano**: «+ Nuovo ticket» (operatore): device, titolo, priorità.
- **Lavorazione**: stato (aperto · in lavorazione · in attesa · chiuso), priorità, assegnatario, note con tempo impiegato (sommato nel ticket) e cronologia completa. Elenco con filtri per testo, stato, priorità e assegnatario; il contatore nel menu conta i ticket non chiusi.
- **Azione sul device**: dal ticket scegli uno **script** o un **runbook** (un solo elenco), la scadenza opzionale di consegna (vedi 8.10) e lanci sul device del ticket. L'esito di ogni script e di ogni passo del runbook (exit, stdout, stderr; le password sono mascherate) torna come nota nel ticket; se l'azione scade senza essere consegnata il ticket lo annota.
- **Azioni automatiche** (admin): «quando un alert del tipo X apre un ticket, lancia lo script/runbook Y» (tipo «*» = tutti), con scadenza e **limite**: al massimo una volta ogni N ore per device e per regola, così un falso allarme ripetuto non rilancia l'azione di continuo (il ticket annota «non rilanciata»).
- I ticket compaiono nella ricerca globale. Eliminando un device se ne eliminano i ticket.

## 8.12 Documentazione (1.24.0)

Menu **Documenti**: procedure, note di rete, contatti e schede per cliente.

- **Documenti**: titolo, categoria (procedura, rete, server e servizi, applicazione, contatti e fornitori, nota, altro), cliente (o «generale»), device opzionale e testo in **Markdown semplice**: titoli `#`, elenchi `-` e `1.`, citazioni `>`, tabelle con `|`, riquadri di codice, `**grassetto**`, `` `codice` ``, collegamenti `[testo](https://…)` e collegamenti interni `[[ticket:12]]`, `[[device:5]]`, `[[doc:3]]`, `[[asset:7]]`. L'HTML scritto a mano non viene eseguito. Ricerca nel titolo e nel testo, filtri per categoria e cliente, «fissa in alto».
- **Versioni**: ogni modifica conserva la versione precedente (le ultime 20): si possono vedere e ripristinare.
- **Scheda cliente** (generata): riepilogo dei device per sistema operativo, tabella con CPU, RAM, IP, ultimo utente, ultimo contatto e versione dell'agent, asset del cliente (con scadenze), ticket aperti e documenti. **Scheda device** (generata, dal link «Scheda e documenti» nella testata del device): sistema, hardware, dischi, IP, conteggio software e servizi, asset collegati, ticket recenti e documenti. Si aggiornano da sole a ogni apertura.
- **Esporta Markdown** e **Stampa** per documenti e schede; nel ticket compare «Documentazione utile» (documenti del device e del cliente).
- **Credenziali**: non vanno nei documenti. Un testo che contiene «password: valore», token, chiavi o «secret» con un valore viene rifiutato; si scrive solo dove la credenziale si trova nel gestore di password (senza i due punti).
- **Permessi**: vede chi ha accesso al cliente; crea e modifica l'operatore; elimina l'admin. I documenti «generali» sono visibili a tutti.

## 8.13 Modelli, revisione periodica e import dei documenti (1.25.0)

- **Modelli**: in *Documenti → Nuovo da modello* scegli un modello e (se serve) il cliente: l'editor si apre già compilato. Di serie: scheda backup, procedura di ripristino, rete e VLAN, firewall e VPN, scheda server, contatti e fornitori, nuovo utente o uscita, manutenzione mensile, incidente e post-mortem. I segnaposto `{{CLIENTE}}`, `{{DEVICE}}`, `{{DATA}}`, `{{AUTORE}}`, `{{SISTEMA}}`, `{{IP}}` si riempiono da soli. In *Gestione dei modelli* (admin) si modificano i modelli, se ne creano di propri, si ripristina il testo di serie e da qualunque documento si usa «Salva come modello». I modelli di serie si aggiornano con le nuove versioni finché non vengono modificati.
- **Revisione periodica**: ogni documento può avere «da rivedere ogni 3/6/12/24 mesi» (i modelli la preimpostano). Passata la scadenza (dall'ultima modifica o dall'ultima revisione) il documento mostra «da rivedere»: filtro e contatore in *Documenti*, avviso nella pagina e pulsante «Segna come rivisto».
- **Importa** (*Documenti → Importa*, operatore): carichi file e vedi un'**anteprima** prima che venga scritto qualcosa, dove puoi togliere documenti, correggere titolo, categoria e cliente e scegliere cosa fare se il titolo esiste già (salta, aggiorna conservando la versione precedente, crea una copia).
  - **Markdown, testo e HTML** (.md, .txt, .html; più file insieme): il titolo viene dalla prima riga `#` (o dal front-matter, o dal nome del file); l'HTML è convertito in Markdown semplice e le immagini incorporate sono scartate e segnalate.
  - **ZIP**: la prima cartella è il cliente (se esiste), quella dopo la categoria; i file nascosti e `__MACOSX` sono ignorati.
  - **CSV** (separatore ; , o tab): mappatura guidata di titolo, categoria, cliente e colonne del testo; le colonne che sembrano credenziali (password, token, chiave, PIN…) sono escluse.
  - Limiti: 500 documenti per import, 200 KB per file, 8 MB in totale. I documenti che sembrano contenere credenziali sono saltati. A fine import il pulsante **Annulla questo import** elimina i documenti creati e ripristina quelli aggiornati.
  - Non sono importabili direttamente Word, PDF e le API di altri sistemi: esporta in Markdown o CSV.

## 8.15 Editor dei documenti: Markdown o visuale (1.26.3)

- Sopra il testo scegli **Markdown** (testo semplice, come prima) oppure **Visuale (barra strumenti)**: nel secondo si vede già il documento formattato e la barra offre titoli (T1-T3), grassetto, corsivo, codice, elenchi puntati e numerati, lista di controllo ☐, citazione, riquadro di codice, link web, collegamento a ticket/device/documento/asset, tabella (+ riga, + colonna), linea di separazione, annulla e ripeti. Si può passare da una modalità all'altra in qualsiasi momento: il testo resta Markdown e viene salvato sempre come Markdown (così versioni, esporta e importa funzionano come prima). La modalità scelta viene ricordata nel browser.
- Il Markdown ora comprende anche il *corsivo* (`*testo*` o `_testo_`), la linea `---` e le liste di controllo `- [ ]` / `- [x]`.
- In modalità visuale il testo incollato è sempre testo semplice (niente HTML da Word o dal web). Caratteri come `*` o `[[` scritti a mano nel testo possono essere letti come Markdown al passaggio di modalità.
- **Cliente e device**: scelto un cliente, il menu device mostra solo i suoi device; scegliendo un device si imposta il suo cliente; il server rifiuta un device che non appartiene al cliente indicato.

## 8.16 Ricerca nei menu e nelle tabelle (1.26.3)

I menu a selezione con molte voci (da 10 in su), anche quelli a gruppi come le azioni script/runbook dei ticket, hanno il campo Cerca con elenco filtrato e jolly `%` (§4). Le tabelle con 15 o più righe hanno il campo **Filtra le righe** (solo le righe della pagina; le ricerche lato server, come quella dei ticket, accettano già `%`).

## 8.19 Risolutivi legati all'alert (1.27.0)

Il risolutivo (script o runbook) appartiene al **tipo di alert**, non al ticket: parte anche se i ticket automatici sono spenti, e il ticket (se c'è) ne riceve le note. Si configura in *Ticket → Impostazioni e azioni automatiche*.

| Modo | Cosa succede |
|---|---|
| automatico | parte appena l'alert si apre, al massimo una volta ogni N ore per device e regola |
| proposto (un clic) | il ticket riceve la nota «Risolutivo disponibile»; il pulsante *Lancia* compare su ticket e alert |
| solo manuale | solo il pulsante *Lancia*, senza avvisi |

Ogni regola può essere limitata a un **cliente** (vuoto = tutti) e ha un tempo di **verifica** (default 15 min). Dopo il lancio: se l'alert rientra il lancio risulta **risolto** e il ticket si chiude come sempre; se alla scadenza l'alert è ancora aperto il lancio risulta **senza effetto**, il ticket sale di priorità e una nota lo dice; se lo script esce con errore risulta **fallito**. La tabella delle regole mostra per ciascuna quanti lanci, quanti risolti (%), falliti e senza effetto.

Un ticket aperto da una persona su un device mostra i risolutivi degli alert aperti su quel device. Pagine: *Ticket → ticket* e *Alert* (card «Risolutivi disponibili»). Azione registrata nel registro audit (`remed_run`).

## 8.18 Selettore cliente nella barra alta e avviso sui documenti (1.26.5)

Il selettore del cliente a destra nella barra alta è ora un pulsante con ricerca: clic, scrivi parte del nome (`%` = jolly, es. `%acme%srl`), frecce su/giù, **Invio** sceglie, **Esc** chiude. «Tutti i clienti» è sempre in elenco. Senza JavaScript resta il menu classico.

Quando sposti un device in un altro cliente, se è citato (`[[device:N]]`) in documenti di altri clienti, il messaggio dopo lo spostamento li elenca: i riferimenti restano validi, ma conviene verificare che il contenuto sia ancora pertinente.

## 8.20 Codice ticket, richieste dal tray, note pubbliche (1.28.0)

Ogni ticket ha un **codice** `T-AAAA-NNNN` (progressivo per anno, mai riutilizzato; ai ticket esistenti è stato assegnato in ordine di creazione) e un **canale di origine**: alert, manuale, tray (e, dalla 1.29.0, email). Il codice compare in elenco, nella scheda e nelle risposte; la ricerca lo trova.

**Richiesta dal tray.** Nella finestra della chat (tray) l'utente spunta «Apri una richiesta di assistenza (ticket)», scrive oggetto e messaggio: il server crea il ticket (canale tray, cliente e device del PC, richiedente = utente collegato), risponde nella chat con il codice e lega la chat al ticket. Da quel momento i messaggi dell'utente diventano **note pubbliche** del ticket, e viceversa. Invio ripetuto dello stesso messaggio = un solo ticket. Una notifica di nuova richiesta parte sui canali di notifica configurati.

**Note interne e pubbliche.** Nei ticket nati dal tray la nota ha un menu: *nota interna* (solo operatori) o *risposta al richiedente* (arriva nella chat del PC come `[T-AAAA-NNNN] testo`). Chiudere il ticket avvisa l'utente e scollega la chat; archiviare la chat scollega il ticket.

## 8.21 Richieste via email e triage (1.29.0)

Una casella dedicata (es. `assistenza@tuodominio.it`) diventa un canale di ingresso dei ticket. Configurazione in *Ticket → Posta: richieste via email* (solo admin): server IMAP, porta, sicurezza, utente, password, cartella, ogni quanti minuti controllare. «Prova la connessione» verifica accesso e cartella; «Controlla ora» esegue subito un giro. I valori stanno in `config.php` (`IMAP_*`, `MAIL_INTAKE`, `MAIL_ACK`, `MAIL_POLL_MIN`). La lettura usa un client IMAP incorporato (nessuna estensione PHP necessaria) ed è innescata dai contatti degli agent, al massimo una volta ogni N minuti. Alla prima attivazione si leggono i messaggi **non letti degli ultimi 3 giorni**, poi solo i nuovi; i messaggi elaborati vengono segnati come letti. Per rispondere ai richiedenti serve l'SMTP configurato in Sistema → Notifiche (il mittente dovrebbe essere la stessa casella).

**Clienti, domini e caselle.** Nella stessa scheda registri per ogni cliente uno o più *domini* (`tossinimobili.it`: vale per tutto il dominio) e *indirizzi* (`tossini@gmail.com`). L'indirizzo esatto prevale sul dominio. Lo stesso indirizzo può stare in più clienti.

**Cosa succede a un messaggio:**
| Caso | Esito |
|---|---|
| Risposta automatica, bounce, newsletter (`Auto-Submitted`, `Precedence`, `List-Id`, `postmaster@`, `noreply@`…), mittente bloccato, stesso `Message-ID` già visto | ignorato |
| Codice `T-AAAA-NNNN` nell'oggetto, oppure `In-Reply-To`/`References` di una nostra email | nota pubblica nel ticket (senza il testo citato); se era chiuso si **riapre**; se il mittente è diverso dal richiedente la nota lo segnala |
| Mittente con **un solo** cliente corrispondente e autenticazione non fallita | **ticket automatico** (canale email, senza device) + conferma di ricezione col codice (max 3 all'ora per mittente) |
| Nessun cliente, **più clienti**, oppure SPF/DKIM/DMARC falliti | **Email da smistare** |

**Triage.** In cima all'elenco ticket la card «Email da smistare» mostra oggetto, mittente e, aprendo la riga, il **testo completo**. Se il mittente è registrato in più clienti compaiono tanti pulsanti «Assegna a …» quanti sono i candidati (un clic); altrimenti scegli il cliente dal menu. «Ricorda questo mittente» registra l'indirizzo per quel cliente (i messaggi successivi andranno da soli). «Ignora» scarta; «Spam» scarta e blocca il mittente (sbloccabile dalla scheda Posta). Chi ha l'accesso limitato ad alcuni clienti non vede il triage.

**Ticket senza device.** I ticket da email nascono senza device: dalla scheda puoi collegarne uno del cliente (abilita script, runbook e risolutivi). Le note pubbliche sono inviate al richiedente per email (oggetto `Re: … [T-AAAA-NNNN]`, con `In-Reply-To`); le note interne no. Chiudere il ticket avvisa il richiedente. Gli allegati non vengono salvati: nel ticket ne compare l'elenco.

## 8.17 Cosa succede se sposti un device in un altro cliente (1.26.4)

| Elemento | Dopo lo spostamento |
|---|---|
| Regole, pacchetti, filtri, finestre di manutenzione, runbook programmati per cliente | si rivalutano subito sul nuovo cliente (le programmazioni dei pacchetti del vecchio cliente vengono tolte, quelle del nuovo create) |
| **Alert** aperti dei monitor che non si applicano più | chiusi (e con loro i ticket collegati, se automatici); gli altri alert restano aperti sul device |
| **Ticket** del device (anche chiusi) | passano al nuovo cliente |
| **Documenti** collegati al device | passano al nuovo cliente (i documenti generali e quelli del vecchio cliente non collegati al device restano dov'erano) |
| **Asset** collegati al device | passano al nuovo cliente; il reparto resta solo se esiste anche lì |
| Reparto del device | resta solo se esiste nel nuovo cliente, altrimenti è tolto |
| Cronologia di job, risultati, metriche, chat, audit | restano sul device, non cambiano |
| Utenti limitati a un cliente | vedono il device e ciò che lo riguarda solo se hanno il nuovo cliente |

L'audit registra lo spostamento con il numero di ticket, documenti e asset seguiti. Nei form di documento e asset, scelto un cliente il menu device mostra solo i suoi device; scegliendo un device si imposta il suo cliente, e il server rifiuta combinazioni incoerenti. Gli alert di monitor rimasti orfani (programmazione eliminata) vengono chiusi anche dalla pulizia oraria.

## 8.14 Documentazione in un database separato (1.26.0)

- I dati della documentazione vivono in `docs.sqlite` (collegato alla stessa connessione): il database principale resta più piccolo e le scritture dei documenti non lo ingrossano. Niente da configurare.
- **Migrazione automatica e sicura** al primo avvio dopo l'aggiornamento: le tabelle `docs`, `doc_rev`, `doc_templates` e `doc_import` vengono copiate in `docs.sqlite` in una transazione, si **verificano i conteggi** e solo dopo si tolgono dal principale; se qualcosa non torna non si cancella nulla (resta tutto dov'era e l'errore va nel log PHP). Se `docs.sqlite` ha già dati propri e nel principale ne compaiono di vecchi (ripristino di un backup datato), non si mescola: le tabelle vecchie sono rinominate `legacy_*`.
- Backup e ripristino: vedi §13 — **una copia a mano del solo `myrmm.sqlite` non contiene più i documenti**. La prova di carico ora scrive anche documenti e versioni in parallelo agli heartbeat e naviga documentazione e ticket.

## 8.22 Modalità demo (1.30.0)

Un database **fittizio** per mostrare o provare myrmm senza toccare i dati veri. *Profilo → Modalità demo* (solo admin): **Entra in modalità demo**.

- **Solo per la tua sessione.** Il flag vive nella riga di sessione; gli altri utenti, anche admin, non vedono nulla di diverso. Una barra arancione in cima («DEMO — dati fittizi») ricorda dove sei e permette di **Esci dalla demo** o **Rigenera**.
- **Dati condivisi tra gli admin** nella cartella `demo/` accanto al database (`demo/myrmm.sqlite`, `demo/docs.sqlite`, `demo/metrics.sqlite`, più asset, trasferimenti e backup demo). Alla prima attivazione si crea e si popola (circa un secondo); chi entra dopo trova la stessa demo, che **non viene mai sovrascritta**. All'attivazione la tua riga utente e la tua sessione vengono copiate nel database demo: i dati veri non cambiano.
- **Contenuto.** Dieci clienti con domini di posta, circa 70 device (Windows, Linux, macOS) con inventario e una settimana di metriche, alcuni spenti e uno in manutenzione; alert aperti e storici; ticket di ogni canale (alert, manuale, tray con chat, email); runbook, programmazioni, job scaduti; risolutivi con la loro statistica; documenti con revisioni e date di verifica; asset e scadenze; email da smistare. Ogni funzione nuova ha i suoi dati d'esempio.
- **La demo vive.** A ogni caricamento della console i device fittizi risultano online (tranne quelli «spenti»), i job vengono chiusi in simulazione dopo pochi secondi (l'esito è marcato `[demo]`; un risolutivo lanciato da un alert lo fa rientrare), le metriche proseguono e le programmazioni girano.
- **Isolamento.** Gli agent e l'API non hanno cookie di sessione e vanno sempre ai dati veri; la demo non scrive mai sul database vero, non invia email o notifiche (SMTP, IMAP, webhook, Telegram, Teams sono bloccati) e rifiuta le azioni che toccano l'installazione: configurazione, notifiche, conservazione, backup e ripristino, prova di carico, password e 2FA personali.
- **Rigenera** ricrea la demo da zero (avvisa se altre sessioni sono in demo); **Elimina dati demo** cancella la cartella `demo/` e riporta tutti sui dati veri. Dopo il logout la sessione successiva è sui dati veri.
- La cartella `demo/` ha un `.htaccess` che nega l'accesso web, come la cartella dei backup.

Nota 1.30.1: sugli schermi stretti le tabelle scorrono in orizzontale dentro la pagina; gli asset si creano dal pulsante **+ Nuovo asset** (Asset) o da **+ Asset per questo device** (scheda device, sezione dati).

## 8.23 Job: selezione multipla e interruzione senza ricaricare; ultimi device (1.31.0)

- **Interrompere più job in una volta.** Nell'elenco *Job recenti* di un device e in *Attività* i job in coda o in corso hanno una casella. **In corso** seleziona tutti quelli attivi visibili, **Nessuno** deseleziona, **Maiusc+clic** seleziona un intervallo di righe. **Interrompi selezionati** annulla i job in coda e chiede all'agent di terminare quelli già inviati; **Forza chiusura** chiude lato server quelli rimasti in «interruzione…» senza attendere l'agent. In *Attività* la selezione vale anche tra device e clienti diversi (filtra prima con *In coda o in corso* e la ricerca).
- **Niente più ricarica.** Annullare, interrompere, forzare o eliminare un job dallo storico aggiorna la riga sul posto e mostra un avviso in basso: la posizione di scorrimento e le righe aperte restano dove sono. Le sequenze legate a un job annullato si fermano come prima.
- **Ultimi device aperti.** L'icona dell'orologio nella barra alta elenca gli ultimi 12 device di cui hai aperto la scheda (il più recente in alto, pallino verde se online). L'elenco è per utente e rispetta i clienti che puoi vedere; riaprire un device lo riporta in cima senza duplicarlo. Si chiude cliccando fuori.
- Righe dei job: colonne riallineate (prima la data andava a capo).

## 8.24 Rete: sonde, sottoreti e apparati monitorati (1.32.0)

Una **sonda** è un normale agent (Windows, Linux o macOS) che sta nella LAN del cliente e controlla dall'interno gli apparati che non possono avere un agent: stampanti, switch, firewall, access point, UPS, NAS. Il menu **Rete** ha le schede *Apparati · Scoperti · Distribuzione · Mappa · Sottoreti · Sonde*.

1. **Sonde** — su un device con agent (versione ≥ 1.32.0) premi *Promuovi a sonda*. Da quel momento l'agent riceve con l'heartbeat l'elenco dei controlli e invia gli esiti in un solo invio per ciclo. Nessuna porta in ingresso, nessun servizio in più.
2. **Sottoreti** — per ogni cliente aggiungi le sue reti (`192.168.1.0/24`, anche più reti o VLAN) e assegna **una o più sonde**: lavora la prima online per priorità, le altre sono **di riserva** (dopo `NET_PROBE_STALE` secondi senza contatto la rete passa alla riserva; con tutte le sonde offline gli apparati risultano «sconosciuti», non «giù»).
3. **Apparati** — *Aggiungi apparato*: cliente, nome, IP (deve cadere in una sottorete del cliente), controllo **Ping**, **Porta TCP** o **SNMP**, intervallo (≥ 15 s) e gravità. Un apparato è «non risponde» dopo `NET_FAILS` controlli consecutivi falliti: si apre un avviso sulla sonda che lavora e si chiude da solo al rientro. Il tempo di risposta finisce nei grafici (Metriche). Un apparato può essere collegato a un **asset**: la scheda dell'asset mostra lo stato e un pulsante *Monitora*.

Le impostazioni (soglie e tempi) sono in **Impostazioni › Rete e sonde**.

## 8.25 Tunnel verso gli apparati attraverso la sonda (1.33.0)

Dalla scheda di un apparato o di un asset (*Console di …via sonda*) l'operatore apre un **tunnel RDP/SSH/web** verso un apparato della LAN del cliente passando dalla sua sonda: come i tunnel del §8.4, ma l'ultimo tratto parte dalla sonda invece che da un PC.

- Servono `TUNNEL_MODE = on` e `job_signing_key` (la sonda apre solo tunnel firmati).
- Le porte consentite sono `TUNNEL_NET_PORTS` (default 22, 80, 443, 3389, 5900, 8080, 8443); la sonda ha una sua lista (`net_tunnel_ports` in `config.json`) e rifiuta il resto. **Telnet (23) è escluso di proposito.**
- Ogni apertura, collegamento e chiusura è nel registro di audit.

## 8.26 SNMP: stampanti, switch, firewall (1.34.0)

Il controllo **SNMP** legge l'apparato con **SNMP v2c o v3** (authNoPriv / authPriv con MD5, SHA, SHA-256/512 e DES, AES-128/192/256). Le **credenziali sono per sottorete** (*Rete › Sottoreti › SNMP*), cifrate nel database (AES-256-GCM) e inviate in chiaro solo alla sonda autenticata, nel canale TLS dell'agent: la console non le mostra mai.

- **Riconoscimento automatico** del profilo dai MIB presenti: stampante, switch, firewall/router, UPS, NAS, access point, generico. Si può forzare dalla scheda dell'apparato.
- **Stampante**: toner e materiali (con soglia `NET_SUPPLY_WARN`), contatore pagine, matricola, avvisi critici dell'apparato. **Switch**: porte fisiche attive/totali, errori. **Firewall/router**: interfacce, CPU, memoria, disco (soglie `NET_CPU_WARN`, `NET_MEM_WARN`, `NET_DISK_WARN`).
- **Porte osservate**: spunta le porte importanti (uplink, server): lo stato è controllato ogni N secondi (controllo veloce) e se cadono si apre un avviso.
- **Scansiona apparato**: la sonda legge tutto ciò che l'apparato espone (MIB standard e del produttore, fino a ~4000 voci, compressi nel database); dall'elenco, con ricerca, scegli un valore e lo segui come **OID personalizzato** (nome e unità) con grafico — senza conoscere gli OID a memoria.
- La scheda dell'apparato (*Rete › Apparati › nome*) mostra misure, interfacce, materiali, dischi, OID personalizzati, grafici e la scansione. Se la community è sbagliata l'apparato risulta giù con il **motivo** (timeout, autenticazione rifiutata…).

## 8.27 Scoperta della rete (1.35.0)

Ogni sonda **scansiona le sue reti** e la scheda **Rete › Scoperti** elenca tutto ciò che risponde, come fanno gli scanner di rete: ping sweep, tabella ARP (anche chi non risponde al ping), porte standard, banner e titolo della pagina web, nome DNS inverso, MAC e **costruttore** (tabella OUI inclusa nell'agent), identificazione SNMP quando la rete ha le credenziali, **tipo probabile** (stampante, switch, PC Windows, telecamera…).

- **Intervallo per sonda**: *Rete › Sonde › Scoperta della rete* — ogni N minuti (0 = solo su richiesta, massimo 1440) e **porte da cercare** (default: 21, 22, 23, 25, 53, 80, 110, 135, 139, 161, 389, 443, 445, 515, 631, 993, 1433, 3306, 3389, 5900, 8080, 8443, 9100). *Scansiona ora* sulla sottorete avvia subito una scansione.
- Reti fino a /20 (4096 indirizzi); oltre, la scansione è parziale e lo dice.
- **Nuovi / censiti / ignorati / spenti**: chi non è mai stato censito è «nuovo» (contatore sulla scheda e, con `NET_FOUND_ALERT = on`, avviso informativo se compare qualcuno in una rete già scansionata). Chi non si vede più in una scansione completa diventa «spento» (sparisce dopo `NET_FOUND_KEEP_DAYS`).
- **Censisci con un clic**: crea l'**asset** (IP, MAC, modello già compilati; collega quello esistente se IP o MAC coincidono) e, volendo, mette l'apparato **sotto monitoraggio** (ping, o SNMP se la rete ha le credenziali).

## 8.28 Installare l'agent dalla sonda (1.36.0)

Dalla lista **Scoperti** seleziona i PC e premi **Installa agent…** (solo amministratori): la scheda **Distribuzione** guida un lotto per cliente.

**Come funziona**
- **Windows**: solo da una **sonda Windows**, con account amministratore del PC: condivisione amministrativa (SMB) e WMI/DCOM, con PowerShell. Servono le regole del firewall di Windows «Condivisione file e stampanti» e «Strumentazione gestione Windows (WMI)»; per gli account **locali** (non di dominio) serve `LocalAccountTokenFilterPolicy = 1` sul PC.
- **Linux/macOS**: da qualunque sonda via **SSH** (password, tastiera interattiva o chiave; `sudo` se l'utente non è root). L'impronta della chiave host è riportata nell'esito.
- L'installazione riusa gli stessi script del §3 (scaricano il binario dal server con il token del cliente e ne verificano lo SHA-256); la sonda li esegue sul PC e controlla che il servizio sia attivo e arruolato.

**Sicurezza delle credenziali**
- Le credenziali si inseriscono **per lotto** e **non vengono salvate**: il server le **cifra con la chiave pubblica della sonda** (libsodium *sealed box*; la chiave privata sta solo sulla sonda, in `probe.key`) e solo la sonda può leggerle. Dopo l'installazione, o un errore, il testo cifrato viene cancellato; in ogni caso dopo 24 ore.
- Con `NET_DEPLOY_STORE = on` (default **off**) compare l'opzione *conserva cifrate per questo cliente* (AES-256-GCM, come le credenziali SNMP); si cancellano dalla scheda.
- Le password non compaiono mai nel registro di audit né negli esiti (sono mascherate).

**Prima la prova a vuoto.** Il primo passo è sempre **Prova a vuoto**: la sonda controlla, senza modificare nulla, accesso e privilegi, sistema e architettura, spazio libero, `curl`/`wget` (Linux), servizio già presente e — importante — **se il PC raggiunge il server**. Solo i PC con prova riuscita nelle ultime 24 ore hanno il pulsante **Installa l'agent sui PC selezionati**; chi ha già l'agent risulta «già installato». Le richieste non prese in carico dalla sonda scadono dopo 10 minuti.

Richiede una sonda con agent ≥ 1.36.0 (si aggiorna da sola).

## 8.29 UPS, NAS, access point, vicini LLDP/CDP e mappa di rete (1.37.0)

- **UPS** (UPS-MIB, RFC 1628): carica della batteria, autonomia residua, tensione e temperatura, carico, alimentazione in uscita. Avvisi: **a batteria** (critico: manca la rete elettrica), **batteria bassa/scarica** (critico), carica sotto `NET_UPS_BATT_WARN` (default 30%).
- **NAS** (Synology: MIB del produttore; QNAP e altri: CPU/memoria/volumi da hrStorage): stato di sistema, temperatura, **dischi anomali** e **volumi RAID degradati** con nome (avvisi critici), disco più caldo con soglia `NET_NAS_TEMP_WARN` (default 55 °C).
- **Access point** (UniFi, MikroTik): client Wi-Fi collegati e, per UniFi, reti con canale e client per rete.
- **Vicini LLDP e CDP** letti da switch, firewall e access point: la scheda dell'apparato elenca *porta locale → vicino → porta del vicino* (con MAC/IP e descrizione).
- **Mappa** (*Rete › Mappa*, per cliente): disegno della rete a livelli — Internet, firewall, switch, poi AP, UPS, NAS, PC e il resto — e **Scarica SVG**. Le linee **piene** sono collegamenti *confermati* da LLDP/CDP; le **tratteggiate** sono *ipotetiche*: ciò che non ha un vicino noto è appeso allo switch (o al firewall) della sua sottorete IP. Un vicino che non è tra gli apparati noti compare come nodo «esterno». Ogni nodo è un link alla sua scheda. La mappa è un'ipotesi: più apparati annunciano LLDP/CDP, più è precisa.
- La **modalità demo** (§8.22) include ora una rete d'esempio (albergo: firewall, due switch, due access point, UPS, NAS, stampante, telecamere e PC scoperti) per provare mappa, schede e Scoperti.

## 8.30 Console riorganizzata: regole comuni a tutte le pagine (1.38.0)

Le regole complete (e i criteri di usabilità da cui derivano) sono in `UI-LINEE-GUIDA.md`; `ci/layout_test.py` le verifica.

- **«+ Aggiungi»** sta sempre nella barra alta, a destra; il tasto `n` apre la voce della pagina corrente. Contiene: cliente, device, ticket, asset, documento, rete e sonda, script, utente, importa da CSV.
- **Elenchi** (≥ 8 righe): in alto la ricerca (`%` = jolly, ricordata per pagina e utente) con il contatore; selezionando delle righe la stessa barra diventa la **barra di selezione** («N selezionati su M», Seleziona tutti, Deseleziona); intestazione e barra restano fisse scorrendo; **densità** compatta/standard/ampia ricordata.
- **Anteprima laterale**: clic su una riga (o `Invio`) apre la scheda in un pannello a destra senza lasciare l'elenco; `Maiusc+Invio` apre la pagina intera; `Esc` chiude.
- **Scorciatoie** (`?` le elenca): `/` cerca nell'elenco, `Ctrl K` cerca ovunque, `n` aggiungi, `j`/`k` riga seguente/precedente, `x` seleziona, `Invio`, `Esc`. Non agiscono mai mentre si scrive in un campo; si disattivano dal pannello `?`.
- Il **vocabolario** è unico: Cliente › Sede › Reparto, Device (agent), Apparato (rete), Asset.
- **Menu a tendina lunghi** (10 voci o più): un solo componente, un pulsante che apre un pannello con ricerca (`%` = jolly), gruppi e tastiera (frecce, Invio, Esc). Sostituisce i campi «Cerca» sparsi accanto ai menu.
- **Tabelle**: l'intestazione resta visibile scorrendo (nella pagina o, per tabelle larghe come l'elenco Device, nel riquadro stesso). Una sola ricerca per elenco: nell'elenco Device è il campo in alto, con jolly.
- **Elenco dei job**: ogni riga mostra il **nome dell'attività** (pianificazione, monitor o script di libreria) con la sua descrizione; il testo completo e la prima riga dello script compaiono al passaggio del mouse e nel dettaglio. L'origine dice «ogni N min» invece dell'identificativo interno. Solo i job lanciati a mano mostrano la prima riga del codice.
- **Telefono**: le barre strumenti lunghe si riducono alla ricerca più il pulsante «Filtri e azioni»; le colonne secondarie (es. in Clienti) si nascondono; le tabelle con molte colonne scorrono di lato invece di schiacciarsi; i passi dell'onboarding mettono i pulsanti sotto al testo.

## 8.31 Da fare

*Da fare* raccoglie in un unico elenco, dal più urgente: alert aperti, device non visti da più di 3 giorni, apparati scoperti da censire, scadenze (scadute prima), ticket aperti e passi di onboarding ancora aperti. Ogni riga porta alla pagina giusta.

## 8.32 Credenziali del cliente (SNMP, Windows, SSH)

*Rete › Credenziali* (admin): **quante se ne vogliono** per cliente, cifrate (stessa chiave degli asset). Ogni rete indica quali sono valide (nessuna spunta = tutte); ogni apparato può restringere ulteriormente la scelta, anche più credenziali insieme. La sonda riceve la prima più le alternative, le prova una dopo l'altra, **ricorda quella che funziona** per l'apparato e la segnala al server (`cred_id`), che la prova per prima la volta dopo. La credenziale «Propria della rete» delle versioni precedenti continua a funzionare e può essere **adottata** tra quelle del cliente con un clic. La sonda deve essere alla 1.38.0 per provare più credenziali; con una sonda più vecchia viene usata solo la prima.

## 8.33 Onboarding di un cliente

*Clienti › Nuovo cliente* apre l'onboarding: **nove passi fissi, in qualsiasi ordine, nessuno bloccante** — Anagrafica, Sedi e reparti, Credenziali, Rete e sonda, Device, Asset, Documenti, Monitoraggio e regole, Revisione e attivazione. Un passo risulta «fatto» da solo quando i dati ci sono (es. anagrafica compilata, almeno un device) oppure si segna a mano. Il cliente resta «in corso» (e compare in *Da fare*) finché non si preme **Attiva**. I clienti creati dall'importazione partono già in onboarding.

## 8.34 Procedura guidata della rete e aggiunta di un device

- **Rete › Procedura guidata** (`?view=netwiz`): cinque passi — rete e sonda (la sonda si collega alla rete in un colpo), credenziali, scoperta, classificazione, installazione dell'agent.
- **Aggiungi device** (`?view=newdevice`): per il cliente scelto mostra il comando di installazione già pronto (Windows, Linux, macOS) con token del cliente e attende il primo contatto (*In attesa del primo device*).

## 8.35 Importazione da CSV

*Importa da CSV* (operatore): asset, documenti o clienti. Le colonne si abbinano da sole per nome (modificabili); la **prova a vuoto** è attiva di default, non salva nulla e segnala le righe buone e quelle da correggere con numero di riga e motivo; togliendo la spunta si importa davvero. Separatore `;` o `,` (riconosciuto da solo), fino a 2000 righe.

## 8.36 Modelli di documento, cestino, rinomina

- **Modelli** (*Documenti*): 15 modelli di serie, tra cui Scheda cliente, Inventario di rete, Procedura di emergenza, Piano di backup, Contratto di assistenza, Accessi VPN; i segnaposto `{{CLIENTE}}`, `{{DATA}}`, `{{AUTORE}}`, `{{REFERENTE}}`, `{{RETI}}`, `{{ELENCO_DEVICE}}`… si riempiono con i dati veri. I modelli di serie non modificati seguono gli aggiornamenti; quelli modificati no.
- **Cestino** (*Piattaforma › Cestino*): documenti, asset (con note e allegati) e ticket eliminati restano 30 giorni; compare **Annulla** subito dopo l'eliminazione, oppure si ripristinano dalla pagina.
- **Eliminare un cliente** richiede di digitarne il nome. **Rinominare** un cliente aggiorna device, asset, documenti, reti, credenziali, ticket e onboarding.

## 8.37 Comandi manuali e interprete (1.38.1)

Nella pagina di un device, *Esegui un comando* si adatta al sistema: su **Windows** offre **PowerShell** (predefinito) o **cmd** (prompt dei comandi); su **Linux e macOS** dice «shell» perché il testo gira con `bash` (o `sh`), oppure con l'interprete indicato da una prima riga `#!/usr/bin/env python3`.

**cmd** non richiede un agent nuovo: il testo è salvato con la prima riga `#!cmd` (che l'elenco non mostra) e, quando viene consegnato a un device Windows, il server lo incapsula in un breve script PowerShell che scrive un `.cmd` temporaneo (codepage OEM), lo esegue con `cmd.exe /d /c`, restituisce uscita e codice di uscita (`exit /b N`) e cancella il file. La firma del job copre lo script incapsulato.

Anche gli script di libreria hanno il selettore (*PowerShell* / *cmd*, solo per quelli Windows); l'etichetta accanto al nome dice il tipo: «Windows · PowerShell», «Windows · cmd», «Linux/macOS · shell». Un testo `#!cmd` consegnato a un device non Windows non viene incapsulato: usa lo script giusto per il sistema.

## 8.38 Nome del device, alias, runbook e filtro clienti (1.38.2)

- **PC rinominato.** A ogni contatto l'agent riporta l'hostname: se è cambiato (`Rename-Computer`, `hostnamectl`… dopo il riavvio richiesto dal sistema), il nome nel portale lo segue. Il vecchio nome resta tra i «nomi precedenti» (compare come *ex …* accanto al nome, ed è trovato dalla ricerca) e nel registro delle azioni (`device_renamed`).
- **Alias.** Accanto al nome nella pagina del device, *✎ alias* apre un campo (operatori): un nome di comodo, come «Cassa reception», che non sostituisce l'hostname. Compare nell'elenco Device e nella pagina; filtro dell'elenco e ricerca globale lo cercano.
- **Runbook.** La pagina *Runbook* ha l'editor: *+ Nuovo runbook* e *Modifica* (nome, descrizione, «fermati al primo errore», passi: script con le sue variabili oppure attese; si riordinano con ↑↓ e si tolgono con ✕), *Duplica* ed *Elimina*. Resta possibile salvarli dalla scheda *Script e job* di un device.
- **Filtro clienti a scelta multipla.** Il pulsante in alto apre l'elenco con caselle (e ricerca): uno o più clienti, oppure «Tutti»; riassume «Cliente X», «3 clienti» o «Tutti i clienti», e la scelta si ricorda per 90 giorni. Dashboard, device, alert, job, asset… mostrano solo i clienti scelti; gli operatori con accesso limitato vedono comunque solo i propri.
- **Avviso di incoerenza.** Se apri la scheda di un device (o un asset, il task manager, i servizi, i file) di un cliente **fuori dal filtro** — dagli *ultimi device*, dalla ricerca, da un link, oppure cambiando filtro mentre la scheda è aperta — compare una barra in alto: *Attenzione: stai guardando il device X del cliente Y, ma il filtro è su Z*, con *Passa a Y*, *Tutti i clienti* e *Ignora*. Negli *ultimi device* quelli fuori filtro hanno l'etichetta «fuori filtro». Non blocca nulla: segnala dove sei, per non lanciare comandi sul PC sbagliato.

## 8.39 Collegamenti multipli e allegati (1.39.0)

Un apparato può servire più device, una procedura può valere per più clienti: i collegamenti non sono più uno a uno.

- **Apparato → device.** Nella scheda apparato, accanto a *Device collegato* (il principale) c'è *Altri device collegati*: scegli dall'elenco (con ricerca) e compare un'etichetta per ciascuno; la ✕ sull'etichetta toglie il collegamento. I device devono essere dello stesso cliente dell'apparato. Nella scheda di **ognuno** dei device, sezione *Cliente e dati › Asset collegati*, l'apparato compare. Se un device cambia cliente, l'apparato (che è di un cliente solo) perde quel collegamento; se un device viene eliminato, i suoi collegamenti spariscono.
- **Documento → clienti, device, apparati.** Nell'editor, sotto cliente e device principali, il blocco *Collega anche a* ha tre selettori: *Altri clienti*, *Altri device*, *Apparati*. Scegliere un device o un apparato aggiunge da solo anche il suo cliente. Il documento compare nell'elenco di ciascun cliente (filtro *ogni cliente* incluso), nella scheda di ciascun device (*Documenti collegati*) e di ciascun apparato; nell'elenco documenti le colonne Cliente e Device mostrano «+N» per i collegamenti in più. Chi ha un perimetro ristretto vede il documento se **almeno uno** dei clienti collegati è nel suo perimetro, e modificandolo non perde i collegamenti ad altri clienti che non vede. Da una scheda apparato o device, *+ Documento per questo apparato/device* apre l'editor già collegato.
- **Allegati** su documenti, device (scheda *Cliente e dati*) e apparati: PDF, DOCX, TXT, configurazioni (cfg, conf, rsc…), immagini, archivi, qualunque tipo. Si caricano più file in una volta; il limite per invio è quello del file manager (`FS_MAX_MB`, e comunque non oltre `upload_max_filesize` / `post_max_size` dell'hosting: il browser avvisa prima di inviare). Fino a 100 allegati per elemento. I file stanno nella cartella `assets/` accanto al database, con nome casuale e `.htaccess` che nega l'accesso diretto: si scaricano solo da qui, con login e nel perimetro clienti dell'utente. Il download è sempre «scarica»; *apri* (PDF, immagini, testi, configurazioni) li mostra nel browser in un riquadro isolato (nessuno script). Ogni scaricamento, caricamento ed eliminazione finisce nell'Audit. Gli allegati dei vecchi asset sono passati da soli alla nuova tabella. Eliminando un documento o un asset gli allegati restano nel Cestino per 30 giorni e tornano con il ripristino; eliminando un device spariscono. **Attenzione:** i file non sono dentro il backup del database (come per gli allegati già esistenti): copiare anche la cartella `assets/`.
- Test: `ci/links_test.py` (apparati multi-device, documenti multi-collegamento, perimetro clienti, allegati, limiti, cestino, eliminazione device, migrazione).

## 8.40 Codice dei ticket, marchio personalizzato e diagnostica (1.40.0)

Tutte e tre le impostazioni stanno in **Sistema** (admin), ognuna nella sua scheda.

- **Codice dei ticket.** Scheda *Codice dei ticket*: un modello con segnaposto `{YYYY}` (anno a 4 cifre), `{YY}` (a 2), `{MM}` (mese), `{DD}` (giorno) e `{N}` oppure `{N:4}` (progressivo con da 1 a 8 cifre; senza numero sono 4). Il resto è testo fisso (lettere, cifre e `_ . / # -`, fino a 40 caratteri); serve esattamente un progressivo. Predefinito `T-{YYYY}-{N:4}` (`T-2026-0042`); per esempio `T-{YY}{MM}{DD}-{N:4}` dà `T-261013-0001`. Il progressivo **riparte** in base al segnaposto di data più fine: ogni giorno, mese o anno; senza data non riparte mai. Il progressivo non riutilizza mai un numero (anche se il contatore si perde, riparte dal massimo dei codici esistenti dello stesso periodo). **I ticket già creati tengono il loro codice**; ricerca ed elenchi funzionano con tutti i formati. La data usa il fuso orario del server. Un modello vuoto torna al predefinito; un modello non valido viene rifiutato con il motivo.
- **Marchio personalizzato (white label).** Scheda *Personalizzazione del marchio*: **nome** (fino a 40 caratteri), **logo** (PNG, JPEG, WebP o SVG, massimo 256 KB, meglio quadrato) e **colore principale**. Si applicano alla pagina di accesso, al menu, ai titoli delle pagine, al piè di pagina, alle email di notifica (oggetto e mittente), ai testi della chat con l'utente e al LEGGIMI dello ZIP di installazione. Lasciando il nome vuoto, senza logo e con «usa quello predefinito» restano **myrmm**, la formica e il verde originali. Il colore viene adattato ai due temi (più chiaro sullo scuro, più scuro sul chiaro) e il testo sopra i pulsanti resta sempre leggibile. Anche i grigi dell'interfaccia (sfondi, riquadri, bordi, testi) prendono la tinta del colore scelto (con un colore grigio restano neutri); i colori di stato ok/avviso/errore non cambiano. L'SVG è controllato (niente script, eventi o riferimenti esterni) e il logo è servito con intestazioni restrittive; il file sta in `data/brand/` con nome casuale. Non cambiano il nome del servizio e dei file dell'agent sui PC.
- **Diagnostica prestazioni.** Scheda *Diagnostica prestazioni*, pulsante *Misura adesso*: versione di PHP, OPcache (attiva? successi, memoria), compressione, velocità del processore, scrittura e latenza del disco, SQLite (inserimenti, scrittura singola con commit, letture) su un file di prova che viene cancellato, e i tempi delle interrogazioni tipiche sul database vero (device, risultati, audit, alert, ticket). Ogni voce ha uno stato (ok, avviso, critico) e un suggerimento. La misura dura qualche secondo e resta salvata con la data dell'ultima esecuzione. Il numero che conta di più per gli heartbeat è la *latenza di una piccola scrittura*: sopra i 5 ms il disco è il collo di bottiglia (tipico dei dischi di rete degli hosting condivisi).
- Pacchetto di distribuzione: non contiene più il confronto con altri RMM; contiene `THIRD-PARTY-NOTICES.md` con le licenze delle librerie dell'agent e della libreria QR inclusa nel server (1.40.1: l'elenco era incompleto). Negli esempi gli indirizzi sono `rmm.example.com`.
- Test: `ci/brand_test.py` (modello dei ticket, marchio, diagnostica).

## 8.41 Menù delle azioni e report al volo (1.41.0)

**Meno pulsanti in fila.** Le azioni meno vitali sono raccolte in menù a tendina, nello stesso stile dell'elenco *Colonne*:
- **Device**: *Azioni sui selezionati ▾* (inventario completo, scansione e applicazione patch, aggiornamento agent, imposta reparto, sposta in cliente, imposta campo) ed *Esporta ▾*. Su telefono stanno dietro a «Filtri e azioni», come il resto della barra.
- **Alert**, **Attività**, **Asset**, **Scadenze**: un solo *Esporta ▾* al posto dei vari pulsanti CSV.
- **Scheda del device**: *Report ▾* in testata e *Altre azioni ▾* (inventario completo ora, aggiorna agent); Task manager, Servizi e File manager restano visibili perché sono gli strumenti d'uso quotidiano.
- **Report mensile**: *Esporta ▾* (PDF, Excel, CSV, stampa della pagina).

**Report al volo di un singolo elemento.** Dal menu *Report ▾* della scheda di un **device**, di un **asset**, di un **ticket** e dal report mensile di un **cliente** si scarica subito il contenuto in **PDF**, **Excel (XLSX)** o **CSV**:
- device: scheda (con i campi personalizzati), dischi, alert (aperti e ultimi 90 giorni), patch in sospeso, ticket, ultime operazioni, asset collegati, software installato;
- asset: scheda con i campi del tipo (le password non sono mai incluse);
- ticket: scheda e cronologia completa;
- cliente e mese: sintesi, tipi di alert, device con più alert, alert del mese, parco macchine, sistemi a fine supporto.
Tutti gli elenchi (device, inventario, software, alert, attività, asset, scadenze) si esportano ora anche in Excel e PDF, con gli stessi filtri di prima. Il CSV resta identico (separatore `;`, BOM per Excel, difesa dalle formule). L'Excel ha un foglio per sezione, intestazione in grassetto e bloccata, larghezze automatiche, numeri veri; il PDF è A4 (orizzontale se le colonne sono molte), con intestazione ripetuta a ogni pagina, numerazione e, per elenchi oltre 3000 righe, l'avviso che l'elenco completo è in CSV/Excel. Nessuna libreria esterna (serve solo l'estensione `zip` di PHP per l'Excel; se manca, si scarica il CSV).
- Permessi: i report di un singolo elemento li scarica anche il ruolo *viewer*, limitatamente al proprio perimetro clienti (altrimenti 404); gli elenchi richiedono *operator*. Ogni download è nel registro di audit (`report_get`, `export`).
- Test: `ci/report_test.py` (apertura reale di XLSX con openpyxl, PDF verificati con qpdf e pdftotext, perimetro, ruoli, menù su desktop e telefono).

## 8.42 Lingue e dossier di audit (1.42.0)

**Metodo di traduzione.** L'italiano è la lingua di origine: il testo italiano è la chiave. Ogni lingua è un file `server/lang/<codice>.json` (`en`, `fr`, `es`; formato `{"testo italiano": "traduzione"}`). Le correzioni fatte da console stanno nel database e prevalgono sul file, quindi sopravvivono agli aggiornamenti. Ordine di ricerca: lingua scelta, poi inglese, poi italiano (una voce mancante non resta mai vuota). In **Sistema → Lingue** (admin): lingua predefinita, copertura per lingua, modifica stringa per stringa, **esporta** (tutto o solo mancanti) e **importa** JSON, lingua per ogni cliente. Ogni utente sceglie la propria lingua in **Profilo**; report e dossier di un cliente escono nella sua lingua (modificabile al download).
- **Pagine esistenti.** Con la *raccolta dei testi* attiva, ogni pagina aperta registra i testi non noti; si traducono poi in *Modifica* senza toccare il codice. L'interfaccia completa in inglese è arrivata con la 1.44.0 (§8.44).
- **Stato.** `en.json` copre documenti e console (§8.44); `fr.json` e `es.json` sono vuoti (ripiegano sull'inglese).

**Dossier di audit** (menù *Operazioni → Dossier audit*, viewer nel proprio perimetro). Documenti PDF generati al volo (nessun archivio) per cliente e periodo: *Report esecutivo*, *Inventario*, *Aggiornamenti e patch*, *Incidenti e interventi*, *Accessi*, *Scadenze*, *Rischi e raccomandazioni*, *Mappa dei controlli e delle evidenze* (NIS2 art. 21, ISO/IEC 27001:2022 Allegato A, GDPR art. 32, misure minime AgID, evidenze tipo polizza cyber). Ogni PDF ha copertina, indice, riquadri di sintesi, grafici, tabelle, ID documento e «Pagina X di Y»; con marchio personalizzato usa nome, colore e logo PNG/JPEG. Da ogni documento si scarica anche Excel/CSV con i dati completi; il pulsante **ZIP completo** raccoglie tutto con `SHA256SUMS.txt` (impronte per dimostrare che i file non sono stati modificati).
- **Limiti dichiarati.** Sono evidenze, non una certificazione: la mappa dei controlli dice cosa il sistema rileva e segna «Da integrare» ciò che richiede documenti dell'organizzazione. La disponibilità è una stima dagli alert offline. Il logo SVG non entra nel PDF. Antivirus, cifratura, firewall, amministratori locali e backup risultano «non rilevati» finché l'agent non li raccoglie (vedi §8.43).
- Test: `ci/lang_test.py`, `ci/dossier_test.py` (PDF con qpdf/pdftotext, XLSX, ZIP con hash, perimetro e ruoli).

## 8.43 Prove di sicurezza raccolte dall'agent (1.43.0)

L'inventario completo contiene ora una sezione **Sicurezza** (visibile nella scheda del device e usata dal dossier di audit, che sostituisce «non rilevato» con i dati veri). Si aggiorna con l'inventario (ogni 12 ore o su richiesta).
- **Windows**: antivirus/EDR registrato nel Centro sicurezza (nome, attivo, firme aggiornate; sui server, dove il Centro sicurezza non c'è, si usa Microsoft Defender), cifratura BitLocker dei volumi di sistema e dati, firewall per profilo (dominio, privato, pubblico), amministratori locali, ultimo backup riuscito (Windows Server Backup oppure Veeam Agent).
- **Linux**: cifratura dei volumi montati (LUKS, da `lsblk`), firewall (ufw, firewalld o nftables), amministratori locali (sudo/wheel/admin). **macOS**: solo amministratori locali. Antivirus e backup non sono rilevati su queste piattaforme e nel dossier restano «da integrare».
- Una voce che l'agent non riesce a leggere resta **assente** (non conta né come conforme né come carenza); «antivirus non presente» compare solo se la ricerca ha dato esito negativo.
- **Limiti onesti.** Le interrogazioni di Windows non sono provabili senza un Windows: la logica che interpreta i risultati è provata con test (`agent/security_test.go`), il comando Linux è provato end-to-end, ma la raccolta su Windows va verificata sul primo PC reale: scheda del device → *Inventario completo ora* → sezione Sicurezza. Il rilevamento del backup riguarda solo i due prodotti citati; altri prodotti restano da documentare a mano.

## 8.44 Console completa in inglese (1.44.0)

La console è tradotta per intero in inglese (`server/lang/en.json`, circa 3.300 voci). Il metodo resta quello del §8.42; cambia il filtro di uscita, che ora traduce **blocchi di testo** e non frammenti.
- **Chiave e segnaposto.** Un paragrafo con tag in linea (`<b>`, `<a>`, `<code>`…) è una sola voce: i tag diventano `<1>…</1>`, i numeri `{n}`, `<br>` resta com'è. Nella traduzione vanno **conservati tutti i segnaposto** (`{n}`, `<1>`…`</1>`): una traduzione che li perde viene ignorata e resta l'italiano. Esempio: «Hai <1>{n}</1> device» → «You have <1>{n}</1> devices».
- **Cosa si traduce.** Testi delle pagine, attributi (`title`, `placeholder`, `aria-label`, `alt`, pulsanti, `data-confirm`), segnaposto delle textarea, messaggi di conferma e avviso dentro JavaScript (solo a corrispondenza esatta del testo). Etichette con un dato dopo (`Scheda device: NOME`, `Servizi · NOME`, `Lancia su NOME`) si traducono sull'etichetta e il dato resta com'è.
- **Cosa non si traduce.** I dati (nomi di host, clienti, ticket, documenti, corpi degli script e delle procedure), i messaggi grezzi dell'API verso gli agent, le parole singole dentro JavaScript e i corpi degli script di libreria (sono codice). Le descrizioni delle variabili degli script si traducono.
- **Non da tradurre.** In Sistema → Lingue → Modifica ogni voce ha la casella *Non tradurre* (codice, nomi propri, dati): vale per tutte le lingue, la voce sparisce dai mancanti e dalla copertura, la raccolta non la registra più e il filtro *Non da tradurre* permette di rivederle. Con una ricerca nel filtro, *Segna tutte le voci del filtro* flagga in blocco. Le esportazioni JSON contengono la chiave riservata `__non_tradurre__` (elenco); chi traduce il file lascia stare quelle voci e l'importazione le ricorda.
- **Come completare o correggere.** Sistema → Lingue → *Raccolta testi*: naviga, poi traduci ciò che compare in «da tradurre» (o correggi da *Modifica*). Francese e spagnolo ripiegano sull'inglese finché non hanno un proprio file.
- **Costo.** Il filtro lavora sull'HTML già prodotto: nelle pagine grandi (centinaia di device) aggiunge circa 100–250 ms rispetto all'italiano; l'italiano non ne è toccato.
- **Limiti onesti.** La copertura viene da una raccolta automatica delle pagine con dati di prova, più una scansione del sorgente per messaggi, stati vuoti e descrizioni: uno stato che non si è mai presentato nelle prove (un errore raro, un ramo di configurazione) può essere rimasto in italiano; compare allora nella raccolta testi. Il test `ci/lang_ui_test.py` verifica che 45 pagine in inglese non lascino frasi italiane.

## 8.45 Telefoni e tablet senza agent: check-in (1.46.0)

Android e iOS non permettono di eseguire script né di installare un servizio come sugli altri sistemi. Per avere comunque **inventario e stato online** in console, è il telefono a segnalarsi: un'automazione sul telefono fa una POST periodica a `?action=mobile_checkin`. Niente Termux, niente agent, niente MDM.
- **Chiamata.** `POST <server>/?action=mobile_checkin`, JSON o form. Obbligatori `token` (token del cliente, lo stesso degli installer: il telefono finisce in quel cliente) e `id` (stringa fissa e unica per telefono, 8-64 caratteri `A-Za-z0-9._:-`, da trattare come un segreto). Facoltativi: `name`, `os` (`android`/`ios`), `os_version`, `manufacturer`, `model`, `battery`, `charging`, `free_gb`, `total_gb`, `ip`, `ssid`, `user`, `interval_min` (5-1440, default 60). Il token si può passare anche nell'intestazione `X-Token`.
- **Cosa succede.** Alla prima chiamata il server crea il device (colonne `mobile_id` e `mobile_min`), nelle successive aggiorna ultimo contatto e inventario (OS, produttore, modello, batteria, spazio, IP, utente) e chiude l'alert offline. Lo spazio libero passa dalle soglie disco come per gli altri device.
- **Online/offline.** Un telefono è online per il doppio del suo `interval_min` (minimo 30 minuti; gli agent restano a 10). Il server crea per il telefono una soglia `offline_min` propria (param `mobile`) e la aggiorna se l'intervallo cambia; quella globale non cambia. Vale per elenco, scheda, dashboard e report.
- **Cosa non c'è.** Script, task manager, file manager, controllo remoto, aggiornamento agent: la scheda lo dice e nasconde i pulsanti. Un job lanciato in massa su un telefono resta in attesa e non viene consegnato.
- **Sicurezza.** Chi conosce token e `id` può far risultare online quel telefono; un `id` già usato non si può riusare con il token di un altro cliente (403). Token errati sono limitati come l'arruolamento (429 dopo `RL_MAX_FAILS`). Revocando il device i check-in sono rifiutati.
- **Modelli pronti.** In Installazione → «Telefoni e tablet (Android e iOS) senza agent» ci sono indirizzo, JSON di esempio e i passi per iOS (Comandi + automazione personale: iOS non garantisce intervalli precisi, usa `interval_min` largo) e Android (MacroDroid, Tasker, HTTP Shortcuts; disattivare l'ottimizzazione batteria dell'app).
- **Test.** `ci/mobile_test.py` (19 controlli).

## 8.46 Android Enterprise: telefoni aziendali e personali (1.47.0)

Per i telefoni Android myrmm si appoggia all'**Android Management API** di Google, come fanno gli RMM che gestiscono i mobile (per esempio SuperOps): sul telefono gira «Android Device Policy», l'app di Google, e non c'è nessun agent nostro da installare. Il check-in del §8.45 resta per iPhone e per i telefoni che non si possono arruolare.
- **Cosa si ottiene.** Arruolamento con QR, inventario e stato letti dall'API (OS, produttore, modello, seriale, RAM, archiviazione, livello patch di sicurezza, proprietà aziendale o personale, conformità ai criteri), comandi **blocca schermo**, **riavvia** e **ripristina (wipe)**. Non si eseguono script e non c'è controllo remoto, come negli altri RMM.
- **Aziendali e personali.** Aziendale (*fully managed*): il telefono si ripristina, nella schermata di benvenuto si tocca 6 volte e si inquadra il QR; criteri e app si applicano da soli. Personale (*work profile*): l'utente installa Android Device Policy dal Play Store e inquadra il QR; è gestita solo la parte di lavoro, il resto del telefono resta suo.
- **Collegamento (Piattaforma → Android, una volta sola).** In Google Cloud Console: progetto, attivare *Android Management API*, *service account* con chiave JSON. La chiave si incolla nella pagina (resta cifrata, come i segreti RustDesk, e non viene più mostrata). L'enterprise si crea con «Crea enterprise con Google» (Google chiede l'accesso e torna alla console; se non torna, c'è il ripiego col token incollato a mano) oppure si indica una già esistente (`enterprises/LC…`).
- **Criteri.** Due criteri, `myrmm-company` e `myrmm-byod`, in JSON di Android Management API, modificabili dalla pagina. Quelli di partenza fanno solo riportare stato e inventario: password, app e restrizioni si aggiungono quando servono. Si inviano a Google a ogni salvataggio e a ogni nuovo QR.
- **Aggiungi telefono.** Scegli tipo (aziendale o personale), cliente, nome facoltativo e validità (da 1 ora a 30 giorni): myrmm chiede a Google un token di arruolamento a uso singolo e mostra QR, istruzioni e codice. Cliente e nome viaggiano nel token: alla sincronizzazione il telefono nasce già nel cliente giusto e col nome scelto.
- **Sincronizzazione.** Ogni mezz'ora circa (agganciata a manutenzione, elenco Device e dashboard) più il pulsante «Sincronizza ora». I telefoni sono device con `mobile_id = amapi:<id>`; stato online dall'ultimo rapporto di Google, con finestra di 12 ore (Android non riporta a intervalli regolari) e soglia offline propria di 720 minuti. Il tipo di proprietà e la conformità compaiono nell'inventario.
- **Comandi.** Dalla scheda del telefono: blocca e riavvia (operatore), ripristina (solo admin; sul telefono personale rimuove il work profile). Il comando parte a Google e il telefono lo esegue alla prossima connessione. Ogni comando è nell'audit.
- **Cosa serve.** Un progetto Google Cloud con l'API attiva e un account per creare l'enterprise (gratuiti); **quota dispositivi** concessa da Google al progetto (da richiedere con il loro modulo: senza, l'arruolamento fallisce con «l'organizzazione ha raggiunto i limiti di utilizzo» anche a zero dispositivi, e la risposta può richiedere giorni); un telefono offline da 270 giorni va riarruolato. Il server ha bisogno di raggiungere `androidmanagement.googleapis.com` in HTTPS.
- **Richiesta quota (1.51.0).** Nella pagina Android, sotto «Aggiungi telefono», c'è il riquadro con il link diretto al modulo di Google (`goo.gle/android-enterprise-response`: quota iniziale fino a 500 dispositivi, serve una giustificazione), alle regole d'uso e alla pagina Quote del progetto nella console (con l'ID progetto preso dalla chiave del service account). Il riquadro compare anche in cima alla pagina quando l'errore ricevuto da Google parla di limiti o quota.
- **Alternativa senza Google (1.51.0).** Nella stessa pagina, la scheda «Alternativa senza Google: check-in del telefono» (§8.45) prepara per un telefono Android o iPhone indirizzo e JSON già compilati (token del cliente, `id` casuale, nome, intervallo) e i passi per HTTP Shortcuts o Comandi. Non servono quota, enterprise né service account.
- **Limiti.** Cancellare un telefono dalla console non lo toglie da Google: alla sincronizzazione successiva ricompare. La rimozione si fa dal comando di ripristino o dalla console Google. Lo spazio libero non è fornito dall'API: l'inventario mostra solo la capacità.
- **Test.** `ci/android_test.py` (43 controlli) contro un Google simulato: autenticazione JWT RS256, creazione enterprise, criteri, token, sincronizzazione con più pagine, comandi.

## 8.51 App myrmm per Android (APK) (1.52.0)

Per i telefoni Android quando non si può o non si vuole usare Android Enterprise (§8.46 richiede la quota dispositivi di Google e dati d'impresa, DUNS compreso). Nessun Google, nessun account aziendale. Sorgente in `android/` (repository `myrmm-android`, pubblico).

- **Cosa fa.** Un'app che si segnala alla console con un lavoro periodico di Android (ogni 15-1440 minuti, sopravvive al riavvio): modello, produttore, versione di Android e livello patch, batteria, spazio, IP, stato dell'amministratore. Il telefono compare in Device come negli altri check-in (§8.45), con l'etichetta «apk».
- **Comandi dalla console.** Nella scheda del telefono: *Controlla ora*, *Blocca schermo* (operatore) e *Ripristina (wipe)* (solo admin, scrivendo il nome del telefono). I comandi stanno in coda (tabella `mobile_cmds`) e il telefono li prende al check-in successivo: la latenza massima è l'intervallo scelto. Dopo l'esecuzione il telefono riporta l'esito subito; la scheda mostra lo storico (in coda, consegnato, eseguito, non riuscito, scaduto dopo 24 ore). Ogni comando è nell'audit.
- **Sicurezza del telefono.** Blocco e ripristino funzionano solo se nell'app si attiva l'*amministratore del dispositivo*; il ripristino richiede anche la spunta «Consenti il ripristino» sul telefono, spenta di base. Solo HTTPS. L'identificativo del telefono è casuale e resta sul telefono; il token è quello del cliente (§8.45): un identificativo già usato non si può riusare con un altro cliente.
- **Installazione.** *Piattaforma → Android → Alternativa senza Google*: scegli cliente, nome e sistema; la console mostra **due QR**: *1. Scarica l'APK* (indirizzo `?action=mobile_apk` del tuo server) e *2. Configura l'app* (vedi sotto). L'APK è **incluso nel pacchetto** (`server/update/myrmm-android.apk`, servito dal tuo server con `?action=mobile_apk`, senza accesso alla console perché il telefono non ha l'accesso); l'ultima compilazione è anche nella release `latest` del repository (con `meta apk:url` si può indicare un altro indirizzo). Dopo ogni nuova compilazione si copia l'APK in `server/update/`. Il QR di configurazione apre una pagina (`?action=mobile_setup`) con il pulsante «Apri nell'app myrmm»: l'app si apre con indirizzo, token, nome e intervallo già compilati e basta premere *Salva e avvia*. Poi si attiva l'amministratore e si esclude l'app dal risparmio batteria.
- **Inventario ricco (1.53.0, app 1.2.0).** A ogni check-in: RAM libera/totale, uptime (e ultimo boot), tipo di rete, salute e temperatura della batteria. Ogni 6 ore (e dopo un comando) anche: versione/API Android, build, kernel, architettura, schermo, lingua, fuso, operatore, cifratura, blocco schermo, debug USB, opzioni sviluppatore, segni di root e le app installate dall'utente (nome, versione, pacchetto, data; le app di sistema sono solo contate). L'app usa il permesso `QUERY_ALL_PACKAGES`, adatto alla distribuzione fuori da Play Store. Tutto in «Hardware e software» della scheda.
- **Identità del telefono (app 1.2.1).** L'id deriva dall'Android ID (hash con il nome del pacchetto): reinstallando l'app lo stesso telefono ritrova il suo device; dopo un ripristino di fabbrica risulta nuovo. Un telefono già registrato mantiene il suo id. L'Android ID dipende anche dalla chiave di firma dell'app: se cambia la chiave, il telefono risulta nuovo (per questo la chiave va tenuta nei segreti di GitHub, vedi `android/README.md`).
- **Firma dell'app (importante).** Android installa un aggiornamento solo se la firma è la stessa. Su GitHub la chiave di debug cambia a ogni build, quindi l'APK va firmato con una chiave fissa nei segreti del repo `myrmm-android`: `KEYSTORE_B64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`. Tieni una copia del file `.jks` e delle password: se le perdi, ogni aggiornamento richiede la disinstallazione (e il telefono risulta nuovo, perché l'Android ID dipende dalla chiave). Verifica: l'impronta SHA-256 del certificato dell'APK deve restare uguale tra una versione e l'altra.
- **Aggiornamenti.** L'app **non si aggiorna da sola** (Android non permette l'installazione silenziosa a un'app fuori da Play Store o senza gestione completa). Il server legge la versione dell'APK incluso da `server/update/apk-version.txt` e la comunica a ogni check-in; se è più recente di quella installata l'app mostra «Aggiornamento disponibile» con il pulsante *Scarica l'aggiornamento*, e la scheda del telefono in console mostra «app X: disponibile la Y». Si scarica e si installa **sopra** la versione presente: dati e impostazioni restano, ma l'installazione va confermata sul telefono. Funziona solo se la nuova versione è firmata con la **stessa chiave**; la chiave di debug del workflow è in cache e può cambiare se la cache scade (allora: disinstalla e reinstalla). Per una firma stabile si può generare una chiave una volta sola e metterla nei segreti del repository (vedi `android/README.md`).
- **Dove si trova.** Piattaforma → Android, scheda «App myrmm per Android (senza Google)»: è sempre visibile, anche se Android Enterprise non è collegato (dalla 1.52.1). In cima c'è il QR di scarico; scegliendo cliente, nome e sistema e premendo *Prepara* compaiono il QR di configurazione e i passi.
- **Scollegare Android Enterprise (1.52.1).** Nella stessa pagina, in «1. Collegamento a Google», il pulsante *Scollega Android Enterprise* rimuove da myrmm service account, enterprise, criteri e stato della sincronizzazione; la spunta *elimina anche i telefoni importati da Google* li cancella dall'elenco (altrimenti restano). Su Google l'enterprise e il service account restano: si eliminano dalla console Google.
- **Compilazione.** Il workflow GitHub Actions compila a ogni push e pubblica `myrmm-android.apk` nella release `latest`; gli errori di compilazione escono come annotazioni. L'APK è firmato con la chiave di debug del runner, tenuta in cache: se la cache scade la firma cambia e si reinstalla da zero.
- **Limiti.** Non esegue script e non c'è controllo remoto; non c'è push, quindi i comandi arrivano al check-in (minimo 15 minuti, limite di Android); il riavvio da remoto non è possibile; l'API di amministratore del dispositivo è deprecata e sulle versioni recenti di Android può avere limiti. **Non provata su un telefono reale**: finora compilata e firmata su GitHub, e il lato server è testato con un telefono simulato.
- **Test.** `ci/devkind_test.py` (funzioni per tipo di device e inventario ricco) e `ci/mobile_test.py` (37 controlli: inventario APK, comandi, doppio clic, conferma del wipe, esiti, scadenza, altro cliente, pagina del QR) e `ci/android_test.py` (44).

## 8.52 Linee guida e assistente MCP sui device (1.53.0, eseguibile Go dalla 1.54.0)

- **Linee guida.** Operazioni → *Linee guida* (visibile a tutti): regole d'ingaggio dell'assistente, cosa si può fare per tipo di device, uso dei token, distribuzione e percorsi dei file. È la fonte unica: la stessa pagina esce dall'API (`r=guidelines`) e dallo strumento MCP `myrmm_guidelines`, e il server MCP all'avvio invita l'assistente a leggerle prima di agire.
- **Script di libreria** (Script → cerca «myrmm MCP»): *installa su Windows*, *installa su Linux*, *installa su macOS*, **collega Claude Desktop (Windows)** (1.65.3), *rimuovi da Windows*, *rimuovi da Linux/macOS*. Variabili: `MCP_TOKEN` (obbligatoria), `MCP_URL` (vuota = indirizzo letto dalla config dell'agent), `MCP_USER` (Linux/macOS: utente che leggerà la configurazione).
- **Un solo eseguibile, nessun Python (1.54.0).** Il server MCP è un programma Go statico (`mcp/go`, solo libreria standard) compilato da `release.sh` per windows/amd64, linux/amd64+arm64, darwin/amd64+arm64 e pubblicato in `update/myrmm-mcp-<os>-<arch>[.exe]` (circa 6 MB ciascuno). Sul device non si installa nient'altro: né Python, né runtime, né pacchetti. Requisiti minimi come l'agent (Windows 10 / Server 2016 o successivi). Il vecchio `myrmm_mcp.py` resta pubblicato e riceve le stesse correzioni, come riserva per le installazioni 1.53 e per chi preferisce Python; non è più distribuito dagli script.
- **Claude Desktop (1.65.3).** Lo script «collega Claude Desktop (Windows)» si esegue dopo l'installazione, sul PC dove c'è Claude Desktop. Variabile facoltativa `MCP_USER` (default: l'utente collegato alla console; l'utente deve aver fatto l'accesso almeno una volta). Aggiunge la voce `myrmm` a `claude_desktop_config.json` dell'utente (anche nella cartella dati dell'installazione da Microsoft Store, se esiste) **senza perdere il resto del file** (copia in `.myrmm.bak`; JSON non valido: esito 7 e file intatto) e dà a quell'utente la lettura di `myrmm-mcp.json`, così il token non finisce nel suo profilo. Esiti: 2 utente non valido o senza profilo, 6 server MCP non installato, 7 JSON non valido. Non installa Claude Desktop (si scarica da claude.ai/download) e, se manca, lo segnala. Dopo ogni reinstallazione del server MCP va rilanciato (i permessi di lettura vengono ripristinati) e Claude Desktop va chiuso del tutto (icona nell'area di notifica → Esci) e riaperto. Test su Windows vero: `ci/windows_install_test.py`.
- **Cosa fa l'installazione.** Chiede a `?action=api&r=mcp&os=…&arch=…&info=1` l'hash SHA-256 e la dimensione dell'eseguibile per quel sistema, lo scarica (`r=mcp&os=…&arch=…`) con lo stesso token, ne confronta l'hash (se è diverso non lo installa e non lascia nulla) e lo mette al posto del vecchio (su Windows rinomina anche un `.exe` in uso). Poi scrive `myrmm-mcp.json` con indirizzo e token, prova l'eseguibile (`--version`) e verifica il collegamento con il suo `--check` (stampa solo ASCII, mai il token, esce 0 se il token funziona). Rilanciare lo script aggiorna l'eseguibile e ripulisce i file della 1.53 (`myrmm_mcp.py`, `myrmm-mcp.cmd`, il runtime `python`). Codici di uscita: 2 variabili non valide, 3 eseguibile che non parte (sistema o architettura non compatibili), 4 download o hash, 5 verifica del token. Stampa il comando per registrare l'MCP (`claude mcp add myrmm -- <percorso>`). Il server legge la configurazione dal file accanto all'eseguibile (seguendo i collegamenti simbolici) quando mancano `MYRMM_URL`/`MYRMM_TOKEN`; `MYRMM_CONFIG` indica un altro file; `"proxy"` nel file (o `MYRMM_PROXY`) indica un proxy, altrimenti valgono `HTTPS_PROXY`/`HTTP_PROXY` (come per l'agent; il proxy di Windows in Internet Explorer non viene letto).
- **Dove.** Windows `C:\Program Files\myrmm-mcp\myrmm-mcp.exe` (ACL: solo Amministratori e SYSTEM sul file di configurazione); Linux `/opt/myrmm-mcp/myrmm-mcp`; macOS `/usr/local/myrmm-mcp/myrmm-mcp`; comando `/usr/local/bin/myrmm-mcp` (collegamento simbolico). Configurazione 600.
- **Su quali device.** Quelli che scegli tu: Device → seleziona (stesso sistema per volta) → *Esegui sui selezionati* → script e `MCP_TOKEN`. Gli script non toccano i device non selezionati e saltano da soli i sistemi non adatti (script Windows su Windows, «unix» su Linux/macOS).
- **Sicurezza.** I valori delle variabili entrano nello script come testo letterale (here-document/here-string): un token con apici o comandi non viene eseguito e viene rifiutato (il token deve essere `myrmm_` + 48 caratteri esadecimali; l'indirizzo deve essere https). **Valori su più righe (corretto in 1.54.0).** Nella 1.53 un valore con un a capo seguito dal terminatore (`'@` in PowerShell, `MYRMM_V` in sh) usciva dal blocco ed eseguiva codice prima di qualunque controllo; provato e corretto: il segnaposto `{{NOME|linea}}` (nuovo, vale per qualunque script di libreria) sostituisce a capo e ritorni a capo con spazi, e gli script MCP lo usano per tutte le loro variabili; inoltre l'API `run` rifiuta con 422 i valori di variabile con a capo, caratteri di controllo o oltre 4000 byte. Resta vero per gli altri script di libreria che mettono `{{VAR}}` tra apici: il valore su una riga con un apice può ancora uscire dalle virgolette; per questo la coda di approvazione mostra il testo già sostituito e vale rileggerlo. Il token nel testo di un job viene sostituito da asterischi appena arriva l'esito (vale per qualunque job, anche non MCP); finché il job è in corso lo vede chi può vedere i job. Usa un token dedicato, di sola lettura se basta, e revocalo con la rimozione. L'eseguibile non è firmato (lo scarica l'agent, non il browser, quindi Windows non applica SmartScreen; un antivirus potrebbe comunque segnalarlo come l'agent).
- **Limiti.** Lo script Windows è stato eseguito solo con PowerShell 7 su Linux (con `icacls` neutralizzato), non con Windows PowerShell 5.1 su un Windows vero: provalo prima su una VM del collaudo. L'eseguibile macOS non è stato provato su un Mac (il linker Go firma ad hoc i binari arm64). Nessun controllo remoto aggiuntivo: l'MCP usa l'API con i limiti del token.
- **Test.** `ci/mcp_go_parity_test.py` (22 controlli: stesse richieste all'API e stesse risposte del Python per ogni strumento, ordine delle chiavi, accenti, errori di rete e di server, riga molto lunga, configurazione con BOM / collegamento simbolico / `MYRMM_CONFIG` / proxy, `--version`, `--check`); `ci/mcp_deploy_test.py` (48 controlli: script e variabili, sintassi sh, download per le 5 piattaforme con hash, esecuzione reale degli script in sandbox con agent Linux e, se c'è `pwsh`, dello script Windows, hash manomesso, aggiornamento sopra la 1.53, iniezione con valori su più righe, rifiuto dell'API, rimozione, linee guida, mascheramento del token).
- **Server MCP** (`mcp/go`, programma Go statico; `mcp/myrmm_mcp.py` è la versione equivalente in Python). 24 strumenti (17 fino alla 1.67, più i 7 degli incarichi AI, §8.67): linee guida, stato, clienti, device, scheda, alert, script, backup, esecuzione (con attesa dell'esito), bozze, job, annulla, audit, incarichi. Si configura con `MYRMM_URL` e `MYRMM_TOKEN`; per Claude Code: `claude mcp add myrmm -e MYRMM_URL=https://…/index.php -e MYRMM_TOKEN=myrmm_… -- /percorso/myrmm-mcp` (o `-- python3 mcp/myrmm_mcp.py`).
- **Laboratorio consigliato.** Una o più macchine di prova arruolate nel cliente «Collaudo»: una VM Windows (anche con più versioni), una VM Linux, un Mac. Arruolamento come per ogni device (Deploy). Un token `operator` con scrittura diretta su «Collaudo» permette all'assistente di accodare, leggere l'esito e correggere senza chiedere ogni volta; un secondo token `viewer` senza limiti di cliente gli lascia leggere il parco reale senza poterlo toccare. Per eseguire su un cliente reale: token con approvazione.
- **Cosa non c'è, di proposito.** Nessun ruolo admin via API, nessuna esecuzione di testo libero fuori dai clienti di collaudo, nessun accesso a file, tunnel o desktop remoto.

### 8.50 Bozze di script ed esecuzione inline (1.51.0)

L'assistente può creare script nuovi e provarli live, ma **solo sul collaudo**: nulla arriva ai clienti reali senza un clic di un amministratore.

- **Bozze.** `r=draft_save` (POST: name, description, platform windows/unix/any, timeout, body; `id` per modificare), `r=draft_delete`, e in lettura `r=drafts` (body=1 per il testo) e `r=draft&id=`. Servono token a **scrittura diretta**. Le bozze stanno in una tabella a parte: non compaiono nella libreria, nelle regole, nelle pianificazioni né nei runbook.
- **Esecuzione.** `r=run` con `draft_id` (oppure `body` + `platform` per un testo libero non salvato). Solo token a scrittura diretta, solo su clienti di collaudo, simulazione predefinita, stesse variabili `{{NOME}}`. Un token con elenco di script ammessi non può eseguire testo libero. Il job riporta origine `draft:N` o `inline`; il testo libero finisce nell'audit (primi 1500 caratteri), con impronta SHA-1.
- **Promozione.** In *API e collaudo → Bozze di script* leggi il testo e premi **Promuovi alla libreria** (solo admin): diventa uno script normale, la bozza resta tracciata come promossa e non è più modificabile. Eliminare una bozza è consentito anche agli operatori.
- **Collaudo dalla pagina Clienti.** Ogni cliente ha il pulsante «Collaudo: sì/no» (solo admin). Togliere il collaudo riporta a «con approvazione» i token a scrittura diretta.
- **MCP.** Nuovi strumenti `myrmm_list_drafts`, `myrmm_save_draft`, `myrmm_delete_draft`, `myrmm_run_draft`, `myrmm_run_inline`. Ciclo tipico: salva bozza → eseguila sul collaudo → leggi l'esito → correggi → rieseguila → tu la promuovi.
- **Limite.** La simulazione resta best-effort. Un'esecuzione reale (dry_run falso) di testo libero sul collaudo fa davvero ciò che dice: usa macchine di prova ripristinabili (snapshot).
- **Test.** `ci/api_test.py` (106 controlli) e `ci/api_agent_test.py` (23, con ciclo bozza sbagliata → corretta su agent Linux reale).
- **Test.** `ci/api_test.py` (71 controlli: perimetro, approvazioni, collaudo, simulazione per piattaforma, scadenza, revoca, indirizzi, limiti) e `ci/api_agent_test.py` (agent Linux reale e server MCP: simulazione, esecuzione, variabili, codice di uscita).

## 8.53 Variabili degli script: sostituzione sicura (1.54.2)

Un valore passato a `{{NOME}}` (console, schedulazioni, regole, API, MCP) non può più diventare codice. Prima della 1.54.2 il valore veniva incollato nel testo dello script così com'era: in `'{{NOME}}'` bastava un valore con un apice per uscire dalla stringa ed eseguire comandi sul device.

- **Come funziona.** Il server legge lo script da sinistra a destra, seguendo apici, virgolette, here-string/here-document, commenti e sottoespressioni (`$( )`, backtick), e protegge il valore secondo il punto in cui sta. PowerShell: in `'…'` gli apici si raddoppiano (anche quelli tipografici ‘ ’, che PowerShell tratta come apici); in `"…"` si antepone il backtick a `` ` ``, `$`, `"`, “ ” „; in un commento gli a capo diventano spazi. sh: in `'…'` un apice diventa `'\''`; in `"…"` si antepone il backslash a `\`, `$`, `` ` ``, `"`. Nel codice (fuori da stringhe) un valore «semplice» (numero, nome, percorso) resta com'è; qualunque altro diventa una stringa tra apici, quindi `1; Remove-Item …` non è più un comando ma un testo.
- **Quale shell.** sh se lo script inizia con `#!` o se il device è Linux/macOS; altrimenti PowerShell (lo decide la piattaforma del device su cui gira).
- **Quando lo script non parte.** Se un valore potrebbe chiudere una here-string o un here-document (una riga uguale al terminatore, `'@`, `EOF`), il job diventa uno script che stampa «myrmm: script non eseguito: …» ed esce con 1: nulla del valore viene eseguito, e l'errore si vede nell'esito del job.
- **`{{NOME|linea}}`** resta valido: a capo e ritorni a capo diventano spazi prima di tutto il resto. L'API rifiuta ancora (422) valori con a capo o caratteri di controllo.
- **Prova.** `ci/var_inject_test.py`: casi per ogni contesto più TUTTA la libreria (188 script) con 29 valori ostili ciascuno. PowerShell: albero sintattico di pwsh (stesso numero di comandi e istruzioni del valore innocuo, nessun errore nuovo). sh: bashlex e un'esecuzione con PATH vuoto in cui ogni comando esterno viene solo registrato (nessun comando iniettato). Controllo negativo: con la vecchia sostituzione testuale il test trova 331 violazioni in PowerShell e 206 in sh; con la nuova zero.
- **Limiti.** L'analisi non è un interprete: costrutti PowerShell molto insoliti (stringhe costruite a pezzi, `Invoke-Expression` su testo composto) possono sfuggire. Il resto del rischio è nello script: un valore tra apici è sicuro, ma uno script che lo passa a `Invoke-Expression`, `eval` o `sh -c` lo esegue comunque.

## 8.54 Libreria script per temi, con etichette (1.55.0)

La libreria è passata da 188 a **323 script** (Windows, Linux, macOS), ciascuno con **etichette** che dicono a che cosa serve e quanto è rischioso. La pagina *Libreria script* ha una ricerca (nome, descrizione, variabili) e i filtri per etichetta, raggruppati e con il numero di script; più etichette insieme si sommano (servono tutte).

- **Vocabolario.** *Piattaforma* (windows, linux, macos: messa da sola), *Tipo* (monitor, raccolta, azione, installazione, diagnostica), *Rischio* (sola-lettura, modifica, distruttivo), *Area* (sicurezza, rete, dischi, servizi, utenti, aggiornamenti, software, prestazioni, stampa, inventario, pulizia, remoto, eventi, energia, browser, office, certificati, backup, container, virtualizzazione, web, database, dominio, hardware, tempo, file, cloud, avvio, sistema) e *Insieme* (onboarding, offboarding, hardening, risoluzione-problemi, manutenzione, audit, server, postazione, portatile). Ogni script ha almeno un Tipo, un Rischio e un'Area; un monitor è sempre di sola lettura. Gli script che già c'erano hanno etichette scelte a mano (`library/curated-tags.txt`); le etichette libere create da te restano ammesse e si cambiano da «modifica».
- **Convenzioni degli script nuovi.** Quelli che eliminano dati (rischio *distruttivo*) hanno un'anteprima: senza `APPLICA=si` mostrano solo che cosa farebbero. I monitor escono con 1 e scrivono il motivo nella prima riga, più `MYRMM_METRIC nome=valore`. Uscita 2 = variabile non valida, 3 = sistema operativo sbagliato o mancano i privilegi di amministratore. I valori passati a `{{NOME}}` sono sempre verificati prima dell'uso (e protetti dalla 1.54.2). Le nuove cartelle da cui si genera la libreria sono `library/windows`, `library/linux`, `library/macos` e `library/unix` (Linux e macOS insieme); `python3 tools/gen_library.py` le trasferisce nel server.
- **Che cosa c'è di nuovo.** Windows (65 script): sicurezza e audit, Defender, BitLocker, firewall, rete e DNS, hosts, aggiornamenti (in attesa, cronologia, criteri), AppX, Teams/Office/OneDrive, browser, runtime, utenti e gruppi locali con offboarding, Entra ID/Intune/gpresult, IIS, SQL Server, Hyper-V, stampa, permessi NTFS, controller di dominio, affidabilità e schermate blu, USB/PnP, variabili d'ambiente, avvio dei servizi, termina processo, regole firewall, robocopy, zip, registro HKLM, OpenSSH, driver non firmati. macOS (29): sicurezza, MDM, Time Machine, utenti, avvii, cache, Spotlight, rete, DNS, pacchetti, Rosetta, monitor. Linux (24) e Linux/macOS (17): file, archivi, porte, servizi, utenti, ufw, kernel, swap, database, aggiornamenti automatici.
- **API e MCP.** `GET /api/v1/scripts?tag=windows,sicurezza&q=firewall` filtra come la pagina; ogni script riporta `tags`. Lo strumento MCP `myrmm_list_scripts` accetta gli stessi parametri `tag` e `q`.
- **Come sono stati provati.** Tre livelli. (1) Statico, `ci/library_test.py`: intestazione, variabili, etichette, citazioni dei segnaposto, parser PowerShell 7 e controllo di compatibilità con PowerShell 5.1. (2) Comportamento, in locale: `ci/library_unix_test.py` esegue gli script sh in una radice finta con comandi simulati (Linux e macOS, bash e dash, valori ostili, date limite) e `ci/library_win_test.py` esegue quelli PowerShell con i cmdlet di Windows simulati (casi limite, rifiuti, anteprima e applicazione, nomi protetti, valori ostili). (3) Su sistemi veri, con un ramo temporaneo del repository pubblico: ogni script di sola lettura o con anteprima gira su Linux (Ubuntu), macOS (Apple e Intel) e Windows Server 2022 e 2025 con Windows PowerShell 5.1 (`ci/export_library.py` + `ci/library_run.py`), e 14 scenari «con modifiche» (robocopy e specchio, zip, eliminazione file, registro, variabili, firewall, servizi, processi, utenti e gruppi, hosts, tar.gz, blocco account, quarantena) cambiano davvero lo stato e verificano il risultato con comandi nativi (`ci/apply_scenarios.py`, `ci/export_apply.py`, `ci/library_apply.py`). Il test eseguito su sistemi veri ha trovato un nome di prova non valido e un caso lento ("cartelle più grandi" su tutto C:), già corretti.
- **Agent Windows.** Ogni script PowerShell parte ora con l'output in UTF-8: prima le lettere accentate potevano arrivare nella tabella codici OEM del computer (850) e comparire sbagliate nei risultati.

## 8.55 Altri script dal confronto con ComStore e CyberDrain (1.56.0)

La libreria passa da 323 a **341 script**. I nuovi vengono dal confronto con l'elenco dei componenti ComStore di Datto RMM (e dai componenti CyberDrain che vi compaiono): sono stati presi solo quelli generici, non gli installer di programmi di terzi né le integrazioni con servizi esterni. Le convenzioni sono quelle di §8.54 (etichette, anteprima con `APPLICA=si`, monitor con `MYRMM_METRIC`, uscita 2 = variabile non valida, 3 = sistema o privilegi sbagliati).

- **Windows (13).** *Software di controllo remoto non autorizzato* (AnyDesk, TeamViewer, ScreenConnect, RustDesk, VNC e altri trenta circa; `AMMESSI` elenca quelli leciti); *certificati Secure Boot 2023* (Windows UEFI CA 2023 nel database db); *file canarino anti-ransomware* (crea, controlla, rimuovi); *salva/ripristina i permessi NTFS* (icacls); *blocca la versione feature* di Windows Update (TargetReleaseVersion); *blocca o consenti i dischi USB*; *opzioni di sistema* (percorsi lunghi, blocco per inattività, CTRL+ALT+CANC); *disattiva suggerimenti, widget, notizie e Chat*; *IPv6 sulle schede*; *registrazione PowerShell* (Script Block e Module Logging); *versione e criteri di PowerShell*; *build e fine del supporto Microsoft* (tabella interna: verifica sempre su learn.microsoft.com); *idoneità a Windows 11* (TPM 2.0, Secure Boot, RAM, disco, processore; l'elenco dei processori supportati non è verificato).
- **Linux/macOS (5).** *Salute della batteria* (usura e cicli, soglie `SOGLIA_USURA` e `SOGLIA_CICLI`); *stato SMART dei dischi* (diskutil o smartctl); *software presente o assente* (`MODO`); *riavvio programmato con avviso* agli utenti (anteprima di default, `AZIONE=annulla`); *ClamAV* (installazione, età del database, demone).
- **Come sono stati provati.** Gli stessi tre livelli di §8.54: controllo statico, comportamento in locale con comandi finti (Windows su PowerShell 7 con cmdlet simulati; Linux/macOS in una radice isolata, con bash e dash) e prova su sistemi veri (Ubuntu, macOS Apple e Intel, Windows 2022 e 2025).

## 8.56 Scelta degli script e pagina Script ridisegnate (1.57.0)

La selezione degli script da lanciare su un device era confusa: un menu a tendina, un blocco di variabili e due pulsanti sullo stesso piano. Ora ha **due zone**:

- **Elenco con ricerca e menu Etichette** (scheda Lavori del device). Ogni riga mostra solo il **titolo** e il rischio (pallino + parola); un clic sul titolo (▸) apre la **descrizione** e le etichette dello script, un secondo clic la richiude. La ricerca guarda il **titolo o il testo della descrizione**; se una riga corrisponde solo per la descrizione si apre da sola, così si vede perché è comparsa; `%` limita la ricerca al titolo (jolly). Le **etichette** stanno in un menu «Etichette ▾» a scelta multipla (caselle, con i conteggi): dentro lo stesso gruppo (Tipo, Rischio, Area, Insieme) basta una delle scelte, fra gruppi servono tutte. Le scelte compaiono come chip sotto la ricerca e si tolgono con un clic; Esc chiude il menu; «Azzera filtri» le toglie tutte. «Aggiungi» mette lo script in coda, Invio aggiunge il primo risultato. Si vedono 40 righe alla volta («Mostra altri»).
- **Pannello «Attività» a scomparsa a destra.** Si apre da solo alla prima aggiunta; contiene i passaggi in sequenza (variabili del passaggio, attese, riordino, rimozione), il caricamento di un runbook, «Ferma alla prima che fallisce», il tempo massimo e «Salva come runbook». Un solo pulsante di invio: «Esegui ora» con un passaggio (usa `runscript`), «Esegui N attività» con più (usa `runseq`). La coda sopravvive al cambio di scheda (sessionStorage per device). Esc o × lo chiudono; sotto 1280 px copre la pagina, sopra sposta il contenuto.
- **Pagina Script** con lo stesso linguaggio: ricerca per titolo o descrizione, menu Etichette, tabella con titolo (la descrizione e le etichette si aprono con un clic), piattaforma, rischio, variabili (con la guida nel suggerimento), timeout e azioni «Esegui…» / «Modifica»; «Nuovo script» in un blocco richiudibile e la modifica in una scheda in alto. Il vecchio pulsante «+ Nuovo script» è tolto: c'è già «+ Aggiungi».
- **Traduzioni.** Le 203 descrizioni di script che mancavano sono ora in `server/lang/en.json` (le chiavi con numeri usano `{n}`, come per le altre stringhe).

## 8.57 Azioni di massa unificate, viste condivise e «+ Aggiungi» (1.58.0)

Gestire un parco macchine vuol dire fare la stessa cosa su molti device in pochi clic, sapendo cosa succederà a quelli spenti.

- **Un solo menu «Azioni»** nell'elenco Device (operatore). Con la selezione attiva elenca, in sezioni: **Subito** (inventario completo, scansiona patch, applica patch, aggiorna agent), **Esegui** (script o sequenza…, runbook…), **Diagnostica rapida** (informazioni sistema, ultimi errori ed eventi, processi, connettività, porte, sessioni, a seconda della piattaforma), **Report** (CSV, Excel, PDF dei tre elenchi) e **Organizza** (reparto, cliente, campi personalizzati). Ha una casella di ricerca, «Seleziona i visibili» e il conteggio dei selezionati sul pulsante. Prende il posto del blocco script separato, del menu Esporta e di «+ Nuovo».
- **Riepilogo prima di ogni azione di massa.** Una finestra dice quanti device sono **online ora**, quanti **offline da meno di 3 giorni** (probabilmente spenti), **da più di 3 giorni** (forse dismessi), **mai collegati**, e quanti **non adatti** alla piattaforma dello script. Per quelli spenti si sceglie: **Metti in coda** (il job resta `pending` e parte al primo contatto; per gli script si imposta anche dopo quanto scade: mai, 1 h, 4 h, 12 h, 24 h, 3 giorni, 7 giorni) oppure **Salta i device offline** (il server li scarta davvero e il messaggio finale dice quanti ne ha saltati).
- **Pannello «Esegui su N device».** Lo stesso selettore degli script della scheda del device (ricerca per titolo o descrizione, menu Etichette, coda dei passaggi con variabili, attese e «si ferma al primo errore»), in un cassetto a destra con la coda a fianco; parte già filtrato sulla piattaforma dei device scelti. Con un passaggio usa `bulkrun` (anche ripetizione e monitor, solo admin), con più passaggi la nuova `bulkseq`: ogni device riceve solo i passaggi adatti al suo sistema. Le diagnostiche rapide aprono il pannello con lo script già pronto.
- **Viste.** Il menu **Viste** salva cliente, ricerca, stato, software e filtro salvato dell'elenco Device. Le viste sono **condivise con tutti per impostazione predefinita**; con «solo per me» restano personali. Una vista condivisa si può **nascondere dal proprio menu** senza toglierla agli altri (si ritrova in «Viste che hai nascosto»); la elimina chi l'ha creata o un admin. Sono distinte dai *filtri salvati* (gruppi dinamici per criteri, solo admin).
- **«+ Aggiungi» rinnovato.** Si apre con una casella di ricerca già attiva («stampante», «cliente», «ticket»…); in cima la voce **di questa pagina** (il tasto `n` la apre subito) e gli **usati di recente**; poi le voci per gruppo (Device e apparati, Persone e clienti, Lavoro) con una riga di spiegazione, compresi i tipi di apparato senza agent e i comandi di installazione dell'agent. Si scorre con ↑↓, Invio apre, Esc chiude. «+ Nuovo» dell'elenco Device è tolto.
- **API.** `POST ?action=bulkseq` (`ids[]`, passi come in `runseq`, `offline=skip|queue`, `ttl`), `view_save` / `view_del` / `view_hide`; tutte le azioni di massa accettano `offline=skip`. La scansione patch di massa ora legge `ids[]` (prima agiva solo su `device_id`).

## 8.58 Scheda device: un solo menu «Azioni» (1.59.0)

La testata della scheda device ha ora lo stesso menu «Azioni» dell'elenco, al posto di «Report», di «Altre azioni» e dei pulsanti sparsi nella Panoramica. Sezioni: **Subito** (inventario completo, scansiona e applica patch, aggiorna agent), **Esegui** (script o sequenza, runbook, comando libero: portano alla scheda *Script e job* con il campo giusto già attivo), **Diagnostica rapida** (parte subito e mostra l'esito in *Azioni rapide*), **Alimentazione** (riavvia o spegni tra 5 minuti, annulla il programmato), **Manutenzione** (1 h, 4 h, 24 h, termina), **Strumenti** (Task manager, Servizi, File manager, a seconda dei permessi) e **Report** (PDF, Excel, CSV). Ha una casella di ricerca.

Anche qui c'è il **riepilogo prima di agire**, ma solo quando serve: se il device è **offline** dice che l'azione resta in coda (per gli script e il riavvio si sceglie dopo quanto scade) e chiede conferma; le azioni distruttive (riavvio, spegnimento, applica patch) mostrano sempre la finestra con il testo di conferma; le azioni normali su un device online partono con un clic. La logica del riepilogo è un modulo unico condiviso con l'elenco Device.

## 8.59 Coerenza tra le pagine e menu laterale riordinato (1.60.0)

- **Menu a sinistra in gruppi**: in alto, sempre visibili, *Dashboard* e *Da fare*; poi *Parco macchine* (Device, Asset, Rete, Backup, Scadenze, Filtri), *Assistenza* (Alert, Ticket, Chat, Documenti), *Automazione* (Script, Runbook, Check, Regole, Pacchetti, Patch, Attività, Manutenzione), *Report e audit*, *Amministrazione*. I gruppi sono comprimibili; restano aperti Parco macchine, Assistenza e quello della pagina corrente.
- **Creazione = pulsante primario in testata**: nelle pagine a schede (check, regole, utenti, variabili, campi, script, manutenzione, scadenze, patch, filtri, pacchetti) e nelle altre con «+ Nuovo…» (ticket, Rete…) la sezione di creazione non occupa più una scheda: compare «+ Nuovo…» in alto a destra; il modulo si apre al posto dell'elenco con «← Torna all'elenco». `#new` nell'indirizzo lo apre direttamente.
- **Filtri dal vivo**: i moduli di filtro (GET) non hanno più «Filtra»: selezioni, caselle e date applicano subito, i campi di testo dopo 550 ms dalla digitazione, mantenendo il fuoco.
- Pagine con una sola scheda residua non mostrano più la colonna delle schede.

## 8.60 Proattività dei pacchetti: diagnosi e risolutivi (1.61.0)

- **Un solo pacchetto, tre livelli** scelti all'applicazione (e modificabili dopo, per ambito con «Imposta» o per singola regola con «modifica» in *Regole*): *solo monitoraggio* (avvisa e basta), *monitoraggio + risolutivi proposti* (la diagnosi parte da sola, il risolutivo si lancia con un clic dal ticket), *monitoraggio + risolutivi automatici*. Le regole senza livello restano «classiche» (rimedio a ogni alert).
- **Diagnosi e risolutivo per voce**: ogni controllo del pacchetto ha una diagnosi (sola lettura, parte sempre) e un risolutivo con classe **sicuro** (es. spooler di stampa, file temporanei, servizi fermi, orologio, reset Windows Update) o **a rischio**. Un risolutivo a rischio resta sempre *proposto*, anche con livello automatico.
- **Osservazione per cliente**: in *Clienti → Proattività* si imposta un periodo (giorni dall'applicazione o data); finché dura i risolutivi automatici restano proposti.
- **Ticket sempre**: ogni alert di un monitor con livello attivo apre un ticket con l'esito della diagnosi; se l'alert rientra il ticket si chiude da solo. Il risolutivo automatico ha al massimo 2 tentativi in 24 ore; poi la priorità del ticket sale (escalation).
- **Soglia disco graduata**: lo spazio libero è confrontato con la percentuale limitata tra un minimo e un massimo in GB (`DISK_MIN_GB`=5, `DISK_MAX_GB`=100): 10% di 4 TB non pretende 400 GB, 10% di 60 GB non scende sotto 5 GB. Vale per il controllo integrato e per i monitor Windows/Linux (variabili SOGLIA_PERC, SOGLIA_GB_MIN, SOGLIA_GB_MAX).
- **Libreria**: nuovo Tipo `risolutivo` e 7 script (spooler, temporanei, servizi fermi, orologio, diagnosi servizi, diagnosi Windows Update, systemd Linux); al primo avvio i pacchetti base/Server/postazione ricevono Windows Update fallito e Spooler con i risolutivi abbinati.

## 8.61 Menu «Azioni» negli elenchi e menu laterale riordinato (1.62.0)

- **Un solo schema per agire su più righe**: Script, Attività, Alert, Ticket e Asset hanno una colonna di caselle (con «seleziona tutte») e un menu **Azioni** in testata, come l'elenco device. Le voci si attivano secondo quante righe hai spuntato (es. «Esegui su device…» e «Modifica…» solo con una riga), prima di ogni azione compare il riepilogo con l'elenco delle righe e l'eventuale scelta (priorità, operatore, durata del posticipo). Nessun pulsante per riga: i contenuti delle tabelle restano solo dati.
- **Cosa c'è nei menu**: *Script* — Esegui, Modifica, Elimina (admin). *Attività* — seleziona i job in coda, interrompi, forza chiusura. *Alert* — prendi in carico, assegna, posticipa/riattiva, chiudi a mano. *Ticket* — cambia stato, cambia priorità, assegna. *Asset* — stampa etichette QR, elimina (admin, finiscono nel cestino). Le azioni di massa passano da un'unica azione server (`?action=bulk`), con le stesse regole di perimetro delle azioni singole: ciò che è fuori perimetro o già nello stato voluto viene saltato e conteggiato nel messaggio.
- **Alert a schede orizzontali**: Da gestire, Miei, Non assegnati, Per operatore, Posticipati, Risolti (con contatori); si vede una scheda alla volta, quindi la selezione non conta mai due volte lo stesso alert.
- **Esporta sempre in testata**, accanto ad Azioni: Alert, Attività, Asset, Scadenze e (nuovo) Ticket con i filtri attivi.
- **Menu laterale**: il gruppo «Automazione» è diviso in **Libreria** (Script, Runbook, Pacchetti: ciò che si scrive e si riusa) e **Automazione** (Regole, Check, Patch, Attività, Manutenzione: ciò che gira o ha girato).

## 8.62 Screenshot e immagini nella chat (1.63.0)

- **Dall'utente all'assistenza.** Nella finestra «Assistenza» (tray) due pulsanti sopra la casella di testo e una voce nel menu dell'icona: **Screenshot** (nasconde la finestra della chat e apre lo strumento di cattura di Windows, `ms-screenclip:`: l'utente sceglie area, finestra o schermo intero; su Windows senza lo strumento si usa Stampa), **Allega immagine…** (PNG, JPEG, GIF, BMP) e **Ctrl+V** con un'immagine negli appunti. **Nulla parte senza consenso**: compare sempre un'anteprima a tutto schermo con l'avviso di controllare password e dati riservati, un messaggio facoltativo e i pulsanti *Invia*, *Annulla* e (per lo screenshot) *Rifai tra 3 secondi*. La tray invia l'immagine come PNG all'agent, che la riduce (lato lungo 1600 px, JPEG) per stare sotto 1,5 MB: nello script non c'è né cattura dello schermo né codifica JPEG, perché Microsoft Defender segnala come `HackTool:PowerShell/EmpireGetScreenshot` gli script che lo fanno (successo con la 1.63.0: `tray.ps1` finiva in quarantena e l'icona spariva).
- **Dall'assistenza all'utente.** Nel composer della console: **Allega immagine** (o incolla con Ctrl+V, o trascina nella conversazione), anteprima con ✕ prima dell'invio, testo facoltativo. L'agent scarica l'immagine con la chiave del device e la tray la mostra come miniatura con «[ingrandisci]».
- **Chiedere uno screenshot.** Il pulsante **Chiedi uno screenshot** invia all'utente un messaggio (tipo *richiesta di screenshot*) che spiega che vedrà l'anteprima e deciderà se inviare: la console non può catturare lo schermo da sola e l'utente non è mai ripreso senza saperlo.
- **Condivisione.** Cliccando una miniatura nella console si apre l'ingrandimento con **Apri**, **Allega al device** (la copia finisce tra gli Allegati della scheda device) e, se la chat è legata a un ticket, **Allega al ticket**. Se la chat è legata a un ticket, le immagini scambiate (in entrambi i versi) diventano allegati del ticket e il testo una nota; una richiesta aperta dal tray con uno screenshot lo porta direttamente nel nuovo ticket. I ticket hanno ora il riquadro **Allegati**.
- **Sicurezza.** Il tipo dell'immagine si verifica sui primi byte (PNG, JPEG, GIF, WebP) lato agent e lato server, mai dall'estensione o dal tipo dichiarato; massimo 1,5 MB dopo la riduzione (PNG grezzo dalla tray fino a 14 MB) e 4 MB dalla console. I file stanno nella cartella protetta degli allegati con nome casuale (`ci` + 32 esadecimali) e si leggono solo da una sessione di console con il device nel proprio perimetro (`?action=chat_img`, risposta con `nosniff` e `sandbox`) o dal device interessato per le sole immagini dell'assistenza (`?action=chat_img_dev`). Sul PC stanno in `chatimg\` (permessi 0600). Se il server rifiuta un'immagine, dopo 3 tentativi l'agent rinuncia (il messaggio risulta «non inviata»), così un invio anomalo non blocca gli heartbeat.
- **Conservazione.** Le immagini della chat si tengono **30 giorni** (server e PC): poi il file sparisce e il messaggio resta con la dicitura «immagine scaduta»; le copie allegate a device e ticket restano finché non le elimini. Eliminando un device si cancellano anche le sue immagini e gli allegati dei suoi ticket.
- **Limiti noti.** Con la 1.63.0 Defender può aver messo in quarantena `tray.ps1`: dopo l'aggiornamento alla 1.63.1 ripristina l'elemento o lascia che l'agent riscriva il file (cambia l'hash dello script). WebP dal disco non è leggibile dalla tray sulle versioni di Windows senza il codec. Test: `ci/chat_img_test.py` (46 verifiche: agent→server, console, sicurezza dei nomi, ticket, conservazione) e `agent/chat_img_test.go`.

## 8.63 Tray nativa in Go e tunnel «un clic» (1.64.0, rifinita nella 1.65.0)

- **Un'unica tray, in Go.** Dalla 1.65.0 la versione PowerShell non esiste più. La tray è nativa (user32, shell32, RichEdit): nessuno script, quindi niente falsi positivi AMSI. Icona, finestra di chat, notifiche, ticket dalla chat, **screenshot, allegati e miniature** (§8.62). Parla soltanto con l'API locale dell'agent (127.0.0.1, intestazione `X-Myrmm-Tray`). **Dalla 1.67.0 non è più un exe separato né un'attività pianificata: vedi §8.66.**
- **Diagnosi.** Se l'icona non compare: `%TEMP%\myrmm-tray.log` sul PC dell'utente e la sezione «Tray» della diagnostica completa (§14.3). Senza certificato di firma del codice SmartScreen/Defender possono guardare l'exe con sospetto: la prima prova va fatta su un PC pilota.

## 8.64 Riordino della console (1.65.0)

- **Menu laterale con ricerca.** In alto il campo **Cerca nel menu…** filtra le voci e anche le *funzioni* (es. «tunnel», «tray», «task manager», «registro»): ogni funzione porta alla pagina o alla scheda del device dove si trova. Le voci hanno nomi unici e parlanti; i vecchi indirizzi continuano a funzionare. Rinominati: **Chat → Assistenza utenti**, **Check → Soglie**, **Pacchetti → Pacchetti di monitor**, **Operazioni → Registro operazioni**, **Agent → Installa agent**, **Android → Telefoni Android**, **MCP → API e assistente**, **Sistema → Impostazioni**.
- **Assistenza utenti.** Due schede: *Conversazioni* e *Icona sui PC* (elenco dei PC Windows con stato dell'icona, **Attiva/Disattiva** per PC e, per l'amministratore, per tutti). La gestione dell'icona non sta più nel «Controllo remoto» del device.
- **Scheda del device.** Ordine: Panoramica, **Attività** (subito dopo), Salute, Metriche, **Controllo remoto** (sessione, tunnel, RustDesk), **Assistenza utente** (chat e icona di quel PC), Diagnostica e servizi, Hardware e software, Cliente e dati, Agent e accesso. La Panoramica ha i pulsanti di accesso rapido (Esegui uno script, Tunnel, Attività, Assistenza). In **Attività**: prima *In corso e in coda*, poi lo *Storico*; gli strumenti di lancio (script o sequenza, comando libero, schedulazioni) sono tre riquadri chiusi in alto, che si aprono con un clic: niente più scorrimento per arrivare alle attività.
- **Test.** `ci/ui_test.py` (719 verifiche), `ci/devkind_test.py`, `ci/android_test.py`, `ci/bulk_test.py` adattati.

## 8.65 Etichette QR per device e asset, ticket legati agli asset (1.66.0)

- **Etichette QR dei device.** Stesso formato delle etichette degli asset (64×30 mm: QR a sinistra; a destra nome, modello, cliente · reparto, numero di serie, `#id`). Dall'elenco **Device → Azioni → Stampa etichette QR** (sui device spuntati, massimo 200) oppure dalla scheda del device (pulsante **Etichetta QR**). Si apre in una nuova scheda, pronta per la stampa.
- **Il QR non cambia nel tempo.** Alla prima stampa ogni device o asset riceve un **codice permanente** (`d…` per i device, `a…` per gli asset, 10 caratteri) salvato nel database: rinominare, spostare di cliente o ristampare non cambia il QR, quindi le etichette già attaccate restano valide. Il QR contiene `?view=go&l=CODICE`, non l'id. Le etichette asset stampate prima della 1.66.0 puntavano direttamente alla scheda e continuano a funzionare.
- **Cosa succede inquadrando il QR.** Si apre la pagina dell'RMM di quell'oggetto: la scheda del device (con in cima il riquadro **Ticket**) o quella dell'asset. Senza login passa dall'accesso e poi arriva alla scheda. Un codice sconosciuto, o di un oggetto fuori dal perimetro dell'utente, porta all'elenco con un messaggio. Basta il ruolo di tecnico (operatore) per aprire ticket; il lettore vede la scheda e i ticket.
- **Ticket ↔ asset.** Un ticket può essere legato a un **device**, a un **asset** o a entrambi. Se l'asset ha un device collegato, il ticket prende anche quello. L'elenco ticket ha la colonna **Asset** e il filtro `&ast=ID`; la scheda del ticket mostra il link all'asset; la scheda dell'asset ha il riquadro **Ticket** con quelli aperti e l'apertura rapida (titolo + priorità).
- **Apertura rapida dal telefono.** Il riquadro Ticket (titolo, priorità, **Apri ticket**) è pensato per chi arriva dal QR: due tocchi e il ticket nasce già legato a quel device o asset. Il cliente (perimetro) viene dall'oggetto.
- **Test.** `ci/ui_test.py` (+19 verifiche: codici permanenti, redirect, perimetro, creazione ticket da QR, filtro, menu di massa).

## 8.66 Tray dentro l'agent, chat per utente (1.67.0)

- **Perché cambia.** Sui PC la tray non partiva (e le immagini della chat risultavano «non pronte»): la cartella `C:\ProgramData\myrmm` ha permessi solo per SYSTEM e Amministratori, quindi un utente standard non poteva leggere né `tray.json` né `myrmm-tray.exe`, e l'attività pianificata falliva in silenzio. Il vecchio modello (file condivisi + attività pianificata) è stato abbandonato.
- **Un solo eseguibile.** La tray è il sottocomando `myrmm-agent.exe tray`. Il **servizio** la avvia in ogni sessione utente attiva o collegata (WTSQueryUserToken + CreateProcessAsUser, desktop `winsta0\default`, nessuna finestra) passando porta e chiave per **variabili d'ambiente**: non servono file leggibili dall'utente e l'exe è quello di Program Files. La chiave è derivata dalla chiave dell'agent e dall'utente (`sid:HMAC`), si ricalcola dopo un riavvio del servizio e l'agent la collega all'utente tramite WTS.
- **Supervisione.** Ogni 10 s il servizio controlla le sessioni: avvia la tray mancante (attesa di 25 s all'avvio, ripartenza con attese crescenti fino a ~10 min se muore subito), la chiude se la sessione termina, l'utente cambia o la modalità è «nascosta». La tray esce da sola se l'agent cambia versione o non risponde da oltre un minuto; il servizio la rilancia. Alla disinstallazione e all'aggiornamento le tray vengono fermate prima di toccare l'exe. Il vecchio `myrmm-tray.exe`, l'attività `myrmm-tray`, la chiave Run e `tray.json` vengono rimossi al primo avvio.
- **Chat per sessione.** Sui PC con più utenti (RDS, PC condivisi) ogni utente ha **la sua conversazione**: la console mostra le schede degli utenti collegati (e «Tutti» per i messaggi a ogni utente), i messaggi hanno un destinatario, il ticket aperto dalla chat è legato all'utente che l'ha aperto. Un PC con un solo utente funziona come prima; i vecchi agent restano compatibili (conversazione unica).
- **Configuratore.** `myrmm-agent.exe tray-config status|show|hide` mostra o nasconde l'icona senza reinstallare. Si lancia dalla console con lo script di libreria «myrmm tray: stato, mostra o nascondi l'icona (Windows)»: l'agent rileva il cambio, lo comunica al server (`tray_local`) e la scelta compare in console (`tray_mode`).
- **Immagini.** Il download di screenshot e allegati avviene su richiesta della tray; se fallisce, il motivo (HTTP 502 con testo) arriva alla tray e al suo log, e `/state` espone `img_err`.
- **Da verificare su un PC vero** (la parte Windows è provata solo con compilazione, `go vet` e test con supervisore simulato; i test nel repository pubblico girano su Windows): avvio della tray con un utente standard, due utenti contemporanei su RDS, `tray-config hide/show`.

## 8.67 Incarichi AI e connettore MCP remoto (1.68.0)

Schema: **un'AI «superiore»** (per esempio Claude collegato come connettore) scrive un incarico → **l'RMM** lo tiene in coda → **un'AI «locale»** (Claude Desktop, Claude Code o un altro client MCP sul PC) lo prende, lo esegue con gli strumenti già esistenti e riporta → l'AI superiore (e tu, dalla console) leggono l'esito.

- **Coda nell'RMM.** Tabelle `ai_tasks` e `ai_task_events`. Stati: *in attesa di approvazione*, *in coda*, *in corso*, *attende una risposta*, *risposta data*, *concluso*, *fallito*, *annullato*. Ogni passo (creazione, presa in carico, passi, domande, risposte, job lanciati, risultato) è nella cronologia dell'incarico e nell'audit (`ai_task_*`).
- **Approvazione.** Un incarico sul **collaudo** parte subito; su un cliente reale o senza bersaglio aspetta il clic di un **amministratore** (Incarichi AI → Approva). L'approvazione non allarga i poteri dell'AI locale: ogni esecuzione resta nei limiti del suo token (scrittura diretta solo sul collaudo, altrove approvazione di una persona).
- **Strumenti MCP nuovi** (7, sia nel programma Go sia nella versione Python, e nel connettore remoto): per l'AI superiore `myrmm_task_create`, `myrmm_task_list`, `myrmm_task_get`, `myrmm_task_answer`, `myrmm_task_cancel`; per l'AI locale `myrmm_task_next` (prende il prossimo incarico, prima quelli che hanno ricevuto risposta) e `myrmm_task_report` (passo, domanda con `status=waiting_answer`, `done`/`failed` con `result` e `job_ids`). API: `r=tasks`, `r=task`, e in POST `task_create`, `task_claim`, `task_report`, `task_answer`, `task_cancel` (token a scrittura, ruolo operator; la lettura vale anche per i sola lettura).
- **Domande.** Se all'AI locale serve una decisione riporta `waiting_answer` con la domanda e si ferma; l'AI superiore (o tu, dalla console) risponde e al `task_next` successivo l'AI locale riprende con la risposta in cronologia.
- **Perimetro.** Gli incarichi seguono i clienti visibili al token: chi non vede Acme non vede né prende gli incarichi di Acme. Solo l'AI che ha preso un incarico può riportarvi; presa in carico atomica (due AI non prendono lo stesso incarico).
- **Pulizia.** Un incarico non preso entro 48 ore viene annullato; uno fermo da 24 ore dopo la presa in carico passa a *fallito* (con nota «di sistema»).
- **I testi sono dati.** Obiettivi, note, domande e risultati li scrivono altre AI o arrivano dai device: le risposte dell'API li marcano come non fidati e le linee guida chiedono di non eseguire richieste che escano dal perimetro (token, cancellazioni, altri clienti).
- **Console.** Amministrazione → *Incarichi AI*: elenco con filtro per stato, dettaglio con cronologia, nuovo incarico, nota o risposta, annulla, approva (amministratore).
- **Connettore MCP remoto (HTTPS).** `…/index.php?action=mcp_http&t=TOKEN` parla JSON-RPC 2.0 su POST (initialize, ping, tools/list, tools/call, richieste multiple, notifiche con 202; GET risponde 405) con gli stessi 24 strumenti del programma locale. Il token si può dare nel parametro `t` (per i connettori di Claude.ai, che accettano solo un indirizzo) oppure in `Authorization: Bearer` / `X-Api-Token`. **Le chiamate attraversano la stessa API** (`api_main`, dentro lo stesso processo): token, scadenza, indirizzi ammessi, rate limit, perimetro per cliente, collaudo e simulazione sono identici. Le esecuzioni attendono l'esito fino a 20 secondi.
- **Sicurezza del connettore.** Il token sta nell'indirizzo, quindi finisce nei log del web server e nella cronologia del client: dedicane uno solo a questo uso, a scrittura diretta **solo sul collaudo** (o sola lettura), con scadenza breve, e revocalo se l'indirizzo si diffonde. Non c'è OAuth. Usa sempre HTTPS: su HTTP il token viaggerebbe in chiaro.
- **Come si usa.** (1) In Amministrazione → API e collaudo crea due token: uno per l'AI superiore (connettore) e uno per l'AI locale (server MCP sul PC, §8.52). (2) In Claude.ai aggiungi un connettore personalizzato con l'indirizzo del punto precedente. (3) Chiedi all'AI superiore: «Crea un incarico per il PC di Collaudo: …». (4) Sul PC, in una chat di Claude Desktop con l'MCP myrmm: «Prendi il prossimo incarico e eseguilo». (5) L'AI superiore legge il risultato con `myrmm_task_get`.
- **Limiti.** Un'AI locale lavora solo quando c'è una chat aperta: non si «sveglia» da sola quando arriva un incarico (serve un programma di polling, non incluso). Il connettore non è stato provato con Claude.ai vero, solo con client JSON-RPC di prova.
- **Test.** `ci/ai_tasks_test.py` (74 controlli: ciclo completo, approvazione, perimetro, cronologia, audit, console, connettore remoto) e `ci/mcp_go_parity_test.py` (24 strumenti uguali a Python).

## 9. Controllo remoto (RustDesk)

Orchestrazione, non un componente proprietario. Due script in libreria:

- **Installa RustDesk (accettazione utente)** — consigliato: nessuna password permanente, **ogni connessione va accettata dall'utente a schermo**
  (`approve-mode = 'click'`). Variabile `DOWNLOAD_URL`. Verifica il comportamento sulla tua versione di RustDesk prima di distribuirlo.
- **Installa RustDesk (controllo remoto)** — accesso unattended con password. **Tutte le variabili sono facoltative** (1.38.1): `DOWNLOAD_URL` vuoto = ultima versione ufficiale da GitHub (se non risponde, una versione fissa nota); `RUSTDESK_PASSWORD` vuota = password casuale di 20 caratteri, cifrata e visibile nella pagina del device; `CONFIG_STRING` = tuo server self-hosted. L'avvio del servizio non interrompe più lo script (`Start-RDService`: reinstalla il servizio se manca, riprova, ripiega su `sc.exe`). Le password indicate a mano non devono contenere apostrofi. Usalo solo dove serve davvero e con il consenso del cliente.

- **Linux/macOS: installa RustDesk (accettazione utente / controllo remoto)** (1.37.1) — stesse due modalità per Linux (pacchetto `.deb` o `.rpm`) e macOS (`.dmg`): variabile `DOWNLOAD_URL` con il pacchetto adatto al sistema, più `RUSTDESK_PASSWORD` e `CONFIG_STRING` come sopra; anche qui tutto facoltativo (URL vuoto = ultima versione ufficiale per il sistema, password vuota = casuale). Richiedono root; su macOS vanno poi concessi a RustDesk Registrazione schermo e Accessibilità.

Lo stdout `RUSTDESK_ID=…` viene catturato e mostrato nella pagina device con il link **connetti** (`rustdesk://`). Un relay privato (hbbs/hbbr) richiede una VPS; senza, RustDesk usa i server pubblici.

## 11. Aggiornamento dell'agent

1. Incrementa **insieme** `AgentVersion` (agent/main.go) e `APP_VERSION` (server/index.php).
2. `./release.sh`: compila le cinque piattaforme e prepara `server/update/` (`agent.exe`, `agent-linux-*`, `agent-darwin-*`, `version.txt`, `.htaccess` che nega l'accesso diretto). Basta anche una sola piattaforma: le altre non ricevono update.
3. Carica `index.php` e la cartella `update/` sul server.
4. Al heartbeat successivo ogni agent con versione diversa scarica da `?action=agent_bin&plat=<os/arch>` il binario della propria piattaforma, verifica **SHA-256 e firma HMAC**, sostituisce l'exe
   (copia `.old`, rollback se fallisce) e riavvia il servizio. Dopo un errore (rete, server in aggiornamento, download troncato) riprova dopo 1, 2, 5, 10, 30 e infine ogni 60 minuti, e riparte da zero appena il server pubblica un'altra versione (dalla 1.26.1; prima era un solo tentativo all'ora e un riavvio manuale del servizio era l'unico modo per ritentare subito). Se il file è già sostituito ma il servizio non si è riavviato, l'heartbeat ritenta il riavvio ogni minuto con metodi sempre più decisi (`Restart-Service`, poi `sc.exe stop/start` e uscita del processo) senza riscaricare il binario. Senza `job_signing_key` l'update è rifiutato.
5. La pagina *deploy* mostra la versione pubblicata e segnala se è diversa da quella del server. Rollback = ripubblica l'exe precedente.

Gli agent **precedenti alla 0.6.0** non sanno aggiornarsi: il primo passaggio è manuale (strumento di distribuzione o job di deploy).

## 12. Sicurezza

- **HTTPS obbligatorio**: api_key e job viaggiano in chiaro altrimenti. Gli script girano come **SYSTEM**: chi controlla il server controlla i client.
- La firma dei job protegge da MITM e manomissioni in transito, **non** da un server compromesso (il server è la root of trust). Tieni `JOB_SIGNING_KEY` e le credenziali admin robuste e ruotale dopo il collaudo.
- **Accesso console (dalla 1.5.0)**: form di login con sessione (cookie `myrmm_s`, HttpOnly, SameSite=Strict, Secure su https; nel DB è salvato solo l'hash del token). Scadenza per inattività `SESSION_IDLE_MIN` (480 min), massimo 7 giorni. Il basic auth è stato rimosso nella 1.6.1: ogni accesso passa dal form (e dal 2FA, se attivo).
- **Password admin integrata**: `CONSOLE_PASS` in `config.php` è sempre un hash bcrypt; si cambia dal *Profilo*, che riscrive `config.php`. Il 2FA dell'admin integrato si attiva dal Profilo (`CONSOLE_TOTP_SECRET`). Il file deve essere scrivibile dal web server.
- **Accesso a due passaggi (dalla 1.15.0)**: la pagina di accesso chiede solo utente e password; il campo del codice compare in un secondo passaggio **solo se l'account ha il 2FA attivo** (admin integrato con `CONSOLE_TOTP_SECRET` compreso). Il passaggio è legato alla password appena verificata da un token firmato che scade in 5 minuti; con password errata non si capisce se l'account ha il 2FA, e i codici sbagliati contano nel blocco IP.
- **2FA per gli utenti**: pagina *Profilo* → attiva TOTP (Google Authenticator, Aegis, 1Password…); l'admin può azzerarlo da *Utenti*. Gli utenti creati dall'admin devono cambiare la password al primo accesso. "Chiudi le altre sessioni" nel profilo.
- **Limite IP**: `CONSOLE_ALLOW = ['203.0.113.7', '10.0.0.0/8']` limita la sola console; gli endpoint degli agent restano raggiungibili.
- Blocco IP dopo troppi login falliti, anti-CSRF (Origin/Referer + SameSite), header CSP / X-Frame-Options / nosniff, audit di login, 2FA, backup, revoche.
- **Revoca device**: dalla pagina del device (admin) la chiave viene rifiutata subito (403) e si può ripristinare; "Elimina" cancella device e storico.
- **Token di arruolamento per site** (*Deploy*): un token `st-…` per cliente; il device arruolato con quel token finisce nel site del token, qualunque cosa dica l'agent. Si può sospendere/eliminare un token senza toccare gli agent già arruolati. `ENROLL_GLOBAL = false` disabilita il token globale.
- La pagina *Deploy* espone enroll token e chiave di firma: solo admin.
- Il DB contiene le api_key dei device: fuori dal webroot o negato dal `.htaccess`.

## 13. Manutenzione e backup

- **Due file di dati (dalla 1.26.0)**: la documentazione (documenti, versioni, modelli, import) sta in `docs.sqlite`, accanto a `myrmm.sqlite` (e a `metrics.sqlite`). Una **copia a mano del solo `myrmm.sqlite` non contiene più i documenti**: copia entrambi i file. I backup integrati invece li trattano come un'unica operazione: ogni backup crea `myrmm-<data>-<tipo>.sqlite` **e** `myrmm-<data>-<tipo>.docs.sqlite` con lo stesso istante, la rotazione e l'eliminazione li tolgono insieme, *Ripristina* li rimette insieme (dopo il controllo `integrity_check` di entrambi e con la copia «prerestore» di entrambi), e nell'elenco compare «+ documenti» con il pulsante *Scarica documenti*. Un backup fatto con la 1.25 o precedente (documenti dentro il file unico) si ripristina normalmente: i documenti vengono riportati in `docs.sqlite` da quel backup. Ticket e asset restano nel database principale.

- **Pulizia automatica** ogni ora (agganciata a un heartbeat): risultati, job completati, audit, alert risolti, patch installate oltre `RETENTION_DAYS`.
- **Backup integrati** (*Sistema*, admin): creazione manuale con download, copia automatica giornaliera, rotazione `BACKUP_KEEP` (7) in `BACKUP_DIR` (con `.htaccess` che nega l'accesso web; spostala fuori dal webroot se puoi). Gli snapshot usano `VACUUM INTO`, coerenti anche a DB in uso.
- **Carica backup**: nel riquadro *Backup del database* scegli un `.sqlite` o `.gz` e premi *Carica backup*. Il file viaggia a blocchi (max 2 MB l'uno), quindi `upload_max_filesize`/`post_max_size` dell'hosting non lo limitano (tetto 1 GB). Prima di salvarlo si controllano intestazione SQLite, `integrity_check` e presenza delle tabelle `devices`/`jobs`/`meta`; compare come `myrmm-…-upload.sqlite` (se ne tengono 20) e si usa con *Ripristina*.
- **Ripristino**: scegli il backup e scrivi `RIPRISTINA`; controllo `integrity_check`, prima viene fatto un backup "prerestore". Se il backup contiene sessioni vecchie, restano valide quelle del backup.
- Scarica ogni tanto un backup fuori dal server: la cartella sullo stesso hosting non protegge da un guasto dell'hosting.
- Gli aggiornamenti dello schema sono automatici: sostituisci `index.php` e ricarica (`config.php` e dati non si toccano).

## 14. Risoluzione problemi

| Sintomo | Causa / rimedio |
|---|---|
| Enroll fallisce con "invalid character 'ï'" | config.json con BOM: riscrivilo con `[IO.File]::WriteAllText` (l'agent ora tollera comunque il BOM) |
| Enroll/login rispondono 429 | blocco IP anti brute-force: attendi `RL_WINDOW_MIN` minuti |
| Agent bloccato dall'EDR | regola di esclusione sul percorso/hash dell'exe |
| Job rifiutato "firma HMAC non valida" | `job_signing_key` dell'agent ≠ `JOB_SIGNING_KEY` del server |
| Update ignorato | manca `job_signing_key`, oppure `version.txt` = versione già installata, oppure ultimo tentativo < 1 ora fa |
| Un job resta "sent" | PC spento o job perso: consegna at-most-once (vedi `JOB_REDELIVER_MIN`); ricrea il job |
| Patch non si installano | device senza policy, fuori finestra, patch non approvate, finestra già consumata oggi, o scansione non ancora eseguita |
| Alert mancanti su un device | è in manutenzione |
| Script con `$url = ''` e errore "Invalid URI" | la variabile `{{…}}` era vuota: impostala in *variabili* (es. `DOWNLOAD_URL` globale) o nel campo dello script. Gli script RustDesk/deploy aggiornati lo segnalano subito; per averli su un DB esistente eliminali dalla libreria e ricarica la pagina (si ricreano) |
| stderr che inizia con `#< CLIXML` | agent < 1.2.1: l'update lo risolve (`-OutputFormat Text`) |

## 14.1 Il device non compare dopo l'installazione

1. Sul PC leggi `C:\ProgramData\myrmm\enroll-status.txt` (Linux `/etc/myrmm/`, macOS `/Library/Application Support/myrmm/`): contiene l'ultimo errore di arruolamento e l'URL usato. L'agent riprova da solo con attesa crescente (15 s … 5 min); a esito positivo il file sparisce. Gli stessi messaggi sono nel Registro eventi (Applicazione, origine `myrmm-agent`) o nel journal.
2. `bad enroll token`: il token nel `config.json` non è un token di cliente (`st-…`) valido e attivo. Con `ENROLL_GLOBAL = false` il token globale non arruola; il segnaposto `TOKEN-DI-SITE` non funziona. Usa i comandi della procedura guidata Clienti.
3. Errore di rete/TLS o `301`: `server_url` deve essere l'URL esatto, in HTTPS, dello script (un redirect http→https o www→non-www trasforma il POST in GET).
4. `heartbeat: HTTP 401 invalid device key`: il device si era arruolato ma il server non ha più quella chiave (database sostituito/ripristinato dopo l'installazione, device eliminato, `DB_PATH` cambiato). Dalla 1.10.2 l'agent si riarruola da solo dopo 3 tentativi; con agent più vecchi cancella `state.json` nella cartella dati e riavvia il servizio.
5. `heartbeat: risposta non valida dal server (HTTP 200, inizia con "<…")`: il server ha risposto con HTML invece che JSON. Dalla 1.10.5 il messaggio riporta l'inizio della risposta (warning PHP, pagina di errore dell'hosting, WAF, proxy). Il server non stampa più warning PHP nell'output (vanno nel log di PHP) e scarta output spurio nelle risposte agli agent; se il messaggio persiste, l'HTML arriva dall'hosting o da un firewall davanti al server.
6. `429`: troppi tentativi falliti dallo stesso IP, attendi qualche minuto.

## 14.2 L'agent non si aggiorna

Guarda nella vista Device la colonna Agent (⚠ con il motivo) o, nella pagina del device, "Ultimo esito update agent" e "Job in esecuzione".
- `job_signing_key non configurata`: il `config.json` dell'agent non ha la chiave (installazione a mano senza `job_signing_key`). Senza chiave l'update è rifiutato per sicurezza: reinstalla con il comando del cliente (Clienti) o aggiungi la chiave di config.php.
- `firma non valida, RIFIUTATO`: la chiave dell'agent è diversa da `JOB_SIGNING_KEY` del server (config.php rigenerato o installazione di un altro server). Reinstalla con il comando del cliente: porta la chiave giusta.
- `update rimandato: job in esecuzione`: l'aggiornamento riavvia il servizio, quindi attende la fine dei job (oltre 20 minuti procede comunque).
- `in attesa: nuovo tentativo alle HH:MM (dopo N errori)`: attese crescenti da 1 a 60 minuti dopo un fallimento; "Aggiorna agent ora" forza subito. `file sostituito, riavvio in corso`: il binario nuovo è già su disco e l'agent sta ritentando il riavvio del servizio.
- Nessuna nota: `update/version.txt` non coincide con i binari, i file non sono stati caricati tutti, o i binari sono stati caricati in modalità ASCII (usa binario/SFTP).
- Rimedio sempre valido: rilancia il comando di installazione del cliente (con `MYRMM_FORCE=1` se l'agent c'è già).

## 14.3 Diagnostica del device (1.13.0)

Tre livelli, dal più rapido al più completo.

1. **Salute del device** (scheda del device): elenco dei problemi visti dal server. Online/offline e da quanto, device revocato o in disinstallazione, versione dell'agent contro quella pubblicata (con la nota dell'agent se l'aggiornamento non riesce), `JOB_SIGNING_KEY` mancante, inventario non raccolto o vecchio, job in attesa da oltre 10 minuti o consegnati da oltre un'ora senza risultato, job falliti nelle ultime 24 ore, spazio disco, sessione utente, icona nella systray mai vista o ferma, messaggi di chat non consegnati.
2. **Diagnostica completa dal PC** (scheda › *Apri diagnostica completa* › *Raccogli diagnostica dal PC*): la console chiede all'agent un rapporto e lo mostra in pagina, scaricabile come testo (il device deve essere online; è un job di sola lettura registrato in Audit e in Attività). Contiene: versione, hash e percorso dell'eseguibile; configurazione con i segreti oscurati e avvisi (es. chiave di firma assente); file della cartella dati; collegamento al server passo per passo (DNS, TCP, TLS e scadenza del certificato, proxy, risposta dell'applicazione, differenza di orologio, heartbeat con la chiave del device); sessioni utente; icona e chat (API locale, `chat.json`); su Windows servizio, processi tray per sessione e utente (e resti delle versioni precedenti), modalità del linguaggio e criteri di esecuzione di PowerShell, Windows Forms, antivirus, AppLocker, permessi della cartella dati, proxy di sistema, orologio, registro eventi dell'agent e dell'Utilità di pianificazione; su Linux/macOS `systemctl`/`journalctl`/`launchctl`.
3. **Sul PC, anche senza console**: `agent.exe diag` (da PowerShell come amministratore; su Linux/macOS `agent diag`). Stampa il rapporto e lo salva come `diag-<host>-<data>.txt` nella cartella dati (`C:\ProgramData\myrmm`). Serve quando l'agent non si collega affatto. L'ultimo controllo invia un heartbeat leggero, che conta come contatto.

## 14.4 Test automatici su Windows (1.13.1)

La cartella `ci/` contiene una suite di integrazione che gira identica su Windows, Linux e macOS: `python ci/run_tests.py --server server --agent <binario> --out out`.
Avvia il server PHP con una configurazione di prova, installa l'agent (come **servizio** su Windows), poi pilota la console come un operatore e verifica:

- login e navigazione di tutte le viste della console, senza errori PHP;
- sintassi di tutti gli script PowerShell di libreria (Windows PowerShell 5.1 e PowerShell 7);
- arruolamento, inventario (incluso stato sessione), job ad hoc, esecuzione degli script di libreria in sola lettura (informazioni, software, utenti, porte, eventi, hotfix, …);
- diagnostica completa dalla console e `agent diag`;
- chat (console → agent → utente e ritorno), API locale con controllo dell'header, supervisore della tray per sessione, chat per utente;
- **auto-aggiornamento** del servizio (con `--newer-agent`) e **disinstallazione** completa: device rimosso, servizio, attività e dati locali cancellati, nessun riarruolamento.

Il crawl `python3 ci/crawl_test.py` (circa 7 minuti; `CRAWL_ONLY=mobile` per il solo giro da telefono) visita ogni pagina e scheda con i tre ruoli e segnala errori PHP/JS, risposte HTTP ≥ 400 e overflow su telefono.

Il test dell'interfaccia `python3 ci/ui_test.py [cartella-screenshot]` (richiede `playwright` e Chromium; Linux/macOS/Windows) prova accesso con e senza 2FA, schede del device, alert unificati, colonne e nuovo device, notifiche (con server finti Telegram/Teams/webhook/SMTP), impostazioni, metriche, tema chiaro/scuro e layout da telefono, e salva gli screenshot.

Il repo di prova GitHub esegue la suite su Windows Server 2022 e 2025 a ogni push (`.github/workflows/windows.yml`) e pubblica il report su un branch `results-<runner>`. Non provano: l'aspetto grafico di icona e finestra di chat (il runner non ha un utente interattivo) e il collegamento con prodotti esterni (DataCore, Zerto, …), che nel runner non esistono.

## 14.5 Prova guidata della distribuzione su Windows (1.36.0)

La logica è provata nei test (script Windows con WMI/SMB simulati; SSH contro un server in-process; cifratura PHP↔Go), ma la prima volta su un PC Windows vero va fatta a mano, in cinque passi:

1. **Prepara un PC di prova** nella stessa LAN di una sonda **Windows** (agent ≥ 1.36.0): firewall con «Condivisione file e stampanti» e «Strumentazione gestione Windows (WMI)» abilitati; account amministratore (se locale: `reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f`).
2. **Fai comparire il PC in Scoperti**: *Rete › Scoperti › Scansiona ora* sulla sua sottorete; deve avere le porte 135/445 aperte.
3. **Prova a vuoto**: seleziona il PC, *Installa agent…*, inserisci l'account e premi *Prova a vuoto*. Esito atteso: «pronto per l'installazione» con sistema, utente, spazio libero e «il PC verso il server: HTTP 200». Se fallisce, il messaggio dice dove (accesso negato, PC non raggiungibile via SMB/WMI, il PC non raggiunge il server).
4. **Installa**: premi *Installa l'agent sui PC selezionati*. Esito atteso entro pochi minuti: «installato e in esecuzione», e il PC compare in *Device* con la sua versione.
5. **Ripeti la prova a vuoto sullo stesso PC**: deve rispondere «già installato». Controlla nel registro di audit che compaiano `net_deploy_dry`, `net_deploy_run` e gli esiti, e **nessuna password**.

## 15. Limiti noti

- Linux/macOS: niente patch management né monitor integrati oltre ai seed; macOS non collaudato su hardware reale. Gli script di installazione PowerShell non sono stati eseguiti su Windows durante lo sviluppo: provali su un PC di prova.
- Nessun controllo remoto proprietario (si orchestra RustDesk). La rete (sonde, SNMP, scoperta, mappa) funziona **con le sonde-agent** nella LAN del cliente, non dal server: niente collector sempre attivo sull'hosting.
- Distribuzione dell'agent dalla sonda: verso Windows solo da una sonda Windows (SMB/WMI); **WinRM** non è incluso (si può installare con SSH o con gli script del §3); nessuna cache locale del binario sulla sonda (ogni PC lo scarica dal server). Account locali Windows: serve `LocalAccountTokenFilterPolicy = 1`. Telnet escluso dai tunnel.
- Mappa di rete: è un'ipotesi; senza LLDP/CDP i collegamenti sono dedotti dalla sottorete IP. SNMP: nessuna trap (si interroga, non si ascolta).
- Priorità alert a 3 livelli (non 5); niente ticket automatici (PSA) né API REST pubblica.
- Finestre di patch senza attraversamento della mezzanotte; le patch di terze parti non sono gestite (solo Windows Update).
- Variabili degli script: dalla 1.54.2 la sostituzione protegge il valore secondo il punto in cui sta (§8.53); resta all'autore dello script scrivere i placeholder dentro apici o virgolette, e uno script PowerShell molto insolito (stringhe costruite a pezzi) può sfuggire all'analisi.
- Onboarding: l'installazione di un device non è ancora avviabile con un codice QR; le credenziali Windows/SSH del cliente sono archiviate ma la distribuzione dell'agent (§8.28) continua a chiederle nel modulo.

## 16. File

```
README.md                    questo manuale
THIRD-PARTY-NOTICES.md       licenze delle librerie usate dall'agent
UI-LINEE-GUIDA.md            regole di interfaccia e criteri di usabilità
ci/layout_test.py            verifica della coerenza di layout (ricerca, «+ Aggiungi», barra di selezione, bersagli, scorciatoie)
ci/links_test.py             collegamenti multipli e allegati (apparati, documenti, perimetro, cestino)
ci/brand_test.py             codice dei ticket, marchio personalizzato e diagnostica prestazioni
ci/lang_test.py              lingue: metodo, file e database, importazione/esportazione, raccolta testi
ci/dossier_test.py           dossier di audit (PDF, Excel, ZIP con hash), perimetro e ruoli
ci/report_test.py            report al volo (CSV/Excel/PDF) di device, asset, ticket e clienti, esportazioni degli elenchi, menù delle azioni
ci/clickall_test.py          giro di tutti i clic in 3 modalità (telefono, stretto, largo): grafica e usabilità, senza lanciare script

ci/run_tests.py              suite di integrazione (Windows/Linux/macOS), vedi §14.4
ci/snmpsim/gen.py            apparati SNMP finti (stampante, switch, firewall, UPS, NAS, AP) per i test; richiede `pip install snmpsim-lextudio`
ci/deploy_win_mock.ps1       prova dello script Windows di distribuzione con WMI/SMB simulati
release.sh                   compila l'agent, verifica le versioni, prepara server/update/
server/index.php             server completo (API + console)
agent/fs.go                  operazioni file dell'agent (file manager)
agent/tm.go, tm_unix.go, tm_windows.go   task manager: elenco processi e terminazione
server/.htaccess             blocco *.sqlite*
ci/docs_split_test.py        prova della separazione di docs.sqlite: migrazione, backup e ripristino dei due file
server/update/               agent.exe, agent-{linux,darwin}-{amd64,arm64}, version.txt, .htaccess (auto-update e installer)
agent/probe*.go, oui.go      sonda: controlli, SNMP (gosnmp), scoperta di rete, tabella costruttori
agent/deploy*.go, deploy_win.ps1   distribuzione dell'agent dalla sonda (SSH, PowerShell/WMI, cifratura per la sonda)
agent/main.go, plat_windows.go, plat_unix.go, plat_common.go, go.mod, go.sum, config.example.json
dist/                        binari di tutte le piattaforme (prodotti da release.sh; non serve caricarla)
```

## 17. Cronologia

- **1.68.0** — **Incarichi AI** (coda nell'RMM tra un'AI che scrive e un'AI che esegue, con approvazione fuori dal collaudo, cronologia e audit) e **connettore MCP remoto** HTTPS (§8.67); 7 strumenti MCP nuovi (24 in tutto).
- **1.67.2** — anche il riquadro «Ultime attività» della Panoramica del device mostra il nome dello script (monitor, libreria, ticket, alert) al posto della prima riga di codice; la riga di codice resta, etichettata «Script senza nome», solo per i comandi liberi e per i job registrati prima della 1.67.1.
- **1.67.1** — **tray con DPI corretto**: il processo è «DPI aware» (prima Windows ingrandiva a bitmap la finestra e lo screenshot catturava solo la parte alta a sinistra dello schermo); font e layout seguono la scala dello schermo. **Attività**: i job lanciati da ticket, alert o a mano mostrano il nome dello script (il job ne registra l'id) invece della prima riga di codice; i job già in elenco restano com'erano.
- **1.67.0** — **tray integrata nell'agent** (sottocomando avviato dal servizio in ogni sessione, causa dei mancati avvii: permessi di ProgramData), **chat per utente** sui PC con più utenti, configuratore `tray-config` e script di libreria, immagini su richiesta con motivo dell'errore (§8.66).
- **1.66.1** — lo script di installazione Windows scarica l'agent **compresso** (`install_bin&gz=1`, circa metà dei byte, in cache sul server): stesso binario, stesso controllo SHA-256 dopo la decompressione. Test: `ci/install_gz_test.py` (server di prova) e `ci/gz_fetch_test.py` (Windows PowerShell 5.1 vero, nel repository pubblico).
- **1.66.0** — **etichette QR anche per i device** (stampa di massa dall'elenco, stesso formato degli asset) con **codice permanente** che non cambia mai; il QR apre la scheda dell'RMM (login richiesto); **ticket legati anche agli asset** (colonna e filtro, riquadro Ticket con apertura rapida su device e asset).
- **1.65.3** — script di libreria **«myrmm MCP: collega Claude Desktop (Windows)»**: configura Claude Desktop di un utente per usare il server MCP (senza perdere la sua configurazione e senza il token nel profilo); il messaggio finale dell'installazione lo indica.
- **1.65.2** — tray: **«Allega immagine»** funziona (la finestra di scelta del file andava in panico per il filtro), anteprime che non si riescono a leggere diventano un collegamento «[immagine: clic qui per aprirla]» (si apre col programma di Windows) e il log dice il perché; **avvio all'accesso più sicuro** (chiave Run di sistema oltre all'attività pianificata).
- **1.65.1** — tray: le miniature nella chat si disegnano davvero (RichEdit riservava lo spazio ma non disegnava il PNG: ora bitmap `\dibitmap0`); il test su Windows controlla i pixel.
- **1.65.0** — **riordino della console** (§8.64): menu con ricerca di voci e funzioni, nomi unici (Assistenza utenti, Soglie, Pacchetti di monitor, Registro operazioni, Installa agent, Telefoni Android, API e assistente, Impostazioni), scheda del device con Attività in seconda posizione e strumenti di lancio chiusi, Controllo remoto e Assistenza utente separati; **solo tray in Go** (PowerShell eliminata, §8.63); **tunnel con un clic senza preparazione** (il servizio registra da solo il protocollo).
- **1.64.2** — tray in Go: il ciclo dei messaggi era su un thread diverso da quello della finestra (si bloccava all'avvio, a volte): thread del sistema fissato con `LockOSThread`.
- **1.64.1** — tray in Go: una sola copia (il mutex non veniva riconosciuto), icona riaggiunta se Explorer non è pronto all'accesso o viene riavviato, log di diagnosi in `%TEMP%\myrmm-tray.log`.
- **1.64.0** — **Tray nativa in Go** (`myrmm-tray.exe`, scelta per device dalla console, PowerShell resta il predefinito) e **tunnel «Avvia sul mio PC»** (protocollo `myrmm-tunnel://`) (§8.63).
- **1.63.1** — la tray non cattura più lo schermo da PowerShell (Defender la segnalava come HackTool e la metteva in quarantena): screenshot con lo strumento di Windows, riduzione e compressione nell'agent.
- **1.63.0** — **Screenshot e immagini nella chat**: lo screenshot parte sempre da un'anteprima confermata dall'utente (o su sua scelta: allega, incolla); la console allega, incolla e trascina immagini, chiede uno screenshot e le condivide su device e ticket (nuovo riquadro Allegati nei ticket); verifica del tipo sui byte, conservazione 30 giorni (§8.62).
- **1.62.0** — **Menu «Azioni» negli elenchi** (Script, Attività, Alert, Ticket, Asset) con selezione multipla e riepilogo prima di agire; Alert a schede orizzontali; «Esporta» in testata (nuovo export Ticket); menu laterale: «Libreria» separata da «Automazione» (§8.61).
- **1.61.0** — **Proattività dei pacchetti**: tre livelli (monitoraggio / risolutivi proposti / automatici) per pacchetto, ambito e regola; diagnosi sempre, risolutivi «sicuri» automatici, osservazione per cliente, ticket aperto e chiuso, 2 tentativi poi escalation; soglia disco graduata in GB (§8.60).
- **1.60.0** — **Coerenza tra le pagine**: menu laterale in gruppi (Parco macchine, Assistenza, Automazione, Report e audit, Amministrazione), creazione come pulsante «+ Nuovo…» in testata con «← Torna all'elenco», filtri applicati dal vivo senza «Filtra» (§8.59).
- **1.59.0** — **Scheda device con un solo menu «Azioni»** in testata (subito, esegui, diagnostica rapida, alimentazione, manutenzione, strumenti, report) con ricerca e riepilogo prima di agire quando il device è offline o l'azione è distruttiva; tolti «Altre azioni» e i pulsanti sparsi della Panoramica; il riepilogo diventa un modulo condiviso con l'elenco Device (§8.58).
- **1.58.0** — **Azioni di massa unificate**: un solo menu «Azioni» nell'elenco Device (subito, esegui, diagnostica rapida, report, organizza) con **riepilogo prima di agire** (online/offline, accoda o salta i device spenti, scadenza dei job in coda), pannello «Esegui su N device» con lo stesso selettore degli script e sequenze su più device (`bulkseq`), **viste** condivise di default o personali (nascondibili), **«+ Aggiungi»** con ricerca, voce della pagina corrente, recenti e tastiera (assorbe «+ Nuovo»); scansione patch di massa corretta (§8.57).
- **1.57.1** — **Selezione degli script più leggera**: descrizioni e etichette si aprono con un clic sul titolo (in elenco e nella pagina Script); la ricerca cerca nel titolo o nella descrizione e apre da sola le righe trovate solo per la descrizione; le etichette passano in un menu a scelta multipla con conteggi (stesso gruppo = una qualsiasi, gruppi diversi = tutte), con chip delle scelte; nomi e descrizioni delle etichette tradotti in inglese (§8.56).
- **1.57.0** — **Scelta degli script ridisegnata**: elenco con ricerca e chip di etichetta + pannello «Attività» a scomparsa a destra con i passaggi, le variabili e un solo pulsante di invio; pagina Script omogenea (ricerca, chip con conteggi, righe con descrizione e variabili); traduzione inglese di tutte le descrizioni degli script (§8.56).
- **1.56.0** — **Altri 18 script dal confronto con ComStore/CyberDrain**: Windows (software di controllo remoto non autorizzato, Secure Boot 2023, file canarino, permessi NTFS, versione feature di Windows Update, dischi USB, opzioni di sistema, suggerimenti e widget, IPv6, registrazione PowerShell, versione PowerShell, fine supporto Windows, idoneità a Windows 11) e Linux/macOS (batteria, SMART, software presente/assente, riavvio con avviso, ClamAV); in tutto 341 script (§8.55).
- **1.55.0** — **Libreria script per temi**: 135 script nuovi (Windows 65, macOS 29, Linux 24, Linux/macOS 17), tutti con etichette (Tipo, Rischio, Area, Insieme), filtro per etichetta nella pagina e nell'API/MCP (`tag`, `q`), etichette scelte a mano per i 188 script già presenti (§8.54). Provati su tre livelli, compresi Linux, macOS e Windows veri con modifiche reali. L'agent Windows manda ora l'output in UTF-8. Corretti: la protezione «ultimo amministratore» contava l'Administrator integrato; «cartelle più grandi» è più veloce.
- **1.54.2** — **Variabili degli script a prova di iniezione.** La sostituzione di `{{NOME}}` protegge il valore secondo il punto dello script in cui sta (§8.53): apici e virgolette PowerShell e sh, here-string e here-document, commenti, sottoespressioni; un valore ostile resta un testo. Provato su tutta la libreria (188 script) con valori ostili, con controllo negativo. Trovati dal test e corretti: il lettore deve distinguere il here-string `<<<` di bash dal here-document `<<`. Gli script di installazione e rimozione dell'MCP per Windows sono provati su Windows PowerShell 5.1 vero (Windows Server 2022 e 2025) nel workflow del repository pubblico degli agent: download con hash, sostituzione di un eseguibile in uso, permessi, errori, rimozione (`ci/windows_install_test.py`, server finto `ci/fake_myrmm.py`, script esportati da `ci/export_install_scripts.py`).
- **1.54.1** — manutenzione, nessuna funzione nuova. Console: l'aggiornamento dell'ultimo accesso della sessione non può più dare «database is locked» quando due richieste arrivano insieme (la lettura della sessione restava aperta; ora è chiusa e l'aggiornamento non blocca la richiesta). L'esempio di configurazione dell'agent (`agent/config.example.json`) contiene solo segnaposto (nelle versioni dalla 1.13.0 alla 1.54.0 c'erano un token di arruolamento e una chiave di firma veri: chi li ha usati deve averli cambiati). Nuovo `ci/scan_secrets.py` (con prova `ci/scan_secrets_test.py`): cerca chiavi, token, password assegnate, indirizzi privati e termini riservati in TUTTA la storia di un repository (anche file cancellati e binari) prima di pubblicarlo. Il server MCP in Python usa UTF-8 su stdin/stdout (su Windows la codifica locale rompeva le lettere accentate). I test dell'agent non presuppongono più di girare come root e accettano durate di 0 ms sul loopback (timer di Windows). L'agent e l'MCP sono provati anche su un repository pubblico separato (Ubuntu, Windows 2022/2025, macOS Apple Silicon e Intel) con workflow GitHub Actions.
- **1.54.0** — **Server MCP senza Python.** Riscritto in Go (un eseguibile statico per Windows, Linux e macOS, compilato da `release.sh`): gli script di installazione scaricano il file giusto per sistema e architettura, ne verificano l'hash, lo provano e non installano più Python. Nuovi `--version` e `--check`; nuova risorsa API `r=mcp&os=…&arch=…[&info=1]`. **Correzione di sicurezza:** un valore di variabile su più righe poteva uscire dalla here-string/here-document degli script MCP ed eseguire codice (provato su sh e PowerShell); ora i segnaposto accettano il modificatore `{{NOME|linea}}`, gli script MCP lo usano, e l'API `run` rifiuta i valori con a capo. Corretto anche un difetto del Python (una riga JSON che non è un oggetto fermava il server). Test: `ci/mcp_go_parity_test.py`, `ci/mcp_deploy_test.py` esteso.
- **1.53.1** — correzioni sull'assistente MCP e sull'app Android: lo script Windows non usa più l'installer MSI di Python (dava l'errore 1603) ma un runtime «embeddable» privato, con ricerca di Python più robusta e diagnostica; l'app Android 1.2.1 ricava l'id dall'Android ID (la reinstallazione ritrova lo stesso device, un ripristino di fabbrica lo rende nuovo) ed è firmata con una chiave fissa nei segreti del repo, così gli aggiornamenti si installano sopra.
- **1.53.0** — **Funzioni per tipo di device.** Windows, Linux, macOS, Android e iOS mostrano solo ciò che li riguarda: i telefoni non hanno più patch, servizi, riavvio, script, comandi, schedulazioni, metriche, tunnel, RustDesk, chat e «disinstalla agent» (restano check-in, comandi del telefono, hardware e app); Linux e macOS non mostrano patch Windows né chat (servizi systemd/launchd, riavvio, script e shell restano); la lista device mostra «—» nelle colonne Patch e RustDesk dove non si applicano, e le azioni di gruppo (inventario, aggiorna agent) saltano i telefoni. Prima Android e iOS erano trattati come Windows. **Linee guida e assistente MCP sui device** (§8.52): pagina «Linee guida», script di installazione/rimozione per Windows, Linux e macOS che installano anche Python e la configurazione con il token sui device scelti, mascheramento dei token negli script dei job. **App Android 1.2.0**: invia RAM, uptime, tipo di rete, salute e temperatura della batteria, schermo, architettura, kernel, lingua e fuso, operatore, cifratura, blocco schermo, debug USB, opzioni sviluppatore, segni di root e l'elenco delle app installate (esclusa la parte di sistema), mostrati in «Hardware e software». Test: `ci/devkind_test.py`.
- **1.52.1** — correzione: la scheda dell'APK nella pagina Android compariva solo con Google collegato; ora è sempre visibile, con il QR di scarico in cima. Nuovo pulsante «Scollega Android Enterprise» (rimuove chiave, enterprise, criteri e stato; facoltativamente anche i telefoni importati). Test dei report reso stabile.
- **1.52.0** — **App Android (APK)** per i telefoni senza Android Enterprise: check-in con inventario, comandi blocca schermo e ripristino dalla console con conferma e storico, QR di configurazione, compilazione con GitHub Actions; ricerca delle alternative a Google (quota e DUNS).
- **1.51.0** — **Bozze ed esecuzione inline**: l'assistente crea script nuovi come bozze (solo collaudo, fuori da libreria, regole e pianificazioni), li prova live, tu li promuovi con un clic; testo libero eseguibile solo sul collaudo con audit del testo; pulsante Collaudo nella pagina Clienti; strumenti MCP dedicati; Android: link diretto e riquadro guida per la richiesta della quota dispositivi a Google.
- **1.50.0** — **API e collaudo**: token personali con perimetro per cliente, lettura di device, alert, job, backup e inventario, scrittura solo con approvazione o sui clienti di collaudo (simulazione predefinita, audit per token), server MCP, test con agent Linux reale.
- **1.49.0** — **Controllo dei backup**: abbinamento automatico allo strumento dal software installato, controlli modificabili per ogni strumento (registro eventi, file di log delle ultime ore, registro di sistema, servizio, script), strumenti propri e importabili, pagina Stato/Strumenti/Abbinamenti/Prova, alert su backup fermo o fallito, integrazione nei report, nel punteggio e nel dossier.
- **1.48.0** — **Centro report**: 17 report con punteggio di salute spiegato, previsioni e commento a regole fisse; costruttore con modelli, perimetro per cliente/reparto/filtro; esportazioni PDF, Excel (tabelle, grafici nativi, foglio dati per pivot), Word, PowerPoint, HTML autonomo, CSV, CSV per Power BI, JSON e pacchetto ZIP con SHA-256; pianificazioni (giornaliere, settimanali, mensili, trimestrali, per giorno della settimana), invio con allegati o collegamenti, storico con impronte, collegamenti a scadenza, feed per Excel/Power BI, loghi e referenti per cliente. Agent: raccolta del TPM. Le mail del server accettano allegati.
- **1.47.3** — pagina Android: avviso sulla quota dispositivi di Google, necessaria prima di arruolare il primo telefono.
- **1.47.2** — Android Enterprise: il ritorno da Google non arrivava alla console perché il cookie di sessione è `SameSite=Strict` e non viene inviato su una richiesta partita da un altro sito. Ora il ritorno (`amapi_cb`, protetto da uno stato monouso) conserva solo il token e una pagina di passaggio riporta il browser su `amapi_finish`, che crea l'enterprise con la sessione. Aggiunto il ripiego «Google non mi ha riportato qui» (token incollato a mano). Un'enterprise rifiutata da Google non viene più salvata.
- **1.47.1** — correzione: «Crea enterprise con Google» non faceva nulla perché la CSP della console (`form-action 'self'`) blocca in silenzio il redirect di un form verso Google; ora la console mostra una pagina di passaggio con collegamento. Il test `ci/android_test.py` clicca davvero il pulsante nel browser.
- **1.47.0** — Android Enterprise: telefoni Android aziendali (fully managed) e personali (work profile) con QR di arruolamento, criteri JSON, sincronizzazione di inventario e stato dall'Android Management API, comandi blocca/riavvia/wipe; pagina Piattaforma → Android; test `ci/android_test.py` (§8.46).
- **1.46.0** — telefoni e tablet senza agent: check-in da Comandi iOS, MacroDroid, Tasker, HTTP Shortcuts (`?action=mobile_checkin`) per inventario e stato online, soglia offline propria per telefono, scheda senza azioni da agent, istruzioni nella pagina Installazione, test `ci/mobile_test.py` (§8.45).
- **1.45.1** — traduzioni: ~75 voci in più (da elenco `mancanti` dell'utente); il filtro non si confonde più con `>` dentro gli attributi (avviso «allegato troppo grande» ora tradotto), la pagina Lingue non raccoglie più le proprie chiavi, in lingua diversa dall'italiano non si raccolgono i testi già tradotti, e le etichette con dati (`Ticket #12 · offline: …`) si traducono a pezzi.
- **1.45.0** — **flag «non da tradurre»** nelle traduzioni: casella per voce, filtro dedicato, «segna tutte le voci del filtro», le voci flaggate escono dai mancanti, non vengono più raccolte e l'esportazione JSON ne porta l'elenco (`__non_tradurre__`), che l'importazione ricorda.
- **1.44.1** — la raccolta testi non registra più i corpi degli script (sono codice, non interfaccia).
- **1.44.0** — **console completa in inglese**: filtro di traduzione a blocchi (paragrafi con tag, numeri, attributi, textarea, JavaScript a corrispondenza esatta, etichette con dato), circa 3.300 voci in `en.json`, messaggi, stati vuoti e descrizioni delle variabili degli script tradotti; nuovo test `ci/lang_ui_test.py`.
- **1.43.0** — **prove di sicurezza dall'agent**: antivirus/EDR, BitLocker, firewall, amministratori locali e ultimo backup raccolti con l'inventario, mostrati nella scheda del device e nel dossier di audit (§8.43). Agent 1.43.0 (nuovo, va aggiornato sui PC).
- **1.42.0** — **lingue e dossier di audit**: metodo di traduzione in file JSON + database (italiano e inglese ora, francese e spagnolo pronti), lingua per utente e per cliente; otto documenti PDF per audit (NIS2, ISO 27001, GDPR, AgID, polizze cyber) generati al volo con ZIP e impronte SHA-256 (§8.42). Agent 1.42.0 (solo allineamento versione).
- **1.41.0** — **menù delle azioni e report al volo**: i pulsanti poco usati di device, alert, attività, asset, scadenze, scheda device e report mensile sono raccolti in menù (*Azioni*, *Altre azioni*, *Esporta*, *Report*); dalla scheda di device, asset, ticket e dal report mensile di un cliente si scarica subito un report in PDF, Excel o CSV, e tutti gli elenchi si esportano anche in Excel e PDF (§8.41). Nuovo `ci/report_test.py`.
- **1.40.1** — **il colore del marchio colora tutta l'interfaccia**: scegliendo un colore principale non cambiano più solo pulsanti e link, ma anche le sfumature dei grigi (sfondi, riquadri, bordi, testi) in entrambi i temi, la pagina di accesso e le ombre. Con colore predefinito nulla cambia. I colori di stato (ok, avviso, errore) restano verde, giallo e rosso perché hanno un significato.
- **1.40.0** — **codice dei ticket configurabile** (`T-{YY}{MM}{DD}-{N:4}` e simili, progressivo per giorno/mese/anno, i vecchi codici restano), **marchio personalizzabile** (nome, logo e colore da Sistema; predefiniti invariati), **diagnostica prestazioni** (PHP, OPcache, disco, SQLite, interrogazioni tipiche con suggerimenti). Pulizia dei riferimenti: il pacchetto non include più il confronto con altri RMM, aggiunto `THIRD-PARTY-NOTICES.md`, indirizzi di esempio neutri. Agent 1.40.0 (solo allineamento versione).
- **1.39.1** — **menu laterale a gruppi richiudibili**: ogni gruppo (Panoramica, Operazioni, Piattaforma…) si apre e si chiude con un clic sul titolo; lo stato è ricordato nel browser. Al primo accesso restano aperti il primo gruppo e quello della pagina in cui sei (che si apre sempre da solo, così la voce attiva è visibile). Voci più compatte, barra di scorrimento sottile; utente e «Esci» in fondo al menu.
- **1.39.0** — **collegamenti multipli e allegati**: un apparato può essere collegato a più device; un documento a più clienti, device e apparati (e viene trovato da tutti); allegati (PDF, DOCX, TXT, configurazioni…) su documenti, device e apparati, con limiti, anteprima sicura, perimetro clienti, Audit e Cestino. Sezione 8.39. I vecchi allegati degli asset passano da soli alla nuova tabella.
- **1.38.4** — **usabilità del lancio script** (scheda «Script e job» del device): le variabili dello script stanno ora sopra ai pulsanti «Esegui ora», «Aggiungi alla sequenza» e «Aggiungi attesa», che compaiono subito sotto i campi da compilare e sopra la sequenza. Il giro dei clic (`clickall_test.py`) segnala adesso anche i pulsanti messi sopra ai campi che usano. Controllati gli altri moduli (esecuzione di massa, editor runbook, programmazione): già nell'ordine giusto.
- **1.38.3** — **giro completo dei clic** (`ci/clickall_test.py`, tre modalità: smartphone, desktop stretto, desktop largo; ~1080 clic ciascuna su 52 pagine, senza lanciare script reali). Corretti: il menu a tendina con ricerca (es. selettore script nei runbook) che su smartphone si chiudeva appena compariva la tastiera; menu a tendina che sbordava dallo schermo con finestra bassa; pannelli «Colonne», «+ Aggiungi», selettore clienti e «Ultimi device» tagliati ai bordi dello schermo.
- **1.38.2** — **PC rinominati** (il nome nel portale segue l'hostname, con i nomi precedenti) e **alias** modificabile accanto al nome; **editor dei runbook** nella loro pagina (nuovo, modifica, duplica); **filtro clienti a scelta multipla** e **barra di avviso** quando la scheda aperta è di un cliente fuori filtro (anche dagli ultimi device).
- **1.38.1** — correzioni e comandi manuali: **RustDesk su Windows**: l'avvio del servizio non fa più fallire lo script (nuovo `Start-RDService`: reinstalla il servizio se manca, riprova, ripiega su `sc.exe`), URL e password hanno valori predefiniti (ultima versione ufficiale, password casuale); gli errori PowerShell in formato CLIXML (`#< CLIXML …`) vengono convertiti dal server in testo leggibile nei risultati. **Comandi manuali** con diciture per tipo di device (PowerShell, cmd, shell) e scelta PowerShell/cmd su Windows (sezione 8.37); test PowerShell reali nella CI.
- **1.38.0** — **console riorganizzata** (intestazioni di tabella fisse e affidabili, menu a tendina con ricerca unica, barre strumenti compatte su telefono): «+ Aggiungi» e ricerca/selezione uniformi in tutte le pagine, anteprima laterale, scorciatoie, densità, *Da fare*; **credenziali illimitate per cliente** (SNMP, Windows, SSH) scelte per rete e per apparato, con prova in sequenza e ricordo di quella valida; **onboarding** a nove passi, procedura guidata della rete, aggiungi device, **importazione CSV** con prova a vuoto, sei nuovi **modelli di documento**, **cestino** con «Annulla», conferma digitata per eliminare un cliente, rinomina che propaga ovunque; glossario unico (Cliente/Sede). **Comandi manuali** con diciture per tipo di device (PowerShell, cmd, shell) e scelta PowerShell/cmd su Windows.
- **1.37.1** — **Accesso remoto per Linux e macOS**: script per RustDesk (`.deb`/`.rpm`/`.dmg`, unattended e con accettazione), per abilitare/disabilitare SSH, Condivisione schermo (macOS) e xrdp (Linux), tutti con verifica della porta; l'helper del tunnel ora apre `ssh` (`-ssh`/`-alias`), il client VNC (`-vnc`) e il client RDP anche su macOS e Linux; la scheda del device propone la porta giusta per sistema (§8.4.1). Nuovo test `ci/unix_scripts_test.py`.
- **1.37.0** — **UPS, NAS e access point** con profili SNMP dedicati e avvisi (a batteria, batteria scarica, dischi/RAID, temperatura); **vicini LLDP/CDP** letti da switch, firewall e AP; **mappa di rete ipotetica** per cliente (collegamenti confermati e dedotti, scarico SVG); rete d'esempio nella modalità demo; correzione di una scrittura concorrente sull'uscita delle sessioni SSH.
- **1.36.0** — **installazione dell'agent dalla sonda** sui PC scoperti: Windows (SMB + WMI, da sonda Windows) e Linux/macOS (SSH); credenziali per lotto **cifrate per la sola sonda** (non salvate, oppure conservate cifrate per cliente se abilitato); **prova a vuoto obbligatoria** prima dell'installazione; esiti per PC; prova guidata nel manuale (§14.5).
- **1.35.0** — **scoperta della rete**: scansione per sonda (intervallo e porte configurabili per sonda) con ping, ARP, porte, banner, nome, MAC/costruttore, SNMP e tipo probabile; scheda **Scoperti** con nuovi/censiti/ignorati/spenti e **censimento con un clic** (asset + monitoraggio).
- **1.34.0** — **SNMP v2c/v3** con riconoscimento automatico del profilo (stampante, switch, firewall), credenziali per sottorete cifrate, porte osservate con controllo veloce, **Scansiona apparato** (walk fino a ~4000 voci) e **OID personalizzati** con grafici.
- **1.33.0** — **tunnel verso gli apparati di rete** attraverso la sonda (RDP/SSH/web), con porte consentite per lista e audit.
- **1.32.0** — **rete**: sonde-agent nella LAN del cliente, sottoreti con sonde di priorità e riserva, apparati monitorati con ping e porta TCP, avvisi, grafici del tempo di risposta.
- **1.31.0** — **usabilità**: selezione multipla dei job (In corso / Nessuno / Maiusc+clic) con «Interrompi selezionati» e «Forza chiusura», anche tra device diversi in Attività; annullamenti ed eliminazioni senza ricaricare la pagina (resta la posizione di scorrimento); elenco degli ultimi 12 device aperti nella barra alta; colonne dei job riallineate.
- **1.30.1** — **schermi stretti**: le tabelle larghe stanno in un contenitore con barra di scorrimento, la pagina non esce più dai margini; **asset**: pulsante «+ Nuovo asset» (menu per tipo) in testa alla loro schermata, e «+ Asset per questo device» nella scheda del device, con cliente, reparto e collegamento già compilati.
- **1.30.0** — **modalità demo**: database fittizio condiviso tra gli admin (cartella `demo/`), attivabile per sessione dal profilo; circa 10 clienti, 70 device con inventari e metriche, alert, ticket di ogni canale, runbook, risolutivi, documenti, asset, email da smistare; job chiusi in simulazione; nessuna scrittura sui dati veri e nessuna uscita verso l'esterno; agent e API mai coinvolti; Rigenera ed Elimina.
- **1.29.0** — **email → ticket**: lettura IMAP, mappa domini/indirizzi per cliente, instradamento automatico quando il cliente è certo, **triage** con scelta a un clic (anche con mittente in più clienti), risposte agganciate dal codice o dai riferimenti, risposte pubbliche inviate per email, ticket senza device collegabili in seguito, difese anti-loop e controllo SPF/DKIM/DMARC.
- **1.28.0** — **codice ticket** `T-AAAA-NNNN` e canale di origine; **richiesta di assistenza dal tray** (casella «Apri una richiesta», ticket con la chat legata); note interne/pubbliche con risposta al richiedente nella chat del PC.
- **1.27.0** — **risolutivi legati all'alert** (non al ticket): modi automatico / proposto / manuale, limite per cliente, verifica del rientro con esiti (risolto, senza effetto, fallito) e statistiche per regola; pulsante *Lancia* su ticket e alert.
- **1.26.5** — selettore cliente della barra alta con ricerca (jolly `%`, frecce, Invio); dopo lo spostamento di un device avviso se è citato in documenti di altri clienti.
- **1.26.4** — **spostare un device fra clienti** porta con sé ticket, documenti e asset collegati, rivaluta subito regole e pacchetti e chiude gli alert di monitor non più applicabili; nei form di asset (come nei documenti) il menu device è filtrato dal cliente e il server rifiuta incoerenze; pulizia oraria degli alert di monitor orfani.
- **1.26.3** — **documenti**: editor a due modalità (Markdown / visuale con barra strumenti), corsivo, linea e liste di controllo nel Markdown, menu device filtrato dal cliente scelto (con controllo lato server); **ricerca ovunque**: campo Cerca anche nei menu a gruppi (azioni dei ticket) e filtro righe sulle tabelle lunghe.
- **1.26.2** — **ricerca negli elenchi**: scrivendo nel campo Cerca (script della scheda device, menu a selezione, task manager, servizi, ricerca rapida) l'elenco mostra solo le voci che corrispondono, non più una sola voce con il resto nella tendina; `%` funziona da jolly (`%on%win%` trova «Monitor Windows», «Monitor SolarWinds»…); Invio sceglie la prima voce, Esc annulla la ricerca.
- **1.26.1** — icona nella systray e chat attivabili/disattivabili per device dalla console (scheda del device), niente più avviso allarmante se l'icona non è ancora comparsa; **auto-update più robusto**: attese crescenti dopo un errore invece di un'ora fissa, e nuovi tentativi di riavvio del servizio se il file è già sostituito ma l'agent non si è riavviato.
- **1.26.0** — la documentazione passa in un database separato `docs.sqlite` (migrazione automatica con verifica dei conteggi), backup/ripristino/rotazione di entrambi i file come un'unica operazione, prova di carico estesa a documenti e ticket.
- **1.25.0** — documentale: **9 modelli di serie** con segnaposto (modificabili, aggiornati con le versioni), **revisione periodica** dei documenti, **import** da Markdown/testo/HTML, ZIP e CSV con anteprima, esclusione delle credenziali e annullamento.
- **1.24.0** — **Documentazione**: documenti in Markdown sicuro con versioni, schede cliente e device generate dall'inventario, esporta/stampa, collegamenti a ticket, device e asset, blocco delle credenziali.
- **1.23.0** — **Ticket** integrati: apertura e chiusura automatiche dagli alert, lavorazione (stato, priorità, assegnatario, note e tempo), **azioni script/runbook dal ticket** con esito nel ticket, azioni automatiche per tipo di alert con limite.
- **1.22.0** — **scadenza dei job non consegnati** (opzionale, predefinito «mai»): da 1 ora a 7 giorni, su job singoli, di massa, sequenze, runbook e programmazioni; il job scaduto non viene più consegnato e le sequenze si chiudono.
- **1.21.0** — scheduler: passo **attendi** nelle sequenze, **runbook programmabili** (una volta o a intervalli, su cliente e/o filtro), **calendario** delle esecuzioni, notifica di **sequenza ferma** oltre 6 ore.
- **1.20.0** — **Prova di carico** integrata (Sistema): simula fino a 1000 device e operatori, verdetto, report JSON, benchmark del server. **Correzione**: «database is locked» (HTTP 500) sotto contatti simultanei: cursori chiusi prima delle scritture e transazioni `BEGIN IMMEDIATE` (heartbeat, risultati, metriche).
- **1.19.2** — revisione di bug e usabilità: **telefono** (nessuno scroll orizzontale in nessuna pagina: tabelle scorrevoli, schede laterali, menu e campi che non sforano, barre strumenti che vanno a capo); **annullando il job di una sequenza la sequenza si chiude** (prima restava «in corso»); nuovo test `ci/crawl_test.py` che visita ogni pagina e scheda come admin, operatore, viewer e da telefono cercando errori PHP, errori JS, HTTP ≥ 400 e overflow (esito: nessun errore su desktop nei tre ruoli).
- **1.19.1** — la ricerca globale trova anche gli **script della libreria** («Script · nome»): si apre direttamente «Esegui su…» (ruolo operator).
- **1.19.0** — **cerca in tutti i menu a selezione** con almeno 8 voci (campo «Cerca…» accanto al menu: filtra mentre scrivi, Invio sceglie la prima voce) e **filtri salvati (e runbook) nella ricerca globale** in alto (Ctrl K o «/»): scegliendo un filtro si apre l'elenco device filtrato.
- **1.18.0** — **runbook**: sequenze di script salvate con nome, ricaricabili dal device e avviabili su più device dalla nuova pagina *Runbook*.
- **1.17.0** — scheda device *Script e job*: **etichette e filtro per tipo** (manuale / schedulato / monitor / sistema), **ricerca** nell'elenco degli script da lanciare (solo quelli adatti al device) e **sequenze**: più script uno dopo l'altro, riordinabili, con «fermati al primo errore».
- **1.16.1** — la scheda di Sistema con email/SMTP, Telegram, Teams e webhook si chiama ora «Notifiche: email (SMTP), Telegram, Teams, webhook» (era «Notifiche degli alert», poco trovabile); il report mensile usa lo stesso invio email (SMTP o `mail()`).
- **1.16.0** — pacchetto finale: **metriche** con grafici (scheda *Metriche* del device, database separato `metrics.sqlite` con tre livelli di retention, righe `MYRMM_METRIC` dagli script, monitor della libreria aggiornati); **notifiche** configurabili in Sistema (SMTP con fallback a `mail()`, Telegram con ricerca gruppi, Teams, webhook) con pulsanti di prova; **Impostazioni** grafiche per le chiavi di `config.php`; **Alert** e *In carico* unificati, con presa in carico, passaggio, posticipo e chiusura direttamente nella scheda Alert del device; **colonne inventariali** selezionabili nella lista device e **+ Nuovo** per device-asset (anche SIM); eliminando i job si chiudono gli alert dei monitor falliti; pulsante «Elimina tutti i conclusi» leggibile in entrambi i temi.
- **1.15.2** — **stato della sessione utente sempre aggiornato**: con un tunnel, il file manager o la chat aperti l'agent invia l'inventario completo solo ogni 10 minuti e la scheda mostrava lo stato vecchio (es. «disconnessa» con un RDP già attivo). Ora ogni heartbeat, anche leggero, porta lo stato delle sessioni (`WTSEnumerateSessions`, costo trascurabile) e il server lo fonde nell'inventario.
- **1.15.1** — le pagine a sezioni usano lo stesso schema della scheda device, con le sezioni come **schede a sinistra** (una per volta, ricordata per pagina, `#t=` nell'indirizzo): Sistema, Script, Pacchetti, Profilo, Deploy, Manutenzione, Campi, Utenti, Variabili, Scadenze, Check, Patch, Regole, Filtri. Le liste (Device, Alert, Attività, Audit, Chat, Clienti, Asset) e la dashboard restano a pagina intera. Corretto lo scroll orizzontale della ricerca su telefono.
- **1.15.0** — interfaccia: **colore verde** al posto del blu (tema scuro e chiaro); **nuovo logo** (formica stilizzata) e pagina di accesso rifatta; **accesso a due passaggi**: il campo del codice 2FA compare solo per gli account che lo hanno attivo; **scheda device con schede a sinistra** (Panoramica, Salute e patch, Alert, Accesso remoto, Azioni rapide, Script e job, Hardware e software, Cliente e dati, Agent) con contatori, stato online in testa e striscia di riepilogo; messaggi di esito evidenziati; barra di ricerca adattata al telefono; `ci/ui_test.py`.
- **1.14.1** — tunnel: più connessioni sullo stesso tunnel (con una sola, mstsc mostrava «chiuso dall'operatore» subito dopo l'accettazione del certificato).
- **1.14.0** — **tunnel RDP/SSH/VNC** attraverso il server (§8.4): relay PHP, richiesta firmata all'agent, helper `agent tunnel` sul PC dell'operatore, audit, chiusura automatica. Test end-to-end nella suite `ci/`.
- **1.13.1** — correzioni trovate dai test su Windows reale: la disinstallazione dalla console e il riavvio dopo l'auto-update non eseguivano nulla perché il PowerShell staccato (flag `DETACHED_PROCESS`) usciva subito senza fare niente; ora si usa `CREATE_NO_WINDOW`. Dopo la conferma di disinstallazione l'agent non si riarruola più come nuovo device (file `uninstalling.flag`, con nuovi tentativi di rimozione) e lascia una traccia in `%SystemRoot%\Temp\myrmm-uninstall.log`. Aggiunta la suite di test `ci/` (§14.4).
- **1.13.0** — diagnostica: salute del device, rapporto completo dal PC richiesto dalla console, `agent diag` da riga di comando.
- **1.12.1** — revisione generale: corretta la prima installazione su database nuovo (errore «no such column: site» all'avvio); chat/tray più robuste (installazione dell'icona fuori dal percorso di avvio, niente finestre d'errore, accessi concorrenti protetti).
- **1.12.0** — chat con l'utente collegato e icona nella systray (solo Windows), archiviazione e collegamento agli alert.
- **1.11.1** — sessione utente (stato, utente, ultimo utente, filtri), «Rimuovi e disinstalla agent»; ricerca asset in Ctrl+K ed etichette QR.
- **1.11.0** — asset senza agent (tipi generici precompilati, note, allegati, password cifrate, scadenze, CSV).
- **1.10.18** — alert in carico/assegnazione/tempo/note, vista In carico, sposta device fra clienti, reparti (con token d'installazione), ripristino script del pacchetto.
- **1.10.17** — la libreria script mostra il tag piattaforma (Windows / Linux/macOS / qualsiasi) su tutti gli script; si cambia da «modifica».
- **1.10.16** — controlli sui campi che aprono/chiudono alert (con 8 consigliati).
- **1.10.15** — raccolta inventario: 10 script, 48 campi automatici (BitLocker, TPM, batteria, speedtest…), pacchetti dedicati, pannello Conformità flotta, limite campi 100.
- **1.10.14** — descrizioni estese per tutti i 168 script, intestazione documentata con le variabili nel codice, spiegazioni sotto i campi variabile in tutti i form, convenzione `# @var` per i propri script.
- **1.10.13** — report con grafici e confronto mese precedente, report mensile via email, metriche e grafici in dashboard, fine supporto SO, diagnostica per cliente, pausa script/patch in manutenzione, storico alert nella scheda device.
- **1.10.12** — **Manutenzione** (finestre e immediata), **gestione alert** (in carico, nota, posticipa, chiudi), **report mensile** stampabile per cliente, **Scadenze**, **Dati e pulizia** (conservazione, pulizia, compattazione), **Diagnostica rapida** sulla scheda device.
- **1.10.11** — **Esegui su…** dalla libreria (con anteprima dei bersagli), pagina **Attività** (job di tutta la flotta, export), **Pacchetti di monitor** (6 predefiniti, applicabili per cliente come regole dinamiche), **rinomina/unione clienti**, **dashboard per cliente**, **export CSV** di alert e job. Le regole ora rispettano la piattaforma dello script e non duplicano schedulazioni identiche. Corretto lo script «Windows: rinomina computer» (errore di sintassi PowerShell trovato con il parser di PowerShell 7).
- **1.10.10** — **selettore cliente globale** nella barra alta (filtra dashboard, device, alert, job… sul cliente scelto; si ricorda per 90 giorni; i permessi restano quelli dell'utente e un device di un altro cliente resta apribile da ricerca o link) e **libreria script con ricerca e filtri** (Monitor, Windows, Linux/macOS, registro eventi) con contatore.
- **1.10.9** — **monitor del registro eventi** (≈25 preconfezionati + ricerca libera per log/ID/livello/origine/testo), altri monitor Windows (Hyper-V, cluster, AD, DHCP, IIS, task, URL, DNS…) e Linux (journal, OOM, SMART, RAID/ZFS, Docker, certbot…): libreria a ~170 script.
- **1.10.8** — **upload dei backup dalla console** (a blocchi, aggira i limiti PHP dell'hosting, con verifica di formato/integrità/schema, anche `.gz`) e **libreria script portata a ~100 voci**: ~45 script Windows (info, utenti, sessioni/terminal server, RDP, firewall, SMBv1, pulizia, riparazione Windows Update, DISM/SFC, Defender…), nuovi monitor e ~20 per Linux/macOS.
- **1.10.7** — **script RustDesk più robusti**: verificano il download (dimensione e intestazione eseguibile, errore chiaro se l'URL restituisce una pagina HTML/404), attendono fino a 5 minuti che l'installer — che può terminare subito e completare in background — crei `rustdesk.exe` (cerca anche in Program Files (x86) e nel percorso del servizio) e, se non lo trova, riportano exit code, byte scaricati, privilegi e processi. Gli script della libreria si aggiornano da soli se non li hai modificati; le copie già incollate vanno rilanciate dalla libreria.
- **1.10.6** — **auto-update diagnosticabile e meno fragile**: nella vista Device, accanto alla versione dell'agent in ritardo compare il motivo (⚠: firma non valida, `job_signing_key` mancante, job in esecuzione, un tentativo all'ora…); un job bloccato non rimanda più l'aggiornamento oltre 20 minuti.
- **1.10.5** — **robustezza**: la pagina Servizi verifica la versione dell'agent (≥ 1.10.4) e, se è più vecchio, lo dice e propone l'aggiornamento invece di mandare un job che l'agent eseguirebbe come PowerShell;: nessun warning/notice PHP nell'output (rompeva il JSON verso l'agent con `display_errors` attivo sull'hosting); l'agent segnala stato e inizio della risposta quando non è JSON.
- **1.10.4** — **Servizi**: pagina con l'elenco in tempo reale dei servizi del device e controlli (avvio, arresto, riavvio, tipo di avvio) per Windows, Linux (systemd) e macOS (launchd); richiede agent ≥ 1.10.4.
- **1.10.3** — **reattività**: l'agent si collega ogni 15 s (`wake_seconds`, heartbeat leggero) invece che ogni 60, quindi file manager, task manager e job partono entro ~15 s (prima fino a 60 s); con file o task manager aperti usa un **long-poll** (il server risponde appena c'è un job: operazioni in circa mezzo secondo) e non raccoglie più l'inventario completo ogni minuto, che bloccava l'agent per qualche secondo. Il file manager mostra quanto attende. Più richieste leggere al server: con molte centinaia di device alza `wake_seconds`.
- **1.10.2** — **console**: briciole di pane nelle pagine interne (Device › host › File / Task manager, Clienti › Nuovo cliente; "Device" riporta all'ultimo elenco con site e filtro), il pulsante del menu nasconde/mostra la barra laterale anche su desktop (scelta ricordata), link di ritorno nella modifica filtro. **agent**: se il server non riconosce più la chiave del device (`invalid device key` per 3 heartbeat di fila: database sostituito o ripristinato, device eliminato) l'agent si riarruola da solo con il token del `config.json`. Prima restava bloccato in errore 401.
- **1.10.1** — **Clienti**: oggetto vero (tabella `sites`) con procedura guidata di onboarding (anagrafica → comandi di installazione con attesa live del primo device → riepilogo), presente nei selettori anche prima del primo device; i site già in uso vengono importati. **Agent**: l'arruolamento ora **riprova** con attesa crescente invece di fermarsi al primo errore e scrive il motivo in `enroll-status.txt`; gli script di installazione lo indicano. Device e Inventory unificati (vista Device), dashboard Flotta con nomi.
- **1.10.0** — **filtri a condizioni** (AND/OR, NON, liste con "stesso elemento", versioni, date, regex, filtri annidati, anteprima live, modifica) su tutto l'inventario; **campi personalizzati** (tipi testo/numero/data/sì-no/elenco, modifica singola e in blocco, impostabili da script con `MYRMM_FIELD:`, colonne in Inventory/Device/CSV, ricerca, variabili `{{CF_NOME}}`); filtro salvato in Inventory e Device. In seguito: **Device e Inventory unificati in un'unica vista** (software installato come filtro, tutte le azioni di gruppo); dashboard Flotta con nomi dei device (modalità Nomi/Compatta); selettore cliente/site funzionante in Device e Inventory (prima i link portavano alla dashboard) ed esecuzione di uno script su più device selezionati da Inventory. Nuove tabelle `custom_fields`, `device_fields`. Testi del sistema resi neutri.
- **1.9.1** — la ricerca globale (`Ctrl K`) interroga tutto l'inventory (IP, MAC, utente, seriale, software, servizi…) e mostra il campo trovato.
- **1.9.0** — **task manager** in tempo reale (processi, CPU/RAM, raggruppamento per applicazione, filtro, termina singolo/tutti/con figli, verifica PID+avvio, protezione dei processi di sistema). Nuova chiave `TM_MODE`, `tm_mode` nella config dell'agent. I corpi grandi inviati dall'agent sono compressi (header `X-Gzip`).
- **1.8.0** — **file manager** integrato (elenco, apri, scarica, carica, crea, rinomina, elimina; limite `FS_MAX_MB` configurabile; poll rapido mentre è aperto; richieste a scadenza), **riavvio/spegnimento** programmati con annulla, **servizi** su Windows/Linux/macOS con tipo di avvio. Nuove chiavi `FS_MAX_MB`, `FS_MODE`; nuovo `fs_mode` nella config dell'agent. Il server mostra il limite reale imposto da PHP.
- **1.7.0** — **wizard di primo avvio** e `config.php` fuori da `index.php` (che non si modifica più): scelta della cartella dati anche fuori webroot, chiavi generate, `setup.allow` come guardia; password e 2FA dell'admin integrato gestiti dal Profilo; rimosso il Generatore; fix cache opcache sulla riscrittura del config. Agent 1.7.0 (solo allineamento versione).
- **1.6.1** — pulizia: rimosso il modulo **osquery** (endpoint, vista, tabelle e cartella `osquery/`; le tabelle `osq_*` vengono eliminate dal DB al primo avvio), rimossa la basic auth legacy (`CONSOLE_BASIC`) e la config Authorization di `.htaccess`, Deploy ridotta a pacchetti per site + un blocco manuale. Il 2FA resta **facoltativo** per tutti, primo utente compreso: in *Sistema* è indicato come tale, non come avviso. Gli agent non cambiano.

- **1.6.0** — agent **Linux e macOS** (stesso codice, runner shell/shebang, inventario nativo, auto-update per piattaforma) e **pacchetti di installazione per site**: token per cliente → one-liner PowerShell e sh, script universale (variabile `MYRMM_TOKEN`), ZIP offline per cliente con installer già configurati; installazione idempotente con verifica SHA-256 e permessi ristretti su `config.json`. Script di libreria con piattaforma (Windows / Linux-macOS / qualsiasi): il server non li accoda su device di piattaforma diversa; patch management e card patch solo per Windows. `run` logga su console; l'agent parte anche senza syslog.

- **1.5.0** — sicurezza e restyling. Login con sessione al posto del basic auth, 2FA TOTP, password hash, limite IP, header di sicurezza, cambio password obbligatorio, chiusura sessioni; backup con rotazione/download/ripristino; revoca ed eliminazione device; token di arruolamento per site. Nuova interfaccia: barra laterale, ricerca/palette (Ctrl+K), tema scuro/chiaro, dashboard con "polso della flotta" (una cella per device, per site), lista "da guardare" e grafici (patch per site, versioni agent, job a 14 giorni). L'agent non cambia (solo il numero di versione).

- **1.4.1** — diagnostica auto-update: l'agent riporta nell'inventario l'ultimo esito/motivo dell'update (firma non valida, download HTTP, rinviato per job in corso…) e i job in esecuzione; visibili nella pagina device. Su un PC con agent che non si aggiorna: Visualizzatore eventi → Application → origine "myrmm-agent".
- **1.4.0** — vista **Inventory** (tabella di tutti i device: stato, hostname, site, utente, OS, modello, seriale, RAM, CPU%, RAM%, disco libero, IP, boot, agent, patch, alert, RustDesk, ultimo contatto; filtro testo e rapidi, ordinamento a clic, colonne nascoste a scelta, CSV, selezione multipla). Pulsanti: **Inventario completo** (subito, via heartbeat: serve agent ≥ 1.4.0), **Applica patch** (selezionate / tutte, escluse le rifiutate, senza riavvio automatico; dalla pagina device o in massa), **Aggiorna agent** / **Distribuisci a tutti** (reinstalla l'agent presente in update/ anche se la versione è uguale; pannello con versione, dimensione, sha256 e quanti device sono disallineati). Nuovo agent: inventario completo asincrono, update forzato rimandato se ci sono job in corso.
- **1.3.0** — RustDesk integrato nel motore: card "Accesso remoto (RustDesk)" nella pagina del device con ID, modalità (unattended / accettazione utente), password memorizzata (cifrata AES-256-GCM, nascosta; "mostra"/"copia" richiedono ruolo operator e finiscono in audit), pulsanti "Apri app RustDesk" (rustdesk://) e "Web client" (costante `RUSTDESK_WEB_URL`, segnaposto `{id}`/`{password}`). I dati vengono catturati dagli script di libreria (RUSTDESK_ID/MODE/PW; la password è mascherata nell'output salvato) e modificabili a mano.
- **1.2.7** — fix job "mai terminato" con RustDesk: gli script RustDesk usavano `Start-Process -Wait` sull'installer, che aspetta anche i processi lasciati attivi (RustDesk/servizio) e tiene aperte le pipe stdout/stderr, quindi il risultato non arrivava mai. Ora `-PassThru` + `WaitForExit(timeout)`. Gli script di libreria del pacchetto si aggiornano da soli all'avvio se non li hai modificati (hash in meta); le tue modifiche non vengono mai sovrascritte.
- **1.2.6** — job: "Annulla" (pending, immediato) e "Interrompi" (in esecuzione: l'agent termina PowerShell e i processi figli al prossimo heartbeat, esito "interrotto", exit -4, non genera alert); "Forza chiusura" se il PC è offline. Storico: "Elimina" per singolo job, "Elimina riusciti" (restano i falliti), "Elimina tutti i conclusi". Tutto in audit.
- **1.2.5** — fix inventario completo: IP/DNS/gateway annidati (array serializzati da PowerShell come {"value":[..],"Count":n}) causavano "Array to string conversion" e mostravano "2, Array".
- **1.2.4** — agent: i job girano in parallelo (max 4) invece che in fila. Prima una scansione patch lunga (Windows Update può impiegare minuti) bloccava heartbeat e tutti gli altri job sullo stesso PC. Nessun job viene eseguito due volte; l'auto-update attende la fine dei job in corso.
- **1.2.3** — restyling grafico (tema chiaro/scuro automatico, header fisso con voce attiva, card più pulite). Job recenti in elenco compatto: stato, prima riga dello script, origine, durata, data; clic sulla riga per espandere script/stdout/stderr, pulsanti "Espandi/Comprimi tutti" e filtro "solo falliti". Le card della pagina device (manutenzione, variabili, servizio, esegui script, nuovo job, schedulazioni, patch) e le query osquery sono richiudibili.
- **1.2.2** — pagina device: "Esegui script dalla libreria (una volta)" con campi variabile e avviso sulle variabili vuote.
- **1.2.1** — agent: stderr in testo (niente CLIXML) e niente barre di avanzamento; script RustDesk/deploy con controllo delle variabili obbligatorie.
- **1.2.0** — versioni di server e agent allineate (`release.sh`); script RustDesk con accettazione utente + link "connetti"; manuale riscritto.
- **1.1.0** — utenti e ruoli con scope per site, anti-CSRF, filtri salvati, regole dinamiche, rimedio automatico, patch management con finestre e approvazione.
- **1.0.0** — monitor con script, 11 monitor pronti, esecuzione su più device, variabili a cascata, manutenzione, ricerca software e CSV, pagina deploy.
- **0.9.0** — retention automatica, anti brute-force, riconsegna job opzionale, auto-update firmato dell'agent.
- **≤ 0.8** — agent Go, firma job, inventario, schedulazioni, check/alert/notifiche, deploy+patch via script, multi-site, RustDesk, dashboard e audit.
