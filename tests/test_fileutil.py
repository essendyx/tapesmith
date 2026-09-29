import threading
import time

import pytest

from tapesmith.fileutil import FileLock, FileLockTimeout, atomic_write_bytes, atomic_write_text
from tapesmith.templates.fill import CounterStore


def test_atomic_write_replaces_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "sub" / "a.json"
    atomic_write_text(p, "eins")
    atomic_write_text(p, "zwei")
    assert p.read_text(encoding="utf-8") == "zwei"
    assert [x.name for x in p.parent.iterdir()] == ["a.json"]


def test_atomic_write_bytes_replaces(tmp_path):
    p = tmp_path / "b.bin"
    atomic_write_bytes(p, b"eins")
    atomic_write_bytes(p, b"zwei")
    assert p.read_bytes() == b"zwei"
    assert [x.name for x in p.parent.iterdir()] == ["b.bin"]


def test_atomic_write_cleans_tmp_on_error(tmp_path, monkeypatch):
    import os

    p = tmp_path / "c.json"
    original_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("Datenträger nicht bereit")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        atomic_write_text(p, "eins")
    monkeypatch.setattr(os, "replace", original_replace)
    assert not p.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    import os

    p = tmp_path / "d.json"
    original_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("gesperrt durch Virenscanner")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    atomic_write_text(p, "inhalt")
    assert p.read_text(encoding="utf-8") == "inhalt"
    assert calls["n"] == 3


def test_file_lock_excludes_second_holder(tmp_path):
    lock = tmp_path / "x.lock"
    with FileLock(lock):
        with pytest.raises(FileLockTimeout, match="gesperrt"):
            with FileLock(lock, timeout_s=0.1):
                pass
    with FileLock(lock, timeout_s=0.1):
        pass


def test_counter_commit_is_serialised_across_threads(tmp_path):
    store = CounterStore(tmp_path / "counters.json")
    threads = [threading.Thread(target=lambda: [store.commit("k") for _ in range(25)]) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.peek("k") == 101
