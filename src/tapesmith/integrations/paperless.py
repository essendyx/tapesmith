"""Client für Paperless-ngx (ASN-Serien, Garantie-Etikett, zentraler Nummernkreis).

Nur lesende Aufrufe (GET). ASN-Reservierung läuft über den zentralen Nummernkreis `asn`
(`numbering.NumberRanges`), der vor jeder Reservierung auf `max(lokal, Paperless)` angehoben wird
(`sync_range`), damit zwei Rechner keine Dubletten erzeugen. Korrespondenten- und
Custom-Field-Namen werden je Client-Instanz einmal zwischengespeichert.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from tapesmith.integrations.credentials import read_secret
from tapesmith.integrations.httpclient import make_client, request_json
from tapesmith.numbering import NumberRange, NumberRanges
from tapesmith.i18n import N_, _t

SERVICE = "Paperless"
SCAN_TEST_HINT = (N_("Vor dem Serieneinsatz einmal testen: ein ASN-Label auf ein Blatt kleben, einscannen und prüfen, ob Paperless die ASN übernimmt (PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE, Präfix wie paperless.asn_prefix)."))

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y")


@dataclass(frozen=True)
class DocumentHit:
    id: int
    title: str
    created: str                      # TT.MM.JJJJ
    correspondent: str | None
    asn: int | None
    custom: dict[str, str]            # Feldname -> Wert als Text
    url: str                          # <public_url oder url>/documents/<id>/details


@dataclass(frozen=True)
class Warranty:
    document: DocumentHit
    kaufdatum: str
    monate: int | None
    ende: str | None
    quelle: str                       # "Custom Field Kaufdatum" | "Erstelldatum des Dokuments"
    quelle_ende: str                  # "Laufzeit angegeben" | "Custom Field Garantie bis"
                                       # | "Kaufdatum plus Laufzeit" | "" (ende None)


def add_months(d: date, months: int) -> date:
    """Monatsaddition mit Tageskappung (wie `templates.fill._add_months`, aber für `date`)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def _parse_date_text(text: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(_t("Datum '{text}' nicht lesbar (ISO JJJJ-MM-TT oder TT.MM.JJJJ)", text=text))


def _fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _created_to_text(raw: str) -> str:
    """ISO-Datum/-Zeit von Paperless (`created`) -> TT.MM.JJJJ."""
    text = str(raw)[:10]
    try:
        return _fmt(datetime.strptime(text, "%Y-%m-%d").date())
    except ValueError:
        return text


def asn_text(prefix: str, width: int, number: int) -> str:
    """`"ASN" + zfill -> "ASN00042"`."""
    return prefix + str(number).zfill(width)


def asn_number(text: str, prefix: str) -> int:
    """Umkehrung von `asn_text`; `ValueError` bei falschem Präfix oder ungültiger Zahl."""
    if not text.startswith(prefix):
        raise ValueError(_t("ASN '{text}' passt nicht zu Präfix '{prefix}'", text=text, prefix=prefix))
    rest = text[len(prefix):]
    if not rest.isdigit():
        raise ValueError(_t("ASN '{text}' ist keine gültige Nummer", text=text))
    return int(rest)


class PaperlessClient:
    """Zugriff auf die lesende Paperless-API."""

    def __init__(self, url: str, token: str, *, public_url: str | None = None, timeout_s: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        self.url = url
        self.public_url = public_url
        self._client = make_client(url, service=SERVICE,
                                   headers={"Authorization": f"Token {token}",
                                            "Accept": "application/json; version=9"},
                                   timeout_s=timeout_s, transport=transport)
        self._custom_fields_cache: dict[int, dict] | None = None
        self._correspondents_cache: dict[int, str] = {}

    @classmethod
    def from_settings(cls, data: dict, *, keyring_module=None, environ=None, transport=None) -> PaperlessClient:
        section = data["paperless"]
        token = read_secret(section.get("token_ref"), what=SERVICE, keyring_module=keyring_module,
                            environ=environ)
        return cls(section["url"], token, public_url=section.get("public_url"),
                   timeout_s=float(section.get("timeout_s") or 10.0), transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PaperlessClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def next_asn(self) -> int:
        """Nächste freie ASN aus Paperless (`GET /api/documents/next_asn/`)."""
        value = request_json(self._client, "GET", "/api/documents/next_asn/", service=SERVICE)
        return int(value)

    def _custom_field_defs(self) -> dict[int, dict]:
        if self._custom_fields_cache is None:
            data = request_json(self._client, "GET", "/api/custom_fields/", service=SERVICE,
                                params={"page_size": 100})
            results = data.get("results", []) if isinstance(data, dict) else (data or [])
            self._custom_fields_cache = {int(f["id"]): f for f in results}
        return self._custom_fields_cache

    def _correspondent_names(self, ids: list[int]) -> dict[int, str]:
        wanted = sorted({i for i in ids if i is not None})
        missing = [i for i in wanted if i not in self._correspondents_cache]
        if missing:
            id_list = ",".join(str(i) for i in missing)
            data = request_json(self._client, "GET", "/api/correspondents/", service=SERVICE,
                                params={"id__in": id_list, "page_size": 100})
            results = data.get("results", []) if isinstance(data, dict) else (data or [])
            for c in results:
                self._correspondents_cache[int(c["id"])] = c.get("name") or ""
        return {i: self._correspondents_cache.get(i, "") for i in wanted}

    def _custom_value_text(self, field_def: dict, value) -> str:
        if value is None:
            return ""
        if field_def.get("data_type") == "select":
            options = (field_def.get("extra_data") or {}).get("select_options") or []
            for opt in options:
                if str(opt.get("id")) == str(value):
                    return str(opt.get("label", value))
        return str(value)

    def _hit(self, raw: dict, correspondent_names: dict[int, str]) -> DocumentHit:
        field_defs = self._custom_field_defs()
        custom: dict[str, str] = {}
        for entry in raw.get("custom_fields") or []:
            field_def = field_defs.get(entry.get("field"))
            if field_def is None:
                continue
            custom[field_def["name"]] = self._custom_value_text(field_def, entry.get("value"))
        corr_id = raw.get("correspondent")
        correspondent = correspondent_names.get(corr_id) if corr_id is not None else None
        base = (self.public_url or self.url).rstrip("/")
        return DocumentHit(id=int(raw["id"]), title=raw.get("title") or "",
                           created=_created_to_text(raw.get("created") or ""),
                           correspondent=correspondent, asn=raw.get("archive_serial_number"),
                           custom=custom, url=f"{base}/documents/{raw['id']}/details")

    def search(self, text: str = "", *, correspondent: str = "", date_from: date | None = None,
              date_to: date | None = None, limit: int = 25) -> list[DocumentHit]:
        """Dokumentensuche; löst Korrespondenten- und Custom-Field-Namen auf."""
        params: dict[str, str] = {}
        if text:
            params["query"] = text
        if correspondent:
            params["correspondent__name__icontains"] = correspondent
        if date_from is not None:
            params["created__date__gte"] = date_from.isoformat()
        if date_to is not None:
            params["created__date__lte"] = date_to.isoformat()
        params["page_size"] = str(limit)
        params["ordering"] = "-created"
        data = request_json(self._client, "GET", "/api/documents/", service=SERVICE, params=params)
        results = data.get("results", []) if isinstance(data, dict) else (data or [])
        names = self._correspondent_names([r.get("correspondent") for r in results])
        return [self._hit(r, names) for r in results]

    def document(self, doc_id: int) -> DocumentHit:
        """Ein einzelnes Dokument."""
        raw = request_json(self._client, "GET", f"/api/documents/{doc_id}/", service=SERVICE)
        corr_id = raw.get("correspondent")
        names = self._correspondent_names([corr_id]) if corr_id is not None else {}
        return self._hit(raw, names)


def peek_next_asn(ranges: NumberRanges, data: dict, paperless_next: int) -> str:
    """Text der Nummer, die als nächste reserviert würde, ohne zu reservieren."""
    section = data["paperless"]
    key, prefix, width = section["asn_range"], section["asn_prefix"], section["asn_width"]
    try:
        start = max(ranges.get(key).next, paperless_next)
    except KeyError:
        start = paperless_next
    return asn_text(prefix, width, start)


def sync_range(ranges: NumberRanges, data: dict, paperless_next: int) -> NumberRange:
    """Hebt den ASN-Nummernkreis auf `max(lokal, paperless_next)` an; legt ihn beim ersten Gebrauch an."""
    section = data["paperless"]
    key, prefix, width = section["asn_range"], section["asn_prefix"], section["asn_width"]
    try:
        current = ranges.get(key)
    except KeyError:
        return ranges.define(key, start=paperless_next, prefix=prefix, width=width)
    if current.prefix != prefix or current.width != width:
        raise ValueError(_t("Nummernkreis {key!r} hat Präfix '{prefix}' Breite {width}, homelab.json sagt Präfix '{prefix2}' Breite {width2}", key=key, prefix=current.prefix, width=current.width, prefix2=prefix, width2=width))
    return ranges.advance_to(key, paperless_next)


def reserve_asns(client: PaperlessClient, ranges: NumberRanges, data: dict, count: int) -> list[str]:
    """Reserviert `count` ASNs im zentralen Nummernkreis (1..500), nach Abgleich mit Paperless."""
    if not 1 <= count <= 500:
        raise ValueError(_t("'count' muss 1..500 sein, ist {count}", count=count))
    paperless_next = client.next_asn()
    sync_range(ranges, data, paperless_next)
    key = data["paperless"]["asn_range"]
    return ranges.reserve(key, count)


def void_asn(ranges: NumberRanges, data: dict, asn: str, reason: str) -> None:
    """Verwirft eine vergebene ASN (Fehldruck)."""
    key = data["paperless"]["asn_range"]
    ranges.void(key, asn, reason)


def warranty(hit: DocumentHit, fields: Mapping[str, str], *, months: int | None = None) -> Warranty:
    """Garantie aus Custom Fields (Rückfall Erstelldatum), mit Vorrangregel für das Ende."""
    kaufdatum_name = fields.get("kaufdatum")
    kaufdatum_raw = hit.custom.get(kaufdatum_name, "") if kaufdatum_name else ""
    if kaufdatum_raw:
        kaufdatum_date = _parse_date_text(kaufdatum_raw)
        quelle = _t("Custom Field Kaufdatum")
    else:
        kaufdatum_date = _parse_date_text(hit.created)
        quelle = _t("Erstelldatum des Dokuments")
    kaufdatum = _fmt(kaufdatum_date)

    monate_name = fields.get("garantie_monate")
    monate_raw = hit.custom.get(monate_name, "") if monate_name else ""
    monate: int | None = None
    if monate_raw:
        try:
            monate = int(monate_raw)
        except ValueError:
            monate = None

    garantie_bis_name = fields.get("garantie_bis")
    garantie_bis_raw = hit.custom.get(garantie_bis_name, "") if garantie_bis_name else ""

    if months is not None:
        ende = _fmt(add_months(kaufdatum_date, months))
        quelle_ende = _t("Laufzeit angegeben")
        monate = months
    elif garantie_bis_raw:
        ende = _fmt(_parse_date_text(garantie_bis_raw))
        quelle_ende = _t("Custom Field Garantie bis")
    elif monate is not None:
        ende = _fmt(add_months(kaufdatum_date, monate))
        quelle_ende = _t("Kaufdatum plus Laufzeit")
    else:
        ende = None
        quelle_ende = ""

    return Warranty(document=hit, kaufdatum=kaufdatum, monate=monate, ende=ende, quelle=quelle,
                    quelle_ende=quelle_ende)


def warranty_values(w: Warranty, *, geraet: str, link: str,
                    default_months: int = 24) -> tuple[dict[str, str], list[str]]:
    """Werte für die Vorlage `garantie-qr` (nur Eingabefelder) plus etwaige Warnungen."""
    warnings: list[str] = []
    if w.ende:
        ende = w.ende
    else:
        ende = _fmt(add_months(_parse_date_text(w.kaufdatum), default_months))
        warnings.append(_t("Garantiedauer unbekannt, {default_months} Monate ab Kaufdatum angenommen", default_months=default_months))
    values = {"geraet": geraet, "kaufdatum": w.kaufdatum, "ende": ende, "link": link}
    return values, warnings
