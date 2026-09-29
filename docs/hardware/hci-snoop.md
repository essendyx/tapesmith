# HCI-Snoop-Mitschnitt

Anleitung, um den Bluetooth-Funkverkehr zwischen der Android-App **Print Master** und dem P12
mitzuschneiden. Das ist der sicherste Weg, unbelegte Befehle (z. B. einen Dichtebefehl) zu finden,
ohne raten zu müssen.

## Voraussetzungen

- Android-Handy mit aktivierten Entwickleroptionen (Einstellungen → Über das Telefon → mehrmals auf
  die Build-Nummer tippen).
- Die Android-App **Print Master** (die App, mit der der P12 normalerweise bedient wird).
- Ein PC mit [Wireshark](https://www.wireshark.org/) und `adb` (Android Platform Tools).
- Ein USB-Kabel zum Verbinden des Handys mit dem PC.

## Mitschnitt aufnehmen

1. Entwickleroptionen öffnen → **„Bluetooth-HCI-Snoop-Protokoll aktivieren"** einschalten.
2. Bluetooth am Handy aus- und wieder einschalten, damit die Aufzeichnung sauber neu beginnt.
3. Den P12 frisch einschalten (nicht schon vorher aus einer anderen App/Verbindung gedruckt haben,
   sonst greift der Print-Master-Effekt, siehe `density.PRINT_MASTER_NOTE`).
4. In Print Master ein Label **einmal mit Dichte „niedrig"**, dann **einmal mit Dichte „hoch"**
   drucken.
5. Die Uhrzeit beider Druckvorgänge notieren (Start/Ende), das erleichtert später das Filtern im
   Mitschnitt.

## Datei holen

- `adb bugreport bericht.zip` ausführen; das Snoop-Log liegt darin unter
  `FS/data/misc/bluetooth/logs/btsnoop_hci.log`.
- Auf älteren Geräten liegt es direkt unter `/sdcard/btsnoop_hci.log` (dann per `adb pull` holen).

## Auswerten

1. `btsnoop_hci.log` in Wireshark öffnen.
2. Für **BLE**: Filter `btatt.opcode == 0x52 || btatt.opcode == 0x12` (Write Command/Write Request)
   auf das Handle der Schreib-Charakteristik (beim P12 FF02, siehe `transport/ble.py`).
3. Für **SPP** (klassisches Bluetooth, wie es die CLI/GUI standardmäßig nutzt): Filter `btrfcomm`.
4. Die Bytes der gefundenen Pakete als Hex exportieren.
5. Gezielt nach diesen Präfixen suchen: `1B 4E 04` (M110-Kandidat), `1F 11 02` (M02-Kandidat),
   `1B 37` (ESC 7, Heizparameter, **gesperrt**, siehe `protocol.rawcmd`), `1F 11` (Abfragen).

## Vergleich mit dem Hex-Log

- Mit `p12 --hexlog log.txt text Test` einen eigenen Testdruck mitschneiden (unser eigenes Protokoll).
- `log.txt` mit dem aus Wireshark exportierten Mitschnitt vergleichen.
- Alle Unterschiede **vor** dem Rasterkopf (`1D 76 30`) notieren. Das sind die Kandidaten für
  bisher unbekannte Befehle.
- Tabelle führen:

  | Zeit | Richtung | Bytes | Vermutung |
  |---|---|---|---|
  | | TX/RX | | |

## Ergebnis eintragen

- Befund in `docs/hardware/README.md` eintragen (Gerät, Firmware, gefundene Bytes, Vermutung).
- Danach gezielt mit `p12 raw` einzelne Kandidaten testen, dabei die Schutzliste beachten:
  gesperrte Befehle (`1B 37`) werden nie gesendet, alles Unbekannte nur mit `--unsafe` und
  ausdrücklicher Bestätigung.

## Datenschutz

Das Snoop-Log enthält den **gesamten** Bluetooth-Verkehr des Handys (nicht nur den mit dem P12),
also potenziell auch andere Geräte, Kopfhörer, Wearables. Nach der Auswertung: Log löschen, das
Bluetooth-HCI-Snoop-Protokoll wieder ausschalten, und die Datei **nicht** ins Repo aufnehmen.
