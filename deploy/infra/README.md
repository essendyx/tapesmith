# Betrieb von Tapesmith im Heimnetz

Betriebsdoku: LAN-Freigabe des Druckdienstes, Zugangs-Tokens, Home Assistant, Telegram, Hotfolder, MCP, PowerShell-Modul sowie Release und Update. Alles hier ist optional; ohne diese Schritte läuft Tapesmith nur lokal auf dem PC. Keine Secrets in dieser Datei, nur Pfad-Referenzen.

Skripte in diesem Ordner:

- `setup-tapesmith-lan.ps1`: legt die Windows-Firewallregel für den Druckdienst an, prüft oder entfernt sie (idempotent, einmaliger Admin-Schritt).
- `proxmox-tapesmith-role.sh`: legt auf einem Proxmox-Host eine Rolle nur mit Leserechten und ein API-Token für die Proxmox-Integration an.

## 1. Überblick

- Der Druckdienst **p12d** läuft auf dem PC mit dem Drucker und ist der einzige Inhaber der Druckerverbindung. Er bietet die Named Pipe und den HTTP-Server (REST-API, Web-Oberfläche, `/health`, `/mcp`) auf Port **8712** (`web.port`).
- **Standard ist nur localhost** (`127.0.0.1:8712`). Erst `lan.enabled = true` in `config.json` und ein Dienst-Neustart binden zusätzlich an das LAN (`lan.bind`, Standard `0.0.0.0`).
- Zugriff aus dem LAN nur von Adressen aus `lan.allowed_networks` (Standard `192.168.0.0/16`, am besten auf das eigene Netz einschränken) und nur mit API-Token. `/health` und die statischen Dateien der Oberfläche gehen aus erlaubten Netzen ohne Token.
- Die Windows-Firewallregel legt nie die App an, sondern einmalig `setup-tapesmith-lan.ps1` als Administrator.
- Konfiguration und Daten liegen unter `%APPDATA%\Tapesmith` (`config.json`, `access\tokens.json`, `hotfolder\`).

## 2. LAN-Freigabe Schritt für Schritt

1. PowerShell **als Administrator** öffnen (Rechtsklick, Als Administrator ausführen) und das Skript starten:

   ```powershell
   .\deploy\infra\setup-tapesmith-lan.ps1 -RemoteAddress 192.168.1.0/24
   ```

   Es legt die Regel `Tapesmith-LAN-TCP-8712` (Anzeigename „Tapesmith Druckdienst (TCP 8712, LAN)“, Gruppe „Tapesmith“) an: eingehend, TCP, Port 8712, nur die angegebenen Quellnetze (Standard `192.168.0.0/16`), Profile Privat und Domäne. Weitere Parameter: `-Port`, `-RemoteAddress 192.168.1.0/24, 10.10.0.0/16`, `-FirewallProfile Private`. Erlaubt sind nur private IPv4-Netze (10/8, 172.16/12, 192.168/16) mit Präfix mindestens 8, nie `Any`. Ein zweiter Aufruf ändert nichts („Regel ist aktuell, nichts geändert.“) oder setzt nur abweichende Werte. Mit `-WhatIf` zeigt es nur, was es tun würde.
2. Status prüfen (geht ohne Adminrechte):

   ```powershell
   .\deploy\infra\setup-tapesmith-lan.ps1 -Status
   ```

   Zeigt Regel, Aktivierung, Richtung, Aktion, Protokoll, Port, Quellnetze, Profile und auf welchen Adressen der Druckdienst lauscht.
3. LAN in der App einschalten: `p12 config set lan.enabled true` (oder Web-Oberfläche, Seite „Zugriff“).
4. Dienst neu starten, damit die Bindung wirkt: `p12 daemon restart`.
5. Von einem Gerät im Netz testen: `http://<PC-IP>:8712/health` liefert `{"ok": true, "app": ..., "version": ...}`.
6. Token anlegen (Abschnitt 3) und damit die Oberfläche oder API im LAN nutzen.

Rückbau:

- `.\deploy\infra\setup-tapesmith-lan.ps1 -Remove` (als Administrator) entfernt die Regel, falls vorhanden.
- `p12 config set lan.enabled false` und `p12 daemon restart`: der Dienst lauscht wieder nur auf localhost.

## 3. Tokens, Familienlink und Grenzen

- Anlegen: `p12 token add NAME --rolle admin|drucken|familie` (oder Web-Oberfläche, Seite „Zugriff“). Der Klartext erscheint **genau einmal**, danach nur noch ein Hinweis mit der Token-ID.
- Auflisten: `p12 token list`. Widerrufen: `p12 token revoke ID_ODER_NAME` (wirkt sofort, auch im laufenden Dienst).
- Rollen: `admin` (Verwaltung, alles), `drucken` (Drucken, Vorschau, Status, Warteschlange, Verlauf, MCP), `familie` (nur die Familien-Druckseite `/familie`).
- Gespeichert werden Tokens nur als SHA-256-Hash in `%APPDATA%\Tapesmith\access\tokens.json`. Wer das Token verliert, legt ein neues an.
- Familienlink: Für ein Token mit Rolle `familie` zeigt die Web-Oberfläche den Link `http://<PC-IP>:8712/familie#t=<Token>` an. Auf dem Handy öffnen und als Lesezeichen speichern, nicht weitergeben. Freigegebene Vorlagen stehen in `family.templates`.
- Rate-Limit: je LAN-Adresse höchstens 10 Fehlversuche (falsches Token) in 10 Minuten, danach 15 Minuten Sperre mit `429` und `Retry-After`, auch für `/health` und auch mit richtigem Token. localhost wird nie gesperrt.
- Grenzen für Fremdzugriffe (Quellen `api`, `mcp`, `mqtt`, `hotfolder`): höchstens `guard.confirm_copies` = 5 Kopien je Auftrag und Labels bis `guard.confirm_label_mm` = 150 mm. Darüber lehnt der Fehldruckschutz ab (`abgelehnt`), denn diese Quellen können Rückfragen des Fehldruckschutzes nicht bestätigen; `confirmed` bestätigt dort nur Band-Rückfragen. Dazu gelten die Kontingente je Stunde aus `guard.quotas`.

## 4. Home Assistant und MQTT

- Broker: ein MQTT-Broker im eigenen Netz (z. B. Mosquitto), eingetragen als `mqtt.host` und `mqtt.port`. Ein eigener Benutzer `tapesmith` mit ACL `tapesmith/#` (lesen und schreiben) und `homeassistant/#` (schreiben) ist empfehlenswert.
- Passwort in der App hinterlegen: `p12 secret set mqtt` (landet im Windows Credential Manager unter `tapesmith/mqtt`, Referenz `mqtt.password_ref = keyring:tapesmith/mqtt`). Prüfen: `p12 secret check mqtt`.
- Einschalten: `p12 config set mqtt.enabled true` (wirkt ohne Neustart innerhalb von etwa 5 s).
- Home Assistant findet das Gerät „Labeldrucker P12“ über MQTT-Discovery (Präfix `homeassistant`): Verbindung, Akku, Deckel, Warteschlange, Knopf „Testlabel“. Druck per Topic `tapesmith/print/set`.
- Beispiele für Skripte und Automationen: `deploy/homeassistant/README.md`.

## 5. Telegram

- Bot-Token: als Secret-Referenz in `telegram.token_ref` eintragen, entweder im Windows Credential Manager (`p12 secret set telegram` und `telegram.token_ref = keyring:tapesmith/telegram`) oder als Datei (`telegram.token_ref = file:<Pfad zu einer Datei mit dem Token in der ersten Zeile>`, die Datei liegt außerhalb jedes Repos und ist nur für den eigenen Benutzer lesbar). Prüfen: `p12 secret check telegram` (zeigt nie den Wert).
- Chat: `p12 config set telegram.chat_id <Chat-ID>`, dann `p12 config set telegram.enabled true`.
- Test: `p12 telegram test` (Ausgabe „Gesendet.“ oder „Fehler: ...“). Übersicht: `p12 telegram status`.
- Meldungen: Warteschlange hängt (`telegram.queue_stuck_min`), Drucker offline (`telegram.offline_min`), Druckfehler, Restmeter niedrig (`telegram.roll_low_m`). Je Zustand nur eine Meldung bis zur Erholung.
- Ruhezeiten: `telegram.quiet_hours` (Standard `22:00-07:00`), in dieser Zeit keine Meldungen.

## 6. Hotfolder

- Einschalten: `p12 config set hotfolder.enabled true`. Ordner: `hotfolder.dir`, Standard `%APPDATA%\Tapesmith\hotfolder`.
- Formate: `*.json` (`{"template": "gefriergut", "values": {...}, "copies": 2}`, `vars` gilt als Alias für `values`), `*.txt` (Textlabel, gleiche Zeilen werden zu Kopien zusammengefasst), `*.csv` (Tabelle für eine Vorlage), `*.png` (Bild).
- Eine Datei gilt als fertig, wenn Größe und Änderungszeit `hotfolder.settle_s` lang stabil sind. Erfolgreich gedruckt: Datei wandert nach `done\`. Fehler: Datei wandert nach `error\`, daneben eine `.log`-Datei mit dem Grund.
- Protokoll: `hotfolder.log` im Hotfolder (ohne sensible Werte). Status: `p12 hotfolder status`, einzelner Durchlauf: `p12 hotfolder run-once`.
- Grenzen wie in Abschnitt 3 (Quelle `hotfolder`).

## 7. MCP (Claude)

- Einrichtung anzeigen: `p12 mcp --config` (startet nichts).
- stdio für Claude Code auf diesem PC: `claude mcp add p12 -- <Pfad zum Repo>\.venv\Scripts\python.exe -m tapesmith.cli mcp` (bzw. `%LOCALAPPDATA%\Programs\Tapesmith\current\Scripts\python.exe` der installierten App). Der MCP-Prozess spricht per HTTP mit dem lokalen Druckdienst.
- HTTP-Variante im Dienst (`mcp.http = true`): `claude mcp add --transport http p12-http http://127.0.0.1:8712/mcp --header "Authorization: Bearer <TOKEN>"`. Das Token vorher mit `p12 token add Claude --rolle drucken` anlegen.
- Werkzeuge: `list_templates`, `label_preview`, `label_print`, `printer_status`, `print_history`, `queue_list`. Gedruckt wird nur mit einer `preview_id` aus `label_preview` und `confirm=true`.

## 8. PowerShell-Modul

Das Modul `Tapesmith` spricht die REST-API an (lokal mit der Sitzung des Dienstes, im LAN mit API-Token). Installation und Befehle: `deploy/powershell/Tapesmith/README.md`.

## 9. Überwachung und bekannte Fallen

- **Uptime-Monitor** (optional): Wer einen Monitor wie Uptime Kuma betreibt, prüft per HTTP `http://<PC-IP>:8712/health` auf das Schlüsselwort `"ok":true`, z. B. alle 60 s. Das geht erst mit LAN-Freigabe. Ist der PC aus, ist der Monitor rot (erwartet).
- **PowerShell-Pipe**: Binärdaten nie über PowerShell-Pipes führen, sie werden dort umkodiert.
- **270°**: Das Kopfbild wird intern um 270 Grad gedreht, bevor es als Raster gesendet wird.
- **COM-Blockade**: Ist der P12 aus oder eingeschlafen, blockiert das Öffnen des Bluetooth-COM-Ports 10 bis 20 s. Deshalb baut der Druckdienst die Verbindung im Worker mit Timeout auf und ist der einzige Inhaber der Verbindung.
- **Nicht-interaktive Quellen** (API, MCP, MQTT, Hotfolder) können Rückfragen des Fehldruckschutzes nicht bestätigen; gleiche Hotfolder-Aufträge werden 1,5 s lang entprellt.

## 10. Fehlersuche

- **Firewall-Dialog beim ersten Binden an 0.0.0.0**: Windows fragt beim ersten Start mit `lan.enabled = true`, ob Python im Netz kommunizieren darf. Mit der Regel aus `setup-tapesmith-lan.ps1` ist das nicht nötig; den Dialog abzulehnen ist in Ordnung, weil die Regel für Port 8712 und das Quellnetz gilt.
- **403 „Zugriff verweigert: Adresse nicht freigegeben“**: Die Client-Adresse liegt nicht in `lan.allowed_networks`, oder `lan.enabled` war beim Dienststart aus (nach dem Einschalten `p12 daemon restart`). Auch ein fremder Host-Header (Aufruf über einen Namen, der nicht in `lan.hostnames` steht) ergibt 403.
- **401 „Nicht angemeldet“**: Token fehlt oder ist falsch bzw. widerrufen. Neues Token mit `p12 token add` anlegen.
- **429 „Zu viele Fehlversuche“**: Nach 10 falschen Tokens in 10 Minuten ist die Adresse 15 Minuten gesperrt. Warten (Header `Retry-After`), localhost ist nicht betroffen.
- **`/health` ohne `home_key` im LAN**: So gewollt. LAN-Clients bekommen nur `ok`, `app` und `version`, localhost zusätzlich `home_key` und `pid`.
- **Dienst nicht erreichbar**: `.\deploy\infra\setup-tapesmith-lan.ps1 -Status` zeigt, ob die Regel aktiv ist und ob der Dienst auf `0.0.0.0:8712` lauscht.

## 11. Release und Update

Tapesmith wird über Python verteilt: das Paket `tapesmith` liegt auf PyPI, die installierte App
(`py -m tapesmith install`) hat je Version eine eigene Python-Umgebung unter
`%LOCALAPPDATA%\Programs\Tapesmith\versions\<Version>` und startet immer mit dem signierten
`pythonw.exe` (`-m tapesmith...`), nie mit einer eigenen EXE. So blockiert Windows Smart App Control
nichts, obwohl Tapesmith keine Code-Signatur hat.

Die installierte App sucht Updates in `update.source` (Standard: die GitHub-Releases des Projekts,
`github:essendyx/tapesmith`) und nimmt nur Manifeste an, deren Ed25519-Signatur zu einem Schlüssel in
`src/tapesmith/update/trusted_keys.json` passt. Das Manifest enthält eine vollständige Lock-Liste
(Paketname, Version und SHA-256 aller Wheels für `win_amd64` und die unterstützten
Python-Versionen). Der Updater legt damit eine neue Umgebung an, installiert mit
`pip install --require-hashes --only-binary=:all: -r lock.txt` (nur Dateien mit passender
Prüfsumme, nur fertige Wheels), führt den Selbsttest der neuen Version aus und schaltet erst im
Leerlauf um. Wer einen eigenen Fork verteilt, erzeugt einen eigenen Schlüssel und trägt die eigene
Quelle ein.

1. **Signaturschlüssel erzeugen** (einmalig, im App-Repo):

   ```
   .venv\Scripts\python tools\release.py keygen --private <Schlüsselordner>\tapesmith_update_signing_key.pem --public-out src\tapesmith\update\trusted_keys.json
   ```

   Der private Schlüssel liegt nur im gewählten Schlüsselordner außerhalb des Repos (das Werkzeug
   beschränkt die Rechte auf den aktuellen Benutzer), nie im Repo. Den öffentlichen Schlüssel in
   `trusted_keys.json` committen. Den Inhalt der PEM-Datei als Secret `TAPESMITH_UPDATE_SIGNING_KEY`
   im GitHub-Environment `release` hinterlegen. Schlüsseltausch: neuen Schlüssel mit `keygen`
   zusätzlich in `trusted_keys.json` aufnehmen, eine Version mit beiden Schlüsseln ausliefern, erst
   danach mit dem neuen signieren.
2. **Kein GitHub-Token nötig:** Das Repository ist öffentlich, die App fragt die Releases ohne Token ab.
3. **Release veröffentlichen:** Version in `pyproject.toml` und `src\tapesmith\__init__.py` erhöhen
   (PEP 440, z. B. `0.4.0` oder `0.4.0b1` für den Kanal `beta`), committen, Tag `v<Version>` pushen.
   Der Workflow `.github/workflows/release.yml` prüft die Version, führt die Tests aus, baut Web-Oberfläche,
   Wheel und sdist, lädt mit `pip download` für Python 3.11 und 3.12 alle Wheels, erzeugt daraus mit
   `tools\release.py` Manifest und `lock.txt`, signiert das Manifest (Environment `release` mit
   Freigabe), veröffentlicht auf PyPI per Trusted Publishing (Environment `pypi`) und legt das
   GitHub-Release mit `manifest.json`, `manifest.json.sig`, `lock.txt` und dem Wheel an.
4. **Dateifreigabe als Quelle** (optional, ohne PyPI): Wheels je Python-Version mit
   `py -3.11 -m pip download --only-binary=:all: -d wheels\py311 dist\tapesmith-<v>-py3-none-any.whl`
   (ebenso für 3.12) laden, dann `tools\release.py publish-dir --version <v> --wheels 3.11=wheels\py311
   --wheels 3.12=wheels\py312 --notes "…" --key <Schlüsselordner>\tapesmith_update_signing_key.pem
   --copy-wheels --out \\<server>\<freigabe>\tapesmith` und in der App
   `update.source = "file:\\<server>\<freigabe>\tapesmith"`. Liegen Wheels im Ordner (bzw. in
   `wheels`), installiert pip nur von dort. Der Benutzer braucht nur Leserecht, kein Token.
5. **Rückfall:** Meldet `/health` der neuen Version nicht binnen 60 s die neue Versionsnummer, stellt
   der Updater automatisch auf die vorige zurück und trägt die Version in `install.json` unter `failed`
   ein (nie wieder automatisch angeboten). Manuell: `p12 update rollback` bzw. Einstellungen › Updates
   › „Auf vorige Version zurück“. Protokoll: `%APPDATA%\Tapesmith\logs\update.log`.
6. **Umzug vom früheren portablen Build:** Die App-Versionen bis 0.3 waren eine PyInstaller-EXE. Sie
   können das neue Manifest (Schema 2) nicht lesen und melden bei der Update-Prüfung einen Fehler.
   Einmal `py -m pip install --user tapesmith` und `py -m tapesmith install` ausführen: die
   Installation übernimmt den Ordner, ersetzt Autostart, Startmenü und Apps-und-Features-Eintrag und
   entfernt die alte EXE. Benutzerdaten in `%APPDATA%\Tapesmith` bleiben unverändert.
