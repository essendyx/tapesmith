"""Serien/Zähler: Präfix/Suffix, Startwert, Schrittweite, führende Nullen, Buchstaben,
Modi einfach/parallel/verschachtelt (z. B. A1..A9, B1.. wie bei DYMO ID)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from tapesmith.i18n import _t

MAX_SERIES = 500
COUNTER_KINDS = ("number", "letters")
MODES = ("simple", "parallel", "nested")

_LETTERS_ONLY = re.compile(r"^[A-Z]+$")


@dataclass(frozen=True)
class Counter:
    start: str = "1"
    step: int = 1
    width: int = 0
    kind: str = "number"


@dataclass(frozen=True)
class SeriesSpec:
    mode: str = "simple"
    counters: tuple[Counter, ...] = (Counter(),)
    count: int = 1
    inner_count: int = 1
    prefix: str = ""
    suffix: str = ""
    separator: str = ""


def _letters_to_num(letters: str) -> int:
    n = 0
    for c in letters:
        n = n * 26 + (ord(c) - ord("A") + 1)
    return n


def _num_to_letters(n: int) -> str:
    chars = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def counter_values(counter: Counter, count: int) -> list[str]:
    if count < 1:
        raise ValueError(_t("count muss mindestens 1 sein"))
    if counter.kind == "letters":
        if counter.step < 1:
            raise ValueError(_t("Buchstaben-Zähler: step muss >= 1 sein"))
        if not _LETTERS_ONLY.match(counter.start):
            raise ValueError(_t("Buchstaben-Zähler: start '{start}' muss aus A-Z bestehen", start=counter.start))
        start_num = _letters_to_num(counter.start)
        values = []
        for i in range(count):
            n = start_num + i * counter.step
            if n < 1:
                raise ValueError(_t("Zähler würde negativ"))
            values.append(_num_to_letters(n))
        return values
    if counter.kind != "number":
        raise ValueError(_t("Unbekannte Zähler-Art '{kind}' (erlaubt: {items})", kind=counter.kind, items=', '.join(COUNTER_KINDS)))
    if counter.step == 0:
        raise ValueError(_t("Zähler: step darf nicht 0 sein"))
    start_int = int(counter.start)
    width = counter.width
    if counter.start.startswith("0") and len(counter.start) > 1:
        width = max(width, len(counter.start))
    values = []
    for i in range(count):
        v = start_int + i * counter.step
        if v < 0:
            raise ValueError(_t("Zähler würde negativ"))
        values.append(str(v).zfill(width))
    return values


def series_values(spec: SeriesSpec) -> list[str]:
    if spec.mode == "parallel":
        raise ValueError(_t("parallel: parallel_values verwenden"))
    if spec.count < 1:
        raise ValueError(_t("count muss mindestens 1 sein"))
    if spec.mode == "simple":
        if len(spec.counters) != 1:
            raise ValueError(_t("simple: genau 1 Zähler nötig"))
        if spec.count > MAX_SERIES:
            raise ValueError(_t("Serie zu lang ({count} > {max_series})", count=spec.count, max_series=MAX_SERIES))
        values = counter_values(spec.counters[0], spec.count)
        return [spec.prefix + v + spec.suffix for v in values]
    if spec.mode == "nested":
        if len(spec.counters) != 2:
            raise ValueError(_t("nested: genau 2 Zähler nötig (außen, innen)"))
        if spec.inner_count < 1:
            raise ValueError(_t("inner_count muss mindestens 1 sein"))
        total = spec.count * spec.inner_count
        if total > MAX_SERIES:
            raise ValueError(_t("Serie zu lang ({total} > {max_series})", total=total, max_series=MAX_SERIES))
        outer_values = counter_values(spec.counters[0], spec.count)
        inner_values = counter_values(spec.counters[1], spec.inner_count)
        return [
            spec.prefix + o + spec.separator + n + spec.suffix
            for o in outer_values
            for n in inner_values
        ]
    raise ValueError(_t("Unbekannter Modus '{mode}' (erlaubt: {items})", mode=spec.mode, items=', '.join(MODES)))


def parallel_values(fields: Mapping[str, SeriesSpec], count: int) -> list[dict[str, str]]:
    if count < 1:
        raise ValueError(_t("count muss mindestens 1 sein"))
    per_field: dict[str, list[str]] = {}
    for name, spec in fields.items():
        values = series_values(spec)
        if len(values) != count:
            raise ValueError(_t("Feld '{name}': Serie hat {count} statt {count2} Werte", name=name, count=len(values), count2=count))
        per_field[name] = values
    return [{name: per_field[name][i] for name in fields} for i in range(count)]


def describe(spec: SeriesSpec) -> str:
    values = series_values(spec)
    n = len(values)
    if n == 1:
        return f"{values[0]} (1 Label)"
    return f"{values[0]} … {values[-1]} ({n} Labels)"
