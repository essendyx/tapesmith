import pytest

from tapesmith.jobs import KINDS, SOURCES, CancelToken, IncompletePrint, JobMeta, spec_from_dict, spec_to_dict
from tapesmith.render.compose import LabelSpec
from tapesmith.transport.base import TransportError


def test_job_meta_defaults():
    meta = JobMeta()
    assert meta.source == "cli"
    assert meta.kind == "image"
    assert meta.title == ""
    assert meta.template is None
    assert meta.values == {}
    assert meta.sensitive is False
    assert meta.spec is None


def test_job_meta_rejects_invalid_source():
    with pytest.raises(ValueError):
        JobMeta(source="carrier-pigeon")


def test_job_meta_rejects_invalid_kind():
    with pytest.raises(ValueError):
        JobMeta(kind="postcard")


def test_job_meta_sources_and_kinds_are_valid():
    for source in SOURCES:
        JobMeta(source=source)
    for kind in KINDS:
        JobMeta(kind=kind)


def test_job_meta_to_dict_is_json_ready():
    meta = JobMeta(source="gui", kind="text", title="Test", values={"a": "b"})
    d = meta.to_dict()
    assert d["source"] == "gui"
    assert d["kind"] == "text"
    assert d["title"] == "Test"
    assert d["values"] == {"a": "b"}


def test_spec_round_trip():
    spec = LabelSpec(lines=("a", "b"), qr="x", max_length_mm=40.0)
    data = spec_to_dict(spec)
    assert data["lines"] == ["a", "b"]
    restored = spec_from_dict(data)
    assert restored == spec
    assert restored.lines == ("a", "b")


def test_spec_from_dict_rejects_unknown_key():
    data = spec_to_dict(LabelSpec(lines=("a",)))
    data["unbekannt"] = 1
    with pytest.raises(ValueError):
        spec_from_dict(data)


def test_cancel_token_lifecycle():
    token = CancelToken()
    assert token.cancelled is False
    assert token.wait(0.01) is False
    token.cancel()
    assert token.cancelled is True
    assert token.wait(0.01) is True


def test_incomplete_print_is_transport_error():
    exc = IncompletePrint("x", 5, 10)
    assert isinstance(exc, TransportError)
    assert exc.rows_sent == 5
    assert exc.rows_total == 10
    assert str(exc) == "x"
