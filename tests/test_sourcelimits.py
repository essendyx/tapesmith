"""Tests für `tapesmith.sourcelimits`."""

import pytest

from tapesmith import sourcelimits
from tapesmith.guard import JobRequest, evaluate


def test_max_copies_defaults():
    assert sourcelimits.max_copies({}, "gui") == 50
    assert sourcelimits.max_copies({}, "api") == 5
    assert sourcelimits.max_copies({}, "mcp") == 5
    assert sourcelimits.max_copies({}, "mqtt") == 5
    assert sourcelimits.max_copies({}, "hotfolder") == 5


def test_max_copies_folgt_guard_confirm_copies():
    assert sourcelimits.max_copies({"guard": {"confirm_copies": 3}}, "api") == 3


def test_max_copies_unbekannte_quelle_wirft():
    with pytest.raises(ValueError):
        sourcelimits.max_copies({}, "quatsch")


def test_max_copies_konsistent_mit_guard_evaluate():
    copies = sourcelimits.max_copies({}, "api")
    decision = evaluate(JobRequest("api", 30.0, 30.0 * copies, copies))
    assert decision.allowed is True
    assert decision.needs_confirmation is False

    decision2 = evaluate(JobRequest("api", 30.0, 30.0 * (copies + 1), copies + 1))
    assert decision2.allowed is False
    assert "kann nicht bestätigen" in decision2.message()


def test_max_label_mm():
    assert sourcelimits.max_label_mm({}, "api") == 150.0
    assert sourcelimits.max_label_mm({}, "cli") == 500.0


def test_copies_error():
    assert sourcelimits.copies_error({}, "mqtt", 5) is None
    msg = sourcelimits.copies_error({}, "mqtt", 6)
    assert "1 bis 5" in msg
    assert "mqtt" in msg
    for bad in (True, 0, "2", 2.5):
        assert sourcelimits.copies_error({}, "mqtt", bad) is not None
    assert sourcelimits.copies_error({}, "gui", 6) is None


def test_family_max_copies():
    assert sourcelimits.family_max_copies({}) == 5
    assert sourcelimits.family_max_copies({"family": {"max_copies": 3}}) == 3
    assert sourcelimits.family_max_copies({"family": {"max_copies": 20}}) == 5


def test_policy_kaputte_guard_sektion_liefert_standardwerte():
    pol = sourcelimits.policy({"guard": {"confirm_copies": -1}})
    assert pol.confirm_copies == 5


def test_limits_text():
    assert sourcelimits.limits_text({}, "api") == "höchstens 5 Kopien je Auftrag, Labels bis 150 mm"
