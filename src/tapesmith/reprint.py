""""Erneut drucken" aus dem Verlauf als Kern-API.

Nicht sensible Einträge werden aus dem gespeicherten Kopfbild gedruckt; Kopien, Kette und
Jobaufteilung plant die Pipeline wieder genauso wie beim Original. Sensible Vorlagen-Einträge
haben kein Kopfbild; ihre verdeckten Felder müssen neu eingegeben werden (`sets`). Dasselbe gilt
für WLAN-QRs mit Passwort ohne Vorlage (QR-Seite, `tapesmith qr wifi`): SSID, Sicherheitsart und Layout
stehen im Verlauf, das Passwort wird als Feld `password` neu eingegeben.

Kein Qt, kein argparse, kein `cli_cmds`: die CLI (`cli_cmds/reprint.py`) und die Web-API
nutzen nur `load_entry`/`prepare_reprint`.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from tapesmith import config, numbering, paths
from tapesmith.device.profile import DeviceProfile
from tapesmith.document.render import render_spec
from tapesmith.history import HistoryEntry, HistoryStore
from tapesmith.jobs import JobMeta, spec_from_dict
from tapesmith.labelmeta import qr_meta
from tapesmith.pipeline import PrintLabel, labels_from_result
from tapesmith.render.compose import RenderResult
from tapesmith.render.qrcontent import wifi_content
from tapesmith.tape.profiles import TapeProfile, current_tape
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.model import TemplateError
from tapesmith.templates.render import render_meta, render_template
from tapesmith.templates.store import find_template
from tapesmith.i18n import _t

CURRENT_TAPE = object()  # Sentinel: „eingelegtes Band aus der Konfiguration"


class MissingSecrets(TemplateError):
    def __init__(self, fields: tuple[str, ...]):
        if len(fields) == 1:
            message = _t("Feld '{value}' ist sensibel und muss neu eingegeben werden", value=fields[0])
        else:
            names = ", ".join(f"'{f}'" for f in fields)
            message = _t("Felder {names} sind sensibel und müssen neu eingegeben werden", names=names)
        super().__init__(message)
        self.fields = fields


@dataclass(frozen=True)
class ReprintJob:
    entry: HistoryEntry
    labels: tuple[PrintLabel, ...]
    meta: JobMeta
    copies: int
    chain: bool
    from_image: bool                   # True: gespeichertes Kopfbild; False: Vorlage neu gefüllt
    result: RenderResult | None        # nur bei Vorlage
    counter_keys: tuple[str, ...]      # nach erfolgreichem Druck committen
    counters: CounterStore | None

    def commit_counters(self) -> None:
        if self.counters is None:
            return
        for key in self.counter_keys:
            self.counters.commit(key)


def load_entry(store: HistoryStore, target: str | int) -> HistoryEntry:
    """Löst 'last' oder eine Verlaufs-ID (int oder Ziffern-Zeichenkette) zum Verlaufseintrag auf."""
    if target == "last":
        entry = store.last()
        if entry is None:
            raise ValueError(_t("Verlauf ist leer, nichts zum Nachdrucken"))
        return entry
    if isinstance(target, int) or (isinstance(target, str) and target.isdigit()):
        entry_id = int(target)
        try:
            return store.get(entry_id)
        except KeyError as exc:
            raise ValueError(_t("Verlaufseintrag {entry_id} gibt es nicht", entry_id=entry_id)) from exc
    raise ValueError(_t("'{target}' ist weder 'last' noch eine Verlaufs-ID", target=target))


def missing_secret_fields(store: HistoryStore, entry: HistoryEntry) -> tuple[str, ...]:
    """Sensible Vorlagenfelder, die vor dem Nachdruck neu eingegeben werden müssen (leer bei Kopfbild)."""
    return store.reprint_source(entry.id).missing


def _default_counters() -> CounterStore:
    """Zentrale Zähler (`numbering.counter_store`); ungültige Config -> bisheriger Pfad."""
    try:
        return numbering.counter_store(config.load_config())
    except Exception:  # noqa: BLE001
        return CounterStore(paths.app_dir() / "counters.json")


def prepare_reprint(store: HistoryStore, entry: HistoryEntry, profile: DeviceProfile, *,
                    sets: dict[str, str] | None = None, copies: int | None = None,
                    chain: bool | None = None, source: str = "cli",
                    now: Callable[[], datetime] = datetime.now,
                    counters: CounterStore | None = None,
                    tape: "TapeProfile | None | object" = CURRENT_TAPE) -> ReprintJob:
    """Bereitet den Nachdruck eines Verlaufseintrags vor (ohne zu drucken)."""
    sets = sets or {}
    copies = copies if copies is not None else entry.copies
    chain = chain if chain is not None else entry.chained
    prefix = _t("Nachdruck #{id}: ", id=entry.id)
    src = store.reprint_source(entry.id)
    if tape is CURRENT_TAPE:
        tape = current_tape(config.load_config())

    if src.kind == "head":
        meta = JobMeta(source=source, kind="reprint", title=prefix + entry.title, template=entry.template,
                       values=entry.values, sensitive=entry.sensitive, spec=entry.spec)
        return ReprintJob(entry=entry, labels=(PrintLabel(src.head),), meta=meta, copies=copies,
                          chain=chain, from_image=True, result=None, counter_keys=(), counters=None)

    if src.kind == "qr-wifi":
        return _prepare_wifi_reprint(entry, src.values, sets, profile, copies=copies, chain=chain,
                                     prefix=prefix, source=source, tape=tape)

    template = find_template(src.template)
    missing = tuple(field_id for field_id in src.missing if field_id not in sets)
    if missing:
        raise MissingSecrets(missing)
    input_ids = {f.id for f in template.fields if f.type == "input"}
    inputs = {k: v for k, v in (src.values | sets).items() if k in input_ids}
    counters = counters or _default_counters()
    resolved = resolve_values(template, inputs, now(), counters)
    tr = render_template(template, resolved.values, profile, tape=tape)
    meta = render_meta(tr, kind="reprint", title_prefix=prefix, source=source)
    return ReprintJob(entry=entry, labels=labels_from_result(tr.result), meta=meta, copies=copies,
                      chain=chain, from_image=False, result=tr.result,
                      counter_keys=resolved.counter_keys, counters=counters)


def _prepare_wifi_reprint(entry: HistoryEntry, values: dict[str, str], sets: dict[str, str],
                          profile: DeviceProfile, *, copies: int, chain: bool, prefix: str,
                          source: str, tape: TapeProfile | None = None) -> ReprintJob:
    password = sets.get("password")
    if not password:
        raise MissingSecrets(("password",))
    content = wifi_content(values["ssid"], password, security=values["security"],
                           hidden=values["hidden"] == "ja")
    layout = json.loads(values["qr_spec"])
    layout["qr"] = content.data
    spec = spec_from_dict(layout)
    result = render_spec(spec, profile, tape)
    meta = qr_meta(content, spec.lines, source=source, spec=spec, kind="reprint", title_prefix=prefix)
    return ReprintJob(entry=entry, labels=labels_from_result(result), meta=meta, copies=copies,
                      chain=chain, from_image=False, result=result, counter_keys=(), counters=None)
