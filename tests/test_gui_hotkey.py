"""Tests für globale Tastenkürzel: Parser, AltGr-Kollision, Registrierung über ein
Fake-Backend und den nativen Ereignisfilter. Nie echte RegisterHotKey-Aufrufe."""

import ctypes
from ctypes import wintypes

import pytest

from tapesmith.gui.hotkey import (
    GERMAN_ALTGR,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    WM_HOTKEY,
    FakeLayoutProbe,
    HotkeyManager,
    HotkeySpec,
    WinLayoutProbe,
    altgr_conflict,
    format_hotkey,
    parse_hotkey,
)


class FakeBackend:
    def __init__(self, ok=True):
        self.ok = ok
        self.registered = {}
        self.calls = []

    def register(self, hwnd, hotkey_id, modifiers, vk):
        self.calls.append(("register", hwnd, hotkey_id, modifiers, vk))
        if self.ok is True or (callable(self.ok) and self.ok(vk)):
            self.registered[hotkey_id] = (modifiers, vk)
            return True
        return False

    def unregister(self, hwnd, hotkey_id):
        self.calls.append(("unregister", hwnd, hotkey_id))
        self.registered.pop(hotkey_id, None)


# ---------- parse/format ----------

@pytest.mark.parametrize("text, mods, vk, key", [
    ("Ctrl+Alt+L", MOD_CONTROL | MOD_ALT, 0x4C, "L"),
    ("strg + alt + umschalt + l", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x4C, "L"),
    ("Win+Shift+F9", MOD_WIN | MOD_SHIFT, 0x78, "F9"),
    ("Alt+7", MOD_ALT, 0x37, "7"),
    ("CTRL+F24", MOD_CONTROL, 0x87, "F24"),
    ("Ctrl+Alt+Shift+L", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x4C, "L"),
])
def test_parse_hotkey(text, mods, vk, key):
    assert parse_hotkey(text) == HotkeySpec(mods, vk, key)


@pytest.mark.parametrize("text", ["L", "Shift+L", "Ctrl+Alt+", "Ctrl+Alt+LL", "Ctrl+Alt+Ä", "Win+L",
                                  "", "Ctrl+Alt+L+K", "Ctrl+Foo+L", "Ctrl+F25"])
def test_parse_hotkey_fehler(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


def test_parse_hotkey_win_l_meldung():
    with pytest.raises(ValueError, match="sperrt Windows"):
        parse_hotkey("Win+L")


def test_format_hotkey():
    assert format_hotkey(parse_hotkey("Ctrl+Alt+L")) == "Strg+Alt+L"
    assert format_hotkey(parse_hotkey("Ctrl+Alt+Shift+L")) == "Strg+Alt+Umschalt+L"
    assert format_hotkey(parse_hotkey("shift+win+f9")) == "Umschalt+Win+F9"
    # Rundlauf
    assert parse_hotkey(format_hotkey(parse_hotkey("Alt+Win+7"))) == parse_hotkey("Alt+Win+7")


# ---------- AltGr ----------

def test_altgr_conflict():
    probe = FakeLayoutProbe(GERMAN_ALTGR)
    message = altgr_conflict(parse_hotkey("Ctrl+Alt+Q"), probe)
    assert message is not None and "„@“" in message and "Strg+Alt+Q" in message
    assert altgr_conflict(parse_hotkey("Ctrl+Alt+L"), probe) is None
    assert altgr_conflict(parse_hotkey("Ctrl+Alt+Shift+7"), probe) is None
    assert altgr_conflict(parse_hotkey("Win+Alt+Q"), probe) is None
    assert altgr_conflict(parse_hotkey("Alt+Q"), probe) is None
    assert altgr_conflict(parse_hotkey("Ctrl+Alt+Win+Q"), probe) is None
    assert "„{“" in altgr_conflict(parse_hotkey("Ctrl+Alt+7"), probe)


def test_fake_probe_umschalt_tabelle():
    probe = FakeLayoutProbe(GERMAN_ALTGR, shift_table={"7": "x"})
    assert "„x“" in altgr_conflict(parse_hotkey("Ctrl+Alt+Shift+7"), probe)


def test_win_layout_probe_liefert_text_oder_none():
    # liest nur das aktuelle Tastaturlayout, verändert nichts
    value = WinLayoutProbe().altgr_char(0x4C, False)
    assert value is None or isinstance(value, str)


# ---------- Manager ----------

def test_manager_register_erfolg(qtbot):
    backend = FakeBackend()
    manager = HotkeyManager(backend=backend, probe=FakeLayoutProbe(GERMAN_ALTGR), hwnd_provider=lambda: 42)
    assert manager.register("quick", "Ctrl+Alt+L") is None
    kind, hwnd, hotkey_id, mods, vk = backend.calls[-1]
    assert (kind, hwnd, vk) == ("register", 42, 0x4C)
    assert mods == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
    assert manager.registered() == {"quick": parse_hotkey("Ctrl+Alt+L")}

    # gleicher Name erneut: alte Registrierung wird zuerst gelöst
    assert manager.register("quick", "Ctrl+Alt+K") is None
    assert ("unregister", 42, hotkey_id) in backend.calls
    assert manager.registered()["quick"].key == "K"
    assert len(backend.registered) == 1


def test_manager_register_altgr_und_belegt(qtbot):
    backend = FakeBackend(ok=lambda vk: vk != 0x4D)
    manager = HotkeyManager(backend=backend, probe=FakeLayoutProbe(GERMAN_ALTGR))
    message = manager.register("quick", "Ctrl+Alt+Q")
    assert message is not None and "@" in message
    assert backend.calls == []
    message = manager.register("quick", "Ctrl+Alt+Shift+M")
    assert message == "Strg+Alt+Umschalt+M ist schon von einem anderen Programm belegt"
    assert manager.registered() == {}
    message = manager.register("quick", "Nix")
    assert message is not None
    assert manager.registered() == {}


def test_manager_unregister_all(qtbot):
    backend = FakeBackend()
    manager = HotkeyManager(backend=backend, probe=FakeLayoutProbe({}))
    manager.register("quick", "Ctrl+Alt+L")
    manager.register("clipboard", "Ctrl+Alt+Shift+L")
    assert len(backend.registered) == 2
    manager.unregister_all()
    assert backend.registered == {}
    assert manager.registered() == {}


def test_native_filter_mit_echtem_qt_zeiger(qtbot):
    # Qt übergibt die Nachricht als shiboken VoidPtr; dessen bool() ist immer False. Die frühere
    # Prüfung "not message" ließ deshalb jede echte Nachricht fallen: der Hotkey ging nie (29.09.2026).
    from shiboken6 import VoidPtr
    backend = FakeBackend()
    manager = HotkeyManager(backend=backend, probe=FakeLayoutProbe({}))
    manager.register("quick", "Ctrl+Alt+L")
    quick_id = next(call[2] for call in backend.calls if call[0] == "register")
    seen = []
    manager.triggered.connect(seen.append)
    msg = wintypes.MSG(message=WM_HOTKEY, wParam=quick_id)
    pointer = VoidPtr(ctypes.addressof(msg))
    result = manager.native_filter().nativeEventFilter(b"windows_generic_MSG", pointer)
    assert seen == ["quick"]
    assert result[0] is True


def test_native_filter_loest_signal_aus(qtbot):
    backend = FakeBackend()
    manager = HotkeyManager(backend=backend, probe=FakeLayoutProbe({}))
    manager.register("quick", "Ctrl+Alt+L")
    manager.register("clipboard", "Ctrl+Alt+Shift+L")
    quick_id = next(call[2] for call in backend.calls if call[0] == "register" and call[4] == 0x4C
                    and not call[3] & MOD_SHIFT)
    seen = []
    manager.triggered.connect(seen.append)
    filt = manager.native_filter()

    msg = wintypes.MSG(message=WM_HOTKEY, wParam=quick_id)
    result = filt.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
    assert seen == ["quick"]
    assert result[0] is True

    other = wintypes.MSG(message=0x0100, wParam=quick_id)
    result = filt.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(other))
    assert seen == ["quick"]
    assert result[0] is False

    unknown = wintypes.MSG(message=WM_HOTKEY, wParam=999)
    result = filt.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(unknown))
    assert seen == ["quick"]
    assert result[0] is False

    result = filt.nativeEventFilter(b"xcb_generic_event_t", ctypes.addressof(msg))
    assert result[0] is False
    assert manager.handle_hotkey_id(quick_id) is True
    assert manager.handle_hotkey_id(12345) is False
