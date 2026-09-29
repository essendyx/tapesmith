# Tapesmith: PowerShell-Modul für den Phomemo P12

Automatisierung des Labeldruckers Phomemo P12 aus der PowerShell-Konsole (Windows PowerShell 5.1
und PowerShell 7): Labels drucken, auch aus der Pipeline (z. B. `Get-PhysicalDisk`, `Import-Csv`),
Vorschau als PNG, Status, Vorlagen und Warteschlange. Das Modul spricht ausschließlich die REST-API
des Druckdienstes **p12d** an, lokal mit dem Sitzungs-Token aus
`session.json`, im LAN mit einem API-Token.

## Installation

Variante A, dauerhaft für den eigenen Benutzer:

```powershell
Copy-Item -Recurse C:\src\tapesmith\deploy\powershell\Tapesmith `
    "$HOME\Documents\WindowsPowerShell\Modules\Tapesmith"
Import-Module Tapesmith
```

Variante B, direkt aus dem Repository (z. B. zum Testen einer neuen Version):

```powershell
Import-Module C:\src\tapesmith\deploy\powershell\Tapesmith
```

`Get-Command -Module Tapesmith` zeigt die acht Cmdlets.

## Lokale Nutzung

Läuft der Druckdienst bereits auf diesem PC (`p12 app` bzw. `p12 daemon start`), findet
`Connect-P12` Adresse und Sitzungs-Token automatisch über `session.json`:

```powershell
Get-P12Status
Get-P12Template
Send-P12Label -Template gefriergut -Values @{inhalt = 'Suppe'} -WhatIf
Send-P12Label -Template gefriergut -Values @{inhalt = 'Suppe'}
```

`-WhatIf` erzeugt nur eine Vorschau (PNG-Datei unter `$env:TEMP`) und druckt nichts.

## Nutzung im LAN mit einem API-Token

Auf dem PC mit dem Druckdienst ein Token mit der Rolle `drucken` anlegen:

```powershell
p12 token add PowerShell --rolle drucken
```

Auf dem anderen Rechner im Netz damit verbinden (das Token wird als `SecureString` abgefragt und
nie ausgegeben):

```powershell
Connect-P12 -Uri http://<PC-IP>:8712 -Token (Read-Host -AsSecureString)
Get-P12Status
```

Alternativ per Umgebungsvariablen (gilt, solange `Connect-P12` nicht aufgerufen wurde):

```powershell
$env:TAPESMITH_URL = 'http://<PC-IP>:8712'
$env:TAPESMITH_TOKEN = '<Token>'
```

Die alten Namen `P12LABEL_URL` und `P12LABEL_TOKEN` (vor Version 0.3) gelten weiter als Rückfall.

`Disconnect-P12` setzt die Verbindung zurück, danach wird sie wieder neu ermittelt.

## Beispiele

Seriennummer von Datenträgern etikettieren, erst als Vorschau prüfen:

```powershell
Get-PhysicalDisk | Select-Object -First 1 |
    Send-P12Label -Template datentraeger -Map @{sn = 'SerialNumber'} -WhatIf
```

Ohne `-WhatIf` wird gedruckt. Kabeletiketten aus einer CSV-Datei (Spaltennamen entsprechen den
Feld-Ids der Vorlage, sonst `-Map` verwenden):

```powershell
Import-Csv kabel.csv | Send-P12Label -Template kabelfahne
```

Warteschlange ansehen und aufräumen:

```powershell
Get-P12Job -IncludeDone
Get-P12Job | Where-Object Zustand -eq wartet | Remove-P12Job -Confirm:$false
```

## Grenzen für die Quelle `api`

Das Modul sendet jede Anfrage mit dem Kopf `X-P12-Source: api`. Der Fehldruckschutz erlaubt dieser
Quelle höchstens 5 Kopien je Auftrag und Labels bis 150 mm (Einstellung `guard.confirm_copies` bzw.
`guard.confirm_label_mm`); darüber liefert `Send-P12Label` den Status `abgelehnt`, `-Confirmed`
hilft dagegen nicht. `-Confirmed` bestätigt nur, dass das eingelegte Band nicht zur Vorlage passt
(Band-Rückfrage, Status `bestätigung_nötig`). Zusätzlich gilt für die Quelle `api` ein Kontingent
von 20 Aufträgen pro Stunde (Fehldruckschutz-Einstellungen in der Web-Oberfläche bzw.
`p12 config`).

## Fehlerbehandlung

Fehlerantworten des Druckdienstes (einheitliches Format mit `message` und `hint`) werden zu einem
terminierenden PowerShell-Fehler mit genau dieser Meldung. Ein abgelehnter oder um Rückfrage
bittender Druckauftrag terminiert den Aufruf dagegen nicht: `Send-P12Label` liefert immer ein
Ausgabeobjekt mit `Status`, `Titel`, `Warteschlange`, `Warnungen`, `Gruende`; bei `abgelehnt`
zusätzlich einen nicht terminierenden Fehler (`Write-Error`, mit `-ErrorAction SilentlyContinue`
unterdrückbar).

## Kompatibilität

Windows PowerShell 5.1 und PowerShell 7 (`CompatiblePSEditions = Desktop, Core`). Die Moduldateien
sind UTF-8 mit BOM gespeichert, weil Windows PowerShell 5.1 Umlaute sonst falsch liest.
