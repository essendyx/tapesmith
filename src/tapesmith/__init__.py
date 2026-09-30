"""Tapesmith: label studio for the Phomemo P12."""

import os

__version__ = "0.4.1"

# Bis 0.2.x hieß die App "P12 Label" und las Umgebungsvariablen mit dem Präfix P12LABEL_.
# Alte Namen gelten weiter als Rückfall: ist TAPESMITH_X nicht gesetzt, übernimmt es den Wert
# von P12LABEL_X. Das geschieht einmal beim Import des Pakets, also vor jedem Lesezugriff.
LEGACY_ENV_PREFIX = "P12LABEL_"
ENV_PREFIX = "TAPESMITH_"


def apply_legacy_env(environ=None) -> list[str]:
    """Kopiert gesetzte `P12LABEL_*`-Variablen nach `TAPESMITH_*`, sofern dort nichts steht.
    Gibt die übernommenen neuen Namen zurück."""
    env = os.environ if environ is None else environ
    taken = []
    for key in list(env):
        if key.upper().startswith(LEGACY_ENV_PREFIX):
            new = ENV_PREFIX + key[len(LEGACY_ENV_PREFIX):].upper()
            if new not in env:
                env[new] = env[key]
                taken.append(new)
    return taken


apply_legacy_env()
