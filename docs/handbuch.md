# Tapesmith: Handbuch (deutsch)

Ausführliches Handbuch zu Tapesmith, der Windows-Anwendung für den Labeldrucker Phomemo P12
(Bluetooth, 12-mm-Band). Die englische Übersicht steht im [README](../README.md).

## Schnellstart

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\p12 doctor
.venv\Scripts\p12 print-image label.png        # Breite 96 oder bis 88 Punkte
.venv\Scripts\p12 --transport file:job.bin calibrate edge   # Trockenlauf
.venv\Scripts\p12 verify                       # geführte Testreihe (eigenes Konsolenfenster)
.venv\Scripts\p12 text "pmx10 SSD-1" "SN 274913" --max-mm 40 --preview v.png   # Text mit Auto-Fit, erst Vorschau
.venv\Scripts\p12 text "SSD-1" --qr S4EWNX0R123456                            # QR links, Text rechts
.venv\Scripts\p12 template list                                               # Vorlagen
.venv\Scripts\p12 template print datentraeger-qr --set sn=ata-SanDisk_SDSSDHP256G_112233274913
.venv\Scripts\python -m pytest                 # ohne Drucker
.venv\Scripts\python -m pytest --hardware      # mit Drucker
```
Exit-Codes: 0 ok, 1 Fehler/Konfiguration, 5 Drucker nicht erreichbar, 6 Vorlage oder Variable fehlt/ungültig, 7 Drucker belegt.

Eigene Vorlagen (`*.tapesmith.json`) liegen unter `%APPDATA%\Tapesmith\templates` und überschreiben gleichnamige mitgelieferte.

## Kommandozeile

Jeder Druck (`text`, `template print`, `print-image`, `print`, `qr`, `reprint`) läuft über die
Druck-Pipeline: Statusabfrage vorher (nur Warnung, blockiert nie), Fehldruckschutz mit Rückfrage,
Kopien und Ketten, Verlauf, Export und sauberer Abbruch mit Strg+C (Rest weiß, dann Vorschub).

```
p12 status                                    # Akku, Deckel, Band, Firmware (--json)
p12 setup --test-label                        # Port suchen, testen, in config.json speichern
p12 text "SSD-1" --copies 4 --chain           # 4 Kopien als Kette mit Schnittlinien (spart Vor-/Nachlauf)
p12 text "Kabel 01" --copies 10 --chain --yes # Rückfrage (viele Kopien/Überlänge) vorab bestätigen
p12 text "SSD-1" --export label.pdf           # zusätzlich als PDF/PNG/PBM ablegen (Endung bestimmt Format)
p12 text "pmx10 SSD-1 SN 274913" --size 60 --max-mm 30   # passt nicht -> Vorschläge "--fix …"
p12 text "pmx10 SSD-1 SN 274913" --size 60 --max-mm 30 --fix laenger
echo pmx10 | p12 print                        # Text von stdin
p12 print --image logo.png --fit              # Bild, zu große Bilder verkleinern
p12 qr wifi --ssid Gast --password-prompt     # Passwort nie als Argument (Shell-History)
p12 history 274913                            # Verlauf durchsuchen (auch Teilstrings)
p12 reprint last                              # letzten Auftrag nachdrucken (Kopien/Kette wie das Original)
p12 reprint 17 --copies 1                     # Eintrag 17, eigene Kopienzahl hat Vorrang
p12 reprint last --prompt pw                  # sensible Vorlage: Feld verdeckt neu eingeben
```

Gemeinsame Druckoptionen: `--preview DATEI.png` (nur Vorschau, bei Kopien/Kette mit Bandbilanz),
`--copies N`, `--chain`, `--no-cut-marks`, `-y/--yes`, `--export DATEI`.

`reprint`: Sensible Vorlagen (z. B. WLAN-Passwort) speichern weder Bild noch Klartext; beim Nachdruck
das Feld mit `--prompt FELD` verdeckt eingeben. WLAN-QRs aus `p12 qr wifi` bzw. der QR-Seite
speichern SSID, Sicherheitsart und Layout, das Passwort nur maskiert: `p12 reprint last --prompt password`
(die Oberfläche fragt es beim „Erneut drucken“ verdeckt ab). `--set FELD=WERT` geht auch, landet aber in der
Shell-History. Enthielt ein Auftrag mehrere verschiedene Labels, druckt `reprint` nur das erste
(in der CLI erzeugt jeder Befehl ohnehin genau ein Label je Auftrag).

Alt-Befehle (Kompatibilität zu phomemo-p12-tools): `phomemo_render_label` und `phomemo_print_p12`
werden mit installiert und verweisen auf die neuen Befehle.

Fehler erscheinen als Klartext mit Handlungsanweisung (`-> …`). Exit-Codes unverändert:
0 ok, 1 Fehler/Konfiguration/nicht bestätigt/abgebrochen, 5 nicht erreichbar oder Druck unvollständig,
6 Vorlage/Variable, 7 belegt (auch COM-Port von anderem Programm gehalten). 2 bis 4 sind reserviert
(2 nutzt argparse für Aufruffehler).

### Fehldruckschutz und `config.json`

`%APPDATA%\Tapesmith\config.json` (Schlüssel optional):

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `guard.confirm_label_mm` | 150 | Label länger -> Rückfrage |
| `guard.confirm_copies` | 5 | mehr Kopien -> Rückfrage |
| `guard.max_label_mm` | 500 | harte Obergrenze je Label |
| `guard.max_request_mm` | 2000 | harte Obergrenze Band je Auftrag |
| `guard.max_copies` | 50 | harte Obergrenze Kopien |
| `connect_timeout_s` | 5 | wirkt in der CLI: harter Timeout beim Öffnen des Ports (ausgeschalteter Drucker -> nach ca. 5 s Exit 5) |
| `idle_timeout_s` | 300 | wirkt im Druckdienst (Oberfläche, Tray): Verbindung wird nach so vielen Sekunden Leerlauf getrennt (0 = sofort nach dem Druck); die CLI trennt nach jedem Befehl |
| `gui.ctrl_enter_only` | false | Schnelldruck der Oberfläche: nur Strg+Enter druckt, Enter = neue Zeile |

Ohne Terminal (Skript, Pipe) wird bei einer Rückfrage nicht gedruckt (Exit 1); dann `--yes` angeben.
Ketten werden je Job auf höchstens 200 mm Inhalt aufgeteilt.

## Schnelldruck und Statusleiste

Die Oberfläche ist eine Web-Oberfläche, sie läuft nur im Standardbrowser (`p12 app`, siehe
„Oberfläche (Web)“ unten); das frühere Qt-Hauptfenster gibt es nicht mehr. Die
Regeln für den Schnelldruck gelten unverändert. `p12 gui` funktioniert weiter und leitet mit einem Hinweis auf
`p12 app` um. Selbsttest ohne Drucker (druckt nie, schreibt keine Nutzerdaten, braucht kein Qt):
`p12 gui --selftest` (`--selftest-out datei.txt` schreibt das Ergebnis in eine Datei; letzte Zeile
„Selbsttest ok“, Exit 0).

Die Statusleiste zeigt Verbindung („P12 · verbunden“ usw., nie nur als Farbe), Fortschritt,
„Abbrechen“ und Meldungen im Klartext: Warnungen (z. B. Deckel offen) als Hinweis, ohne den
Druck zu blockieren; Fehler (z. B. „Drucker nicht erreichbar“) mit Handlungsanweisung.
Einziger Dialog beim Drucken ist die Rückfrage des Fehldruckschutzes (Überlänge, viele Kopien).

Schnelldruck-Tasten:
- **Enter** druckt genau 1 Label, aber nur, wenn die Vorschau zum aktuellen Text passt.
- **Strg+Enter** und „Drucken“ drucken mit der eingestellten Kopienzahl bzw. als Kette.
- **Umschalt+Enter** fügt eine neue Zeile ein.
- **Einfügen** druckt nie; mehrzeilig eingefügter Text wird erst geprüft (zweimal Enter).
- Einstellung „Nur mit Strg+Enter drucken“ (`gui.ctrl_enter_only`): Enter = neue Zeile.

Vorschau „Design/Druckbild“: „Druckbild“ zeigt exakt die gesendeten Punkte; Vor- und Nachlauf sowie
der Bandverbrauch sind als „ca.“/geschätzt gekennzeichnet. Vorschau und Druckbild rendert immer der
Python-Kern (WYSIWYG), die Oberfläche zeigt nur die fertigen Bilder.

Abbrechen: „Abbrechen“ in der Fortschrittsleiste oder Esc; der Rest des Labels wird weiß aufgefüllt
und vorgeschoben. Verbindung: der Druckdienst hält die Verbindung und trennt nach `idle_timeout_s`
Sekunden Leerlauf. Verlauf: Suche, „Erneut drucken“, Export (PNG/PDF/PBM).

## Editor & Inhalte

**Editor** (Seite 2, Strg+2): Objekte frei platzieren: Text, QR, Barcode (Code128), DataMatrix, Icon, Linie,
Pfeil, Rahmen, Warnbalken, Bild. Hinzufügen über die Palette oder, wenn die Leinwand den Fokus hat,
per Buchstabe: T Text, Q QR, B Barcode, D DataMatrix, I Icon, L Linie, A Pfeil, R Rahmen,
W Warnbalken, M Bild. Weitere Tasten: Pfeiltasten verschieben (Raster), Entf löscht, Strg+Z/Strg+Y
(bzw. Strg+Umschalt+Z) Rückgängig/Wiederholen, Strg+D duplizieren, Strg+R/Strg+Umschalt+R drehen,
Strg+M spiegeln, Strg+A alles auswählen, Esc Auswahl aufheben, Strg+P drucken, Strg+S speichern. Ebenen, Eigenschaften, Verlauf (Sprung zu einem
Schritt), Ausrichten/Verteilen, Raster und Einrasten (`gui.editor_grid_dots`, `gui.editor_snap`).
Fehler (z. B. Code passt nicht) werden am Objekt markiert; gedruckt wird nur ein fehlerfreies Label.
Dokumente lassen sich speichern/öffnen und als Vorlage ablegen.

**Codes:** Code128 (Modul 2 oder 3 Punkte, optional mit Klarschrift) und DataMatrix (quadratisch,
Modulgröße automatisch). Jeder Code wird vor dem Druck per Selbsttest zurückgelesen (zxing-cpp).

**Icons:** Tabler Icons (MIT-Lizenz, `icons/LICENSE-tabler.txt`) und eine Auswahl Simple Icons
(CC0, `icons/simple/LICENSE-simple-icons.txt`). Die Simple-Icons-Logos sind Marken ihrer Inhaber
(`icons/simple/MARKEN.txt`); CC0 gilt nur für die Grafikdateien, nicht für die Markenrechte. Eigene
Icons (PNG) landen unter `%APPDATA%\Tapesmith\icons`.

**Bilder:** Import mit Schwelle, Dithering (Floyd-Steinberg/Bayer), Invertieren; das Bild wird
eingebettet (Dokument bleibt eine Datei).

**Vorlagen v2 + Galerie:** Vorlagen können ein komplettes Objekt-Dokument oder einen Generator
(Kabelfahne, Kabelwickel, Raster) enthalten, dazu Kategorie, Beispielwerte und Zielprodukt. Die
**Galerie** (Seite 3, Strg+3) zeigt alle Vorlagen mit Vorschau, Suche, Favoriten („Anpinnen“, `gui.favorites`) sowie
„Im Editor bearbeiten“ und „Serie/Import…“; „Verwenden“ springt in die Vorlagenseite. Eigener
Vorlagenordner: `templates_dir`. Prüfung aller Vorlagen mit Beispiel- und Maximaldaten:
`p12 template lint`. Raster-Vorlagen (Patchpanel, Switch, Sicherungskasten, Sortiment): Knopf
**„Belegung exportieren…“** auf der Vorlagenseite schreibt die Belegung als Tabelle.
**Schriftgröße:** Raster-Vorlagen setzen alle Felder standardmäßig in einer einheitlichen Größe
(der größten, bei der jedes Feld passt) mit mindestens 1 mm Innenabstand zu den Trennstrichen.
Jede Vorlage mit automatisch eingepasstem Text hat das Feld `schriftgroesse`: `auto`, `auto-feld`
(nur Raster, jedes Feld einzeln) oder eine Texthöhe in mm (`--set schriftgroesse=3,5`). Passt eine
feste Größe nicht, wird verkleinert und gewarnt, nie abgeschnitten. Im Vorlagenformat legt der
optionale Schlüssel `text_height` den Standard fest (`false` blendet das Feld aus).

**Vorlagen übersetzen:** Eine Vorlage kann einen Block `translations` tragen, je Sprache ein Objekt
(heute `en`). Er ersetzt beim Laden in dieser Sprache Anzeigename (`title`), Beschreibung,
Kategorie, Stichworte (`tags`), Beispielwerte (`sample`), Zeilen der Kurzform (`lines`, gleiche
Anzahl wie `layout.lines`), Texte von Dokumentobjekten (`texts`, je Objekt-ID) und je Feld
(`fields.<id>`) Bezeichnung (`label`), Standardwert (`default`), Auswahl (`choices`, gleiche Anzahl),
lookup-Tabelle (`map`) und Auswahl-Beschriftungen (`choice_labels`). Die ID (`name`) bleibt in allen
Sprachen gleich (Verlauf, CLI, Favoriten). `choice_labels` gibt es auch ohne Übersetzung: es zeigt zu
Auswahlwerten, die Kennungen sind (z. B. `haengt`), einen lesbaren Text an; gedruckt bzw. gespeichert
wird der Wert. Eine lookup-Tabelle findet auch Werte der anderen Sprachen (Nachdruck aus dem
Verlauf). Beispiel:

```json
"translations": {
  "en": {
    "title": "freezer",
    "description": "Frozen food with shelf life ...",
    "category": "Household",
    "fields": {"kategorie": {"label": "Category", "choices": ["Meat", "Fish"]},
               "tage": {"map": {"Meat": "180", "Fish": "120"}}},
    "texts": {"text1": "{inhalt}\nFrozen {eingefroren}"},
    "sample": {"inhalt": "Goulash", "kategorie": "Meat"}
  }
}
```

Ältere App-Versionen kennen den Schlüssel nicht und lehnen solche Vorlagen ab. `p12 template lint`
prüft jede Sprache des Blocks mit Beispiel- und Maximaldaten und meldet Lücken (Beschreibung,
Kategorie, Stichworte, Feldbezeichnungen, Auswahl-Beschriftungen) als Warnung. Alle mitgelieferten
Vorlagen sind vollständig übersetzt; ebenso die Bandprofile (`tapes.json`) und Zielobjekte
(`targets.json`) über `translations.<sprache>.name` (und `note`).

**Serien/Import:** `p12 batch VORLAGE --data liste.csv|.xlsx` (Spalten werden Feldern zugeordnet,
`--map`, `--save-mapping`), `--lines -`, `--clipboard`, `--series port=1..24`,
`--contact-sheet übersicht.png`, `--dry-run`. In der Oberfläche: „Serie/Import…“ auf der Vorlagenseite oder in der Galerie.

**Band:** `p12 tape list`, `p12 tape set weiss-schwarz`, `p12 tape roll` (Restmeter-Schätzung),
`p12 tape new-roll`, `p12 tape empty` (Rolle war leer → Längenfaktor lernen); in der Oberfläche unter
Einstellungen. Rollen und Faktor gelten **je Band**; jeder Druck (Oberfläche, Tray und CLI) zieht Inhalt plus
Vor-/Nachlauf von der Rolle des gerade gewählten Bandes ab und warnt, wenn sie nicht reicht. Die Vorschau aller Seiten zeigt Band- und Druckfarbe. Auf dunklem Band
(Weiß/Gold auf Schwarz) werden QR, Code128 und DataMatrix **invertiert** gedruckt (Module bleiben
ungedruckt, die Ruhezone wird gedruckt), damit Scanner sie lesen. Das gilt auch im Schnelldruck
(optionales Feld „QR“) und im QR-Assistenten.

**Schneidpause:** Zwischen den Druckjobs eines Auftrags (Kopien/Serien ohne Kette: nach jedem
Label) hält der Druck an
(`cut_pause_s`: nicht gesetzt = keine Pause, `0` = bis „Weiter“, `> 0` = automatisch nach so vielen
Sekunden; CLI `--cut-pause SEK`). Die Oberfläche zeigt oben eine Leiste „Label 1/3 abschneiden, dann
‚Weiter‘“; **Leertaste** oder „Weiter“ setzt fort (die Leertaste wirkt nur während der Pause).

**Kalibrierung:** Vorschub unter Einstellungen („Lineal drucken (100 mm)“, gemessene Länge
eintragen, „Übernehmen“) bzw. `p12 calibrate ruler`. Bildschirm („Bildschirm kalibrieren…“,
`gui.screen_px_per_mm`) sorgt dafür, dass der Editor in 100 % echte Millimeter zeigt.

Neue `config.json`-Schlüssel:

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `tape.current` | `schwarz-weiss` | eingelegtes Band (Vorschaufarbe, Invertierung von Codes, Eignungsprüfung) |
| `templates_dir` | nicht gesetzt | eigener Vorlagenordner statt `%APPDATA%\Tapesmith\templates` |
| `cut_pause_s` | nicht gesetzt | Schneidpause: keine / `0` bis „Weiter“ / Sekunden |
| `gui.screen_px_per_mm` | nicht gesetzt | Bildschirm-Kalibrierung für den Editor |
| `gui.favorites` | `[]` | Favoriten der Galerie |
| `gui.editor_grid_dots` | 8 | Rasterweite im Editor (Punkte) |
| `gui.editor_snap` | true | Einrasten am Raster/an Objekten |

Der Selbsttest (`p12 gui --selftest`) prüft zusätzlich Dokument, Codes, Icons, invertierte Codes auf dunklem Band und Vorlagen-Lint.

## Dienst & Windows

Alle Druckwege (Oberfläche, CLI, Tray, Hotkey, Kontextmenü/URI) laufen wenn möglich über
einen gemeinsamen Hintergrunddienst, dazu kommen Warteschlange, Tray-App mit globalem Hotkey,
Zwischenablage-Druck, Windows-Integration, Kommandopalette, Datenträger- und SSH-Diskscanner,
Statusanzeige, experimentelle Transporte (BLE/USB/Blockmodus), Verlauf-Ausbau (Archiv, Statistik,
Inventar), Sicherung/Nummernkreise und Entwicklerwerkzeuge (Rohbefehle, Dichte-Teststreifen).

### Druckdienst p12d

`p12d` startet bei Bedarf (aus der Oberfläche, der CLI oder der Tray-App) und läuft im
**Benutzerkontext** weiter (kein Windows-Dienst, kein Adminrecht nötig). Es gibt höchstens eine
Instanz je Benutzer **und** App-Verzeichnis (also je `TAPESMITH_HOME`).

```
p12 daemon start                # startet den Dienst (falls er nicht schon läuft)
p12 daemon status                # PID, Version, Verbindung, Warteschlange
p12 daemon stop                  # beendet den Dienst (--force auch während eines Druckauftrags)
p12 daemon restart
```

Der Dienst enthält auch die HTTP-API der Web-Oberfläche (siehe „Oberfläche (Web)“).
Log: `%APPDATA%\Tapesmith\logs\p12d.log`. Ist kein Dienst erreichbar oder startbar, druckt die
CLI bzw. die Tray-App **direkt** (dieselbe Pipeline); ausdrücklich erzwingen mit `--no-daemon`
bzw. der Umgebungsvariable `TAPESMITH_NO_DAEMON=1`. Diagnose/Einrichtung (`doctor`, `probe`,
`verify`, `setup`, `raw`, `density`) reservieren dafür kurz den Drucker beim laufenden Dienst
(Lease) statt ihn zu blockieren. Die Verbindung läuft über eine Named Pipe, die **nur der eigene
Windows-Benutzer** öffnen kann (kein Netzdienst, kein Zugriff von außen).

Der Alt-Befehl `phomemo_print_p12` (Kompatibilität zu phomemo-p12-tools) druckt weiterhin direkt
am COM-Port. Läuft der Dienst gerade, meldet er ggf. „belegt" (Exit 7); dann hilft
`p12 daemon stop` oder derselbe Druck über `p12 print`/`p12 text`.

### Warteschlange

`p12 queue list|cancel|dup|move|retry|pause|resume` sowie die Seite **Warteschlange** zeigen und
steuern die Aufträge des Dienstes. Kann der Drucker beim Senden nicht erreicht werden, reiht der
Dienst den Auftrag ein („wartet") und versucht ihn mit Backoff (30 s → 5 min) automatisch erneut,
schneller, wenn eine passive BLE-Advertisement-Probe (`queue.probe`) den eingeschalteten Drucker
schon vorher erkennt. Abschaltbar über `queue.auto_retry=false` bzw. `queue.probe=off`. Sensible
Aufträge (z. B. WLAN-Passwort) werden **nie** auf Platte geschrieben, nur im Speicher; sie gehen
beim Beenden des Dienstes verloren (so angezeigt). Standardmäßig reihen Oberfläche/Tray/Hotkey offline
automatisch ein; die CLI nur mit `--queue` (umstellbar über `queue.cli_default`). Ist der Deckel
**verifiziert** offen, pausiert die automatische Warteschlange, bis er wieder zu ist.

### Tray-App und Hotkeys

`p12 tray` (bzw. in der installierten App `pythonw -m tapesmith.gui.tray`) startet die Tray-App im Infobereich.
**Die Tray-App öffnet nie ein eigenes Fenster**, keinen Dialog, kein Popup und keine MessageBox.
Nativ sind nur das Symbol und sein Kontextmenü; alles, was Oberfläche braucht, öffnet einen neuen
Tab im Standardbrowser (jedes Mal mit frischer Sitzung). Hinweise und Fehler kommen als
Windows-Benachrichtigung des Tray-Symbols.

| Auslöser | Wirkung |
|---|---|
| Linksklick aufs Symbol, „Web-Oberfläche öffnen“ | Web-Oberfläche (Startseite) im Browser |
| **Strg+Alt+L** (`hotkey.quick`), „Schnelldruck“ | `/schnelldruck` im Browser |
| **Strg+Alt+Umschalt+L** (`hotkey.clipboard`), „Zwischenablage in Schnelldruck“ | `/schnelldruck?text=…` mit dem Text der Zwischenablage vorbelegt (höchstens 500 Zeichen, URL-kodiert); gedruckt wird erst im Browser |
| „Verlauf“ | `/verlauf` |
| „Druckerstatus“ | Einstellungen, Abschnitt Verbindung |
| „Log und Diagnose“ | Einstellungen, Abschnitt Hilfe und Diagnose |
| „Einstellungen“ | Einstellungen, Abschnitt Tray und Tastenkürzel |
| Update-Hinweis oben im Menü | Einstellungen, Abschnitt Updates |
| Favorit mit fehlenden Eingaben | `/aktion?uri=tapesmith://print?…` |

Direkt ohne Oberfläche wirken: Favoriten drucken, letzte Labels nachdrucken, Testlabel,
Warteschlange pausieren/fortsetzen, „Mit Windows starten“ und Beenden.

**Alle Einstellungen der Tray-App stehen in der Web-Oberfläche** unter Einstellungen, Abschnitt
„Tray und Tastenkürzel“ (Kürzel an/aus, beide Kürzel, Benachrichtigungen, Favoriten); den Autostart
schaltet „Windows-Integration“ (oder das Häkchen im Tray-Menü). Die Tray-App prüft die
Konfigurationsdatei alle 2 s und übernimmt Änderungen ohne Neustart. Beim Speichern prüft die
Web-Oberfläche die Kürzel wie früher der Tray-Dialog: gültige Taste, zwei verschiedene Kürzel und
**keine AltGr-Kollision**. Auf der deutschen Tastatur ist Strg+Alt praktisch AltGr, darum wird z. B.
`Strg+Alt+Q` (erzeugt mit AltGr das Zeichen „@“) abgelehnt.

Die Kürzel registriert die Tray-App ohne Fenster (`RegisterHotKey` mit hwnd NULL, die Meldung kommt
als Thread-Nachricht in die Qt-Nachrichtenschleife).

Favoriten im Tray-Menü (`tray.favorites`), je Eintrag Titel, Vorlage und feste Werte:

```json
"tray": {"favorites": [{"title": "Geöffnet am", "template": "geoeffnet-am", "values": {}}]}
```

**Testmodus ohne Browser:** Ist `TAPESMITH_BROWSER_LOG=<Datei>` gesetzt, startet die Tray-App (bzw.
`p12 app`) weder Druckdienst noch Browser, sondern hängt nur die Route (ohne Token) an diese
Datei an. So lässt sich ein gebautes Tray prüfen, ohne dass ein Tab aufgeht.

### Zwischenablage

Strg+Alt+Umschalt+L (oder „Zwischenablage in Schnelldruck“ im Tray-Menü) öffnet den Schnelldruck
im Browser mit dem Text der Zwischenablage vorbelegt; es wird nie direkt gedruckt. Die Erkennung
der Zwischenablage-Arten (`tapesmith.clipboard`) nutzen weiterhin Selbsttest und Web-Oberfläche:

| Art in der Zwischenablage | Vorschlag |
|---|---|
| Seriennummer / `by-id`-Name | Vorlage `datentraeger` |
| IPv4-Adresse | Vorlage `ip-label` |
| MAC-Adresse | Monospace, normalisiert (`AA:BB:CC:DD:EE:FF`) |
| URL | QR-Code + Hostname (lange URL: Hinweis auf Kurz-Link) |
| eine Zeile | Text |
| zwei Zeilen | zwei Zeilen, Schriftgröße 44 |
| ab drei Zeilen | Frage „ein Label pro Zeile?“ mit Bandbilanz |
| Bild | gerastert |

### Kontextmenü und URI

```
p12 integrate install|uninstall|status [--context] [--uri] [--autostart] [--dry-run]
```

Schreibt nur unter `HKCU` (kein Adminrecht) und ist idempotent. **Diesen Befehl führen Sie
selbst aus**, kein Skript und kein Automatismus. `p12 integrate install --context --uri` legt Rechtsklick-Einträge
für die Dateiarten aus `integration.FILE_ACTIONS` an (`.csv`/`.xlsx` als Serie, Bilder, `.txt`
zeilenweise, `*.tapesmith.json` als Vorlage, Ordner „Name als Label"/„QR mit UNC-Pfad") sowie das
URI-Schema `tapesmith://…`. Beispiel-Link (z. B. aus Obsidian):

```
tapesmith://print?template=datentraeger&host=pmx10&sn=274913
```

Ein solcher Link öffnet die Web-Oberfläche im Standardbrowser **vorausgefüllt**, gedruckt wird erst
nach Bestätigung durch den User, nie automatisch. Unter Windows 11 stehen die neuen
Kontextmenü-Einträge oft unter „Weitere Optionen anzeigen" (Umschalt+F10). Nach dem Umstieg von der Qt-Oberfläche
den Befehl einmal erneut ausführen, damit die Einträge die Web-Oberfläche statt der alten
Qt-Oberfläche öffnen.

### Kommandopalette und Tastenkürzel

**Strg+K** öffnet die Kommandopalette (Fuzzy-Suche über Vorlagen, letzte Aktionen, Bandprofile,
z. B. „ssd" für die Datenträger-Vorlage, „wieder" für „letztes erneut drucken", „band" für ein
Bandprofil). Weitere Tastenkürzel: **Strg+P** drucken, **Strg+D** duplizieren (im Editor),
**Strg+Umschalt+V** Zwischenablage als Seriendaten öffnen, **Strg+1…8** zwischen den Seiten der Kernapp wechseln,
**Strg+,** Einstellungen.

### Datenträger-Assistent

Seite **Datenträger** (Modul Datenträger, Reiter „Laufwerke“) bzw. `p12 drives [label E:]` auf der Kommandozeile: erkennt
angeschlossene Wechseldatenträger (USB-Stick, SD-Karte) und schlägt ein Kurzetikett vor, z. B.
„Bezeichnung · 64 GB · exFAT".

### Statusanzeige

Status-Chip, Fenstertitel und Tray-Tooltip zeigen **nur geprüfte** Werte ohne Zusatz; andere mit dem
Zusatz „(unbestätigt)", fehlende als „nicht verfügbar". Das **Band** wird im Chip nie als „ok"
angezeigt (eine leere Rolle erkennt der P12 nicht zuverlässig). Das Detailpanel zeigt zusätzlich
Firmware, Seriennummer, MAC, Transport und die **letzte Antwort** als Hex. Abgefragt wird nur bei
sichtbarer Oberfläche (Intervall `status.poll_s`) oder auf Klick auf den Chip.

### Experimentell: Blockmodus, BLE, USB

`block_rows` in `calibration.json` schaltet die Blockübertragung ein (0 = aus, Standard;
sonst ≤ 255 Zeilen je Block). BLE-Transport: `p12 ble scan` sucht Geräte, `--transport
ble[:Adresse]` verbindet ohne Windows-Pairing (nie gleichzeitig mit der klassischen
SPP-Verbindung). USB: `p12 usb` erkennt den P12 über VID 0x4C4A/PID 0x4155; USB-Druck ist nur
möglich, wenn `"experimental": ["usb"]` in `calibration.json` gesetzt ist. Alle drei Punkte gelten
als **experimental** und sind an der Hardware noch nicht vollständig geprüft (siehe
`docs/hardware/README.md`).

### SSH-Disk-Scanner

Beispiel-Konfiguration (nur als Beispiel, keine Voreinstellung):

```json
"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root", "key": "%USERPROFILE%\\.ssh\\id_ed25519_homelab"}]}
```

`p12 disks hosts|scan|print` liest die Platten eines konfigurierten Homelab-Hosts per SSH aus und
druckt sie als Serie über die Vorlage `datentraeger`; in der Oberfläche macht das die Seite
**Datenträger** (Reiter „SSH“). Voraussetzung ist das Windows-Feature „OpenSSH-Client"; beim ersten Verbinden muss
der Host-Schlüssel einmal bestätigt werden (`ssh.strict_host_key`). Der SSH-Schlüssel steht in der
Konfiguration **nur als Pfad**, nie als Inhalt.

### Verlauf, Archiv, Statistik, Inventar

- **Archiv:** `archive.dir` legt Druckjobs als JSON+PNG in einem (Git-)Ordner ab; sensible
  Felder werden maskiert und ohne Bild archiviert. `archive.git_commit=true` committet danach
  automatisch, es wird **nie** gepusht. `p12 archive add last|<ID>` archiviert nachträglich,
  `p12 archive scan <Pfad>` prüft eine Datei/einen Ordner auf Secrets.
- **Statistik:** `p12 stats --by monat|vorlage|quelle|art|rolle` zeigt den Bandverbrauch
  gruppiert.
- **Inventar:** `p12 inv box add|list|show|rm`, `p12 inv add|rm|mv|find|lend|return|loans`,
  `p12 inv label box|content|loan` sowie die Seite „Inventar" verwalten Boxen mit Inhalt und
  Verleihliste inklusive QR-Labels.

### Sicherung, Konfiguration als Code, Nummernkreise

`p12 backup create|restore|list` sichert Konfiguration, Kalibrierung, Zähler, Rollen, Verlauf,
Inventar und Warteschlange als Zip; `backup.auto_daily=true` lässt den Dienst täglich automatisch
sichern. `p12 config export|import <Ordner>` legt die Konfiguration als lesbaren, Git-tauglichen
Ordner ab. Zentrale Nummernkreise: `numbering.dir` zeigt auf einen gemeinsamen Ordner
(z. B. ein Share oder Git-Repo): **alle** Druckwege mit Vorlagen-Zählern (CLI, Oberfläche, Tray, Serien,
SSH-Serie, Inventar) zählen dann dort, damit ein zweiter Rechner keine doppelten Nummern vergibt.
Verwaltung über `p12 nummern list|define|reserve|void|export|import`.

### Entwicklerwerkzeuge

`p12 raw` sendet einzelne Rohbefehle (Hex) und dekodiert die Antwort. Eine **Schutzliste** prüft
jeden Befehl vorher: bekannte Abfragen (`1F 11 xx`) sind erlaubt, **ESC 7 gesperrt** (Heizparameter
(kann den Druckkopf überhitzen), alles Unbekannte nur mit `--unsafe` **und** ausdrücklicher
Eingabe „JA". `p12 raw --listen 10` lauscht danach auf Spontanmeldungen (z. B. beim Öffnen/
Schließen des Deckels). `p12 density` druckt experimentelle Dichte-Teststreifen; da für den P12
kein Dichtebefehl belegt ist, warnt der Befehl vorher, dass der Drucker nach einem Druck aus
**Print-Master** bis zum nächsten Neustart dunkler druckt („Print-Master-Effekt"). Der gewählte
Wert wird nur im Bandprofil gespeichert, nie automatisch gesendet. Anleitung für einen
Bluetooth-Mitschnitt (der sicherste Weg zu einem echten Dichtebefehl): `docs/hardware/hci-snoop.md`.

### Neue Einstellungen

Neue Schlüssel in `%APPDATA%\Tapesmith\config.json` (Abfrage/Änderung auch über
`p12 config get|set <schlüssel>`):

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `daemon.enabled` | `true` | Oberfläche/CLI/Tray nutzen den Druckdienst |
| `daemon.spawn` | `true` | Dienst bei Bedarf starten |
| `daemon.connect_timeout_s` | `2.0` | Warten auf die Pipe |
| `daemon.start_timeout_s` | `10.0` | Warten nach dem Start |
| `daemon.idle_exit_s` | `1800` | Dienst beendet sich nach Untätigkeit (kein Pipe-Client, kein offener Browser-Tab mit der Oberfläche, keine wartenden Aufträge); 0 = nie |
| `queue.enabled` | `true` | Offline-Aufträge einreihen (Oberfläche/Tray/Hotkey) |
| `queue.auto_retry` | `true` | automatischer Nachdruck |
| `queue.backoff_start_s` / `queue.backoff_max_s` | `30` / `300` | Backoff |
| `queue.probe` | `"auto"` | `auto` · `ble` · `connect` · `off` |
| `queue.cli_default` | `false` | CLI reiht ohne `--queue` ein |
| `status.poll_s` | `120` | Statusabfrage bei sichtbarer Oberfläche (Browser-Tab im Vordergrund); 0 = nur auf Klick |
| `hotkey.enabled` | `true` | globale Hotkeys der Tray-App |
| `hotkey.quick` | `"Ctrl+Alt+L"` | öffnet `/schnelldruck` im Browser |
| `hotkey.clipboard` | `"Ctrl+Alt+Shift+L"` | öffnet `/schnelldruck` mit dem Text der Zwischenablage |
| `tray.favorites` | `[]` | Favoriten im Tray-Menü |
| `tray.toast_s` | `3` | ohne Wirkung (früher Vorschau-Toast), wird nur noch geprüft |
| `tray.notify` | `true` | Windows-Benachrichtigungen |
| `ble.address` | `null` | feste BLE-Adresse |
| `ble.names` | `["P12","P12 PRO","P12PRO"]` | Gerätenamen für Suche/Probe |
| `ble.scan_timeout_s` | `8.0` | BLE-Suche |
| `ssh.hosts` | `[]` | SSH-Hosts (Schlüssel nur als Pfad) |
| `ssh.timeout_s` | `20` | SSH-Zeitlimit |
| `ssh.strict_host_key` | `true` | nur bekannte Host-Schlüssel |
| `archive.dir` | `null` | Archivordner (aus = null) |
| `archive.git_commit` | `false` | nach Secret-Scan committen (nie pushen) |
| `backup.dir` | `null` | Sicherungsordner (Standard `<App-Verzeichnis>\backups`) |
| `backup.keep` | `10` | so viele Sicherungen behalten |
| `backup.auto_daily` | `false` | Dienst sichert täglich |
| `numbering.dir` | `null` | zentraler Ordner für Nummernkreise/Zähler |

## Module

Tapesmith besteht aus der **Kernapp** und aus **Modulen**. Die Kernapp ist immer da: Schnelldruck,
Editor, Galerie, Vorlagen, QR-Code, Verlauf, Warteschlange, Statistik, Zugriff und Einstellungen.
Module sind eingebaute Zusatzbereiche für besondere Aufgaben; sie sind anfangs **ausgeschaltet**.

| Modul (`id`) | Wofür | Seite | CLI | eigene Vorlagen | Einstellungen |
|---|---|---|---|---|---|
| Inventar (`inventar`) | Boxen, Inhalte und Verleih | Inventar | `inv` | `aufbewahrungsbox` | keine |
| Datenträger (`datentraeger`) | Laufwerke dieses PCs, SSH-Disk-Scanner, Plattentausch (ZFS) | Datenträger (Reiter Laufwerke, SSH-Scanner, Plattentausch) | `drives`, `disks`, `platte` | `datentraeger`, `datentraeger-qr`, `platte-defekt` | SSH-Hosts (`ssh.*`) |
| Proxmox (`proxmox`) | VMs und Container aus Proxmox VE | Homelab › Proxmox | `proxmox` | `vm-lxc`, `vm-lxc-qr` | `proxmox.*` |
| Paperless (`paperless`) | ASN-Nummern und Garantie-Etiketten | Homelab › Paperless | `asn`, `garantie` | `asn`, `garantie`, `garantie-qr` | `paperless.*` |
| Home Assistant (`homeassistant`) | Batterien und Wartung | Homelab › Home Assistant | `batterie` | `batterie` | `homeassistant.*` |
| Obsidian-Vault (`vault`) | Etiketten aus Notizen, Vermerk nach dem Druck | Homelab › Obsidian-Vault | `vault`, `asset-notiz` | keine | `obsidian.*` |
| Assets (`assets`) | Anlagen-Nummern mit QR-Code und Kurz-Link | Homelab › Assets | `asset`, `kurz` | `asset-tag`, `asset-kurz` | `assets.*`, `shortlink.*` |
| Kabel (`kabel`) | Kabel-IDs nach TIA-606, NetBox-Import | Homelab › Kabel | `kabel` | keine | `kabel.*` |
| Kleinanzeigen (`kleinanzeigen`) | Verkaufsartikel mit Preis und QR-Code | Homelab › Kleinanzeigen | `ka` | `ka-artikel` | `kleinanzeigen.*` |
| Seriennummer-Scan (`snscan`) | Seriennummer aus einem Foto des Aufklebers | Homelab › Seriennummer-Scan | `sn-scan` | keine | keine |

**Ein- und ausschalten:** Einstellungen › Module (je Modul ein Schalter mit Erklärsatz und Beispiel) oder
`tapesmith module list`, `tapesmith module enable <id> [<id> …]`, `tapesmith module disable <id>`,
`tapesmith module enable --all`. Die Änderung wirkt sofort, ohne Neustart: der Dienst liest
`config.json` bei jeder Anfrage, die Oberfläche lädt Seitenleiste, Befehlspalette und Galerie neu.
Gespeichert wird die Liste in `config.json`:

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `modules.enabled` | `[]` | eingeschaltete Module (Kennungen wie oben); unbekannte Kennungen werden ignoriert |

**Ausgeschaltete Module erscheinen nirgends:** nicht in der Seitenleiste, der Befehlspalette, der
Galerie und Vorlagenliste (ihre Vorlagen sind ausgeblendet, `tapesmith template list` ebenso), im
Tray-Menü (Favoriten mit Modulvorlagen), in den Einstellungen und in der Homelab-Übersicht. Die
Homelab-Übersicht zeigt nur eingeschaltete Integrationsmodule; ist keines an, verschwindet der Eintrag
Homelab aus der Seitenleiste. Ruft man eine Seite eines ausgeschalteten Moduls direkt auf, erscheint nur
ein Hinweis mit dem Weg zu den Modulen. Die API-Routen eines ausgeschalteten Moduls antworten mit
**HTTP 409** und dem Fehlercode `module.disabled` (Modul in `details.module`), CLI-Befehle mit Exit-Code 1
und dem Klartext „Modul X ist ausgeschaltet, einschalten unter Einstellungen > Module oder
`tapesmith module enable X`“. Tastenkürzel Strg+1 bis Strg+8 gehören fest zu den Seiten der Kernapp.

**Einstellungen der Module:** Jedes eingeschaltete Modul mit Einstellungen hat in Einstellungen eine
eigene Karte direkt unter „Module“ (Datenträger: SSH-Hosts aus `config.json`; die Homelab-Module:
ihre Abschnitte aus `homelab.json`). Token-Felder nehmen nur Referenzen auf; „Prüfen“ zeigt ohne
Netzzugriff, ob der Dienst eingetragen ist und das Token gefunden wird. Die frühere Seite
Homelab › Einstellungen leitet zu Einstellungen › Module weiter.

**Umstieg und ältere Konfiguration:** Wer von „P12 Label“ umsteigt, behält alles: die Datenübernahme
setzt `modules.enabled` auf die Module, zu denen Daten oder Einstellungen vorhanden sind (Inventar-
Datenbank mit Einträgen, `ssh.hosts` oder SSH-Scans, Abschnitte in `homelab.json`, Asset- und
Kleinanzeigen-Datenbank, Kabelregister, gedruckte Modulvorlagen im Verlauf); ist eine Datei nicht
lesbar, im Zweifel alle. Dasselbe gilt für eine `config.json` ohne `modules` (etwa aus Version 0.3.0):
dann gelten die erkannten Module, und der Druckdienst schreibt die Liste beim nächsten Start fest.

Die Beschreibung der Module steht einmal im Code (`src/tapesmith/modules.py`, Texte in
`src/tapesmith/locales/<sprache>/modules.json`); die Oberfläche liest dieselbe Beschreibung aus
`web/src/modules/registry.json` (neu erzeugen mit `python -m tapesmith.modules --write-web`) bzw. zur
Laufzeit aus `GET /api/v1/modules` (`PUT /api/v1/modules/<id>` mit `{"enabled": true}` schaltet um).

## Einstellungen: sichtbar, Erweitert, nur `config.json`

Die Seite Einstellungen zeigt oben, was man im Alltag braucht: Drucker (Status, Suchen und testen,
Testlabel), Band und Rolle, Kalibrierung, Bildschirm, Drucken (Nur Strg+Enter druckt, Schneidpause,
Rückfrage ab Labellänge und Kopienzahl), Warteschlange (aktiv, automatischer Nachdruck), Editor
(Einrasten, Rasterweite in mm), Tray und Tastenkürzel, Oberfläche (Sprache, Farbschema), Module und ihre
Einstellungskarten, Updates (Nach Updates suchen, automatisch installieren, Kanal), Sicherung (tägliche
Sicherung, Anzahl, Jetzt sichern), Windows-Integration (Autostart), Zugriff sowie Hilfe und Diagnose (mit
Version, Laufzeit, PID und Pfaden des Druckdienstes). Jedes Zahlenfeld trägt seine Einheit im Feld.

Am Seitenende liegt der eingeklappte Abschnitt **Erweitert** (der Zustand gilt je Browser; ein Link
`/einstellungen?abschnitt=<karte>` auf eine Karte darin öffnet ihn): MAC-Adresse und Transport,
Obergrenzen für Labellänge, Auftragslänge und Kopien, Sicherungsordner, Vorlagenordner, Archivordner
und Git-Versionierung, Web-Port, Bluetooth LE (experimentell), Kontextmenü und `tapesmith://`,
Konfiguration als Code und die Plausibilitätsprüfung.

**Nur in `config.json`** (keine Zeile in der Oberfläche, setzbar mit `p12 config set`):
`connect_timeout_s` (Verbindungs-Zeitlimit), `idle_timeout_s` (Trennen nach Ruhe), `queue.probe`,
`queue.backoff_start_s`, `queue.backoff_max_s`, `queue.cli_default`, `status.poll_s`,
`gui.screen_px_per_mm` (setzt „Bildschirm kalibrieren“), `gui.editor_grid_dots` (die Rasterweite in
Druckpunkten, 8 je mm; die Oberfläche zeigt sie in mm), `update.source`, `update.check_interval_h`,
`update.idle_min`, `update.keep_versions`, `numbering.dir` und `daemon.idle_exit_s`.

## Oberfläche (Web)

Die Oberfläche ist eine Web-Oberfläche (React, TypeScript, Fluent UI), die **nur im
Standardbrowser** läuft. Ein eigenes Fenster gibt es nicht: nativ sind nur das Tray-Symbol und
sein Kontextmenü (Qt bleibt nur dafür). Schnelldruck-Popup, Zwischenablage-Toast und
Tray-Einstellungsdialog sind entfernt, ihre Aufgaben übernehmen Browser-Tabs.

```
p12 app                    # Druckdienst bei Bedarf starten, Oberfläche im Standardbrowser öffnen
p12 app --route /verlauf   # direkt auf einer Seite starten
```

`tapesmith` (ohne Konsole), `python -m tapesmith.gui`, `p12 gui`, die Startmenü-Verknüpfung, das
Tray-Menü, Kontextmenü, `tapesmith://`-Links und der Neustart nach einem Update öffnen ebenso den
Browser; in der installierten App ist das `pythonw -m tapesmith.webui.browser`. Startet der Druckdienst nicht,
endet `p12 app` mit Exit 1 und der Meldung auf stderr; ohne Konsole (`pythonw`) steht sie in
`<App-Verzeichnis>\logs\app.log` (kein Meldungsfenster). `--browser` (früher: Browser statt Fenster) wird noch angenommen und hat keine Wirkung
mehr, `--compact` gibt es nicht mehr.

**Aufbau:** Der Druckdienst p12d bringt eine HTTP-API mit, die **nur** an `127.0.0.1` bindet
(Port `web.port`, Standard 8712). Jede API-Anfrage braucht ein Sitzungs-Token, das der Dienst bei
jedem Start neu erzeugt und in `%APPDATA%\Tapesmith\web\session.json` ablegt; `p12 app` hängt es als
Fragment an die Adresse (`http://127.0.0.1:8712/…#t=…`, das Fragment geht nie an den Server). Die
Oberfläche übernimmt es beim Start in den Sitzungsspeicher des Tabs und entfernt es sofort aus der
Adresszeile. Ein Browser ohne Token zeigt nur den Hinweis „Bitte über ‚p12 app‘ öffnen“. Aus dem
Netz ist die Oberfläche standardmäßig nicht erreichbar; LAN-Freigabe, dauerhafte API-Tokens und
`/docs` stehen im Abschnitt „LAN und Automatisierung“. Vorschau und Druckbild rendert immer der Python-Kern, gedruckt wird über dieselbe
Pipeline wie bei CLI und Tray (Fehldruckschutz, Verlauf, Restmeter, Schneidpause, Warteschlange).

**Seiten** (links in der Navigation; die Kernapp mit Strg+1 bis Strg+8 in dieser Reihenfolge, darunter die eingeschalteten Module):

| Seite | Inhalt |
|---|---|
| Schnelldruck (Start) | Text, Enter druckt, Kopien/Kette, letzte Texte, optional QR |
| Editor | Objekte frei platzieren, Ebenen, Eigenschaften, Raster, Rückgängig |
| Galerie | alle Vorlagen mit Vorschau, Favoriten, Suche |
| Vorlagen | Felder ausfüllen, Serie/Import (CSV, XLSX, Zwischenablage), Belegung exportieren |
| QR-Code | URL, Text, WLAN, Visitenkarte |
| Verlauf | Suche, erneut drucken, Export, im Editor öffnen |
| Warteschlange | Aufträge des Dienstes, Pause, erneut versuchen |
| Statistik | Bandverbrauch, Rollen |
| Inventar (Modul) | Boxen, Inhalte, Verleih, Labels |
| Datenträger (Modul) | Laufwerke, SSH-Disk-Scanner als Serie, Plattentausch (ZFS) |
| Homelab (Module) | Übersicht der eingeschalteten Homelab-Module |
| Einstellungen (Strg+,) | Drucker, Band und Rolle, Kalibrierung, Module, Updates, Sicherung, Integration; Selteneres unter „Erweitert“ |
| Zugriff | LAN-Freigabe, API-Tokens, Familie, MCP, Hotfolder, MQTT, Telegram, Status der Zusatzdienste |

Dazu kommt die eigenständige Handy-Seite `/familie` für Familien-Tokens, ohne Navigation.

Tastenkürzel überall: **Strg+K** Kommandopalette, **Strg+P** aktuelles Label drucken,
**Strg+Umschalt+V** Zwischenablage als Seriendaten, **Esc** laufenden Druck abbrechen, **Leertaste**
setzt eine Schneidpause fort. Im Editor zusätzlich die Kürzel aus „Editor & Inhalte“.

**Aussehen:** Hell/dunkel und Akzentfarbe folgen Windows; die Oberfläche passt sich der
Fenstergröße des Browsers an (in schmalen Fenstern klappt die Navigation ein).

Neue `config.json`-Schlüssel:

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `web.port` | `8712` | Port (nur 127.0.0.1), wirkt nach Neustart des Druckdienstes; Umgebungsvariable `TAPESMITH_WEB_PORT` überschreibt ihn. Die Web-Oberfläche läuft immer (ein alter Eintrag `web.enabled` wird ignoriert). |

**Entwicklung:** `cd web && npm ci && npm run dev` startet den Vite-Entwicklungsserver,
`npm run check` prüft Typen, ESLint und Vitest. `python tools/build_web.py` (mit `--install` vorher
`npm ci`) baut die Oberfläche nach `src/tapesmith/webui/static/`; dieser Ordner ist eingecheckt,
damit Laufzeit und Wheel kein Node brauchen.

**Nach dem Update:** einmal `p12 integrate install --context --uri` ausführen, damit Kontextmenü
und `tapesmith://`-Links die Web-Oberfläche im Browser öffnen. Ein alter Eintrag `app.quick_window`
in `config.json` wird ignoriert (der Hotkey öffnet immer `/schnelldruck` im Browser).

**Screenshots:** `docs/screenshots/index.md` zeigt jede Seite in Hell/Dunkel und Desktop/Handybreite,
zusätzlich auf Englisch (Hauptseiten, Desktop) und bei 200 % Zoom, gegen Demo-Daten
(Datei-Transport, kein echtes Gerät, keine echten Nutzerdaten). Neu aufnehmen (axe-core kommt aus
`web/node_modules`, also vorher im Ordner `web` einmal `npm ci`):

```
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python tools\screenshots.py [--langs de,en] [--sizes desktop,handy,zoom200] [--only verlauf]
```

Das Werkzeug ist gleichzeitig ein Rauchtest: Konsolenfehler, fehlgeschlagene `/api/`-Aufrufe,
axe-Befunde im echten Chromium (WCAG 2 A, AA und 2.1 AA inklusive Farbkontrast) und waagrechter
Überlauf führen zu Exit 1. Details in `tools/screenshots.py`.

## Homelab-Integrationen

Die Homelab-Werkzeuge sind Module (siehe [Module](#module)). Ist mindestens eines eingeschaltet, hat die
Seitenleiste einen Eintrag **Homelab** (`/homelab`) mit einer Übersicht: eine Kachel je eingeschaltetem
Modul mit Zustand aus `GET /api/v1/homelab/check` („eingerichtet“, „Token fehlt“, „nicht eingerichtet“
oder „kein Dienst nötig“). Der Plattentausch gehört zum Modul Datenträger und steht dort als Reiter. Keine Integration druckt selbst: Einzellabels laufen über die normale Druckstrecke,
Serien über den Serien-Dialog der Seite Vorlagen (`/vorlagen?vorlage=<name>&import=<id>`). Jeder
Druckbefehl kennt `--preview DATEI.png` (nur Vorschau, kein Druck); Serienbefehle zusätzlich `--dry-run`
und `--contact-sheet`. Alle Routen liegen unter `/api/v1/homelab` und brauchen das Sitzungs-Token.

| Funktion | Seite | CLI (Beispiele) |
|---|---|---|
| **Plattentausch:** defekte, fehlende oder OFFLINE-Geräte im ZFS-Pool finden, neue Platte per Vergleich mit dem letzten Scan erkennen, `zpool replace` nur zum Kopieren, Labels alt und neu. | Datenträger › Plattentausch | `p12 platte status pmx10`, `p12 platte label pmx10 --alt ata-ALT --neu sdc --slot SSD-2 --preview platte.png` |
| **Proxmox:** VMs und LXCs mit IP (Guest-Agent bzw. LXC-Config); fehlt ein Recht, steht „IP unbekannt“ da. | Proxmox | `p12 proxmox list pmx10`, `p12 proxmox print pmx10 --typ lxc --preview gaeste.png` |
| **Paperless-ASN:** nächste ASN aus Paperless, lokale Reservierung (keine Dubletten), Fehldrucke verwerfen. Vor dem Serieneinsatz einmal ein Label aufkleben und einscannen. | Paperless | `p12 asn next`, `p12 asn reserve 10 --print --dry-run`, `p12 asn reserve 1 --print --preview asn.png`, `p12 asn void ASN00042 --grund Fehldruck` |
| **Garantie:** Rechnung in Paperless suchen, Etikett `garantie-qr` mit Dokumentlink und Garantieende. | Paperless | `p12 garantie suche --haendler Mindfactory`, `p12 garantie print 17 --preview garantie.png` |
| **Obsidian-Vault:** Notizen der freigegebenen Ordner lesen, Frontmatter als Werte, Vermerk „Label gedruckt: …“ nach dem Druck, Snippet (Markdown-Zeile, PNG-Anhang, Changelog-Entwurf). | Obsidian-Vault | `p12 vault list Hosts`, `p12 vault print Hosts/pmx10 --template host-ip --preview host.png`, `p12 vault snippet --kopieren` |
| **Asset-Tags und Kurz-Links:** Nummern `HL-0001` genau einmal, Register mit Status, QR mit Kurz-Link; ohne Kurz-Link-Dienst enthält der QR die lange Adresse (Warnung). Vorschau, `--dry-run` und der Label-Abruf der Web-Seite rechnen die Kurz-URL nur aus (kein Netz, kein Token); erst der echte Druck bzw. das Anlegen setzt den Link, ein vorhandenes Ziel bleibt dabei erhalten. `p12 kurz set` übernimmt das Ziel auch ins Asset (`ziel`) bzw. in den Artikel (`anzeige`). Optional Vault-Notiz `Assets/HL-0001`. | Assets | `p12 asset neu --bezeichnung NAS --dry-run`, `p12 asset print HL-0001 --preview asset.png`, `p12 kurz set HL-0001 https://ziel.example`, `p12 asset-notiz HL-0001` |
| **Plausibilität:** SN gegen letzten SSH-Scan, Asset- und Kabelregister und Vault prüfen, Hostname per DNS. Konflikte sind Warnungen, gedruckt wird erst nach „Trotzdem drucken“. Gehört zur Kernapp (Einstellungen › Erweitert › Plausibilitätsprüfung). | in den Druckdialogen | `p12 plausi datentraeger host=pmx10 sn=S5Y1NX0R123456` |
| **Kabel:** NetBox-Kabelexport (CSV) mit gespeicherter Spaltenzuordnung, IDs nach TIA-606 (`R1.U01:P01`), Kabelregister mit Duplikatprüfung. | Kabel | `p12 kabel netbox kabel.csv --dry-run`, `p12 kabel ids --schema R1 --units 1 --ports 1-24 --print --preview kabel.png` |
| **Batterien und Wartung:** Geräte mit Batterie aus Home Assistant, Batterietyp je Gerät, Etiketten `batterie` und `wartung`, optional To-do in HA. | Home Assistant | `p12 batterie list`, `p12 batterie wartung USV-Akku --intervall 36 --preview wartung.png` |
| **Seriennummer scannen:** Foto vom Herstelleraufkleber auswerten, beste SN vorausgewählt. | Seriennummer-Scan | `p12 sn-scan aufkleber.jpg --print --host pmx10 --slot SSD-1 --preview sn.png` |
| **Kleinanzeigen:** Artikel `KA-001` mit Status verfügbar, reserviert, verkauft; Label mit QR auf die Anzeige und Reserviert-Etikett. | Kleinanzeigen | `p12 ka neu "Monitor 27 Zoll" --preis 80 --preview ka.png`, `p12 ka print KA-001 --reserviert --preview res.png` |

`p12 disks scan|print` und die Seite Datenträger speichern jeden erfolgreichen SSH-Scan zusätzlich im
Scan-Cache (`<App-Verzeichnis>\homelab\scans\<host>.json`); Plattentausch und Plausibilität lesen ihn.
Schlägt das Speichern fehl, bleibt der Scan erfolgreich (nur ein Protokolleintrag).

### Einstellungsdatei `homelab.json`

Eigene Datei `<App-Verzeichnis>\homelab.json` (nicht `config.json`), bearbeitbar in Einstellungen (je
eingeschaltetem Modul eine Karte; `plausi.*` unter Erweitert › Plausibilitätsprüfung) oder mit
`p12 homelab show|set|check|path`. In der Datei stehen nur Abweichungen
vom Standard.

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `paperless.url` | `null` | Paperless-API, z. B. `http://paperless.example.com:8000` |
| `paperless.public_url` | `null` | Adresse für Dokumentlinks im QR (sonst `url`) |
| `paperless.token_ref` | `null` | Token-Referenz, z. B. `keyring:tapesmith/paperless` |
| `paperless.asn_range` / `asn_prefix` / `asn_width` | `asn` / `ASN` / `5` | Nummernkreis und Form der ASN (Präfix wie `PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX`) |
| `paperless.warranty_fields` | `Kaufdatum`, `Garantie Monate`, `Garantie bis` | Namen der Custom Fields |
| `proxmox.hosts` | `[]` | Liste `{"name", "url", "token_ref", "verify_tls"}` |
| `obsidian.mcp_url` | `null` | Obsidian-MCP (ohne Token, nur LAN), z. B. `http://notes.example.com:8092/mcp` |
| `obsidian.vault_dir` | `null` | lokaler Vault-Ordner: PNG-Anhänge und Rückfall zum Lesen (Notizen, Frontmatter), wenn der MCP nicht erreichbar ist |
| `obsidian.attachments_dir` | `Anhänge/Labels` | Anhangsordner im Vault |
| `obsidian.folders` | `["Hosts", "Dienste"]` | freigegebene Ordner (plus immer `Assets`) |
| `obsidian.append_after_print` | `false` | Vermerk nach dem Druck automatisch anhängen |
| `shortlink.base_url` | `null` | öffentliche Adresse des Kurz-Link-Dienstes (ohne sie: lange QR-Inhalte) |
| `shortlink.admin_url` | `null` | Admin-API im LAN (sonst `base_url`) |
| `shortlink.token_ref` | `null` | Admin-Token (Secret-Referenz) |
| `homeassistant.url` | `null` | Home Assistant, z. B. `http://homeassistant.example.com:8123` |
| `homeassistant.token_ref` | `null` | Long-Lived-Token (Secret-Referenz) |
| `homeassistant.todo_entity` | `null` | z. B. `todo.wartung` für Erinnerungen |
| `homeassistant.battery_below` | `101` | nur Geräte unter diesem Ladestand (101 = alle) |
| `assets.range` / `prefix` / `width` / `check_digit` | `asset` / `HL-` / `4` / `false` | Asset-Nummern |
| `kleinanzeigen.range` / `prefix` / `width` | `ka` / `KA-` / `3` | Artikel-Nummern |
| `kabel.range` / `prefix` / `width` | `kabel` / `K-` / `3` | freie Kabel-IDs |
| `kabel.tia_pattern` | `{rack}.U{unit:02}:P{port:02}` | TIA-606-Schema |
| `plausi.networks` | `["192.168.0.0/16"]` | erwartete Netze für IP-Felder |
| `plausi.dns_check` | `true` | Hostnamen per DNS prüfen |
| `*.timeout_s` | `10.0` | Zeitlimit je Dienst |

Nummernkreise (`p12 nummern`): `asn`, `asset`, `ka`, `kabel`. Ein fehlender Kreis wird beim ersten
Gebrauch mit Präfix und Breite aus `homelab.json` angelegt.

### Tokens

Tokens stehen nie in `homelab.json`, sondern nur Referenzen darauf:

- `file:<pfad>`: erste nicht leere Zeile der Datei. Die Datei gehört in einen Ordner außerhalb jedes Repos, der nur für den eigenen Benutzer lesbar ist. Es gibt keine Standardpfade: jede Referenz trägt man selbst ein.
- `keyring:<dienst>/<benutzer>`: Windows-Anmeldeinformationen; hinterlegen mit
  `p12 homelab secret tapesmith/paperless` (fragt verdeckt, oder `--stdin`).
- `env:<NAME>`: Umgebungsvariable.

Fehlt ein Token, lautet die Meldung `Token fehlt: <Dienst> (<Referenz>)` mit einem Hinweis, wie man es
hinterlegt (Web-API: Status 424). `p12 homelab check` und die Übersicht zeigen den Zustand ohne Netzzugriff.
Nicht erreichbare Dienste ergeben Status 503 bzw. Exit-Code 5.

### Dienste und Ablage

- **Kurz-Link-Dienst:** eigener kleiner Redirect-Dienst in `deploy/shortlink/` (Container, SQLite unter
  `/data`, Admin-API mit Bearer-Token, IDs in Großbuchstaben für kleine QR-Codes), Einrichtung in
  `deploy/shortlink/README.md`.
- **Proxmox:** eigene Read-only-Rolle mit Guest-Agent-Recht per idempotentem Skript
  `deploy/infra/proxmox-tapesmith-role.sh` (erst `--dry-run`); das Token als Secret-Referenz
  (Credential Manager oder Datei) in `proxmox.hosts[].token_ref` eintragen.
- **Datenablage:** `<App-Verzeichnis>\homelab\` mit `assets.sqlite3`, `kleinanzeigen.sqlite3`,
  `kabel.json`, `batterietypen.json` und `scans\`. `p12 backup` sichert `homelab.json` und diesen Ordner
  bisher nicht mit; bei Bedarf den Ordner selbst sichern.

## LAN und Automatisierung

Der Druckdienst p12d kann auch aus dem Heimnetz und von Automatisierungen angesprochen
werden: Familien-Druckseite fürs Handy, Kurzendpunkte, MCP für Claude, Hotfolder,
PowerShell-Modul, Home Assistant und Telegram. Alles läuft im Dienst oder spricht ihn per HTTP an;
p12d bleibt der einzige Inhaber der Druckerverbindung, und jeder Auftrag geht durch dieselbe
Pipeline (Fehldruckschutz, Kontingente, Verlauf, Warteschlange, Restmeter).

Ausführliche Betriebsdoku: [`deploy/infra/README.md`](../deploy/infra/README.md) (LAN, Tokens, MQTT,
Telegram, Hotfolder, MCP, Fehlersuche), [`deploy/homeassistant/README.md`](../deploy/homeassistant/README.md)
und [`deploy/powershell/Tapesmith/README.md`](../deploy/powershell/Tapesmith/README.md).

### Standard: nur lokal

Ohne weiteres Zutun lauscht der Dienst nur auf `127.0.0.1:8712`. Aus dem Netz ist nichts
erreichbar. Die LAN-Freigabe braucht drei Schritte:

1. Firewallregel einmalig **als Administrator**: `.\deploy\infra\setup-tapesmith-lan.ps1`
   (idempotent; `-Status` prüft ohne Adminrechte, `-Remove` baut zurück). Die App selbst legt nie
   eine Firewallregel an.
2. `p12 config set lan.enabled true` (oder Seite „Zugriff“ in der Oberfläche).
3. `p12 daemon restart`, denn die Bindung (`lan.bind`, Standard `0.0.0.0`) wirkt erst nach einem
   Neustart.

Aus dem LAN dürfen nur Adressen aus `lan.allowed_networks` (Standard `192.168.0.0/16`, am besten auf das eigene Netz einschränken) zugreifen.
`/health` und die Dateien der Oberfläche gehen dort ohne Token (LAN-Clients bekommen von `/health`
nur `ok`, `app`, `version`); alles unter `/api/` und `/mcp` braucht ein Token. Fremde Host-Header
(DNS-Rebinding) und fremde `Origin` werden mit 403 abgewiesen. Nach 10 falschen Tokens in
10 Minuten ist eine LAN-Adresse 15 Minuten gesperrt (429 mit `Retry-After`); localhost wird nie
gesperrt.

`lan.public_url` (Standard `null`) ist ein optionaler fester Name statt der IP, z. B.
`http://p12pc.fritz.box:8712`, wenn im Heimnetz ein DNS- oder Router-Eintrag existiert. Gesetzt,
zählt er zusätzlich zu den erlaubten Hosts (Host-Prüfung, DNS-Rebinding-Schutz) und erscheint als
erster Eintrag der Familienlinks (`p12 token add … --rolle familie`, Seite „Zugriff“) sowie in
den PowerShell-Beispielen; ohne `lan.public_url` verwenden Familienlinks stattdessen die lokalen
LAN-Adressen. Nur eine `http://`/`https://`-URL ohne Pfad, per `p12 config set lan.public_url …`
oder Seite „Zugriff“.

### Tokens und Rollen

```
p12 token add Handy-Anna --rolle familie     # Klartext erscheint genau jetzt, danach nie wieder
p12 token add Skripte --rolle drucken
p12 token list
p12 token revoke Handy-Anna                  # wirkt sofort, auch im laufenden Dienst
```

| Rolle | darf |
|---|---|
| `admin` (Verwaltung) | alles, auch Einstellungen, Seite „Zugriff“ und Tokens |
| `drucken` | drucken, Vorschau, Status, Warteschlange, Vorlagen, Galerie, Verlauf, Serien, MCP, Familienrouten |
| `familie` | nur die Familien-Druckseite (`/api/v1/familie/...`) |

Tokens liegen nur als SHA-256-Hash in `%APPDATA%\Tapesmith\access\tokens.json`. Anlegen und
Widerrufen geht auch in der Oberfläche auf der Seite **Zugriff** (dort außerdem LAN, Familie, MCP,
Hotfolder, MQTT und Telegram samt Status der Zusatzdienste). Token senden als
`Authorization: Bearer <Token>`, als `X-P12-Token` oder nur bei GET als `?t=<Token>`.

### Familienseite

`http://<PC-IP>:8712/familie` ist eine eigenständige Handy-Seite mit Familien-Token. Für ein Token
mit Rolle `familie` zeigen CLI und Seite „Zugriff“ den fertigen Link
`http://<PC-IP>:8712/familie#t=<Token>` an; auf dem Handy öffnen und als Lesezeichen speichern.
Angeboten werden nur die Vorlagen aus `family.templates` (Standard `gefriergut`, `geoeffnet-am`,
`vorratsdose`, `schule`, `eigentum`), mit Vorschau und höchstens 5 Kopien je Druck. Dazu die
eingebaute Sondervorlage „Freitext“ (`family.freetext_enabled`, Standard an): ein einzelnes
mehrzeiliges Textfeld ohne Vorlage aus dem Speicher, höchstens 200 Zeichen. Andere Seiten und
Daten (Verlauf, Einstellungen) liefern mit diesem Token nichts.

### Kurzendpunkte (REST)

Stabile Kurzschnittstelle unter `/api/v1` für die Rollen `admin` und `drucken`:

| Methode Pfad | Zweck |
|---|---|
| `POST /print` | Vorlage (`{"template", "values", "copies", "confirmed"}`) oder Quelle drucken |
| `POST /print/text` | Textlabel (`{"text": "Zeile 1\nZeile 2"}` oder `{"lines": [...]}`) |
| `GET /preview.png` | Vorschau (`?template=…&values=<JSON>` oder `?text=…`, `raster=1` für das Druckbild) |
| `GET /jobs`, `DELETE /jobs/{id}` | Warteschlange ansehen, Auftrag entfernen |
| `GET /docs` | schlichte HTML-Übersicht aller Routen mit erlaubten Rollen; Schema unter `/api/v1/openapi.json` |

```powershell
$env:P12_TOKEN = "<Token mit Rolle drucken>"
curl.exe -H "Authorization: Bearer $env:P12_TOKEN" -H "Content-Type: application/json" `
  -d '{\"template\": \"gefriergut\", \"values\": {\"inhalt\": \"Gulasch\"}}' `
  http://<PC-IP>:8712/api/v1/print
curl.exe -H "Authorization: Bearer $env:P12_TOKEN" -o vorschau.png "http://<PC-IP>:8712/api/v1/preview.png?text=Hallo"
```

Das Ergebnis ist ein `OutcomeJson` mit `status` (`ok`, `wartet`, `bestätigung_nötig`, `abgelehnt`,
…) und `reasons`.

### Grenzen für Fremdzugriffe

Aufträge mit API-Token laufen als Quelle `api`, MCP als `mcp`, dazu `mqtt` und `hotfolder`. Diese
Quellen können Rückfragen des Fehldruckschutzes nicht bestätigen: über 5 Kopien
(`guard.confirm_copies`) oder über 150 mm Labellänge (`guard.confirm_label_mm`) lehnt der Dienst ab
(`abgelehnt`, „Quelle api kann nicht bestätigen“). `confirmed: true` bestätigt dort nur die
Band-Rückfrage (Vorlage passt nicht zum eingelegten Band). Zusätzlich gelten die Kontingente je
Stunde aus `guard.quotas` (Standard `api` und `mcp` 20 Aufträge bzw. 1000 mm, `mqtt` 10 bzw.
500 mm, `hotfolder` 30 bzw. 1500 mm). Familie, MCP, MQTT und Hotfolder prüfen die Kopiengrenze
schon vorab.

### MCP für Claude

```
p12 mcp --config      # zeigt die Einrichtung für Claude Code, startet nichts
```

`p12 mcp` ist ein stdio-Server, der per HTTP mit dem lokalen Dienst spricht; im Dienst gibt es
zusätzlich `/mcp` (Streamable HTTP, Token Pflicht, Rolle `admin` oder `drucken`, abschaltbar mit
`mcp.http = false`). Werkzeuge: `list_templates`, `label_preview`, `label_print`,
`printer_status`, `print_history`, `queue_list`. Gedruckt wird nur mit der `preview_id` aus
`label_preview` und `confirm=true`, höchstens 5 Kopien.

### Hotfolder, PowerShell, Home Assistant, Telegram

- **Hotfolder:** `p12 config set hotfolder.enabled true`; Ordner `hotfolder.dir`, Standard
  `%APPDATA%\Tapesmith\hotfolder`. `*.json` (`{"template", "values", "copies"}`, `vars` als Alias),
  `*.txt`, `*.csv`, `*.png`. Gedruckt nach `done\`, Fehler nach `error\` mit `.log`.
  `p12 hotfolder status`, `p12 hotfolder run-once`.
- **PowerShell-Modul:** `Import-Module .\deploy\powershell\Tapesmith`, dann `Get-P12Status`,
  `Send-P12Label -Template gefriergut -Values @{inhalt='Suppe'} -WhatIf`, Pipeline aus
  `Get-PhysicalDisk` oder `Import-Csv`. Spricht die REST-API an (lokal über `session.json`, im LAN
  mit Token).
- **Home Assistant (MQTT):** `p12 secret set mqtt`, `p12 config set mqtt.enabled true`. Gerät
  „Labeldrucker P12“ per Discovery (Verbindung, Akku, Deckel, Warteschlange, Knopf Testlabel),
  Druck über `tapesmith/print/set`. `p12 mqtt discovery`, `p12 mqtt status`.
- **Telegram:** Bot-Token als Secret-Referenz in `telegram.token_ref` (Credential Manager oder Datei),
  `p12 config set telegram.chat_id <ID>`, `p12 config set telegram.enabled true`,
  `p12 telegram test`. Meldungen zu hängender Warteschlange, Offline, Druckfehler und niedrigem
  Restmeter, mit Ruhezeiten.

Hotfolder, MQTT, Telegram und MCP wirken ohne Neustart (der Dienst prüft die Konfiguration alle
5 s); nur `lan.*` braucht `p12 daemon restart`. Geheimnisse stehen nie in `config.json`, nur
Referenzen (`keyring:tapesmith/mqtt`, `file:<Pfad>`, `env:<NAME>`); `p12 secret set|check`.

### Bewusste Abweichungen: LAN und Automatisierung

- **API-Tokens:** liegen nicht im Credential Manager, sondern nur als SHA-256-Hash in
  `%APPDATA%\Tapesmith\access\tokens.json` (Klartext genau einmal beim Anlegen). Grund: mehrere
  Tokens mit Rollen und Widerruf, der Dienst muss sie ohne Nutzer-Sitzung prüfen, ein Hash ist
  nicht rückrechenbar. Geheimnisse Dritter (MQTT-Passwort, Telegram-Bot-Token) liegen weiterhin im
  Credential Manager bzw. in der Token-Datei. `/docs` ist eine schlichte HTML-Übersicht statt
  Swagger UI (keine Skripte vom CDN).
- **MCP:** Druck nur mit `preview_id` aus `label_preview` und `confirm=true`; höchstens 5 Kopien
  je Druck (Quelle `mcp`).
- **Hotfolder:** Standardordner `%APPDATA%\Tapesmith\hotfolder` statt `C:\P12\inbox` (per
  `hotfolder.dir` umstellbar). Das JSON-Feld heißt `values`, `vars` gilt als Alias.
  Gleiche Aufträge einer Datei werden zu Kopien zusammengefasst (Entprellung); höchstens 5 Kopien je
  Auftrag.
- **PowerShell:** Das Modul spricht REST statt der Named Pipe.
- **MQTT:** Druck-Topic ist `tapesmith/print/set` (Präfix `mqtt.base_topic`, Standard `tapesmith`)
  statt `p12/print/set`; mit `mqtt.base_topic = "p12"` entsteht die kurze Form. Kein Band-Sensor
  (unverifiziert). Höchstens 5 Kopien je Auftrag.
- **Familie:** höchstens 5 Kopien je Druck, auch wenn `family.max_copies` größer ist.
- **Telegram:** Keine Meldungen zu Band leer oder Akku.
- **Übergreifend:** Nicht-interaktive Quellen (`api`, `mcp`, `mqtt`, `hotfolder`) können
  Rückfragen des Fehldruckschutzes nicht bestätigen: über 5 Kopien oder über 150 mm Labellänge wird
  abgelehnt; `confirmed` bestätigt dort nur die Band-Rückfrage.

Prüfungen am Gerät und im Heimnetz: [`docs/hardware/README.md`](hardware/README.md), Abschnitt
„LAN und Automatisierung: Prüfungen am Gerät und im Heimnetz“.

## Feinschliff

Der Feinschliff bringt die Oberfläche auf ein ruhiges, einheitliches Fluent-2-Niveau, macht sie
vollständig per Tastatur und Screenreader bedienbar, ergänzt Editor-Tabs mit Absturz-
Wiederherstellung, eine Installation ohne Adminrechte, signierte Updates und Englisch als zweite
Sprache. Version: **0.2.0** (erste installierbare Version).

### Sprache

- Unterstützt sind Deutsch und Englisch. Einstellung **Einstellungen › Oberfläche › Sprache**
  (`app.language`): `auto` (Standard, „wie Windows“), `de` oder `en`. Bei `auto` gilt überall die
  **Windows-Anzeigesprache** des Rechners, auf dem Tapesmith läuft: Deutsch bei deutschem Windows,
  bei jeder anderen Sprache Englisch.
- Die Web-Oberfläche übernimmt bei `auto` die vom Dienst gemeldete Sprache (`resolved_language` in
  `GET /api/v1/app`), nicht die des Browsers. Nur wenn der Dienst keine meldet, gilt die erste
  Browsersprache mit Deutsch oder Englisch. Die Familienseite `/familie` folgt immer der Sprache des
  Handys. Der Wechsel wirkt sofort, ohne Neustart; `<html lang>` folgt, alle Daten werden in der neuen
  Sprache neu geladen.
- Die Tray-App (Menü, Hinweise, Tooltip, Status) folgt derselben Einstellung.
- **Texte des Dienstes** (Statuswerte und Statusdetails, Warnungen der Renderer und Generatoren,
  Plausibilitäts- und Fehldruckschutz-Meldungen, Fehlermeldungen und Hinweise der API, Selbsttest,
  Support-Bericht, Telegram-Meldungen, Vorlagen, Band- und Zielnamen) kommen in der Sprache der
  Anfrage: Kopfzeile `X-Tapesmith-Language` (setzt die Oberfläche), Parameter `lang` (Bilder, Links,
  Ereignis-Strom) oder `Accept-Language`, sonst `app.language` bzw. die Windows-Anzeigesprache.
  Fehlermeldungen tragen weiter einen stabilen Code (`error.code`, z. B. `printer.busy`).
- **CLI:** Ausgaben und Hilfetexte folgen ebenfalls `app.language` bzw. der Windows-Anzeigesprache.
  `TAPESMITH_LANG=de` oder `TAPESMITH_LANG=en` erzwingt eine Sprache (für Skripte, die feste
  Meldungen erwarten, empfiehlt sich `TAPESMITH_LANG=de`). Exit-Codes (0, 1, 5, 6, 7), Optionsnamen,
  Unterbefehle, Vorlagen-IDs und Statuswerte (z. B. `wartet`, `läuft`) sind in allen Sprachen gleich.
  Aufträge über den Druckdienst liefern ihre Meldungen in der Sprache der CLI.
- Die letzte Zeile des Selbsttests bleibt `Selbsttest ok` (feste Kennung für Update und Build), die
  übrigen Zeilen sind übersetzt.
- Übersetzungen: `web/src/locales/<sprache>/` (Oberfläche), `src/tapesmith/locales/<sprache>/`
  (Tray, Fehlercodes, Module) und der Meldungskatalog `src/tapesmith/locales/messages/en.json`
  (deutscher Text als Kennung, gepflegt mit `python tools/i18n_messages.py`). Tests prüfen, dass
  jeder Text übersetzt ist und englische Antworten, Vorlagen und CLI-Hilfen keine deutschen Reste
  enthalten.

### Aussehen und Barrierefreiheit

- **Farbschema** (`app.theme`): `system` („wie Windows“, folgt live dem Windows-Farbmodus), `hell`
  oder `dunkel`. Die Bandvorschau behält immer die echte Bandfarbe.
- **Kontrastdesigns** von Windows (z. B. „Wüste“, „Nachthimmel“) werden erkannt
  (`forced-colors`): Rahmen statt Schatten, Systemfarben, sichtbarer Fokus.
- **Reduzierte Bewegung:** Ist in Windows „Animationseffekte“ aus (`prefers-reduced-motion`),
  entfallen alle Übergänge und Einblendungen.
- **Zoom bis 200 %:** Browser- bzw. Fenster-Zoom und Windows-Skalierung bis 200 % ohne waagrechtes
  Scrollen der Seite; breite Tabellen scrollen in ihrem eigenen, per Tab erreichbaren Rahmen.
- **Tastenkürzel-Übersicht:** `?` oder `F1` (außerhalb von Eingabefeldern) zeigt alle Kürzel der
  aktuellen Seite und die globalen, mit Suche.
- **Skip-Link:** Das erste Tab auf jeder Seite zeigt „Zum Inhalt springen“, vorbei an Seitenleiste und
  Kopfzeile.
- Jede Seite ist in Vitest mit axe-core geprüft (Deutsch und Englisch, Grund-, gefüllter und leerer
  Zustand), Kontraste zusätzlich im echten Chromium über das Screenshot-Werkzeug (hell und dunkel).
  Dialoge fangen den Fokus und geben ihn beim Schließen an den Auslöser zurück; Schaltflächen nur mit
  Symbol haben einen übersetzten Namen und Tooltip; Status nie nur über Farbe.

### Editor-Tabs und Wiederherstellung

- Der Editor öffnet bis zu **12 Tabs** (je Dokument einer). Kürzel: **Strg+Alt+T** neuer Tab,
  **Strg+Alt+W** Tab schließen, **Strg+Bild ab** / **Strg+Bild auf** nächster bzw. voriger Tab.
- **Autosave:** Jeder Tab wird 1,5 s nach der letzten Änderung als Entwurf im Druckdienst gespeichert
  (`%APPDATA%\Tapesmith\drafts\<id>.json`, höchstens 50 Entwürfe zu je 2 MB). Jeder Browser-Tab meldet
  sich alle 30 s beim Dienst (Lebenszeichen).
- **Wiederherstellung:** Entwürfe eines Tabs, der nicht regulär geschlossen wurde (Absturz,
  beendeter Prozess, Dienst-Neustart), bietet der nächste Start an: im Editor als Dialog „Entwürfe
  wiederherstellen?“ (Wiederherstellen, Verwerfen, Später), auf anderen Seiten als Hinweis mit
  „Im Editor wiederherstellen“. Direkt: `/editor?wiederherstellen=1`.
- **Rückfrage beim Schließen:** Schließt oder lädt man den Browser-Tab mit ungespeicherten
  Editor-Tabs neu, fragt der Browser mit seinem eigenen Dialog nach (`beforeunload`); „Bleiben“
  lässt die Seite offen. Die Entwürfe bleiben auch nach dem Verlassen erhalten und werden beim
  nächsten Start angeboten.
- Der alte Einzel-Entwurf `documents\_entwurf.p12doc.json` wird beim ersten Start einmalig als
  verwaister Entwurf „Entwurf“ übernommen.

### Installation ohne Adminrechte

Tapesmith wird über Python verteilt (Paket `tapesmith` auf PyPI) und läuft mit dem signierten
Python von python.org. Eine eigene EXE gibt es nicht, deshalb blockiert Windows Smart App Control
nichts, obwohl Tapesmith selbst kein Code-Signing-Zertifikat hat.

1. Python installieren (3.12, 3.11 geht auch), z. B. in einem normalen Terminal ohne Adminrechte:

   ```
   winget install Python.Python.3.12
   ```

2. Tapesmith für den aktuellen Benutzer holen und einrichten:

   ```
   py -m pip install --user tapesmith
   py -m tapesmith install
   ```

- Ordner: `%LOCALAPPDATA%\Programs\Tapesmith\versions\<version>\` ist je Version eine eigene
  Python-Umgebung (venv) mit genau diesem Tapesmith-Stand, `current` ist eine Verzeichnis-Junction
  auf die aktive Version, `install.json` hält Version, Vorversion, gescheiterte Versionen und das
  Basis-Python. Umgebungsvariable `TAPESMITH_INSTALL_ROOT` bzw. `--root` wählen einen anderen Ordner.
- Die Installation legt die Umgebung mit dem laufenden Python an (`--python` wählt ein anderes),
  installiert darin Tapesmith mit pip (nur fertige Wheels, `--only-binary=:all:`) und führt den
  Selbsttest der neuen Umgebung aus. Erst danach wird umgeschaltet.
- Gestartet wird immer `current\Scripts\pythonw.exe -m …`: Startmenü „Tapesmith“
  (`-m tapesmith.webui.browser`), Autostart der Tray-App (`HKCU\…\Run`, Wert „Tapesmith“,
  `-m tapesmith.gui.tray`), `tapesmith://`, `p12label://` und Kontextmenü. Eintrag unter
  **Einstellungen › Apps › Installierte Apps** (HKCU, Herausgeber „Tapesmith contributors“) mit
  Deinstallation (`pythonw -m tapesmith uninstall`).
- **Deinstallieren** über „Installierte Apps“, die Startmenü-Verknüpfung „Tapesmith deinstallieren“
  oder `py -m tapesmith uninstall`: Programmordner, Startmenü und Registry-Einträge werden entfernt.
  **Benutzerdaten in `%APPDATA%\Tapesmith` (Einstellungen, Verlauf, Entwürfe) bleiben erhalten.** Das
  für die Einrichtung genutzte Paket entfernt `py -m pip uninstall tapesmith`.
- Schalter: `install [--root D] [--python P] [--no-shortcuts] [--no-registry] [--no-autostart]
  [--no-start] [--no-open] [--quiet] [--force]`, zum Testen ohne PyPI `--wheel DATEI`,
  `--find-links ORDNER`, `--no-index` und `--lock lock.txt`; `uninstall [--root D] [--no-shortcuts]
  [--no-registry] [--quiet]`.
- Ergebnis auf der Konsole und in `<App-Verzeichnis>\logs\install.log` bzw. `uninstall.log`, Exit-Code
  0 ok, 1 Fehler. Nach erfolgreicher Installation starten die Tray-App und die Web-Oberfläche im
  Standardbrowser (`--no-open` bzw. `--quiet`: nur die Tray-App, `--no-start`: nichts).
- `py -m tapesmith install --status [--json]` zeigt Wurzel, aktive Version, Junction, Basis-Python und
  die Art der Installation, ohne etwas zu ändern.
- **Smart App Control:** `python.exe` und `pythonw.exe` von python.org sind signiert, alle nativen
  Teile (Qt, Pillow, cryptography, pydantic und andere) kommen unverändert als Wheels ihrer
  Projekte von PyPI. Die kleinen `.exe`-Starter, die pip für Kommandozeilenbefehle anlegt, nutzt die
  installierte App nicht; blockiert Smart App Control sie, `py -m tapesmith …` statt `tapesmith …`
  verwenden.
- **Lange Pfade:** Qt (PySide6) bringt sehr lange Dateinamen mit. Bei einem sehr langen
  Benutzernamen kann pip an der Grenze von 260 Zeichen scheitern (Meldung zu „Long Path Support“);
  dann in Windows lange Pfade erlauben (einmalig mit Adminrechten, `LongPathsEnabled`) oder mit
  `--root` einen kürzeren Ordner wählen.
- **Umstieg vom portablen Build (bis 0.3) oder von einem Quellcode-Start:** die beiden Befehle aus
  Schritt 2 ausführen. `tapesmith install` beendet das alte Tapesmith, übernimmt den
  Installationsordner, ersetzt Autostart, Startmenü und Eintrag unter „Installierte Apps“ und
  entfernt die alte `Tapesmith.exe`. Zeigt der Autostart auf eine Python-Umgebung außerhalb der
  Installation (z. B. `C:\src\tapesmith\.venv`), wird Tapesmith dort beendet und der Autostart
  umgestellt; die Umgebung selbst bleibt unangetastet. Die Benutzerdaten bleiben, wie sie sind.

### Updates

- **Nur mit Zustimmung:** Die automatische Prüfung (`update.enabled`) ist aus, bis der Benutzer zustimmt. Beim
  ersten Start der installierten App fragt die Web-Oberfläche einmal („Automatisch nach Updates
  suchen?“); beide Antworten werden gespeichert (`update.asked`), später ändert der Schalter unter
  Einstellungen › Updates die Wahl. Ohne Zustimmung baut Tapesmith von sich aus keine Verbindung zur
  Update-Quelle auf; „Jetzt prüfen“ funktioniert trotzdem.
- **Quellen** (`update.source`): `github:essendyx/tapesmith` (Standard, GitHub-Releases über die
  REST-API, Pakete von PyPI), `file:<Ordner>` (Ordner oder Dateifreigabe mit `manifest.json`,
  `manifest.json.sig` und `lock.txt`; liegen dort auch die Wheels, direkt oder unter `wheels\`,
  installiert pip nur aus diesem Ordner) oder eine `https://…/`-Basisadresse.
- **Ohne Token:** Das Repository ist öffentlich, GitHub wird ohne Anmeldung abgefragt (höchstens 60
  Abrufe je Stunde und Adresse). Ein alter Eintrag `update.token_ref` in `config.json` wird ignoriert.
- **Kanal** `stable` oder `beta` (Vorabversionen wie `0.4.0b1`); Prüfabstand `update.check_interval_h`.
- **Ablauf:** Manifest laden und die Ed25519-Signatur prüfen. Das Manifest enthält Version, Kanal
  und eine vollständige Lock-Liste (jedes Paket mit Version und SHA-256 aller Wheels für Windows x64
  und die unterstützten Python-Versionen). Daraus entsteht `lock.txt`; der Updater legt mit dem
  Basis-Python der Installation die neue Umgebung `versions\<v>` an und installiert mit
  `pip install --require-hashes --only-binary=:all: -r lock.txt`, also nur Dateien, deren Prüfsumme
  im signierten Manifest steht. Danach Kontrolle der installierten Version und Selbsttest
  (`pythonw -m tapesmith.selftest`) in der neuen Umgebung. Umgeschaltet wird nur im
  **Leerlauf**: automatisch (`update.auto_install`) erst, wenn der Dienst seit `update.idle_min`
  Minuten nichts druckt und seit 120 s kein Browser-Tab mit der Oberfläche offen ist; „Jetzt
  installieren“ in Einstellungen › Updates verlangt nur „kein Auftrag aktiv, Warteschlange leer“ und
  fragt vorher, weil der Dienst kurz neu startet. Danach öffnet sich die Oberfläche mit der neuen
  Version in einem neuen Browser-Tab (der alte Tab verliert seine Sitzung und kann geschlossen werden).
- **Rückfall:** Meldet sich der neue Dienst nicht binnen 60 s mit der neuen Version, stellt der
  Updater automatisch auf die vorige Version zurück und merkt sich die gescheiterte Version (sie wird
  nie wieder automatisch angeboten). Scheitert schon der Selbsttest, wird gar nicht umgeschaltet.
  `update.keep_versions` ältere Versionen bleiben liegen.
- CLI: `py -m tapesmith update status [--json]`, `… update check`, `… update install [--yes]`,
  `… update rollback [--yes]` (in einer Entwicklungsumgebung auch `p12 update …`).
- **Signaturschlüssel:** Nur Manifeste, deren Signatur zu einem Schlüssel in
  `src/tapesmith/update/trusted_keys.json` passt, werden angenommen; ohne passenden Schlüssel meldet
  die Seite „Kein vertrauenswürdiger Signaturschlüssel“ und es gibt kein Update.
- **Release veröffentlichen:** Tag `v<version>` pushen; der Workflow `.github/workflows/release.yml`
  baut Wheel und sdist, erzeugt Lock-Liste und Manifest, signiert es, veröffentlicht auf PyPI und legt
  das GitHub-Release an (Details in `deploy/infra/README.md`).

### Problem melden

**Einstellungen › Hilfe und Diagnose › Problem melden** bzw. `p12 report --out DATEI.zip` erzeugt
ein Zip mit `bericht.txt` (Version, Windows, portabel oder installiert, Transport, Druckerstatus,
Warteschlange), der maskierten `config.json` und den letzten 512 KB je Logdatei. Tokens,
Passwörter und Schlüssel werden entfernt (`***`), Secret-Referenzen bleiben als Referenz. Es wird
nichts verschickt: das Zip gibt man selbst weiter.

### Neue `config.json`-Schlüssel

| Schlüssel | Standard | Wirkung |
|---|---|---|
| `app.language` | `"auto"` | Sprache von Oberfläche, Tray-App, Dienst und CLI: `auto` (Windows-Anzeigesprache), `de`, `en` |
| `app.theme` | `"system"` | Farbschema: `system`, `hell`, `dunkel` |
| `update.enabled` | `false` | regelmäßig nach Updates suchen (aus bis zur Zustimmung, siehe Updates) |
| `update.asked` | `false` | die Web-Oberfläche hat einmal nach der automatischen Prüfung gefragt |
| `update.source` | `"github:essendyx/tapesmith"` | Update-Quelle: `github:owner/repo`, `file:<Ordner>` oder `https://…` |
| `update.channel` | `"stable"` | `stable` oder `beta` |
| `update.check_interval_h` | `24` | Prüfabstand in Stunden (1 bis 720) |
| `update.auto_install` | `false` | im Leerlauf automatisch installieren |
| `update.idle_min` | `10` | Minuten Leerlauf vor dem automatischen Update (1 bis 1440) |
| `update.keep_versions` | `2` | ältere Versionen, die im Programmordner bleiben (1 bis 5) |

### Bewusste Abweichungen: Oberfläche, Installation und Update

- Kein Mica-Effekt (die Oberfläche läuft im Browser), stattdessen ruhige Fluent-Flächen; das
  Farbschema ist zusätzlich fest hell oder dunkel wählbar.
- Tabs gibt es im Editor (dort entstehen Etiketten frei); „Problem melden“ verschickt nichts.
- Installation über Python (`py -m tapesmith install`) statt Inno Setup oder eigener EXE; Update-Signatur
  Ed25519 über ein Manifest mit SHA-256 aller Pakete statt Authenticode (kein Code-Signing-Zertifikat); Dateizuordnung bleibt beim Kontextmenü für
  `*.tapesmith.json`.
- Keine Einheitenwahl (Maße bleiben mm und Druckpunkte). Optionsnamen und Unterbefehle der CLI,
  Vorlagen-IDs und Statuswerte sind deutsche Kennungen und bleiben in allen Sprachen gleich.

## Paket bauen und prüfen

Wheel und sdist entstehen mit `python -m build` (im Entwicklungs-venv aus `pip install -e ".[dev]"`):

```
.venv\Scripts\python tools\build_web.py
.venv\Scripts\python -m build
```

Ergebnis: `dist\tapesmith-<version>-py3-none-any.whl` und `dist\tapesmith-<version>.tar.gz`. Das
Wheel enthält die gebaute Web-Oberfläche (`tapesmith/webui/static`), Schriften, Vorlagen, Symbole
und die Übersetzungskataloge; Einstellungen und Verlauf liegen unabhängig davon unter
`%APPDATA%\Tapesmith`. Eine Probeinstallation ohne PyPI, ohne Registry und ohne Startmenü (z. B. in
einer Wegwerf-Umgebung unter `%TEMP%`):

```
py -m venv %TEMP%\ts-probe
%TEMP%\ts-probe\Scripts\python -m pip install dist\tapesmith-<version>-py3-none-any.whl
set TAPESMITH_INSTALL_ROOT=%TEMP%\ts-probe-root
set TAPESMITH_HOME=%TEMP%\ts-probe-home
%TEMP%\ts-probe\Scripts\python -m tapesmith install --wheel dist\tapesmith-<version>-py3-none-any.whl --no-registry --no-shortcuts --no-start
```

Der eingebaute Selbsttest (`python -m tapesmith.selftest --selftest-out selftest.txt`; letzte Zeile
„Selbsttest ok“) läuft bei jeder Installation und jedem Update in der neuen Umgebung. Er prüft auch
die Web-API (ohne Port), die gebaute Oberfläche, uvicorn und den Browserstart (Adresse mit Token,
ohne echten Browser), außerdem die Übersetzungskataloge (de/en mit gleichen Schlüsseln,
Meldungskatalog lesbar), die Update-Signatur (Ed25519 im Speicher, `trusted_keys.json` lesbar) und
das Installationslayout (Junction anlegen, umstellen, entfernen in einem Temp-Ordner). Das
App-Symbol `src/tapesmith/icons/app.ico` erzeugt `tools/make_app_icon.py` (`--check` prüft es).

Hardware-Befunde: [`docs/hardware/README.md`](hardware/README.md)
