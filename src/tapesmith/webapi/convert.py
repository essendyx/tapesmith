"""Kern-Datentypen -> JSON der API (TapeInfo, ProfileInfo, StatusJson)."""

from __future__ import annotations

import dataclasses
from datetime import datetime

from tapesmith.device.profile import DeviceProfile
from tapesmith.ipc.codec import StatusReport, encode_report
from tapesmith.statusview import status_view
from tapesmith.tape.profiles import TapeProfile


def rgb_hex(rgb: tuple[int, int, int]) -> str:
    red, green, blue = rgb
    return f"#{int(red):02x}{int(green):02x}{int(blue):02x}"


def tape_json(tape: TapeProfile, current_id: str) -> dict:
    return {
        "id": tape.id,
        "name": tape.name,
        "background": rgb_hex(tape.background),
        "ink": rgb_hex(tape.ink),
        "material": tape.material,
        "transparent": tape.transparent,
        "dark": tape.dark,
        "code_mode": tape.code_mode,            # "" = automatisch (siehe dark)
        "density": tape.density,
        "current": tape.id == current_id,
    }


def profile_json(profile: DeviceProfile) -> dict:
    return {
        "model": profile.model,
        "head_dots": profile.head_dots,
        "content_dots": profile.content_dots,
        "content_offset": profile.content_offset,
        "dots_per_mm": profile.dots_per_mm,
        "leader_mm": profile.leader_mm,
        "trailer_mm": profile.trailer_mm,
        "length_factor": profile.length_factor,
        "verified": list(profile.verified),
        "experimental": list(profile.experimental),
    }


def status_json(report: StatusReport, *, now: datetime, mac: str | None) -> dict:
    view = status_view(report.state, report, now=now, mac=mac)
    return {"report": encode_report(report), "view": dataclasses.asdict(view)}
