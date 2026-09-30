# Web-Oberfläche (web/)

React 18, TypeScript (strict), Vite, Fluent UI React v9. Der Build landet in `src/tapesmith/webui/static/` und wird eingecheckt, damit Laufzeit und Python-Paket (Wheel) kein Node brauchen.

## Befehle

| Befehl | Zweck |
|---|---|
| `npm ci` | Pakete nach `package-lock.json` installieren |
| `npm run check` | Typprüfung, ESLint (ohne Warnungen), Vitest |
| `npm run build` | Typprüfung und Build nach `../src/tapesmith/webui/static` |
| `npm run build:check` | Probe-Build nach `node_modules/.p12-build-check` (nie committen) |
| `npm run dev` | Vite-Entwicklungsserver mit Proxy auf einen laufenden Druckdienst |

Aus dem Repo-Stamm baut `python tools/build_web.py [--install] [--skip-check]` alles in einem Schritt und prüft das Ergebnis.

## Entwicklungsserver

`npm run dev` braucht das Ziel des Druckdienstes in `P12_DEV_API`; einen fest eingebauten Port gibt es nicht (sonst träfe der Proxy den echten Dienst des Users).

1. Dienst mit eigenem Temp-Home und freiem Port starten:
   `TAPESMITH_HOME=%TEMP%\p12-dev` und `TAPESMITH_WEB_PORT=0`, dann `python -m tapesmith.daemon`.
2. Port und Token aus `<TAPESMITH_HOME>\web\session.json` lesen (`"port"`, `"token"`).
3. `P12_DEV_API=http://127.0.0.1:<port>` setzen und `npm run dev` starten.
4. Die Dev-URL mit angehängtem Token öffnen: `http://localhost:5173/#t=<token>`.

Der Proxy leitet `/api` und `/health` weiter und setzt den `Origin`-Header auf das Ziel, sonst lehnt der Dienst POST-Anfragen ab.

## Tests

Vitest mit jsdom und Testing Library. Hilfen in `src/test/`: `mockApi` (Fetch-Stub, `quiet: true` für Rahmen-Tests), `renderWithProviders`, `LocationProbe`, `FakeEventSource`, `fixtures`. Tests rufen nie das echte Netz auf.

## Seiten Zugriff und Familie

- **Zugriff** (`/zugriff`, `src/pages/Zugriff/`): Karten für LAN-Freigabe, API-Tokens (Anlegen mit einmaliger Anzeige des Klartexts, Widerruf, Familienlinks), Familie, MCP, Hotfolder, MQTT, Telegram und den Status der Zusatzdienste. Spricht nur `/api/v1/access...` an (Rolle `admin`).
- **Familie** (`/familie`, `src/pages/Familie/`): eigenständige Handy-Seite außerhalb der normalen Oberfläche (`main.tsx` wählt sie über `isFamilyPath`). Eigener HTTP-Client (`familyClient.ts`) mit eigenem Token-Speicher in `localStorage`; das Token kommt aus dem Link `…/familie#t=<Token>` und wird nie als Admin-Sitzung (`sessionStorage` `p12.token`) abgelegt. Spricht nur `/api/v1/familie/...` an; der Build erzeugt dafür den Chunk `FamilyApp-*.js`.

Beide Seiten nutzen die JSON-Typen `AccessJson`, `FamilyTemplate`, `FamilyPreview` und `FamilyPrintResult`; Tests in `Zugriff.test.tsx`, `Familie.test.tsx` und `familyClient.test.ts`.
