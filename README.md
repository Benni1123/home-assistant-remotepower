# RemotePower für Home Assistant

Custom Integration für [RemotePower](https://github.com/tyxak/remotepower).
Erste Version, anhand des RemotePower-8.0-Quellcodes entwickelt. Noch nicht
gegen eine echte Instanz getestet. Keine offizielle RemotePower-Integration.

## Funktionen

- Ein Gerät je Host; neue Hosts werden automatisch entdeckt.
- Sensoren: Updates, Sicherheitsupdates, Betriebssystem, Paketmanager,
  Agent-Version, letzter Kontakt.
- Binärsensoren: online und Neustart erforderlich.
- Gesamtübersicht: Hosts online, Updates gesamt, Hosts ohne aktuelle Update-Daten.
- Button **Paketdaten neu erfassen**: Inventar und Upgrade-Anzahl neu melden.
  Entspricht **Packages → Scan now** in der RemotePower-Weboberfläche
  (derselbe API-Endpunkt `/api/devices/<id>/scan-packages`).
  Erneuert keine Paketlisten und installiert nichts.
- Button **Nach Updates suchen (APT)**: festes `apt-get -o
  APT::Update::Error-Mode=any update`, Erfolg abwarten, danach Inventar-Scan.
  Nur für APT-Hosts und nach Freischaltung in den Optionen.
- Zusätzliche, anfangs deaktivierte Buttons: **Pakete aktualisieren**,
  **Neustarten**, **Herunterfahren**, **ACME-Zertifikate neu erfassen**.
- Anfangs deaktivierte Auswahl **APT-Upgrade-Modus**: Standard / Erweitert.
- Aktionsstatus und Update-Verlauf mit bestätigtem Exitcode, letztem Paketbericht
  und letztem Systemstart. Updatepakete und zurückgehaltene Pakete als Attribute.
- Neustartbedarf aus **System-Flag und separatem Kernel-/Hardware-Flag**.
  Der Kernelalarm wird dadurch auch dann angezeigt, wenn die RemotePower-
  Patch-Übersicht keinen Reboot-Badge darstellt.
- HA-Reparaturmeldung bei Neustartbedarf und fehlgeschlagenen Aktionen;
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

## Installation

1. HACS → benutzerdefinierte Repositories → dieses Repository als **Integration**
   hinzufügen. Alternativ `custom_components/remotepower` nach
   `/config/custom_components/remotepower` kopieren.
2. Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **RemotePower**.
4. HTTPS-URL (z. B. `https://10.0.0.109:8443`) und eigenen API-Schlüssel eingeben.
5. Bei deinem selbst signierten Zertifikat **TLS-Zertifikat überprüfen**
   abwählen, falls die CA nicht im Vertrauensspeicher von HA liegt.
6. Unter **Konfigurieren** bei Bedarf APT-Suche und Steueraktionen erlauben.
   Die zusätzlichen Buttons und die Auswahl danach in der Entitätsverwaltung
   aktivieren.

### Selbst signiertes HTTPS

Zertifikatsprüfung ist standardmäßig **an**. Das explizite Abschalten akzeptiert
selbst signierte Zertifikate, ist aber **kein Certificate Pinning**:
auch ein fremdes Zertifikat wird akzeptiert. Nur in vertrauenswürdigen Netzen
verwenden; besser ein vertrauenswürdiges Zertifikat einsetzen oder die private
CA im HA-Vertrauensspeicher hinterlegen. Die Integration lädt keine CA ungeprüft
herunter und ändert keine globalen SSL-Einstellungen.
HTTP und Weiterleitungen sind nicht erlaubt, um den API-Schlüssel zu schützen.

### API-Schlüssel und Rechte

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

## Sicherheit und Bedeutung der Aktionen

### Aktionsstatus und Verlauf (ab 0.2.0)

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

### Proxmox-Schutz

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

### Wartung und Reparaturen

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

### Verbindung und Diagnose

Im Drei-Punkte-Menü der Integration **Neu konfigurieren** wählen. URL, Schlüssel
und TLS-Prüfung werden lesend validiert; bei Fehlern bleibt die alte Verbindung
unverändert. Leerer Schlüssel behält den bisherigen, ohne ihn im Formular
anzuzeigen. Eintrags-ID, Geräte und Entitäts-IDs bleiben erhalten. Für dieselbe
RemotePower-Instanz nach Adress-/Zugangsdatenänderung verwenden.

Diagnosen arbeiten mit einer Positivliste: keine URL, API-Schlüssel,
Hostnamen, Paketnamen, IPs, Tags, Gruppen, rohen Befehle oder Ausgaben.
Die anonymisierte Zuordnung enthält nur Hostnummern, Zustände und Zeitstempel.

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

## Sammelaktionen

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

## Entwicklung

```sh
python -m pip install aiohttp voluptuous
python -m unittest discover -s tests -v
```

Tests mit simulierten API-Antworten, ohne Zugangsdaten oder Aktionen auf echten
Hosts. Die lokalen HA-Plattformtests nutzen kleine Test-Doubles; ein echter
HA-Lauf und der Test mit einer RemotePower-Instanz stehen noch aus.
