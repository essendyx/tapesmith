import json

import pytest

from tapesmith import paths
from tapesmith.document.targets import RULES, ShortenRule, find_target, load_targets, shorten_steps

TABLE_IDS = {
    "m2-2280", "m2-2242", "ssd-25-stirn", "usb-stick", "hotswap-schacht",
    "ordner-schmal", "ordner-breit", "geoeffnet",
}


def test_load_targets_contains_all_table_ids():
    ids = {t.id for t in load_targets()}
    assert TABLE_IDS <= ids


def test_user_file_overrides_builtin_by_id():
    path = paths.app_dir() / "targets.json"
    path.write_text(json.dumps([{"id": "m2-2280", "name": "M.2 2280 (angepasst)", "max_length_mm": 22}]),
                     encoding="utf-8")
    t = find_target("m2-2280")
    assert t.max_length_mm == 22 and t.name == "M.2 2280 (angepasst)"
    # unveränderte Einträge bleiben erhalten
    assert find_target("usb-stick").max_length_mm == 15


def test_find_target_unknown_lists_available():
    with pytest.raises(ValueError, match="usb-stick"):
        find_target("mars")


def test_target_needs_exactly_one_length_kind():
    from tapesmith.document import targets as mod
    with pytest.raises(ValueError, match="genau eins"):
        mod._parse_target({"id": "x", "name": "X"}, "hint")
    with pytest.raises(ValueError, match="genau eins"):
        mod._parse_target({"id": "x", "name": "X", "max_length_mm": 10, "fixed_length_mm": 20}, "hint")


@pytest.mark.parametrize("rule, n, value, expected", [
    ("last", 6, "112233274913", "274913"),
    ("first", 4, "112233274913", "1122"),
    ("strip_domain", None, "pmx10.home.lan", "pmx10"),
    ("strip_domain", None, "192.0.2.60", "192.0.2.60"),
])
def test_shorten_rule_apply(rule, n, value, expected):
    assert ShortenRule(field="x", rule=rule, n=n).apply(value) == expected


def test_shorten_rule_describe():
    assert ShortenRule(field="sn", rule="last", n=6).describe("Seriennummer") == "Seriennummer: letzte 6 Stellen"
    assert ShortenRule(field="sn", rule="first", n=12).describe("Seriennummer") == "Seriennummer: erste 12 Zeichen"
    assert ShortenRule(field="host", rule="strip_domain").describe("Host") == "Host: ohne Domain"


def test_shorten_steps_two_rules_produce_three_steps_with_cumulative_descriptions():
    rules = (
        ShortenRule(field="sn", rule="last", n=6),
        ShortenRule(field="host", rule="strip_domain"),
    )
    values = {"sn": "112233274913", "host": "pmx10.home.lan"}
    labels = {"sn": "Seriennummer", "host": "Host"}
    steps = shorten_steps(values, rules, labels)
    assert len(steps) == 3
    assert steps[0] == (values, ())
    assert steps[1][0]["sn"] == "274913" and steps[1][1] == ("Seriennummer: letzte 6 Stellen",)
    assert steps[2][0]["host"] == "pmx10"
    assert steps[2][1] == ("Seriennummer: letzte 6 Stellen", "Host: ohne Domain")


def test_shorten_steps_ineffective_rule_creates_no_step():
    rules = (ShortenRule(field="sn", rule="last", n=20),)  # länger als der Wert -> ändert nichts
    values = {"sn": "123"}
    steps = shorten_steps(values, rules, {"sn": "Seriennummer"})
    assert len(steps) == 1


def test_rules_tuple_matches_supported_rules():
    assert set(RULES) == {"last", "first", "strip_domain"}
