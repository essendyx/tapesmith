"""Text in die Windows-Zwischenablage (nur Fake-Backend, kein echter ctypes-Aufruf)."""

import importlib
import sys

import pytest

from tapesmith.integrations import winclip


def test_fake_backend_receives_text():
    got = []
    winclip.copy_text("- 2026-09-28 Label gedruckt: x", backend=got.append)
    assert got == ["- 2026-09-28 Label gedruckt: x"]


def test_backend_error_becomes_runtime_error():
    def broken(_text):
        raise OSError("belegt")

    with pytest.raises(RuntimeError, match="Zwischenablage"):
        winclip.copy_text("x", backend=broken)


def test_without_windows_and_backend(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Zwischenablage nur unter Windows"):
        winclip.copy_text("x")


def test_module_loads_without_windows_call():
    module = importlib.reload(winclip)
    assert callable(module.copy_text)
