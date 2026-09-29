"""Einstieg für den portablen Build (PyInstaller/Nuitka): eine EXE für alle Prozessarten.

`Tapesmith.exe --daemon …` startet den Druckdienst p12d, `Tapesmith.exe --tray …` die Tray-App,
`Tapesmith.exe --install …`/`--uninstall …` den Installer bzw. Deinstaller, `--update-apply
…` wendet ein geladenes Update an, `Tapesmith.exe --selftest [--selftest-out DATEI]` den
Qt-freien Selbsttest. `--app …` und alles andere (nichts, `--uri URI`, `--open AKTION --path
PFAD`) öffnet die Web-Oberfläche im Standardbrowser (`webui.browser.main`, Fehler ins Log
`logs/app.log` plus Exit-Code, nie als Fenster). Die Imports sind absichtlich spät: der
Druckdienst lädt so kein Qt, der Browserstart kein Qt und keinen Druckdienst-Code.
"""

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--daemon":
        from tapesmith.daemon import instance

        return instance.main(args[1:])
    if args and args[0] == "--tray":
        from tapesmith.gui import tray

        return tray.main(args[1:])
    if args and args[0] == "--install":
        from tapesmith.install import installer

        return installer.main(args[1:])
    if args and args[0] == "--uninstall":
        from tapesmith.install import uninstaller

        return uninstaller.main(args[1:])
    if args and args[0] == "--update-apply":
        # Updater-Modul erst hier importieren, damit die Weiche ohne es lädt.
        import importlib

        apply = importlib.import_module("tapesmith.update.apply")
        return apply.main(args[1:])
    if "--selftest" in args:
        from tapesmith import selftest

        return selftest.main(args)
    from tapesmith.webui import browser

    if args and args[0] == "--app":
        args = args[1:]
    return browser.main(args)


if __name__ == "__main__":
    sys.exit(main())
