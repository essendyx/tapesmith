# Home Assistant Anbindung (MQTT Discovery)

Der Druckdienst `p12d` meldet sich per MQTT Discovery als Gerät „Labeldrucker P12" bei Home
Assistant an, solange `mqtt.enabled` in `config.json` an ist. Entitäten, Topics und Grenzen
beschreibt diese Datei.

## Voraussetzungen

* Ein MQTT-Broker (z. B. Mosquitto), in Tapesmith eingetragen über `mqtt.host` und `mqtt.port` (Standard-Port 1883).
* Ein Mosquitto Benutzer `tapesmith` mit ACL: lesen und schreiben auf `tapesmith/#`, schreiben auf
  `homeassistant/#`. Diesen Benutzer legt der Administrator des Brokers an, die App tut das nicht.
* Home Assistant mit aktivierter MQTT Integration, Discovery Präfix `homeassistant` (Standard).

## Einrichtung

1. Passwort des Mosquitto Benutzers `tapesmith` in den Windows Anmeldeinformationen hinterlegen:

   ```
   p12 secret set mqtt
   ```

   (fragt das Passwort interaktiv ab; alternativ `p12 secret set mqtt --stdin` mit dem Passwort
   auf der Standardeingabe, z. B. aus einem Passwortmanager, nie als Kommandozeilenargument).

2. MQTT einschalten:

   ```
   p12 config set mqtt.enabled true
   ```

   Die Anbindung wirkt ohne Dienst-Neustart (Addon-Prüfung alle 5 Sekunden).

3. Zur Kontrolle, ohne Verbindungsaufbau:

   ```
   p12 mqtt discovery   # zeigt die Discovery-Nachrichten als JSON
   p12 mqtt status      # zeigt an/aus, Broker, Benutzer, Passwort-Referenz
   ```

## Entitäten

| Entität | Komponente | Bedingung |
|---|---|---|
| Verbindung | `binary_sensor` (`device_class: connectivity`) | immer |
| Akku | `sensor` (`device_class: battery`, `%`) | nur wenn `battery` im Geräteprofil verifiziert ist |
| Deckel | `binary_sensor` (`device_class: opening`) | nur wenn `lid` im Geräteprofil verifiziert ist |
| Warteschlange | `sensor` (Einheit „Aufträge") | immer |
| Testlabel | `button` | immer |

Der P12 verifiziert Akku und Deckel serienmäßig (siehe `device/profiles/p12.json`); der
Deckelcode ist beim P12 invertiert, das steckt bereits im Geräteprofil, hier zählt nur der
dekodierte Wert (`offen`/`zu`). Ein Sensor für „Band leer" fehlt bewusst: dieser Wert ist beim
P12 nicht verifiziert.

Ist der Deckelzustand (noch) nicht bekannt (`lid_open: null` im Zustandstopic, z. B. direkt nach
dem Start), zeigt der Deckelsensor in Home Assistant „unbekannt" statt fälschlich „zu": die
Discovery-Vorlage prüft `lid_open is none` und liefert dann die Jinja-Sentinel `none`.

## Topics

Alle Topics beginnen mit `mqtt.base_topic` (Standard `tapesmith`):

| Topic | Richtung | Inhalt |
|---|---|---|
| `<base>/availability` | Dienst → HA | `online`/`offline` (retain, Last Will) |
| `<base>/state` | Dienst → HA | `{"connected", "battery", "lid_open", "queue"}` (retain, JSON) |
| `<base>/print/set` | HA → Dienst | `{"template", "values"?, "copies"?}` (JSON) |
| `<base>/print/result` | Dienst → HA | `{"status", "title", "message"}` (JSON, nicht retain) |
| `<base>/test/press` | HA → Dienst | beliebiger Inhalt, druckt ein Testlabel |

Beispiel: eine Vorlage mit Werten über `mqtt.publish` drucken.

```yaml
service: mqtt.publish
data:
  topic: tapesmith/print/set
  payload: >-
    {"template": "gefriergut", "values": {"inhalt": "Suppe"}, "copies": 2}
```

## Kontingent

MQTT ist eine nicht-interaktive Quelle. Kopien sind höchstens
`guard.confirm_copies` (Standard 5) je Auftrag; mehr wird abgelehnt, die Meldung steht im
Ergebnis auf `<base>/print/result`. Eine Rückfrage wegen zu langem Label oder zu vielen Kopien
lässt sich über MQTT nicht bestätigen (`confirmed` sendet MQTT nie); nur die Rückfrage wegen
eines nicht passenden Bandes wird von der Pipeline unabhängig von der Quelle als
`bestätigung_nötig` gemeldet, MQTT druckt dann trotzdem nicht (kein zweiter Versuch), sondern
meldet die Gründe.

## Beispiele in diesem Ordner

* `tapesmith-skript.yaml`: Home Assistant Skript `tapesmith_drucken` mit Feldern für Vorlage,
  Werte und Kopien. Der Nummern-Selektor für Kopien liefert im Template eine Gleitkommazahl
  (`1.0`), das Template wandelt sie mit dem Filter `| int` in eine ganze Zahl um; der Druckdienst
  nimmt eine ganzzahlige Gleitkommazahl ohnehin an (`1.0` wie `1`), lehnt aber echte
  Nachkommastellen (`1.5`) ab.
* `tapesmith-automation-nfc.yaml`: Beispiel Automation, die beim Scannen eines NFC Tags das
  Skript mit einer Vorlage aufruft.
* `tapesmith-rest-command.yaml`: Alternative zu MQTT, `rest_command` ruft die Kurzendpunkte
  (`POST /api/v1/print`) direkt per REST auf, mit dem Token aus `secrets.yaml`
  (`X-P12-Token: !secret p12_token`). Braucht `lan.enabled = true` und ein API-Token mit Rolle
  `drucken` oder `admin`.

Beide Dateien lassen sich über die Home Assistant Oberfläche (Einstellungen, Automatisierungen
und Skripte, YAML bearbeiten) oder als Datei unter `config/scripts.yaml` bzw.
`config/automations.yaml` einfügen.
