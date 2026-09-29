"""Band-Eignung: prüft die in einer Vorlage hinterlegten Bänder gegen das eingelegte."""

from __future__ import annotations

from collections.abc import Sequence

from tapesmith.tape.profiles import MATERIALS, TapeProfile, find_tape, list_tapes
from tapesmith.i18n import N_, _t

_MATERIAL_NAMES = {"kunststoff": N_("Kunststoffband"), "papier": N_("Papierband"), "textil": N_("Textilband")}


def is_suitable(tape: TapeProfile, allowed: Sequence[str]) -> bool:
    """`allowed` leer -> immer geeignet. Sonst True, wenn irgendein Eintrag passt:
    Band-id, "material:<m>", "transparent", "dunkel", "hell"."""
    if not allowed:
        return True
    for entry in allowed:
        if entry == tape.id:
            return True
        if entry.startswith("material:") and entry.split(":", 1)[1] == tape.material:
            return True
        if entry == "transparent" and tape.transparent:
            return True
        if entry == "dunkel" and tape.dark:
            return True
        if entry == "hell" and not tape.dark:
            return True
    return False


def _describe(entry: str) -> str:
    if entry.startswith("material:"):
        material = entry.split(":", 1)[1]
        if material in _MATERIAL_NAMES:
            return _t(_MATERIAL_NAMES[material])
        return _t("Band ({material})", material=material)
    if entry == "transparent":
        return _t("transparentes Band")
    if entry == "dunkel":
        return _t("dunkles Band")
    if entry == "hell":
        return _t("helles Band")
    return find_tape(entry).name


def suitability_reason(template_name: str, tape: TapeProfile, allowed: Sequence[str]) -> str | None:
    """`None`, wenn `tape` geeignet ist; sonst eine deutsche Meldung mit den erlaubten Bändern."""
    if is_suitable(tape, allowed):
        return None
    beschreibung = " oder ".join(_describe(e) for e in allowed)
    return _t("Vorlage '{template_name}' ist für {beschreibung} gedacht, eingelegt: {name}", template_name=template_name, beschreibung=beschreibung, name=tape.name)


def validate_allowed(entries: Sequence[str]) -> None:
    """Für die Vorlagen-Validierung: unbekannte id/Form -> `ValueError`."""
    ids = {t.id for t in list_tapes()}
    for entry in entries:
        if entry in ("transparent", "dunkel", "hell"):
            continue
        if entry.startswith("material:"):
            material = entry.split(":", 1)[1]
            if material in MATERIALS:
                continue
            raise ValueError(_t("Unbekanntes Material '{material}' in Bandregel '{entry}'", material=material, entry=entry))
        if entry in ids:
            continue
        raise ValueError(
            _t("Unbekannte Bandregel '{entry}' (Band-id, 'material:<m>', 'transparent', 'dunkel' oder 'hell')", entry=entry))
