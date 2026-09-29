"""Client für Home Assistant: Batteriestände per Jinja-Vorlage über
`/api/template`, lokale Batterietyp-Zuordnung und optionales Anlegen eines To-do-Eintrags.

Kein Aufruf ohne injizierten `transport` in Tests. Die einzige schreibende Anfrage ist
`add_todo` (POST `/api/services/todo/add_item`), sie läuft nur auf ausdrückliche Aktion.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from tapesmith.fileutil import atomic_write_text
from tapesmith.integrations import settings
from tapesmith.integrations.credentials import read_secret
from tapesmith.integrations.errors import UpstreamError
from tapesmith.integrations.httpclient import make_client, request_json, request_raw
from tapesmith.i18n import _t

SERVICE = "Home Assistant"

# Jinja-Vorlage für POST /api/template: sammelt alle sensor.*/binary_sensor.* mit
# device_class "battery" samt Gerät, Raum, Hersteller/Modell und Batterietyp-Attribut.
BATTERY_TEMPLATE = """{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor | selectattr('attributes.device_class', 'defined') | selectattr('attributes.device_class', 'eq', 'battery') -%}
{%- set ns.rows = ns.rows + [{'entity_id': s.entity_id, 'kind': 'sensor', 'state': s.state, 'friendly_name': s.name,
    'device': device_attr(s.entity_id, 'name_by_user') or device_attr(s.entity_id, 'name') or '',
    'area': area_name(s.entity_id) or '', 'manufacturer': device_attr(s.entity_id, 'manufacturer') or '',
    'model': device_attr(s.entity_id, 'model') or '',
    'battery_type': s.attributes.battery_type_and_quantity or s.attributes.battery_type or ''}] -%}
{%- endfor -%}
{%- for s in states.binary_sensor | selectattr('attributes.device_class', 'defined') | selectattr('attributes.device_class', 'eq', 'battery') -%}
{%- set ns.rows = ns.rows + [{'entity_id': s.entity_id, 'kind': 'binary_sensor', 'state': s.state, 'friendly_name': s.name,
    'device': device_attr(s.entity_id, 'name_by_user') or device_attr(s.entity_id, 'name') or '',
    'area': area_name(s.entity_id) or '', 'manufacturer': device_attr(s.entity_id, 'manufacturer') or '',
    'model': device_attr(s.entity_id, 'model') or '', 'battery_type': s.attributes.battery_type or ''}] -%}
{%- endfor -%}
{{ ns.rows | tojson }}"""


@dataclass(frozen=True)
class BatteryDevice:
    entity_id: str
    device: str
    area: str
    level: int | None
    low: bool
    battery_type: str
    type_source: str
    manufacturer: str = ""
    model: str = ""


class HaClient:
    """HTTP-Client für Home Assistant, Anmeldung mit `Authorization: Bearer <token>`."""

    def __init__(self, url: str, token: str, *, timeout_s: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        self._client = make_client(url, service=SERVICE, headers={"Authorization": f"Bearer {token}"},
                                   timeout_s=timeout_s, transport=transport)

    @classmethod
    def from_settings(cls, data: dict, *, keyring_module=None, environ=None,
                      transport: httpx.BaseTransport | None = None) -> HaClient:
        section = data["homeassistant"]
        token = read_secret(section.get("token_ref"), what=SERVICE, keyring_module=keyring_module,
                            environ=environ)
        return cls(section["url"], token, timeout_s=section.get("timeout_s", 10.0), transport=transport)

    def batteries(self) -> list[dict]:
        """Fragt `BATTERY_TEMPLATE` über `POST /api/template` ab und liefert die geparste Liste."""
        response = request_raw(self._client, "POST", "/api/template", service=SERVICE,
                               json={"template": BATTERY_TEMPLATE})
        try:
            data = json.loads(response.text)
        except ValueError as exc:
            raise UpstreamError(SERVICE, _t("Antwort der Vorlage ist kein JSON")) from exc
        if not isinstance(data, list):
            raise UpstreamError(SERVICE, _t("Antwort der Vorlage ist kein JSON"))
        return data

    def add_todo(self, entity_id: str, item: str, *, due: date | None = None,
                description: str = "") -> None:
        """Legt einen To-do-Eintrag an (einzige schreibende Anfrage)."""
        body: dict[str, str] = {"entity_id": entity_id, "item": item}
        if due is not None:
            body["due_date"] = due.strftime("%Y-%m-%d")
        if description:
            body["description"] = description
        request_json(self._client, "POST", "/api/services/todo/add_item", service=SERVICE, json=body)


class BatteryTypes:
    """Lokale Zuordnung Gerät (entity_id) -> Batterietyp, Datei `homelab/batterietypen.json`."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else (settings.data_dir() / "batterietypen.json")

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, entity_id: str) -> str | None:
        return self._load().get(entity_id)

    def set(self, entity_id: str, battery_type: str | None) -> None:
        data = self._load()
        if not battery_type:
            data.pop(entity_id, None)
        else:
            if not 1 <= len(battery_type) <= 24:
                raise ValueError(_t("Batterietyp muss 1 bis 24 Zeichen haben"))
            data[entity_id] = battery_type
        atomic_write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    def all(self) -> dict[str, str]:
        return self._load()


def _level_of(row: Mapping) -> int | None:
    raw = row.get("state")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _device_key(row: Mapping) -> tuple[str, str]:
    device = row.get("device") or row.get("friendly_name") or row.get("entity_id") or ""
    area = row.get("area") or ""
    return device, area


def parse_devices(raw: Sequence[Mapping], types: "BatteryTypes", *, below: int = 101) -> list[BatteryDevice]:
    """Fasst mehrere Entitäten desselben Geräts zu einer Zeile zusammen (numerischer Sensor
    bevorzugt), ordnet den Batterietyp zu (HA-Attribut vor lokaler Zuordnung) und filtert nach
    `below`. Sortiert: schwach zuerst, dann Batteriestand aufsteigend (None ans Ende), dann
    Raum, Gerät."""
    grouped: dict[tuple[str, str], list[Mapping]] = {}
    order: list[tuple[str, str]] = []
    for row in raw:
        key = _device_key(row)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    devices: list[BatteryDevice] = []
    for key in order:
        device, area = key
        rows = grouped[key]
        chosen = next((r for r in rows if r.get("kind") == "sensor"), rows[0])
        entity_id = str(chosen.get("entity_id", ""))
        kind = chosen.get("kind")

        if kind == "binary_sensor":
            low = chosen.get("state") == "on"
            level = None
            keep = low or below == 101
        else:
            level = _level_of(chosen)
            low = level is not None and level < 20
            if level is None:
                keep = below == 101
            else:
                keep = level < below
        if not keep:
            continue

        battery_type = str(chosen.get("battery_type") or "")
        type_source = "Home Assistant" if battery_type else ""
        if not battery_type:
            local = types.get(entity_id)
            if local:
                battery_type = local
                type_source = "lokal"

        devices.append(BatteryDevice(
            entity_id=entity_id, device=str(device), area=str(area), level=level, low=low,
            battery_type=battery_type, type_source=type_source,
            manufacturer=str(chosen.get("manufacturer") or ""), model=str(chosen.get("model") or ""),
        ))

    devices.sort(key=lambda d: (not d.low, d.level if d.level is not None else 10**9, d.area, d.device))
    return devices


def battery_values(dev: BatteryDevice, *, day: date) -> dict[str, str]:
    """Werte für die Vorlage `batterie`: Gerät, Raum, Typ, Datum (heute, sofern `day` nicht anders)."""
    return {"geraet": dev.device, "raum": dev.area, "typ": dev.battery_type, "datum": day.strftime("%d.%m.%Y")}


def maintenance_values(was: str, *, day: date, months: int, note: str = "") -> dict[str, str]:
    """Werte für die Vorlage `wartung`; `months` (Intervall) muss 1 bis 120 sein."""
    if not 1 <= months <= 120:
        raise ValueError(_t("Intervall muss 1 bis 120 Monate sein"))
    return {"was": was, "datum": day.strftime("%d.%m.%Y"), "intervall": str(months), "notiz": note}


def due_date(day: date, months: int) -> date:
    """Monatsaddition mit Tageskappung, wie `templates.fill._add_months`."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    day_of_month = min(day.day, calendar.monthrange(year, month)[1])
    return day.replace(year=year, month=month, day=day_of_month)
