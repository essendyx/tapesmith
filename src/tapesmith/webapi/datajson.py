"""JSON-Umwandlungen für den Bereich Daten: Verlauf, Warteschlange, Statistik,
Inventar, Datenträger, SSH. Reine Umformung, keine Geschäftslogik (die steckt im Kern:
`history.py`, `stats.py`, `inventory.py`, `drives.py`, `sshscan.py`)."""

from __future__ import annotations

import dataclasses
from datetime import date

from tapesmith.drives import DriveInfo, marketing_size, suggest_label
from tapesmith.history import HistoryEntry, HistoryStore
from tapesmith.inventory import Box, Item, Loan, SearchHit
from tapesmith.reprint import missing_secret_fields
from tapesmith.sshscan import DiskRow, SshHost
from tapesmith.stats import RollUsage, UsageRow
from tapesmith.i18n import _t


def history_entry_json(entry: HistoryEntry, store: HistoryStore) -> dict:
    from tapesmith.history import is_reprintable

    data = entry.to_dict()
    data["reprintable"] = is_reprintable(entry)
    data["missing_secrets"] = list(missing_secret_fields(store, entry))
    return data


def usage_row_json(row: UsageRow) -> dict:
    return dataclasses.asdict(row)


def roll_usage_json(row: RollUsage) -> dict:
    return dataclasses.asdict(row)


def item_json(item: Item) -> dict:
    return {"id": item.id, "box_id": item.box_id, "name": item.name, "qty": item.qty, "note": item.note}


def box_json(box: Box, items: int) -> dict:
    return {"id": box.id, "location": box.location, "note": box.note,
            "created": box.created.isoformat(), "items": items}


def box_detail_json(box: Box, items: list[Item]) -> dict:
    data = box_json(box, len(items))
    data["item_list"] = [item_json(i) for i in items]
    return data


def loan_json(loan: Loan, today: date) -> dict:
    return {
        "id": loan.id, "item": loan.item, "person": loan.person,
        "since": loan.since.isoformat(),
        "due": loan.due.isoformat() if loan.due else None,
        "returned": loan.returned.isoformat() if loan.returned else None,
        "note": loan.note, "open": loan.open, "overdue": loan.overdue(today),
    }


def search_hit_json(hit: SearchHit, box_items: int | None) -> dict:
    return {
        "item": item_json(hit.item),
        "box": box_json(hit.box, box_items or 0) if hit.box is not None else None,
        "text": hit.text(),
    }


def drive_json(info: DriveInfo) -> dict:
    return {
        "root": info.root, "label": info.label, "size_bytes": info.size_bytes,
        "free_bytes": info.free_bytes, "filesystem": info.filesystem, "bus": info.bus,
        "removable": info.removable, "size_text": marketing_size(info.size_bytes),
        "suggestion": list(suggest_label(info)),
    }


def ssh_host_json(host: SshHost) -> dict:
    return {"name": host.name, "host": host.host, "user": host.user, "port": host.port, "key": host.key}


def disk_json(disk: DiskRow) -> dict:
    return dataclasses.asdict(disk)


def disk_row_from_json(data: dict) -> DiskRow:
    allowed = {f.name for f in dataclasses.fields(DiskRow)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(_t("Unbekannte Felder in DiskJson: {sorted}", sorted=sorted(unknown)))
    values = {**{f.name: None for f in dataclasses.fields(DiskRow)}, **data}
    for key in ("host", "device", "model", "serial", "size", "tran", "wwn"):
        if values.get(key) is None:
            values[key] = ""
    return DiskRow(**values)
