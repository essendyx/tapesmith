"""Job-Pacing: Wartezeit bis der Druck physisch fertig ist (kein Job-Ende-Signal bekannt)."""

from tapesmith.device.profile import DeviceProfile


def estimate_print_seconds(rows: int, profile: DeviceProfile) -> float:
    length_mm = rows / profile.dots_per_mm
    return length_mm / profile.speed_mm_s + profile.feed_seconds + profile.pacing_margin_seconds
