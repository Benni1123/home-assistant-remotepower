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
  Das löst **keine Scans, Upgrades oder Befehle** aus.

## Sicherheit und Bedeutung der Aktionen

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
`mode_standard`, `mode_extended`.

Für die letzten fünf zusätzlich `confirm: true` setzen und Steueraktionen in
den Integrationsoptionen erlauben. Die Antwort liefert je Host `scan_queued`,
`queued`, `applied`, `approval_required` oder `failed`.
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
