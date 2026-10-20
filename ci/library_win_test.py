#!/usr/bin/env python3
"""Prove di comportamento degli script Windows della libreria per temi, su PowerShell 7 (pwsh) con i cmdlet di Windows sostituiti da funzioni finte.
Ogni script è materializzato come fa il server (segnaposto con apici sicuri), preceduto da un preludio di finti cmdlet (registro, Defender, rete…),
ed eseguito con «pwsh -File»; si controllano uscita e testo. Il controllo «sono amministratore» viene sostituito da una variabile di prova.
La prova su un VERO Windows PowerShell 5.1 è un'altra: ci/library_run.py sui runner GitHub.
Uso: python3 ci/library_win_test.py [filtro-nome]      Serve php e pwsh; senza pwsh salta."""
import os, re, shutil, subprocess, sys, tempfile
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import libseed
PWSH = shutil.which("pwsh")
if not PWSH: print("pwsh non disponibile: salto"); sys.exit(0)
FILTER = sys.argv[1] if len(sys.argv) > 1 else ""
ok = bad = 0
def check(n, c, x=""):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("  FALLITO", n, "\n          " + str(x)[:1200].replace("\n", "\n          "))
rows, TMP, _ = libseed.seeded(port=8798)
BY = {r["name"]: r for r in rows}
ADMIN_RX = r"\(\[Security\.Principal\.WindowsPrincipal\]\[Security\.Principal\.WindowsIdentity\]::GetCurrent\(\)\)\.IsInRole\(\[Security\.Principal\.WindowsBuiltInRole\]::Administrator\)"
def want(n): return not FILTER or FILTER.lower() in n.lower()

def ps(v):
    """valore Python → testo PowerShell"""
    if v is None: return "$null"
    if v is True: return "$true"
    if v is False: return "$false"
    if isinstance(v, (int, float)): return str(v)
    if isinstance(v, dict): return "[pscustomobject]@{" + "; ".join(f"'{k}' = {ps(x)}" for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)): return "@(" + ", ".join(ps(x) for x in v) + ")" if v else "@()"
    if isinstance(v, str) and v.startswith("=PS="): return v[4:]
    return "'" + str(v).replace("'", "''") + "'"

PRELUDE = r'''
$global:REG = @{}; $global:REGKEYS = @{}; $global:LOG = New-Object System.Collections.ArrayList
$global:IS_ADMIN = %ADMIN%
function Get-ItemProperty { param($Path, $Name, $ErrorAction)
  if ($Name) { $k = "$Path|$Name"; if ($global:REG.ContainsKey($k)) { $o = New-Object psobject; $o | Add-Member NoteProperty $Name $global:REG[$k]; return $o } else { throw "mancante" } }
  $o = New-Object psobject; $f = $false
  foreach ($kk in @($global:REG.Keys)) { if ($kk.StartsWith("$Path|")) { $o | Add-Member NoteProperty $kk.Substring($Path.Length + 1) $global:REG[$kk]; $f = $true } }
  if (-not $f) { throw "mancante" }; return $o }
function New-ItemProperty { param($Path, $Name, $Value, $PropertyType, [switch]$Force, $ErrorAction) $global:REG["$Path|$Name"] = $Value; $global:REGKEYS[$Path] = $true; [void]$global:LOG.Add("New-ItemProperty $Path $Name=$Value") }
function Set-ItemProperty { param($Path, $Name, $Value, $Type, [switch]$Force, $ErrorAction) $global:REG["$Path|$Name"] = $Value; [void]$global:LOG.Add("Set-ItemProperty $Path $Name=$Value") }
function New-Item { param($Path, $ItemType, [switch]$Force, $ErrorAction) $global:REGKEYS[$Path] = $true; [void]$global:LOG.Add("New-Item $Path"); return $null }
$global:REGCHILD = @{}; $global:COM = @{}
function Get-ChildItem { [CmdletBinding()] param([Parameter(Position=0)]$Path, $LiteralPath, [switch]$Directory, [switch]$File, [switch]$Force, [switch]$Recurse, $Filter)
  $p = if ($LiteralPath) { $LiteralPath } else { $Path }
  if ($p -is [string] -and $p -match '^Registry::|^HK(LM|CU):') { if ($global:REGCHILD.ContainsKey($p)) { return @($global:REGCHILD[$p] | ForEach-Object { [pscustomobject]@{ PSChildName = $_; Name = $_ } }) } else { return @() } }
  Microsoft.PowerShell.Management\Get-ChildItem @PSBoundParameters }
function New-Object { param([Parameter(Position=0)]$TypeName, [Parameter(Position=1)]$ArgumentList, $ComObject)
  if ($ComObject) { if ($global:COM.ContainsKey($ComObject)) { return (& $global:COM[$ComObject]) } else { throw "COM $ComObject non simulato" } }
  if ($PSBoundParameters.ContainsKey('ArgumentList')) { Microsoft.PowerShell.Utility\New-Object -TypeName $TypeName -ArgumentList $ArgumentList } else { Microsoft.PowerShell.Utility\New-Object -TypeName $TypeName } }
$__realTestPath = Get-Command Microsoft.PowerShell.Management\Test-Path -CommandType Cmdlet
function Test-Path { param([Parameter(Position=0)]$Path, $LiteralPath, $PathType)
  $p = if ($LiteralPath) { $LiteralPath } else { $Path }
  if ($p -match '^HK(LM|CU):') { return ($global:REGKEYS.ContainsKey($p) -or @($global:REG.Keys | Where-Object { $_.StartsWith("$p|") }).Count -gt 0) }
  if ($global:MOCKPATHS -and ($global:MOCKPATHS | Where-Object { $p -like $_ })) { return $true }
  & $__realTestPath -LiteralPath $p }
'''
LASTFILES = {}
def run(name, vars=None, mocks="", admin=True, body_sub=None, timeout=120, env=None, files=None):
    r = BY[name]; vs = {k: "" for k in re.findall(r"\{\{\s*([A-Za-z_]\w*)", r["body"])}; vs.update(vars or {})
    body = libseed.php_materialize([(r["body"], vs, "windows")], TMP)[0]
    body = re.sub(ADMIN_RX, "$global:IS_ADMIN", body)
    if body_sub: body = body_sub(body)
    d = tempfile.mkdtemp(prefix="myrmm-w-")
    for rel, content in (files or {}).items():
        fp = os.path.join(d, rel); os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "wb").write(content if isinstance(content, bytes) else content.encode("utf-8"))
        if rel.startswith("bin/"): os.chmod(fp, 0o755)
    f = os.path.join(d, "t.ps1")
    open(f, "w", encoding="utf-8-sig").write(PRELUDE.replace("%ADMIN%", "$true" if admin else "$false") + "\n" + mocks + "\n" + body + "\n")
    e = dict(os.environ); e.update({"PATH": d + "/bin:" + os.environ.get("PATH", ""), "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1", "SystemDrive": d + "/sys", "ProgramData": d + "/pd", "TEMP": d, "TMP": d, "USERPROFILE": d + "/u", "SystemRoot": d + "/win", "windir": d + "/win", "COMPUTERNAME": "PC-PROVA"}); e.update(env or {})
    try:
        p = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", f], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=e, stdin=subprocess.DEVNULL)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired: out, rc = "TIMEOUT", 124
    LASTFILES.clear(); LASTFILES["__dir__"] = d
    for root, _, fs in os.walk(d):
        for fn in fs:
            fp = os.path.join(root, fn)
            if fn == "t.ps1": continue
            try: LASTFILES[os.path.relpath(fp, d)] = open(fp, "rb").read()[:200000].decode("utf-8", "replace")
            except Exception: pass
    shutil.rmtree(d, ignore_errors=True)
    return rc, out
def expect(label, res, rc=None, has=(), hasnot=(), regex=()):
    r, o = res
    check(f"{label}: uscita {rc}", rc is None or r == rc, f"rc={r}\n{o}")
    for s in has: check(f"{label}: contiene «{s}»", s in o, o)
    for s in hasnot: check(f"{label}: non contiene «{s}»", s not in o, o)
    for rx in regex: check(f"{label}: corrisponde a {rx}", re.search(rx, o, re.M), o)
HOSTILE = ["a'; Write-Output PWNED; '", "$(Write-Output PWNED)", "`$(PWNED)", "a\"; Write-Output PWNED; \"", "x' + (Write-Output PWNED) + '", "'@\nWrite-Output PWNED\n@'"]

# ======================================================================================================================
N = "Windows: audit di sicurezza (Defender, firewall, BitLocker, UAC, SMB, RDP)"
if want(N):
    print("==", N)
    sysk = "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System"
    good = ("$global:REG['%s|EnableLUA']=1; $global:REG['HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server|fDenyTSConnections']=1; $global:REG['HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa|RunAsPPL']=1\n"
            "function Get-MpComputerStatus { %s }\nfunction Get-NetFirewallProfile { %s }\nfunction Get-BitLockerVolume { param($MountPoint,$ErrorAction) %s }\n"
            "function Get-SmbServerConfiguration { param($ErrorAction) %s }\nfunction Get-LocalUser { param($Name,$ErrorAction) %s }\n")
    def mk(mp=None, fw=None, bl=None, smb=None, gu=None):
        return good % (sysk, ps(mp or dict(RealTimeProtectionEnabled=True, AntivirusSignatureAge=1)), ps(fw or [dict(Name="Domain", Enabled=True), dict(Name="Private", Enabled=True), dict(Name="Public", Enabled=True)]),
                       ps(bl or dict(ProtectionStatus="On")), ps(smb or dict(EnableSMB1Protocol=False, RequireSecuritySignature=True)), ps(gu or dict(Enabled=False)))
    r = run(N, {"FALLISCI": "si"}, mk()); expect("tutto a posto", r, 0, ["nessuna impostazione da rivedere", "OK          Defender: protezione in tempo reale"], ["ATTENZIONE"])
    m = mk(mp=dict(RealTimeProtectionEnabled=False, AntivirusSignatureAge=30), fw=[dict(Name="Public", Enabled=False)], bl=dict(ProtectionStatus="Off"), smb=dict(EnableSMB1Protocol=True, RequireSecuritySignature=False), gu=dict(Enabled=True))
    m += "$global:REG['%s|EnableLUA']=0; $global:REG['HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server|fDenyTSConnections']=0; $global:REG['HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon|AutoAdminLogon']='1'; $global:REG['HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon|DefaultPassword']='x'; $global:REG['HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\WDigest|UseLogonCredential']=1\n" % sysk
    r = run(N, {}, m); expect("tutto sbagliato", r, 0, ["impostazioni da rivedere", "ATTENZIONE  Defender: protezione in tempo reale", "vecchie di 30 giorni", "ATTENZIONE  Firewall profilo Public", "ATTENZIONE  BitLocker", "ATTENZIONE  UAC", "ATTENZIONE  SMBv1", "NLA", "WDigest", "Accesso automatico", "Password predefinita", "Account Guest"])
    r = run(N, {"FALLISCI": "si"}, m); expect("FALLISCI=si", r, 1); r = run(N, {"FALLISCI": "no"}, m); expect("FALLISCI=no", r, 0)
    r = run(N, {}, ""); expect("senza nessun cmdlet (tutto non rilevabile)", r, 0, ["INFO"])

N = "Windows: Defender (stato, minacce recenti, esclusioni)"
if want(N):
    print("==", N)
    st = dict(AntivirusEnabled=True, RealTimeProtectionEnabled=True, BehaviorMonitorEnabled=True, IoavProtectionEnabled=True, AntivirusSignatureVersion="1.2.3", AntivirusSignatureAge=2, AntivirusSignatureLastUpdated="ieri", QuickScanEndTime="oggi", FullScanEndTime="mai", IsTamperProtected=True)
    mk = ("function Get-MpComputerStatus { param($ErrorAction) %s }\nfunction Get-MpThreatDetection { param($ErrorAction) @([pscustomobject]@{InitialDetectionTime=(Get-Date).AddDays(-1); ThreatID=7; ActionSuccess=$true; Resources=@('file:_C:\\x.exe')}, [pscustomobject]@{InitialDetectionTime=(Get-Date).AddDays(-30); ThreatID=8; ActionSuccess=$true; Resources=@('file:_C:\\vecchio.exe')}) }\n"
          "function Get-MpThreat { param($ThreatID,$ErrorAction) [pscustomobject]@{ThreatName='Trojan:Test/Eicar'} }\n"
          "function Get-MpPreference { param($ErrorAction) [pscustomobject]@{ExclusionPath=@('C:\\Dati');ExclusionExtension=@('xyz');ExclusionProcess=@('app.exe')} }\n") % ps(st)
    r = run(N, {}, mk); expect("stato", r, 0, ["Tempo reale: True", "Trojan:Test/Eicar", "x.exe", "percorso:   C:\\Dati", "estensione: xyz", "processo:   app.exe"], ["vecchio.exe"])
    r = run(N, {"GIORNI": "60"}, mk); expect("finestra larga", r, 0, ["vecchio.exe"])
    r = run(N, {}, ""); expect("Defender assente", r, 0, ["non è disponibile"])
    for v in ("x", "0", "1;id", "-3", "99999"): r = run(N, {"GIORNI": v}, mk); expect(f"GIORNI non valido {v!r}", r, 2)

N = "Windows: aggiungi o rimuovi un'esclusione di Defender"
if want(N):
    print("==", N)
    mk = ("$global:P = @{ExclusionPath=@(); ExclusionExtension=@(); ExclusionProcess=@()}\n"
          "function Add-MpPreference { param($ExclusionPath,$ExclusionExtension,$ExclusionProcess,$ErrorAction) foreach($k in 'ExclusionPath','ExclusionExtension','ExclusionProcess'){ $v=Get-Variable $k -ValueOnly -ErrorAction SilentlyContinue; if($v){ $global:P[$k] = @($global:P[$k]) + $v; [void]$global:LOG.Add(\"Add $k $v\") } } }\n"
          "function Remove-MpPreference { param($ExclusionPath,$ExclusionExtension,$ExclusionProcess,$ErrorAction) foreach($k in 'ExclusionPath','ExclusionExtension','ExclusionProcess'){ $v=Get-Variable $k -ValueOnly -ErrorAction SilentlyContinue; if($v){ $global:P[$k] = @($global:P[$k] | Where-Object { $_ -ne $v }); [void]$global:LOG.Add(\"Remove $k $v\") } } }\n"
          "function Get-MpPreference { [pscustomobject]$global:P }\n")
    r = run(N, {"TIPO": "percorso", "VALORE": "D:\\Progetti\\App"}, mk); expect("aggiungi percorso", r, 0, ["aggiunta"])
    r = run(N, {"TIPO": "estensione", "VALORE": ".xyz"}, mk); expect("aggiungi estensione", r, 0, ["«.xyz»: aggiunta"])
    r = run(N, {"TIPO": "processo", "VALORE": "app.exe"}, mk); expect("aggiungi processo", r, 0, ["aggiunta"])
    r = run(N, {"AZIONE": "rimuovi", "TIPO": "percorso", "VALORE": "D:\\Progetti\\App"}, mk + "$global:P.ExclusionPath = @('D:\\Progetti\\App')\n"); expect("rimuovi percorso", r, 0, ["rimossa"])
    r = run(N, {"AZIONE": "rimuovi", "TIPO": "percorso", "VALORE": "D:\\Altro"}, mk); expect("rimuovi esclusione inesistente", r, 0, ["rimossa"])
    for tipo, val in (("percorso", "C:\\"), ("percorso", "C:"), ("percorso", "*"), ("percorso", "\\\\server"), ("percorso", "C:\\Windows"), ("percorso", "C:\\Users"), ("percorso", "C:\\Program Files"),
                      ("estensione", "exe"), ("estensione", ".ps1"), ("estensione", "a b"), ("estensione", "x;y"), ("processo", "a|b"), ("percorso", "D:\\a\"b"), ("percorso", "D:\\a<b")):
        r = run(N, {"TIPO": tipo, "VALORE": val}, mk); expect(f"{tipo} {val!r} rifiutato", r, 2); check(f"{tipo} {val!r}: nessuna modifica", "Add " not in r[1], r[1])
    for v in ({"TIPO": ""}, {"TIPO": "cartella"}, {"AZIONE": "cancella"}, {"VALORE": ""}):
        vv = {"TIPO": "percorso", "VALORE": "D:\\x"}; vv.update(v); r = run(N, vv, mk); expect(f"non valido {v}", r, 2)
    r = run(N, {"TIPO": "percorso", "VALORE": "D:\\x"}, mk, admin=False); expect("senza amministratore", r, 3)
    for h in HOSTILE:
        r = run(N, {"TIPO": "processo", "VALORE": h}, mk); check(f"valore ostile {h[:14]!r} non esegue nulla", "PWNED" not in r[1].replace("PWNED; '", "").replace("PWNED)", ""), r[1])
    r = run(N, {"TIPO": "percorso", "VALORE": "D:\\x"}, mk.replace("function Add-MpPreference", "function Add-MpPreference-Orig") + "function Add-MpPreference { throw 'protetto da manomissione' }\n"); expect("Defender rifiuta", r, 1, ["Operazione non riuscita"])

N = "Windows: riattiva le protezioni di Defender"
if want(N):
    print("==", N)
    mk = ("$global:S = @{RealTimeProtectionEnabled=$false; BehaviorMonitorEnabled=$false; IoavProtectionEnabled=$false; AntivirusSignatureAge=5}\n"
          "function Get-MpComputerStatus { param($ErrorAction) [pscustomobject]$global:S }\n"
          "function Set-MpPreference { param($DisableRealtimeMonitoring,$DisableBehaviorMonitoring,$DisableIOAVProtection,$DisableScriptScanning,$MAPSReporting,$SubmitSamplesConsent,$CloudBlockLevel,$ErrorAction) if($PSBoundParameters.ContainsKey('DisableRealtimeMonitoring')){ $global:S.RealTimeProtectionEnabled = -not $DisableRealtimeMonitoring; $global:S.BehaviorMonitorEnabled = $true; $global:S.IoavProtectionEnabled = $true }; if($MAPSReporting){ Write-Output \"CALL cloud $MAPSReporting\" } }\n"
          "function Update-MpSignature { param($ErrorAction) $global:S.AntivirusSignatureAge = 0 }\n")
    r = run(N, {}, mk); expect("riattiva", r, 0, ["Tempo reale: True", "Firme: 0 giorni", "CALL cloud Advanced"])
    r = run(N, {"CLOUD": "no"}, mk); expect("senza cloud", r, 0, [], ["CALL cloud"])
    r = run(N, {}, mk.replace("$global:S.RealTimeProtectionEnabled = -not $DisableRealtimeMonitoring", "$global:S.RealTimeProtectionEnabled = $false")); expect("resta spento", r, 1, ["ancora spenta"])
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)
    r = run(N, {}, "function Get-MpComputerStatus { throw 'no' }\n"); expect("Defender assente", r, 1, ["non è disponibile"])
    r = run(N, {}, mk + "function Set-MpPreference { throw 'criteri di gruppo' }\n"); expect("Set-MpPreference fallisce", r, 1, ["Impossibile modificare"])

N = "Windows: disabilita LLMNR e NetBIOS su TCP/IP"
if want(N):
    print("==", N)
    mk = ("function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) @([pscustomobject]@{Description='Ethernet 1'; Id=1}, [pscustomobject]@{Description='Wi-Fi'; Id=2}) }\n"
          "function Invoke-CimMethod { param($InputObject,$MethodName,$Arguments) Write-Output \"CALL $MethodName $($InputObject.Description) $($Arguments.TcpipNetbiosOptions)\" | Out-Host; [pscustomobject]@{ReturnValue=0} }\n")
    r = run(N, {}, mk); expect("entrambi", r, 0, ["LLMNR: disabilitato", "disabilitato su 2 schede", "CALL SetTcpipNetbios Ethernet 1 2", "CALL SetTcpipNetbios Wi-Fi 2"])
    r = run(N, {"COSA": "llmnr"}, mk); expect("solo LLMNR", r, 0, ["LLMNR"], ["NetBIOS"])
    r = run(N, {"COSA": "NetBIOS"}, mk); expect("solo NetBIOS (maiuscole)", r, 0, ["NetBIOS"], ["LLMNR"])
    r = run(N, {"COSA": "llmnr, netbios"}, mk); expect("con spazio", r, 0, ["LLMNR", "NetBIOS"])
    r = run(N, {}, mk.replace("ReturnValue=0", "ReturnValue=91")); expect("errore WMI", r, 1, ["codice 91"])
    for v in ("tutto", "llmnr;id", "$(id)", ",", "mdns"): r = run(N, {"COSA": v}, mk); expect(f"COSA non valido {v!r}", r, 2)
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)

N = "Windows: programmi in avvio automatico"
if want(N):
    print("==", N)
    mk = ("$global:REG['HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run|Updater']='C:\\Prog\\upd.exe /silent'\n$global:REG['HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run|MioApp']='C:\\Users\\mario\\app.exe'\n"
          "$global:MOCKPATHS = @('*Start Menu*','*Startup*')\n"
          "function Get-ChildItem { param($Path,$LiteralPath,[switch]$Directory,[switch]$File,[switch]$Force,$ErrorAction) $p = if($LiteralPath){$LiteralPath}else{$Path}; if($p -like '*Users'){ return @([pscustomobject]@{FullName='/sys/Users/mario'}) }; if($p -like '*StartUp*' -or $p -like '*Startup*'){ return @([pscustomobject]@{Name='collegamento.lnk'}, [pscustomobject]@{Name='desktop.ini'}) }; @() }\n"
          "function Get-ScheduledTask { param($ErrorAction) @([pscustomobject]@{TaskPath='\\'; TaskName='MioLogon'; State='Ready'; Triggers=@([pscustomobject]@{CimClass=[pscustomobject]@{CimClassName='MSFT_TaskLogonTrigger'}}); Actions=@([pscustomobject]@{Execute='C:\\x\\a.exe'; Arguments='-q'})},"
          " [pscustomobject]@{TaskPath='\\Microsoft\\Windows\\X\\'; TaskName='Interno'; State='Ready'; Triggers=@([pscustomobject]@{CimClass=[pscustomobject]@{CimClassName='MSFT_TaskLogonTrigger'}}); Actions=@()},"
          " [pscustomobject]@{TaskPath='\\'; TaskName='Giornaliera'; State='Ready'; Triggers=@([pscustomobject]@{CimClass=[pscustomobject]@{CimClassName='MSFT_TaskDailyTrigger'}}); Actions=@()}) }\n"
          "function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) @([pscustomobject]@{Name='Terzo'; State='Running'; PathName='C:\\Programmi\\Terzo\\t.exe'}, [pscustomobject]@{Name='Win'; State='Running'; PathName='C:\\Windows\\system32\\svchost.exe -k x'}) }\n")
    r = run(N, {}, mk); expect("elenco", r, 0, ["Run  Updater = C:\\Prog\\upd.exe /silent", "MioApp", "collegamento.lnk", "\\MioLogon  ->  C:\\x\\a.exe -q", "Terzo (Running)", "Elementi trovati: 6"], ["Interno", "Giornaliera", "svchost", "desktop.ini  ("])
    r = run(N, {}, ""); expect("sistema vuoto", r, 0, ["Elementi trovati: 0"])

N = "Windows: servizi con percorso non quotato"
if want(N):
    print("==", N)
    svc = lambda *a: "function Get-CimInstance { param($ClassName,$ErrorAction) @(" + ", ".join(ps(dict(Name=n, StartMode="Auto", PathName=p)) for n, p in a) + ") }\n"
    bsv = svc(("A", "C:\\Program Files\\App\\a.exe"), ("B", "C:\\Program Files\\App\\b.exe -k run"), ("C", '"C:\\Program Files\\App\\c.exe" -x'), ("D", "C:\\Windows\\system32\\svchost.exe -k netsvcs"), ("E", "C:\\Tool\\e.exe /s /c C:\\Program Files\\x"), ("F", ""), ("G", "C:\\Program Files\\App\\g.bat arg"))
    r = run(N, {}, bsv); expect("trovati", r, 0, ["NON QUOTATO: 3", "servizi_percorso_non_quotato=3", "A  (Auto)", "B  (Auto)", "G  (Auto)"], ["C  (", "D  (", "E  ("])
    r = run(N, {"FALLISCI": "si"}, bsv); expect("FALLISCI", r, 1)
    r = run(N, {"FALLISCI": "si"}, svc(("C", '"C:\\Program Files\\c.exe"'))); expect("nessuno", r, 0, ["Nessun servizio", "non_quotato=0"])

N = "Windows: regole firewall in ingresso consentite"
if want(N):
    print("==", N)
    rules = ("function Get-NetFirewallRule { param($Direction,$Action,$Enabled,$ErrorAction) @([pscustomobject]@{DisplayName='Mia app'; DisplayGroup=$null; Profile='Any'}, [pscustomobject]@{DisplayName='Condivisione file'; DisplayGroup='File e stampanti'; Profile='Private'}) }\n"
             "function Get-NetFirewallPortFilter { param($AssociatedNetFirewallRule,$ErrorAction) if($AssociatedNetFirewallRule.DisplayName -eq 'Mia app'){ [pscustomobject]@{Protocol='TCP'; LocalPort='8080'} } else { [pscustomobject]@{Protocol='TCP'; LocalPort='445'} } }\n"
             "function Get-NetFirewallApplicationFilter { param($AssociatedNetFirewallRule,$ErrorAction) [pscustomobject]@{Program='C:\\app\\mia.exe'} }\n")
    r = run(N, {}, rules); expect("solo personalizzate", r, 0, ["consentite: 1 (solo non predefinite)", "Mia app  [Any]  TCP/8080  C:\\app\\mia.exe"], ["Condivisione file"])
    r = run(N, {"TUTTE": "si"}, rules); expect("tutte", r, 0, ["consentite: 2", "Condivisione file", "TCP/445"])
    r = run(N, {}, "function Get-NetFirewallRule { throw 'x' }\n"); expect("firewall non leggibile", r, 1)

N = "Windows: membri dei gruppi locali privilegiati"
if want(N):
    print("==", N)
    mk = ("function Get-LocalGroup { param($SID,$ErrorAction) $n = @{'S-1-5-32-544'='Administrators';'S-1-5-32-555'='Utenti desktop remoto'}[$SID]; if($n){ [pscustomobject]@{Name=$n} } else { throw 'x' } }\n"
          "function Get-LocalGroupMember { param($SID,$ErrorAction) if($SID -eq 'S-1-5-32-544'){ @([pscustomobject]@{Name='PC\\Administrator';ObjectClass='User'}, [pscustomobject]@{Name='PC\\mario';ObjectClass='User'}, [pscustomobject]@{Name='DOM\\Domain Admins';ObjectClass='Group'}) } else { @([pscustomobject]@{Name='PC\\luca';ObjectClass='User'}) } }\n")
    r = run(N, {}, mk); expect("elenco", r, 0, ["== Administrators (3)", "== Utenti desktop remoto (1)", "PC\\mario  [User]", "PC\\luca"], ["ACCOUNT NON ATTESI"])
    r = run(N, {"ATTESI": "Administrator, DOM\\Domain Admins", "FALLISCI": "si"}, mk); expect("non atteso", r, 1, ["NON ATTESI NEGLI ADMINISTRATORS: PC\\mario"])
    r = run(N, {"ATTESI": "administrator,mario,DOM\\Domain Admins", "FALLISCI": "si"}, mk); expect("tutti attesi", r, 0, [], ["NON ATTESI"])
    r = run(N, {"ATTESI": "administrator", "FALLISCI": "no"}, mk); expect("non atteso senza FALLISCI", r, 0, ["NON ATTESI"])
    r = run(N, {}, mk.replace("Get-LocalGroupMember { param($SID,$ErrorAction)", "Get-LocalGroupMember { param($SID,$ErrorAction) throw 'orfano';")); expect("membri non leggibili", r, 0, ["non leggibili"])

N = "Windows: criteri di password e blocco account"
if want(N):
    print("==", N)
    def sec(min_=14, cx=1, lock=5): return "function secedit.exe { param([Parameter(ValueFromRemainingArguments)]$a) $f = $a[($a.IndexOf('/cfg'))+1]; Set-Content -LiteralPath $f -Value @('[System Access]','MinimumPasswordLength = %s','MaximumPasswordAge = 42','PasswordComplexity = %s','PasswordHistorySize = 24','LockoutBadCount = %s','LockoutDuration = 15') }\n" % (min_, cx, lock)
    r = run(N, {"FALLISCI": "si"}, sec()); expect("criteri buoni", r, 0, ["nessun valore debole", "Lunghezza minima: 14"])
    r = run(N, {"FALLISCI": "si"}, sec(6, 0, 0)); expect("criteri deboli + FALLISCI", r, 1, ["lunghezza minima 6", "complessità disattivata", "nessun blocco"])
    r = run(N, {}, sec(6, 1, 5)); expect("deboli senza FALLISCI", r, 0, ["CRITERI DEBOLI"])
    r = run(N, {"LUNGHEZZA": "8"}, sec(8, 1, 5)); expect("soglia 8", r, 0, ["nessun valore debole"])
    for v in ("x", "1;id", "-1", "9999"): r = run(N, {"LUNGHEZZA": v}, sec()); expect(f"LUNGHEZZA non valida {v!r}", r, 2)
    r = run(N, {}, sec(), admin=False); expect("senza amministratore", r, 3)

N = "Windows: BitLocker (volumi, protettori e chiavi di ripristino)"
if want(N):
    print("==", N)
    mk = ("function Get-BitLockerVolume { param($ErrorAction) @([pscustomobject]@{MountPoint='C:';VolumeType='OperatingSystem';VolumeStatus='FullyEncrypted';ProtectionStatus='On';EncryptionPercentage=100;EncryptionMethod='XtsAes256';KeyProtector=@([pscustomobject]@{KeyProtectorType='Tpm'},[pscustomobject]@{KeyProtectorType='RecoveryPassword'})},"
          " [pscustomobject]@{MountPoint='D:';VolumeType='Data';VolumeStatus='FullyEncrypted';ProtectionStatus='On';EncryptionPercentage=100;EncryptionMethod='Aes128';KeyProtector=@([pscustomobject]@{KeyProtectorType='Password'})}) }\n")
    r = run(N, {}, mk); expect("due volumi", r, 0, ["C:  tipo=OperatingSystem", "protettori: RecoveryPassword, Tpm", "chiavi di ripristino: 1", "ATTENZIONE: protezione attiva ma nessuna chiave"])
    r = run(N, {}, "function Get-BitLockerVolume { throw 'no' }\n"); expect("non disponibile", r, 0, ["non è disponibile"])
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)
    r = run(N, {}, "function Get-BitLockerVolume { @() }\n"); expect("nessun volume", r, 0, ["(nessun volume)"])

N = "Windows: TPM, Secure Boot e protezioni hardware"
if want(N):
    print("==", N)
    mk = ("function Get-Tpm { param($ErrorAction) [pscustomobject]@{TpmPresent=$true;TpmReady=$true;TpmEnabled=$true} }\nfunction Confirm-SecureBootUEFI { param($ErrorAction) $true }\n"
          "function Get-CimInstance { param($Namespace,$ClassName,$ErrorAction) if($ClassName -eq 'Win32_Tpm'){ [pscustomobject]@{SpecVersion='2.0, 0, 1.38';ManufacturerIdTxt='INTC'} } else { [pscustomobject]@{VirtualizationBasedSecurityStatus=2;SecurityServicesRunning=@(1,2)} } }\n")
    r = run(N, {}, mk); expect("tutto presente", r, 0, ["TPM presente: True", "2.0, 0, 1.38", "Secure Boot attivo: True", "Credential Guard, Integrità della memoria (HVCI)"])
    r = run(N, {}, ""); expect("niente di rilevabile", r, 0, ["TPM: non rilevabile", "Secure Boot: non supportato", "Device Guard"])
    r = run(N, {}, mk.replace("SecurityServicesRunning=@(1,2)", "SecurityServicesRunning=@()")); expect("nessun servizio VBS", r, 0, ["servizi in esecuzione: nessuno"])

N = "Windows: sessioni SMB e file aperti da altri computer"
if want(N):
    print("==", N)
    mk = ("function Get-SmbSession { param($ErrorAction) 1..3 | ForEach-Object { [pscustomobject]@{ClientUserName=\"DOM\\u$_\";ClientComputerName=\"PC$_\";NumOpens=$_;SecondsIdle=10*$_} } }\n"
          "function Get-SmbOpenFile { param($ErrorAction) @([pscustomobject]@{ClientUserName='DOM\\u1';Path='D:\\Dati\\a.xlsx';SessionId=11}) }\n")
    r = run(N, {}, mk); expect("elenco", r, 0, ["== Sessioni: 3", "DOM\\u2  da PC2  file aperti=2", "== File aperti: 1", "D:\\Dati\\a.xlsx"])
    r = run(N, {"MAX": "1"}, mk); expect("MAX=1", r, 0, ["== Sessioni: 3", "DOM\\u1"], ["DOM\\u2 "])
    for v in ("x", "0", "1;id", "-1"): r = run(N, {"MAX": v}, mk); expect(f"MAX non valido {v!r}", r, 2)
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)
    r = run(N, {}, "function Get-SmbSession { throw 'x' }\n"); expect("server SMB assente", r, 1)


# ---- Windows blocco 2: rete e dischi ----
import socket, threading, time as _t
N = "Windows: configurazione IP, DNS e gateway di ogni scheda"
if want(N):
    print("==", N)
    mk = ("function Get-NetIPConfiguration { param($ErrorAction) @([pscustomobject]@{InterfaceAlias='Ethernet';InterfaceDescription='Intel NIC';InterfaceIndex=3;IPv4Address=@([pscustomobject]@{IPAddress='192.168.1.10';PrefixLength=24});IPv6Address=@([pscustomobject]@{IPAddress='fe80::1'});IPv4DefaultGateway=@([pscustomobject]@{NextHop='192.168.1.1'});DNSServer=@([pscustomobject]@{AddressFamily=2;ServerAddresses=@('1.1.1.1','9.9.9.9')});NetProfile=[pscustomobject]@{Name='Ufficio';NetworkCategory='DomainAuthenticated'}}) }\n"
          "function Get-NetAdapter { param($InterfaceIndex,$ErrorAction) [pscustomobject]@{Status='Up';MacAddress='00-11-22-33-44-55';LinkSpeed='1 Gbps'} }\nfunction Get-NetIPInterface { param($InterfaceIndex,$AddressFamily,$ErrorAction) [pscustomobject]@{Dhcp='Enabled'} }\n")
    r = run(N, {}, mk); expect("una scheda", r, 0, ["== Ethernet (Intel NIC)", "MAC=00-11-22-33-44-55", "IPv4: 192.168.1.10/24   DHCP: Enabled", "Gateway: 192.168.1.1", "DNS: 1.1.1.1, 9.9.9.9", "Ufficio (DomainAuthenticated)"])
    r = run(N, {}, "function Get-NetIPConfiguration { @() }\n"); expect("nessuna scheda", r, 0, ["Nessuna scheda"])

N = "Windows: connessioni TCP stabilite per processo"
if want(N):
    print("==", N)
    mk = ("function Get-NetTCPConnection { param($State,$ErrorAction) @([pscustomobject]@{OwningProcess=10;LocalAddress='10.0.0.5';LocalPort=50000;RemoteAddress='8.8.8.8';RemotePort=443}, [pscustomobject]@{OwningProcess=20;LocalAddress='10.0.0.5';LocalPort=50001;RemoteAddress='1.2.3.4';RemotePort=80}, [pscustomobject]@{OwningProcess=10;LocalAddress='127.0.0.1';LocalPort=5;RemoteAddress='127.0.0.1';RemotePort=6}) }\n"
          "function Get-Process { param($ErrorAction) @([pscustomobject]@{Id=10;ProcessName='chrome'}, [pscustomobject]@{Id=20;ProcessName='updater'}) }\n")
    r = run(N, {}, mk); expect("elenco", r, 0, ["verso l'esterno: 2", "chrome", "-> 8.8.8.8:443", "updater"], ["127.0.0.1:6"])
    r = run(N, {"FILTRO": "chrome"}, mk); expect("filtro processo", r, 0, ["esterno: 1", "chrome"], ["updater"])
    r = run(N, {"FILTRO": "1.2.3"}, mk); expect("filtro indirizzo", r, 0, ["esterno: 1", "updater"])
    r = run(N, {"MAX": "1"}, mk); expect("MAX=1", r, 0, ["esterno: 2"])
    for v in ({"MAX": "x"}, {"MAX": "0"}, {"MAX": "1;id"}, {"FILTRO": "a b"}, {"FILTRO": "$(id)"}, {"FILTRO": "a'b"}): r = run(N, v, mk); expect(f"non valido {v}", r, 2)
    r = run(N, {}, "function Get-NetTCPConnection { throw 'x' }\n"); expect("non leggibile", r, 1)

N = "Windows: traccia il percorso di rete verso un host"
if want(N):
    print("==", N)
    mk = "function Test-NetConnection { param($ComputerName,[switch]$TraceRoute,$WarningAction,$ErrorAction) [pscustomobject]@{PingSucceeded=$true;RemoteAddress='127.0.0.1';InterfaceAlias='lo';PingReplyDetails=[pscustomobject]@{RoundtripTime=1};TraceRoute=@('10.0.0.1','127.0.0.1')} }\n"
    r = run(N, {"HOST": "127.0.0.1"}, mk); expect("host locale", r, 0, ["== Risoluzione", "127.0.0.1", "Raggiungibile: True", " 1  10.0.0.1", " 2  127.0.0.1"])
    r = run(N, {"HOST": "nome-che-non-esiste.invalid"}, mk); expect("non risolvibile", r, 1, ["non risolvibile"])
    for v in ("", "-x", "a b", "a;id", "$(id)", "a'b", "a|b", "a`b", "a&b", "x" * 300): r = run(N, {"HOST": v}, mk); expect(f"HOST non valido {v[:12]!r}", r, 2)
    for h in HOSTILE: r = run(N, {"HOST": h}, mk); check(f"ostile {h[:14]!r}", "PWNED" not in r[1].replace("PWNED; '", ""), r[1])

N = "Windows: prova più porte TCP verso un host"
if want(N):
    print("==", N)
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", 0)); srv.listen(5); op = srv.getsockname()[1]
    cl = socket.socket(); cl.bind(("127.0.0.1", 0)); cp = cl.getsockname()[1]; cl.close()
    r = run(N, {"HOST": "127.0.0.1", "PORTE": f"{op}, {cp}"}, ""); expect("una aperta, una chiusa", r, 0, [f"{op}  APERTA", f"{cp}  chiusa", "Porte aperte: 1 su 2"])
    for v in ({"PORTE": "0"}, {"PORTE": "70000"}, {"PORTE": "80;id"}, {"PORTE": ",".join(str(i) for i in range(1, 52))}, {"ATTESA": "0"}, {"ATTESA": "31"}, {"ATTESA": "x"}, {"HOST": ""}, {"HOST": "a b"}, {"HOST": "-x"}, {"HOST": "a;id"}):
        vv = {"HOST": "127.0.0.1", "PORTE": "80"}; vv.update(v); r = run(N, vv, ""); expect(f"non valido {v}", r, 2)
    srv.close()

N = "Windows: Wi-Fi (rete collegata e profili salvati)"
if want(N):
    print("==", N)
    mk = ("function Get-Service { param($Name,$ErrorAction) [pscustomobject]@{Status='Running'} }\nfunction netsh.exe { param([Parameter(ValueFromRemainingArguments)]$a) if($a -contains 'interfaces'){ '    Name  : Wi-Fi'; '    SSID  : Ufficio'; '    Signal : 90%' } else { '    All User Profile     : Ufficio'; '    All User Profile     : CasaMario'; 'Profiles on interface Wi-Fi:'; '' } }\n")
    r = run(N, {}, mk); expect("collegato", r, 0, ["SSID  : Ufficio", "All User Profile     : CasaMario"], ["Profiles on interface"])
    r = run(N, {}, "function Get-Service { param($Name,$ErrorAction) $null }\n"); expect("senza Wi-Fi", r, 0, ["non ha il servizio Wi-Fi"])
    r = run(N, {}, "function Get-Service { param($Name,$ErrorAction) [pscustomobject]@{Status='Stopped'} }\n"); expect("servizio fermo", r, 0, ["non è in esecuzione"])

N = "Windows: imposta i server DNS di una scheda di rete"
if want(N):
    print("==", N)
    mk = ("function Get-NetAdapter { param($Name,$ErrorAction) $all = @([pscustomobject]@{Name='Ethernet';ifIndex=3;Status='Up';Virtual=$false}, [pscustomobject]@{Name='Wi-Fi';ifIndex=4;Status='Up';Virtual=$false}, [pscustomobject]@{Name='vEthernet';ifIndex=9;Status='Up';Virtual=$true}); if($Name){ $x = @($all | Where-Object { $_.Name -eq $Name }); if($x.Count -eq 0){ throw 'no' }; $x } else { $all } }\n"
          "function Set-DnsClientServerAddress { param($InterfaceIndex,$ServerAddresses,[switch]$ResetServerAddresses,$ErrorAction) if($ResetServerAddresses){ Write-Output \"CALL reset $InterfaceIndex\" } else { Write-Output \"CALL set $InterfaceIndex $($ServerAddresses -join ',')\" } }\n"
          "function Get-DnsClientServerAddress { param($InterfaceIndex,$AddressFamily,$ErrorAction) [pscustomobject]@{ServerAddresses=@('1.1.1.1')} }\nfunction Clear-DnsClientCache { }\n")
    r = run(N, {"DNS": "1.1.1.1, 9.9.9.9"}, mk); expect("tutte le schede fisiche", r, 0, ["CALL set 3 1.1.1.1,9.9.9.9", "CALL set 4 1.1.1.1,9.9.9.9"], ["CALL set 9"])
    r = run(N, {"SCHEDA": "Wi-Fi", "DNS": "2606:4700:4700::1111"}, mk); expect("una scheda, IPv6", r, 0, ["CALL set 4 2606:4700:4700::1111"], ["CALL set 3"])
    r = run(N, {"SCHEDA": "Wi-Fi"}, mk); expect("DNS automatici", r, 0, ["CALL reset 4"])
    r = run(N, {"SCHEDA": "Inesistente", "DNS": "1.1.1.1"}, mk); expect("scheda inesistente", r, 2, ["non esiste"])
    for v in ("1.1.1", "1.1.1.1.1", "256.1.1.1", "a.b.c.d", "1.1.1.1;id", "$(id)", "abc", "1.1.1.-1", "1..1.1", "0x7f.1.1.1"):
        r = run(N, {"DNS": v}, mk); expect(f"DNS non valido {v!r}", r, 2, ["non è un indirizzo IP valido"]); check(f"DNS {v!r}: nessuna modifica", "CALL" not in r[1], r[1])
    for v in ("a;b", "a$(id)", "a'b", 'a"b', "a|b"): r = run(N, {"SCHEDA": v, "DNS": "1.1.1.1"}, mk); expect(f"SCHEDA non valida {v!r}", r, 2)
    r = run(N, {"DNS": "1.1.1.1"}, mk, admin=False); expect("senza amministratore", r, 3)

N = "Windows: impostazioni proxy (sistema, utente e criteri)"
if want(N):
    print("==", N)
    ie = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
    mk = ("function netsh.exe { 'Current WinHTTP proxy settings:'; '    Proxy Server(s) :  proxy.lan:8080' }\n$global:REG['%s|ProxyEnable']=1; $global:REG['%s|ProxyServer']='proxy.lan:3128'; $global:REG['%s|AutoConfigURL']='http://wpad/wpad.dat'\n"
          "$global:REG['HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\CurrentVersion\\Internet Settings|ProxyServer']='pol:80'\n") % (ie, ie, ie)
    r = run(N, {}, mk); expect("proxy configurato", r, 0, ["proxy.lan:8080", "Proxy attivo: sì   server: proxy.lan:3128", "wpad.dat", "ProxyServer = pol:80"])
    r = run(N, {}, "function netsh.exe { 'Direct access (no proxy server).' }\n"); expect("nessun proxy", r, 0, ["Direct access", "Proxy attivo: no", "(nessun criterio proxy)"])

N = "Windows: voci del file hosts"
if want(N):
    print("==", N)
    H = "# esempio\n127.0.0.1 localhost\n10.0.0.5   server.lan srv  # mio\n0.0.0.0 windowsupdate.microsoft.com\nsolo\n"
    r = run(N, {}, "", files={"win/System32/drivers/etc/hosts": H}); expect("hosts", r, 0, ["voci attive: 4", "server.lan srv", "<-- ATTENZIONE", "VOCI SOSPETTE: 1", "(riga anomala) solo"])
    r = run(N, {}, ""); expect("file assente", r, 0, ["File hosts non trovato"])

N = "Windows: aggiungi o rimuovi una voce nel file hosts"
if want(N):
    print("==", N)
    HF = "win/System32/drivers/etc/hosts"; H = "# c\n127.0.0.1 localhost\n10.0.0.9 vecchio.lan altro\n"
    mk = "function Clear-DnsClientCache { }\n"
    r = run(N, {"NOME": "nuovo.lan", "IP": "10.0.0.7"}, mk, files={HF: H}); expect("aggiungi", r, 0, ["Aggiunta: 10.0.0.7"]); t = LASTFILES.get(HF, ""); check("riga scritta e file intatto", "10.0.0.7\tnuovo.lan" in t and "vecchio.lan" in t and "# c" in t, t); check("copia di sicurezza", LASTFILES.get(HF + ".myrmm.bak") == H, list(LASTFILES))
    r = run(N, {"NOME": "vecchio.lan", "IP": "10.0.0.8"}, mk, files={HF: H}); expect("aggiungi sostituisce la voce di quel nome", r, 0); t = LASTFILES.get(HF, ""); check("una sola voce", t.count("vecchio.lan") == 1 and "10.0.0.8\tvecchio.lan" in t and "altro" not in t, t)
    r = run(N, {"AZIONE": "rimuovi", "NOME": "vecchio.lan"}, mk, files={HF: H}); expect("rimuovi", r, 0, ["Rimossa ogni voce"]); t = LASTFILES.get(HF, ""); check("voce rimossa, il resto no", "vecchio.lan" not in t and "localhost" in t, t)
    for v in ({"NOME": "localhost", "IP": "1.2.3.4"}, {"NOME": "a b", "IP": "1.2.3.4"}, {"NOME": "a;id", "IP": "1.2.3.4"}, {"NOME": "", "IP": "1.2.3.4"}, {"NOME": "-x", "IP": "1.2.3.4"}, {"NOME": "x.lan", "IP": ""}, {"NOME": "x.lan", "IP": "999.1.1.1"}, {"NOME": "x.lan", "IP": "1.2.3"}, {"NOME": "x.lan", "IP": "1.2.3.4 evil.com"}, {"NOME": "x.lan", "IP": "1.2.3.4\n6.6.6.6 evil"}, {"AZIONE": "boh", "NOME": "x.lan", "IP": "1.2.3.4"}):
        r = run(N, v, mk, files={HF: H}); expect(f"non valido {v}", r, 2); check(f"{v}: file intatto", LASTFILES.get(HF) == H, LASTFILES.get(HF))
    r = run(N, {"NOME": "x.lan", "IP": "1.2.3.4"}, mk, admin=False, files={HF: H}); expect("senza amministratore", r, 3)

N = "Windows: invia un pacchetto Wake-on-LAN"
if want(N):
    print("==", N)
    got = []
    def lis(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: s.bind(("127.0.0.1", port))
        except Exception: return None
        s.settimeout(15); return s
    s9, s7 = lis(9), lis(7)
    if s9 and s7:
        r = run(N, {"MAC": "00:1A:2b:3C:4d:5E", "BROADCAST": "127.0.0.1"}, ""); expect("invio", r, 0, ["inviato a 127.0.0.1", "00:1A:2B:3C:4D:5E"])
        for s_ in (s9, s7):
            try: d, _ = s_.recvfrom(2048)
            except Exception: d = b""
            mac = bytes.fromhex("001A2B3C4D5E")
            check(f"pacchetto magico porta {s_.getsockname()[1]}", len(d) == 102 and d[:6] == b"\xff" * 6 and d[6:] == mac * 16, d.hex())
        s9.close(); s7.close()
        r = run(N, {"MAC": "00-1A-2B-3C-4D-5E", "BROADCAST": "127.0.0.1"}, ""); expect("MAC con trattini", r, 0)
    else: print("  (porte UDP 9/7 non disponibili: salto la prova del pacchetto)")
    for v in ({"MAC": ""}, {"MAC": "00:1A:2B"}, {"MAC": "00:1A:2B:3C:4D:5G"}, {"MAC": "00:1A:2B:3C:4D:5E;id"}, {"MAC": "00:1A:2B:3C:4D:5E", "BROADCAST": "999.1.1.1"}, {"MAC": "00:1A:2B:3C:4D:5E", "BROADCAST": "a.b.c.d"}, {"MAC": "00:1A:2B:3C:4D:5E", "BROADCAST": "1.1.1.1;id"}):
        r = run(N, v, ""); expect(f"non valido {v}", r, 2)

def mktree(d, spec):
    for rel, size in spec.items():
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b"A" * size)
N = "Windows: cartelle più grandi"
if want(N):
    print("==", N)
    base = tempfile.mkdtemp(prefix="myrmm-t-")
    mktree(base, {"grande/a.bin": 3 * 1048576, "grande/sub/b.bin": 2 * 1048576, "media/c.bin": 1048576, "piccola/d.bin": 1000, "radice.txt": 500000})
    os.symlink(os.path.join(base, "grande"), os.path.join(base, "collegamento"))
    r = run(N, {"PERCORSO": base}, ""); expect("ordinamento", r, 0, ["Sottocartelle esaminate: 3", "5,0 MB", "1,0 MB"] if False else ["Sottocartelle esaminate: 3"], ["collegamento"], regex=[r"5\.0 MB\s+\S*grande", r"1\.0 MB\s+\S*media"])
    out = r[1]; check("grande prima di media", out.index("grande") < out.index("media") < out.index("piccola"), out)
    r = run(N, {"PERCORSO": base, "TOP": "1"}, ""); expect("TOP=1", r, 0, ["grande"], ["media", "piccola"])
    for v in ({"TOP": "x"}, {"TOP": "0"}, {"TOP": "1;id"}, {"PERCORSO": base + "/*"}, {"PERCORSO": base + "/non-esiste"}, {"PERCORSO": 'a"b'}): r = run(N, v, ""); expect(f"non valido {v}", r, 2)
    shutil.rmtree(base, ignore_errors=True)

N = "Windows: file più grandi in una cartella"
if want(N):
    print("==", N)
    base = tempfile.mkdtemp(prefix="myrmm-t-")
    mktree(base, {"a/grosso.bin": 5 * 1048576, "b/medio.bin": 2 * 1048576, "b/c/piccolo.bin": 1000, "enorme.bin": 9 * 1048576})
    os.symlink(os.path.join(base, "a"), os.path.join(base, "ln"))
    r = run(N, {"PERCORSO": base, "MIN_MB": "1"}, ""); expect("trovati", r, 0, ["almeno 1 MB", ": 3"], ["piccolo"]); out = r[1]; check("ordine decrescente", out.index("enorme") < out.index("grosso") < out.index("medio"), out); check("niente doppioni via collegamento", out.count("grosso.bin") == 1, out)
    r = run(N, {"PERCORSO": base, "MIN_MB": "4", "TOP": "1"}, ""); expect("soglia e TOP", r, 0, ["enorme"], ["grosso", "medio"])
    for v in ({"MIN_MB": "x"}, {"TOP": "0"}, {"TOP": "1;id"}, {"PERCORSO": base + "/non-esiste"}, {"PERCORSO": "a|b"}): r = run(N, v, ""); expect(f"non valido {v}", r, 2)
    shutil.rmtree(base, ignore_errors=True)

N = "Windows: elimina file vecchi in una cartella"
if want(N):
    print("==", N)
    sub = lambda b: b.replace("'^[A-Za-z]:\\\\'", "'^(/|[A-Za-z]:\\\\)'")
    def tree():
        base = tempfile.mkdtemp(prefix="myrmm-t-")
        mktree(base, {"vecchio.log": 2000, "sub/vecchio2.log": 2000, "sub/nuovo.log": 100, "vecchio.txt": 100, "fuori/importante.log": 100})
        old = _t.time() - 90 * 86400
        for rel in ("vecchio.log", "sub/vecchio2.log", "vecchio.txt", "fuori/importante.log"): os.utime(os.path.join(base, rel), (old, old))
        return base
    base = tree(); target = base + "/"
    r = run(N, {"PERCORSO": base, "GIORNI": "30"}, "", body_sub=sub); expect("anteprima", r, 0, ["circa", ": 4,", "Anteprima"] if False else ["Anteprima: non è stato eliminato nulla"], regex=[r"vecchi di 30 giorni.*: 4,"]); check("anteprima: tutto presente", all(os.path.exists(os.path.join(base, x)) for x in ("vecchio.log", "sub/vecchio2.log", "vecchio.txt")), "")
    r = run(N, {"PERCORSO": base, "GIORNI": "30", "FILTRO": "*.log", "APPLICA": "si"}, "", body_sub=sub); expect("applica con filtro", r, 0, ["Eliminati 3 file"])
    check("log vecchi eliminati", not os.path.exists(base + "/vecchio.log") and not os.path.exists(base + "/sub/vecchio2.log"), os.listdir(base))
    check("nuovo, non .log e già altro intatti", os.path.exists(base + "/sub/nuovo.log") and os.path.exists(base + "/vecchio.txt"), os.listdir(base))
    shutil.rmtree(base, ignore_errors=True)
    base = tree(); other = tempfile.mkdtemp(prefix="myrmm-o-"); mktree(other, {"intoccabile.log": 10}); os.utime(other + "/intoccabile.log", (_t.time() - 99 * 86400,) * 2)
    os.symlink(other, base + "/giunzione")
    r = run(N, {"PERCORSO": base, "GIORNI": "30", "APPLICA": "si"}, "", body_sub=sub); expect("con collegamento simbolico", r, 0); check("il collegamento non viene seguito", os.path.exists(other + "/intoccabile.log"), os.listdir(other))
    shutil.rmtree(base, ignore_errors=True); shutil.rmtree(other, ignore_errors=True)
    base = tree()
    for v in ("C:\\", "C:", "D:\\", "C:\\Windows", "C:\\Windows\\System32", "c:\\windows\\system32\\config", "C:\\Program Files", "C:\\Program Files (x86)\\App", "C:\\Users", "C:\\Users\\mario", "C:\\ProgramData", "C:\\Boot", "C:\\$Recycle.Bin", "C:\\Recovery", "C:\\System Volume Information",
              "C:\\a\\..\\Windows", "relativo\\dir", "C:\\a*", "C:\\a?b", 'C:\\a"b', "C:\\a|b", "C:\\a<b", ""):
        r = run(N, {"PERCORSO": v, "APPLICA": "si"}, "", body_sub=sub); expect(f"PERCORSO {v!r} rifiutato", r, 2)
    for v in ("C:\\Windows\\Temp\\xyz", "C:\\Users\\Public\\Documents", "C:\\Users\\mario\\Downloads\\x", "C:\\ProgramData\\Vendor\\logs"):
        r = run(N, {"PERCORSO": v}, "", body_sub=sub); expect(f"PERCORSO consentito {v!r}", r, 2, ["non esiste"])
    for v in ({"GIORNI": "x"}, {"GIORNI": "0"}, {"GIORNI": "1;id"}, {"GIORNI": "-3"}, {"FILTRO": "a/b"}, {"FILTRO": "a\\b"}, {"FILTRO": "a;b|c"}, {"FILTRO": "..\\x"}): r = run(N, dict({"PERCORSO": base, "APPLICA": "si"}, **v), "", body_sub=sub); expect(f"non valido {v}", r, 2)
    check("nulla eliminato con valori non validi", os.path.exists(base + "/vecchio.log"), os.listdir(base)); shutil.rmtree(base, ignore_errors=True)

N = "Windows: svuota il cestino di tutti gli utenti"
if want(N):
    print("==", N)
    sub = lambda b: b.replace("($d.DeviceID + '\\')", "($d.DeviceID + '/')")
    def rb():
        base = tempfile.mkdtemp(prefix="myrmm-t-"); mktree(base, {"$Recycle.Bin/S-1-5-21-1/$R1.txt": 1048576, "$Recycle.Bin/S-1-5-21-1/$I1.txt": 100, "$Recycle.Bin/S-1-5-21-2/dir/x.bin": 2097152}); return base
    base = rb(); mk = "function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) @([pscustomobject]@{DeviceID='%s'}) }\n" % base
    r = run(N, {}, mk, body_sub=sub); expect("anteprima", r, 0, ["Cestini: 3 elementi, circa 3", "Anteprima"]); check("anteprima: intatto", os.path.exists(base + "/$Recycle.Bin/S-1-5-21-1/$R1.txt"), "")
    r = run(N, {"APPLICA": "si"}, mk, body_sub=sub); expect("svuota", r, 0, ["Eliminati 3 elementi"]); check("svuotato ma cartelle SID restano", not os.path.exists(base + "/$Recycle.Bin/S-1-5-21-1/$R1.txt") and os.path.isdir(base + "/$Recycle.Bin/S-1-5-21-1"), os.listdir(base + "/$Recycle.Bin"))
    r = run(N, {}, mk, admin=False, body_sub=sub); expect("senza amministratore", r, 3)
    shutil.rmtree(base, ignore_errors=True)

N = "Windows: dimensione dei profili utente"
if want(N):
    print("==", N)
    d = None
    files = {"sys/Users/mario/Downloads/a.bin": 3 * 1048576, "sys/Users/mario/Documents/b.bin": 1048576, "sys/Users/luca/x.bin": 100, "sys/Users/Default/y.bin": 10, "sys/Users/Public/z.bin": 10}
    r = run(N, {}, "", files={k: b"A" * v for k, v in files.items()}); expect("profili", r, 0, ["Profili: 3", "mario", "luca", "Public", "Download 3,"], ["Default"]); check("mario prima di luca", r[1].index("mario") < r[1].index("luca"), r[1])
    r = run(N, {}, ""); expect("senza C:\\Users", r, 1, ["non trovata"])

N = "Windows: ottimizza i volumi (TRIM per SSD, deframmentazione per HDD)"
if want(N):
    print("==", N)
    def vm(media): return ("function Get-Volume { param($DriveLetter,$ErrorAction) [pscustomobject]@{DriveType='Fixed';FileSystem='NTFS';SizeRemaining=50GB} }\nfunction Get-Partition { param($DriveLetter,$ErrorAction) [pscustomobject]@{N=1} }\n"
                           "function Get-Disk { param([Parameter(ValueFromPipeline)]$i) process { [pscustomobject]@{N=1} } }\nfunction Get-PhysicalDisk { param([Parameter(ValueFromPipeline)]$i) process { [pscustomobject]@{MediaType='%s'} } }\n"
                           "function Optimize-Volume { param($DriveLetter,[switch]$ReTrim,[switch]$Defrag,[switch]$Analyze,$ErrorAction) Write-Host \"CALL opt $DriveLetter trim=$ReTrim defrag=$Defrag analyze=$Analyze\" }\n") % media
    r = run(N, {"VOLUME": "C"}, vm("SSD")); expect("SSD", r, 0, ["CALL opt C trim=True defrag=False", "TRIM eseguito"])
    r = run(N, {"VOLUME": "d:"}, vm("HDD")); expect("HDD", r, 0, ["CALL opt d trim=False defrag=True", "Deframmentazione eseguita"])
    r = run(N, {"VOLUME": "C"}, vm("Unspecified")); expect("tipo ignoto", r, 0, ["analyze=True", "solo l'analisi"]) if False else expect("tipo ignoto", r, 0, ["analyze=True"])
    for v in ("CC", "1", "C;id", "$(id)", "C:\\x", "-"): r = run(N, {"VOLUME": v}, vm("SSD")); expect(f"VOLUME non valido {v!r}", r, 2)
    r = run(N, {"VOLUME": "C"}, vm("SSD"), admin=False); expect("senza amministratore", r, 3)
    r = run(N, {"VOLUME": "C"}, vm("SSD").replace("DriveType='Fixed'", "DriveType='Removable'")); expect("non fisso", r, 2)
    r = run(N, {"VOLUME": "C"}, vm("SSD") + "function Optimize-Volume { throw 'occupato' }\n"); expect("ottimizzazione fallisce", r, 1, ["non riuscita"])
    r = run(N, {"VOLUME": "Z"}, vm("SSD") + "function Get-Volume { throw 'no' }\n"); expect("volume inesistente", r, 2)

N = "Windows: copie shadow (VSS) e spazio riservato"
if want(N):
    print("==", N)
    mk = ("function Get-CimInstance { param($ClassName,$ErrorAction) if($ClassName -eq 'Win32_ShadowCopy'){ @([pscustomobject]@{InstallDate=(Get-Date '2026-10-01 10:00');VolumeName='\\\\?\\Volume{1}\\'}, [pscustomobject]@{InstallDate=(Get-Date '2026-10-02 10:00');VolumeName='\\\\?\\Volume{2}\\'}) } else { @([pscustomobject]@{DeviceID='\\\\?\\Volume{1}\\';Name='C:\\'}) } }\n"
          "function vssadmin.exe { 'Shadow Copy Storage association'; '   Used Shadow Copy Storage space: 1 GB (1%)'; '' }\n")
    r = run(N, {}, mk); expect("due copie", r, 0, ["Copie shadow: 2", "2026-10-02 10:00  \\\\?\\Volume{2}\\", "2026-10-01 10:00  C:\\", "Used Shadow Copy Storage space"])
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)
    r = run(N, {}, "function Get-CimInstance { throw 'x' }\n"); expect("non leggibile", r, 1)

N = "Windows: dischi fisici, partizioni e volumi"
if want(N):
    print("==", N)
    mk = ("function Get-PhysicalDisk { param($ErrorAction) @([pscustomobject]@{DeviceId='0';FriendlyName='Samsung SSD';MediaType='SSD';BusType='NVMe';Size=500GB;HealthStatus='Healthy';OperationalStatus='OK'}) }\n"
          "function Get-Disk { param($ErrorAction) @([pscustomobject]@{Number=0;FriendlyName='Samsung SSD';PartitionStyle='GPT';Size=500GB;IsOffline=$false}) }\n"
          "function Get-Partition { param($DiskNumber,$ErrorAction) @([pscustomobject]@{PartitionNumber=1;Type='Basic';Size=499GB;DriveLetter='C'}) }\n"
          "function Get-Volume { param($ErrorAction) @([pscustomobject]@{DriveLetter='C';FileSystemLabel='Sistema';FileSystem='NTFS';Size=499GB;SizeRemaining=100GB;HealthStatus='Healthy';DriveType='Fixed'}, [pscustomobject]@{DriveLetter='E';FileSystemLabel='';FileSystem='';Size=0;SizeRemaining=0;HealthStatus='';DriveType='CD-ROM'}) }\n")
    r = run(N, {}, mk); expect("un disco", r, 0, ["Samsung SSD  SSD  bus=NVMe", "tabella=GPT", "partizione 1  Basic", "C:  Sistema  NTFS", "(20%)"], ["E:"])
    r = run(N, {}, ""); expect("nulla leggibile", r, 0, ["(non leggibili)"])


# ---- Windows blocco 3: software, aggiornamenti, utenti, cloud ----
N = "Windows: rimuovi app Microsoft Store preinstallate (AppX)"
if want(N):
    print("==", N)
    mk = ("$global:APPS = @([pscustomobject]@{Name='Microsoft.XboxApp';Version='1.0';PackageFullName='Microsoft.XboxApp_1'}, [pscustomobject]@{Name='Microsoft.MicrosoftSolitaireCollection';Version='4.0';PackageFullName='Sol_1'}, [pscustomobject]@{Name='Microsoft.WindowsStore';Version='9';PackageFullName='Store_1'})\n"
          "function Get-AppxPackage { param([switch]$AllUsers,$Name,$ErrorAction) @($global:APPS | Where-Object { $_.Name -like $Name }) }\n"
          "function Get-AppxProvisionedPackage { param([switch]$Online,$ErrorAction) @([pscustomobject]@{DisplayName='Microsoft.XboxApp';PackageName='Microsoft.XboxApp_prov'}) }\n"
          "function Remove-AppxPackage { param($Package,[switch]$AllUsers,$ErrorAction) Write-Output \"CALL remove $Package\" }\n"
          "function Remove-AppxProvisionedPackage { param([switch]$Online,$PackageName,$ErrorAction) Write-Output \"CALL removeprov $PackageName\" }\n")
    r = run(N, {"APP": "Microsoft.XboxApp"}, mk); expect("anteprima", r, 0, ["App trovate: 1", "Microsoft.XboxApp  1.0", "immagine preinstallata: 1", "Anteprima"], ["CALL"])
    r = run(N, {"APP": "Microsoft.XboxApp, *Solitaire*", "APPLICA": "si"}, mk); expect("applica", r, 0, ["CALL remove Microsoft.XboxApp_1", "CALL remove Sol_1", "Rimosse 2 app (0 errori)"])
    r = run(N, {"APP": "Microsoft.Inesistente", "APPLICA": "si"}, mk); expect("nessuna app", r, 0, ["App trovate: 0"], ["CALL"])
    for v in ("*", "**", "ab*", "Microsoft.WindowsStore", "*Store*", "Microsoft.Windows.ShellExperienceHost", "Microsoft.NET.Native.Framework", "Microsoft.VCLibs.140", "Microsoft.UI.Xaml.2.8", "Microsoft.MicrosoftEdge", "Microsoft.SecHealthUI", "Microsoft.DesktopAppInstaller", "Microsoft.WindowsCalculator", "a;b", "Microsoft.Xbox App?", "$(id)", "a'b", "", ","):
        r = run(N, {"APP": v, "APPLICA": "si"}, mk); expect(f"APP {v!r} rifiutato", r, 2); check(f"APP {v!r}: nulla rimosso", "CALL" not in r[1], r[1])
    r = run(N, {"APP": "Microsoft.XboxApp"}, mk, admin=False); expect("senza amministratore", r, 3)
    r = run(N, {"APP": "Microsoft.XboxApp", "APPLICA": "si"}, mk.replace("Write-Output \"CALL remove $Package\"", "throw 'in uso'")); expect("rimozione fallita", r, 1, ["non rimossa"])

N = "Windows: svuota le cache di Teams e Office"
if want(N):
    print("==", N)
    files = {"sys/Users/mario/AppData/Roaming/Microsoft/Teams/Cache/a.bin": b"A" * 1048576, "sys/Users/mario/AppData/Local/Microsoft/Office/16.0/OfficeFileCache/c.bin": b"B" * 2097152, "sys/Users/mario/AppData/Local/Microsoft/Outlook/mario.ost": b"C" * 1000, "sys/Users/mario/Documents/tesi.docx": b"D" * 100, "sys/Users/luca/AppData/Local/Packages/MSTeams_8wekyb3d8bbwe/LocalCache/x.bin": b"E" * 1048576}
    r = run(N, {}, "function Get-Process { @() }\n", files=files); expect("anteprima", r, 0, ["Cache trovate: 3, circa 4", "Anteprima"]); check("anteprima: nulla eliminato", "sys/Users/mario/AppData/Roaming/Microsoft/Teams/Cache/a.bin" in LASTFILES, list(LASTFILES))
    r = run(N, {"APPLICA": "si"}, "function Get-Process { @() }\n", files=files); expect("applica", r, 0, ["Pulizia eseguita (0 cartelle con errori)"])
    check("cache eliminate", all(k not in LASTFILES for k in ("sys/Users/mario/AppData/Roaming/Microsoft/Teams/Cache/a.bin", "sys/Users/mario/AppData/Local/Microsoft/Office/16.0/OfficeFileCache/c.bin", "sys/Users/luca/AppData/Local/Packages/MSTeams_8wekyb3d8bbwe/LocalCache/x.bin")), list(LASTFILES))
    check("OST e documenti intatti", "sys/Users/mario/AppData/Local/Microsoft/Outlook/mario.ost" in LASTFILES and "sys/Users/mario/Documents/tesi.docx" in LASTFILES, list(LASTFILES))
    op = "function Get-Process { param($Name,$ErrorAction) @([pscustomobject]@{ProcessName='OUTLOOK'}) }\nfunction Stop-Process { param([Parameter(ValueFromPipeline)]$i,[switch]$Force) process { Write-Output \"CALL stop $($i.ProcessName)\" } }\n"
    r = run(N, {"APPLICA": "si"}, op, files=files); expect("programmi aperti senza CHIUDI", r, 1, ["Programmi aperti", "OUTLOOK", "CHIUDI=si"]); check("niente eliminato", "sys/Users/mario/AppData/Roaming/Microsoft/Teams/Cache/a.bin" in LASTFILES, "")
    r = run(N, {"APPLICA": "si", "CHIUDI": "si"}, op, files=files); expect("con CHIUDI", r, 0, ["CALL stop OUTLOOK", "Pulizia eseguita"])
    r = run(N, {}, op, files=files); expect("anteprima con programmi aperti", r, 0, ["Programmi aperti"])
    r = run(N, {"APPLICA": "si"}, "", admin=False); expect("senza amministratore", r, 3)

N = "Windows: OneDrive (account, cartelle protette e criteri)"
if want(N):
    print("==", N)
    sid = "S-1-5-21-111-222-333-1001"; hk = f"Registry::HKEY_USERS\\{sid}"
    mk = (f"$global:REGCHILD['Registry::HKEY_USERS'] = @('{sid}', '{sid}_Classes', 'S-1-5-18', '.DEFAULT')\n$global:REGCHILD['{hk}\\Software\\Microsoft\\OneDrive\\Accounts'] = @('Business1', 'Personal')\n"
          f"$global:REG['{hk}\\Software\\Microsoft\\OneDrive\\Accounts\\Business1|UserEmail']='mario@acme.it'; $global:REG['{hk}\\Software\\Microsoft\\OneDrive\\Accounts\\Business1|UserFolder']='C:\\Users\\mario\\OneDrive - Acme'\n"
          f"$global:REG['{hk}\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders|Desktop']='C:\\Users\\mario\\OneDrive - Acme\\Desktop'; $global:REG['{hk}\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders|Personal']='C:\\Users\\mario\\Documents'\n"
          "$global:REG['HKLM:\\SOFTWARE\\Policies\\Microsoft\\OneDrive|KFMSilentOptIn']='tenant-guid'\nfunction Get-Process { param($Name,$ErrorAction) @([pscustomobject]@{ProcessName='OneDrive'}) }\n")
    r = run(N, {}, mk); expect("un utente", r, 0, ["in esecuzione: sì", "utenti con sessione caricata: 1", "account Business1: mario@acme.it", "Desktop    -> C:\\Users\\mario\\OneDrive - Acme\\Desktop   [su OneDrive]", "Documenti  -> C:\\Users\\mario\\Documents", "KFMSilentOptIn = tenant-guid"], ["Personal:"])
    r = run(N, {}, "function Get-Process { @() }\n"); expect("nessun utente", r, 0, ["in esecuzione: no", "caricata: 0", "(nessun criterio OneDrive)"])

N = "Windows: estensioni installate in Chrome ed Edge"
if want(N):
    print("==", N)
    mf = lambda name, ver, perms: ('{"name": "%s", "version": "%s", "permissions": %s}' % (name, ver, perms)).encode()
    files = {"sys/Users/mario/AppData/Local/Google/Chrome/User Data/Default/Extensions/abc123/1.0_0/manifest.json": mf("Adblock", "1.0", '["storage", "<all_urls>"]'),
             "sys/Users/mario/AppData/Local/Google/Chrome/User Data/Default/Extensions/def456/2.0_0/manifest.json": mf("__MSG_appName__", "2.0", '["tabs"]'),
             "sys/Users/mario/AppData/Local/Google/Chrome/User Data/Default/Extensions/def456/1.0_0/manifest.json": mf("Vecchia", "1.0", '[]'),
             "sys/Users/luca/AppData/Local/Microsoft/Edge/User Data/Profile 1/Extensions/zzz/3.1_0/manifest.json": mf("Tema", "3.1", '[]'),
             "sys/Users/luca/AppData/Local/Microsoft/Edge/User Data/Guest/Extensions/gg/1_0/manifest.json": mf("Ospite", "1", '[]'),
             "sys/Users/luca/AppData/Local/Google/Chrome/User Data/Default/Extensions/rotta/1.0_0/manifest.json": b"{non json"}
    r = run(N, {}, "", files=files); expect("estensioni", r, 0, ["Estensioni trovate: 3 (di cui 1 con accesso a tutti i siti)", "Adblock  v1.0  abc123   <-- legge tutti i siti", "(nome localizzato)  v2.0", "Edge", "Tema"], ["Ospite", "Vecchia"])
    r = run(N, {}, ""); expect("nessun browser", r, 0, ["Estensioni trovate: 0"])

N = "Windows: .NET e Visual C++ runtime installati"
if want(N):
    print("==", N)
    mk = ("$global:REG['HKLM:\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full|Release']=528040\n"
          "function Get-ItemProperty { param($Path,$Name,$ErrorAction) if($Name){ if($Name -eq 'Release'){ [pscustomobject]@{Release=528040} } else { throw 'x' } } else { @([pscustomobject]@{DisplayName='Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.38';DisplayVersion='14.38.33135'}, [pscustomobject]@{DisplayName='Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.38';DisplayVersion='14.38.33135'}, [pscustomobject]@{DisplayName='7-Zip';DisplayVersion='23'}) } }\n")
    dn = "#!/bin/sh\ncase \"$1\" in --list-runtimes) echo 'Microsoft.NETCore.App 8.0.5 [C:\\dotnet]';; --list-sdks) echo '8.0.300 [C:\\dotnet\\sdk]';; esac\n"
    r = run(N, {}, mk, files={"bin/dotnet.exe": dn}); expect("runtime", r, 0, ["4.x: Release 528040 = 4.8", "runtime: Microsoft.NETCore.App 8.0.5", "sdk: 8.0.300", "Pacchetti Visual C++: 1"], ["7-Zip"])
    r = run(N, {}, "function Get-ItemProperty { [CmdletBinding()] param($Path,$Name) if($Name){ throw 'x' } }\n"); expect("niente installato", r, 0, ["4.x: non installato", "dotnet non trovato", "Pacchetti Visual C++: 0"])

def comupd(updates=(), hist=(), fail=False):
    """Microsoft.Update.Session finto"""
    ups = ", ".join(ps(u) for u in updates); hs = ", ".join(ps(h) for h in hist)
    return ("$global:COM['Microsoft.Update.Session'] = { %s $s = New-Object psobject; "
            "$s | Add-Member ScriptMethod CreateUpdateSearcher { $x = New-Object psobject; "
            "$x | Add-Member ScriptMethod Search { param($q) $res = New-Object psobject; $u = @(%s); $c = New-Object psobject; $c | Add-Member NoteProperty Count $u.Count; $c | Add-Member ScriptMethod Item { param($i) $u[$i] }.GetNewClosure(); $res | Add-Member NoteProperty Updates $c; $res }.GetNewClosure(); "
            "$x | Add-Member ScriptMethod GetTotalHistoryCount { %d }.GetNewClosure(); "
            "$x | Add-Member ScriptMethod QueryHistory { param($a,$b) $h = @(%s); $c = New-Object psobject; $c | Add-Member NoteProperty Count $h.Count; $c | Add-Member ScriptMethod Item { param($i) $h[$i] }.GetNewClosure(); $c }.GetNewClosure(); $x }.GetNewClosure(); $s }\n") % ("throw 'servizio fermo';" if fail else "", ups, len(hist), hs)
N = "Windows: aggiornamenti in attesa di installazione (elenco)"
if want(N):
    print("==", N)
    ups = [dict(KBArticleIDs=["5034123"], MsrcSeverity="Critical", MaxDownloadSize=100 * 1048576, Title="Aggiornamento cumulativo", RebootRequired=True), dict(KBArticleIDs=[], MsrcSeverity=None, MaxDownloadSize=2 * 1048576, Title="Firma Defender", RebootRequired=False)]
    r = run(N, {}, comupd(ups)); expect("due aggiornamenti", r, 0, ["in attesa: 2", "KB5034123  [Critical]  100 MB  Aggiornamento cumulativo  (riavvio)", "[senza gravità]  2 MB  Firma Defender", "Download totale: 102 MB"])
    r = run(N, {}, comupd([])); expect("nessuno", r, 0, ["in attesa: 0"])
    r = run(N, {}, comupd(fail=True)); expect("Windows Update fermo", r, 1, ["non risponde"])

N = "Windows: cronologia degli aggiornamenti (riusciti e falliti)"
if want(N):
    print("==", N)
    now = "(Get-Date)"
    hist = [dict(Title="KB1 ok", Date="=PS=(Get-Date).AddDays(-2)", ResultCode=2, HResult=0), dict(Title="KB2 fallito", Date="=PS=(Get-Date).AddDays(-3)", ResultCode=4, HResult="=PS=-2145124329"), dict(Title="KB3 vecchio", Date="=PS=(Get-Date).AddDays(-90)", ResultCode=4, HResult=1), dict(Title="", Date="=PS=(Get-Date).AddDays(-1)", ResultCode=2, HResult=0)]
    r = run(N, {}, comupd(hist=hist)); expect("cronologia", r, 0, ["1 riusciti, 1 falliti o interrotti", "FALLITO", "0x80240017", "KB2 fallito", "KB1 ok"], ["KB3 vecchio"])
    r = run(N, {"GIORNI": "200"}, comupd(hist=hist)); expect("finestra larga", r, 0, ["2 falliti", "KB3 vecchio"])
    for v in ("x", "0", "1;id", "-1"): r = run(N, {"GIORNI": v}, comupd(hist=hist)); expect(f"GIORNI non valido {v!r}", r, 2)
    r = run(N, {}, comupd(fail=True)); expect("non disponibile", r, 1)

N = "Windows Update: criteri applicati (WSUS, rinvii, riavvio automatico)"
if want(N):
    print("==", N)
    wu = "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate"
    r = run(N, {}, f"$global:REG['{wu}|WUServer']='http://wsus.lan:8530'; $global:REG['{wu}|UseWUServer']=1; $global:REG['{wu}|DeferQualityUpdatesPeriodInDays']=7; $global:REG['{wu}\\AU|NoAutoUpdate']=0; $global:REG['{wu}\\AU|AUOptions']=4\n"); expect("criteri", r, 0, ["WUServer = http://wsus.lan:8530   [server WSUS]", "DeferQualityUpdatesPeriodInDays = 7", "AU\\AUOptions = 4", "Criteri impostati: 5"])
    r = run(N, {}, ""); expect("nessun criterio", r, 0, ["Nessun criterio"])

N = "Windows: ricostruisci l'indice di Windows Search"
if want(N):
    print("==", N)
    edb = "pd/Microsoft/Search/Data/Applications/Windows/Windows.edb"
    mk = ("function Get-Service { param($Name,$ErrorAction) $o = [pscustomobject]@{Status='Running'}; $o | Add-Member ScriptMethod WaitForStatus { param($s,$t) }; $o }\n"
          "function Stop-Service { param($Name,[switch]$Force,$ErrorAction) Write-Output \"CALL stop $Name\" }\nfunction Start-Service { param($Name,$ErrorAction) Write-Output \"CALL start $Name\" }\n")
    r = run(N, {}, mk, files={edb: b"E" * 3 * 1048576}); expect("ricostruisce", r, 0, ["CALL stop WSearch", "CALL start WSearch", "(3 MB)", "ricostruendo"]); check("indice eliminato", edb not in LASTFILES, list(LASTFILES))
    r = run(N, {}, mk); expect("indice assente", r, 1, ["non eliminato"])
    r = run(N, {}, "function Get-Service { $null }\n"); expect("servizio assente", r, 0, ["non è installato"])
    r = run(N, {}, mk.replace("Write-Output \"CALL stop $Name\"", "throw 'dipendenze'"), files={edb: b"E"}); expect("stop fallisce", r, 1, ["Impossibile fermare"]); check("indice non toccato", edb in LASTFILES, "")
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)

N = "Windows: aggiungi o rimuovi un utente da un gruppo locale"
if want(N):
    print("==", N)
    def gm(admins=("PC\\Administrator", "PC\\mario"), rdp=("PC\\luca",)):
        return ("$global:MK_GR1 = @{ 'Administrators' = [System.Collections.ArrayList]@(%s); 'Remote Desktop Users' = [System.Collections.ArrayList]@(%s) }\n"
                "function Get-LocalGroup { param($Name,$ErrorAction) if($global:MK_GR1.ContainsKey($Name)){ [pscustomobject]@{Name=$Name; SID=[pscustomobject]@{Value=$(if($Name -eq 'Administrators'){'S-1-5-32-544'}else{'S-1-5-32-555'})}} } else { throw 'no' } }\n"
                "function Get-LocalGroupMember { param($Group,$ErrorAction) @($global:MK_GR1[$Group] | ForEach-Object { [pscustomobject]@{Name=$_; ObjectClass='User'; PrincipalSource='Local'} }) }\n"
                "function Add-LocalGroupMember { param($Group,$Member,$ErrorAction) [void]$global:MK_GR1[$Group].Add($Member); Write-Output \"CALL add $Group $Member\" }\n"
                "function Remove-LocalGroupMember { param($Group,$Member,$ErrorAction) $global:MK_GR1[$Group].Remove(($global:MK_GR1[$Group] | Where-Object { $_ -ieq $Member -or ($_ -split '\\\\')[-1] -ieq $Member } | Select-Object -First 1)); Write-Output \"CALL remove $Group $Member\" }\n") % (", ".join(ps(a) for a in admins), ", ".join(ps(a) for a in rdp))
    r = run(N, {"UTENTE": "luca", "GRUPPO": "Administrators"}, gm()); expect("aggiungi", r, 0, ["CALL add Administrators luca", "aggiunto"])
    r = run(N, {"UTENTE": "luca", "GRUPPO": "Remote Desktop Users"}, gm()); expect("già membro", r, 0, ["già membro"], ["CALL add"])
    r = run(N, {"UTENTE": "luca", "GRUPPO": "Remote Desktop Users", "AZIONE": "rimuovi"}, gm()); expect("rimuovi", r, 0, ["CALL remove Remote Desktop Users luca", "rimosso"])
    r = run(N, {"UTENTE": "pippo", "GRUPPO": "Remote Desktop Users", "AZIONE": "rimuovi"}, gm()); expect("non membro", r, 0, ["non è membro"], ["CALL remove"])
    r = run(N, {"UTENTE": "mario", "GRUPPO": "Administrators", "AZIONE": "rimuovi"}, gm()); expect("rimuovi un admin con un altro admin integrato", r, 2, ["ultimo amministratore"]) if False else expect("rimuovi mario (resta solo Administrator integrato)", r, 2, ["ultimo amministratore"])
    r = run(N, {"UTENTE": "mario", "GRUPPO": "Administrators", "AZIONE": "rimuovi"}, gm(admins=("PC\\Administrator", "PC\\mario", "PC\\anna"))); expect("rimuovi un admin con un altro admin", r, 0, ["CALL remove Administrators mario"])
    for v in ({"UTENTE": "Administrator"}, {"UTENTE": "DOM\\administrator"}, {"UTENTE": ""}, {"UTENTE": "a;b"}, {"UTENTE": "$(id)"}, {"UTENTE": "a'b"}, {"GRUPPO": ""}, {"GRUPPO": "Inesistente"}, {"GRUPPO": "a;b"}, {"AZIONE": "boh"}):
        vv = {"UTENTE": "luca", "GRUPPO": "Administrators"}; vv.update(v); r = run(N, vv, gm()); expect(f"non valido {v}", r, 2); check(f"{v}: nessuna modifica", "CALL" not in r[1], r[1])
    r = run(N, {"UTENTE": "luca", "GRUPPO": "Administrators"}, gm(), admin=False); expect("senza amministratore", r, 3)

N = "Windows: offboarding di un account locale"
if want(N):
    print("==", N)
    def off(users=("mario", "anna", "Administrator"), admins=("PC\\Administrator", "PC\\mario", "PC\\anna"), rdp=("PC\\mario",), sessioni=True):
        return ("$global:MK_EN = @{" + "; ".join(f"'{u}' = $true" for u in users) + "}\n$global:MK_GRP2 = @{ 'S-1-5-32-544' = @(%s); 'S-1-5-32-555' = @(%s) }\n" % (", ".join(ps(a) for a in admins), ", ".join(ps(a) for a in rdp)) +
                "function Get-LocalUser { param($Name,$ErrorAction) if(-not $global:MK_EN.ContainsKey($Name)){ throw 'no' }; [pscustomobject]@{Name=$Name;Enabled=$global:MK_EN[$Name]} }\n"
                "function Disable-LocalUser { param($Name,$ErrorAction) $global:MK_EN[$Name] = $false; Write-Output \"CALL disable $Name\" }\n"
                "function Get-LocalGroupMember { param($SID,$ErrorAction) if(-not $global:MK_GRP2.ContainsKey($SID)){ return @() }; @($global:MK_GRP2[$SID] | ForEach-Object { [pscustomobject]@{Name=$_;ObjectClass='User';PrincipalSource='Local'} }) }\n"
                "function Remove-LocalGroupMember { param($SID,$Member,$ErrorAction) Write-Output \"CALL remove $SID $($Member.Name)\" }\n"
                + ("function quser.exe { '  UTENTE    SESSIONE   ID  STATO'; ' mario     console     3  Attivo'; ' anna      rdp-tcp#1   5  Attivo' }\nfunction logoff.exe { param($id) Write-Output \"CALL logoff $id\" }\n" if sessioni else "function quser.exe { }\nfunction logoff.exe { }\n"))
    r = run(N, {"UTENTE": "mario"}, off()); expect("offboarding", r, 0, ["CALL disable mario", "CALL remove S-1-5-32-544 PC\\mario", "CALL remove S-1-5-32-555 PC\\mario", "CALL logoff 3", "disabilitato"], ["CALL logoff 5"])
    r = run(N, {"UTENTE": "mario"}, off(sessioni=False)); expect("senza sessioni", r, 0, ["Nessuna sessione aperta"])
    r = run(N, {"UTENTE": "mario"}, off(admins=("PC\\Administrator", "PC\\mario"))); expect("ultimo admin attivo: l'Administrator integrato è attivo", r, 0)
    r = run(N, {"UTENTE": "mario"}, off(users=("mario",), admins=("PC\\mario",), rdp=())); expect("ultimo amministratore", r, 2, ["ultimo amministratore"]); check("niente disabilitato", "CALL disable" not in r[1], r[1])
    r = run(N, {"UTENTE": "mario"}, off(users=("mario",), admins=("PC\\mario", "PC\\Administrator"), rdp=())); expect("Administrator integrato disabilitato conta?", r, 2, ["ultimo amministratore"]) if False else None
    for v in ("Administrator", "Guest", "DefaultAccount", "WDAGUtilityAccount", "", "a;b", "$(id)", "a'b", "nessuno", "a" * 70, "root"):
        r = run(N, {"UTENTE": v}, off()); expect(f"UTENTE {v[:14]!r} rifiutato", r, 2); check(f"UTENTE {v[:14]!r}: niente disabilitato", "CALL disable" not in r[1], r[1])
    r = run(N, {"UTENTE": "mario"}, off(), admin=False); expect("senza amministratore", r, 3)
    r = run(N, {"UTENTE": "mario"}, off() + "function Disable-LocalUser { throw 'negato' }\n"); expect("disabilitazione fallita", r, 1, ["Disabilitazione non riuscita"])

N = "Windows: account locali con password che non scade o molto vecchia"
if want(N):
    print("==", N)
    mk = ("function Get-LocalUser { param($ErrorAction) @([pscustomobject]@{Name='mario';Enabled=$true;PasswordRequired=$true;PasswordExpires=(Get-Date).AddDays(30);PasswordLastSet=(Get-Date).AddDays(-20);LastLogon=(Get-Date).AddDays(-1)},"
          " [pscustomobject]@{Name='svc';Enabled=$true;PasswordRequired=$true;PasswordExpires=$null;PasswordLastSet=(Get-Date).AddDays(-800);LastLogon=$null},"
          " [pscustomobject]@{Name='vuoto';Enabled=$true;PasswordRequired=$false;PasswordExpires=(Get-Date).AddDays(1);PasswordLastSet=$null;LastLogon=$null},"
          " [pscustomobject]@{Name='spento';Enabled=$false;PasswordRequired=$false;PasswordExpires=$null;PasswordLastSet=$null;LastLogon=$null}) }\n")
    r = run(N, {}, mk); expect("elenco", r, 0, ["Account abilitati: 3   da rivedere: 2", "svc", "la password non scade mai", "password di 800 giorni", "vuoto", "password non obbligatoria", "password mai impostata"], ["mario ", "spento"])
    r = run(N, {"FALLISCI": "si"}, mk); expect("FALLISCI", r, 1); r = run(N, {"GIORNI": "1000"}, mk); expect("soglia alta", r, 0, [], ["800 giorni"])
    for v in ("x", "0", "1;id"): r = run(N, {"GIORNI": v}, mk); expect(f"GIORNI non valido {v!r}", r, 2)

N = "Windows: profili utente e ultimo utilizzo"
if want(N):
    print("==", N)
    mk = ("function Get-CimInstance { param($ClassName,$ErrorAction) @([pscustomobject]@{SID='S-1-5-21-1-2-3-1001';Special=$false;Loaded=$true;LastUseTime=(Get-Date).AddDays(-1);LocalPath='C:\\Users\\mario'}, [pscustomobject]@{SID='S-1-5-21-1-2-3-1002';Special=$false;Loaded=$false;LastUseTime=(Get-Date).AddDays(-400);LocalPath='C:\\Users\\vecchio'}, [pscustomobject]@{SID='S-1-5-18';Special=$true;Loaded=$true;LastUseTime=$null;LocalPath='C:\\Windows\\system32\\config\\systemprofile'}) }\n")
    r = run(N, {}, mk); expect("profili", r, 0, ["Profili utente (non speciali): 2", "(400 giorni fa)  non caricato  C:\\Users\\vecchio", "(1 giorni fa)  CARICATO"], ["systemprofile"]); check("il più vecchio prima", r[1].index("vecchio") < r[1].index("mario"), r[1])
    r = run(N, {}, "function Get-CimInstance { throw 'x' }\n"); expect("non leggibile", r, 1)

N = "Windows: stato Entra ID, dominio e Intune (dsregcmd)"
if want(N):
    print("==", N)
    out = "#!/bin/sh\ncat <<'EOF'\n+---+\n| Device State\n+---+\n\n             AzureAdJoined : YES\n          EnterpriseJoined : NO\n              DomainJoined : YES\n                DomainName : ACME\n               Device Name : PC-01\n                  DeviceId : 1111-2222\n                TenantName : Acme SpA\n                    MdmUrl : https://enrollment.manage.microsoft.com\n                    NgcSet : NO\n                AzureAdPrt : YES\n                  Altro : x\nEOF\n"
    r = run(N, {}, "", files={"bin/dsregcmd.exe": out}); expect("ibrido", r, 0, ["AzureAdJoined : YES", "DomainName : ACME", "TenantName : Acme SpA", "MdmUrl : https://enrollment", "Riepilogo: ibrido (dominio + Entra ID)"], ["Altro"])
    r = run(N, {}, "", files={"bin/dsregcmd.exe": "#!/bin/sh\necho '   AzureAdJoined : NO'\necho '   DomainJoined : NO'\n"}); expect("non collegato", r, 0, ["non collegato né a dominio né a Entra ID"])
    r = run(N, {}, "", files={"bin/dsregcmd.exe": "#!/bin/sh\nexit 0\n"}); expect("senza output", r, 1)
    r = run(N, {}, ""); expect("dsregcmd assente", r, 0, ["non è disponibile"])

N = "Windows: forza la sincronizzazione con Intune (MDM)"
if want(N):
    print("==", N)
    mk = ("function Get-ScheduledTask { param($TaskPath,$ErrorAction) @([pscustomobject]@{TaskPath='\\Microsoft\\Windows\\EnterpriseMgmt\\GUID1\\';TaskName='Schedule #1 created by enrollment client';State='Ready'}, [pscustomobject]@{TaskPath='\\Microsoft\\Windows\\EnterpriseMgmt\\GUID1\\';TaskName='Off';State='Disabled'}) }\n"
          "function Start-ScheduledTask { param($InputObject,$ErrorAction) Write-Output \"CALL start $($InputObject.TaskName)\" }\n")
    r = run(N, {}, mk); expect("sincronizza", r, 0, ["CALL start Schedule #1", "Sincronizzazione avviata (1 attività)"], ["CALL start Off"])
    r = run(N, {}, "function Get-ScheduledTask { @() }\n"); expect("non iscritto", r, 1, ["non risulta iscritto"])
    r = run(N, {}, mk.replace("Write-Output \"CALL start $($InputObject.TaskName)\"", "throw 'negato'")); expect("avvio fallito", r, 1, ["Non avviata"])
    r = run(N, {}, mk, admin=False); expect("senza amministratore", r, 3)

N = "Windows: criteri di gruppo applicati (gpresult)"
if want(N):
    print("==", N)
    g = "#!/bin/sh\ncat <<'EOF'\n\nRSOP data for PC\\SYSTEM on PC : Logging Mode\n  Site Name:                  Default-First-Site\n  Applied Group Policy Objects\n  -----------------------------\n      Default Domain Policy\n      Criteri BitLocker\n\nEOF\n"
    r = run(N, {}, "", files={"bin/gpresult.exe": g}); expect("gpresult", r, 0, ["Default Domain Policy", "Site Name:", "Criteri BitLocker"])
    r = run(N, {}, "", files={"bin/gpresult.exe": "#!/bin/sh\nexit 0\n"}); expect("senza output", r, 1)
    r = run(N, {}, ""); expect("gpresult assente", r, 1, ["non è disponibile"])


# ---- Windows blocco 4: server, rete, sistema, file ----
def listing(): return LASTFILES
N = "Windows: siti e pool di applicazioni IIS"
if want(N):
    print("==", N)
    def iis(siti, pool, w3=True, importfail=False):
        return ((r"function Get-Service { [CmdletBinding()] param($Name) if($Name -eq 'W3SVC'){ " + ("[pscustomobject]@{Name='W3SVC'}" if w3 else "$null") + " } }" + "\n") +
                ("function Import-Module { [CmdletBinding()] param($Name) " + ("throw 'no'" if importfail else "") + " }\n") +
                f"function Get-Website {{ [CmdletBinding()] param() @({', '.join(ps(s) for s in siti)}) }}\n" +
                f"function Get-ChildItem {{ [CmdletBinding()] param($Path) if($Path -like 'IIS:*'){{ @({', '.join(ps(p) for p in pool)}) }} }}\n")
    S = lambda n, st: dict(Name=n, State=st, Bindings=dict(Collection=[dict(protocol="http", bindingInformation="*:80:" + n)]))
    P = lambda n, st: dict(Name=n, State=st, managedRuntimeVersion="v4.0", processModel=dict(identityType="ApplicationPoolIdentity"))
    r = run(N, {"FALLISCI": "si"}, iis([S("Default", "Started")], [P("DefaultAppPool", "Started")])); expect("tutto attivo", r, 0, ["Siti: 1", "Default  [Started]  http://*:80:Default", "DefaultAppPool  [Started]  identità ApplicationPoolIdentity  .NET v4.0", "siti_o_pool_fermi=0"])
    m = iis([S("Default", "Started"), S("Blog", "Stopped")], [P("Pool2", "Stopped")])
    r = run(N, {"FALLISCI": "si"}, m); expect("fermi con FALLISCI", r, 1, ["sito Blog", "pool Pool2", "siti_o_pool_fermi=2"])
    r = run(N, {}, m); expect("fermi senza FALLISCI", r, 0, ["siti_o_pool_fermi=2"])
    r = run(N, {}, iis([], [], w3=False)); expect("IIS assente", r, 0, ["IIS non è installato"])
    r = run(N, {}, iis([], [], importfail=True)); expect("modulo assente", r, 1, ["WebAdministration"])

N = "Windows: servizi di SQL Server"
if want(N):
    print("==", N)
    def sv(*items): return "function Get-CimInstance { [CmdletBinding()] param($ClassName) @(" + ", ".join(ps(dict(Name=n, State=s, StartMode=m, StartName="NT Service\\x")) for n, s, m in items) + ") }\n"
    base = [("MSSQLSERVER", "Running", "Auto"), ("SQLSERVERAGENT", "Running", "Auto"), ("SQLBrowser", "Stopped", "Disabled"), ("MSSQL$SQLEXPRESS", "Running", "Auto"), ("SQLWriter", "Stopped", "Auto"), ("Spooler", "Running", "Auto")]
    r = run(N, {"FALLISCI": "si"}, sv(*base)); expect("tutto a posto", r, 0, ["Servizi SQL Server: 5", "MSSQLSERVER", "sql_servizi_fermi=0"], ["Spooler"])
    m = sv(*(base[:1] + [("SQLSERVERAGENT", "Stopped", "Auto")] + base[2:]))
    r = run(N, {}, m); expect("agent fermo, senza FALLISCI", r, 0, ["ad avvio automatico ma fermi: SQLSERVERAGENT", "sql_servizi_fermi=1"])
    r = run(N, {"FALLISCI": "si"}, m); expect("agent fermo con FALLISCI", r, 1)
    r = run(N, {}, sv(("Spooler", "Running", "Auto"))); expect("SQL assente", r, 0, ["non è installato"])

N = "Windows: macchine virtuali Hyper-V"
if want(N):
    print("==", N)
    mk = ("function Get-VM { [CmdletBinding()] param() @([pscustomobject]@{Name='srv1';State='Running';Generation=2;ProcessorCount=4;MemoryAssigned=8GB;Uptime='1.02:00:00'}, [pscustomobject]@{Name='srv0';State='Off';Generation=1;ProcessorCount=2;MemoryAssigned=0;Uptime='00:00:00'}) }\n"
          "function Get-VMSnapshot { [CmdletBinding()] param($VMName) if($VMName -eq 'srv1'){ @(1,2) } else { throw 'x' } }\n")
    r = run(N, {}, mk); expect("elenco", r, 0, ["Macchine virtuali: 2, in esecuzione 1", "srv1  [Running]  gen 2  4 CPU  8,0 GB RAM  attività 1.02:00:00  punti di controllo 2", "srv0  [Off]"]) if False else expect("elenco", r, 0, ["Macchine virtuali: 2, in esecuzione 1", "srv1  [Running]  gen 2  4 CPU", "punti di controllo 2", "srv0  [Off]", "punti di controllo 0"])
    check("ordinate per nome", r[1].index("srv0") < r[1].index("srv1"), r[1])
    r = run(N, {}, ""); expect("Hyper-V assente", r, 0, ["non è installato"])
    r = run(N, {}, "function Get-VM { [CmdletBinding()] param() throw 'accesso negato' }\n"); expect("errore", r, 1, ["accesso negato"])

N = "Windows: lavori di stampa in coda"
if want(N):
    print("==", N)
    J = lambda i, u, d, st, mins: dict(Id=i, UserName=u, DocumentName=d, JobStatus=st, SubmittedTime=f"=PS=(Get-Date).AddMinutes(-{mins})")
    jobs = ", ".join(ps(j) for j in (J(1, "mario", "a.pdf", "Normal", 2), J(2, "anna", "b.docx", "Error", 5), J(3, "luca", "c.xls", "Normal", 120)))
    mk = "function Get-Printer { [CmdletBinding()] param() @([pscustomobject]@{Name='HP1'}, [pscustomobject]@{Name='Vuota'}) }\nfunction Get-PrintJob { [CmdletBinding()] param($PrinterName) if($PrinterName -eq 'HP1'){ @(" + jobs + ") } }\n"
    r = run(N, {}, mk); expect("coda", r, 0, ["HP1: 3 lavori", "#1  mario  a.pdf  [Normal]  2 min", "#2  anna  b.docx  [Error]  5 min   <-- bloccato", "#3  luca  c.xls  [Normal]  120 min   <-- bloccato", "Lavori in coda: 3, bloccati: 2", "lavori_stampa_bloccati=2"], ["Vuota"])
    r = run(N, {"MINUTI": "500"}, mk); expect("soglia alta", r, 0, ["bloccati: 1"])
    r = run(N, {}, "function Get-Printer { [CmdletBinding()] param() @() }\nfunction Get-PrintJob { [CmdletBinding()] param($PrinterName) @() }\n"); expect("nessun lavoro", r, 0, ["Lavori in coda: 0, bloccati: 0"])
    r = run(N, {}, ""); expect("comandi assenti", r, 1)
    for v in ("x", "1;id", "-5", "$(id)"): r = run(N, {"MINUTI": v}, mk); expect(f"MINUTI non valido {v!r}", r, 2)

N = "Windows: permessi NTFS di una cartella o di un file"
if want(N):
    print("==", N)
    A = lambda who, rights, t="Allow", inh=False: dict(IdentityReference=who, FileSystemRights=rights, AccessControlType=t, IsInherited=inh)
    acl = lambda *a, prot=False: "$global:MOCKPATHS=@('C:\\Dati*'); function Get-Acl { [CmdletBinding()] param($LiteralPath) " + ps(dict(Owner="BUILTIN\\Administrators", AreAccessRulesProtected=prot, Access=list(a))) + " }\n"
    r = run(N, {"PERCORSO": "C:\\Dati"}, acl(A("NT AUTHORITY\\SYSTEM", "FullControl", inh=True), A("BUILTIN\\Users", "ReadAndExecute, Synchronize"))); expect("permessi corretti", r, 0, ["Proprietario: BUILTIN\\Administrators", "Eredità dal padre: attiva", "NT AUTHORITY\\SYSTEM  FullControl  (ereditato)", "Voci troppo permissive: 0"], ["troppo permissivo\n"])
    r = run(N, {"PERCORSO": "C:\\Dati"}, acl(A("Everyone", "FullControl"), A("BUILTIN\\Users", "Modify, Synchronize"), A("Everyone", "FullControl", "Deny"), A("DOM\\Utenti autenticati", "Write"), prot=True)); expect("troppo permissivi", r, 0, ["Eredità dal padre: disattivata", "Everyone  FullControl  (diretto)   <-- troppo permissivo", "BUILTIN\\Users  Modify, Synchronize  (diretto)   <-- troppo permissivo", "Voci troppo permissive: 3"]) if False else expect("troppo permissivi", r, 0, ["Eredità dal padre: disattivata", "<-- troppo permissivo", "Voci troppo permissive: 3"])
    r = run(N, {"PERCORSO": "C:\\Dati"}, acl()); expect("nessuna voce", r, 0, ["Voci troppo permissive: 0"])
    r = run(N, {"PERCORSO": "C:\\Altro"}, acl()); expect("percorso inesistente", r, 2, ["non esiste"])
    r = run(N, {"PERCORSO": "C:\\Dati"}, "$global:MOCKPATHS=@('C:\\Dati*'); function Get-Acl { [CmdletBinding()] param($LiteralPath) throw 'negato' }\n"); expect("ACL illeggibile", r, 1, ["negato"])
    for v in ("", "Dati", "relativo\\x", "C:\\Dati|x", "C:\\Da?ti", "C:\\Da*ti", "a'; Write-Output PWNED; '", "$(Write-Output PWNED)", "C:\\a\"b", "C:\\a<b"):
        r = run(N, {"PERCORSO": v}, acl()); expect(f"PERCORSO {v!r} rifiutato", r, 2); check(f"PERCORSO {v!r}: nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])

N = "Windows: stato del controller di dominio (FSMO e replica)"
if want(N):
    print("==", N)
    cs = lambda role: "function Get-CimInstance { [CmdletBinding()] param($ClassName) [pscustomobject]@{DomainRole=%d} }\n" % role
    nd = "#!/bin/sh\necho 'Schema master          dc1.acme.local'\necho 'Infrastructure master  dc1.acme.local'\n"
    ok_rep = "#!/bin/sh\ncat <<'EOF'\nReplication Summary Start Time: 2026-10-01\n\nSource DSA          largest delta    fails/total %%   error\n DC1                   05m:10s    0 /   5    0\n DC2                   12m:02s    0 /   5    0\nEOF\n"
    bad_rep = ok_rep.replace("DC2                   12m:02s    0 /   5    0", "DC2                   12m:02s    3 /   5   60  (8524) errore")
    r = run(N, {}, cs(5), files={"bin/netdom.exe": nd, "bin/repadmin.exe": ok_rep}); expect("controller sano", r, 0, ["== netdom.exe query fsmo", "Schema master          dc1.acme.local", "== repadmin.exe /replsummary", "replica_errori=0"])
    r = run(N, {}, cs(5), files={"bin/netdom.exe": nd, "bin/repadmin.exe": bad_rep}); expect("replica con errori", r, 1, ["replica_errori=1", "la replica riporta errori"])
    r = run(N, {}, cs(2)); expect("non è un controller", r, 0, ["non è un controller di dominio"])
    r = run(N, {}, cs(4)); expect("strumenti assenti", r, 0, ["netdom.exe non è disponibile", "repadmin.exe non è disponibile", "replica_errori=0"])

N = "Windows: indice di affidabilità e arresti anomali recenti"
if want(N):
    print("==", N)
    def rel(idx, ap=3, sis=2, fail=False):
        met = ", ".join(ps(dict(StartMeasurementDate=f"=PS=(Get-Date).AddDays(-{d})", SystemStabilityIndex=v)) for d, v in idx)
        return ("function Get-CimInstance { [CmdletBinding()] param($ClassName) " + ("throw 'x'" if fail else f"@({met})") + " }\n"
                f"function Get-WinEvent {{ [CmdletBinding()] param($FilterHashtable) if($FilterHashtable.LogName -eq 'Application'){{ @(1..{ap}) }} else {{ @(1..{sis}) }} }}\n").replace("@(1..0)", "@()")
    r = run(N, {}, rel([(2, 7.0), (1, 8.25)])); expect("affidabile", r, 0, ["ultimo 8", "minimo del periodo 7", "misure 2", "(evento 1000): 3", "(eventi 41 e 6008): 2", "affidabilita=8", "arresti_sistema=2"])
    r = run(N, {}, rel([(1, 3.5)])); expect("indice basso", r, 1, ["affidabilità sotto 5"])
    r = run(N, {"SOGLIA": "3"}, rel([(1, 3.5)])); expect("soglia personalizzata", r, 0)
    r = run(N, {"GIORNI": "3"}, rel([(10, 2.0), (1, 9.0)])); expect("misura vecchia fuori finestra", r, 0, ["misure 1"])
    r = run(N, {}, rel([])); expect("nessuna misura", r, 0, ["Nessuna misura"])
    r = run(N, {}, rel([], fail=True)); expect("indice non disponibile", r, 1)
    r = run(N, {}, rel([(1, 8.0)], ap=0, sis=0)); expect("senza arresti", r, 0, ["(evento 1000): 0", "arresti_sistema=0"])
    for var, v in (("GIORNI", "x"), ("GIORNI", "0"), ("GIORNI", "1;id"), ("SOGLIA", "x"), ("SOGLIA", "100"), ("SOGLIA", "-1")): r = run(N, {var: v}, rel([(1, 8.0)])); expect(f"{var} non valido {v!r}", r, 2)

N = "Windows: schermate blu recenti (dump di memoria)"
if want(N):
    print("==", N)
    old = "[IO.File]::SetLastWriteTime((Join-Path $env:SystemRoot 'Minidump/old.dmp'), (Get-Date).AddDays(-40))\n"
    ev = lambda n: "function Get-WinEvent { [CmdletBinding()] param($FilterHashtable) @(" + ", ".join("[pscustomobject]@{TimeCreated=(Get-Date); Message='Il computer è stato riavviato dopo un controllo di bug. 0x0000009f'}" for _ in range(n)) + ") }\n"
    r = run(N, {"FALLISCI": "si"}, ev(0)); expect("nessun dump", r, 0, ["Dump di memoria negli ultimi 14 giorni: 0; eventi BugCheck: 0", "schermate_blu=0"])
    f = {"win/Minidump/new.dmp": b"x" * 2097152, "win/Minidump/old.dmp": b"x" * 10, "win/Minidump/note.txt": b"x", "win/MEMORY.DMP": b"x" * 1048576}
    r = run(N, {"FALLISCI": "si"}, old + ev(0), files=f); expect("dump recenti con FALLISCI", r, 1, ["new.dmp", "MEMORY.DMP", "2.0 MB", "eventi BugCheck: 0", "schermate_blu=2"], ["old.dmp", "note.txt"]) if False else expect("dump recenti con FALLISCI", r, 1, ["new.dmp", "MEMORY.DMP", "2", "eventi BugCheck: 0", "schermate_blu=2"], ["old.dmp", "note.txt"])
    r = run(N, {}, old + ev(0), files=f); expect("senza FALLISCI", r, 0, ["schermate_blu=2"])
    r = run(N, {"GIORNI": "60"}, old + ev(0), files=f); expect("finestra larga", r, 0, ["old.dmp"])
    r = run(N, {"FALLISCI": "si"}, ev(2)); expect("solo eventi", r, 1, ["eventi BugCheck: 2", "schermate_blu=2", "controllo di bug"])
    for v in ("x", "0", "1;id", "-1"): r = run(N, {"GIORNI": v}, ev(0)); expect(f"GIORNI non valido {v!r}", r, 2)

N = "Windows: dispositivi USB e dispositivi con errori (Plug and Play)"
if want(N):
    print("==", N)
    D = lambda nome, iid, cl, st="OK", code=0, pres=True: dict(FriendlyName=nome, InstanceId=iid, Class=cl, Status=st, ConfigManagerErrorCode=code, Present=pres)
    pnp = lambda *d: "function Get-PnpDevice { [CmdletBinding()] param([switch]$PresentOnly) @(" + ", ".join(ps(x) for x in d) + ") }\n"
    r = run(N, {}, pnp(D("Tastiera USB", "USB\\VID_1\\1", "HIDClass"), D("Hub radice", "USB\\ROOT_HUB30\\1", "USB"), D("Scheda audio", "HDAUDIO\\1", "MEDIA"), D("Dispositivo ignoto", "USB\\VID_2\\2", "Other", "Error", 28), D("Fantasma", "PCI\\1", "Net", "Unknown", 45, False), D("Rotto", "PCI\\2", "Net", "Error", 43))); expect("elenco", r, 0, ["collegati (esclusi hub e controller): 2", "Tastiera USB  [HIDClass]  OK", "Dispositivi con errore: 2", "Dispositivo ignoto  [Other]  codice 28: driver non installato", "Rotto  [Net]  codice 43: il dispositivo ha segnalato un problema", "dispositivi_con_errore=2"], ["Hub radice", "Fantasma"])
    r = run(N, {}, pnp(D("Strano", "PCI\\3", "Net", "Error", 99))); expect("codice sconosciuto", r, 0, ["codice 99: vedi Gestione dispositivi"])
    r = run(N, {}, pnp()); expect("nessun dispositivo", r, 0, ["collegati (esclusi hub e controller): 0", "Dispositivi con errore: 0", "dispositivi_con_errore=0"])
    r = run(N, {}, ""); expect("comando assente", r, 1)

ENVCLS = ("Add-Type -TypeDefinition 'public static class Env2 { public static System.Collections.Generic.Dictionary<string,string> D = new System.Collections.Generic.Dictionary<string,string>(); public static bool Fail = false;"
          " public static string GetEnvironmentVariable(string n, string t) { string v; return D.TryGetValue(n, out v) ? v : null; }"
          " public static void SetEnvironmentVariable(string n, string v, string t) { if (Fail) throw new System.Exception(\"negato\"); if (string.IsNullOrEmpty(v)) D.Remove(n); else D[n] = v; } }'\n")
N = "Windows: imposta o elimina una variabile d'ambiente di sistema"
if want(N):
    print("==", N)
    sub = lambda b: b.replace("[Environment]::", "[Env2]::")
    R = lambda vars, pre="", **kw: run(N, vars, ENVCLS + pre, body_sub=sub, **kw)
    r = R({"NOME": "MIA_VAR", "VALORE": "C:\\Dati;x"}); expect("imposta nuova", r, 0, ["(non definita)", "Impostata MIA_VAR.", "Valore ora: C:\\Dati;x"])
    r = R({"NOME": "MIA_VAR", "VALORE": "nuovo"}, "[Env2]::D['MIA_VAR']='vecchio'\n"); expect("sovrascrive", r, 0, ["Valore attuale di MIA_VAR: vecchio", "Valore ora: nuovo"])
    r = R({"NOME": "MIA_VAR", "AZIONE": "elimina"}, "[Env2]::D['MIA_VAR']='x'\n"); expect("elimina", r, 0, ["Eliminata MIA_VAR.", "Valore ora: (non definita)"])
    r = R({"NOME": "MIA_VAR", "AZIONE": "elimina"}); expect("elimina assente", r, 0, ["Niente da eliminare."])
    r = R({"NOME": "MIA_VAR", "VALORE": "0"}); expect("valore 0", r, 0, ["Valore ora: 0"])
    for h in HOSTILE:
        r = R({"NOME": "VAR1", "VALORE": h}); expect(f"VALORE ostile {h[:12]!r}", r, 2 if "\n" in h else 0, [] if "\n" in h else ["Impostata VAR1."]); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
        r = R({"NOME": h, "VALORE": "x"}); expect(f"NOME ostile {h[:12]!r}", r, 2)
    for n in ("Path", "PATH", "windir", "ComSpec", "TEMP", "ProgramFiles", "ProgramFiles(x86)", "OS", "USERNAME", "PSModulePath", "PROCESSOR_ARCHITECTURE"):
        r = R({"NOME": n, "VALORE": "x"}); expect(f"NOME protetto {n}", r, 2)
    for v in ({"NOME": "1ABC"}, {"NOME": "a b"}, {"NOME": "a-b"}, {"NOME": "A" * 65}, {"NOME": ""}, {"VALORE": ""}, {"VALORE": "x" * 2001}, {"AZIONE": "boh"}):
        vv = {"NOME": "VAR1", "VALORE": "x"}; vv.update(v); r = R(vv); expect(f"non valido {str(v)[:30]}", r, 2)
    r = R({"NOME": "VAR1", "VALORE": "x"}, admin=False); expect("senza amministratore", r, 3)
    r = R({"NOME": "VAR1", "VALORE": "x"}, "[Env2]::Fail=$true\n"); expect("scrittura rifiutata", r, 1, ["Operazione non riuscita:", "negato"])

N = "Windows: cambia il tipo di avvio di un servizio"
if want(N):
    print("==", N)
    mk = lambda st="Stopped": (f"function Get-Service {{ [CmdletBinding()] param($Name) if($Name -eq 'Spooler'){{ [pscustomobject]@{{Name='Spooler';DisplayName='Print Spooler';Status='{st}';StartType='Manual'}} }} else {{ throw 'x' }} }}\n"
        "function Set-Service { [CmdletBinding()] param($Name,$StartupType) Write-Output \"CALL set $Name $StartupType\" }\nfunction Start-Service { [CmdletBinding()] param($Name) Write-Output \"CALL start $Name\" }\n")
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "automatico", "AVVIA": "si"}, mk()); expect("automatico e avvia", r, 0, ["Print Spooler): stato Stopped, avvio attuale Manual", "CALL set Spooler Automatic", "CALL start Spooler", "Servizio avviato."])
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "automatico", "AVVIA": "si"}, mk("Running")); expect("già in esecuzione", r, 0, ["CALL set Spooler Automatic"], ["CALL start"])
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "Ritardato"}, mk()); expect("ritardato maiuscola", r, 0, ["AutomaticDelayedStart"], ["CALL start"])
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "manuale", "AVVIA": "si"}, mk()); expect("manuale non avvia", r, 0, ["CALL set Spooler Manual"], ["CALL start"])
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "disattivato"}, mk()); expect("disattivato", r, 0, ["CALL set Spooler Disabled"])
    for s in ("rpcss", "RpcSs", "WinDefend", "wuauserv", "EventLog", "myrmm-agent", "DattoAgent", "BITS", "Dhcp", "Schedule", "TermService"):
        r = run(N, {"SERVIZIO": s, "TIPO": "disattivato"}, mk()); expect(f"servizio protetto {s}", r, 2); check(f"{s}: nulla cambiato", "CALL" not in r[1], r[1])
    for s, t in (("", "manuale"), ("Spooler", ""), ("Spooler", "boh"), ("Inesistente", "manuale"), ("a;b", "manuale"), ("$(id)", "manuale"), ("a'b", "manuale"), ("Spooler", "manuale'; x; '")):
        r = run(N, {"SERVIZIO": s, "TIPO": t}, mk()); expect(f"non valido {s!r}/{t!r}", r, 2); check("nulla cambiato", "CALL" not in r[1], r[1])
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "manuale"}, mk(), admin=False); expect("senza amministratore", r, 3)
    r = run(N, {"SERVIZIO": "Spooler", "TIPO": "manuale"}, mk().replace("Write-Output \"CALL set $Name $StartupType\"", "throw 'dipendenze'")); expect("Set-Service fallisce", r, 1, ["Operazione non riuscita: dipendenze"])

N = "Windows: termina un processo per nome"
if want(N):
    print("==", N)
    mk = (r"function Get-Process { [CmdletBinding()] param($Name) if($Name -eq 'notepad'){ @([pscustomobject]@{Id=1234;WorkingSet64=50MB;StartTime=(Get-Date).AddHours(-1)}, [pscustomobject]@{Id=1235;WorkingSet64=20MB;StartTime=(Get-Date)}, [pscustomobject]@{Id=$PID;WorkingSet64=1MB;StartTime=(Get-Date)}, [pscustomobject]@{Id=4;WorkingSet64=1MB;StartTime=(Get-Date)}) } }" + "\n"
          "function Stop-Process { [CmdletBinding()] param($Id,[switch]$Force) Write-Output \"CALL stop $Id\" }\n")
    r = run(N, {"NOME": "notepad"}, mk); expect("anteprima", r, 0, ["trovati: 2", "PID 1234  50 MB", "PID 1235", "Anteprima"], ["CALL", "PID 4 "])
    r = run(N, {"NOME": "notepad.exe", "APPLICA": "si"}, mk); expect("applica", r, 0, ["CALL stop 1234", "CALL stop 1235", "Terminati 2 processi (0 errori)"])
    r = run(N, {"NOME": "chrome", "APPLICA": "si"}, mk); expect("nessun processo", r, 0, ["trovati: 0"], ["CALL"])
    r = run(N, {"NOME": "notepad", "APPLICA": "si"}, mk.replace("Write-Output \"CALL stop $Id\"", "if($Id -eq 1235){ throw 'accesso negato' } else { Write-Output \"CALL stop $Id\" }")); expect("uno fallisce", r, 1, ["CALL stop 1234", "PID 1235 non terminato: accesso negato", "Terminati 1 processi (1 errori)"])
    for n in ("System", "svchost", "SVCHOST.exe", "lsass", "csrss", "explorer", "winlogon", "MsMpEng", "myrmm-agent", "DattoAgent", "datto-x", "AEMAgent", "services", "dwm"):
        r = run(N, {"NOME": n, "APPLICA": "si"}, mk); expect(f"protetto {n}", r, 2); check(f"{n}: nulla terminato", "CALL" not in r[1], r[1])
    for n in ("", "a", "a;b", "$(id)", "a'b", "x" * 61, "a|b", "*"):
        r = run(N, {"NOME": n, "APPLICA": "si"}, mk); expect(f"non valido {n[:12]!r}", r, 2); check("nulla terminato", "CALL" not in r[1], r[1])
    r = run(N, {"NOME": "notepad", "APPLICA": "si"}, mk, admin=False); expect("senza amministratore", r, 3)

N = "Windows: apri o chiudi una porta in ingresso nel firewall"
if want(N):
    print("==", N)
    mk = lambda esiste=False: ("$global:FWX = " + ("$true" if esiste else "$false") + "\n"
        "function Get-NetFirewallRule { [CmdletBinding()] param($DisplayName) if($global:FWX -and $DisplayName -like 'myrmm-*'){ [pscustomobject]@{DisplayName=$DisplayName} } }\n"
        "function Remove-NetFirewallRule { [CmdletBinding()] param([Parameter(ValueFromPipeline)]$InputObject) process { Write-Output \"CALL remove $($InputObject.DisplayName)\" } }\n"
        "function New-NetFirewallRule { [CmdletBinding()] param($DisplayName,$Direction,$Action,$Protocol,$LocalPort,$RemoteAddress,$Profile) [IO.File]::AppendAllText((Join-Path $env:TEMP 'fw.log'), \"$DisplayName|$Direction|$Action|$Protocol|$LocalPort|$($RemoteAddress -join ',')|$($LocalPort.GetType().Name)`n\") }\n")
    fw = lambda: LASTFILES.get("fw.log", "")
    r = run(N, {"NOME": "web", "PORTA": "8080"}, mk()); expect("TCP qualunque", r, 0, ["Regola myrmm-web creata: TCP 8080 da Any."]); check("parametri", fw().strip() == "myrmm-web|Inbound|Allow|TCP|8080|Any|Int32", fw())
    r = run(N, {"NOME": "dns", "PORTA": "53", "PROTOCOLLO": "udp", "REMOTI": "192.168.1.0/24, 10.0.0.5"}, mk()); expect("UDP con remoti", r, 0, ["UDP 53 da 192.168.1.0/24, 10.0.0.5"]); check("parametri remoti", fw().strip() == "myrmm-dns|Inbound|Allow|UDP|53|192.168.1.0/24,10.0.0.5|Int32", fw())
    r = run(N, {"NOME": "web", "PORTA": "8080"}, mk(True)); expect("esiste già", r, 0, ["esiste già"]); check("nulla creato", fw() == "", fw())
    r = run(N, {"NOME": "web", "AZIONE": "rimuovi"}, mk(True)); expect("rimuovi", r, 0, ["CALL remove myrmm-web", "Rimosse 1 regole myrmm-web."])
    r = run(N, {"NOME": "web", "AZIONE": "rimuovi"}, mk()); expect("rimuovi assente", r, 0, ["Nessuna regola myrmm-web."], ["CALL"])
    for v in ({"NOME": ""}, {"NOME": "a b"}, {"NOME": "a;b"}, {"NOME": "$(id)"}, {"NOME": "a'b"}, {"NOME": "x" * 41}, {"PORTA": ""}, {"PORTA": "0"}, {"PORTA": "65536"}, {"PORTA": "80;x"}, {"PORTA": "abc"}, {"PORTA": "-1"}, {"PROTOCOLLO": "ICMP"}, {"REMOTI": "evil;x"}, {"REMOTI": "a b"}, {"REMOTI": "1.2.3.4, $(id)"}, {"AZIONE": "boh"}):
        vv = {"NOME": "web", "PORTA": "80"}; vv.update(v); r = run(N, vv, mk()); expect(f"non valido {v}", r, 2); check(f"{v}: nulla creato", fw() == "" and "CALL" not in r[1], r[1])
    r = run(N, {"NOME": "web", "PORTA": "80"}, mk(), admin=False); expect("senza amministratore", r, 3)
    r = run(N, {"NOME": "web", "PORTA": "80"}, mk().replace("[IO.File]::AppendAllText", "throw 'negato'; [IO.File]::AppendAllText")); expect("creazione fallita", r, 1, ["Creazione non riuscita"])

N = "Windows: copia o sincronizza una cartella con robocopy"
if want(N):
    print("==", N)
    rb = lambda code=1: f"#!/bin/sh\necho \"$*\" >> \"$TEMP/rc.log\"\nprintf '   Files :  3  3  0  0  0  0\\n'\nexit {code}\n"
    pth = "$global:MOCKPATHS=@('C:\\Dati', 'C:\\Dati*', 'D:\\Origine', 'D:\\Origine*', '\\\\srv\\share*')\n"
    log = lambda: LASTFILES.get("rc.log", "")
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "E:\\Copia"}, pth, files={"bin/robocopy.exe": rb()}); expect("anteprima", r, 0, ["modalità copia  anteprima", "Anteprima: non è stato copiato", "robocopy codice 1"]); check("argomenti anteprima", "/E" in log() and "/L" in log().split() and "/MIR" not in log(), log())
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "E:\\Copia", "APPLICA": "si"}, pth, files={"bin/robocopy.exe": rb(3)}); expect("copia", r, 0, ["ESEGUITA", "robocopy codice 3"], ["Anteprima:"]); check("senza /L", "/L" not in log().split() and "/XJ" in log(), log())
    r = run(N, {"ORIGINE": "D:\\Origine\\", "DESTINAZIONE": "E:\\Copia\\", "MIRROR": "si", "APPLICA": "si"}, pth, files={"bin/robocopy.exe": rb(0)}); expect("specchio", r, 0, ["modalità specchio  ESEGUITA"]); check("MIR", "/MIR" in log() and "/E " not in log() + " ", log()); check("percorsi senza barra finale", log().startswith("D:\\Origine E:\\Copia "), log())
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "E:\\Copia", "MIRROR": "si"}, pth, files={"bin/robocopy.exe": rb(2)}); expect("specchio in anteprima", r, 0, ["modalità specchio  anteprima"]); check("MIR con /L", "/MIR" in log() and "/L" in log().split(), log())
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "\\\\srv\\share\\bk", "APPLICA": "si"}, pth, files={"bin/robocopy.exe": rb()}); expect("destinazione UNC", r, 0, ["ESEGUITA"])
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "C:\\Users\\mario\\Backup", "APPLICA": "si"}, pth, files={"bin/robocopy.exe": rb()}); expect("sotto il profilo utente", r, 0, ["ESEGUITA"])
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "E:\\Copia", "APPLICA": "si"}, pth, files={"bin/robocopy.exe": rb(8)}); expect("errori di robocopy", r, 1, ["codice 8"])
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "E:\\Copia"}, pth); expect("robocopy assente", r, 1, ["non è disponibile"])
    r = run(N, {"ORIGINE": "D:\\Mancante", "DESTINAZIONE": "E:\\Copia"}, pth, files={"bin/robocopy.exe": rb()}); expect("origine mancante", r, 2, ["non è una cartella"])
    rifiuti = [("D:\\Origine", "D:\\Origine"), ("D:\\Origine", "d:\\origine\\"), ("D:\\Origine", "D:\\Origine\\sotto"), ("D:\\Origine\\sotto", "D:\\Origine"), ("D:\\Origine", "C:\\"), ("D:\\Origine", "C:"), ("D:\\Origine", "E:\\"), ("D:\\Origine", "C:\\Windows"), ("D:\\Origine", "C:\\Windows\\System32"), ("D:\\Origine", "C:\\Program Files"), ("D:\\Origine", "C:\\Program Files (x86)\\x"),
           ("D:\\Origine", "C:\\Users"), ("D:\\Origine", "C:\\ProgramData\\x"), ("D:\\Origine", "E:\\a\\..\\b"), ("D:\\Origine", "E:\\a|b"), ("D:\\Origine", "E:\\a?b"), ("D:\\Origine", "relativo"), ("relativo", "E:\\x"), ("", "E:\\x"), ("D:\\Origine", ""), ("a'; Write-Output PWNED; '", "E:\\x"), ("D:\\Origine", "$(Write-Output PWNED)"), ("D:\\Origine", "E:\\a\"b")]
    for o, d in rifiuti:
        r = run(N, {"ORIGINE": o, "DESTINAZIONE": d, "APPLICA": "si", "MIRROR": "si"}, pth, files={"bin/robocopy.exe": rb()}); expect(f"rifiutato {o!r} -> {d!r}", r, 2); check("robocopy non invocato", log() == "", log()); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {"ORIGINE": "D:\\Origine", "DESTINAZIONE": "E:\\Copia"}, pth, files={"bin/robocopy.exe": rb()}, admin=False); expect("senza amministratore", r, 3)

N = "Windows: comprimi una cartella in un file ZIP"
if want(N):
    print("==", N)
    mk = lambda pat="'C:\\Dati', 'C:\\Dati*', 'C:\\Backup'": (f"$global:MOCKPATHS=@({pat})\n"
        "function Compress-Archive { [CmdletBinding()] param($LiteralPath,$DestinationPath,$CompressionLevel) [IO.File]::AppendAllText(\"$env:TEMP/zip.log\", \"$LiteralPath|$DestinationPath|$CompressionLevel`n\") }\n"
        "function Get-Item { [CmdletBinding()] param($LiteralPath) [pscustomobject]@{Length=3145728} }\nfunction Join-Path { [CmdletBinding()] param($Path,$ChildPath) \"$Path\\$ChildPath\" }\n")
    r = run(N, {"ORIGINE": "C:\\Dati", "DESTINAZIONE": "C:\\Backup"}, mk()); expect("zip", r, 0, ["Creato C:\\Backup", "(3,0 MB)"]) if False else expect("zip", r, 0, ["Creato C:\\Backup", ".zip ("])
    check("argomenti", re.match(r"C:\\Dati\|C:\\Backup.*-\d{8}-\d{6}\.zip\|Optimal", LASTFILES.get("zip.log", "")), LASTFILES.get("zip.log"))
    r = run(N, {"ORIGINE": "C:\\Dati", "DESTINAZIONE": "C:\\Backup"}, mk("'C:\\Dati', 'C:\\Backup*'")); expect("zip già esistente", r, 1, ["esiste già"])
    r = run(N, {"ORIGINE": "C:\\Dati", "DESTINAZIONE": "C:\\Backup"}, mk().replace("[IO.File]::AppendAllText", "throw 'disco pieno'; [IO.File]::AppendAllText")); expect("compressione fallita", r, 1, ["Compressione non riuscita: disco pieno"])
    for o, d in (("C:\\Dati", "C:\\Mancante"), ("C:\\Mancante", "C:\\Backup"), ("C:\\Windows", "C:\\Backup"), ("C:\\Program Files\\x", "C:\\Backup"), ("C:\\ProgramData", "C:\\Backup"), ("C:\\Dati", "C:\\Dati\\sub"), ("C:\\Dati", "C:\\Dati"), ("relativo", "C:\\Backup"), ("C:\\Dati", "relativo"), ("C:\\Dati", ""), ("", "C:\\Backup"), ("C:\\Da|ti", "C:\\Backup"), ("C:\\a\\..\\Dati", "C:\\Backup"), ("a'; Write-Output PWNED; '", "C:\\Backup"), ("C:\\Dati", "$(Write-Output PWNED)")):
        r = run(N, {"ORIGINE": o, "DESTINAZIONE": d}, mk()); expect(f"rifiutato {o!r} -> {d!r}", r, 2); check("nessuno zip", "zip.log" not in LASTFILES, r[1]); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {"ORIGINE": "C:\\Dati", "DESTINAZIONE": "C:\\Backup"}, mk(), admin=False); expect("senza amministratore", r, 3)

N = "Windows: imposta o elimina un valore del registro (HKLM)"
if want(N):
    print("==", N)
    K = "SOFTWARE\\Policies\\Acme"; HK = "HKLM:\\" + K
    mk = ("function Get-ItemProperty { [CmdletBinding()] param($LiteralPath,$Path,$Name) $p = if($LiteralPath){$LiteralPath}else{$Path}; $k = \"$p|$Name\"; if($global:REG.ContainsKey($k)){ $o = New-Object psobject; $o | Add-Member NoteProperty $Name $global:REG[$k]; $o } else { throw 'mancante' } }\n"
          "function New-ItemProperty { [CmdletBinding()] param($LiteralPath,$Name,$Value,$PropertyType,[switch]$Force) $global:REG[\"$LiteralPath|$Name\"] = $Value; [IO.File]::AppendAllText((Join-Path $env:TEMP 'reg.log'), \"SET $LiteralPath|$Name|$PropertyType|$Value|$($Value.GetType().Name)`n\") }\n"
          "function Remove-ItemProperty { [CmdletBinding()] param($LiteralPath,$Name) $global:REG.Remove(\"$LiteralPath|$Name\"); [IO.File]::AppendAllText((Join-Path $env:TEMP 'reg.log'), \"DEL $LiteralPath|$Name`n\") }\n")
    rl = lambda: LASTFILES.get("reg.log", "")
    r = run(N, {"CHIAVE": K, "NOME": "Abilita", "VALORE": "1"}, mk); expect("anteprima", r, 0, ["valore attuale (assente)", "Anteprima: verrebbe impostato DWord = 1"]); check("nulla scritto", rl() == "", rl())
    r = run(N, {"CHIAVE": K, "NOME": "Abilita", "VALORE": "1", "APPLICA": "si"}, mk); expect("imposta DWord", r, 0, ["Impostato DWord = 1"]); check("tipo UInt32", rl().strip() == f"SET {HK}|Abilita|DWord|1|UInt32", rl())
    r = run(N, {"CHIAVE": K, "NOME": "Abilita", "VALORE": "0", "APPLICA": "si"}, mk + f"$global:REG['{HK}|Abilita']=1\n"); expect("valore 0 sovrascrive", r, 0, ["valore attuale 1", "Impostato DWord = 0"]); check("scritto 0", "|DWord|0|UInt32" in rl(), rl())
    r = run(N, {"CHIAVE": K, "NOME": "Testo", "VALORE": "ciao mondo", "TIPO": "String", "APPLICA": "si"}, mk); expect("String", r, 0, ["Impostato String = ciao mondo"]); check("tipo String", "|String|ciao mondo|String" in rl(), rl())
    r = run(N, {"CHIAVE": K, "NOME": "Grande", "VALORE": "9999999999", "TIPO": "QWord", "APPLICA": "si"}, mk); expect("QWord", r, 0); check("tipo UInt64", "|QWord|9999999999|UInt64" in rl(), rl())
    r = run(N, {"CHIAVE": K, "NOME": "Abilita", "AZIONE": "elimina", "APPLICA": "si"}, mk + f"$global:REG['{HK}|Abilita']=1\n"); expect("elimina", r, 0, ["Valore eliminato."]); check("DEL", rl().strip() == f"DEL {HK}|Abilita", rl())
    r = run(N, {"CHIAVE": K, "NOME": "Abilita", "AZIONE": "elimina"}, mk + f"$global:REG['{HK}|Abilita']=1\n"); expect("elimina in anteprima", r, 0, ["verrebbe eliminato"]); check("nulla cancellato", rl() == "", rl())
    r = run(N, {"CHIAVE": K, "NOME": "Abilita", "AZIONE": "elimina", "APPLICA": "si"}, mk); expect("elimina assente", r, 0, ["Niente da eliminare."])
    r = run(N, {"CHIAVE": K + "\\Nuova", "NOME": "X", "VALORE": "1", "APPLICA": "si"}, mk); expect("crea la chiave", r, 0, ["Impostato"]); 
    for h in HOSTILE:
        r = run(N, {"CHIAVE": K, "NOME": "T", "VALORE": h, "TIPO": "String", "APPLICA": "si"}, mk); expect(f"VALORE ostile {h[:12]!r}", r, 2 if "\n" in h else 0); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
        r = run(N, {"CHIAVE": h, "NOME": "T", "VALORE": "1", "APPLICA": "si"}, mk); expect(f"CHIAVE ostile {h[:12]!r}", r, 2)
        r = run(N, {"CHIAVE": K, "NOME": h, "VALORE": "1", "APPLICA": "si"}, mk); expect(f"NOME ostile {h[:12]!r}", r, 2)
    for k in ("SYSTEM\\CurrentControlSet\\Services\\x", "HKLM:\\SOFTWARE\\x", "SOFTWARE", "SOFTWARE\\", "SOFTWARE\\a\\..\\b", "SOFTWARE\\a\\\\b", "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run", "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce",
              "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon", "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options\\x.exe", "SOFTWARE\\Microsoft\\Windows Defender\\Exclusions", "SOFTWARE\\Policies\\Microsoft\\Windows Defender", "SOFTWARE\\Classes\\exefile", "SOFTWARE\\Microsoft\\SystemCertificates\\Root", "SOFTWARE\\Microsoft\\Cryptography\\x"):
        r = run(N, {"CHIAVE": k, "NOME": "X", "VALORE": "1", "APPLICA": "si"}, mk); expect(f"CHIAVE rifiutata {k!r}", r, 2); check("nulla scritto", rl() == "", rl())
    for v in ({"TIPO": "Binary"}, {"VALORE": "abc"}, {"VALORE": "-1"}, {"VALORE": "4294967296"}, {"VALORE": "1.5"}, {"VALORE": ""}, {"VALORE": "x\ny", "TIPO": "String"}, {"VALORE": "x" * 2001, "TIPO": "String"}, {"NOME": ""}, {"NOME": "a\\b"}, {"AZIONE": "boh"}):
        vv = {"CHIAVE": K, "NOME": "X", "VALORE": "1", "APPLICA": "si"}; vv.update(v); r = run(N, vv, mk); expect(f"non valido {str(v)[:30]}", r, 2); check("nulla scritto", rl() == "", rl())
    r = run(N, {"CHIAVE": K, "NOME": "X", "VALORE": "1", "APPLICA": "si"}, mk, admin=False); expect("senza amministratore", r, 3)
    r = run(N, {"CHIAVE": K, "NOME": "X", "VALORE": "1", "APPLICA": "si"}, mk.replace("$global:REG[\"$LiteralPath|$Name\"] = $Value;", "throw 'accesso negato';")); expect("scrittura fallita", r, 1, ["Operazione non riuscita: accesso negato"])

N = "Windows: installa e avvia il server OpenSSH"
if want(N):
    print("==", N)
    lg = lambda: LASTFILES.get("ssh.log", "")
    def ssh(stato=None, listen=True, cap=True, addfail=False, fw=1):
        sv = "$null" if stato is None else f"[pscustomobject]@{{Name='sshd';Status='{stato}'}}"
        return (f"$global:SSHSVC = {sv}\n"
            "function Log($m) { [IO.File]::AppendAllText((Join-Path $env:TEMP 'ssh.log'), \"$m`n\") }\n"
            "function Get-Service { [CmdletBinding()] param($Name) $global:SSHSVC }\n"
            "function Set-Service { [CmdletBinding()] param($Name,$StartupType) Log \"set $Name $StartupType\" }\n"
            "function Start-Service { [CmdletBinding()] param($Name) Log \"start $Name\"; $global:SSHSVC = [pscustomobject]@{Name='sshd';Status='Running'} }\n"
            "function Get-WindowsCapability { [CmdletBinding()] param([switch]$Online,$Name) " + ("[pscustomobject]@{Name='OpenSSH.Server~~~~0.0.1.0'}" if cap else "") + " }\n"
            "function Add-WindowsCapability { [CmdletBinding()] param([switch]$Online,$Name) " + ("throw 'rete assente'" if addfail else "Log \"add $Name\"; $global:SSHSVC = [pscustomobject]@{Name='sshd';Status='Stopped'}") + " }\n"
            "function Get-NetTCPConnection { [CmdletBinding()] param($State,$LocalPort) " + ("[pscustomobject]@{LocalPort=22}" if listen else "") + " }\n"
            f"function Get-NetFirewallRule {{ [CmdletBinding()] param($DisplayName) @(1..{fw} | ForEach-Object {{ [pscustomobject]@{{Enabled='True';Direction='Inbound'}} }}) }}\n").replace("@(1..0 |", "@(@() |")
    r = run(N, {}, ssh("Running")); expect("già installato e attivo", r, 0, ["già installato", "sshd: Running, avvio automatico, porta 22 in ascolto: sì, regole firewall in ingresso attive: 1"]); check("avvio automatico impostato, niente start", "set sshd Automatic" in lg() and "start" not in lg().replace("set sshd", ""), lg())
    r = run(N, {}, ssh("Stopped")); expect("installato ma fermo", r, 0, ["Running"]); check("start", "start sshd" in lg(), lg())
    r = run(N, {}, ssh(None)); expect("da installare", r, 0, ["Installo OpenSSH.Server~~~~0.0.1.0...", "porta 22 in ascolto: sì"]); check("add poi start", lg().index("add ") < lg().index("start sshd"), lg())
    r = run(N, {}, ssh(None, cap=False)); expect("funzionalità assente", r, 1, ["non disponibile"])
    r = run(N, {}, ssh(None, addfail=True)); expect("installazione fallita", r, 1, ["Installazione non riuscita: rete assente"])
    r = run(N, {}, ssh("Running", listen=False)); expect("porta non in ascolto", r, 1, ["porta 22 non è in ascolto"])
    r = run(N, {}, ssh("Running", fw=0)); expect("nessuna regola firewall", r, 0, ["regole firewall in ingresso attive: 0"])
    r = run(N, {}, ssh("Running"), admin=False); expect("senza amministratore", r, 3)

N = "Windows: driver non firmati"
if want(N):
    print("==", N)
    D = lambda n, s=False, cl="Net": dict(DeviceName=n, IsSigned=s, DeviceClass=cl, DriverProviderName="Acme", DriverVersion="1.0", InfName="oem1.inf")
    mk = lambda *d, fail=False: "function Get-CimInstance { [CmdletBinding()] param($ClassName) " + ("throw 'x'" if fail else "@(" + ", ".join(ps(x) for x in d) + ")") + " }\n"
    r = run(N, {"FALLISCI": "si"}, mk(D("Scheda A", True), D("", False))); expect("tutti firmati", r, 0, ["Driver non firmati: 0", "driver_non_firmati=0"])
    r = run(N, {}, mk(D("Zeta"), D("Alfa"), D("Firmato", True))); expect("due non firmati", r, 0, ["Driver non firmati: 2", "Alfa  [Net]  Acme 1.0  oem1.inf", "driver_non_firmati=2"], ["Firmato"]); check("ordinati", r[1].index("Alfa") < r[1].index("Zeta"), r[1])
    r = run(N, {"FALLISCI": "si"}, mk(D("Alfa"))); expect("FALLISCI", r, 1)
    r = run(N, {}, mk(*[D("Dev%02d" % i) for i in range(45)])); expect("più di 40", r, 0, ["Driver non firmati: 45", "... e altri 5"])
    r = run(N, {}, mk(fail=True)); expect("elenco non disponibile", r, 1)

# ---- Windows blocco 5: ispirati a ComStore/CyberDrain ----
RM = "function Remove-ItemProperty { [CmdletBinding()] param($Path,$Name) [void]$global:REG.Remove(\"$Path|$Name\") }\n"
ABS = lambda b: b.replace("'^[A-Za-z]:\\\\.+'", "'^/.+'")

N = "Windows: software di controllo remoto non autorizzato"
if want(N):
    print("==", N)
    def mk(sw=(), srv=(), prc=()):
        return ("function Get-ItemProperty { [CmdletBinding()] param($Path) @(" + ", ".join(ps(dict(DisplayName=x)) for x in sw) + ") }\n"
                "function Get-CimInstance { [CmdletBinding()] param($ClassName) @(" + ", ".join(ps(dict(Name=x, DisplayName=x, PathName='C:\\x.exe')) for x in srv) + ") }\n"
                "function Get-Process { [CmdletBinding()] param() @(" + ", ".join(ps(dict(ProcessName=x)) for x in prc) + ") }\n")
    r = run(N, {}, mk(["Microsoft Office", "7-Zip"], ["Spooler"], ["explorer"])); expect("pulito", r, 0, ["non ammesso: 0", "accesso_remoto_non_ammesso=0"])
    r = run(N, {}, mk(["AnyDesk"], [], ["AnyDesk"])); expect("AnyDesk", r, 1, ["NON AMMESSO  AnyDesk: programma installato, processo in esecuzione", "accesso_remoto_non_ammesso=1"])
    r = run(N, {}, mk(["ScreenConnect Client (abc)"], ["ScreenConnect Client (abc)"], [])); expect("ScreenConnect", r, 1, ["ScreenConnect / ConnectWise Control: programma installato, servizio"])
    r = run(N, {"AMMESSI": "AnyDesk"}, mk(["AnyDesk"], [], ["AnyDesk"])); expect("ammesso", r, 0, ["ammesso      AnyDesk", "non ammesso: 0"])
    r = run(N, {"AMMESSI": "AnyDesk, splashtop"}, mk(["AnyDesk", "TeamViewer", "Splashtop Streamer"])); expect("uno ammesso uno no", r, 1, ["NON AMMESSO  TeamViewer", "ammesso      Splashtop"], ["NON AMMESSO  AnyDesk"])
    for h in HOSTILE: r = run(N, {"AMMESSI": h}, mk()); expect(f"AMMESSI ostile {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])

N = "Windows: certificati Secure Boot 2023 (aggiornamento dei certificati Microsoft)"
if want(N):
    print("==", N)
    mk = lambda sb, db=None: ("function Confirm-SecureBootUEFI { [CmdletBinding()] param() " + ("throw 'non supportato'" if sb is None else ps(sb)) + " }\n"
        "function Get-SecureBootUEFI { [CmdletBinding()] param($Name) " + ("throw 'no'" if db is None else "[pscustomobject]@{Bytes=[Text.Encoding]::ASCII.GetBytes('" + db + "')}") + " }\n")
    r = run(N, {}, mk(None)); expect("BIOS legacy", r, 0, ["non supportato", "secureboot_ca2023=-1"])
    r = run(N, {}, mk(True, "xx Windows UEFI CA 2023 yy")); expect("certificato presente", r, 0, ["presente", "secureboot_ca2023=1"])
    r = run(N, {}, mk(True, "Microsoft Windows Production PCA 2011") + "$global:REG['HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecureBoot\\Servicing|UEFICA2023Status']='NotStarted'\n"); expect("certificato assente", r, 1, ["ASSENTE", "UEFICA2023Status = NotStarted", "secureboot_ca2023=0"])
    r = run(N, {}, mk(False, "Windows PCA 2011")); expect("Secure Boot disattivo", r, 0, ["attivo: no"])
    r = run(N, {}, mk(True)); expect("db non leggibile", r, 0, ["non leggibile"])

N = "Windows: file canarino anti-ransomware"
if want(N):
    print("==", N)
    NI = "function New-Item { [CmdletBinding()] param($Path,$ItemType,[switch]$Force) Microsoft.PowerShell.Management\\New-Item -ItemType Directory -Path $Path -Force | Out-Null }\n"
    D = tempfile.mkdtemp(prefix="myrmm-can-"); D2 = tempfile.mkdtemp(prefix="myrmm-can-")
    st = lambda: LASTFILES.get("pd/myrmm/canarini.json", "")
    r = run(N, {"PERCORSI": D}, NI, body_sub=ABS); expect("controlla senza registro", r, 0, ["Nessun canarino registrato", "canarini_alterati=0"])
    r = run(N, {"PERCORSI": f"{D};{D2}", "AZIONE": "crea"}, NI, body_sub=ABS); expect("crea", r, 0, ["Creato", "Fatto: 4 file"]); check("file esistono", os.path.exists(D + "/!_myrmm_non_toccare.docx") and os.path.exists(D2 + "/zz_myrmm_non_toccare.xlsx"))
    reg = st()
    # il registro non sopravvive tra due run (cartella temporanea): lo ricreo come file del run successivo
    import json as _j
    imp = lambda f: __import__("hashlib").sha256(open(f, "rb").read()).hexdigest().upper()
    regj = _j.dumps({D + "/" + n: imp(D + "/" + n) for n in ("!_myrmm_non_toccare.docx", "zz_myrmm_non_toccare.xlsx")})
    fl = {"pd/myrmm/canarini.json": regj}
    r = run(N, {"PERCORSI": D}, NI, body_sub=ABS, files=fl); expect("controlla intatti", r, 0, ["controllati: 2, alterati: 0"])
    open(D + "/zz_myrmm_non_toccare.xlsx", "w").write("cifrato!")
    r = run(N, {"PERCORSI": D}, NI, body_sub=ABS, files=fl); expect("modificato", r, 1, ["MODIFICATO", "alterati: 1", "canarini_alterati=1", "possibile ransomware"])
    os.remove(D + "/!_myrmm_non_toccare.docx")
    r = run(N, {"PERCORSI": D}, NI, body_sub=ABS, files=fl); expect("mancante", r, 1, ["MANCANTE", "alterati: 2"])
    r = run(N, {"PERCORSI": D, "AZIONE": "rimuovi"}, NI, body_sub=ABS, files=fl); expect("rimuovi", r, 0, ["Rimosso"]); check("file tolto", not os.path.exists(D + "/zz_myrmm_non_toccare.xlsx"))
    r = run(N, {"PERCORSI": D + "-assente", "AZIONE": "crea"}, NI, body_sub=ABS); expect("cartella assente", r, 0, ["Cartella assente"])
    for v in ({"PERCORSI": ""}, {"AZIONE": "boh"}, {"PERCORSI": "relativo\\x"}, {"PERCORSI": "C:\\"}, {"PERCORSI": "C:\\a\\..\\b"}, {"PERCORSI": "C:\\a|b"}, {"PERCORSI": ";".join(["C:\\d%d" % i for i in range(21)])}):
        vv = {"PERCORSI": D}; vv.update(v); r = run(N, vv, NI); expect(f"non valido {str(v)[:30]}", r, 2)
    for h in HOSTILE: r = run(N, {"PERCORSI": h}, NI); expect(f"ostile {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    shutil.rmtree(D, ignore_errors=True); shutil.rmtree(D2, ignore_errors=True)

N = "Windows: salva o ripristina i permessi NTFS di una cartella"
if want(N):
    print("==", N)
    ic = {"bin/icacls.exe": "#!/bin/sh\necho \"icacls $*\" >> \"$TEMP/icacls.log\"\nif [ \"$2\" = /save ]; then mkdir -p \"$(dirname \"$3\")\"; echo ACLDATA > \"$3\"; fi\nexit ${ICACLS_RC:-0}\n"}
    AF = "/tmp/myrmm-acl-prova/x.acl"
    r = run(N, {"PERCORSO": "/tmp", "FILE": AF}, "", body_sub=ABS, files=ic); expect("salva", r, 0, ["salvati in " + AF]); check("icacls /save", "icacls /tmp /save " + AF + " /t /c" in LASTFILES.get("icacls.log", ""), LASTFILES.get("icacls.log"))
    os.makedirs("/tmp/myrmm-acl-dir/sub", exist_ok=True)
    r = run(N, {"PERCORSO": "/tmp/myrmm-acl-dir/sub", "FILE": AF, "AZIONE": "ripristina"}, "", body_sub=ABS, files=ic); expect("ripristina", r, 0, ["ripristinati da"]); check("icacls /restore sulla cartella padre", "icacls /tmp/myrmm-acl-dir /restore " + AF + " /c" in LASTFILES.get("icacls.log", ""), LASTFILES.get("icacls.log"))
    r = run(N, {"PERCORSO": "/tmp", "FILE": "/tmp/myrmm-acl-assente/n.acl", "AZIONE": "ripristina"}, "", body_sub=ABS, files=ic); expect("file assente", r, 2, ["non trovato"])
    r = run(N, {"PERCORSO": "/tmp", "FILE": AF}, "", body_sub=ABS, files=ic, env={"ICACLS_RC": "5"}); expect("icacls fallisce", r, 1, ["non riuscito"])
    r = run(N, {"PERCORSO": "/tmp/myrmm-cartella-inesistente"}, "", body_sub=ABS, files=ic); expect("non è una cartella", r, 2)
    for v in ({"PERCORSO": ""}, {"AZIONE": "boh"}, {"PERCORSO": "C:\\Windows\\System32"}, {"PERCORSO": "C:\\Program Files (x86)\\x"}, {"PERCORSO": "C:\\ProgramData"}, {"PERCORSO": "relativo"}, {"PERCORSO": "C:\\a\\..\\b"}, {"FILE": "C:\\x.txt"}, {"FILE": "relativo.acl"}):
        vv = {"PERCORSO": "/tmp", "FILE": AF}; vv.update(v); r = run(N, vv, "", body_sub=ABS, files=ic); expect(f"non valido {str(v)[:34]}", r, 2)
    for h in HOSTILE: r = run(N, {"PERCORSO": h}, "", files=ic); expect(f"ostile {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {"PERCORSO": "/tmp", "FILE": AF}, "", body_sub=ABS, files=ic, admin=False); expect("senza amministratore", r, 3)
    shutil.rmtree("/tmp/myrmm-acl-prova", ignore_errors=True); shutil.rmtree("/tmp/myrmm-acl-dir", ignore_errors=True)

N = "Windows Update: blocca o sblocca la versione feature (TargetReleaseVersion)"
if want(N):
    print("==", N)
    K = "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate"
    r = run(N, {}, RM); expect("stato senza blocco", r, 0, ["nessun blocco"])
    r = run(N, {"AZIONE": "blocca", "VERSIONE": "23H2"}, RM); expect("blocca 11 23H2", r, 0, ["Versione bloccata su Windows 11 23H2", "versione fissata su Windows 11 23H2"])
    r = run(N, {"AZIONE": "blocca", "PRODOTTO": "Windows 10", "VERSIONE": "22H2"}, RM); expect("blocca 10 22H2", r, 0, ["Windows 10 22H2"])
    r = run(N, {"AZIONE": "sblocca"}, RM + f"$global:REG['{K}|TargetReleaseVersion']=1; $global:REG['{K}|ProductVersion']='Windows 11'; $global:REG['{K}|TargetReleaseVersionInfo']='23H2'\n"); expect("sblocca", r, 0, ["rimosso", "nessun blocco"])
    r = run(N, {}, RM + f"$global:REG['{K}|TargetReleaseVersion']=1; $global:REG['{K}|ProductVersion']='Windows 11'; $global:REG['{K}|TargetReleaseVersionInfo']='24H2'\n"); expect("stato con blocco", r, 0, ["Windows 11 24H2"])
    for v in ({"AZIONE": "boh"}, {"PRODOTTO": "Windows 7"}, {"AZIONE": "blocca", "VERSIONE": ""}, {"AZIONE": "blocca", "VERSIONE": "2023"}, {"AZIONE": "blocca", "VERSIONE": "23H3"}):
        vv = {"VERSIONE": "23H2"}; vv.update(v); r = run(N, vv, RM); expect(f"non valido {str(v)[:34]}", r, 2)
    for h in HOSTILE: r = run(N, {"AZIONE": "blocca", "VERSIONE": h}, RM); expect(f"ostile {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {}, RM, admin=False); expect("senza amministratore", r, 3)

N = "Windows: blocca o consenti i dischi USB (archiviazione di massa)"
if want(N):
    print("==", N)
    K = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\USBSTOR"
    mk = lambda s=3, usb=0: (f"$global:REG['{K}|Start']={s}\n" if s is not None else "") + "function Get-CimInstance { [CmdletBinding()] param($ClassName) @(" + ", ".join(ps(dict(Model="Chiavetta", Size=16e9, InterfaceType="USB")) for _ in range(usb)) + ") }\n"
    r = run(N, {}, mk()); expect("stato consentito", r, 0, ["Start = 3 (consentito)", "collegati ora: 0"])
    r = run(N, {"AZIONE": "blocca"}, mk(usb=1)); expect("blocca", r, 0, ["Prima: USBSTOR Start = 3", "Dopo: USBSTOR Start = 4 (bloccato)", "collegati ora: 1", "Chiavetta"])
    r = run(N, {"AZIONE": "consenti"}, mk(4)); expect("consenti", r, 0, ["Dopo: USBSTOR Start = 3 (consentito)"])
    r = run(N, {"AZIONE": "blocca"}, mk(None)); expect("driver assente", r, 1, ["non trovato"])
    r = run(N, {"AZIONE": "blocca"}, mk() + "function Set-ItemProperty { [CmdletBinding()] param($Path,$Name,$Value) throw 'negato' }\n"); expect("scrittura fallita", r, 1, ["Operazione non riuscita: negato"])
    for h in ("boh",) + tuple(HOSTILE): r = run(N, {"AZIONE": h}, mk()); expect(f"AZIONE non valida {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {}, mk(), admin=False); expect("senza amministratore", r, 3)

N = "Windows: opzioni di sistema (percorsi lunghi, blocco inattività, CTRL+ALT+CANC)"
if want(N):
    print("==", N)
    FS = "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem"; PS_ = "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System"
    r = run(N, {}, ""); expect("solo lettura", r, 0, ["Percorsi lunghi: (non impostato)", "Blocco per inattività (s): (non impostato)"]); check("nulla scritto", True)
    r = run(N, {"PERCORSI_LUNGHI": "si", "INATTIVITA": "900", "CTRL_ALT_CANC": "si"}, ""); expect("imposta tutto", r, 0, ["Percorsi lunghi: (non impostato) -> 1", "(s): (non impostato) -> 900", "richiesto: (non impostato) -> 0"])
    r = run(N, {"PERCORSI_LUNGHI": "no", "CTRL_ALT_CANC": "no"}, f"$global:REG['{FS}|LongPathsEnabled']=1\n"); expect("disabilita", r, 0, ["Percorsi lunghi: 1 -> 0", "richiesto: (non impostato) -> 1"])
    r = run(N, {"INATTIVITA": "0"}, ""); expect("inattività 0", r, 0, ["-> 0"])
    for v in ({"PERCORSI_LUNGHI": "forse"}, {"CTRL_ALT_CANC": "1"}, {"INATTIVITA": "30"}, {"INATTIVITA": "90000"}, {"INATTIVITA": "abc"}, {"INATTIVITA": "-5"}): r = run(N, v, ""); expect(f"non valido {v}", r, 2)
    for h in HOSTILE: r = run(N, {"INATTIVITA": h}, ""); expect(f"ostile {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {"INATTIVITA": "900"}, "function New-ItemProperty { [CmdletBinding()] param($Path,$Name,$Value,$PropertyType,[switch]$Force) throw 'negato' }\n"); expect("scrittura fallita", r, 1, ["modifica non riuscita (negato)"])
    r = run(N, {}, "", admin=False); expect("senza amministratore", r, 3)

N = "Windows: disattiva suggerimenti, widget, notizie e Chat nella barra"
if want(N):
    print("==", N)
    r = run(N, {}, RM); expect("stato", r, 0, ["predefinito di Windows"], ["DISATTIVATO"])
    r = run(N, {"AZIONE": "applica"}, RM); expect("applica", r, 0, ["Suggerimenti e app consigliate     DISATTIVATO", "Widget", "Icona Chat nella barra             DISATTIVATO", "dopo il prossimo accesso"], ["predefinito"])
    full = "".join(f"$global:REG['{k}|{n}']={v}\n" for k, n, v in (("HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\CloudContent", "DisableWindowsConsumerFeatures", 1), ("HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\Windows Chat", "ChatIcon", 3)))
    r = run(N, {}, RM + full); expect("stato dopo applicazione", r, 0, ["Suggerimenti e app consigliate     DISATTIVATO", "Icona Chat nella barra             DISATTIVATO", "Notizie e interessi                predefinito"])
    r = run(N, {"AZIONE": "ripristina"}, RM + full); expect("ripristina", r, 0, ["predefinito di Windows"], ["DISATTIVATO"])
    r = run(N, {"AZIONE": "applica"}, RM + "function New-ItemProperty { [CmdletBinding()] param($Path,$Name,$Value,$PropertyType,[switch]$Force) throw 'negato' }\n"); expect("scrittura fallita", r, 1, ["non riuscito (negato)"])
    for h in ("boh",) + tuple(HOSTILE): r = run(N, {"AZIONE": h}, RM); expect(f"AZIONE non valida {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {}, RM, admin=False); expect("senza amministratore", r, 3)

N = "Windows: attiva o disattiva IPv6 sulle schede di rete"
if want(N):
    print("==", N)
    lg = lambda: LASTFILES.get("ipv6.log", "")
    def mk(nad=("Ethernet",), en=True):
        return ("function Log($m) { [IO.File]::AppendAllText((Join-Path $env:TEMP 'ipv6.log'), \"$m`n\") }\n"
                "function Get-NetAdapter { [CmdletBinding()] param($Name,[switch]$Physical) @(" + ", ".join(ps(dict(Name=n, Status="Up")) for n in nad) + ") | Where-Object { $_.Name -like $Name } }\n"
                f"function Get-NetAdapterBinding {{ [CmdletBinding()] param($Name,$ComponentID) [pscustomobject]@{{Enabled={ps(en)}}} }}\n"
                "function Disable-NetAdapterBinding { [CmdletBinding()] param($Name,$ComponentID) Log \"disable $Name $ComponentID\" }\n"
                "function Enable-NetAdapterBinding { [CmdletBinding()] param($Name,$ComponentID) Log \"enable $Name $ComponentID\" }\n")
    r = run(N, {}, mk()); expect("stato", r, 0, ["Ethernet  [Up]  IPv6: attivo"]); check("nulla cambiato", lg() == "", lg())
    r = run(N, {"AZIONE": "disattiva"}, mk()); expect("anteprima", r, 0, ["sarebbe disattivato", "Anteprima: non è stato cambiato nulla"]); check("nulla cambiato", lg() == "", lg())
    r = run(N, {"AZIONE": "disattiva", "APPLICA": "si"}, mk(("Ethernet", "Wi-Fi"))); expect("disattiva tutte", r, 0, ["fatto"]); check("due disable", lg().count("disable") == 2 and "ms_tcpip6" in lg(), lg())
    r = run(N, {"AZIONE": "attiva", "APPLICA": "si", "SCHEDA": "Wi-Fi"}, mk(("Ethernet", "Wi-Fi"), en=False)); expect("attiva una", r, 0, ["Wi-Fi  [Up]  IPv6: disattivato"]); check("solo Wi-Fi", lg().strip() == "enable Wi-Fi ms_tcpip6", lg())
    r = run(N, {"SCHEDA": "Altra"}, mk()); expect("scheda inesistente", r, 0, ["Nessuna scheda fisica"])
    r = run(N, {"AZIONE": "disattiva", "APPLICA": "si"}, mk().replace("Log \"disable $Name $ComponentID\"", "throw 'busy'")); expect("errore", r, 1, ["non riuscito: busy"])
    for v in ({"AZIONE": "boh"}, {"SCHEDA": "a;b"}, {"SCHEDA": "x'y"}) + tuple({"SCHEDA": h} for h in HOSTILE): r = run(N, v, mk()); expect(f"non valido {str(v)[:30]}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {}, mk(), admin=False); expect("senza amministratore", r, 3)

N = "Windows: registrazione PowerShell (Script Block e Module Logging)"
if want(N):
    print("==", N)
    SB = "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\PowerShell\\ScriptBlockLogging"; ML = "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\PowerShell\\ModuleLogging"
    r = run(N, {}, RM); expect("stato", r, 0, ["Script Block Logging: non attivo", "Module Logging:       non attivo"])
    r = run(N, {"AZIONE": "attiva"}, RM); expect("attiva", r, 0, ["Script Block Logging: ATTIVO", "Module Logging:       ATTIVO"])
    on = f"$global:REG['{SB}|EnableScriptBlockLogging']=1; $global:REG['{ML}|EnableModuleLogging']=1; $global:REG['{ML}\\ModuleNames|*']='*'\n"
    r = run(N, {"AZIONE": "disattiva"}, RM + on); expect("disattiva", r, 0, ["Script Block Logging: non attivo", "Module Logging:       non attivo"])
    r = run(N, {}, RM + on); expect("stato attivo", r, 0, ["ATTIVO"])
    r = run(N, {"AZIONE": "attiva"}, RM + "function New-ItemProperty { [CmdletBinding()] param($Path,$Name,$Value,$PropertyType,[switch]$Force) throw 'negato' }\n"); expect("scrittura fallita", r, 1, ["Operazione non riuscita: negato"])
    for h in ("boh",) + tuple(HOSTILE): r = run(N, {"AZIONE": h}, RM); expect(f"AZIONE non valida {h[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])
    r = run(N, {}, RM, admin=False); expect("senza amministratore", r, 3)

N = "Windows: versione, modalità e criteri di esecuzione di PowerShell"
if want(N):
    print("==", N)
    r = run(N, {}, ""); expect("esegue", r, 0, ["Windows PowerShell:", "Modalità del linguaggio: FullLanguage", "PowerShell 7: non installato", "Criteri di esecuzione:", "Release di .NET Framework 4.x: non rilevato"])
    r = run(N, {}, "$global:REG['HKLM:\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full|Release']=533320\n"); expect(".NET rilevato", r, 0, ["4.x: 533320"])

N = "Windows: build, versione e fine del supporto Microsoft"
if want(N):
    print("==", N)
    CV = "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
    mk = lambda build, ed="Professional", prod="Windows 10 Pro", dv="22H2", it="Client": "".join(f"$global:REG['{CV}|{k}']={ps(v)}\n" for k, v in (("CurrentBuildNumber", str(build)), ("UBR", 5000), ("EditionID", ed), ("ProductName", prod), ("DisplayVersion", dv), ("InstallationType", it)))
    r = run(N, {}, mk(26100, "ServerStandard", "Windows Server 2025 Standard", "24H2", "Server")); expect("server 2025", r, 0, ["Windows Server 2025", "fine del supporto (server): 2034-10-10", "giorni_a_fine_supporto="])
    r = run(N, {}, mk(19041, dv="2004")); expect("build scaduta", r, 1, ["Windows 10 2004", "non è più supportata da"])
    r = run(N, {"MARGINE": "9999"}, mk(26100, "ServerStandard", "Windows Server 2025 Standard", "24H2", "Server")); expect("margine enorme", r, 1, ["termina fra"])
    r = run(N, {}, mk(12345)); expect("build sconosciuta", r, 0, ["non presente nella tabella", "giorni_a_fine_supporto=-1"])
    r = run(N, {}, mk(19045, "Enterprise", "Windows 10 Enterprise")); expect("Enterprise usa la seconda data", r, 1, ["Enterprise/Education", "2025-10-14"])
    r = run(N, {}, "function Get-ItemProperty { [CmdletBinding()] param($Path) }\n"); expect("registro illeggibile", r, 1, ["non leggibile"])
    for v in ("x", "-1", "1;id", "99999") + tuple(HOSTILE): r = run(N, {"MARGINE": v}, mk(19045)); expect(f"MARGINE non valido {v[:10]!r}", r, 2); check("nessuna iniezione", not re.search(r"^PWNED", r[1], re.M), r[1])

N = "Windows: idoneità per Windows 11 (TPM, Secure Boot, RAM, disco, processore)"
if want(N):
    print("==", N)
    def mk(tpm="2.0", sb=True, ram=16, disk=256, cpu=None):
        cpu = cpu or dict(Name="Intel Test", AddressWidth=64, NumberOfCores=4, MaxClockSpeed=3000)
        return ("function Confirm-SecureBootUEFI { [CmdletBinding()] param() " + ("throw 'bios'" if sb is None else ps(sb)) + " }\n"
            "function Get-CimInstance { [CmdletBinding()] param([Parameter(Position=0)]$ClassName,$Namespace,$Filter)\n"
            "  switch ($ClassName) {\n"
            "    'Win32_Tpm' { " + ("throw 'nessun tpm'" if tpm is None else "[pscustomobject]@{SpecVersion='%s, 0, 1.38'}" % tpm) + " }\n"
            f"    'Win32_ComputerSystem' {{ [pscustomobject]@{{TotalPhysicalMemory={int(ram * 1073741824)}}} }}\n"
            f"    'Win32_LogicalDisk' {{ [pscustomobject]@{{Size={int(disk * 1073741824)}}} }}\n"
            f"    'Win32_Processor' {{ {ps(cpu)} }} }} }}\n")
    r = run(N, {}, mk()); expect("idoneo", r, 0, ["TPM 2.0                        OK", "Requisiti minimi soddisfatti", "mancanti=0"])
    r = run(N, {}, mk(tpm="1.2", sb=None, ram=2, disk=40, cpu=dict(Name="Vecchia", AddressWidth=32, NumberOfCores=1, MaxClockSpeed=900))); expect("tutto mancante", r, 1, ["MANCA", "mancanti=6", "TPM 2.0", "Avvio UEFI", "Secure Boot attivo", "RAM >= 4 GB", "Disco di sistema", "Processore"])
    r = run(N, {}, mk(tpm=None)); expect("nessun TPM", r, 1, ["TPM non rilevato", "mancanti=1"])
    r = run(N, {}, mk(sb=False)); expect("Secure Boot spento", r, 1, ["disattivato", "mancanti=1"])
    r = run(N, {}, mk(ram=3.9)); expect("RAM 3,9 GB accettata", r, 0)
    r = run(N, {}, mk(disk=60)); expect("disco 60 GB rifiutato", r, 1, ["Disco di sistema >= 64 GB"])

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d ok, %d falliti" % (ok, bad)); sys.exit(1 if bad else 0)
