"""Ende-zu-Ende-Tests über `create_app` mit echter Sicherheits-Middleware.

Deckt die Querschnitte von Oberfläche, Installation und Update ab: stabile Fehlercodes in jeder Fehlerantwort, Parität der
Fehlercode-Kataloge (Python und Web), Entwürfe-API mit Rollenprüfung, Sprachwahl, „Problem melden“,
Update Ende zu Ende gegen eine `file:`-Quelle mit Testschlüssel und Installer/Deinstallation mit
Fakes. Kein Test nutzt Netz oder die echte Registry: ein Wächter lässt beides sofort scheitern.
Alle Ordner liegen in `tmp_path`; es wird nie gedruckt und nie ein echter Schlüssel erzeugt.
"""

from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from tapesmith import errors as errors_mod
from tapesmith import integration, paths
from tapesmith.install import installer, junction, layout, uninstaller
from tapesmith.install.registry import FakeUninstallRegistry
from tapesmith.install.shortcuts import FakeShortcuts
from tapesmith.lock import PrinterBusy
from tapesmith.update import apply as apply_mod
from tapesmith.update import signing
from tapesmith.update.errors import UpdateError
from tapesmith.update.service import UpdateService
from tapesmith.webapi import drafts
from tapesmith.webapi.drafts import DraftStore
from update_fakes import FakeVenvRun, make_version
from webapi_fakes import close_ctx, make_client, make_token

ROOT = Path(__file__).resolve().parents[1]
WEB_LOCALES = ROOT / "web" / "src" / "locales"
PY_LOCALES = ROOT / "src" / "tapesmith" / "locales"
CLIENT_CODES = {"client.offline", "client.bad_response"}

SID_A = "fenster-aaaa-1111"
SID_B = "fenster-bbbb-2222"
DOC = {"version": 1, "objects": [
    {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 40, "h": 20, "text": "Server"},
]}


# ---------------------------------------------------------------- Wächter und Hilfen

@pytest.fixture(autouse=True)
def kein_netz_keine_registry(monkeypatch):
    """Kein Test erreicht Netz oder echte Registry."""

    def no_transport(self, request):
        raise AssertionError(f"echter HTTP-Transport benutzt: {request.method} {request.url}")

    def no_registry(self, *args, **kwargs):
        raise AssertionError(f"echte Registry beschrieben: {args!r}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_transport)
    monkeypatch.setattr(integration.WinRegBackend, "set", no_registry)


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


class Clock:
    def __init__(self, start: float = 5000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def _err(response: httpx.Response) -> dict:
    body = response.json()
    assert "error" in body, response.text
    assert set(body["error"]) >= {"kind", "code", "message", "hint", "exit_code", "details"}
    return body["error"]


def _flatten(data: dict, prefix: str = "") -> set[str]:
    """Codes eines verschachtelten Fehlerkatalogs: jedes Blatt `{title, hint}` ist ein Code."""
    codes: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        assert isinstance(value, dict), path
        if "title" in value and isinstance(value["title"], str):
            codes.add(path)
        else:
            codes |= _flatten(value, path)
    return codes


def _load_release_tool():
    spec = importlib.util.spec_from_file_location("release_tool_e2e_app", ROOT / "tools" / "release.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- 1. Fehlercodes

def test_404_unbekannte_route_hat_code(api):
    client, _ctx = api
    r = client.get("/api/v1/gibt-es-nicht")
    assert r.status_code == 404
    assert _err(r)["code"] == "not_found"


def test_ohne_token_auth_required(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        r = client.get("/api/v1/settings")
        assert r.status_code == 401
        assert _err(r)["code"] == "auth.required"
    finally:
        close_ctx(ctx)


def test_validierung_request_invalid(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"falsch": 1})
    assert r.status_code == 422
    assert _err(r)["code"] == "request.invalid"


def test_drucker_belegt_printer_busy(api, monkeypatch):
    client, ctx = api

    def busy(**_kw):
        raise PrinterBusy("Druckauftrag läuft")

    monkeypatch.setattr(ctx.service, "status", busy)
    r = client.post("/api/v1/status/refresh", json={})
    assert r.status_code == 409
    assert _err(r)["code"] == "printer.busy"


def test_homelab_token_fehlt(api, tmp_path):
    client, _ctx = api
    # Nie eine echte Token-Datei nutzen: die Referenz zeigt immer unter tmp_path.
    from tapesmith.integrations import settings
    settings.set_setting("paperless.token_ref", f"file:{tmp_path / 'fehlt.token'}")
    r = client.get("/api/v1/homelab/paperless/asn/next")
    assert r.status_code == 424, r.text
    assert _err(r)["code"] == "integration.token_missing"


def test_update_ohne_installation(api):
    client, _ctx = api
    r = client.post("/api/v1/update/install", json={"version": "0.2.1"})
    assert r.status_code == 409, r.text
    assert _err(r)["code"] == "update.not_installed"


# ---------------------------------------------------------------- 2. Code-Parität

def test_fehlercode_kataloge_paritaet():
    expected_py = set(errors_mod.ERROR_CODES)
    assert len(expected_py) == len(errors_mod.ERROR_CODES), "doppelte Codes in ERROR_CODES"
    for lang in ("de", "en"):
        web = json.loads((WEB_LOCALES / lang / "errors.json").read_text(encoding="utf-8"))
        assert _flatten(web) == expected_py | CLIENT_CODES, lang
        py = json.loads((PY_LOCALES / lang / "errors.json").read_text(encoding="utf-8"))
        assert _flatten(py) == expected_py, lang


# ---------------------------------------------------------------- 3. Entwürfe

def test_entwuerfe_ende_zu_ende(api):
    client, ctx = api
    clock = Clock()
    store = DraftStore(paths.app_dir() / drafts.DRAFTS_DIR_NAME, clock=clock,
                       now=lambda: datetime(2026, 9, 28, 12, 0, 0))
    ctx.extras["draft_store"] = store

    def body(session: str, title: str, order: int) -> dict:
        return {"session": session, "title": title, "doc_name": None, "document": DOC, "dirty": True,
                "order": order}

    r = client.put("/api/v1/drafts/entwurf-a-0001", json=body(SID_A, "Eigenes", 0))
    assert r.status_code == 200, r.text
    assert r.json()["session"] == SID_A
    assert client.put("/api/v1/drafts/entwurf-b-0001", json=body(SID_B, "Fremdes", 1)).status_code == 200

    listing = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert [d["id"] for d in listing["own"]] == ["entwurf-a-0001"]
    assert listing["orphaned"] == []  # Fenster B hat eben noch ein Lebenszeichen gegeben

    clock.t += drafts.ALIVE_S + 5
    client.post("/api/v1/drafts/heartbeat", json={"session": SID_A})
    listing = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert [d["id"] for d in listing["orphaned"]] == ["entwurf-b-0001"]

    adopted = client.post("/api/v1/drafts/entwurf-b-0001/adopt", json={"session": SID_A})
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["session"] == SID_A
    listing = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert sorted(d["id"] for d in listing["own"]) == ["entwurf-a-0001", "entwurf-b-0001"]
    assert listing["orphaned"] == []

    full = client.get("/api/v1/drafts/entwurf-b-0001").json()
    assert full["document"]["objects"][0]["text"] == "Server"

    assert client.delete("/api/v1/drafts/entwurf-b-0001").json() == {}
    assert _err(client.get("/api/v1/drafts/entwurf-b-0001"))["code"] == "not_found"


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/api/v1/drafts?session=fenster-aaaa-1111"),
    ("GET", "/api/v1/update/status"),
    ("POST", "/api/v1/support/report"),
])
def test_rolle_drucken_bekommt_403(tmp_path, method, path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        secret = make_token(ctx, "drucken")
        r = client.request(method, path, headers={"Authorization": f"Bearer {secret}"})
        assert r.status_code == 403, r.text
        assert _err(r)["code"] == "auth.forbidden"
    finally:
        close_ctx(ctx)


# ---------------------------------------------------------------- 4. Sprache und Einstellungen

def test_sprache_umstellen_und_abschnitte(api):
    client, _ctx = api
    assert client.get("/api/v1/app").json()["language"] == "auto"
    r = client.patch("/api/v1/settings", json={"changes": {"app.language": "en"}})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/app").json()["language"] == "en"
    sections = {s["id"] for s in client.get("/api/v1/settings").json()["sections"]}
    assert {"oberflaeche", "updates"} <= sections


# ---------------------------------------------------------------- 5. Problem melden

def test_support_bericht_ohne_token(api):
    client, _ctx = api
    geheim = "geheimes-token-0815"
    (paths.log_dir() / "p12d.log").write_text(
        f"GET /familie#t={geheim}\nX-P12-Token: {geheim}\nAuthorization: Bearer {geheim}\n",
        encoding="utf-8")
    r = client.post("/api/v1/support/report")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "logs/p12d.log" in zf.namelist()
    for name in zf.namelist():
        assert geheim not in zf.read(name).decode("utf-8", "replace"), name


# ---------------------------------------------------------------- 6. Update Ende zu Ende

def _wheel_dirs(base: Path, version: str) -> dict[str, Path]:
    """Wheel-Ordner je Python-Version wie nach `pip download` (Platzhalter-Inhalte)."""
    dirs = {}
    for py, tag in (("3.11", "cp311"), ("3.12", "cp312")):
        folder = base / f"py{tag[2:]}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"tapesmith-{version}-py3-none-any.whl").write_bytes(f"tapesmith {version}".encode())
        (folder / f"pillow-12.3.0-{tag}-{tag}-win_amd64.whl").write_bytes(f"pillow {tag}".encode())
        dirs[py] = folder
    return dirs


def _installed_root(root: Path) -> Path:
    make_version(root, "0.2.0")
    installer.activate("0.2.0", root=root)
    return root


def test_update_ende_zu_ende_file_quelle(tmp_path, monkeypatch):
    import hashlib

    release = _load_release_tool()
    root = _installed_root(tmp_path / "wurzel")
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(root))

    pem, entry = signing.generate_keypair()
    key_file = tmp_path / "schluessel" / "priv.pem"
    key_file.parent.mkdir()
    key_file.write_bytes(pem)
    keys = [(entry["id"], signing.load_private_key(key_file).public_key())]

    feed = tmp_path / "quelle"
    dirs = _wheel_dirs(tmp_path / "bau" / "0.2.1", "0.2.1")
    wheel_args = [arg for py, folder in dirs.items() for arg in ("--wheels", f"{py}={folder}")]
    out: list[str] = []
    rc = release.main(["publish-dir", "--version", "0.2.1", "--notes", "Probe", *wheel_args,
                       "--key", str(key_file), "--copy-wheels", "--out", str(feed)], out=out.append,
                      restrict=lambda p: None)
    assert rc == 0, out
    assert {p.name for p in feed.iterdir()} == {"manifest.json", "manifest.json.sig", "lock.txt", "wheels"}

    cfg = {"update": {"source": f"file:{feed}", "keep_versions": 2}}
    run = FakeVenvRun()
    svc = UpdateService(lambda: cfg, keys_loader=lambda: keys, root=root, run=run, spawn=lambda argv: 0,
                        executable=str(layout.venv_python(layout.version_dir("0.2.0", root), gui=True)),
                        now=lambda: datetime(2026, 10, 2, 8, 0), app_version=lambda: "0.2.0")

    status = svc.check()
    assert status.installed is True
    assert status.current == "0.2.0"
    assert status.available["version"] == "0.2.1"

    target = svc.prepare("0.2.1")
    assert target == layout.version_dir("0.2.1", root)
    assert layout.is_complete_version(target)
    assert run.kinds() == ["venv", "pip", "selftest"], "Selbsttest der neuen Version wurde nicht ausgeführt"
    pip_argv = run.calls[1][0]
    assert "--require-hashes" in pip_argv and "--no-index" in pip_argv
    assert pip_argv[pip_argv.index("--find-links") + 1] == str(feed / "wheels")
    # Die Lock-Liste des Updaters kommt aus dem signierten Manifest und trägt die echten Prüfsummen.
    wheel = dirs["3.11"] / "tapesmith-0.2.1-py3-none-any.whl"
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in run.locks[0]
    assert run.locks[0] == (feed / "lock.txt").read_text(encoding="utf-8")
    assert svc.status().state == "ready"

    spawned: list[list[str]] = []
    result = apply_mod.apply_update(
        "0.2.1", root=root, stopper=lambda: True, lister=lambda: [], killer=lambda pid, t: True,
        spawn=lambda argv: spawned.append(list(argv)) or 0, health=lambda: {"version": "0.2.1"},
        clock=lambda: 0.0, sleep=lambda s: None, keep=2)
    assert result == apply_mod.RESULT_OK
    assert junction.read_junction(layout.current_link(root)).name == "0.2.1"
    state = layout.read_state(root)
    assert state.current == "0.2.1" and state.previous == "0.2.0"
    assert ["-m", "tapesmith.daemon"] in [argv[1:] for argv in spawned]
    assert ["-m", "tapesmith.gui.tray"] in [argv[1:] for argv in spawned]

    # Zweiter Durchlauf: pip lehnt ein Paket ab (Prüfsumme passt nicht), nichts wird umgeschaltet.
    feed2 = tmp_path / "quelle2"
    dirs2 = _wheel_dirs(tmp_path / "bau" / "0.2.2", "0.2.2")
    wheel_args2 = [arg for py, folder in dirs2.items() for arg in ("--wheels", f"{py}={folder}")]
    assert release.main(["publish-dir", "--version", "0.2.2", *wheel_args2, "--key", str(key_file),
                         "--out", str(feed2)], out=out.append, restrict=lambda p: None) == 0
    cfg["update"]["source"] = f"file:{feed2}"
    svc2 = UpdateService(lambda: cfg, keys_loader=lambda: keys, root=root, run=FakeVenvRun(pip_rc=1),
                         spawn=lambda argv: 0,
                         executable=str(layout.venv_python(layout.version_dir("0.2.1", root), gui=True)),
                         now=lambda: datetime(2026, 10, 3, 8, 0), app_version=lambda: "0.2.1")
    assert svc2.check().available["version"] == "0.2.2"
    with pytest.raises(UpdateError) as info:
        svc2.prepare("0.2.2")
    assert info.value.code == "update.download_failed"
    assert junction.read_junction(layout.current_link(root)).name == "0.2.1"
    assert layout.read_state(root).current == "0.2.1"
    assert not layout.version_dir("0.2.2", root).exists()
    assert svc2.status().error["code"] == "update.download_failed"


# ---------------------------------------------------------------- 7. Installer Ende zu Ende

def _tree(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_installer_und_deinstallation_mit_fakes(tmp_path, app_home, monkeypatch):
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(tmp_path / "startmenue"))
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "config.json").write_text('{"transport": "memory"}', encoding="utf-8")
    home_before = _tree(app_home)

    root = tmp_path / "Programs" / "Tapesmith"
    shortcuts, uninstall_reg, registry = FakeShortcuts(), FakeUninstallRegistry(), integration.FakeRegistry()
    spawned: list[list[str]] = []

    assert not root.exists()
    assert uninstall_reg.values == {} and registry.data == {}
    result = installer.install(version="0.2.0", root=root, python=Path("C:/Fake/Python311/python.exe"),
                               run=FakeVenvRun(), shortcuts=shortcuts,
                               uninstall_registry=uninstall_reg, registry=registry,
                               spawn=lambda argv: spawned.append(list(argv)) or 0,
                               stopper=lambda r: True, source_stopper=lambda env: True)
    assert result.version == "0.2.0"
    assert layout.is_complete_version(layout.version_dir("0.2.0", root))
    assert junction.read_junction(layout.current_link(root)) is not None
    assert layout.read_state(root).current == "0.2.0"
    assert {p.name for p in shortcuts.items} == {"Tapesmith.lnk", "Tapesmith deinstallieren.lnk"}
    assert uninstall_reg.values["DisplayName"] == "Tapesmith"
    assert uninstall_reg.values["DisplayVersion"] == "0.2.0"
    assert registry.data, "Kontextmenü, URI und Autostart fehlen in der Fake-Registry"
    assert spawned == [[str(layout.current_pythonw(root)), "-m", "tapesmith.gui.tray"]]

    deleted: list[Path] = []
    lines = uninstaller.uninstall(root=root, shortcuts=shortcuts, uninstall_registry=uninstall_reg,
                                  registry=registry, stopper=lambda r: True, schedule_delete=deleted.append,
                                  quiet=True)
    assert deleted == [root]
    assert shortcuts.items == {}
    assert uninstall_reg.values == {}
    assert not any(registry.data.values())
    assert junction.read_junction(layout.current_link(root)) is None
    assert any("Benutzerdaten" in line for line in lines)
    assert _tree(app_home) == home_before


def test_status_erneut_verbinden(api, monkeypatch):
    client, ctx = api
    seen = {}
    real = ctx.service.status

    def spy(**kw):
        seen.update(kw)
        return real(fresh=False)

    monkeypatch.setattr(ctx.service, "status", spy)
    r = client.post("/api/v1/status/refresh", json={"reconnect": True})
    assert r.status_code == 200, r.text
    assert seen == {"fresh": True, "reconnect": True}
