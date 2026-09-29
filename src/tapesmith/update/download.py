"""Prüfung eines geladenen Update-Pakets gegen das (signierte) Manifest: Größe und SHA-256."""

from __future__ import annotations

from pathlib import Path

from tapesmith.update.errors import UpdateError
from tapesmith.update.manifest import Manifest, file_sha256
from tapesmith.i18n import _t


def verify_package(path: Path, manifest: Manifest) -> Path:
    """`update.checksum_mismatch`, wenn Größe oder SHA-256 nicht zum Manifest passen."""
    path = Path(path)
    size = path.stat().st_size
    if size != manifest.size:
        raise UpdateError("update.checksum_mismatch",
                          _t("Paket {file}: Größe {size} statt {size2} Bytes", file=manifest.file, size=size, size2=manifest.size),
                          hint=_t("Download beschädigt. Erneut nach Updates suchen."))
    digest = file_sha256(path)
    if digest != manifest.sha256:
        raise UpdateError("update.checksum_mismatch", _t("Paket {file}: SHA-256 passt nicht zum Manifest", file=manifest.file),
                          hint=_t("Download beschädigt. Erneut nach Updates suchen."))
    return path
