# Kurz-Link-Redirect-Dienst

Eigenständiger, containerisierter Dienst für kurze, alphanumerische Umleitungen.
`GET /<ID>` leitet per HTTP 302 auf ein hinterlegtes Ziel um, geeignet für kompakte QR-Codes im
Alphanumerik-Modus (Großbuchstaben, Ziffern, Bindestrich). Daten liegen in SQLite unter `/data`.
Der Dienst kennt `tapesmith` nicht und hat eigene Abhängigkeiten (`requirements.txt`).

## API

IDs folgen dem Muster `^[0-9A-Z][0-9A-Z-]{0,15}$`. Eingehende Pfade werden vor dem Nachschlagen in
Großbuchstaben gewandelt (`/hl-0042` findet `HL-0042`). Automatisch vergebene IDs zählen fortlaufend
in Basis 36 hoch (`1`, `2`, … `9`, `A`, … `Z`, `10`, …), vorhandene IDs werden übersprungen.

| Methode Pfad | Token | Zweck |
|---|---|---|
| GET `/health` | nein | `{"ok": true, "links": <Anzahl>, "version": "1"}`, bei Datenbankfehler 503 |
| GET/HEAD `/<ID>` | nein | Ziel gesetzt: 302 auf das Ziel (zählt `hits` nur bei GET). Kein Ziel: 200 Hinweisseite. Unbekannt/ungültig: 404 |
| POST `/api/links` | ja | `{"target": str\|null, "id"?: str, "note"?: str}` -> 201 Link. ID vergeben: 409. Ungültig: 422 |
| PUT `/api/links/{id}` | ja | `{"target": str\|null, "note"?: str}` -> 200 (geändert) bzw. 201 (neu). `note` fehlt: bleibt unverändert |
| GET `/api/links` | ja | `{"links": [Link, ...]}`, sortiert nach ID |
| GET `/api/links/{id}` | ja | Link bzw. 404 |
| DELETE `/api/links/{id}` | ja | 204 bzw. 404 |

Ein `Link` (`LinkJson`) hat die Felder `id`, `target`, `note`, `created`, `updated`, `hits`
(Zeiten als ISO UTC mit `Z`, Sekundenauflösung).

Die Admin-API unter `/api/` verlangt den Header `Authorization: Bearer <SHORTLINK_ADMIN_TOKEN>`.
Ist kein Token gesetzt oder kürzer als 24 Zeichen, antwortet die Admin-API auf jede Anfrage mit
503 „Admin-Token nicht gesetzt“. Bei fehlendem oder falschem Token: 401 `{"error": "Nicht angemeldet"}`.

Ziele müssen mit `http://` oder `https://` beginnen, dürfen höchstens 2000 Zeichen lang sein und
keine Leerzeichen, Steuerzeichen oder `javascript:` enthalten. Notizen sind höchstens 200 Zeichen lang.

Sicherheitsheader auf allen Antworten: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`. Keine CORS-Header. Kein `/docs`, `/redoc`, `/openapi.json`.

## Umgebungsvariablen

| Variable | Standard | Zweck |
|---|---|---|
| `SHORTLINK_DB` | `/data/shortlink.sqlite3` | Pfad zur SQLite-Datenbank |
| `SHORTLINK_ADMIN_TOKEN` | (leer) | Admin-Token, mindestens 24 Zeichen |
| `SHORTLINK_PORT` | `8000` | Port für uvicorn im Container |

## Deployment (Beispiel für einen Docker-Host im Heimnetz)

1. Einen Ordner wie `/opt/shortlink/` anlegen und dieses Verzeichnis dorthin kopieren.
2. `.env` aus `.env.example` anlegen: Admin-Token mit `openssl rand -hex 32` erzeugen, in `.env`
   eintragen (nie committen) und einen freien Port als `SHORTLINK_HOST_PORT` wählen. Denselben
   Token beim Tapesmith-Client als Secret-Referenz in `shortlink.token_ref` hinterlegen (Windows
   Credential Manager oder eine Datei außerhalb jedes Repos).
3. `docker compose up -d --build` im Ordner.
4. Optional öffentlich erreichbar machen, z. B. über einen Reverse-Proxy oder Tunnel mit eigener
   Subdomain (etwa `l.example.com`). Die Admin-API unter `/api/*` dabei zusätzlich absichern (z. B.
   mit einer Anmeldung vor dem Proxy); die Redirect-Pfade (`/<ID>`) und `/health` bleiben ohne
   Anmeldung erreichbar. Aus dem LAN ist die Admin-API über `http://<Docker-Host>:<SHORTLINK_HOST_PORT>`
   erreichbar.
5. Optional einen Uptime-Monitor auf `/health` anlegen (HTTP, erwartet 200 und `"ok":true`).
6. Backup: Die Datenbank liegt im Named Volume `shortlink-data` (Compose-Projekt `shortlink`, also
   Volume `shortlink_shortlink-data`), nicht in einem Ordner neben `compose.yaml`. Kein Bind-Mount
   verwenden: der Container läuft als uid 1000, ein von Docker angelegter Host-Ordner gehört root
   und SQLite kann die Datenbank dann nicht anlegen. Sichern z. B. mit
   `docker compose exec shortlink python -c "import sqlite3; s=sqlite3.connect('/data/shortlink.sqlite3'); s.backup(sqlite3.connect('/data/backup.sqlite3'))"`
   und `docker compose cp shortlink:/data/backup.sqlite3 ./shortlink-backup.sqlite3`.
7. In `homelab.json` des Tapesmith-Clients `shortlink.base_url` (öffentliche Adresse) und
   `shortlink.admin_url` (LAN-Adresse) setzen.

## Beispiel

```bash
curl -X POST https://l.example.com/api/links \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"target": "https://example.com/ziel", "id": "HL-0001", "note": "Testgeraet"}'
```

## Entwicklung

```
pip install -r requirements.txt
SHORTLINK_ADMIN_TOKEN=$(openssl rand -hex 32) SHORTLINK_DB=./dev.sqlite3 \
  uvicorn shortlink:factory --factory --reload
```

Tests: `tests/test_shortlink_service.py` im Tapesmith-Repo (eigenes venv, `fastapi`/`uvicorn` reichen aus).
