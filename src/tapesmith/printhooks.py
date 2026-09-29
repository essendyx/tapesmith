"""Gemeinsame Druck-Hooks für GUI und CLI.

`print_hooks` liefert die Pipeline-Argumente, mit denen jeder Druck (egal ob aus der GUI
(`gui.services.build_services`) oder der CLI (`cli_cmds.base.build_pipeline`)) Inhalt plus
Vor-/Nachlauf von der Rolle des aktuellen Bandes abzieht, vorher warnt, wenn die Rolle nicht
reicht oder fast leer ist, und den Schwarzanteil mit dem Akkustand prüft. Kein Qt.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tapesmith.pipeline import CheckResult
from tapesmith.render.inkcheck import ink_warnings
from tapesmith.tape.rolls import RollStore


def n7_status_check(plan, status) -> list[str]:
    """Schwarzanteil-Hinweis: Akkustand aus dem Preflight-Status, falls vorhanden."""
    battery = status.get("battery") if status is not None else None
    akku = battery.value if battery is not None and isinstance(battery.value, int) else None
    return list(ink_warnings([job.head for job in plan.chain.jobs], akku))


def print_hooks(rolls: RollStore, tape_id: Callable[[], str]) -> dict[str, Any]:
    """Keyword-Argumente für `PrintPipeline`: Verbrauch, Rollen-Check und Schwarzanteil-Check.

    `tape_id` wird bei jedem Druck neu gefragt, damit ein Bandwechsel sofort gegen die Rolle
    des neuen Bandes zählt."""

    def roll_check(plan) -> CheckResult:
        return CheckResult(warnings=tuple(rolls.check(plan.chain.balance.chain_mm, tape_id=tape_id())))

    return {"on_consumed": lambda mm: rolls.consume(mm, tape_id=tape_id()),
            "checks": (roll_check,),
            "status_checks": (n7_status_check,)}
