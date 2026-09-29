from tapesmith.lock import PrintLock


def test_lock_name_from_env(monkeypatch):
    monkeypatch.setenv("TAPESMITH_LOCK_NAME", r"Local\Tapesmith.X")
    assert PrintLock().name == r"Local\Tapesmith.X"
    monkeypatch.delenv("TAPESMITH_LOCK_NAME")
    assert PrintLock().name == r"Local\Tapesmith.Print"
    assert PrintLock(r"Local\Y").name == r"Local\Y"
