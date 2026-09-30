"""Auto-Update der installierten App (Verteilung über Python).

Ablauf: Quelle prüfen (`sources`), Manifest mit Ed25519 prüfen (`signing`, `manifest`: Version,
Kanal und Lock-Liste mit SHA-256 aller Wheels), neue Python-Umgebung `versions/<v>` mit dem
Basis-Python der Installation anlegen und darin `pip install --require-hashes --only-binary=:all:
-r lock.txt` plus Selbsttest (`tapesmith.install.venv`), Umschalten im Leerlauf mit
Gesundheitsprüfung und Rückfall (`apply`). `service` bündelt das für API, CLI und Addon, `state`
hält den Zustand in `<App-Verzeichnis>/update/state.json`.

Qt-frei wie der ganze Kern (siehe `tests/test_update_service.py`)."""
