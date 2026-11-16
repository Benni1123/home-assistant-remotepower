# RemotePower for Home Assistant

[English](#english) · [Deutsch](#deutsch)

<a id="english"></a>

## English

Custom integration for [RemotePower](https://github.com/tyxak/remotepower),
developed against the RemotePower 8.0 API and source code. This is not an
official RemotePower integration. Automated tests cover simulated API responses
and real Home Assistant entity/repair APIs with a fake host; full live-system
validation is still ongoing.

### Features

- One device per host; new hosts are discovered automatically.
- Sensors: pending updates, security updates, operating system, package manager,
  agent version and last contact.
- Binary sensors: online, reboot required, maintenance and protected Proxmox host.
- Fleet summary: online hosts, total pending updates and hosts without current
  update data.
- **Rescan package data** button: request a fresh inventory and upgrade count.
  This is the equivalent of **Packages → Scan now** in RemotePower, using the
  same `/api/devices/<id>/scan-packages` endpoint. It does not refresh repository
  indexes or install packages.
- **Search for updates (APT)** button: check that `apt-get` exists, run the fixed
  `apt-get -o APT::Update::Error-Mode=any update` command, wait for confirmed success,
  then request an inventory scan. Enable it in the integration options first.
  It also works before the agent has identified the package manager, without
  a preliminary manual scan. If APT is missing, it stops without requesting a
  scan. A host with an already known non-APT manager remains excluded.
- Additional buttons, disabled by default: **Upgrade packages**, **Reboot**,
  **Shut down**, **Rescan ACME certificates** and **Upgrade packages without
  cleanup (APT)**.
- **APT upgrade mode** selection: Standard / Extended, disabled by default.
- Action status, update history with confirmed exit codes, last package-report
  and boot timestamps. Available and kept-back package names are sensor attributes.
- Reboot requirements combine the **system flag and separate kernel/hardware
  flag**, including kernel alerts not shown as a reboot badge in RemotePower's
  patch overview.
- HA Repairs issues for reboot requirements, failed actions and a configurable
  number of pending package updates. Reboot repairs offer an explicit
  **Perform reboot** confirmation, never automatic execution.
- Proxmox host safeguards and a separate APT upgrade path without `autoremove`,
  cache cleanup or an automatic reboot.
- Bulk actions skip hosts covered by active maintenance windows.
- Connection editing through **Reconfigure** and diagnostics without credentials,
  addresses, hostnames or raw command output.
- `remotepower.bulk_action` explicitly targets host IDs, a group or all monitored hosts.
- English and German UI.
- Original RemotePower integration icons at standard and double resolution.
  Local integration branding requires **Home Assistant 2026.3 or newer**.
  Older supported HA versions work without the icon. Images originate from
  RemotePower, copyright 2025 tyxak, MIT license; see
  `custom_components/remotepower/brand/LICENSE`.

Unknown or offline update counts are **not displayed as zero**. The fleet total
stays unknown while any host lacks current counts. Offline status and metadata
remain visible. Disappeared hosts are not automatically deleted from the device registry.

### Installation

1. In HACS, add this repository as a custom repository of type **Integration**.
   Alternatively copy `custom_components/remotepower` to
   `/config/custom_components/remotepower`.
2. Restart Home Assistant.
3. Open Settings → Devices & services → Add integration → **RemotePower**.
4. Enter the HTTPS server URL, for example `https://remotepower.local:8443`,
   and a dedicated API key.
5. For a self-signed certificate whose CA is not trusted by HA, explicitly
   disable **Verify TLS certificate** if you accept the risk described below.
6. Under **Configure**, optionally enable APT refresh and control actions.
   Enable the additional buttons and upgrade-mode selection in the entity registry.

#### Self-signed HTTPS

Certificate verification is **on by default**. Disabling it accepts self-signed
certificates but is **not certificate pinning**: an unrelated certificate is
accepted too. Only use this on a trusted network. Prefer a trusted certificate
or add your private CA to HA's trust store. The integration does not download
and trust an unverified CA or change global SSL settings.
Plain HTTP and redirects are rejected to protect the API key.

#### API keys and permissions

Create a dedicated key for HA in RemotePower's API Keys settings.
Authentication uses `X-Token`; keys are not logged. HA stores the key in the
configuration entry, not in an external secret vault.

- A **viewer** key is sufficient for sensors.
- In the inspected server code, direct package scans, ACME scans, upgrade-mode
  changes and `/api/exec/wait` require admin permissions. An **admin** API key
  covers all integration features but is not restricted to those features.
- Where possible, limit the key to the required hosts by group/tag/site,
  HA's source IP and an appropriate expiration date.
- Cached reports are read every 60 seconds by default, configurable from 30
  to 3600 seconds. Without a previously requested operation, polling does not
  trigger host actions. A confirmed HA-requested upgrade receives the one-time
  follow-up package scan described below.

### Safety and action semantics

#### Action status and history

A successful queue response means **Waiting for agent**, not successful execution.
Status changes use fresh command results and exit codes. A lower update count
or RemotePower's “verified” badge is **not proof of command success**.
Disappearance from the queue only means **Dispatched; result unconfirmed**,
not reliably “running”: the inspected API exposes no authoritative execution-start event.

Native upgrades do not provide a unique command ID linking the request to its
result. The integration compares command type, results not present in the
pre-request history and server timestamps. Simultaneous identical actions
from other clients cannot be conclusively distinguished; multiple matching
results produce **Result unknown**. The separate no-cleanup upgrade path uses
a unique marker and a fingerprint of the full command instead.

After confirmed upgrade success, a package scan is requested **once**, even if
a kept-back package remains. The scan intent is persisted before the request,
preventing replay after an HA restart. If the scan fails or remains unconfirmed,
request it manually. Upgrades are never retried automatically.
The last package-report timestamp, `pkg_scan_ts`, records receipt by the server,
not necessarily a fresh `apt update`.

Current HA operations and the previous ten operations per host are stored
locally without raw commands or output. After an HA restart, observation resumes
without executing the request again. An operation without a confirmed result
after two hours becomes **Result unknown**, not “failed”.

A reboot is only confirmed when the host is online again and reports a changed
boot timestamp. Without a known pre-reboot timestamp, success cannot be asserted.
An offline or unreachable host alone does not prove a successful reboot or shutdown.

#### Proxmox safeguards

Proxmox is detected through reported Proxmox package names, a Proxmox OS label,
the `ProxmoxHost` / `proxmox-host` group or the **`proxmox-host`** tag.
Detection is remembered even after the last pending Proxmox packages are upgraded.
A kernel name containing `-pve` alone is deliberately insufficient because
LXCs share the host kernel. **Explicitly tag undetected PVE hosts with
`proxmox-host` before enabling controls.**

The native upgrade with automatic cleanup is blocked on detected PVE hosts.
**Upgrade packages without cleanup (APT)** uses a fixed `apt-get update`
followed by `apt-get upgrade --with-new-pkgs`, retains existing configuration
files and runs no `autoremove`, `clean` or `reboot`.
If `update-initramfs` exists, a kernel module tree must be visible; otherwise
the command stops as a precaution. This path uses RemotePower's normal command
execution and approval mechanisms.
It can still restart services and install kernels: it is not a replacement for
backups, maintenance windows or checking Proxmox upgrade notes.

Reboot, shutdown and the no-cleanup upgrade path on detected PVE hosts also
require **Allow Proxmox host power actions and upgrades without cleanup**.
An ordinary HA entity button cannot provide a reliable interactive confirmation
on every invocation, so these controls are explicitly gated.

#### Maintenance and repairs

Global maintenance state and maintenance windows are refreshed immediately before
a bulk action. Active device, group, site, tag and global windows are considered.
Smart-group membership cannot be evaluated locally: an active smart window
conservatively excludes the entire selection. Unknown maintenance formats or
failed maintenance requests block the batch rather than bypassing safeguards.
This is intentionally stricter than RemotePower's execution-allowing change
windows: **active maintenance windows exclude hosts from HA bulk actions**.

Repair issues can be disabled in the integration options. The reboot repair
dialog requires explicit confirmation and applies the same control, Proxmox
and approval safeguards as the regular reboot button. A queued reboot leaves
the issue open until fresh host data clears both system and kernel reboot
requirements. Existing reboot issues remain while hosts are offline.
Kernel reboot requirements use RemotePower's structured flag, not a guess based
on different version strings.

**Package-update repairs:** Under **Configure**, set a per-host threshold:
default **100**, **0 = off**, maximum 100000. For example, a threshold of 10 creates
**“XX package updates available: Hostname”** at **10 or more** pending updates.
The same issue is updated with the current count, not duplicated for each package.
A fresh online report below the threshold removes it. Unknown/offline counts
preserve an existing issue but do not create a new one.
The global repair-issues option must also be enabled. These issues provide a
link to RemotePower and never install packages automatically.

#### Connection editing and diagnostics

Choose **Reconfigure** from the integration's three-dot menu. The URL, key and
TLS settings are validated with read-only requests. Failed validation leaves
the previous connection unchanged. An empty API-key field retains the existing
key without displaying it. The entry, devices and entity IDs are preserved.
Use this for the same RemotePower instance after an address or credential change.

Diagnostics use an allowlist: no URL, API key, hostname, package names, IPs,
tags, groups, raw commands or output. Hosts are represented by anonymous
numbers with states and timestamps.

#### Additional operational notes

- Upgrade, power and mode changes require the control-actions option.
  Automations can trigger power actions without an interactive prompt once
  their entities are enabled.
- **Upgrade packages** uses RemotePower's native upgrade endpoint. Its Linux
  command currently includes `autoremove` and cache cleanup. Do not confuse
  this with an update search or a single-package upgrade. Extended mode can
  install additional dependencies and new kernel packages.
- RemotePower maker-checker approval, command allowlists and agent audit mode
  are not bypassed. A queued action has **not yet been executed**.
- Approval requirements appear in service responses; individual buttons show
  a corresponding message.
- RemotePower implements ACME rescanning for Linux only. Other hosts may be rejected.
- APT search waits up to 120 seconds for a result. After a timeout or connection
  failure, the command may still run. **Do not blindly retry**; check RemotePower's
  command history. Write requests are not automatically retried. After a manually
  approved or late-completing APT search, use **Rescan package data**.
- HA prevents parallel calls to the same host. Other clients may still act.
  The reported command and exit code are checked before scanning after APT refresh.
- A scan normally appears after one or two agent contacts. An HA restart does
  not immediately install packages or execute a host query.

### Bulk actions

In Developer tools → Actions, select **RemotePower: Run bulk action** and choose
the integration entry. Set exactly **one** target filter: host IDs, a group name
or `all_monitored: true`.

```yaml
action: remotepower.bulk_action
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  action: scan_packages
  group: devices
```

Supported actions:
`scan_packages`, `search_updates`, `scan_acme`, `upgrade`, `reboot`, `shutdown`,
`mode_standard`, `mode_extended`, `upgrade_no_cleanup`.

Upgrades, power actions and mode changes also require `confirm: true` and
enabled control actions in the integration options.
Per-host results are `scan_queued`, `queued`, `applied`, `approval_required`,
`skipped_maintenance` or `failed`. Scripts can capture them with `response_variable`.
There is no default selection of every host. Offline hosts are rejected.
Native upgrade and power batches are sent as a batch to RemotePower so that
single-host requests do not bypass its batch limits. Those limits are not
automatically overridden.
Bulk actions are **not a rolling-reboot orchestrator**: queued reboots may
happen at practically the same time. Shutting down the host running HA or
RemotePower also stops the corresponding management interface.

### Releases and local test builds

A manually installed **0.2.2** test build can later be updated to **1.0.0**
through HACS once the repository is registered there and that release has
been published. A lower local manifest version alone neither registers an
integration with HACS nor publishes a release. There is no separate built-in
OTA updater in this integration.

### Development

```sh
python -m pip install aiohttp voluptuous
python -m unittest discover -s tests -v
```

Local tests use simulated API responses and lightweight HA test doubles,
without credentials or actions on real hosts. CI additionally checks imports
and exercises real Home Assistant entity, issue-registry and repair-flow APIs
with a fake host. This is not an end-to-end test of a live RemotePower deployment.

---

<a id="deutsch"></a>

## Deutsch

Custom Integration für [RemotePower](https://github.com/tyxak/remotepower),
entwickelt anhand der RemotePower-8.0-API und ihres Quellcodes. Keine offizielle
RemotePower-Integration. Automatische Tests prüfen simulierte API-Antworten
und echte HA-Entitäts-/Reparatur-APIs mit einem simulierten Host; die vollständige
Prüfung an laufenden Systemen ist noch nicht abgeschlossen.

### Funktionen

- Ein Gerät je Host; neue Hosts werden automatisch entdeckt.
- Sensoren: Updates, Sicherheitsupdates, Betriebssystem, Paketmanager,
  Agent-Version, letzter Kontakt.
- Binärsensoren: online, Neustart erforderlich, Wartung und geschützter Proxmox-Host.
- Gesamtübersicht: Hosts online, Updates gesamt, Hosts ohne aktuelle Update-Daten.
- Button **Paketdaten neu erfassen**: Inventar und Upgrade-Anzahl neu melden.
  Entspricht **Packages → Scan now** in der RemotePower-Weboberfläche
  (derselbe API-Endpunkt `/api/devices/<id>/scan-packages`).
  Erneuert keine Paketlisten und installiert nichts.
- Button **Nach Updates suchen (APT)**: festes `apt-get -o
  APT::Update::Error-Mode=any update`, Erfolg abwarten, danach Inventar-Scan.
  Nach Freischaltung in den Optionen nutzbar, auch wenn der Agent den Paketmanager
  noch nicht erkannt hat. Der Befehl prüft zuerst auf dem Host, ob `apt-get`
  vorhanden ist; bei Fehlen wird ohne Scan abgebrochen. Ein vorheriger manueller
  Paketscan ist nicht erforderlich. Bei bereits erkanntem Nicht-APT-Paketmanager
  bleibt der APT-Button gesperrt.
- Zusätzliche, anfangs deaktivierte Buttons: **Pakete aktualisieren**,
  **Neustarten**, **Herunterfahren**, **ACME-Zertifikate neu erfassen** und
  **Pakete ohne Bereinigung aktualisieren (APT)**.
- Anfangs deaktivierte Auswahl **APT-Upgrade-Modus**: Standard / Erweitert.
- Aktionsstatus und Update-Verlauf mit bestätigtem Exitcode, letztem Paketbericht
  und letztem Systemstart. Updatepakete und zurückgehaltene Pakete als Attribute.
- Neustartbedarf aus **System-Flag und separatem Kernel-/Hardware-Flag**.
  Der Kernelalarm wird dadurch auch dann angezeigt, wenn die RemotePower-
  Patch-Übersicht keinen Reboot-Badge darstellt.
- HA-Reparaturmeldungen bei Neustartbedarf, fehlgeschlagenen Aktionen und
  einer einstellbaren Anzahl ausstehender Paketupdates;
  Bestätigungsdialog **Neustart durchführen**, keine automatische Ausführung.
- Schutz erkannter Proxmox-Hosts und zusätzlicher APT-Upgrade-Button ohne
  `autoremove`, Cache-Bereinigung oder automatischen Neustart.
- Sammelaktionen überspringen Hosts in aktiven Wartungsfenstern.
- Verbindung bearbeiten über **Neu konfigurieren**; Diagnoseexport ohne
  Zugangsdaten, Adressen, Hostnamen und rohe Befehlsausgaben.
- Sammelaktionen per `remotepower.bulk_action`, explizit für Host-IDs,
  eine Gruppe oder alle überwachten Hosts.
- Deutsche und englische Oberfläche.
- Originales RemotePower-Integrationsicon in normaler und doppelter Auflösung.
  Lokale Integrationsicons benötigen Home Assistant **2026.3 oder neuer**;
  auf älteren unterstützten Versionen funktioniert die Integration ohne Icon.
  Die Bilder stammen aus RemotePower (Copyright 2025 tyxak, MIT-Lizenz);
  siehe `custom_components/remotepower/brand/LICENSE`.

Unbekannte oder offline Update-Zahlen werden **nicht als null** angezeigt.
Die Gesamtzahl bleibt unbekannt, sobald ein Host keine aktuellen Zahlen hat.
Offline-Status und Metadaten bleiben sichtbar. Verschwundene Hosts werden
nicht ungefragt aus der Geräteregistrierung gelöscht.

### Installation

1. HACS → benutzerdefinierte Repositories → dieses Repository als **Integration**
   hinzufügen. Alternativ `custom_components/remotepower` nach
   `/config/custom_components/remotepower` kopieren.
2. Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **RemotePower**.
4. HTTPS-URL (z. B. `https://remotepower.local:8443`) und eigenen API-Schlüssel eingeben.
5. Bei deinem selbst signierten Zertifikat **TLS-Zertifikat überprüfen**
   abwählen, falls die CA nicht im Vertrauensspeicher von HA liegt.
6. Unter **Konfigurieren** bei Bedarf APT-Suche und Steueraktionen erlauben.
   Die zusätzlichen Buttons und die Auswahl danach in der Entitätsverwaltung
   aktivieren.

#### Selbst signiertes HTTPS

Zertifikatsprüfung ist standardmäßig **an**. Das explizite Abschalten akzeptiert
selbst signierte Zertifikate, ist aber **kein Certificate Pinning**:
auch ein fremdes Zertifikat wird akzeptiert. Nur in vertrauenswürdigen Netzen
verwenden; besser ein vertrauenswürdiges Zertifikat einsetzen oder die private
CA im HA-Vertrauensspeicher hinterlegen. Die Integration lädt keine CA ungeprüft
herunter und ändert keine globalen SSL-Einstellungen.
HTTP und Weiterleitungen sind nicht erlaubt, um den API-Schlüssel zu schützen.

#### API-Schlüssel und Rechte

RemotePower API Keys: eigenen Schlüssel nur für HA erzeugen.
Authentifizierung über `X-Token`, Schlüssel werden nicht geloggt.
HA speichert den Schlüssel in seinem Konfigurationseintrag (kein externer Tresor).

- **viewer** reicht für Sensoren.
- Der direkte Paket-Scan, ACME-Scan, Upgrade-Modus und `/api/exec/wait` erfordern
  im geprüften Code Admin-Rechte. Ein **admin**-API-Key deckt alle Funktionen ab,
  ist aber nicht auf diese Funktionen beschränkt.
- Schlüssel nach Möglichkeit auf benötigte Hosts (Gruppe/Tag/Standort),
  HA-Quell-IP und eine angemessene Laufzeit begrenzen.
- Sensoren werden automatisch alle 60 Sekunden gelesen (30–3600 einstellbar).
  Ohne zuvor angeforderten Auftrag löst dies keine Hostaktionen aus. Ein
  bestätigtes, über HA angefordertes Upgrade erhält den beschriebenen
  einmaligen Follow-up-Paketscan.

### Sicherheit und Bedeutung der Aktionen

#### Aktionsstatus und Verlauf

Eine positive Queue-Antwort wird als **Wartet auf Agent**, nicht als erfolgreicher
Abschluss angezeigt. Statuswechsel verwenden neue Befehlsresultate und deren
Exitcode. Die Verringerung der Update-Anzahl / RemotePowers „verified“-Badge
ist dafür **kein Erfolgsnachweis**. Ein aus der Queue verschwundener Auftrag
heißt nur **Übergeben; Ergebnis unbestätigt**, nicht nachweislich „läuft“.
Für eine belastbare Startmeldung stellt die geprüfte API keinen Startzeitpunkt bereit.

Für native Upgrades stellt RemotePower keinen eindeutigen Command-ID-Bezug
zwischen Auftrag und Ergebnis bereit. Die Integration vergleicht Befehlstyp,
neue Resultate gegenüber einem vorab gelesenen Verlauf und Serverzeitstempel.
Zeitgleiche identische Fremdaktionen können nicht zweifelsfrei unterschieden
werden; mehrere passende Resultate ergeben **Ergebnis unbekannt**.
Der separate Upgrade-ohne-Bereinigung-Weg verwendet dagegen eine eindeutige
Kennung und den Fingerabdruck des vollständigen Befehls.

Nach bestätigtem Upgrade-Erfolg wird **einmalig** ein Paketscan angefordert,
auch wenn noch ein zurückgehaltenes Paket übrig ist. Die Scanabsicht wird vor
dem API-Aufruf gespeichert, damit ein HA-Neustart keinen doppelten Request
verursacht. Scheitert der Scan oder bleibt sein Ergebnis unklar, kann er
manuell angestoßen werden. Es gibt keine automatische Wiederholung von Upgrades.
Zeitpunkt der letzten Paketmeldung (`pkg_scan_ts`) ist der Eingang beim Server,
nicht zwingend der Zeitpunkt eines frischen `apt update`.

Aktuelle HA-Aktionen und die letzten zehn vorherigen Aktionen werden lokal
gespeichert, ohne rohe Befehle oder Ausgaben. Nach einem HA-Neustart wird nur
weiter beobachtet, nie erneut ausgeführt. Bleibt nach zwei Stunden ein
Ergebnis aus, lautet der Zustand **Ergebnis unbekannt**, nicht „fehlgeschlagen“.

Ein Neustart ist erst bestätigt, wenn der Host wieder online ist und einen
neuen Systemstartzeitpunkt meldet. Ohne bekannten vorherigen Systemstart kann
kein Erfolg behauptet werden. Ein ausgeschalteter oder unerreichbarer Host
allein beweist keinen erfolgreichen Neustart oder Shutdown.

#### Proxmox-Schutz

Die Integration erkennt Proxmox anhand gemeldeter Proxmox-Paketnamen, einer
Proxmox-Betriebssystembezeichnung, der Gruppe `ProxmoxHost` / `proxmox-host`
oder des Tags **`proxmox-host`**. Die Erkennung wird gespeichert, damit sie
nach dem Installieren der letzten ausstehenden Proxmox-Pakete nicht verschwindet.
Eine Kernelbezeichnung mit `-pve` allein reicht absichtlich nicht, da LXCs
denselben Kernel teilen. **Nicht erkannte PVE-Hosts ausdrücklich mit
`proxmox-host` markieren**, bevor Steueraktionen verwendet werden.

Für erkannte PVE-Hosts ist das native Upgrade mit automatischer Bereinigung
gesperrt. **Pakete ohne Bereinigung aktualisieren (APT)** nutzt ein festes
`apt-get update` plus `apt-get upgrade --with-new-pkgs`, übernimmt bestehende
Konfigurationsdateien und führt kein `autoremove`, `clean` oder `reboot` aus.
Falls `update-initramfs` vorhanden ist, muss ein Kernelmodulbaum sichtbar sein;
andernfalls bricht der Befehl vorsorglich ab.
Dieser Weg nutzt die normale RemotePower-Befehlsausführung und deren Freigaben.
Er kann trotzdem Dienste neu starten und Kernelpakete installieren: kein
Ersatz für Backups, Wartungsfenster und Prüfung der Proxmox-Versionshinweise.

Host-Neustarts/Shutdowns und der bereinigungsfreie Upgrade-Weg erfordern für
erkannte PVE-Hosts zusätzlich **Proxmox-Host-Stromaktionen und Upgrades ohne
Bereinigung erlauben**. Auf einer HA-Entitätskarte gibt es keine verlässliche
interaktive Sicherheitsabfrage bei jedem Knopfdruck; deshalb diese Sperren.

#### Wartung und Reparaturen

Vor einer Sammelaktion werden globale Wartung und Wartungsfenster frisch
gelesen. Aktive Geräte-, Gruppen-, Standort-, Tag- und globale Fenster werden
berücksichtigt. Smart-Gruppen kann die Integration nicht lokal auswerten:
bei einem aktiven Smart-Fenster wird konservativ die gesamte Auswahl
ausgeschlossen. Ein unbekanntes Wartungsformat oder eine fehlgeschlagene
Abfrage blockiert die Sammelaktion, statt den Schutz zu überspringen.
Das ist bewusst strenger als RemotePowers ausführungsfreigebende Change-Windows:
**aktive Wartungsfenster schließen Hosts aus HA-Sammelaktionen aus**.

Reparaturen lassen sich in den Optionen abschalten. Der Neustart-Dialog
erfordert eine ausdrückliche Bestätigung und nutzt dieselben Steuer-, Proxmox-
und Freigabesicherungen wie der normale Reboot-Button. Nach „vorgemerkt“
bleibt die Reparatur offen, bis neue Hostdaten keinen System- und keinen
Kernel-Neustartbedarf mehr melden. Bei Offline-Hosts bleibt eine bestehende
Neustartmeldung erhalten. Ein Kernelalarm wird nicht aus unterschiedlichen
Versionsstrings erraten, sondern aus RemotePowers strukturiertem Kernel-Flag.

**Paketupdate-Reparaturen:** Unter **Konfigurieren** ist ein Schwellenwert je
Host einstellbar (Standard **100**, **0 = aus**, maximal 100000). Bei beispielsweise
10 eingestellten Updates erscheint ab **10 einschließlich** eine Warnung
**„XX Paketupdates verfügbar: Hostname“**. Die Zahl wird aktualisiert, statt
für jedes Paket eine eigene Reparatur anzulegen. Ein neuer Online-Bericht
unterhalb des Schwellenwerts entfernt sie. Bei unbekannten Paketdaten oder
Offline-Hosts bleibt eine bestehende Warnung erhalten; aus solchen Daten wird
keine neue Warnung erzeugt. Die allgemeine Option **Reparaturmeldungen anzeigen**
muss ebenfalls aktiv sein. Diese Meldung installiert nichts und bietet nur
einen Link zu RemotePower, keine ungefragte Update-Aktion.

#### Verbindung und Diagnose

Im Drei-Punkte-Menü der Integration **Neu konfigurieren** wählen. URL, Schlüssel
und TLS-Prüfung werden lesend validiert; bei Fehlern bleibt die alte Verbindung
unverändert. Leerer Schlüssel behält den bisherigen, ohne ihn im Formular
anzuzeigen. Eintrags-ID, Geräte und Entitäts-IDs bleiben erhalten. Für dieselbe
RemotePower-Instanz nach Adress-/Zugangsdatenänderung verwenden.

Diagnosen arbeiten mit einer Positivliste: keine URL, API-Schlüssel,
Hostnamen, Paketnamen, IPs, Tags, Gruppen, rohen Befehle oder Ausgaben.
Die anonymisierte Zuordnung enthält nur Hostnummern, Zustände und Zeitstempel.

#### Weitere Betriebshinweise

- Upgrade/Stromaktionen/Modusänderungen erfordern die Option **Steueraktionen
  erlauben**. In Automationen können Stromaktionen ohne interaktive Nachfrage
  laufen, sobald du ihre Entitäten aktivierst.
- Paketupgrade verwendet RemotePowers **nativen** Upgrade-Endpunkt. Dessen
  Linux-Befehl beinhaltet derzeit auch `autoremove` und Cache-Bereinigung.
  **Nicht** mit einer reinen Suche oder einem einzelnen Paketupdate verwechseln.
  Erweitert kann zusätzliche Abhängigkeiten und neue Kernelpakete installieren.
- RemotePower-Freigaben (Maker-Checker), Whitelists und Agent-Audit-Modus werden
  nicht umgangen. Eine vorgemerkte Aktion ist **noch nicht ausgeführt**.
- Meldet eine Aktion Freigabebedarf, wird das im Service-Ergebnis ausgewiesen;
  ein Einzelbutton zeigt eine entsprechende Meldung.
- ACME-Scan ist laut RemotePower nur für Linux implementiert; auf anderen
  Hosts kann der Server ihn ablehnen.
- APT-Suche wartet höchstens 120 Sekunden auf die Antwort. Bei Timeout oder
  Verbindungsabbruch kann der Befehl trotzdem noch laufen. **Nicht blind erneut
  drücken**, sondern den Verlauf in RemotePower prüfen. Keine automatischen
  Wiederholungen schreibender Requests. Nach einer manuell freigegebenen oder
  verspätet abgeschlossenen APT-Suche den Button **Paketdaten neu erfassen** nutzen.
- Hostaktionen sind in HA pro Host gegen parallele Aufrufe gesperrt.
  Andere Clients können trotzdem Aktionen auslösen. Die Integration prüft
  den gemeldeten Befehl und Exitcode, bevor sie einen Scan nach APT auslöst.
- Ein Scan erscheint typischerweise nach ein bis zwei Agentenkontakten.
  Keine sofortige Installation/Abfrage auf dem Host beim HA-Neustart.

### Sammelaktionen

Unter Entwicklerwerkzeuge → Aktionen **RemotePower: Sammelaktion ausführen**
auswählen. Den Integrationseintrag im Formular wählen. Genau **einen**
Zielfilter setzen: Host-IDs, Gruppenname oder `all_monitored: true`.

```yaml
action: remotepower.bulk_action
data:
  entry_id: DEINE_KONFIGURATIONSEINTRAGS_ID
  action: scan_packages
  group: devices
```

Mögliche Aktionen:
`scan_packages`, `search_updates`, `scan_acme`, `upgrade`, `reboot`, `shutdown`,
`mode_standard`, `mode_extended`, `upgrade_no_cleanup`.

Für Upgrades, Stromaktionen und Modusänderungen zusätzlich `confirm: true` setzen und Steueraktionen in
den Integrationsoptionen erlauben. Die Antwort liefert je Host `scan_queued`,
`queued`, `applied`, `approval_required`, `skipped_maintenance` oder `failed`.
In Skripten kann sie über `response_variable` gespeichert werden.
Es gibt keine Standardauswahl aller Hosts. Offline-Hosts werden abgelehnt.
Upgrade- und Strom-Sammelaktionen gehen als native Batch-Anfrage an RemotePower,
damit dessen Batch-Begrenzungen nicht durch einzelne Anfragen umgangen werden.
Die Integration setzt keine automatische Übersteuerung dieser Begrenzungen.
Sammelaktionen sind **kein Rolling-Reboot-Orchestrator**: vorgemerkte Neustarts
können praktisch gleichzeitig stattfinden. Bei HA und RemotePower auf demselben
Host beendet dessen Herunterfahren auch die jeweilige Verwaltungsoberfläche.

### Veröffentlichungen und lokale Testversionen

Eine manuell installierte Testversion **0.2.2** kann später über HACS auf
**1.0.0** aktualisiert werden, sobald das Repository dort registriert und
dieses Release veröffentlicht ist. Eine niedrigere lokale Manifest-Version
allein registriert keine Integration in HACS und veröffentlicht kein Release.
Die Integration enthält keinen separaten eingebauten OTA-Updater.

### Entwicklung

```sh
python -m pip install aiohttp voluptuous
python -m unittest discover -s tests -v
```

Die lokalen Tests verwenden simulierte API-Antworten und kleine HA-Test-Doubles,
ohne Zugangsdaten oder Aktionen auf echten Hosts. Die CI prüft zusätzlich
Imports und echte HA-Entitäts-, Issue-Registry- und Reparatur-APIs mit einem
simulierten Host. Das ist kein Ende-zu-Ende-Test einer laufenden RemotePower-Instanz.
