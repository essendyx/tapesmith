"""Tests für `tapesmith.apitokens`."""

import json
import re
from datetime import datetime, timedelta

import pytest

from tapesmith.apitokens import ROLES, TokenInfo, TokenStore

SECRET_RE = re.compile(r"^p12_[0-9a-f]{8}_[A-Za-z0-9_-]{20,}$")


def store(tmp_path, **kw) -> TokenStore:
    return TokenStore(tmp_path / "tokens.json", **kw)


def test_create_liefert_klartext_passend_zum_muster(tmp_path):
    st = store(tmp_path)
    info, secret = st.create("Handy", "familie")
    assert SECRET_RE.match(secret)
    assert info.role == "familie"
    text = st.path.read_text(encoding="utf-8")
    assert secret not in text
    assert "sha256:" in text


def test_verify_roundtrip(tmp_path):
    st = store(tmp_path)
    _info, secret = st.create("Handy", "familie")
    verified = st.verify(secret)
    assert verified is not None
    assert verified.name == "Handy"

    assert st.verify(secret + "x") is None
    assert st.verify("p12_00000000_" + "a" * 43) is None
    assert st.verify("") is None
    assert st.verify("Bearer x") is None


def test_zwei_stores_auf_derselben_datei_mtime_reload(tmp_path):
    a = store(tmp_path)
    b = store(tmp_path)
    _info, secret = a.create("Handy", "familie")

    verified = b.verify(secret)
    assert verified is not None and verified.name == "Handy"

    a.revoke("Handy")
    assert b.verify(secret) is None


def test_revoke_per_name_und_id(tmp_path):
    st = store(tmp_path)
    info, _secret = st.create("Handy", "familie")
    st.revoke(info.id)
    assert st.list() == []

    info2, _secret2 = st.create("Tablet", "drucken")
    st.revoke("Tablet")
    assert st.list() == []


def test_revoke_unbekannt_key_error(tmp_path):
    st = store(tmp_path)
    with pytest.raises(KeyError):
        st.revoke("nichts-da")


def test_revoke_mehrdeutig_value_error(tmp_path):
    st = store(tmp_path, now=lambda: datetime(2026, 1, 1))
    # Zwei Einträge mit demselben Namen lassen sich nur über id anlegen (create verbietet
    # doppelte Namen); wir erzeugen die Mehrdeutigkeit hier direkt in der Datei.
    st.create("Eins", "familie")
    data = json.loads(st.path.read_text(encoding="utf-8"))
    dup = dict(data["tokens"][0])
    dup["id"] = "deadbeef"
    data["tokens"].append(dup)
    st.path.write_text(json.dumps(data), encoding="utf-8")
    st2 = store(tmp_path, now=lambda: datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        st2.revoke("Eins")


def test_create_name_doppelt_case_insensitiv(tmp_path):
    st = store(tmp_path)
    st.create("Handy", "familie")
    with pytest.raises(ValueError):
        st.create("handy", "familie")


def test_create_unbekannte_rolle(tmp_path):
    st = store(tmp_path)
    with pytest.raises(ValueError):
        st.create("Gast", "gast")


def test_last_used_gesetzt_und_gedrosselt(tmp_path):
    now = {"t": datetime(2026, 1, 1, 10, 0, 0)}
    st = store(tmp_path, now=lambda: now["t"], touch_interval_s=600.0)
    _info, secret = st.create("Handy", "familie")

    verified = st.verify(secret)
    assert verified.last_used is not None
    mtime_1 = st.path.stat().st_mtime

    now["t"] += timedelta(seconds=5)
    st.verify(secret)
    mtime_2 = st.path.stat().st_mtime
    assert mtime_1 == mtime_2

    now["t"] += timedelta(seconds=700)
    st.verify(secret)
    mtime_3 = st.path.stat().st_mtime
    assert mtime_3 != mtime_2


def test_verify_kaputte_datei_liefert_none(tmp_path):
    st = store(tmp_path)
    st.create("Handy", "familie")
    st.path.write_text("{kaputt", encoding="utf-8")
    assert st.verify("p12_00000000_" + "a" * 30) is None


def test_to_json_schluessel(tmp_path):
    st = store(tmp_path)
    info, _secret = st.create("Handy", "familie")
    data = info.to_json()
    assert set(data) == {"id", "name", "role", "role_label", "created", "last_used", "hint"}
    assert "hash" not in data
    assert data["role_label"] == "Familie"


def test_find(tmp_path):
    st = store(tmp_path)
    info, _secret = st.create("Handy", "familie")
    assert st.find(info.id).name == "Handy"
    assert st.find("Handy").id == info.id
    assert st.find("unbekannt") is None


def test_roles_konstante():
    assert ROLES == ("admin", "drucken", "familie")


def test_default_path_unter_app_dir(app_home):
    st = TokenStore()
    assert st.path == app_home / "access" / "tokens.json"
