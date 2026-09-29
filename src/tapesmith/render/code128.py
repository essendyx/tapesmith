"""Code128-Encoder in reinem Python, ohne zxing-cpp.

Die Codeset-Wahl folgt dem ZXing-Code128Writer (den zxing-cpp für `create_barcode` nutzt), damit
die Balkenfolge bitgleich zur bisherigen Ausgabe bleibt: Start mit Code C bei zwei führenden
Ziffern, sonst Code B; Wechsel nach C nur bei mindestens vier Ziffern in Folge (bei ungerader
Anzahl erst nach der ersten Ziffer), zurück nach B vor einer einzelnen Ziffer oder einem
anderen Zeichen. Erlaubt sind die druckbaren ASCII-Zeichen 32 bis 126 (Code B), Code A wird
dafür nie gebraucht. `tests/test_code128_encoder.py` vergleicht gegen zxing-cpp.
"""

from __future__ import annotations
from tapesmith.i18n import _t

# Balken-/Lückenbreiten je Symbolwert 0 bis 105, dazu Stopp (106, sieben Elemente).
PATTERNS: tuple[str, ...] = tuple("""
212222 222122 222221 121223 121322 131222 122213 122312 132212 221213
221312 231212 112232 122132 122231 113222 123122 123221 223211 221132
221231 213212 223112 312131 311222 321122 321221 312212 322112 322211
212123 212321 232121 111323 131123 131321 112313 132113 132311 211313
231113 231311 112133 112331 132131 113123 113321 133121 313121 211331
231131 213113 213311 213131 311123 311321 331121 312113 312311 332111
314111 221411 431111 111224 111422 121124 121421 141122 141221 112214
112412 122114 122411 142112 142211 241211 221114 413111 241112 134111
111242 121142 121241 114212 124112 124211 411212 421112 421211 212141
214121 412121 111143 111341 131141 114113 114311 411113 411311 113141
114131 311141 411131 211412 211214 211232 2331112
""".split())

CODE_C, CODE_B = 99, 100
START_B, START_C, STOP = 104, 105, 106


def _validate(data: str) -> None:
    if not data:
        raise ValueError(_t("Barcode ohne Inhalt"))
    for ch in data:
        if not 32 <= ord(ch) <= 126:
            raise ValueError(_t("Code128 erlaubt nur ASCII-Zeichen (ohne Umlaute): {ch!r}", ch=ch))


def _costs(data: str) -> tuple[list[int], list[int]]:
    """Minimale Symbolzahl für data[pos:] je Codeset (B, C), rückwärts berechnet. Code C ist nur
    möglich, solange zwei Ziffern folgen, sonst kostet der Rest dort einen Wechsel nach B."""
    n = len(data)
    in_b = [0] * (n + 1)
    in_c = [0] * (n + 1)
    for pos in range(n - 1, -1, -1):
        pair = pos + 1 < n and data[pos].isdigit() and data[pos + 1].isdigit()
        stay_c = 1 + in_c[pos + 2] if pair else None
        stay_b = 1 + in_b[pos + 1]
        in_b[pos] = min(stay_b, 1 + stay_c) if stay_c is not None else stay_b
        in_c[pos] = min(stay_c, 1 + stay_b) if stay_c is not None else 1 + stay_b
    return in_b, in_c


def code128_symbols(data: str) -> list[int]:
    """Symbolwerte vom Startzeichen bis zur Prüfsumme (ohne Stopp)."""
    _validate(data)
    in_b, in_c = _costs(data)
    n = len(data)

    def pair_at(pos: int) -> bool:
        return pos + 1 < n and data[pos].isdigit() and data[pos + 1].isdigit()

    def c_first(pos: int, current: int) -> bool:
        # Gleichstand: Code C gewinnt (wie zxing-cpp)
        if not pair_at(pos):
            return False
        c_cost = 1 + in_c[pos + 2]
        b_cost = 1 + in_b[pos + 1]
        if current == CODE_C:
            return c_cost <= 1 + b_cost
        return 1 + c_cost <= b_cost if current == CODE_B else c_cost <= b_cost

    current = CODE_C if c_first(0, 0) else CODE_B
    symbols = [START_C if current == CODE_C else START_B]
    pos = 0
    while pos < n:
        wanted = CODE_C if c_first(pos, current) else CODE_B
        if wanted != current:
            symbols.append(wanted)
            current = wanted
        if current == CODE_C:
            symbols.append(int(data[pos:pos + 2]))
            pos += 2
        else:
            symbols.append(ord(data[pos]) - 32)
            pos += 1
    checksum = symbols[0] + sum(i * value for i, value in enumerate(symbols[1:], start=1))
    symbols.append(checksum % 103)
    return symbols


def _bits(widths: str) -> str:
    return "".join(("1" if i % 2 == 0 else "0") * int(w) for i, w in enumerate(widths))


def encode_modules(data: str) -> str:
    """"1"/"0"-Folge der Module (1 = Balken), ohne Ruhezone."""
    return "".join(_bits(PATTERNS[s]) for s in code128_symbols(data)) + _bits(PATTERNS[STOP])
