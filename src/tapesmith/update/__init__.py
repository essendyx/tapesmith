"""Auto-Update der installierten App.

Ablauf: Quelle prüfen (`sources`), Manifest mit Ed25519 prüfen (`signing`, `manifest`), Paket laden
und Prüfsumme vergleichen (`download`), nach `versions/<v>.staging` entpacken und Selbsttest
(`stage`), Umschalten im Leerlauf mit Gesundheitsprüfung und Rückfall (`apply`). `service` bündelt
das für API, CLI und Addon, `state` hält den Zustand in `<App-Verzeichnis>/update/state.json`.

Qt-frei wie der ganze Kern (siehe `tests/test_update_service.py`)."""
