"""Tests für Backoff, BLE-Erreichbarkeits-Probe und RetryScheduler."""

import pytest

from tapesmith.daemon.probe import (
    Backoff,
    BleAdvertisementProbe,
    NullProbe,
    RetryDecision,
    RetryScheduler,
    bleak_available,
    make_probe,
)


# 9
def test_backoff_delays():
    b = Backoff()
    assert [b.delay(n) for n in range(1, 7)] == [30, 60, 120, 240, 300, 300]
    with pytest.raises(ValueError):
        Backoff(10, 5)


# 10
def test_ble_advertisement_probe():
    probe = BleAdvertisementProbe(scanner=lambda t: [("P12", "00:11:22:33:44:55")])
    assert probe.check() is True

    probe2 = BleAdvertisementProbe(scanner=lambda t: [("Mi Band", "11:22:33:44:55:66")])
    assert probe2.check() is False

    probe3 = BleAdvertisementProbe(
        address="001122334455", scanner=lambda t: [(None, "00:11:22:33:44:55")]
    )
    assert probe3.check() is True

    def raising_scanner(t):
        raise RuntimeError("boom")

    probe4 = BleAdvertisementProbe(scanner=raising_scanner)
    assert probe4.check() is None


def test_null_probe():
    probe = NullProbe()
    assert probe.name == "none"
    assert probe.check() is None


# 11
def test_make_probe(monkeypatch):
    import tapesmith.daemon.probe as probe_mod

    monkeypatch.setattr(probe_mod, "bleak_available", lambda: False)
    assert isinstance(make_probe("auto"), NullProbe)
    assert isinstance(make_probe("off"), NullProbe)
    assert isinstance(make_probe("connect"), NullProbe)
    with pytest.raises(ValueError):
        make_probe("x")


def test_make_probe_ble_and_auto_with_bleak(monkeypatch):
    import tapesmith.daemon.probe as probe_mod

    monkeypatch.setattr(probe_mod, "bleak_available", lambda: True)
    assert isinstance(make_probe("auto"), BleAdvertisementProbe)
    assert isinstance(make_probe("ble"), BleAdvertisementProbe)


def test_bleak_available_reflects_find_spec(monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert bleak_available() is False
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert bleak_available() is True


# 12
def test_retry_scheduler_decide_and_ready():
    t = [0.0]
    scheduler = RetryScheduler(Backoff(), clock=lambda: t[0])

    decision = scheduler.decide(True, None)
    assert decision.action == "drucken"
    assert scheduler.ready() is True  # keine Wartezeit -> sofort bereit

    scheduler.on_offline()
    assert scheduler.next_try_in == 30.0
    assert scheduler.ready() is False

    decision = scheduler.decide(True, None)
    assert decision.action == "warten"
    assert 0 < decision.wait_s <= 30

    t[0] = 31.0
    assert scheduler.ready() is True
    decision = scheduler.decide(True, False)
    assert decision.action == "warten"
    assert decision.wait_s == 60
    assert "nicht erreichbar" in decision.reason

    scheduler.on_online()
    assert scheduler.ready() is True
    decision = scheduler.decide(True, None)
    assert decision.action == "drucken"


def test_retry_scheduler_no_due_jobs():
    scheduler = RetryScheduler(Backoff(), clock=lambda: 0.0)
    decision = scheduler.decide(False, None)
    assert decision == RetryDecision("warten", 3600, "")


def test_retry_scheduler_auto_retry_off_and_manual():
    t = [0.0]
    scheduler = RetryScheduler(Backoff(), auto_retry=False, clock=lambda: t[0])
    decision = scheduler.decide(True, None)
    assert decision.action == "warten"
    assert decision.reason == "Automatischer Nachdruck aus"
    assert scheduler.ready() is False

    scheduler.on_manual_retry()
    assert scheduler.ready() is True
    decision = scheduler.decide(True, None)
    assert decision.action == "drucken"

    # einmalig: nach der Entscheidung wieder "aus", solange auto_retry False bleibt
    decision2 = scheduler.decide(True, None)
    assert decision2.action == "warten"


def test_retry_scheduler_manual_retry_during_active_backoff():
    # Backoff läuft bereits (nach on_offline) -> manueller Retry muss sofort wirken,
    # ohne auf das Ende der alten Wartezeit zu warten.
    t = [0.0]
    scheduler = RetryScheduler(Backoff(), clock=lambda: t[0])
    scheduler.on_offline()
    assert scheduler.next_try_in == 30.0
    assert scheduler.ready() is False

    t[0] = 5.0
    scheduler.on_manual_retry()
    assert scheduler.ready() is True
    decision = scheduler.decide(True, None)
    assert decision.action == "drucken"


def test_scheduler_configure_without_restart():
    t = [0.0]
    scheduler = RetryScheduler(Backoff(30, 300), clock=lambda: t[0])
    assert scheduler.on_offline() == 30
    scheduler.configure(backoff=Backoff(5, 10))
    assert scheduler.decide(True, True).wait_s == 5       # laufende Wartezeit verkürzt
    t[0] = 5
    assert scheduler.decide(True, True).action == "drucken"
    scheduler.configure(auto_retry=False)
    assert scheduler.auto_retry is False
    assert not scheduler.ready()
    assert scheduler.decide(True, True).reason == RetryScheduler.AUTO_OFF_REASON
    scheduler.configure(auto_retry=True)
    assert scheduler.ready()
