"""Verzeichnis-Junction `current`: braucht kein Adminrecht.

`switch_junction` stellt `link` auf ein neues Ziel um, ohne den Inhalt des alten Ziels zu
löschen: erst `link.new` anlegen, dann den alten Link (nur die Verknüpfung, `os.rmdir`)
entfernen, dann umbenennen. Nie `shutil.rmtree` auf einen Link."""

from __future__ import annotations

import _winapi
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from tapesmith.i18n import _t


def create_junction(link: Path, target: Path, *,
                    runner: Callable[..., "subprocess.CompletedProcess"] | None = None) -> None:
    """Legt `link` als Verzeichnis-Junction auf `target` an. `target` muss existieren."""
    link = Path(link)
    target = Path(target)
    if not target.is_dir():
        raise ValueError(_t("Verknüpfungsziel fehlt oder ist kein Ordner: {target}", target=target))
    create = getattr(_winapi, "CreateJunction", None)
    if create is not None:
        create(str(target), str(link))
        return
    run = runner or subprocess.run
    result = run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, text=True)
    if result.returncode != 0:
        text = (result.stdout or "") + (result.stderr or "")
        raise OSError(_t("mklink /J fehlgeschlagen: {strip}", strip=text.strip()))


def read_junction(link: Path) -> Path | None:
    """Ziel der Junction, oder `None`, wenn `link` keine Verknüpfung ist."""
    try:
        raw = os.readlink(link)
    except OSError:
        return None
    text = str(raw)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return Path(text)


def switch_junction(link: Path, target: Path, *,
                    runner: Callable[..., "subprocess.CompletedProcess"] | None = None) -> None:
    """Stellt `link` auf `target` um: `link.new` anlegen (vorherigen Rest entfernen), alten
    Link mit `os.rmdir` entfernen (nur die Verknüpfung, nie den Inhalt des Ziels), dann
    `os.replace`. Existiert `link` noch nicht, entspricht das einer Neuanlage."""
    link = Path(link)
    new_link = link.with_name(link.name + ".new")
    if new_link.exists() or read_junction(new_link) is not None:
        try:
            os.rmdir(new_link)
        except OSError:
            if new_link.is_file():
                new_link.unlink()
            else:
                import shutil
                shutil.rmtree(new_link)
    create_junction(new_link, target, runner=runner)
    if link.exists() or read_junction(link) is not None:
        os.rmdir(link)
    os.replace(new_link, link)
