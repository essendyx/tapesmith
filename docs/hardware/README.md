# Hardware-Befunde P12

Gerät: Phomemo P12, Firmware 1.0.0, Verbindung über Bluetooth SPP (ausgehender COM-Port). Seriennummer und MAC-Adresse sind in dieser Doku durch Beispielwerte ersetzt.

## Grundbefund (2026-09-26)

Rohdaten: `2026-09-26-p12-verify.json` (Testreihe `p12 verify`), `2026-09-26-p12-calibration.json`.

| Punkt | Ergebnis | Status |
|---|---|---|
| Referenzlabel (soburi-identischer Datenstrom) | druckt identisch zum alten Label | belegt |
| Antworten über SPP | ja, alle Statusabfragen nach ca. 60 ms | belegt |
| Antwort auf Rasterkopf, Raster, Vorschub | keine (Timeout) | belegt → nur nach Abfragen auf Antwort warten |
| Akku `1F1108` | `1A 04 <Prozent>` (75 %) | belegt |
| Deckel `1F1112` | **P12 invertiert:** `1A 05 99` = offen, `1A 05 98` = zu (phomymo umgekehrt) | belegt |
| Spontanmeldungen | ja, Deckel öffnen/schließen wird ungefragt gemeldet (`1A 05 99`, `1A 05 98`) | belegt |
| Abfragen doppelt beantwortet | Deckelabfrage lieferte zwei gleiche Antworten | beobachtet |
| Band `1F1111` | `1A 06 89` bei eingelegtem Band, auch bei offenem Deckel; „leer“ (`88`) ungeprüft | teilweise |
| `1F1138` | `1A 17 03`, Bedeutung unbekannt | offen |
| `1F1113` | `1A 03 A8`, laut phomymo „Überhitzung“, beim P12 vermutlich anders | offen |
| Medium `1F1119` | `1A 0C 0B` = endlos | belegt |
| Seriennummer `1F1109` | ASCII, `A1B2C3D4E5F6G7H` | belegt |
| Druckbare Kopfzeilen | 4 bis 91 (Offset 4, 88 Punkte); soburi nutzte 8 bis 95 | belegt, kalibriert |
| Längenfaktor | 100 mm → 98,5 mm gedruckt, Faktor 1,0152 | belegt, kalibriert |
| Vor-/Nachlauf | je 8 mm | belegt |
| Pacing (Wartezeit vor Trennen) | Kantentest 12 cm und Lineal vollständig | belegt |

### Bewusst noch offen
- Band entnommen / leer (`1A 06 88`) am Gerät prüfen
- Job-Ende-Signal (keines beobachtet)
- Puffer-/Längenlimit langer Labels
- Druckdichte-Befehl (phomymo #45)
- Statusdecoder geräteabhängig machen (Deckel invertiert), Antwortwartezeit nur für Abfragen

## Befund Textlabel, QR und Nachlauf (2026-09-27)

| Punkt | Ergebnis | Status |
|---|---|---|
| Textlabel `p12 text "pmx10 SSD-1 SN 274913" --max-mm 60` (Schrift 38, DejaVu Sans) | oben/unten nichts abgeschnitten, auch Unterlänge „p“ | belegt |
| QR V1-M, 4-Punkt-Module, Ruhezone quer zum Band nur Bandrand (`datentraeger-qr`) | Handy-Scan liefert `112233274913` | belegt |
| Nachlauf nach dem Druck (ohne Zusatz) | ca. 16 mm Leerband nach dem Inhalt, Inhalt wird beim Hebel-Schnitt nicht abgeschnitten | belegt (Messung mit +9 mm Testnachlauf: 26 mm) |
| Leere Rolle | Drucker nimmt den Job an, es kommt nichts heraus; Status meldete weiterhin „Band ok“ (`1A 06 89`) | beobachtet → Band-leer-Erkennung bleibt ungeprüft |

## Kommandozeile: offen für den Gerätetest

Alles unten ist im Code umgesetzt und mit Tests ohne Drucker abgesichert, aber noch nicht am P12 geprüft:

- **Chunk-Übertragung:** Raster wird in Blöcken à 256 Zeilen geschrieben. Druckt ein langes Label (z. B. 100 mm) ohne Aussetzer/Streifen?
- **Abbruch (Strg+C):** Rest des angekündigten Labels wird weiß aufgefüllt, dann Vorschub. Druckt der P12 danach sauber weiter, kein hängender Job?
- **Kette ≤ 200 mm je Job:** `p12 text "Kabel 01" --length-mm 30 --copies 10 --chain --yes` -> 2 Jobs; kommen beide vollständig heraus?
- **Schnittlinien:** gestrichelte Linie zwischen den Kettengliedern sichtbar und mit der Schere gut zu treffen?
- **Preflight-Laufzeit:** Statusabfrage vor jedem Druck (Akku, Band, Deckel): wie lange verzögert sie den Druckstart?
- **Band leer:** weiterhin unbelegt, der P12 meldete bei leerer Rolle „Band ok“; Warnung ist nur Hinweis.
- **`trailer_mm`:** in `calibration.json` 16 mm prüfen (Messung: ca. 16 mm Nachlauf); die Bandbilanz der Kette hängt davon ab.
- **Verbindungs-Timeout:** Drucker aus -> `p12 text x` meldet nach ca. 5 s (`connect_timeout_s`) Exit 5 statt nach 8 s.
- **Hex-Log:** `--hexlog` schreibt `1a0599` jetzt als „Deckel offen“ (invertierter P12-Code); am Gerät gegenprüfen.

## Editor und Inhalte: offen für den Gerätetest

Im Code umgesetzt und ohne Drucker getestet, am P12 noch zu prüfen:

- **Code128 Modul 2/3:** Vorlage `asn` (`p12 template print asn`) mit Modul 3 und testweise Modul 2: lesen Handy und Paperless/zxing den Barcode zuverlässig?
- **DataMatrix:** Editor-Objekt bzw. `p12 print` mit DataMatrix `S4EWNX0R123456`: Modulgröße ausreichend, scanbar?
- **Invertierte Codes auf Weiß-auf-Schwarz:** Band `weiss-schwarz` wählen, `datentraeger-qr` drucken (Vorlagenseite, Schnelldruck mit QR-Feld, QR-Assistent). Module ungedruckt, Ruhezone gedruckt; liest das Handy den QR?
- **Kabelfahne beide Ausrichtungen:** `kabelfahne` quer und längs: Text auf beiden Fahnenhälften lesbar, Mittelteil passt um das Kabel?
- **Kabelwickel-Haftung:** `kabelwickel` um ein dünnes Kabel: hält der Wickel, überlappt der Klebebereich?
- **Raster-Genauigkeit:** nach Vorschub-Kalibrierung (Lineal 100 mm) Raster-Vorlage (`raster-patchpanel`) drucken: passen die Felder über die ganze Länge auf das Patchpanel?
- **Schwarzanteil bei niedrigem Akku:** großflächig schwarzes Label bei Akku < 30 %: Streifen/Aussetzer? Hinweis erscheint?
- **Schneidpause-Timing:** `p12 text x --copies 3 --cut-pause 0` bzw. Oberfläche mit „Weiter“: bleibt der Drucker während der Pause verbunden, schneidet sich jedes Label sauber?
- **Restmeter-Schätzung:** neue Rolle beginnen (`p12 tape new-roll`), bis zum Ende drucken, `p12 tape empty`: wie weit lag die Schätzung daneben, konvergiert der gelernte Faktor?

## Dienst und Windows: offen für den Gerätetest

Im Code umgesetzt und ohne Drucker getestet, am P12 noch zu prüfen:

1. Parallel-Druck GUI/CLI/Hotkey über den Dienst (keine „belegt"-Meldung, drei Quellen im Verlauf).
2. Warteschlange + BLE-Probe (Drucker aus → „wartet", einschalten → Nachdruck, Deckel offen → Pause).
3. BLE-Transport (`p12 ble scan`, `--transport ble`, Name/Adresse/Notify-Antworten/Druckqualität).
4. USB-Diagnose (`p12 usb`: Treiber usbprint/HID/usbser).
5. Blockmodus 255 Zeilen (Lücke/Versatz an Blockgrenzen?).
6. Statusanzeige/Deckel (Chip, Titelleiste, Tooltip, MAC-Antwort auf `1F 11 20` notieren, bisher nicht dekodiert).
7. Hotkey/AltGr (Strg+Alt+L öffnet `/schnelldruck` im Browser, `@ € µ { [ ] } \ ~ |` weiter tippbar).
8. Zwischenablage-Arten (SN, by-id, URL, IP, MAC, 2/5 Zeilen, Bild).
9. Kontextmenü/URI (User installiert selbst mit `p12 integrate install`, danach `uninstall`).
10. SSH-Scanner pmx10 (Abgleich mit `lsblk` auf dem Host).
11. `p12 raw`-Spontanmeldungen (`--listen` bei Deckel auf/zu; Bedeutung von `1F1138`/`1F1113`).
12. Dichte-Teststreifen nach HCI-Snoop (`p12 density`, Effekt „dunkler nach Print-Master" gegenprüfen).

Ergebnisse hier eintragen; erst danach werden die betroffenen Werte im Geräteprofil als `verified` markiert.

## Web-Oberfläche: offen für den Gerätetest

Web-Oberfläche (nur Browser plus Tray), Browserstart und Qt-Abbau sind im Code umgesetzt und ohne Drucker getestet, am P12
und am Windows-Rechner noch zu prüfen:

1. `p12 app` öffnet die Oberfläche im Standardbrowser (bei laufendem Dienst in unter 2 s); das Token verschwindet sofort aus der Adresszeile; hell/dunkel und Akzentfarbe folgen Windows.
2. Schnelldruck im Browser: Enter druckt, Fortschritt läuft, Abbrechen bricht sauber ab.
3. Hotkey Strg+Alt+L öffnet `/schnelldruck` als neuen Browser-Tab (Zeit messen, Ziel unter 1,5 s), Enter druckt; die Tray-App öffnet dabei kein eigenes Fenster. Strg+Alt+Umschalt+L öffnet den Schnelldruck mit dem Text der Zwischenablage vorbelegt und druckt nicht selbst. Linksklick aufs Tray-Symbol öffnet die Web-Oberfläche.
4. Tray „Web-Oberfläche öffnen“ öffnet die Oberfläche im Standardbrowser; ein zweites Öffnen öffnet einen zweiten, gleichwertigen Tab. Mit gestopptem Dienst (`p12 daemon stop`) startet „Öffnen“ ihn neu; mit `daemon.enabled = false` erscheint eine Tray-Benachrichtigung (kein Fenster) „Web-Oberfläche nicht geöffnet“ mit Grund.
5. Paralleldruck Browser, `p12 text` und Hotkey ohne „belegt“.
6. Schneidpause mit Leertaste im Browser.
7. Editor 100 % nach Bildschirm-Kalibrierung entspricht echten Millimetern; Druck entspricht der Vorschau.
8. Kontextmenü/URI nach erneutem `p12 integrate install --context --uri` öffnen die Oberfläche im Browser vorausgefüllt, Druck erst nach Bestätigung.
9. Portable `Tapesmith.exe` ohne Argument öffnet den Browser; `--tray`, `--daemon`, Selbsttest ok; im Ordner `_internal` liegt kein `webview`, `pythonnet` oder `clr_loader`.
10. Export (PNG/PDF) im Browser landet im Download-Ordner.
11. Browser ohne Token zeigt nur den Hinweis; Port von anderem Rechner nicht erreichbar.
12. Bandwechsel und neue Rolle wirken auf alle Vorschauen und den Restmeter.

Ergebnisse hier eintragen.

## Homelab-Prüfungen

Die Homelab-Integrationen (Seite Homelab, CLI-Befehle aus README „Homelab-Integrationen“) sind
im Code umgesetzt und nur mit aufgezeichneten Antworten getestet. Erst nach den Infrastruktur-Aktionen
(Kurz-Link-Dienst, Proxmox-Rolle, Paperless-Token, HA-Token) gegen die echten Dienste und am P12 prüfen.
Status je Prüfung hier fortschreiben (offen, ok, Befund).

| Nr. | Prüfung | Status |
|---|---|---|
| 1 | Kurz-Link: `https://<kurz-domain>/health` antwortet vom Handy im Mobilfunknetz; ein Test-Link `/T1` leitet auf das Ziel um (Familienhandy mit privatem DNS prüfen). Asset-Label `HL-0001` drucken, QR mit Handykamera scannen: öffnet das Ziel; Ziel in der Seite Assets ändern, gleicher QR führt aufs neue Ziel. | offen |
| 2 | Paperless-ASN: `p12 asn reserve 1 --print --preview asn.png` (reserviert die Nummer, schreibt nur die Vorschau) und ein echtes ASN-Label drucken, auf ein Blatt kleben, einscannen: Paperless setzt die ASN (Barcode-Erkennung, Präfix passend zu `PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX`). Erst danach Serien (Kette) drucken. Fehldruck mit `p12 asn void … --grund` verwerfen. | offen |
| 3 | Garantie: in der Seite Paperless eine echte Rechnung suchen, Garantie-Etikett drucken, QR öffnet das Dokument in Paperless. | offen |
| 4 | Proxmox: nach dem Rollen-Skript zeigt `p12 proxmox list pmx10` VMs und LXCs mit IPs (VMs mit Guest-Agent), fehlende Rechte ergeben „IP unbekannt“ statt Abbruch; Kette `vm-lxc` für zwei Gäste drucken. | offen |
| 5 | Plattentausch: an einem Host mit intaktem Pool zeigt der Assistent „keine defekten Geräte“; mit einer testweise per `zpool offline` genommenen Spare- bzw. Test-Pool-Platte (nur wenn gewünscht, nie am Produktivpool) erscheint sie als OFFLINE, Befehl zum Kopieren, Labels alt und neu als Vorschau. | offen |
| 6 | Obsidian: Seite Vault listet `Hosts/`, Frontmatter von `Hosts/pmx10` wird zu Werten, Label `host-ip` über den Direktdruck der Vault-Seite drucken: bei eingeschaltetem „Nach dem Druck Vermerk in die Vault-Notiz schreiben“ steht danach eine Zeile „Label gedruckt: …“ in der Notiz (im Vault prüfen), bei ausgeschaltetem nicht. Snippet: Markdown-Zeile in der Zwischenablage, PNG im Anhangsordner (falls `obsidian.vault_dir` gesetzt). | offen |
| 7 | Home Assistant: Seite Batterien listet Geräte mit Batterie (auch Homematic IP), Typ setzen, Batterie-Label drucken; optional erscheint das To-do in HA. | offen |
| 8 | SN-Scan: Handy-Foto vom Aufkleber einer SSD/HDD in der Seite Seriennummer scannen hochladen, Seriennummer wird erkannt, Datenträger-Label drucken, SN stimmt mit `p12 disks scan` überein. | offen |
| 9 | Kleinanzeigen: Artikel anlegen, Label mit QR auf die Anzeige drucken, Status „reserviert“ mit Name setzen und Reserviert-Etikett drucken. | offen |
| 10 | NetBox: echten Kabel-Export (CSV) importieren, Zuordnung prüfen, Kabelfahnen-Serie als Vorschau; TIA-606-Schema `R1.U01:P01` bis `P24` als Serie. | offen |
| 11 | Plausibilität: Datenträger-Label mit einer SN eines anderen Hosts ausfüllen: Konflikt wird angezeigt, Druck erst nach „Trotzdem drucken“. | offen |

## LAN und Automatisierung: Prüfungen am Gerät und im Heimnetz

LAN-Freigabe, Tokens, Familienseite, Kurzendpunkte, MCP, Hotfolder, PowerShell-Modul, Home
Assistant und Telegram sind im Code umgesetzt und ohne Drucker, Broker und Netz getestet
(`tests/test_e2e_lan_automation.py` u. a.). Am P12, am Handy und im Heimnetz noch zu prüfen (Handy im WLAN
`192.0.2.0/24`, `<PC-IP>` ist die LAN-Adresse der Workstation):

| Nr. | Prüfung | Ergebnis |
|---|---|---|
| 1 | Ohne `lan.enabled` ist `http://<PC-IP>:8712/health` vom Handy nicht erreichbar. | offen |
| 2 | Firewall-Skript als Administrator (`deploy/infra/setup-tapesmith-lan.ps1`), `p12 config set lan.enabled true`, `p12 daemon restart`: `/health` vom Handy antwortet ohne `home_key`. | offen |
| 3 | Familien-Token anlegen (`p12 token add Handy --rolle familie` oder Seite „Zugriff“), Link auf dem Handy öffnen, `gefriergut` drucken; andere Seiten (z. B. `/api/v1/history`) liefern keine Daten. | offen |
| 4 | 11 falsche Tokens vom Handy: 429 für 15 min, lokal keine Störung; Widerruf sperrt die Familienseite. | offen |
| 5 | Admin-Token im Browser eines LAN-PCs: volle Oberfläche, Seite Zugriff. | offen |
| 6 | Home Assistant: Gerät „Labeldrucker P12“, Deckel öffnen zeigt „offen“ (P12-Invertierung korrekt), Knopf Testlabel druckt, Skript druckt eine Vorlage. | offen |
| 7 | Hotfolder: JSON druckt und landet in `done\`, kaputte Datei in `error\` mit `.log`. | offen |
| 8 | MCP in Claude Code: Vorschau ja, Druck nur nach Bestätigung. | offen |
| 9 | PowerShell: `Get-P12Status`, `Send-P12Label -WhatIf`, Pipeline aus `Get-PhysicalDisk`. | offen |
| 10 | Telegram: Testnachricht, „Warteschlange hängt“ bei ausgeschaltetem Drucker, Ruhezeit ohne Meldung. | offen |
| 11 | Uptime-Kuma-Monitor auf `/health` grün, Alarm bei beendetem Dienst. | offen |

Ergebnisse hier eintragen.

## Feinschliff: Prüfungen am PC

Feinschliff, Barrierefreiheit, Editor-Tabs, Installer, Auto-Update und Englisch sind im Code
umgesetzt und ohne Drucker, Netz und echte Registry getestet (`tests/test_e2e_app.py`, Vitest mit
axe, Screenshots mit axe im echten Chromium). Probeinstallation, Deinstallation und Update-Probe liefen
nur in Temp-Ordnern mit Testschlüssel. Noch am PC zu prüfen, Punkte 3 bis 5 erst nach den
Infrastruktur-Aktionen (Signaturschlüssel, Release, siehe `deploy/infra/README.md`,
Abschnitt „Release und Update“). Status je Prüfung hier fortschreiben (offen, ok, Befund).

| Nr. | Prüfung | Status |
|---|---|---|
| 1 | Frisches Benutzerprofil (neuer lokaler Windows-Benutzer ohne Adminrechte): `Tapesmith-portable-0.2.0.zip` entpacken, `Installieren.cmd` doppelklicken: keine UAC-Abfrage, Startmenü-Eintrag „Tapesmith“ (öffnet den Standardbrowser), Eintrag unter „Installierte Apps“, Tray startet, Kontextmenü und `tapesmith://`-Link öffnen die Oberfläche im Browser, Autostart nach Neuanmeldung. | offen |
| 2 | Deinstallieren je einmal über „Installierte Apps“ und über die Startmenü-Verknüpfung: Programmordner, Startmenü und Registry-Einträge sind weg, `%APPDATA%\Tapesmith` (Einstellungen, Verlauf) bleibt erhalten. | offen |
| 3 | Update-Pfad GitHub: 0.2.0 installiert, Release 0.2.1 veröffentlicht; Einstellungen › Updates „Jetzt prüfen“ zeigt 0.2.1, „Jetzt installieren“: Dienst startet neu, die Oberfläche öffnet sich mit 0.2.1 in einem neuen Browser-Tab auf Einstellungen › Updates, Verlauf und Einstellungen unverändert. Automatisch: `update.auto_install` an, alle Browser-Tabs mit der Oberfläche schließen, nach der Leerlaufzeit ist 0.2.1 aktiv. | offen |
| 4 | Rückfall: absichtlich defektes Release (z. B. Selbsttest scheitert) veröffentlichen: es wird nicht umgeschaltet bzw. automatisch zurückgestellt, Meldung in Einstellungen › Updates; `p12 update rollback` stellt manuell zurück. | offen |
| 5 | Signatur: Release mit verändertem Zip (Prüfsumme passt nicht) wird abgelehnt (`update.checksum_mismatch`); ohne hinterlegten Schlüssel meldet die Seite „Kein vertrauenswürdiger Signaturschlüssel“. | offen |
| 6 | HiDPI: Anzeige auf 150 % und 200 % skalieren: Tray-Symbol scharf mit Statusabzeichen, Web-Oberfläche ohne abgeschnittene Texte, Browser-Zoom 200 % ohne waagrechtes Scrollen. | offen |
| 7 | Dunkelmodus und Kontrast: Windows auf dunkel und zurück, Oberfläche und Tray-Kontextmenü folgen live; Kontrastdesign „Wüste“ bzw. „Nachthimmel“: alles lesbar, Fokus sichtbar. | offen |
| 8 | Sprache: Einstellungen › Oberfläche auf English: Oberfläche und Tray-Menü sofort englisch, Fehlermeldung (z. B. Drucker aus) mit englischem Titel; zurück auf „wie Windows“. | offen |
| 9 | Tastatur und Screenreader: ganze App nur mit Tastatur bedienen (Tab, Pfeile, Enter, Esc, `?` für die Kürzel-Übersicht); Sprachausgabe (Narrator) liest Seitenleiste, Knöpfe und Vorschau-Text vor. | offen |
| 10 | Absturz-Wiederherstellung: im Editor zwei Tabs mit ungespeicherten Änderungen, Browserprozess im Task-Manager beenden, über das Tray neu öffnen: Wiederherstellung wird angeboten, beide Tabs kommen zurück. Dasselbe mit beendetem `p12d`-Prozess während der Bearbeitung (Autosave läuft nach dem Neustart weiter). | offen |
| 11 | Browser-Tab schließen oder neu laden mit ungespeicherten Änderungen: der Browser fragt mit seinem eigenen Dialog nach („Seite verlassen?“), „Abbrechen“ bzw. „Bleiben“ lässt die Seite offen; ohne Änderungen schließt der Tab ohne Rückfrage. | offen |
| 12 | Problem melden: Einstellungen › Hilfe und Diagnose › „Problem melden“ lädt ein Zip; darin keine Tokens (Stichprobe in `logs\` und `config.json`). | offen |
