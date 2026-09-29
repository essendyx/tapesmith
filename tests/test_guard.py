"""Tests für den Fehldruckschutz-Kern."""

import threading
import time

import pytest
from PIL import Image

from tapesmith.guard import (
    DEFAULT_QUOTAS,
    Debouncer,
    GuardDecision,
    GuardPolicy,
    GuardRejected,
    JobRequest,
    JobRunning,
    Quota,
    Usage,
    content_key,
    evaluate,
    load_policy,
)


def req(**kw):
    base = dict(source="cli", label_mm=40.0, tape_mm=64.0, copies=1)
    base.update(kw)
    return JobRequest(**base)


class TestEvaluate:
    def test_normalfall(self):
        decision = evaluate(req())
        assert decision.allowed
        assert not decision.needs_confirmation
        assert decision.reasons == ()

    def test_label_ueber_schwelle_braucht_rueckfrage(self):
        decision = evaluate(req(label_mm=151.0))
        assert decision.allowed
        assert decision.needs_confirmation
        assert "151 mm" in decision.message()

    def test_label_auf_schwelle_braucht_keine_rueckfrage(self):
        decision = evaluate(req(label_mm=150.0))
        assert decision.allowed
        assert not decision.needs_confirmation
        assert decision.reasons == ()

    def test_kopien_ueber_schwelle_braucht_rueckfrage(self):
        decision = evaluate(req(source="gui", copies=6))
        assert decision.allowed
        assert decision.needs_confirmation
        assert "6 Kopien" in decision.message()

    def test_kopien_auf_schwelle_braucht_keine_rueckfrage(self):
        decision = evaluate(req(copies=5))
        assert decision.allowed
        assert not decision.needs_confirmation
        assert decision.reasons == ()

    def test_kopien_ueber_obergrenze_wird_abgelehnt(self):
        decision = evaluate(req(copies=51))
        assert not decision.allowed
        assert not decision.needs_confirmation
        assert "Obergrenze" in decision.message()

    def test_label_ueber_obergrenze_wird_abgelehnt(self):
        decision = evaluate(req(label_mm=501.0))
        assert not decision.allowed

    def test_tape_ueber_obergrenze_wird_abgelehnt(self):
        decision = evaluate(req(tape_mm=2100.0))
        assert not decision.allowed
        assert "2100 mm" in decision.message()

    def test_nicht_interaktive_quelle_kann_nicht_bestaetigen(self):
        decision = evaluate(req(source="api", label_mm=151.0))
        assert not decision.allowed
        assert "kann nicht bestätigen" in decision.message()

    def test_kontingent_jobs_erschoepft(self):
        decision = evaluate(req(source="mqtt"), usage=Usage(jobs=10))
        assert not decision.allowed
        assert "10 Jobs pro Stunde" in decision.message()

    def test_kontingent_tape_erschoepft(self):
        decision = evaluate(req(source="mqtt", tape_mm=30.0), usage=Usage(tape_mm=480.0))
        assert not decision.allowed
        assert "500 mm pro Stunde" in decision.message()

    def test_kontingent_gilt_nur_fuer_bekannte_quellen(self):
        decision = evaluate(req(source="cli"), usage=Usage(jobs=10_000, tape_mm=10_000_000.0))
        assert decision.allowed

    def test_mehrere_gruende_werden_gesammelt(self):
        decision = evaluate(req(copies=60, label_mm=600.0))
        assert not decision.allowed
        assert len(decision.reasons) >= 2

    def test_unbekannte_quelle_wirft_value_error(self):
        with pytest.raises(ValueError):
            evaluate(req(source="fax"))


class TestLoadPolicy:
    def test_uebernimmt_einzelne_felder_und_quotas(self):
        policy = load_policy(
            {
                "guard": {
                    "confirm_copies": 3,
                    "quotas": {"api": {"jobs_per_hour": 2, "mm_per_hour": 100}},
                }
            }
        )
        assert policy.confirm_copies == 3
        assert policy.quotas["api"] == Quota(2, 100.0)
        assert policy.quotas["mqtt"] == DEFAULT_QUOTAS["mqtt"]

    def test_unbekannter_schluessel_wirft_value_error(self):
        with pytest.raises(ValueError, match="guard.foo"):
            load_policy({"guard": {"foo": 1}})

    def test_negative_zahl_wirft_value_error(self):
        with pytest.raises(ValueError):
            load_policy({"guard": {"confirm_copies": -1}})

    def test_ohne_guard_schluessel_liefert_defaults(self):
        policy = load_policy({})
        assert policy == GuardPolicy()


class TestGuardRejected:
    def test_ist_value_error_und_zeigt_gruende(self):
        decision = evaluate(req(copies=51))
        err = GuardRejected(decision)
        assert isinstance(err, ValueError)
        assert "Obergrenze" in str(err)


class TestDebouncer:
    def test_gleicher_key_innerhalb_intervall_wird_abgelehnt(self):
        now = [0.0]
        deb = Debouncer(min_interval_s=1.5, clock=lambda: now[0])
        assert deb.accept("a") is True
        now[0] = 1.0
        assert deb.accept("a") is False
        now[0] = 1.6
        assert deb.accept("a") is True

    def test_anderer_key_ist_sofort_erlaubt(self):
        now = [0.0]
        deb = Debouncer(min_interval_s=1.5, clock=lambda: now[0])
        assert deb.accept("a") is True
        assert deb.accept("b") is True

    def test_running_wirft_bei_verschachtelung(self):
        deb = Debouncer()
        with deb.running():
            with pytest.raises(JobRunning):
                with deb.running():
                    pass

    def test_running_ist_nach_verlassen_wieder_frei(self):
        deb = Debouncer()
        with deb.running():
            pass
        with deb.running():
            pass

    def test_running_aus_zwei_threads_nur_einer_gewinnt(self):
        deb = Debouncer()
        results = []
        barrier = threading.Barrier(2)
        release = threading.Event()

        def worker():
            barrier.wait()
            try:
                with deb.running():
                    results.append("ok")
                    release.wait(2.0)
            except JobRunning:
                results.append("blocked")

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        time.sleep(0.2)
        release.set()
        t1.join(2.0)
        t2.join(2.0)

        assert sorted(results) == ["blocked", "ok"]


class TestContentKey:
    def _img(self, color=0):
        return Image.new("1", (8, 4), color)

    def test_gleiche_bilder_gleicher_key(self):
        a = [self._img()]
        b = [self._img()]
        assert content_key("cli", a) == content_key("cli", b)

    def test_ein_pixel_anders_anderer_key(self):
        a = self._img()
        b = self._img()
        b.putpixel((0, 0), 255)
        assert content_key("cli", [a]) != content_key("cli", [b])

    def test_andere_quelle_anderer_key(self):
        a = [self._img()]
        assert content_key("cli", a) != content_key("gui", a)
