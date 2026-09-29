"""Ein-Klick-Korrekturvorschläge als Kern-API.

Zu einer :class:`LabelSpec`, die Probleme hat (Ausnahme aus `render_label` oder
Warnungen aus `render/checks.py`), werden konkrete, bereits geprüfte Korrekturen
berechnet: verkleinern, Länge erhöhen, kürzen, QR-Fehlerkorrektur senken,
zentrieren. Jeder zurückgegebene Vorschlag rendert garantiert fehlerfrei.
Seiteneffektfrei und deterministisch, keine GUI, keine CLI hier.
"""

import dataclasses
from dataclasses import dataclass

from tapesmith.device.profile import DeviceProfile
from tapesmith.render.checks import LONG_LABEL_MM, is_small_font_warning
from tapesmith.render.compose import LabelSpec, RenderResult, render_label
from tapesmith.i18n import _t

FIX_IDS = ("verkleinern", "laenger", "kuerzen", "qr_ecc_l", "zentrieren")
ELLIPSIS = "…"

_MIN_KEPT_CHARS = 1


@dataclass(frozen=True)
class Fix:
    id: str
    title: str
    spec: LabelSpec
    result: RenderResult


@dataclass(frozen=True)
class Diagnosis:
    ok: bool
    error: str | None
    warnings: tuple[str, ...]
    result: RenderResult | None


def diagnose(spec: LabelSpec, profile: DeviceProfile) -> Diagnosis:
    try:
        result = render_label(spec, profile)
    except ValueError as exc:
        return Diagnosis(ok=False, error=str(exc), warnings=(), result=None)
    warnings = tuple(result.warnings)
    return Diagnosis(ok=not warnings, error=None, warnings=warnings, result=result)


def _has_font_warning(warnings) -> bool:
    return any(is_small_font_warning(w) for w in warnings)


def _has_problem(diag: Diagnosis) -> bool:
    return diag.error is not None or bool(diag.warnings)


def _better(baseline: Diagnosis, candidate: Diagnosis) -> bool:
    """Der Kandidat rendert fehlerfrei und ist strikt besser als der Ausgangszustand."""
    if candidate.error is not None:
        return False
    if baseline.error is not None:
        return True
    return len(candidate.warnings) < len(baseline.warnings)


def _find_verkleinern(spec: LabelSpec, profile: DeviceProfile, baseline: Diagnosis) -> Fix | None:
    if spec.font_size is None or not _has_problem(baseline):
        return None
    candidate_spec = dataclasses.replace(spec, font_size=None)
    diag = diagnose(candidate_spec, profile)
    if not _better(baseline, diag):
        return None
    return Fix("verkleinern", _t("Schrift automatisch anpassen (verkleinern)"), candidate_spec, diag.result)


def _find_laenger(spec: LabelSpec, profile: DeviceProfile, baseline: Diagnosis) -> Fix | None:
    if spec.fixed_length_mm is not None:
        field = "fixed_length_mm"
    elif spec.max_length_mm is not None:
        field = "max_length_mm"
    else:
        return None
    error_from_length = baseline.error is not None and "passt nicht" in baseline.error
    if not (error_from_length or _has_font_warning(baseline.warnings)):
        return None

    current = getattr(spec, field)
    lo = int(current) + 1
    hi = int(LONG_LABEL_MM)
    if lo > hi:
        return None

    def ok_at(length: int) -> Diagnosis:
        candidate = dataclasses.replace(spec, **{field: length})
        return diagnose(candidate, profile)

    hi_diag = ok_at(hi)
    if hi_diag.error is not None or _has_font_warning(hi_diag.warnings):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        mid_diag = ok_at(mid)
        if mid_diag.error is None and not _has_font_warning(mid_diag.warnings):
            hi = mid
        else:
            lo = mid + 1
    final_diag = ok_at(lo)
    candidate_spec = dataclasses.replace(spec, **{field: lo})
    return Fix("laenger", _t("Länge auf {lo} mm erhöhen", lo=lo), candidate_spec, final_diag.result)


def _find_kuerzen(spec: LabelSpec, profile: DeviceProfile, baseline: Diagnosis) -> Fix | None:
    originals = list(spec.lines)
    if not any(line.strip() for line in originals) or not _has_problem(baseline):
        return None

    kept = [len(line) for line in originals]
    current = list(originals)

    def shortenable_indices():
        return [i for i, line in enumerate(originals) if line.strip() and kept[i] > _MIN_KEPT_CHARS]

    attempts = 0
    while attempts < 200:
        candidates = shortenable_indices()
        if not candidates:
            return None
        idx = max(candidates, key=lambda i: len(current[i]))
        kept[idx] -= 1
        current[idx] = originals[idx][:kept[idx]] + ELLIPSIS
        attempts += 1
        candidate_spec = dataclasses.replace(spec, lines=tuple(current))
        diag = diagnose(candidate_spec, profile)
        if diag.error is None and not _has_font_warning(diag.warnings):
            changed = [i for i in range(len(originals)) if kept[i] < len(originals[i])]
            longest_changed = max(changed, key=lambda i: len(current[i]))
            title = _t("Text kürzen: „{value}“", value=current[longest_changed])
            return Fix("kuerzen", title, candidate_spec, diag.result)
    return None


def _find_qr_ecc_l(spec: LabelSpec, profile: DeviceProfile, baseline: Diagnosis) -> Fix | None:
    if not spec.qr or spec.qr_error.lower() == "l":
        return None
    rejected = baseline.error is not None and "QR-Inhalt passt nicht lesbar" in baseline.error
    warned = baseline.result is not None and baseline.result.qr is not None and bool(baseline.result.qr.warnings)
    if not (rejected or warned):
        return None
    candidate_spec = dataclasses.replace(spec, qr_error="l")
    diag = diagnose(candidate_spec, profile)
    if not _better(baseline, diag):
        return None
    return Fix("qr_ecc_l", _t("QR-Fehlerkorrektur auf L senken (kleinerer Code)"), candidate_spec, diag.result)


def _find_zentrieren(spec: LabelSpec, profile: DeviceProfile, baseline: Diagnosis) -> Fix | None:
    if spec.fixed_length_mm is None or spec.align == "center":
        return None
    candidate_spec = dataclasses.replace(spec, align="center")
    diag = diagnose(candidate_spec, profile)
    if diag.error is not None:
        return None
    return Fix("zentrieren", _t("Inhalt zentrieren"), candidate_spec, diag.result)


_FINDERS = (
    _find_verkleinern,
    _find_laenger,
    _find_kuerzen,
    _find_qr_ecc_l,
    _find_zentrieren,
)


def suggest_fixes(spec: LabelSpec, profile: DeviceProfile) -> list[Fix]:
    baseline = diagnose(spec, profile)
    fixes = []
    for finder in _FINDERS:
        fix = finder(spec, profile, baseline)
        if fix is not None:
            fixes.append(fix)
    return fixes


def apply_fix(spec: LabelSpec, profile: DeviceProfile, fix_id: str) -> Fix:
    if fix_id not in FIX_IDS:
        raise ValueError(_t("Unbekannte Korrektur '{fix_id}' (möglich: {items})", fix_id=fix_id, items=', '.join(FIX_IDS)))
    for fix in suggest_fixes(spec, profile):
        if fix.id == fix_id:
            return fix
    raise ValueError(_t("Korrektur '{fix_id}' passt hier nicht", fix_id=fix_id))
