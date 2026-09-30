"""Installation ohne Adminrechte und ohne eigene EXE: je Version eine Python-Umgebung
(`venv`), Junction `current`, Startmenü, Apps & Features, Deinstallation. Qt-frei, wie der ganze
Kern (siehe `tests/test_install_no_qt.py`).

Grundlage für den Updater: `venv.provision`, `installer.activate`, `installer.register_version`,
`installer.prune`, `processes.processes_under`, `processes.stop_daemon`."""
