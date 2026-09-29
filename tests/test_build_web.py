"""Tests für tools/build_web.py (Build der Web-Oberfläche). Ohne echtes npm."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_web.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_web", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bw():
    return _load_module()


class FakeRunner:
    def __init__(self, fail_on: str | None = None):
        self.calls: list[tuple[list[str], dict]] = []
        self.fail_on = fail_on

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        joined = " ".join(cmd[1:])
        code = 1 if self.fail_on is not None and joined == self.fail_on else 0
        return subprocess.CompletedProcess(cmd, code)

    def steps(self) -> list[str]:
        return [" ".join(c[1:]) for c, _ in self.calls]


def _write_static(static: Path, assets: list[str], present: list[str]) -> None:
    (static / "assets").mkdir(parents=True, exist_ok=True)
    tags = "".join(f'<script type="module" src="/assets/{a}"></script>' for a in assets)
    (static / "index.html").write_text(f"<!doctype html><html><head>{tags}</head></html>", encoding="utf-8")
    for name in present:
        (static / "assets" / name).write_text("x", encoding="utf-8")


@pytest.fixture
def layout(tmp_path, bw, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text("{}", encoding="utf-8")
    static = tmp_path / "static"
    _write_static(static, ["index-abc.js"], ["index-abc.js"])
    monkeypatch.setattr(bw, "WEB_DIR", web)
    monkeypatch.setattr(bw, "STATIC_DIR", static)
    monkeypatch.setattr(bw, "find_npm", lambda: "npm")
    return web, static


def test_install_runs_ci_check_build_in_order(bw, layout):
    web, _static = layout
    (web / "package-lock.json").write_text("{}", encoding="utf-8")
    runner = FakeRunner()
    assert bw.main(["--install"], runner=runner) == 0
    assert runner.steps() == ["ci", "run check", "run build"]
    for _cmd, kwargs in runner.calls:
        assert Path(kwargs["cwd"]) == web


def test_install_without_lockfile_uses_npm_install(bw, layout):
    runner = FakeRunner()
    assert bw.main(["--install"], runner=runner) == 0
    assert runner.steps() == ["install", "run check", "run build"]


def test_without_install_no_ci(bw, layout):
    runner = FakeRunner()
    assert bw.main([], runner=runner) == 0
    assert runner.steps() == ["run check", "run build"]


def test_skip_check_leaves_out_check(bw, layout):
    runner = FakeRunner()
    assert bw.main(["--skip-check"], runner=runner) == 0
    assert runner.steps() == ["run build"]


def test_failing_step_gives_exit_1_and_stops(bw, layout, capsys):
    runner = FakeRunner(fail_on="run check")
    assert bw.main([], runner=runner) == 1
    assert runner.steps() == ["run check"]
    assert "fehlgeschlagen" in capsys.readouterr().err


def test_no_npm_gives_exit_1_with_message(bw, layout, monkeypatch, capsys):
    monkeypatch.setattr(bw, "find_npm", lambda: None)
    runner = FakeRunner()
    assert bw.main([], runner=runner) == 1
    assert runner.calls == []
    assert "npm nicht gefunden: Node.js installieren" in capsys.readouterr().err


def test_missing_static_after_build_gives_exit_1(bw, layout, capsys):
    _web, static = layout
    (static / "index.html").unlink()
    assert bw.main(["--skip-check"], runner=FakeRunner()) == 1
    assert "index.html" in capsys.readouterr().err


def test_verify_static_reports_missing_index(bw, tmp_path):
    problems = bw.verify_static(tmp_path / "leer")
    assert len(problems) == 1
    assert "index.html" in problems[0]


def test_verify_static_reports_missing_assets(bw, tmp_path):
    static = tmp_path / "static"
    _write_static(static, ["index-abc.js", "fluent-def.js"], ["index-abc.js"])
    (static / "index.html").write_text(
        (static / "index.html").read_text(encoding="utf-8").replace(
            "</head>", '<link rel="modulepreload" href="/assets/fluent-def.js"><link rel="stylesheet" href="/assets/app.css"></head>'
        ),
        encoding="utf-8",
    )
    problems = bw.verify_static(static)
    assert any("fluent-def.js" in p for p in problems)
    assert any("app.css" in p for p in problems)
    assert not any("index-abc.js" in p for p in problems)


def test_verify_static_ok(bw, tmp_path):
    static = tmp_path / "static"
    _write_static(static, ["index-abc.js"], ["index-abc.js"])
    assert bw.verify_static(static) == []


def test_find_npm_prefers_npm_cmd_on_windows(bw, monkeypatch):
    seen: list[str] = []

    def fake_which(name):
        seen.append(name)
        return r"C:\node\npm.cmd" if name == "npm.cmd" else None

    monkeypatch.setattr(bw.shutil, "which", fake_which)
    monkeypatch.setattr(bw, "IS_WINDOWS", True)
    assert bw.find_npm() == r"C:\node\npm.cmd"


def test_find_npm_none(bw, monkeypatch):
    monkeypatch.setattr(bw.shutil, "which", lambda name: None)
    assert bw.find_npm() is None


def test_checked_in_build_is_complete(bw):
    """Der eingecheckte Build verweist nur auf vorhandene Dateien."""
    assert bw.verify_static(bw.STATIC_DIR) == []
