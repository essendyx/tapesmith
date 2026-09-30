"""Reine Funktionen von tools/screenshots.py und tools/demo_data.py (kein Browser)."""

import re

import pytest
from datetime import datetime
from pathlib import Path

import tools.demo_data as demo_data
import tools.screenshots as screenshots
from tapesmith.document.model import document_from_dict
from tapesmith.daemon.queue import JobQueue
from tapesmith.history import HistoryStore
from tapesmith.inventory import InventoryStore
from tapesmith import config as config_mod

FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.png$")


def test_shot_plan_counts_and_unique_ascii_filenames():
    plan = screenshots.shot_plan(screenshots.ALL_ROUTES, screenshots.THEMES, screenshots.SIZES,
                                 screenshots.LANGS)

    main, themes = len(screenshots.MAIN_ROUTES), len(screenshots.THEMES)
    extra_sizes = sum(len(route.sizes) for route in screenshots.EXTRA_ROUTES)
    english_extra = sum(1 for route in screenshots.EXTRA_ROUTES if route.english)
    expected_de = main * themes * 2 + extra_sizes * themes  # Hauptseiten Desktop und Handy, Extras je Größe
    expected_en = (main + english_extra) * themes           # Englisch: Haupt- und Modulseiten, nur Desktop
    expected_zoom = main                                  # 200 %: Hauptseiten, nur hell, Deutsch
    assert len(screenshots.MAIN_ROUTES) == 14
    assert len(plan) == expected_de + expected_en + expected_zoom

    names = [screenshots.shot_filename(shot) for shot in plan]
    assert len(names) == len(set(names)), "Dateinamen müssen eindeutig sein"
    for name in names:
        assert FILENAME_RE.match(name), f"Dateiname {name!r} enthält Umlaute/Leerzeichen/Großschreibung"


def test_shot_plan_respects_requested_sizes():
    only_desktop = screenshots.shot_plan(screenshots.ALL_ROUTES, screenshots.THEMES, ["desktop"], ["de"])
    assert all(shot.size == "desktop" for shot in only_desktop)
    # jede Hauptroute + jede Extra-Route je Thema einmal
    assert len(only_desktop) == (len(screenshots.MAIN_ROUTES) + len(screenshots.EXTRA_ROUTES)) * len(
        screenshots.THEMES)
    assert {route.sizes for route in screenshots.EXTRA_ROUTES if route.english} == {screenshots.MODULE_SIZES}


def test_page_url_builds_localhost_url_with_token_fragment():
    assert screenshots.page_url(8712, "tok", "/verlauf?x=1") == "http://127.0.0.1:8712/verlauf?x=1#t=tok"
    assert screenshots.page_url(54321, "abc", "/schnelldruck") == "http://127.0.0.1:54321/schnelldruck#t=abc"


def test_is_expected_error_accepts_no_404():
    """Der Editor nutzt die Entwürfe-API, `documents/_entwurf` gibt es nicht mehr."""
    assert screenshots.EXPECTED_404_PATHS == ()
    assert screenshots.is_expected_error("http://127.0.0.1:8712/api/v1/documents/_entwurf?t=x", 404) is False
    assert screenshots.is_expected_error("http://127.0.0.1:8712/api/v1/documents/_entwurf", 500) is False
    assert screenshots.is_expected_error("http://127.0.0.1:8712/api/v1/history", 500) is False
    assert screenshots.is_expected_error("http://127.0.0.1:8712/api/v1/history", 404) is False


def test_write_index_lists_every_image(tmp_path):
    plan = screenshots.shot_plan(screenshots.MAIN_ROUTES[:2], screenshots.THEMES, screenshots.SIZES,
                                 screenshots.LANGS)
    screenshots.write_index(tmp_path, plan)
    text = (tmp_path / "index.md").read_text(encoding="utf-8")
    for shot in plan:
        assert screenshots.shot_filename(shot) in text
    for route in screenshots.MAIN_ROUTES[:2]:
        assert route.title in text


def test_existing_shots_keeps_only_shots_with_a_saved_file(tmp_path):
    plan = screenshots.shot_plan(screenshots.MAIN_ROUTES[:2], screenshots.THEMES, ["desktop"])
    assert len(plan) >= 2
    saved, missing = plan[0], plan[1:]
    (tmp_path / screenshots.shot_filename(saved)).write_bytes(b"not a real png, just a marker")

    kept = screenshots.existing_shots(tmp_path, plan)

    assert kept == [saved]
    for shot in missing:
        assert shot not in kept


class _Recorder:
    def __init__(self):
        self.events: list[tuple] = []
        self.visible: dict[str, bool] = {}


class _FakeLocator:
    """Genügt für die Playwright-Aufrufe, die `tools/screenshots.py` auf einem Locator macht."""

    def __init__(self, recorder: _Recorder, name: str, *, aria_expanded: str | None = None):
        self._r = recorder
        self._name = name
        self._aria_expanded = aria_expanded

    @property
    def first(self):
        return self

    def fill(self, value: str) -> None:
        self._r.events.append(("fill", self._name, value))

    def focus(self) -> None:
        self._r.events.append(("focus", self._name))

    def dispatch_event(self, event: str) -> None:
        self._r.events.append((event, self._name))

    def is_visible(self) -> bool:
        return self._r.visible.get(self._name, True)

    def get_attribute(self, attr: str):
        return self._aria_expanded if attr == "aria-expanded" else None


class _FakeKeyboard:
    def __init__(self, recorder: _Recorder):
        self._r = recorder

    def press(self, combo: str) -> None:
        self._r.events.append(("key", combo))

    def type(self, text: str) -> None:
        self._r.events.append(("type", text))


class _FakeMouse:
    def __init__(self, recorder: _Recorder):
        self._r = recorder

    def move(self, x, y) -> None:
        self._r.events.append(("mouse_move", x, y))


class _FakePage:
    """Fälscht genau die Playwright-Aufrufe, die die reinen `tools/screenshots.py`-Helfer
    (ohne echten Browser) auf einer Seite machen, damit ihre Reihenfolge/Wahl von Selektoren
    geprüft werden kann, ohne Chromium zu starten."""

    def __init__(self):
        self.recorder = _Recorder()
        self.keyboard = _FakeKeyboard(self.recorder)
        self.mouse = _FakeMouse(self.recorder)
        self._more_options = _FakeLocator(self.recorder, "button:Mehr Optionen", aria_expanded="false")
        self.eval_on_selector_all = lambda selector, expr: 0  # keine Spinner mehr
        self.wait_for_load_state = lambda state, timeout=None: None

    def get_by_placeholder(self, text: str) -> _FakeLocator:
        return _FakeLocator(self.recorder, f"placeholder:{text}")

    def get_by_label(self, text: str) -> _FakeLocator:
        return _FakeLocator(self.recorder, f"label:{text}")

    def get_by_role(self, role: str, name=None) -> _FakeLocator:
        key = name.pattern if hasattr(name, "pattern") else name
        if role == "button" and key == "Mehr Optionen":
            return self._more_options
        return _FakeLocator(self.recorder, f"role:{role}:{key}")

    def wait_for_selector(self, selector: str, timeout=None) -> None:
        self.recorder.events.append(("wait_for_selector", selector))

    def wait_for_timeout(self, ms) -> None:
        self.recorder.events.append(("wait_timeout", ms))

    def bring_to_front(self) -> None:
        self.recorder.events.append(("bring_to_front",))

    def evaluate(self, script: str, arg=None) -> None:
        self.recorder.events.append(("evaluate", script, arg))


def test_confirm_dialog_opens_more_options_before_filling_kopien():
    """Regression: `Kopien` liegt hinter dem eingeklappten "Mehr Optionen" (Schnelldruck/index.tsx,
    `optionsOpen`); ohne den Klick war das Feld nie sichtbar, `fill()` hing bis zum Timeout, und
    der Rückfrage-Dialog 'Wirklich drucken?' erschien nie."""
    page = _FakePage()

    screenshots._confirm_dialog(page, {})

    events = page.recorder.events
    opened_at = events.index(("focus", "button:Mehr Optionen"))
    filled_at = next(i for i, e in enumerate(events) if e[:2] == ("fill", "label:Kopien"))
    assert opened_at < filled_at


def test_open_more_options_skips_the_click_when_already_expanded():
    page = _FakePage()
    page._more_options._aria_expanded = "true"

    screenshots._open_more_options(page)

    assert ("focus", "button:Mehr Optionen") not in page.recorder.events


def test_ensure_painted_forces_a_real_input_event_before_every_screenshot():
    """Regression: ohne ein echtes Eingabeereignis lieferte `page.screenshot()` für fast alle
    Hauptseiten nur die Hintergrundfarbe zurück; das gilt für JEDE
    Aufnahme, nicht nur für Routen mit `interact`."""
    page = _FakePage()

    screenshots._ensure_painted(page, (1440, 900))

    kinds = [e[0] for e in page.recorder.events]
    assert "bring_to_front" in kinds
    assert kinds.count("mouse_move") >= 1
    assert "wait_timeout" in kinds


def test_clear_stray_overlay_backgrounds_targets_fluent_portal_zindex():
    """Regression: Fluent-UI-Portal-Wurzeln (Tooltip/Menü/Dialog/Toast) erben das `background-color`
    der obersten `<FluentProvider>` (ThemeProvider.tsx) und verdecken dadurch als blickdichte,
    viewportgroße `position:absolute; z-index:1000000`-Geschwister von `#root` die ganze Seite,
    schon bevor überhaupt etwas geöffnet wurde (per `page.evaluate`
    nachgeprüft: Entfernt man nur ihre Hintergrundfarbe, zeigt der Screenshot echten Inhalt)."""
    page = _FakePage()

    screenshots._clear_stray_overlay_backgrounds(page)

    events = [e for e in page.recorder.events if e[0] == "evaluate"]
    assert len(events) == 1
    _, script, arg = events[0]
    assert arg == screenshots.STRAY_OVERLAY_MIN_ZINDEX
    assert "root" in script  # #root selbst darf nie angefasst werden
    assert "position" in script and "zIndex" in script


def test_wait_ready_waits_for_a_concrete_visible_element():
    """Regression: `_wait_ready` gab sich früher mit "networkidle" + "keine Spinner mehr" zufrieden;
    beides sagt nichts darüber aus, ob überhaupt etwas sichtbar gemalt wurde."""
    page = _FakePage()

    screenshots._wait_ready(page, timeout_s=1.0)

    waited_selectors = [e[1] for e in page.recorder.events if e[0] == "wait_for_selector"]
    assert screenshots.READY_SELECTOR in waited_selectors


def test_write_index_after_existing_shots_never_links_a_missing_file(tmp_path):
    """Regression: `main()` rief `write_index` frueher mit dem GEPLANTEN Shot-Set auf, nicht mit
    den tatsaechlich gespeicherten Aufnahmen; scheiterte eine Aufnahme (z. B. weil ein Dialog nicht
    rechtzeitig erschien), verwies `index.md` auf ein PNG, das nie geschrieben wurde."""
    plan = screenshots.shot_plan(screenshots.EXTRA_ROUTES, ["hell"], ["desktop"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # nur die erste Aufnahme "gelingt" (Datei existiert), der Rest scheitert im simulierten Lauf.
    (out_dir / screenshots.shot_filename(plan[0])).write_bytes(b"png-platzhalter")

    saved = screenshots.existing_shots(out_dir, plan)
    screenshots.write_index(out_dir, saved)

    text = (out_dir / "index.md").read_text(encoding="utf-8")
    assert screenshots.shot_filename(plan[0]) in text
    for shot in plan[1:]:
        assert screenshots.shot_filename(shot) not in text


def test_seed_demo_writes_realistic_stores(app_home):
    info = demo_data.seed_demo(app_home, now=datetime(2026, 9, 28, 10, 0, 0))

    cfg = config_mod.load_config()
    assert cfg["transport"].startswith("file:")

    history = HistoryStore()
    try:
        entries = history.search(limit=50)
        assert len(entries) >= 16
        kinds = {e.kind for e in entries}
        assert {"calibrate", "test", "image", "reprint"} <= kinds, "Systemtitel je Art werden erwartet"
        assert any(e.sensitive for e in entries), "ein sensibler WLAN-QR-Eintrag wird erwartet"
        assert any(e.status == "fehler" for e in entries), "ein Fehler-Eintrag wird erwartet"
    finally:
        history.close()

    inventory = InventoryStore()
    try:
        boxes = {b.id for b in inventory.boxes()}
        assert "BOX-07" in boxes
        assert len(boxes) >= 5
        loans = inventory.loans(open_only=True)
        assert len(loans) == 3
        assert sum(1 for loan in loans if loan.overdue(datetime(2026, 9, 28).date())) == 1
    finally:
        inventory.close()

    doc_path = app_home / "documents" / f"{demo_data.DOCUMENT_NAME}.p12doc.json"
    assert doc_path.is_file()
    import json

    document_from_dict(json.loads(doc_path.read_text(encoding="utf-8")))  # muss gültig sein

    assert info["history_ids"]
    assert info["queue_ids"]
    queue = JobQueue()
    try:
        # Warteschlange mit genau 4 aktiven (nicht erledigten) Aufträgen.
        assert len(queue.list(include_done=False)) == 4
        assert queue.active_count() == 4
        assert sorted(j.id for j in queue.list(include_done=False)) == sorted(info["queue_ids"])
    finally:
        queue.close()
    assert info["document"] == demo_data.DOCUMENT_NAME


def test_editor_route_selects_exactly_one_object():
    """Editor "mit einem ausgewählten Objekt" (Singular). Strg+A wählte alle
    4 Objekte des Demo-Dokuments."""
    editor = next(r for r in screenshots.MAIN_ROUTES if r.key == "editor")
    assert editor.interact == "select_one"
    assert "select_all" not in screenshots.INTERACTIONS


def test_select_one_clicks_the_single_text_object_in_layers_panel():
    page = _FakePage()

    screenshots._select_one(page, {})

    events = page.recorder.events
    assert ("key", "Control+a") not in events
    clicks = [e for e in events if e[0] == "click"]
    assert clicks == [("click", rf"role:option:\({demo_data.SELECTED_OBJECT_ID}\)$")]
    # Ebenen-Reiter vor dem Klick, danach zurück auf Eigenschaften (Einzelobjekt-Panel).
    names = [e[1] for e in events if e[0] in ("focus", "click")]
    assert names.index("role:tab:Ebenen") < names.index(clicks[0][1]) < names.index("role:tab:Eigenschaften")
    assert "role:button:Eigenschaften und Ebenen" not in names


def test_select_one_opens_drawer_on_narrow_layout_and_closes_it_again():
    page = _FakePage()
    page.recorder.visible["role:tab:Ebenen"] = False

    screenshots._select_one(page, {})

    events = page.recorder.events
    names = [e[1] for e in events if e[0] in ("focus", "click")]
    assert names[0] == "role:button:Eigenschaften und Ebenen"
    click_at = next(i for i, e in enumerate(events) if e[0] == "click")
    assert ("key", "Escape") in events[click_at:]


def test_index_shots_keeps_images_of_pages_outside_a_partial_run(tmp_path):
    """Regression: ein Teillauf `--only editor` schrieb `index.md` nur mit den Editor-Bildern neu
    und warf alle übrigen, weiterhin vorhandenen Aufnahmen aus dem Index."""
    full = screenshots.shot_plan(screenshots.ALL_ROUTES, screenshots.THEMES, screenshots.SIZES,
                                 screenshots.LANGS)
    for shot in full[:3] + full[-2:]:
        (tmp_path / screenshots.shot_filename(shot)).write_bytes(b"png-platzhalter")

    listed = screenshots.index_shots(tmp_path)

    assert listed == full[:3] + full[-2:]


# ---------------------------------------------------------------- Seiten Zugriff und Familie


def test_routes_zugriff_and_familie():
    by_key = {route.key: route for route in screenshots.MAIN_ROUTES}
    assert by_key["zugriff"].path == "/zugriff"
    assert by_key["zugriff"].token_key is None
    assert by_key["familie"].path == "/familie"
    assert by_key["familie"].token_key == "family_token"


def test_shot_url_uses_family_token_only_for_family_page():
    plan = screenshots.shot_plan(screenshots.MAIN_ROUTES, ["hell"], ["handy"])
    shots = {shot.page: shot for shot in plan}
    info = {"family_token": "p12_abcdef01_familie"}
    assert screenshots.shot_url(shots["familie"], 8712, "sitzung", info) == \
        "http://127.0.0.1:8712/familie#t=p12_abcdef01_familie"
    assert screenshots.shot_url(shots["zugriff"], 8712, "sitzung", info) == \
        "http://127.0.0.1:8712/zugriff#t=sitzung"
    # ohne Familien-Token fällt die Seite auf das Sitzungs-Token zurück (admin darf die Familienrouten)
    assert screenshots.shot_url(shots["familie"], 8712, "sitzung", {}) == "http://127.0.0.1:8712/familie#t=sitzung"


def test_seed_access_demo_creates_tokens_per_role(tmp_path):
    from tapesmith.apitokens import TokenStore

    store = TokenStore(tmp_path / "access" / "tokens.json")
    info = screenshots.seed_access_demo(store)
    tokens = store.list()
    assert {t.role for t in tokens} == {"admin", "drucken", "familie"}
    family = store.verify(info["family_token"])
    assert family is not None and family.role == "familie"


# ---------------------------------------------------------------- Sprachen, 200 %, axe


def _plan_all():
    return screenshots.shot_plan(screenshots.ALL_ROUTES, screenshots.THEMES, screenshots.SIZES,
                                 screenshots.LANGS)


def test_zusaetzliche_routen():
    main = {route.key: route for route in screenshots.MAIN_ROUTES}
    extra = {route.key: route for route in screenshots.EXTRA_ROUTES}
    assert main["homelab"].path == "/homelab"
    assert extra["homelab-proxmox"].path == "/homelab/proxmox"
    assert extra["homelab-proxmox"].sizes == ("desktop", "handy")
    assert extra["homelab-proxmox"].english is True
    assert extra["homelab-proxmox"].interact == "proxmox_load"
    assert extra["tastenkuerzel"].interact == "shortcuts"
    assert extra["editor-tabs"].interact == "second_tab"
    assert extra["wiederherstellen"].path == "/editor?wiederherstellen=1"
    assert extra["wiederherstellen"].drafts == "verwaist"
    assert extra["einstellungen-updates"].path == "/einstellungen?abschnitt=updates"
    for key in ("shortcuts", "second_tab"):
        assert key in screenshots.INTERACTIONS


def test_routen_fuer_module_mit_und_ohne_module():
    extra = {route.key: route for route in screenshots.EXTRA_ROUTES}
    assert extra["einstellungen-module"].path == "/einstellungen?abschnitt=module"
    assert extra["einstellungen-erweitert"].path == "/einstellungen?abschnitt=erweitert"
    for key in ("ohne-module", "einstellungen-ohne-module", "homelab-ohne-module", "modul-ausgeschaltet"):
        assert extra[key].modules == ()
    assert extra["einstellungen-module"].modules is None
    plan = screenshots.shot_plan([extra["ohne-module"]], ["hell"], ["desktop"])
    assert plan[0].modules == ()


def test_seed_demo_schaltet_alle_module_ein_und_werkzeug_schaltet_um(app_home):
    import json
    from datetime import datetime

    from tapesmith import config as config_mod
    from tapesmith import modules
    from tools.demo_data import seed_demo

    seed_demo(app_home, now=datetime(2026, 9, 29, 12, 0))
    assert modules.enabled_ids(config_mod.load_config()) == modules.MODULE_IDS
    screenshots.set_demo_modules(())
    assert json.loads((app_home / "config.json").read_text(encoding="utf-8"))["modules"]["enabled"] == []
    screenshots.set_demo_modules(None)
    assert modules.enabled_ids(config_mod.load_config()) == modules.MODULE_IDS


def test_englisch_haupt_und_modulseiten_desktop_hell_und_dunkel():
    english = [shot for shot in _plan_all() if shot.lang == "en"]
    expected = {route.key for route in screenshots.MAIN_ROUTES} | {
        route.key for route in screenshots.EXTRA_ROUTES if route.english}
    assert {shot.page for shot in english} == expected
    assert "homelab-kleinanzeigen" in expected
    assert {shot.size for shot in english} == {"desktop"}
    assert {shot.theme for shot in english} == {"hell", "dunkel"}
    assert all(screenshots.shot_filename(shot).endswith("-en.png") for shot in english)


def test_zoom200_nur_hell_deutsch_hauptseiten_mit_doppelter_dichte():
    zoom = [shot for shot in _plan_all() if shot.size == "zoom200"]
    assert {shot.page for shot in zoom} == {route.key for route in screenshots.MAIN_ROUTES}
    assert {(shot.theme, shot.lang) for shot in zoom} == {("hell", "de")}
    for shot in zoom:
        assert shot.viewport == (720, 450)
        assert shot.device_scale_factor == 2
        assert shot.is_mobile is False
        assert shot.full_page is True
    assert screenshots.shot_filename(zoom[0]) == f"{zoom[0].page}-hell-zoom200.png"


def test_dateinamen_je_sprache():
    shot = screenshots.Shot(page="verlauf", theme="dunkel", size="desktop", route="/verlauf",
                            viewport=(1440, 900), full_page=True, is_mobile=False, device_scale_factor=1)
    assert screenshots.shot_filename(shot) == "verlauf-dunkel-desktop.png"
    en = screenshots.Shot(**{**shot.__dict__, "lang": "en"})
    assert screenshots.shot_filename(en) == "verlauf-dunkel-desktop-en.png"


def test_langs_und_themes_filtern_den_plan():
    only_en = screenshots.shot_plan(screenshots.ALL_ROUTES, ["hell"], screenshots.SIZES, ["en"])
    assert only_en and all(shot.lang == "en" and shot.theme == "hell" for shot in only_en)
    only_de = screenshots.shot_plan(screenshots.ALL_ROUTES, screenshots.THEMES, ["desktop", "handy"], ["de"])
    assert all(shot.lang == "de" and shot.size != "zoom200" for shot in only_de)


def test_index_hat_abschnitte_deutsch_englisch_200(tmp_path):
    plan = _plan_all()
    screenshots.write_index(tmp_path, plan)
    text = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "## Deutsch" in text
    assert "## Englisch" in text
    assert "## 200 %" in text
    assert text.index("## Deutsch") < text.index("## Englisch") < text.index("## 200 %")
    for shot in plan:
        assert f"({screenshots.shot_filename(shot)})" in text
    assert "\u2013" not in text and "\u2014" not in text  # keine Gedankenstriche


def test_index_ohne_englisch_laesst_den_abschnitt_weg(tmp_path):
    plan = screenshots.shot_plan(screenshots.MAIN_ROUTES[:1], ["hell"], ["desktop"], ["de"])
    screenshots.write_index(tmp_path, plan)
    text = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "## Englisch" not in text and "## 200 %" not in text


def test_axe_issues_je_element_mit_regel_ziel_thema():
    shot = screenshots.shot_plan([screenshots.MAIN_ROUTES[0]], ["dunkel"], ["desktop"], ["en"])[0]
    violations = [{"id": "color-contrast", "help": "Elements must meet minimum color contrast",
                   "nodes": [{"target": ["#root .caption"], "failureSummary": "Fix any of the following:\n  4.1"},
                             {"target": ["button.x"], "failureSummary": ""}]}]
    issues = screenshots.axe_issues(shot, violations)
    assert [issue.kind for issue in issues] == ["axe", "axe"]
    assert all(issue.page == shot.page for issue in issues)
    assert "color-contrast [dunkel/desktop/en] #root .caption" in issues[0].detail
    assert "Fix any of the following: 4.1" in issues[0].detail
    assert issues[1].detail.endswith("button.x: Elements must meet minimum color contrast")
    assert screenshots.axe_issues(shot, []) == []


def test_axe_regeln_und_skript():
    assert screenshots.AXE_TAGS == ("wcag2a", "wcag2aa", "wcag21aa")
    assert screenshots.AXE_SCRIPT.name == "axe.min.js"
    assert "axe-core" in screenshots.AXE_SCRIPT.parts


def test_main_ohne_axe_core_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(screenshots, "AXE_SCRIPT", tmp_path / "fehlt" / "axe.min.js")
    assert screenshots.main(["--out", str(tmp_path / "out")]) == 1
    assert "npm ci" in capsys.readouterr().err


def test_main_unbekannte_sprache_exit_1(tmp_path, capsys):
    assert screenshots.main(["--out", str(tmp_path / "out"), "--langs", "fr"]) == 1
    assert "fr" in capsys.readouterr().err


def test_shortcuts_interaction_druckt_fragezeichen_ausserhalb_von_feldern():
    page = _FakePage()
    screenshots._shortcuts(page, {})
    events = page.recorder.events
    blur_at = next(i for i, e in enumerate(events) if e[0] == "evaluate")
    key_at = events.index(("key", "?"))
    assert blur_at < key_at
    assert ("wait_for_selector", "[role='dialog']") in events


class _RowLocator(_FakeLocator):
    def wait_for(self, timeout=None) -> None:
        self._r.events.append(("wait_for", self._name))


class _TabsPage(_FakePage):
    def get_by_role(self, role: str, name=None):
        if role == "row":
            key = name.pattern if hasattr(name, "pattern") else name
            return _RowLocator(self.recorder, f"role:row:{key}")
        return super().get_by_role(role, name)


def test_second_tab_oeffnet_das_zweite_dokument_per_doppelklick():
    for lang, label in (("de", "Öffnen"), ("en", "Open")):
        page = _TabsPage()
        screenshots._second_tab(page, {"lang": lang})
        events = page.recorder.events
        assert events[0] == ("focus", f"role:button:{label}")
        assert ("dblclick", f"role:row:{re.escape(demo_data.SECOND_DOCUMENT_NAME)}") in events
        assert any(e[0] == "wait_for_selector" and demo_data.SECOND_DOCUMENT_NAME in e[1] for e in events)


def test_select_one_nutzt_englische_beschriftungen():
    page = _FakePage()
    screenshots._select_one(page, {"lang": "en"})
    names = [e[1] for e in page.recorder.events if e[0] in ("focus", "click")]
    assert "role:tab:Layers" in names and "role:tab:Properties" in names


def test_zweites_demo_dokument(app_home):
    demo_data.seed_demo(app_home, now=datetime(2026, 9, 28, 10, 0, 0))
    import json

    for name in (demo_data.DOCUMENT_NAME, demo_data.SECOND_DOCUMENT_NAME):
        path = app_home / "documents" / f"{name}.p12doc.json"
        document_from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_verwaiste_entwuerfe_und_leeren(app_home):
    from tapesmith.webapi.drafts import DraftStore

    app_home.mkdir(parents=True, exist_ok=True)
    ids = demo_data.seed_orphaned_drafts(app_home, now=datetime(2026, 9, 28, 10, 0, 0))
    assert len(ids) == 2
    listing = DraftStore(app_home / "drafts").list("fenster-screenshot-1")
    assert [d["id"] for d in listing["orphaned"]] == ids
    assert listing["own"] == []
    assert all(d["session"] == demo_data.DRAFT_SESSION and d["dirty"] for d in listing["orphaned"])

    (app_home / "drafts" / "fremd.txt").write_text("bleibt", encoding="utf-8")
    demo_data.reset_drafts(app_home)
    assert sorted(p.name for p in (app_home / "drafts").iterdir()) == ["fremd.txt"]


def test_verwaiste_entwuerfe_nur_im_demo_home(app_home, tmp_path):
    other = tmp_path / "anderes-home"
    other.mkdir()
    import pytest

    with pytest.raises(RuntimeError, match="Demo-Home"):
        demo_data.seed_orphaned_drafts(other)


def test_prepare_drafts_leert_und_legt_nur_fuer_wiederherstellen_an(app_home):
    app_home.mkdir(parents=True, exist_ok=True)
    plan = {shot.page: shot for shot in screenshots.shot_plan(screenshots.ALL_ROUTES, ["hell"], ["desktop"], ["de"])}
    screenshots._prepare_drafts(app_home, plan["wiederherstellen"])
    assert len(list((app_home / "drafts").glob("*.json"))) == 2
    screenshots._prepare_drafts(app_home, plan["verlauf"])
    assert list((app_home / "drafts").glob("*.json")) == []


def test_overflow_issue_meldet_ueberlauf_des_inhalts_und_der_seite():
    shot = screenshots.shot_plan([screenshots.MAIN_ROUTES[0]], ["hell"], ["zoom200"], ["de"])[0]
    assert screenshots.overflow_issue(shot, {"main_sw": 654, "main_cw": 654, "doc_sw": 720, "vw": 720}) is None
    assert screenshots.overflow_issue(shot, {"main_sw": 655, "main_cw": 654, "doc_sw": 720, "vw": 720}) is None
    issue = screenshots.overflow_issue(shot, {"main_sw": 824, "main_cw": 654, "doc_sw": 720, "vw": 720,
                                              "wide": ["section.p12-card bis 880 px"]})
    assert issue is not None and issue.kind == "ueberlauf" and issue.page == shot.page
    assert "824/654" in issue.detail and "section.p12-card" in issue.detail and "zoom200" in issue.detail
    page_wide = screenshots.overflow_issue(shot, {"main_sw": 0, "main_cw": 0, "doc_sw": 800, "vw": 720})
    assert page_wide is not None and "800/720" in page_wide.detail


def test_dialog_aufnahmen_nur_viewport():
    plan = {shot.page: shot for shot in screenshots.shot_plan(screenshots.ALL_ROUTES, ["hell"], ["desktop"], ["de"])}
    assert plan["wiederherstellen"].full_page is False
    assert plan["tastenkuerzel"].full_page is False
    assert plan["verlauf"].full_page is True


def test_demo_home_neutral_und_geschuetzt(tmp_path):
    assert screenshots.DEMO_HOME.lower().startswith("c:\\tapesmith-demo")
    home = screenshots.prepare_demo_home(tmp_path / "demo")
    assert (home / screenshots.DEMO_MARKER).is_file()
    (home / "alt.txt").write_text("x", encoding="utf-8")
    home = screenshots.prepare_demo_home(home)
    assert not (home / "alt.txt").exists()
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "wichtig.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError):
        screenshots.prepare_demo_home(fremd)
    assert (fremd / "wichtig.txt").is_file()


def test_axe_laesst_nur_die_fokus_waechter_von_fluent_aus():
    assert screenshots.AXE_EXCLUDE == "[data-tabster-dummy]"
    assert "exclude" in screenshots.AXE_RUN and "wcag" not in screenshots.AXE_EXCLUDE


def test_demo_daten_englisch(app_home):
    """`seed_demo(lang="en")`: Demo-Inhalte auf Englisch (Dokumente, Inventar), Vorlagen englisch."""
    info = demo_data.seed_demo(app_home, now=datetime(2026, 9, 28, 10, 0, 0), lang="en")
    try:
        assert info["document"] == "Demo server rack"
        assert info["second_document"] == "Demo cable tray"
        assert (app_home / "documents" / "Demo server rack.p12doc.json").is_file()
        drafts = demo_data.seed_orphaned_drafts(app_home, now=datetime(2026, 9, 28, 10, 0, 0))
        assert drafts
    finally:
        demo_data.seed_demo.__globals__["_LANG"][0] = "de"


def test_screenshots_zeigen_nie_echte_netzwerkdaten(monkeypatch):
    # Aufnahmen landen im öffentlichen Repo: Rechnername und LAN-Adressen des PCs, auf dem sie
    # entstehen, werden durch Demo-Werte ersetzt.
    import socket

    from tapesmith import netinfo
    monkeypatch.setattr(socket, "gethostname", socket.gethostname)
    monkeypatch.setattr(netinfo, "local_ipv4_addresses", netinfo.local_ipv4_addresses)
    screenshots._neutral_network_identity()
    assert socket.gethostname() == screenshots.DEMO_HOSTNAME
    assert netinfo.local_ipv4_addresses() == ["192.0.2.10"]
    assert netinfo.lan_addresses({}, None) in ([], ["192.0.2.10"])
