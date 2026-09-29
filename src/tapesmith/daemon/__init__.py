"""Druckdienst p12d.

Qt-freier Hintergrundprozess im Benutzerkontext, einzige Instanz je Benutzer und App-Verzeichnis
(`instance.SingleInstance`, Named Mutex) und alleiniger Inhaber der Druckerverbindung:

- `service.PrintService`: führt Aufträge nacheinander über Pipeline + ConnectionManager aus,
  reiht Offline-Aufträge ein, Status/Zustand, Reservierung (Lease), Neuladen der Konfiguration.
- `runner.QueueRunner`: Nachdruck wartender Aufträge (Backoff, Probe, Deckel, Lease, Pause).
- `server.DaemonServer`: Named-Pipe-Server nach Protokoll v1, Ereignisse an alle Clients.
- `instance`: `run_daemon`/`main` (`python -m tapesmith.daemon`), Leerlauf-Ende, Tagessicherung.
- `queue`, `probe`: Warteschlange (SQLite) und Erreichbarkeits-Logik.
"""
