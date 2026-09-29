"""Tests für Serien/Zähler: templates/series.py."""

import pytest

from tapesmith.templates.series import (
    Counter,
    SeriesSpec,
    counter_values,
    describe,
    parallel_values,
    series_values,
)


def test_series_values_simple_number():
    spec = SeriesSpec(counters=(Counter(start="1"),), count=3, prefix="Port ")
    assert series_values(spec) == ["Port 1", "Port 2", "Port 3"]


def test_counter_values_leading_zeros_from_start():
    values = counter_values(Counter(start="007"), 3)
    assert values == ["007", "008", "009"]


def test_counter_values_leading_zeros_from_width():
    values = counter_values(Counter(start="9", width=2), 2)
    assert values == ["09", "10"]


def test_counter_values_step():
    values = counter_values(Counter(start="1", step=5), 3)
    assert values == ["1", "6", "11"]


def test_counter_values_letters():
    values = counter_values(Counter(start="Y", kind="letters"), 4)
    assert values == ["Y", "Z", "AA", "AB"]


def test_series_values_nested():
    spec = SeriesSpec(
        mode="nested",
        counters=(Counter(start="A", kind="letters"), Counter(start="1")),
        count=2,
        inner_count=3,
    )
    assert series_values(spec) == ["A1", "A2", "A3", "B1", "B2", "B3"]


def test_series_values_nested_separator():
    spec = SeriesSpec(
        mode="nested",
        counters=(Counter(start="A", kind="letters"), Counter(start="1")),
        count=2,
        inner_count=3,
        separator="-",
    )
    assert series_values(spec) == ["A-1", "A-2", "A-3", "B-1", "B-2", "B-3"]


def test_parallel_values():
    fields = {
        "port": SeriesSpec(counters=(Counter(start="1"),), count=3),
        "kabel": SeriesSpec(counters=(Counter(start="01", width=2),), count=3, prefix="K"),
    }
    result = parallel_values(fields, 3)
    assert result == [
        {"port": "1", "kabel": "K01"},
        {"port": "2", "kabel": "K02"},
        {"port": "3", "kabel": "K03"},
    ]


def test_parallel_values_too_short_raises():
    fields = {
        "port": SeriesSpec(counters=(Counter(start="1"),), count=2),
        "kabel": SeriesSpec(counters=(Counter(start="1"),), count=3),
    }
    with pytest.raises(ValueError):
        parallel_values(fields, 3)


def test_series_values_parallel_mode_raises():
    spec = SeriesSpec(mode="parallel")
    with pytest.raises(ValueError):
        series_values(spec)


def test_count_zero_raises():
    with pytest.raises(ValueError):
        series_values(SeriesSpec(count=0))


def test_too_long_raises():
    with pytest.raises(ValueError):
        series_values(SeriesSpec(counters=(Counter(start="1"),), count=501))


def test_negative_counter_raises():
    with pytest.raises(ValueError):
        counter_values(Counter(start="1", step=-1), 3)


def test_letters_with_numeric_start_raises():
    with pytest.raises(ValueError):
        counter_values(Counter(start="1", kind="letters"), 3)


def test_nested_with_one_counter_raises():
    spec = SeriesSpec(mode="nested", counters=(Counter(start="1"),), count=2, inner_count=3)
    with pytest.raises(ValueError):
        series_values(spec)


def test_describe():
    spec = SeriesSpec(
        mode="nested",
        counters=(Counter(start="A", kind="letters"), Counter(start="1")),
        count=2,
        inner_count=3,
    )
    assert describe(spec) == "A1 … B3 (6 Labels)"
