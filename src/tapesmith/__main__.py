"""`python -m tapesmith …`: Einstieg ohne eigene EXE.

`install` und `uninstall` gehen direkt an Installer bzw. Deinstallation (ohne den restlichen
CLI-Unterbau zu laden, so läuft die Deinstallation auch unter `pythonw.exe` ohne Konsole); alles
andere ist die normale Kommandozeile (`tapesmith.cli`)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "install":
        from tapesmith.install import installer

        return installer.main(args[1:])
    if args and args[0] == "uninstall":
        from tapesmith.install import uninstaller

        return uninstaller.main(args[1:])
    from tapesmith import cli

    return cli.main(args)


if __name__ == "__main__":
    sys.exit(main())
