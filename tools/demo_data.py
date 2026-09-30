"""Demo-Daten für Screenshots und Rauchtest.

`seed_demo` füllt ein frisches `TAPESMITH_HOME` mit realistischen, aber frei erfundenen Daten:
Konfiguration (Datei-Transport, Band, Favoriten, ein SSH-Beispielhost), Verlauf (mit echten
Miniaturen aus echten Renderns), Warteschlange (zwei wartende Aufträge), Inventar (Boxen,
Gegenstände, ein überfälliger Verleih), Rollen (eine beendete, eine laufende) und zwei Dokumente
in der Editor-Dokumentablage. Es wird nie gedruckt und nie ein echtes Gerät geöffnet (Transport
`file:<home>\\job.bin`).

`seed_orphaned_drafts` legt zwei verwaiste Entwürfe (Sitzung `demo-fenster`) für die Aufnahme
der Wiederherstellung an, `reset_drafts` leert den Entwurfsordner vor jeder Aufnahme.

`seed_demo` setzt selbst keine Umgebungsvariable: der Aufrufer hat `TAPESMITH_HOME=home` bereits
gesetzt (so lesen `paths.app_dir()` und alle Stores automatisch aus `home`).

`lang` wählt die Sprache der Demo-Inhalte (`DEMO_TEXTS`, Deutsch oder Englisch): Texte im Verlauf,
Inventar, Dokumente und Entwürfe sind Nutzerdaten und bleiben in der Sprache, in der sie angelegt
wurden; Vorlagen rendern in der Sprache des Aufrufs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from tapesmith import config as config_mod, numbering, paths
from tapesmith.calibrate import edge_test_head, ruler_content
from tapesmith.i18n import _t
from tapesmith import modules
from tapesmith.daemon.queue import JobQueue
from tapesmith.device.profile import DeviceProfile, load_profile
from tapesmith.document.model import IconObject, LabelDocument, QrObject, RectObject, TextObject, document_to_dict
from tapesmith.history import HistoryStore
from tapesmith.inventory import InventoryStore
from tapesmith.ipc.codec import encode_request
from tapesmith.jobs import JobMeta
from tapesmith.labelmeta import qr_meta, text_meta
from tapesmith.pipeline import PrintLabel, PrintRequest
from tapesmith.protocol.raster import place_on_head
from tapesmith.render.compose import LabelSpec, RenderResult, render_label
from tapesmith.render.qrcontent import url_content, wifi_content
from tapesmith.tape.profiles import TapeProfile, current_tape
from tapesmith.tape.rolls import RollStore
from tapesmith.templates.fill import resolve_values
from tapesmith.templates.render import TemplateRender, render_meta, render_template
from tapesmith.templates.store import find_template
from tapesmith.webapi.documents import save_document
from tapesmith.webapi.drafts import DRAFTS_DIR_NAME, DraftStore

TAPE_ID = "schwarz-weiss"
DOCUMENT_NAME = "Demo Serverschrank"
SECOND_DOCUMENT_NAME = "Demo Kabelfach"
DRAFT_SESSION = "demo-fenster"
BOX_MAIN = "BOX-07"
BOX_SECONDARY = "BOX-12"
FAVORITES = ("datentraeger", "kabelfahne")

# Demo-Inhalte je Sprache (Nutzerdaten, keine Oberflächentexte).
DEMO_TEXTS: dict[str, dict[str, object]] = {
    "de": {
        "document": DOCUMENT_NAME, "second_document": SECOND_DOCUMENT_NAME,
        "document_text": "Serverschrank\nKeller Regal 1", "second_text": "Kabelfach 3\nPatchkabel Cat6",
        "wrap": ("Kabelwickel", "Monitor-HDMI"), "disk": "Datenträger", "box": "Aufbewahrungsbox",
        "wifi_password": "geheimes-passwort-42", "offline": "Drucker nicht erreichbar",
        "box_main_place": "Keller Regal 2", "box_secondary_place": "Büro",
        "items": (("HDMI-Adapter", 2), ("USB-C-Kabel", 3)), "loan": ("Akkuschrauber", "Jan"),
        "more_boxes": (("BOX-03", "Werkstatt", (("Schraubensortiment", 1), ("Kabelbinder", 100), ("Lötzinn", 2))),
                       ("BOX-15", "Dachboden", (("Weihnachtsdeko", 1),)),
                       ("BOX-21", "Keller Regal 1", (("Ersatzlüfter 120 mm", 4), ("SATA-Kabel", 6), ("Netzteil 12 V", 2)))),
        "more_loans": (("Leiter", "Mia", 3, 11), ("Beamer", "Tom", 12, None)),
        "drafts": ("Serverschrank, geändert", "Unbenannt"),
    },
    "en": {
        "document": "Demo server rack", "second_document": "Demo cable tray",
        "document_text": "Server rack\nBasement shelf 1", "second_text": "Cable tray 3\nPatch cable Cat6",
        "wrap": ("Cable wrap", "Monitor HDMI"), "disk": "Disk", "box": "Storage box",
        "wifi_password": "secret-password-42", "offline": "Printer unreachable",
        "box_main_place": "Basement shelf 2", "box_secondary_place": "Office",
        "items": (("HDMI adapter", 2), ("USB-C cable", 3)), "loan": ("Cordless drill", "Sam"),
        "more_boxes": (("BOX-03", "Workshop", (("Screw assortment", 1), ("Cable ties", 100), ("Solder", 2))),
                       ("BOX-15", "Attic", (("Christmas decorations", 1),)),
                       ("BOX-21", "Basement shelf 1", (("Spare fan 120 mm", 4), ("SATA cable", 6), ("Power supply 12 V", 2)))),
        "more_loans": (("Ladder", "Mia", 3, 11), ("Projector", "Tom", 12, None)),
        "drafts": ("Server rack, changed", "Untitled"),
    },
}
_LANG = ["de"]


def demo_text(key: str, lang: str | None = None):
    """Demo-Inhalt `key` in der Sprache `lang` (None: die von `seed_demo`)."""
    return DEMO_TEXTS.get(lang or _LANG[0], DEMO_TEXTS["de"])[key]


class _Clock:
    """Veränderlicher Zeitpunkt, den `HistoryStore` bei jedem `record()` abfragt."""

    def __init__(self, initial: datetime):
        self.value = initial

    def __call__(self) -> datetime:
        return self.value


def _key_file(home: Path) -> Path:
    path = home / "id_ed25519_demo"
    path.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "PLATZHALTER (Demo-Daten, kein echter Schlüssel)\n"
        "-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    return path


def _write_config(home: Path) -> None:
    key_path = _key_file(home)
    config_mod.save_config({
        "transport": f"file:{home / 'job.bin'}",
        "tape": {"current": TAPE_ID},
        "gui": {"favorites": list(FAVORITES)},
        "ssh": {
            "hosts": [
                {"name": "pmx10", "host": "192.0.2.60", "user": "root", "port": 22, "key": str(key_path)},
            ],
            "timeout_s": 20,
            "strict_host_key": True,
        },
        "queue": {"auto_retry": True},
        # Demo mit allen Modulen; Aufnahmen „ohne Module“ schalten sie im Werkzeug vorübergehend aus.
        "modules": {"enabled": list(modules.MODULE_IDS)},
    })


def _payload_for(meta: JobMeta, result: RenderResult) -> dict:
    request = PrintRequest(labels=(PrintLabel(head=result.head, landscape=result.landscape),), meta=meta)
    return {"request": encode_request(request)}


@dataclass(frozen=True)
class _Rendered:
    meta: JobMeta
    result: RenderResult


def _plain(profile: DeviceProfile, lines: tuple[str, ...], *, source: str = "gui",
          qr: str | None = None) -> _Rendered:
    spec = LabelSpec(lines=lines, qr=qr)
    result = render_label(spec, profile)
    meta = text_meta(spec, source=source)
    return _Rendered(meta, result)


def _from_template(name: str, inputs: dict[str, str], profile: DeviceProfile, tape: TapeProfile, *,
                   source: str = "gui", now: datetime) -> _Rendered:
    template = find_template(name)
    counters = numbering.counter_store(config_mod.load_config())
    resolved = resolve_values(template, inputs, now, counters)
    tr: TemplateRender = render_template(template, resolved.values, profile, tape=tape)
    meta = render_meta(tr, source=source)
    return _Rendered(meta, tr.result)


def _url_qr(url: str, profile: DeviceProfile, *, source: str = "gui") -> _Rendered:
    content = url_content(url)
    spec = LabelSpec(lines=(), qr=content.data)
    result = render_label(spec, profile)
    meta = qr_meta(content, source=source, spec=spec)
    return _Rendered(meta, result)


def _wifi_qr(ssid: str, password: str, profile: DeviceProfile, *, source: str = "gui") -> _Rendered:
    content = wifi_content(ssid, password)
    spec = LabelSpec(lines=(), qr=content.data)
    result = render_label(spec, profile)
    meta = qr_meta(content, source=source, spec=spec)
    return _Rendered(meta, result)


def _head_only(meta: JobMeta, head, length_mm: float, tape_mm: float) -> _Rendered:
    """Eintrag ohne Vorlage und ohne Spec (Kalibrierung, Bild): nur das Kopfbild wie beim echten Druck."""
    result = SimpleNamespace(head=head, landscape=None, length_mm=length_mm, tape_mm=tape_mm)
    return _Rendered(meta, result)  # type: ignore[arg-type]


def _system_entries(profile: DeviceProfile, tape: TapeProfile, *, now: datetime) -> list[tuple[timedelta, _Rendered, str, str]]:
    """Einträge mit Titeln, die der Druckdienst selbst vergibt (in der Sprache beim Drucken):
    Kalibrierung (Lineal, Kantentest), Testlabel, Bild aus der Zwischenablage, Nachdruck und Serie."""
    plain = _plain(profile, ("Tapesmith", "Test " + now.strftime("%d.%m.%Y %H:%M")))
    tape_mm = plain.result.tape_mm
    ruler = _head_only(JobMeta(source="gui", kind="calibrate", title=_t("Kalibrierung Lineal")),
                       place_on_head(ruler_content(profile, 100), profile), 100.0, tape_mm)
    edge = _head_only(JobMeta(source="gui", kind="calibrate", title=_t("Kalibrierung Kantentest")),
                      edge_test_head(profile), 118.0, tape_mm)
    test = _Rendered(replace(plain.meta, kind="test", title=_t("Testlabel")), plain.result)
    clip = _plain(profile, ("Screenshot", "Router-Menü"))
    image = _Rendered(JobMeta(source="hotkey", kind="image", title=_t("Bild aus Zwischenablage")), clip.result)
    disk = _from_template("datentraeger", {"host": "pmx10", "slot": "SSD-1", "sn": "112233274913"},
                          profile, tape, source="gui", now=now)
    reprint = _Rendered(replace(disk.meta, kind="reprint", title=_t("Nachdruck #{id}: ", id=1) + disk.meta.title),
                        disk.result)
    cable = _from_template("kabelfahne", {"kabel_id": "K-020", "quelle": "SW2/P01", "ziel": "nas/eth0"},
                           profile, tape, source="gui", now=now)
    series = _Rendered(replace(cable.meta, title=_t("Serie ({count}): ", count=3) + cable.meta.title), cable.result)
    return [
        (timedelta(hours=30), ruler, "ok", ""),
        (timedelta(hours=29, minutes=40), edge, "ok", ""),
        (timedelta(hours=26), test, "ok", ""),
        (timedelta(hours=9), image, "ok", ""),
        (timedelta(hours=6), series, "ok", ""),
        (timedelta(hours=1), reprint, "ok", ""),
    ]


def _seed_history(profile: DeviceProfile, tape: TapeProfile, *, now: datetime) -> list[int]:
    store = HistoryStore(clock=_Clock(now))
    try:
        ids: list[int] = []
        entries: list[tuple[timedelta, _Rendered, str, str]] = [
            (timedelta(days=46, hours=3),
             _from_template("datentraeger", {"host": "pmx10", "slot": "SSD-1", "sn": "112233274913"},
                            profile, tape, source="cli", now=now),
             "ok", ""),
            (timedelta(days=40, hours=5),
             _from_template("kabelfahne", {"kabel_id": "K-017", "quelle": "SW1/P12", "ziel": "pmx10/eno1"},
                            profile, tape, source="gui", now=now),
             "ok", ""),
            (timedelta(days=33, hours=1),
             _plain(profile, tuple(demo_text("wrap")), source="gui"),
             "ok", ""),
            (timedelta(days=25, hours=6),
             _url_qr("https://wiki.example.com/pmx10", profile, source="gui"),
             "ok", ""),
            (timedelta(days=20, hours=2),
             _wifi_qr("Homelab-IoT", demo_text("wifi_password"), profile, source="gui"),
             "ok", ""),
            (timedelta(days=14, hours=4),
             _from_template("datentraeger", {"host": "pmx10", "slot": "SSD-2", "sn": "112233274916"},
                            profile, tape, source="hotkey", now=now),
             "ok", ""),
            (timedelta(days=10, hours=2),
             _from_template("kabelfahne", {"kabel_id": "K-018", "quelle": "SW1/P13", "ziel": "pmx20/eno2"},
                            profile, tape, source="cli", now=now),
             "ok", ""),
            (timedelta(days=7, hours=1),
             _plain(profile, (demo_text("disk"), "SN 274917"), source="gui"),
             "fehler", demo_text("offline")),
            (timedelta(days=5, hours=3),
             _plain(profile, (demo_text("box"), BOX_MAIN)),
             "ok", ""),
            (timedelta(days=3, hours=2),
             _from_template("datentraeger", {"host": "pmx10", "slot": "SSD-3", "sn": "112233274919"},
                            profile, tape, source="gui", now=now),
             "ok", ""),
            (timedelta(days=1, hours=4),
             _from_template("kabelfahne", {"kabel_id": "K-019", "quelle": "SW1/P14", "ziel": "pmx10/eno3"},
                            profile, tape, source="hotkey", now=now),
             "ok", ""),
            (timedelta(hours=2),
             _plain(profile, ("pmx10 SSD-1 · SN 274913",)),
             "ok", ""),
            *_system_entries(profile, tape, now=now),
        ]
        entries.sort(key=lambda item: item[0], reverse=True)
        for age, rendered, status, error in entries:
            store._clock.value = now - age  # noqa: SLF001 (eigener Test-Helfer, kein öffentliches API)
            entry_id = store.record(
                rendered.meta, landscape=rendered.result.landscape, head=rendered.result.head,
                length_mm=rendered.result.length_mm, tape_mm=rendered.result.tape_mm,
                status=status, error=error,
            )
            ids.append(entry_id)
        return ids
    finally:
        store.close()


def _seed_queue(profile: DeviceProfile, tape: TapeProfile, *, now: datetime) -> list[int]:
    queue = JobQueue()
    try:
        waiting = _from_template("datentraeger", {"host": "pmx10", "slot": "SSD-4", "sn": "112233274921"},
                                 profile, tape, source="cli", now=now)
        waiting_id = queue.add(_payload_for(waiting.meta, waiting.result), source=waiting.meta.source,
                               title=waiting.meta.title, sensitive=waiting.meta.sensitive)

        stuck = _plain(profile, (demo_text("disk"), "SN 274926"), source="gui")
        stuck_id = queue.add(_payload_for(stuck.meta, stuck.result), source=stuck.meta.source,
                             title=stuck.meta.title, sensitive=stuck.meta.sensitive)
        queue.mark_retry(stuck_id, demo_text("offline"), now + timedelta(minutes=7))

        cable = _from_template("kabelfahne", {"kabel_id": "K-021", "quelle": "SW2/P02", "ziel": "nas/eth1"},
                               profile, tape, source="api", now=now)
        series_title = _t("Serie ({count}): ", count=4) + cable.meta.title
        series_id = queue.add(_payload_for(cable.meta, cable.result), source="api", title=series_title,
                              sensitive=False)

        ruler = place_on_head(ruler_content(profile, 100), profile)
        calib_meta = JobMeta(source="gui", kind="calibrate", title=_t("Kalibrierung Lineal"))
        calib_id = queue.add({"request": encode_request(PrintRequest(labels=(PrintLabel(head=ruler),), meta=calib_meta))},
                             source="gui", title=calib_meta.title, sensitive=False)
        return [waiting_id, stuck_id, series_id, calib_id]
    finally:
        queue.close()


def _seed_inventory(*, now: datetime) -> dict:
    store = InventoryStore()
    try:
        store.add_box(BOX_MAIN, demo_text("box_main_place"))
        for item, qty in demo_text("items"):
            store.add_item(item, box_id=BOX_MAIN, qty=qty)
        store.add_box(BOX_SECONDARY, demo_text("box_secondary_place"))
        thing, person = demo_text("loan")
        loan = store.lend(thing, person, since=(now - timedelta(days=20)).date(),
                          due=(now - timedelta(days=5)).date())
        boxes = [BOX_MAIN, BOX_SECONDARY]
        for box_id, place, items in demo_text("more_boxes"):
            store.add_box(box_id, place)
            boxes.append(box_id)
            for item, qty in items:
                store.add_item(item, box_id=box_id, qty=qty)
        for thing, person, days_ago, due_in in demo_text("more_loans"):
            store.lend(thing, person, since=(now - timedelta(days=days_ago)).date(),
                       due=(now + timedelta(days=due_in)).date() if due_in is not None else None)
        return {"boxes": boxes, "loan_id": loan.id}
    finally:
        store.close()


def _seed_rolls(*, now: datetime) -> None:
    rolls = RollStore(tape=lambda: TAPE_ID)
    # Beendete Rolle (Vorgängerin): fast leer, per "leer bei" korrigiert.
    rolls.new_roll(TAPE_ID, length_mm=4000.0, now=now - timedelta(days=60))
    rolls.consume(3850.0, TAPE_ID)
    rolls.mark_empty(3900.0, TAPE_ID)
    # Aktuelle Rolle: rund 1,4 m verbraucht.
    rolls.new_roll(TAPE_ID, length_mm=4000.0, now=now - timedelta(days=8))
    rolls.consume(1400.0, TAPE_ID)


# Das Textobjekt, das die Editor-Aufnahme als einzelnes ausgewähltes Objekt zeigt.
SELECTED_OBJECT_ID = "text1"


def _demo_document() -> LabelDocument:
    doc = LabelDocument(objects=(
        RectObject(id="rect1", x=0, y=0, w=404, h=88, thickness=2, fill="none"),
        IconObject(id="icon1", x=10, y=10, w=32, h=32, icon="tabler:server"),
        TextObject(id=SELECTED_OBJECT_ID, x=50, y=10, w=250, h=68, text=demo_text("document_text"),
                  font="sans", size=20, align="left", valign="middle"),
        QrObject(id="qr1", x=312, y=4, w=80, h=80, data="https://intern.example/serverschrank", error="m"),
    ))
    return doc


def _second_document() -> LabelDocument:
    return LabelDocument(objects=(
        IconObject(id="icon1", x=6, y=12, w=32, h=32, icon="tabler:plug"),
        TextObject(id="text1", x=46, y=8, w=260, h=72, text=demo_text("second_text"), font="sans",
                   size=20, align="left", valign="middle"),
    ))


def _seed_document() -> None:
    save_document(demo_text("document"), _demo_document())
    save_document(demo_text("second_document"), _second_document())


def drafts_dir(home: Path) -> Path:
    return Path(home) / DRAFTS_DIR_NAME


def reset_drafts(home: Path) -> None:
    """Leert den Entwurfsordner des Demo-Homes (nur `*.json` direkt darin)."""
    folder = drafts_dir(home)
    if not folder.is_dir():
        return
    for path in folder.glob("*.json"):
        path.unlink(missing_ok=True)


def seed_orphaned_drafts(home: Path, *, now: datetime | None = None) -> list[str]:
    """Zwei Entwürfe einer fremden, nie wieder gemeldeten Fenster-Sitzung (`demo-fenster`): der Editor
    bietet sie mit `/editor?wiederherstellen=1` zur Wiederherstellung an."""
    home = Path(home)
    if paths.app_dir().resolve() != home.resolve():
        raise RuntimeError(f"TAPESMITH_HOME zeigt nicht auf das Demo-Home {home}")
    stamp = now or datetime.now()
    store = DraftStore(drafts_dir(home), now=lambda: stamp)
    changed, untitled = demo_text("drafts")
    entries = (
        ("demo-entwurf-0001", changed, demo_text("document"), _demo_document(), 0),
        ("demo-entwurf-0002", untitled, None, _second_document(), 1),
    )
    for draft_id, title, doc_name, document, order in entries:
        store.put(draft_id, {"session": DRAFT_SESSION, "title": title, "doc_name": doc_name,
                             "document": document_to_dict(document), "dirty": True, "order": order})
    return [entry[0] for entry in entries]


def _seed_logs(*, now: datetime) -> None:
    """Demo-Protokoll des Druckdienstes (Format wie `daemon.instance`), für die Seite Protokoll."""
    from datetime import timedelta

    from tapesmith import paths

    entries = (
        (-3600, "INFO", "tapesmith.daemon", "Druckdienst gestartet (Version demo)"),
        (-3590, "INFO", "tapesmith.transport", "Verbunden mit P12 über COM4"),
        (-3000, "INFO", "tapesmith.jobs", "Auftrag 12 gedruckt: 1 Etikett, 42 mm"),
        (-2400, "WARNING", "tapesmith.transport", "Keine Antwort vom Drucker, neuer Versuch"),
        (-2390, "INFO", "tapesmith.transport", "Verbunden mit P12 über COM4"),
        (-1200, "ERROR", "tapesmith.integrations", "Paperless nicht erreichbar: Zeitüberschreitung"),
        (-600, "INFO", "tapesmith.jobs", "Auftrag 13 gedruckt: 3 Etiketten, 126 mm"),
        (-60, "DEBUG", "tapesmith.queue", "Warteschlange leer"),
    )
    lines = [f"{(now + timedelta(seconds=dt)).strftime('%Y-%m-%d %H:%M:%S')},000 {level} {name}: {msg}"
             for dt, level, name, msg in entries]
    (paths.log_dir() / "daemon.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def seed_demo(home: Path, *, now: datetime, lang: str = "de") -> dict:
    """Füllt `home` (setzt `TAPESMITH_HOME` selbst nicht) mit Demo-Daten in der Sprache `lang`.

    Rückgabe: Übersicht der erzeugten IDs/Namen, für die Extra-Aufnahmen des Screenshot-Werkzeugs.
    """
    from tapesmith import i18n

    _LANG[0] = lang if lang in DEMO_TEXTS else "de"
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    _write_config(home)

    profile = load_profile()
    tape = current_tape(config_mod.load_config())

    with i18n.use_language(_LANG[0]):
        history_ids = _seed_history(profile, tape, now=now)
        queue_ids = _seed_queue(profile, tape, now=now)
    inventory_info = _seed_inventory(now=now)
    _seed_rolls(now=now)
    _seed_document()
    _seed_logs(now=now)

    return {
        "tape_id": TAPE_ID,
        "templates": list(FAVORITES),
        "history_ids": history_ids,
        "queue_ids": queue_ids,
        "document": demo_text("document"),
        "second_document": demo_text("second_document"),
        "lang": _LANG[0],
        **inventory_info,
    }
