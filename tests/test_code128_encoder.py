"""Eigener Code128-Encoder (reines Python): bitgleich zu zxing-cpp, solange zxing-cpp im venv lädt."""

import itertools
import random
import string

import pytest
from PIL import Image

from tapesmith.render.code128 import PATTERNS, code128_symbols, encode_modules

SAMPLES = (
    "A", "1", "12", "123", "1234", "12345", "123456", "1234567", "12345678901", "00", "000", "0000",
    "ASN00042", "ASN0004", "ASN01234", "ASN1", "ASN12", "ASN123", "ASN99999",
    "S4EWNX0R123456", "WD-WCC4N1234567", "ZL2ABC12", "2238E5A6B7C8", "Y7G0A00XFJQE", "PHWL123400ABC",
    "ab12345678cd", "A12B", "A123B", "A1234B", "A12345B", "123456a", "a123456", "12a34", "1a2b3c",
    "S/N MULTI123456789", "HTTP://L.LAN/D7", " ", "~", "{|}", "a b c", "!\"#$%&'()*+,-./:;<=>?@[\\]^_`",
    "Hello World 2026", "00-11-22-33", "12 34 56", "9" * 30, "1" * 31, "x" + "7" * 12 + "y",
)


def _zxing_modules(data: str) -> str:
    zxingcpp = pytest.importorskip("zxingcpp")
    barcode = zxingcpp.create_barcode(data, zxingcpp.BarcodeFormat.Code128)
    img = barcode.to_image(scale=1, add_quiet_zones=False)
    mv = memoryview(img)
    rows, cols = mv.shape
    pixels = Image.frombytes("L", (cols, rows), bytes(mv)).load()
    return "".join("1" if pixels[x, 0] == 0 else "0" for x in range(cols))


def _random_inputs(count: int) -> list[str]:
    rng = random.Random(20260929)
    printable = "".join(chr(c) for c in range(32, 127))
    pools = (string.digits, string.digits + string.ascii_uppercase, printable, string.digits * 4 + "AB-/ ")
    out = []
    for i in range(count):
        pool = pools[i % len(pools)]
        out.append("".join(rng.choice(pool) for _ in range(rng.randint(1, 24))))
    return out


def test_tabelle_vollstaendig():
    assert len(PATTERNS) == 107
    assert all(sum(map(int, p)) == 11 and len(p) == 6 for p in PATTERNS[:106])
    assert sum(map(int, PATTERNS[106])) == 13 and len(PATTERNS[106]) == 7
    assert len(set(PATTERNS)) == 107


def test_bekannte_symbolfolgen():
    assert code128_symbols("ASN00042") == [104, 33, 51, 46, 16, 99, 0, 42, 97]
    assert code128_symbols("1234") == [105, 12, 34, 82]
    assert code128_symbols("123") == [105, 12, 100, 19, 65]
    assert code128_symbols("A") == [104, 33, 34]


def test_module_start_stop_und_laenge():
    modules = encode_modules("ASN01234")
    assert modules.startswith("11010010000") or modules.startswith("11010011100")
    assert modules.endswith("1100011101011")
    assert len(modules) == 11 * (len(code128_symbols("ASN01234"))) + 13


@pytest.mark.parametrize("data", ["", "Größe", "a\tb", "\x7f"])
def test_ungueltige_eingaben(data):
    with pytest.raises(ValueError):
        encode_modules(data)


@pytest.mark.parametrize("data", SAMPLES)
def test_bitgleich_zu_zxing(data):
    assert encode_modules(data) == _zxing_modules(data)


def test_bitgleich_zu_zxing_zufall():
    pytest.importorskip("zxingcpp")
    differ = [d for d in _random_inputs(600) if encode_modules(d) != _zxing_modules(d)]
    assert differ == []


def test_alle_einzelzeichen_bitgleich():
    pytest.importorskip("zxingcpp")
    for code in range(32, 127):
        for data in (chr(code), chr(code) * 2, "0" + chr(code) + "12"):
            assert encode_modules(data) == _zxing_modules(data), repr(data)


def test_alle_kurzen_folgen_aus_ziffer_und_buchstabe_bitgleich():
    """Vollständig über {"1", "A"} bis Länge 10: deckt jede Lage von Ziffernblöcken ab
    (Anfang, Mitte, Ende, gerade und ungerade Länge), also jede Codeset-Entscheidung."""
    pytest.importorskip("zxingcpp")
    differ = []
    for length in range(1, 11):
        for combo in itertools.product("1A", repeat=length):
            data = "".join(combo)
            if encode_modules(data) != _zxing_modules(data):
                differ.append(data)
    assert differ == []
