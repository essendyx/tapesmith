"""Begrenzung der Fehlversuche je Client-Adresse (Einheit und über die Middleware)."""

import threading

import pytest

from tapesmith.webapi.access import LanPolicy
from tapesmith.webapi.ratelimit import FailureLimiter
from webapi_fakes import close_ctx, make_client, make_token


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


def test_nine_failures_free_tenth_blocks(clock):
    lim = FailureLimiter(clock=clock)
    for _ in range(9):
        lim.failure("a")
    assert lim.blocked("a") == 0.0
    lim.failure("a")
    assert lim.blocked("a") == pytest.approx(900.0)
    assert lim.blocked("b") == 0.0
    clock.now += 899.5
    assert lim.blocked("a") == pytest.approx(0.5)
    clock.now += 0.5
    assert lim.blocked("a") == 0.0
    lim.failure("a")                       # nach der Sperre beginnt die Zählung neu
    assert lim.blocked("a") == 0.0


def test_failures_outside_window_expire(clock):
    lim = FailureLimiter(clock=clock, max_failures=3, window_s=10.0, lockout_s=60.0)
    lim.failure("a")
    lim.failure("a")
    clock.now += 11
    lim.failure("a")
    assert lim.blocked("a") == 0.0
    lim.failure("a")
    assert lim.blocked("a") == 0.0
    lim.failure("a")
    assert lim.blocked("a") == pytest.approx(60.0)


def test_success_resets(clock):
    lim = FailureLimiter(clock=clock, max_failures=3)
    lim.failure("a")
    lim.failure("a")
    lim.success("a")
    lim.failure("a")
    lim.failure("a")
    assert lim.blocked("a") == 0.0


def test_max_entries_bounds_memory(clock):
    lim = FailureLimiter(clock=clock, max_entries=5)
    for i in range(50):
        lim.failure(f"10.0.0.{i}")
    assert len(lim) <= 5
    assert lim.tracked() == [f"10.0.0.{i}" for i in range(45, 50)]


def test_expired_entries_cleaned(clock):
    lim = FailureLimiter(clock=clock, max_failures=2, window_s=10.0, lockout_s=20.0, max_entries=100)
    lim.failure("a")
    lim.failure("b")
    lim.failure("b")                        # b gesperrt
    clock.now += 30
    lim.failure("c")
    assert lim.tracked() == ["c"]


def test_thread_safe(clock):
    lim = FailureLimiter(clock=clock, max_failures=10_000, max_entries=10_000)

    def worker(n):
        for i in range(200):
            lim.failure(f"{n}-{i % 20}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(lim) == 160


# ---------------------------------------------------------------- über die Middleware

LAN = LanPolicy(enabled=True, networks=("192.0.2.0/24",), hosts=frozenset({"192.0.2.50"}))


@pytest.fixture
def lan_client(tmp_path, clock):
    client, ctx = make_client(tmp_path, client_ip="192.0.2.77", lan=LAN, auth=None,
                              base_url="http://192.0.2.50:8712", limiter=FailureLimiter(clock=clock))
    yield client, ctx
    close_ctx(ctx)


def test_lockout_via_middleware(lan_client, clock):
    client, ctx = lan_client
    good = make_token(ctx, "admin")
    bad = {"Authorization": "Bearer p12_deadbeef_" + "x" * 30}
    for _ in range(10):
        assert client.get("/api/v1/app", headers=bad).status_code == 401
    r = client.get("/api/v1/app", headers=bad)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "900"
    assert r.json()["error"]["message"] == "Zu viele Fehlversuche, bitte später erneut versuchen"
    assert client.get("/api/v1/app", headers={"Authorization": f"Bearer {good}"}).status_code == 429
    assert client.get("/health").status_code == 429
    clock.now += 0.4
    assert client.get("/health").headers["retry-after"] == "900"     # aufgerundet
    clock.now += 900
    assert client.get("/api/v1/app", headers={"Authorization": f"Bearer {good}"}).status_code == 200


def test_other_address_not_blocked(lan_client, tmp_path):
    client, ctx = lan_client
    for _ in range(10):
        client.get("/api/v1/app", headers={"Authorization": "Bearer falsch"})
    assert client.get("/health").status_code == 429
    assert ctx.limiter.blocked("192.0.2.78") == 0.0


def test_missing_token_does_not_count(lan_client):
    client, ctx = lan_client
    for _ in range(15):
        assert client.get("/api/v1/app").status_code == 401
    assert ctx.limiter.blocked("192.0.2.77") == 0.0


def test_success_resets_counter(lan_client):
    client, ctx = lan_client
    good = make_token(ctx, "admin")
    for _ in range(9):
        client.get("/api/v1/app", headers={"Authorization": "Bearer falsch"})
    assert client.get("/api/v1/app", headers={"Authorization": f"Bearer {good}"}).status_code == 200
    for _ in range(9):
        client.get("/api/v1/app", headers={"Authorization": "Bearer falsch"})
    assert client.get("/health").status_code == 200


def test_loopback_never_blocked(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        for _ in range(20):
            assert client.get("/api/v1/app", headers={"X-P12-Token": "falsch"}).status_code == 401
        assert client.get("/api/v1/app", headers={"X-P12-Token": "test-token"}).status_code == 200
        assert len(ctx.limiter) == 0
    finally:
        close_ctx(ctx)
