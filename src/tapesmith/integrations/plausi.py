"""Plausibilitätsprüfung vor dem Druck.

Prüft die Werte einer Vorlage gegen vorhandene Daten: Seriennummer gegen den letzten SSH-Scan je
Host (Scan-Cache) und optional den Vault, Mehrdeutigkeit der 6-Stellen-Kürzung, IP im Heimnetz,
Hostname per DNS, doppelte Asset-ID bzw. Kabel-ID. Ergebnis sind Befunde `info`/`warnung`/`konflikt`.
Der Server blockiert nie: die Oberfläche zeigt Warnungen gelb und verlangt bei `konflikt` ein
ausdrückliches „Trotzdem drucken". Jede einzelne Quelle ist defensiv: Fehler beim Lesen (Vault
nicht erreichbar, Register nicht lesbar) ergeben einen `info`-Befund statt eine Ausnahme.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from tapesmith.integrations.assets import AssetStore
from tapesmith.integrations.errors import IntegrationError
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.integrations.scancache import ScanRecord
from tapesmith.integrations.tia606 import KabelRegister
from tapesmith.templates.serial import SerialNotDerivable, clean_serial, normalize_serial_input
from tapesmith.i18n import _t

LEVELS = ("info", "warnung", "konflikt")
_SEVERITY = {level: rank for rank, level in enumerate(LEVELS)}     # info < warnung < konflikt

SERIAL_FIELDS = ("sn", "seriennummer", "serial")
HOST_FIELDS = ("host", "hostname")
IP_FIELDS = ("ip", "ipv4", "ip_kurz")
ASSET_FIELDS = ("nummer", "asset", "asset_id")
KABEL_FIELDS = ("kabel_id",)


@dataclass(frozen=True)
class Finding:
    level: str
    field: str | None
    code: str
    message: str
    # code: "sn_unbekannt" | "sn_anderer_host" | "sn_kuerzung_mehrdeutig" | "sn_im_vault_anderer_host"
    #       | "sn_asset" | "ip_ausserhalb" | "ip_ungueltig" | "dns_abweichung" | "dns_unbekannt"
    #       | "asset_verworfen" | "asset_unbekannt" | "asset_andere_sn" | "kabel_vergeben" | "quelle_fehlt"


@dataclass(frozen=True)
class Context:
    scans: Sequence[ScanRecord]
    networks: Sequence[str]
    assets: AssetStore | None = None
    kabel: KabelRegister | None = None
    vault: VaultClient | None = None
    resolver: Callable[[str], list[str]] | None = None     # Hostname -> IPv4-Liste; None = keine DNS-Prüfung


def default_resolver(name: str) -> list[str]:
    """IPv4-Adressen eines Hostnamens über `socket.getaddrinfo`; nicht auflösbar -> leere Liste."""
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET)
    except OSError:
        return []
    result: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in result:
            result.append(ip)
    return result


def worst(findings: Sequence[Finding]) -> str | None:
    """Schwerster Befund (`"konflikt"` > `"warnung"` > `"info"`), `None` ohne Befunde."""
    if not findings:
        return None
    return max((f.level for f in findings), key=lambda level: _SEVERITY[level])


def _sort(findings: list[Finding]) -> list[Finding]:
    """Ausgabereihenfolge konflikt, warnung, info; innerhalb stabil (Regelreihenfolge)."""
    return sorted(findings, key=lambda f: -_SEVERITY[f.level])


def _first(values: Mapping[str, str], fields: Sequence[str]) -> tuple[str | None, str | None]:
    for field in fields:
        raw = values.get(field)
        if raw is not None and raw.strip():
            return field, raw.strip()
    return None, None


def _host_matches(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.split(".", 1)[0].casefold() == b.split(".", 1)[0].casefold()


def _clean_sn(raw: str) -> str:
    try:
        return normalize_serial_input(raw).serial
    except SerialNotDerivable:
        return clean_serial(raw)


def _all_disks(scans: Sequence[ScanRecord]):
    for record in scans:
        for disk in record.disks:
            yield record, disk


def _check_serial(values: Mapping[str, str], ctx: Context, host_value: str | None) -> list[Finding]:
    field, raw = _first(values, SERIAL_FIELDS)
    if raw is None:
        return []
    clean = _clean_sn(raw)
    sn = clean.casefold()
    findings: list[Finding] = []

    if not ctx.scans:
        findings.append(Finding("info", field, "quelle_fehlt", _t("Keine SSH-Scans vorhanden, SN nicht geprüft")))
    else:
        matches = [(r, d) for r, d in _all_disks(ctx.scans) if d.serial.strip().casefold() == sn]
        if not matches:
            latest = max(ctx.scans, key=lambda r: r.scanned_at)
            findings.append(Finding("info", field, "sn_unbekannt",
                _t("SN {raw} in keinem SSH-Scan gefunden (letzte Scans: {host} vom {scanned_at})", raw=raw, host=latest.host, scanned_at=latest.scanned_at)))
        elif host_value:
            other_host = [(r, d) for r, d in matches if not _host_matches(r.host, host_value)]
            if other_host:
                r, d = other_host[0]
                findings.append(Finding("konflikt", field, "sn_anderer_host",
                    _t("SN {raw} gehört laut Scan vom {scanned_at} zu {host} ({device}), nicht zu {host_value}", raw=raw, scanned_at=r.scanned_at, host=r.host, device=d.device, host_value=host_value)))

        short = sn[-6:] if len(sn) >= 6 else sn
        if short:
            others = {f"{d.device} ({r.host})" for r, d in _all_disks(ctx.scans)
                     if d.serial.strip() and d.serial.strip().casefold() != sn
                     and d.serial.strip().casefold()[-6:] == short}
            if others:
                findings.append(Finding("warnung", field, "sn_kuerzung_mehrdeutig",
                    _t("Die letzten 6 Stellen von {raw} passen auch zu {items}", raw=raw, items=', '.join(sorted(others)))))

    if ctx.vault is not None:
        try:
            hits = ctx.vault.search(clean or raw, max_results=10)
        except IntegrationError:
            findings.append(Finding("info", field, "quelle_fehlt", _t("Vault nicht erreichbar, SN nicht im Vault geprüft")))
        else:
            # Ohne Host-Feld gibt es nichts abzugleichen, die Suche läuft trotzdem,
            # damit ein nicht erreichbarer Vault immer als Info gemeldet wird.
            other = [h for h in hits if host_value and h.path.startswith("Hosts/")
                    and not _host_matches(h.path.split("/", 1)[1], host_value)]
            if other:
                findings.append(Finding("warnung", field, "sn_im_vault_anderer_host",
                    _t("SN {raw} taucht im Vault bei {path} auf, nicht bei Host {host_value}", raw=raw, path=other[0].path, host_value=host_value)))

    if ctx.assets is not None:
        asset_field, asset_value = _first(values, ASSET_FIELDS)
        hits = ctx.assets.find_by_serial(clean or raw)
        other = [a for a in hits if not asset_value or a.id.casefold() != asset_value.casefold()]
        if other:
            findings.append(Finding("warnung", field, "sn_asset", _t("SN ist schon Asset {id} zugeordnet", id=other[0].id)))

    return findings


def _ip_value(values: Mapping[str, str], ctx: Context) -> tuple[str | None, str | None]:
    field, raw = _first(values, IP_FIELDS)
    if raw is None:
        return None, None
    text = raw
    if field == "ip_kurz" and text.startswith(".") and ctx.networks:
        try:
            net = ipaddress.IPv4Network(ctx.networks[0], strict=False)
        except ValueError:
            return field, text
        base = str(net.network_address).rsplit(".", 1)[0]
        text = f"{base}.{text[1:]}"
    return field, text


def _check_ip(values: Mapping[str, str], ctx: Context) -> list[Finding]:
    field, text = _ip_value(values, ctx)
    if text is None:
        return []
    try:
        ip = ipaddress.IPv4Address(text)
    except ValueError:
        return [Finding("warnung", field, "ip_ungueltig", _t("'{text}' ist keine gültige IPv4-Adresse", text=text))]
    for raw_net in ctx.networks:
        try:
            net = ipaddress.IPv4Network(raw_net, strict=False)
        except ValueError:
            continue
        if ip in net:
            return []
    return [Finding("warnung", field, "ip_ausserhalb",
        _t("IP {ip} liegt außerhalb der bekannten Netze ({items})", ip=ip, items=', '.join(ctx.networks)))]


def _check_dns(values: Mapping[str, str], ctx: Context) -> list[Finding]:
    if ctx.resolver is None:
        return []
    host_field, host_value = _first(values, HOST_FIELDS)
    if host_value is None:
        return []
    ips = ctx.resolver(host_value)
    if not ips:
        return [Finding("info", host_field, "dns_unbekannt", _t("{host_value} lässt sich nicht auflösen", host_value=host_value))]
    _ip_field, ip_text = _ip_value(values, ctx)
    if ip_text:
        try:
            ipaddress.IPv4Address(ip_text)
        except ValueError:
            ip_text = None
    if ip_text and ip_text not in ips:
        return [Finding("warnung", host_field, "dns_abweichung",
            _t("{host_value} löst auf {value} auf, nicht auf {ip_text}", host_value=host_value, value=ips[0], ip_text=ip_text))]
    return []


def _check_asset(values: Mapping[str, str], ctx: Context) -> list[Finding]:
    if ctx.assets is None:
        return []
    field, raw = _first(values, ASSET_FIELDS)
    if raw is None:
        return []
    asset = ctx.assets.get(raw)
    if asset is None:
        return [Finding("info", field, "asset_unbekannt", _t("Nummer {raw} ist nicht im Asset-Register", raw=raw))]
    if asset.status == "verworfen":
        return [Finding("konflikt", field, "asset_verworfen", _t("Asset {raw} ist als verworfen markiert", raw=raw))]
    _sn_field, sn_value = _first(values, SERIAL_FIELDS)
    if sn_value and asset.seriennummer:
        if asset.seriennummer.strip().casefold() != _clean_sn(sn_value).casefold():
            return [Finding("warnung", field, "asset_andere_sn",
                _t("Asset {raw} ist mit einer anderen Seriennummer registriert ({seriennummer})", raw=raw, seriennummer=asset.seriennummer))]
    return []


def _check_kabel(values: Mapping[str, str], ctx: Context) -> list[Finding]:
    if ctx.kabel is None:
        return []
    field, raw = _first(values, KABEL_FIELDS)
    if raw is None:
        return []
    try:
        exists = ctx.kabel.exists(raw)
    except (OSError, ValueError):
        return [Finding("info", field, "quelle_fehlt", _t("Kabel-Register nicht lesbar, Kabel-ID nicht geprüft"))]
    if exists:
        return [Finding("info", field, "kabel_vergeben", _t("Kabel-ID ist bereits vergeben (Nachdruck?)"))]
    return []


def check(template: str, values: Mapping[str, str], ctx: Context) -> list[Finding]:
    """Befunde für die Werte einer Vorlage (siehe Modul-Docstring); `template` dient nur der
    Erweiterbarkeit (z. B. vorlagenspezifische Regeln später), die Prüfung selbst ist rein
    feldbasiert."""
    _ = template
    _host_field, host_value = _first(values, HOST_FIELDS)
    findings: list[Finding] = []
    findings.extend(_check_serial(values, ctx, host_value))
    findings.extend(_check_ip(values, ctx))
    findings.extend(_check_dns(values, ctx))
    findings.extend(_check_asset(values, ctx))
    findings.extend(_check_kabel(values, ctx))
    return _sort(findings)
