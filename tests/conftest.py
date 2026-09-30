import os
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Schon beim Sammeln (Modul-Code der Testdateien) nie der echte Datenordner. Eigener Temp-Ordner
# für die ganze Sitzung; pro Test setzt die Fixture `app_home` zusätzlich einen frischen Ordner.
_SESSION_HOME = tempfile.mkdtemp(prefix="tapesmith-pytest-")
os.environ["TAPESMITH_HOME"] = _SESSION_HOME
# Deutsch als erkannte Systemsprache, unabhängig von der Windows-Sprache des Rechners (Tests, die
# Englisch oder die Erkennung prüfen, setzen es selbst). `TAPESMITH_LANG` erzwingt nichts.
os.environ["TAPESMITH_SYSTEM_LANG"] = "de"
os.environ.pop("TAPESMITH_LANG", None)

import warnings
from pathlib import Path

import pytest

# Starlette >= 1.x warnt schon beim Import von starlette.testclient, wenn nur httpx (nicht httpx2)
# installiert ist. Der TestClient funktioniert mit httpx unverändert. Der Import hier, vor dem Sammeln
# und mit gezieltem Filter, hält die Warnung auch bei `pytest -W error` fern (die Kommandozeile
# überstimmt sonst die filterwarnings aus pyproject.toml). Entfällt, sobald httpx2 im venv ist.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using .httpx. with .starlette.testclient. is deprecated")
    try:
        import starlette.testclient  # noqa: F401
    except ImportError:
        pass
from PIL import Image, ImageChops

from tapesmith import modules as _modules

_REAL_IMPLICIT_ENABLED = _modules.implicit_enabled


def pytest_addoption(parser):
    parser.addoption("--hardware", action="store_true", help="Tests am echten Drucker ausführen")
    parser.addoption("--update-snapshots", action="store_true", help="Referenzbilder neu schreiben")


def pytest_unconfigure(config):
    shutil.rmtree(_SESSION_HOME, ignore_errors=True)


def pytest_collection_modifyitems(config, items):
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="braucht --hardware")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def app_home(tmp_path, monkeypatch):
    home = tmp_path / "app"
    monkeypatch.setenv("TAPESMITH_HOME", str(home))
    monkeypatch.setenv("TAPESMITH_LOCK_NAME", f"Local\\Tapesmith.Test.{os.getpid()}")
    # Tests drucken direkt (kein Druckdienst); Tests, die den Dienst brauchen, entfernen es gezielt.
    monkeypatch.setenv("TAPESMITH_NO_DAEMON", "1")
    monkeypatch.setenv("TAPESMITH_SYSTEM_LANG", "de")
    monkeypatch.delenv("TAPESMITH_LANG", raising=False)
    # Ablösung der alten "P12 Label"-Installation: nie der echte Ordner.
    monkeypatch.setenv("TAPESMITH_LEGACY_INSTALL_ROOT", str(tmp_path / "legacy-install" / "P12Label"))
    return home


@pytest.fixture(autouse=True)
def _no_real_devices(monkeypatch):
    """Nie die Geräte des Testrechners: gekoppelte Bluetooth-COM-Ports und USB-Geräte kommen aus der
    Registry und unterscheiden sich zwischen Entwicklerrechner (Drucker gekoppelt) und CI-Rechner
    (weder Bluetooth noch USB). Standard ist deshalb "nichts gefunden"; Tests, die Ports oder
    Geräte brauchen, setzen `btports._read_registry` bzw. `usb._read_usb_registry` selbst."""
    from tapesmith.transport import btports, usb

    monkeypatch.setattr(btports, "_read_registry", lambda: [])
    monkeypatch.setattr(usb, "_read_usb_registry", lambda: [])


@pytest.fixture(autouse=True)
def _module_detection_all(monkeypatch):
    """Ohne `modules` in config.json gilt im Produkt die Erkennung benutzter Module (im leeren
    Testordner: keine). Die meisten Tests prüfen aber die Funktionen der Module selbst; für sie gelten
    ohne ausdrückliche Liste alle Module als eingeschaltet. Tests mit `modules.enabled` in config.json
    sehen genau diese Liste; `real_module_detection` stellt die echte Erkennung wieder her."""
    from tapesmith import modules

    monkeypatch.setattr(modules, "implicit_enabled", lambda: modules.MODULE_IDS)


@pytest.fixture
def real_module_detection(monkeypatch, _module_detection_all):
    """Echte Erkennung benutzter Module statt "alle eingeschaltet" (siehe `_module_detection_all`)."""
    from tapesmith import modules

    monkeypatch.setattr(modules, "implicit_enabled", _REAL_IMPLICIT_ENABLED)


def _colors(image: Image.Image) -> list[tuple[int, object]]:
    """Pillow->=10.1-kompatibler Ersatz fuer das veraltete Image.getdata(): liefert
    (Anzahl, Pixelwert)-Paare ueber getcolors()."""
    colors = image.getcolors(maxcolors=max(image.width * image.height, 1))
    if colors is None:
        raise ValueError("zu viele unterschiedliche Farben fuer getcolors()")
    return colors


@pytest.fixture
def pixel_colors():
    """Menge der im Bild vorkommenden Pixelwerte (Ersatz fuer set(image.getdata()))."""
    def get(image: Image.Image) -> set:
        return {value for _count, value in _colors(image)}
    return get


@pytest.fixture
def pixel_counts():
    """Pixelwert -> Anzahl (Ersatz fuer Zaehlungen auf Basis von image.getdata())."""
    def get(image: Image.Image) -> dict:
        return dict((value, count) for count, value in _colors(image))
    return get


SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.fixture
def snapshot(request):
    update = request.config.getoption("--update-snapshots")

    def check(name: str, image: Image.Image):
        path = SNAPSHOTS / f"{name}.png"
        image = image.convert("1")
        if update or not path.exists():
            SNAPSHOTS.mkdir(exist_ok=True)
            image.save(path)
            pytest.fail(f"Snapshot geschrieben, bitte prüfen: {path}")
        expected = Image.open(path).convert("1")
        assert expected.size == image.size, f"Größe {image.size} statt {expected.size}"
        diff = ImageChops.difference(expected.convert("L"), image.convert("L")).getbbox()
        assert diff is None, f"Bild weicht ab im Bereich {diff}; bei gewollter Änderung --update-snapshots"

    return check


@pytest.fixture
def homelab_test_defaults(monkeypatch):
    """Homelab-Integrationen mit neutralen Testadressen (192.0.2.0/24, TEST-NET-1) vorbelegen.

    Im Produkt sind alle Adressen und Token-Referenzen leer (Integrationen aus). Viele Tests prüfen
    aber das Verhalten eines eingerichteten Dienstes über die Standardwerte; diese Fixture ersetzt
    dafür `settings.DEFAULTS` für die Dauer des Tests. Die Token-Dateien gibt es nicht."""
    import copy

    from tapesmith.integrations import settings

    data = copy.deepcopy(settings.DEFAULTS)
    data["paperless"]["url"] = "http://192.0.2.12:8010"
    data["paperless"]["token_ref"] = r"file:C:\Tokens\.paperless_tapesmith_token"
    data["obsidian"]["mcp_url"] = "http://192.0.2.12:8092/mcp"
    data["shortlink"]["token_ref"] = r"file:C:\Tokens\.shortlink_admin_token"
    data["homeassistant"]["url"] = "http://192.0.2.9:8123"
    data["homeassistant"]["token_ref"] = r"file:C:\Tokens\.ha_token"
    data["plausi"]["networks"] = ["192.0.2.0/24"]
    monkeypatch.setattr(settings, "DEFAULTS", data)
    return data
