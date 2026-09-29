"""TIA-606-ID-Schema, freie IDs und Kabel-Register."""

import pytest

from tapesmith.integrations import tia606
from tapesmith.numbering import NumberRanges


def test_render_id_default_pattern():
    assert tia606.render_id("{rack}.U{unit:02}:P{port:02}", rack="R1", unit=12, port=3) == "R1.U12:P03"


def test_render_id_unknown_field_raises():
    with pytest.raises(ValueError):
        tia606.render_id("{foo}", rack="R1", unit=1, port=1)


def test_parse_numbers_list_and_ranges():
    assert tia606.parse_numbers("1,3,5-7") == (1, 3, 5, 6, 7)


@pytest.mark.parametrize("spec", ["0", "5-3", "1-3000"])
def test_parse_numbers_invalid(spec):
    with pytest.raises(ValueError):
        tia606.parse_numbers(spec)


def test_generate_two_racks_in_order():
    ranges = [
        tia606.PortRange(rack="R1", units=(1,), ports=(1, 2)),
        tia606.PortRange(rack="R2", units=(1,), ports=(1,)),
    ]
    ids = tia606.generate("{rack}.U{unit:02}:P{port:02}", ranges)
    assert ids == ["R1.U01:P01", "R1.U01:P02", "R2.U01:P01"]


def test_generate_duplicates_raise():
    ranges = [tia606.PortRange(rack="R1", units=(1, 1), ports=(1,))]
    with pytest.raises(ValueError):
        tia606.generate("{rack}.U{unit:02}:P{port:02}", ranges)


def test_free_ids_defines_circle_and_assigns(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = {"kabel": {"range": "kabel", "prefix": "K-", "width": 3}}
    assert tia606.free_ids(ranges, data, 2) == ["K-001", "K-002"]
    # Kreis existiert jetzt schon: zweiter Aufruf setzt fort statt neu zu definieren.
    assert tia606.free_ids(ranges, data, 1) == ["K-003"]


class TestKabelRegister:
    def _entry(self, kabel_id: str, **kw) -> tia606.KabelEntry:
        return tia606.KabelEntry(id=kabel_id, quelle=kw.get("quelle", ""), ziel=kw.get("ziel", ""),
                                 kabeltyp=kw.get("kabeltyp", ""), quelle_import=kw.get("quelle_import", "manuell"),
                                 created="2026-09-28T10:00:00")

    def test_add_and_exists_case_insensitive(self, tmp_path):
        register = tia606.KabelRegister(tmp_path / "kabel.json")
        register.add([self._entry("K-001", quelle="SW1/P1", ziel="pmx10/eno1")])
        assert register.exists("k-001") is True
        assert register.exists("K-002") is False
        entry = register.get("K-001")
        assert entry is not None and entry.quelle == "SW1/P1"

    def test_duplicates_registered_and_within_list(self, tmp_path):
        register = tia606.KabelRegister(tmp_path / "kabel.json")
        register.add([self._entry("K-001")])
        assert register.duplicates(["K-001", "K-009", "K-009"]) == ["K-001", "K-009"]

    def test_add_existing_raises(self, tmp_path):
        register = tia606.KabelRegister(tmp_path / "kabel.json")
        register.add([self._entry("K-001")])
        with pytest.raises(ValueError):
            register.add([self._entry("K-001")])
        # allow_existing überschreibt statt zu scheitern
        register.add([self._entry("K-001", quelle="neu")], allow_existing=True)
        assert register.get("K-001").quelle == "neu"

    def test_remove(self, tmp_path):
        register = tia606.KabelRegister(tmp_path / "kabel.json")
        register.add([self._entry("K-001")])
        assert register.remove("K-001") is True
        assert register.remove("K-001") is False
        assert register.all() == []

    def test_two_instances_see_each_others_entries(self, tmp_path):
        path = tmp_path / "kabel.json"
        a = tia606.KabelRegister(path)
        b = tia606.KabelRegister(path)
        a.add([self._entry("K-001")])
        assert b.exists("K-001") is True
        b.add([self._entry("K-002")])
        assert {e.id for e in a.all()} == {"K-001", "K-002"}
