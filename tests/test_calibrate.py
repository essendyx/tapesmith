from tapesmith.calibrate import EDGE_PITCH, edge_test_head, ruler_content
from tapesmith.device.profile import load_profile


def test_edge_test_bars_hit_their_head_rows():
    p = load_profile()
    img = edge_test_head(p)
    assert img.width == p.head_dots
    assert img.height == (p.head_dots // 4) * EDGE_PITCH
    for k in (0, 2, 23):
        y = k * EDGE_PITCH + 5
        for row in range(4 * k, 4 * k + 4):
            assert img.getpixel((row, y)) == 0, (k, row)
        if k > 0:
            assert img.getpixel((4 * k - 1, y)) == 255
    assert img.getpixel((0, EDGE_PITCH + 5)) == 255   # Zeile 0 nur im ersten Balken


def test_ruler_ticks_every_mm_long_every_10():
    p = load_profile()
    img = ruler_content(p, 100)
    assert img.size == (p.content_dots, 100 * 8 + 2)
    edge = p.content_dots - 1                       # Oberkante der Querformat-Zeichnung
    assert img.getpixel((edge, 80)) == 0            # 10 mm
    assert img.getpixel((edge, 8)) == 0             # 1 mm
    assert img.getpixel((edge, 4)) == 255           # 0,5 mm: kein Strich
    long_tick = p.content_dots - 1 - (p.content_dots // 2 - 1)
    assert img.getpixel((long_tick, 80)) == 0       # langer Strich bei 10 mm
    assert img.getpixel((long_tick, 8)) == 255      # kurzer Strich bei 1 mm


def test_ruler_wird_mit_laengenfaktor_gedruckt():
    # Das Prüf-Lineal muss den aktuellen Faktor anwenden, sonst zeigt ein neuer Druck nach dem
    # Kalibrieren wieder die Rohlänge (98 mm eingetragen, Lineal blieb bei 98 bis 99).
    import dataclasses
    p = dataclasses.replace(load_profile(), length_factor=1.05)
    img = ruler_content(p, 100)
    assert img.size == (p.content_dots, round(100 * 8 * 1.05) + 2)
    edge = p.content_dots - 1
    assert img.getpixel((edge, round(10 * 8 * 1.05))) == 0     # 10-mm-Strich an der korrigierten Stelle
    assert img.getpixel((edge, round(100 * 8 * 1.05))) == 0    # 100-mm-Strich
