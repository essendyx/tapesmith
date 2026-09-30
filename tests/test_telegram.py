"""Telegram-Meldungen (Addon), Versand nur über einen Fake-Poster, nie echte Nachrichten."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import pytest

from automation_fakes import FakeClock, FakeFacade, FakeNow, queue_json, queued_job, state_json
from tapesmith.automation import telegram

TOKEN = "123:abc"


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "result": {}}

    def json(self) -> dict:
        return self._payload


class FakePoster:
    """Zeichnet (url, json) auf und liefert eine feste Antwort (oder wirft)."""

    def __init__(self, response: FakeResponse | None = None, raise_exc: Exception | None = None):
        self.response = response or FakeResponse()
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, dict]] = []
        self.block: threading.Event | None = None

    def __call__(self, url, json=None, timeout=None):
        if self.block is not None:
            self.block.wait(30)
        self.calls.append((url, json))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response

    @property
    def texts(self) -> list[str]:
        return [j["text"] for _u, j in self.calls]


def _cfg(**tg) -> dict:
    base = {"enabled": True, "token_ref": "env:P12_TEST_TG", "chat_id": 4711, "quiet_hours": None}
    base.update(tg)
    return {"telegram": base}


def _notifier(facade=None, cfg=None, *, poster=None, now=None, clock=None, reader=None):
    facade = facade if facade is not None else FakeFacade()
    poster = poster if poster is not None else FakePoster()
    now = now if now is not None else FakeNow(datetime(2026, 9, 28, 12, 0, 0))
    clock = clock if clock is not None else FakeClock()
    n = telegram.TelegramNotifier(facade, cfg if cfg is not None else _cfg(), http_post=poster,
                                  secret_reader=reader or (lambda ref, **kw: TOKEN), now=now, clock=clock,
                                  hostname="PC1")
    n._token = TOKEN  # wie nach start(), aber ohne Thread
    n._chat_id = 4711
    facade.subscribe(n._on_event)
    return n, facade, poster, now, clock


# ---------- send_message / send_test ----------

def test_send_message_url_und_json():
    poster = FakePoster()
    telegram.send_message(TOKEN, 4711, "Hallo", http_post=poster)
    url, body = poster.calls[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert body == {"chat_id": 4711, "text": "Hallo"}


@pytest.mark.parametrize("response", [
    FakeResponse(401, {"ok": False, "description": "Unauthorized"}),
    FakeResponse(200, {"ok": False, "description": "Unauthorized"}),
])
def test_send_message_fehler_ohne_token(response):
    with pytest.raises(telegram.TelegramError) as info:
        telegram.send_message(TOKEN, 4711, "x", http_post=FakePoster(response))
    assert TOKEN not in str(info.value)
    assert "Unauthorized" in str(info.value)


def test_send_message_netzfehler_ohne_token():
    exc = ConnectionError(f"kaputt bei https://api.telegram.org/bot{TOKEN}/sendMessage")
    with pytest.raises(telegram.TelegramError) as info:
        telegram.send_message(TOKEN, 4711, "x", http_post=FakePoster(raise_exc=exc))
    assert TOKEN not in str(info.value)
    assert "api.telegram.org" not in str(info.value)


def test_send_test_ohne_chat_id():
    ok, err = telegram.send_test(_cfg(chat_id=None), http_post=FakePoster())
    assert ok is False
    assert err.startswith("Chat-ID fehlt")


def test_send_test_mit_token_datei(tmp_path):
    token_file = tmp_path / "t.txt"
    token_file.write_text("BOT_TOKEN=123:abc\n", encoding="utf-8")
    poster = FakePoster()
    cfg = _cfg(token_ref=f"file:{token_file}", enabled=False)
    assert telegram.send_test(cfg, http_post=poster) == (True, None)
    url, body = poster.calls[0]
    assert "bot123:abc/" in url
    assert body["chat_id"] == 4711
    assert body["text"].startswith("Tapesmith: Testnachricht vom Druckdienst auf ")


def test_send_test_token_fehlt(tmp_path):
    ok, err = telegram.send_test(_cfg(token_ref=f"file:{tmp_path / 'nix.txt'}"), http_post=FakePoster())
    assert ok is False
    assert "fehlt" in err


def test_send_test_versandfehler(tmp_path):
    token_file = tmp_path / "t.txt"
    token_file.write_text("123:abc", encoding="utf-8")
    poster = FakePoster(FakeResponse(401, {"ok": False, "description": "Unauthorized"}))
    ok, err = telegram.send_test(_cfg(token_ref=f"file:{token_file}"), http_post=poster)
    assert ok is False
    assert TOKEN not in err


# ---------- create / start ----------

def test_create_aus_ist_none():
    assert telegram.create(FakeFacade(), {"telegram": {"enabled": False}}) is None
    assert telegram.create(FakeFacade(), {}) is None


def test_create_an_liefert_notifier():
    addon = telegram.create(FakeFacade(), _cfg())
    assert isinstance(addon, telegram.TelegramNotifier)
    assert addon.name == "telegram"


def test_start_ohne_token_setzt_fehler_kein_thread():
    def reader(ref, **kw):
        raise telegram.SecretMissing("Umgebungsvariable P12_TEST_TG fehlt oder ist leer")

    facade = FakeFacade()
    n = telegram.TelegramNotifier(facade, _cfg(), http_post=FakePoster(), secret_reader=reader)
    n.start()
    st = n.status()
    assert st["running"] is False
    assert "fehlt" in st["error"]
    assert n._thread is None
    assert facade.subscribers == []
    n.stop()


def test_start_ohne_chat_id_setzt_fehler():
    n = telegram.TelegramNotifier(FakeFacade(), _cfg(chat_id=None), http_post=FakePoster(),
                                  secret_reader=lambda ref, **kw: TOKEN)
    n.start()
    assert n.status()["error"].startswith("Chat-ID fehlt")
    assert n._thread is None


# ---------- Warteschlange ----------

def _stuck_facade(minutes: float, *, now: datetime, count: int = 1) -> FakeFacade:
    created = (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    jobs = [queued_job(i + 1, created=created) for i in range(count)]
    q = queue_json(jobs)
    q["waiting_reason"] = "Drucker aus"
    return FakeFacade(queue=q)


def test_warteschlange_haengt_einmal_und_erholung():
    now = FakeNow(datetime(2026, 9, 28, 12, 0, 0))
    facade = _stuck_facade(16, now=now.now)
    n, _f, poster, _now, _clock = _notifier(facade, _cfg(queue_stuck_min=15), now=now)
    n.check()
    assert poster.texts == ["Tapesmith: Warteschlange hängt seit 16 min, 1 Aufträge warten (Drucker aus)."]
    n.check()
    assert len(poster.texts) == 1
    facade.queue_value = queue_json([])
    n.check()
    assert poster.texts[-1] == "Tapesmith: Warteschlange läuft wieder."
    facade.queue_value = _stuck_facade(20, now=now.now, count=2).queue_value
    n.check()
    assert len(poster.texts) == 3
    assert "seit 20 min, 2 Aufträge warten" in poster.texts[-1]


def test_warteschlange_juenger_als_schwelle_und_grund_unbekannt():
    now = FakeNow(datetime(2026, 9, 28, 12, 0, 0))
    facade = _stuck_facade(10, now=now.now)
    facade.queue_value["waiting_reason"] = ""
    n, _f, poster, _now, _clock = _notifier(facade, _cfg(queue_stuck_min=15), now=now)
    n.check()
    assert poster.texts == []
    now.advance(minutes=6)
    n.check()
    assert poster.texts == ["Tapesmith: Warteschlange hängt seit 16 min, 1 Aufträge warten (unbekannt)."]


def test_warteschlange_zaehlt_nur_wartende():
    now = FakeNow(datetime(2026, 9, 28, 12, 0, 0))
    old = (now.now - timedelta(minutes=60)).isoformat(timespec="seconds")
    facade = FakeFacade(queue=queue_json([queued_job(1, state="druckt", created=old)]))
    n, _f, poster, _now, _clock = _notifier(facade, now=now)
    n.check()
    assert poster.texts == []


def test_abschalter_notify_queue():
    now = FakeNow(datetime(2026, 9, 28, 12, 0, 0))
    facade = _stuck_facade(16, now=now.now)
    facade.state_value = state_json("offline", None)
    n, _f, poster, _now, clock = _notifier(facade, _cfg(notify_queue=False, offline_min=30), now=now)
    n.check()
    clock.advance(31 * 60)
    n.check()
    assert len(poster.texts) == 1
    assert "nicht erreichbar" in poster.texts[0]


# ---------- Offline ----------

def test_offline_nach_schwelle_und_wieder_erreichbar():
    facade = FakeFacade(state=state_json("offline", None))
    n, _f, poster, _now, clock = _notifier(facade, _cfg(offline_min=30))
    n.check()
    clock.advance(29 * 60)
    n.check()
    assert poster.texts == []
    clock.advance(2 * 60)
    n.check()
    assert poster.texts == ["Tapesmith: Drucker seit 31 min nicht erreichbar."]
    n.check()
    assert len(poster.texts) == 1
    facade.state_value = state_json("verbunden")
    n.check()
    assert poster.texts[-1] == "Tapesmith: Drucker wieder erreichbar."


def test_offline_mit_wartenden_auftraegen_und_zustand_fehler():
    now = FakeNow(datetime(2026, 9, 28, 12, 0, 0))
    created = now.now.isoformat(timespec="seconds")
    facade = FakeFacade(state=state_json("fehler", None),
                        queue=queue_json([queued_job(1, created=created), queued_job(2, created=created)]))
    n, _f, poster, _now, clock = _notifier(facade, _cfg(offline_min=30, notify_queue=False), now=now)
    n.check()
    clock.advance(30 * 60)
    n.check()
    assert poster.texts == ["Tapesmith: Drucker seit 30 min nicht erreichbar, 2 Aufträge warten."]


def test_offline_zeit_ab_state_ereignis():
    facade = FakeFacade()
    n, _f, poster, _now, clock = _notifier(facade, _cfg(offline_min=30))
    facade.emit("state", state_json("offline", None))
    facade.state_value = state_json("offline", None)
    clock.advance(10 * 60)
    n.check()   # verarbeitet das Ereignis mit dem Zeitpunkt des Empfangs
    clock.advance(21 * 60)
    n.check()
    assert poster.texts == ["Tapesmith: Drucker seit 31 min nicht erreichbar."]


def test_verbunden_setzt_offline_zeit_zurueck():
    facade = FakeFacade(state=state_json("offline", None))
    n, _f, poster, _now, clock = _notifier(facade, _cfg(offline_min=30))
    n.check()
    clock.advance(20 * 60)
    facade.state_value = state_json("verbunden")
    n.check()
    facade.state_value = state_json("offline", None)
    clock.advance(20 * 60)
    n.check()
    assert poster.texts == []


# ---------- Druckfehler ----------

def _job(status="fehler", title="SSD-1", source="api", **kw) -> dict:
    data = {"job_key": "k", "phase": "fertig", "status": status, "source": source, "title": title,
            "queue_id": None}
    data.update(kw)
    return data


def test_druckfehler_meldung():
    n, facade, poster, _now, _clock = _notifier()
    facade.emit("job", _job())
    n.check()
    assert poster.texts == ["Tapesmith: Druckfehler bei „SSD-1“ (Quelle api, Status fehler)."]


def test_druckfehler_unvollstaendig_und_ok_ignoriert():
    n, facade, poster, _now, clock = _notifier()
    facade.emit("job", _job(status="ok"))
    facade.emit("job", {**_job(), "phase": "start"})
    n.check()
    assert poster.texts == []
    facade.emit("job", _job(status="unvollständig", title="A"))
    n.check()
    assert poster.texts == ["Tapesmith: Druckfehler bei „A“ (Quelle api, Status unvollständig)."]


def test_drei_fehler_eine_meldung():
    n, facade, poster, _now, _clock = _notifier()
    for t in ("SSD-1", "SSD-2", "SSD-3"):
        facade.emit("job", _job(title=t))
    n.check()
    assert poster.texts == ["Tapesmith: Druckfehler bei „SSD-1“ (Quelle api, Status fehler) und 2 weitere."]


def test_fehler_innerhalb_5_min_gebuendelt():
    n, facade, poster, _now, clock = _notifier()
    facade.emit("job", _job(title="A"))
    n.check()
    clock.advance(60)
    facade.emit("job", _job(title="B"))
    facade.emit("job", _job(title="C"))
    n.check()
    assert len(poster.texts) == 1
    clock.advance(4 * 60 + 1)
    n.check()
    assert poster.texts[-1] == "Tapesmith: Druckfehler bei „B“ (Quelle api, Status fehler) und 1 weitere."


def test_druckfehler_sensibel():
    # state="druckt" (nicht "wartet"): der Fixtur-Auftrag soll nur für die Sensibel-Erkennung über
    # queue_id dienen, nicht zusätzlich die Warteschlangen-Meldung auslösen (er ist bewusst alt).
    queue = queue_json([queued_job(7, state="druckt", sensitive=True, title="Geheim")])
    n, facade, poster, _now, _clock = _notifier(FakeFacade(queue=queue))
    facade.emit("job", _job(title="Geheim", queue_id=7))
    n.check()
    facade.emit("job", _job(title=""))
    n._last_error_sent = None
    n.check()
    assert len(poster.texts) == 2
    for text in poster.texts:
        assert "(sensibel)" in text
        assert "Geheim" not in text


def test_notify_error_aus():
    n, facade, poster, _now, _clock = _notifier(cfg=_cfg(notify_error=False))
    facade.emit("job", _job())
    n.check()
    assert poster.texts == []


# ---------- Restmeter ----------

def test_restmeter_niedrig_einmal_und_neue_rolle():
    facade = FakeFacade(remaining_m=0.4)
    n, _f, poster, _now, _clock = _notifier(facade, _cfg(roll_low_m=0.5))
    n.check()
    assert poster.texts == ["Tapesmith: Rolle fast leer, geschätzt noch 0,4 m."]
    facade.remaining_value = 0.3
    n.check()
    assert len(poster.texts) == 1
    facade.remaining_value = None
    n.check()
    facade.remaining_value = 0.2
    n.check()
    assert len(poster.texts) == 1
    facade.remaining_value = 20.0
    n.check()
    facade.remaining_value = 0.3
    n.check()
    assert poster.texts[-1] == "Tapesmith: Rolle fast leer, geschätzt noch 0,3 m."
    assert len(poster.texts) == 2


def test_restmeter_none_nichts():
    n, _f, poster, _now, _clock = _notifier(FakeFacade(remaining_m=None))
    n.check()
    assert poster.texts == []


def test_restmeter_nach_job_ok_ereignis():
    facade = FakeFacade(remaining_m=5.0)
    n, _f, poster, _now, _clock = _notifier(facade, _cfg(roll_low_m=0.5))
    n.check()
    facade.remaining_value = 0.4
    facade.emit("job", _job(status="ok"))
    n.check()
    assert poster.texts == ["Tapesmith: Rolle fast leer, geschätzt noch 0,4 m."]


# ---------- Ruhezeit ----------

def test_ruhezeit_zustand_nach_ende_gesendet():
    now = FakeNow(datetime(2026, 9, 28, 23, 30, 0))
    facade = _stuck_facade(16, now=now.now)
    n, _f, poster, _now, clock = _notifier(facade, _cfg(quiet_hours="22:00-07:00"), now=now)
    n.check()
    assert poster.texts == []
    now.now = datetime(2026, 9, 29, 7, 1, 0)
    clock.advance(7 * 3600)
    n.check()
    assert len(poster.texts) == 1
    assert "Warteschlange hängt" in poster.texts[0]


def test_ruhezeit_druckfehler_gesammelt():
    now = FakeNow(datetime(2026, 9, 29, 2, 0, 0))
    n, facade, poster, _now, clock = _notifier(cfg=_cfg(quiet_hours="22:00-07:00"), now=now)
    facade.emit("job", _job(title="Nacht"))
    n.check()
    assert poster.texts == []
    now.now = datetime(2026, 9, 29, 7, 1, 0)
    clock.advance(5 * 3600)
    n.check()
    assert poster.texts == ["Tapesmith: 1 Druckfehler während der Ruhezeit, zuletzt „Nacht“."]


def test_ruhezeit_erholung_entfaellt():
    now = FakeNow(datetime(2026, 9, 28, 21, 0, 0))
    facade = FakeFacade(state=state_json("offline", None))
    n, _f, poster, _now, clock = _notifier(facade, _cfg(quiet_hours="22:00-07:00", offline_min=30), now=now)
    n.check()
    clock.advance(31 * 60)
    n.check()
    assert len(poster.texts) == 1
    now.now = datetime(2026, 9, 28, 23, 0, 0)
    facade.state_value = state_json("verbunden")
    n.check()
    now.now = datetime(2026, 9, 29, 8, 0, 0)
    n.check()
    assert len(poster.texts) == 1


def test_ruhezeit_none_immer_senden():
    now = FakeNow(datetime(2026, 9, 29, 3, 0, 0))
    n, facade, poster, _now, _clock = _notifier(cfg=_cfg(quiet_hours=None), now=now)
    facade.emit("job", _job())
    n.check()
    assert len(poster.texts) == 1


@pytest.mark.parametrize("spec, hour, minute, quiet", [
    ("22:00-07:00", 22, 0, True), ("22:00-07:00", 6, 59, True), ("22:00-07:00", 7, 0, False),
    ("22:00-07:00", 12, 0, False), ("12:00-13:00", 12, 30, True), ("12:00-13:00", 13, 0, False),
])
def test_in_quiet_hours(spec, hour, minute, quiet):
    assert telegram.in_quiet_hours(spec, datetime(2026, 9, 28, hour, minute)) is quiet


# ---------- Versandfehler ----------

def test_versand_scheitert_retry_nach_5_min():
    poster = FakePoster(FakeResponse(500, {"ok": False, "description": "Bad Gateway"}))
    facade = FakeFacade(remaining_m=0.4)
    n, _f, _p, _now, clock = _notifier(facade, _cfg(roll_low_m=0.5), poster=poster)
    n.check()
    assert len(poster.calls) == 1
    st = n.status()
    assert "Bad Gateway" in st["error"]
    assert st["detail"].startswith("letzter Versand fehlgeschlagen: ")
    assert TOKEN not in st["error"] and TOKEN not in st["detail"]
    clock.advance(4 * 60)
    n.check()
    assert len(poster.calls) == 1
    poster.response = FakeResponse()
    clock.advance(61)
    n.check()
    assert len(poster.calls) == 2
    assert n.status()["error"] is None
    n.check()
    assert len(poster.calls) == 2


def test_offline_erholung_scheitert_und_wird_wiederholt():
    # Eine gescheiterte Erholungsmeldung ("Drucker wieder erreichbar.") galt bisher
    # sofort als gesendet und wurde nie erneut versucht. Sie muss wie jede andere Meldung erst
    # nach einem erfolgreichen Versand als erledigt gelten (Retry frühestens nach 5 min).
    poster = FakePoster()
    facade = FakeFacade(state=state_json("offline", None))
    n, _f, _p, _now, clock = _notifier(facade, _cfg(offline_min=30), poster=poster)
    n.check()
    clock.advance(31 * 60)
    n.check()
    assert len(poster.calls) == 1
    assert poster.texts[-1] == "Tapesmith: Drucker seit 31 min nicht erreichbar."

    facade.state_value = state_json("verbunden")
    poster.response = FakeResponse(500, {"ok": False, "description": "Bad Gateway"})
    n.check()
    assert len(poster.calls) == 2   # Erholung versucht, aber gescheitert: nicht verloren
    assert "Bad Gateway" in n.status()["error"]

    n.check()
    assert len(poster.calls) == 2   # kein erneuter Versuch vor Ablauf der 5-Minuten-Sperre

    clock.advance(5 * 60)
    poster.response = FakeResponse()
    n.check()
    assert len(poster.calls) == 3
    assert poster.texts[-1] == "Tapesmith: Drucker wieder erreichbar."
    assert n.status()["error"] is None

    n.check()
    assert len(poster.calls) == 3   # jetzt endgültig erledigt, keine weitere Erholungsmeldung


def test_status_detail_aktiv():
    n, *_ = _notifier(cfg=_cfg(quiet_hours="22:00-07:00"))
    assert n.status()["detail"] == "aktiv, Ruhezeit 22:00-07:00"
    n2, *_ = _notifier(cfg=_cfg(quiet_hours=None))
    assert n2.status()["detail"] == "aktiv, keine Ruhezeit"


def test_keine_meldung_zu_band_oder_akku():
    facade = FakeFacade(remaining_m=10.0)
    n, _f, poster, _now, _clock = _notifier(facade)
    facade.emit("status", {"battery": 5, "media": "leer"})
    n.check()
    assert poster.texts == []


# ---------- Nebenläufigkeit ----------

def test_on_event_blockiert_nie():
    poster = FakePoster()
    poster.block = threading.Event()
    facade = FakeFacade()
    n = telegram.TelegramNotifier(facade, _cfg(), http_post=poster, secret_reader=lambda ref, **kw: TOKEN,
                                  tick_s=0.01, hostname="PC1")
    n.start()
    try:
        t0 = time.monotonic()
        facade.emit("job", _job())
        facade.emit("job", _job(title="B"))
        assert time.monotonic() - t0 < 5.0      # der Versand hängt, bis der Test ihn freigibt
    finally:
        poster.block.set()
        n.stop()


def test_thread_start_stop():
    facade = FakeFacade()
    poster = FakePoster()
    n = telegram.TelegramNotifier(facade, _cfg(), http_post=poster, secret_reader=lambda ref, **kw: TOKEN,
                                  tick_s=0.01, hostname="PC1")
    n.start()
    thread = n._thread
    assert thread is not None and thread.name == "p12-telegram" and thread.daemon
    assert n.status()["running"] is True
    facade.emit("job", _job())
    deadline = time.monotonic() + 2
    while not poster.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert poster.texts and "SSD-1" in poster.texts[0]
    n.stop()
    assert not thread.is_alive()
    assert n.status()["running"] is False
