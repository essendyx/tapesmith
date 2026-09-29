"""Assistent „Platte tauschen": ZFS-Pools eines Hosts per SSH auf FAULTED/DEGRADED/UNAVAIL/
REMOVED/OFFLINE-Geräte prüfen, die neue Platte erkennen und einen `zpool replace`-Befehl planen.

Der Assistent führt nie einen schreibenden Befehl aus: `build_plan` liefert nur den Befehl als
Text zum Kopieren. Scan und Vergleich nutzen denselben Remote-Befehl wie `sshscan` und den
Scan-Cache aus `integrations.scancache`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from tapesmith import sshscan
from tapesmith.integrations import scancache
from tapesmith.sshscan import DiskRow, Runner, SshError, SshHost
from tapesmith.templates.serial import SerialNotDerivable, parse_by_id
from tapesmith.i18n import _t

PROBLEM_STATES = ("FAULTED", "DEGRADED", "UNAVAIL", "REMOVED", "OFFLINE")

_POOL_LINE_RE = re.compile(r"^\s*pool:\s*(\S+)")
_STATE_LINE_RE = re.compile(r"^\s*state:\s*(\S+)")
_GUID_RE = re.compile(r"^\d{10,20}$")
_WAS_RE = re.compile(r"^was\s+(\S+)")
_PART_TAIL_RE = re.compile(r"-part(\d+)$")
_SD_PART_RE = re.compile(r"^([a-z]+)(\d+)$")
_NVME_PART_RE = re.compile(r"^(\w+n\d+)p(\d+)$")
_SIZE_RE = re.compile(r"^([\d.]+)\s*([KMGT]?)$", re.IGNORECASE)
_SIZE_FACTORS = {"": 1.0, "K": 1024.0, "M": 1024.0**2, "G": 1024.0**3, "T": 1024.0**4}


@dataclass(frozen=True)
class PoolDevice:
    pool: str
    vdev: str | None
    name: str
    state: str
    read: str
    write: str
    cksum: str
    note: str
    was_path: str | None
    by_id: str | None
    partition: str | None
    device: str | None


@dataclass(frozen=True)
class PoolStatus:
    name: str
    state: str
    devices: tuple[PoolDevice, ...]
    errors: str


@dataclass(frozen=True)
class Candidate:
    disk: DiskRow
    reason: str


@dataclass(frozen=True)
class ZfsOverview:
    host: str
    scanned_at: str
    previous_scanned_at: str | None
    disks: tuple[DiskRow, ...]
    pools: tuple[PoolStatus, ...]
    problems: tuple[PoolDevice, ...]
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class ReplacePlan:
    host: str
    pool: str
    old: PoolDevice
    old_serial: str
    old_model: str
    new: DiskRow
    command: str
    hints: tuple[str, ...]
    changelog_md: str
    old_label: dict[str, str]
    new_label: dict[str, str]


def scan_raw(host: SshHost, *, runner: Runner | None = None, timeout_s: float = 20.0,
             strict_host_key: bool = True, ssh_exe: str | None = None,
             key_exists: Callable[[Path], bool] = Path.exists) -> str:
    """Wie `sshscan.scan_host`, gibt aber den rohen stdout zurück (gleiche Fehlerabbildung)."""
    key_path = host.key_path()
    if not key_exists(key_path):
        raise SshError(_t("SSH-Schlüssel {key_path} nicht gefunden", key_path=key_path))
    exe = ssh_exe if ssh_exe is not None else sshscan.find_ssh_exe()
    argv = sshscan.ssh_argv(host, ssh_exe=exe, timeout_s=timeout_s, strict_host_key=strict_host_key)
    run = runner if runner is not None else sshscan.default_runner
    returncode, stdout, stderr = run(argv, timeout_s)
    if returncode == 255:
        raise SshError(sshscan._translate_ssh_error(stderr, host))
    if returncode != 0 and not stdout.strip():
        raise SshError(stderr.strip() or _t("ssh beendete sich mit Code {returncode}", returncode=returncode))
    return stdout


def _byid_table(byid_part: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for name, device in sshscan._parse_byid_lines(byid_part):
        table.setdefault(name, device)
    return table


def _resolve_device_fields(path: str | None, byid_to_device: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    """(by_id, partition, device) aus einem `/dev/...`-Pfad (by-id oder direkt)."""
    if not path:
        return None, None, None
    prefix = "/dev/disk/by-id/"
    if path.startswith(prefix):
        raw_name = path[len(prefix):]
        match = _PART_TAIL_RE.search(raw_name)
        if match:
            base_name = raw_name[: match.start()]
            partition = f"part{match.group(1)}"
        else:
            base_name = raw_name
            partition = None
        return base_name, partition, byid_to_device.get(base_name)
    if path.startswith("/dev/"):
        raw = path[len("/dev/"):]
        match = _NVME_PART_RE.match(raw)
        if match:
            return None, f"part{match.group(2)}", match.group(1)
        match = _SD_PART_RE.match(raw)
        if match:
            return None, f"part{match.group(2)}", match.group(1)
        return None, None, raw
    return None, None, None


def parse_pools(stdout: str) -> tuple[PoolStatus, ...]:
    """Wertet den Abschnitt nach `@@ZPOOL@@` aus (Pools, Zustände, Geräte, Fehlerzeile)."""
    _lsblk_part, byid_part, zpool_part = sshscan._split_sections(stdout)
    byid_to_device = _byid_table(byid_part)

    pools: list[PoolStatus] = []
    current_pool: str | None = None
    current_state = ""
    current_vdev: str | None = None
    devices: list[PoolDevice] = []
    error_lines: list[str] = []

    def _flush() -> None:
        if current_pool is not None:
            pools.append(PoolStatus(name=current_pool, state=current_state, devices=tuple(devices),
                                    errors="\n".join(error_lines).strip()))

    for raw_line in zpool_part.splitlines():
        pool_match = _POOL_LINE_RE.match(raw_line)
        if pool_match:
            _flush()
            current_pool = pool_match.group(1)
            current_state = ""
            current_vdev = None
            devices = []
            error_lines = []
            continue
        if current_pool is None:
            continue
        state_match = _STATE_LINE_RE.match(raw_line)
        if state_match:
            current_state = state_match.group(1)
            continue
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "config:":
            continue
        if stripped.startswith("errors:"):
            error_lines.append(stripped[len("errors:"):].strip())
            continue
        tokens = stripped.split()
        token0 = tokens[0]
        if token0 == current_pool:
            current_vdev = None
            continue
        if sshscan._VDEV_RE.match(token0):
            current_vdev = token0
            continue
        is_guid = bool(_GUID_RE.match(token0))
        if not (token0.startswith("/dev/") or is_guid):
            continue
        if len(tokens) < 5:
            continue
        name, state, read, write, cksum = tokens[:5]
        note = " ".join(tokens[5:])
        was_match = _WAS_RE.match(note)
        was_path = was_match.group(1) if was_match else None
        source_path = was_path if was_path else (name if name.startswith("/dev/") else None)
        by_id, partition, device = _resolve_device_fields(source_path, byid_to_device)
        devices.append(PoolDevice(pool=current_pool, vdev=current_vdev, name=name, state=state,
                                  read=read, write=write, cksum=cksum, note=note, was_path=was_path,
                                  by_id=by_id, partition=partition, device=device))
    _flush()
    return tuple(pools)


def problem_devices(pools: Sequence[PoolStatus]) -> tuple[PoolDevice, ...]:
    """Nur Blätter (keine vdev-Zeilen, nicht die Pool-Zeile) mit einem Problem-Zustand."""
    return tuple(d for pool in pools for d in pool.devices if d.state in PROBLEM_STATES)


def candidates(disks: Sequence[DiskRow], previous: Sequence[DiskRow] | None) -> tuple[Candidate, ...]:
    """Platten, die seit dem vorigen Scan neu sind (Grund hat Vorrang) oder in keinem Pool stecken."""
    prev_keys: set[str] | None = None
    if previous is not None:
        prev_keys = {(d.serial or d.by_id or "") for d in previous if (d.serial or d.by_id)}
    result: list[Candidate] = []
    for disk in disks:
        key = disk.serial or disk.by_id or ""
        if prev_keys is not None and key and key not in prev_keys:
            result.append(Candidate(disk=disk, reason=_t("neu seit dem letzten Scan")))
            continue
        if disk.pool is None:
            result.append(Candidate(disk=disk, reason=_t("in keinem Pool")))
    return tuple(result)


def overview(host: SshHost, *, runner: Runner | None = None, timeout_s: float = 20.0,
            strict_host_key: bool = True, ssh_exe: str | None = None,
            key_exists: Callable[[Path], bool] = Path.exists,
            now: Callable[[], datetime] = datetime.now) -> tuple[ZfsOverview, str]:
    """Scannt den Host, vergleicht mit dem letzten Scan-Cache-Eintrag und speichert den neuen Scan."""
    stdout = scan_raw(host, runner=runner, timeout_s=timeout_s, strict_host_key=strict_host_key,
                      ssh_exe=ssh_exe, key_exists=key_exists)
    disks = tuple(sshscan.parse_output(host.name, stdout))
    pools = parse_pools(stdout)
    previous = scancache.load_scan(host.name)
    previous_disks = previous.disks if previous is not None else None
    previous_scanned_at = previous.scanned_at if previous is not None else None
    cands = candidates(disks, previous_disks)
    problems = problem_devices(pools)

    when = now()
    record = scancache.save_scan(host.name, disks, when=when)
    ov = ZfsOverview(host=host.name, scanned_at=record.scanned_at, previous_scanned_at=previous_scanned_at,
                     disks=disks, pools=pools, problems=problems, candidates=cands)
    return ov, stdout


def _size_bytes(text: str) -> float | None:
    match = _SIZE_RE.match((text or "").strip())
    if not match:
        return None
    return float(match.group(1)) * _SIZE_FACTORS.get(match.group(2).upper(), 1.0)


def _find_previous_disk(host: str, *, device: str | None, by_id: str | None) -> DiskRow | None:
    record = scancache.load_scan(host)
    if record is None:
        return None
    for disk in record.disks:
        if by_id and disk.by_id == by_id:
            return disk
        if device and disk.device == device:
            return disk
    return None


def _old_serial_and_model(host: str, old: PoolDevice) -> tuple[str, str]:
    previous_disk = _find_previous_disk(host, device=old.device, by_id=old.by_id)
    if previous_disk is not None and previous_disk.serial:
        return previous_disk.serial, previous_disk.model
    if old.by_id:
        try:
            disk_id = parse_by_id(old.by_id)
        except SerialNotDerivable:
            pass
        else:
            return disk_id.serial, (disk_id.model or (previous_disk.model if previous_disk else ""))
    return "", (previous_disk.model if previous_disk else "")


def build_plan(ov: ZfsOverview, old_name: str, new_device: str, *, slot: str,
              today: date, reason: str = "") -> ReplacePlan:
    old = next((d for d in ov.problems if d.name == old_name), None)
    if old is None:
        raise ValueError(_t("Gerät '{old_name}' ist kein defektes Gerät", old_name=old_name))
    new = next((d for d in ov.disks if d.device == new_device), None)
    if new is None:
        raise ValueError(_t("Gerät '{new_device}' nicht gefunden", new_device=new_device))
    if new.pool is not None:
        raise ValueError(_t("'{new_device}' ist schon Teil von Pool '{pool}'", new_device=new_device, pool=new.pool))
    if not new.by_id:
        raise ValueError(_t("'{new_device}' hat keinen by-id-Namen", new_device=new_device))

    command = f"zpool replace {old.pool} {old.name} /dev/disk/by-id/{new.by_id}"

    hints = [_t("Befehl erst nach Prüfung von Pool, alter und neuer Platte ausführen, die App führt nichts aus.")]
    if old.partition:
        hints.append(
            _t("Die alte Platte war partitioniert ({partition}): bei Proxmox-Bootplatten vorher Partitionstabelle kopieren (sgdisk) und proxmox-boot-tool format/init ausführen, dann die Partition ersetzen.", partition=old.partition)
        )
    previous_disk = _find_previous_disk(ov.host, device=old.device, by_id=old.by_id)
    if previous_disk is not None:
        old_bytes = _size_bytes(previous_disk.size)
        new_bytes = _size_bytes(new.size)
        if old_bytes is not None and new_bytes is not None and new_bytes < old_bytes:
            hints.append(_t("Die neue Platte ist kleiner als die alte."))

    old_serial, old_model = _old_serial_and_model(ov.host, old)

    old_label = {
        "host": ov.host,
        "slot": slot,
        "sn": old_serial or old.by_id or old.name,
        "datum": today.strftime("%d.%m.%Y"),
        "grund": reason or old.state.lower(),
    }
    new_label = {
        "host": ov.host,
        "slot": slot,
        "sn": new.serial or (new.by_id or ""),
    }

    by_id_or_name = old.by_id or old.name
    changelog_md = (
        _t("### Platte getauscht: {host} · Pool {pool}\n- Alt: {old_model} SN {old_serial} ({by_id_or_name}), Zustand {state}\n- Neu: {model} SN {serial} ({by_id}), Slot {slot}\n- Befehl: `{command}`\n- Verifikation: `zpool status {pool}` nach dem Resilver ohne Fehler\n- Labels: alt „defekt“, neu „{host} · {slot}“ gedruckt\n- Links: [[Hosts/{host}]]", host=ov.host, pool=old.pool, old_model=old_model, old_serial=old_serial, by_id_or_name=by_id_or_name, state=old.state, model=new.model, serial=new.serial, by_id=new.by_id, slot=slot, command=command)
    )

    return ReplacePlan(host=ov.host, pool=old.pool, old=old, old_serial=old_serial, old_model=old_model,
                       new=new, command=command, hints=tuple(hints), changelog_md=changelog_md,
                       old_label=old_label, new_label=new_label)
