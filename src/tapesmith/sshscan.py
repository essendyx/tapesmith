"""SSH-Disk-Scanner: Seriennummern und Datenträger eines Homelab-Hosts per SSH auslesen
(lsblk + /dev/disk/by-id + optional zpool status) und daraus Zeilen für die Vorlage
`datentraeger` bauen; das fehleranfällige Abtippen der Seriennummer entfällt.

Kein echter SSH-Aufruf hier fest verdrahtet: `scan_host` nimmt einen injizierbaren `Runner`
(Standard `default_runner`, ruft `ssh.exe` ohne Windows-Shell auf). Tests arbeiten ausschließlich
mit aufgezeichneten Fake-Ausgaben (`tests/data/ssh/`) und Fake-Runnern.

Beispiel-Host (nur Doku, nie hart codieren): {"name": "pmx10", "host": "192.0.2.60",
"user": "root", "key": "%USERPROFILE%\\.ssh\\id_ed25519_homelab"}.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from pathlib import Path

from tapesmith.dataimport.table import Table
from tapesmith.templates.serial import DiskId, SerialNotDerivable, parse_by_id
from tapesmith.i18n import _t

REMOTE_SCRIPT = ("lsblk -J -o NAME,MODEL,SERIAL,SIZE,TYPE,TRAN,WWN; echo '@@BYID@@'; find /dev/disk/by-id -maxdepth 1 -type l -printf '%f %l\\n' 2>/dev/null || ls -l /dev/disk/by-id/; echo '@@ZPOOL@@'; zpool status -P 2>/dev/null || true")
BYID_PREFERENCE = ("ata-", "nvme-", "scsi-SATA_", "scsi-", "usb-", "wwn-", "nvme-eui.")
VIRTUAL_PREFIXES = ("loop", "zd", "rbd", "nbd", "zram", "sr", "dm-", "md")

CREATE_NO_WINDOW = 0x08000000

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")
_PART_RE = re.compile(r"-part\d+$")
_TRAILING_NUM_SUFFIX_RE = re.compile(r"_\d+$")
_POOL_LINE_RE = re.compile(r"^\s*pool:\s*(\S+)")
_VDEV_RE = re.compile(
    r"^(mirror-\d+|raidz\d+-\d+|draid\d+(?::\d+d)?(?::\d+c)?(?::\d+s)?(?:-\d+)?|spare|log|cache|special)$")
_NVME_PART_RE = re.compile(r"^(\w+n\d+)p\d+$")
_SD_PART_RE = re.compile(r"^([a-z]+)\d+$")


class SshError(RuntimeError):
    """SSH-bezogener Fehler mit deutscher Klartextmeldung samt Handlungsanweisung."""


@dataclass(frozen=True)
class SshHost:
    name: str
    host: str
    user: str = "root"
    port: int = 22
    key: str = ""

    def key_path(self) -> Path:
        return Path(os.path.expanduser(os.path.expandvars(self.key)))


@dataclass(frozen=True)
class DiskRow:
    host: str                 # SshHost.name
    device: str                # "sda", "nvme0n1"
    model: str
    serial: str                # "" wenn unbekannt
    size: str                  # lsblk SIZE, z. B. "1.8T"
    tran: str                  # "sata", "nvme", "usb", ""
    wwn: str
    by_id: str | None          # bevorzugter by-id-Name (ohne Pfad)
    pool: str | None
    vdev: str | None           # "mirror-0", "raidz1-0", None bei Einzelplatte


Runner = Callable[[list[str], float], tuple[int, str, str]]   # (argv, timeout) -> (returncode, stdout, stderr)


def hosts_from_config(cfg: dict) -> list[SshHost]:
    """`cfg["ssh"]["hosts"]` (Defaults `user="root"`, `port=22`) validiert; ein ungültiger
    Eintrag löst `ValueError` aus. Keine echte Netzwerkprüfung hier."""
    entries = (cfg or {}).get("ssh", {}).get("hosts", [])
    hosts: list[SshHost] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(_t("ssh.hosts: Eintrag muss ein Objekt sein, ist {entry!r}", entry=entry))
        name = entry.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(_t("ssh.hosts: ungültiger Name {name!r} (erlaubt: {pattern})", name=name, pattern=_NAME_RE.pattern))
        if name in seen:
            raise ValueError(_t("ssh.hosts: doppelter Name '{name}'", name=name))
        seen.add(name)
        host_value = entry.get("host")
        if (not isinstance(host_value, str) or not host_value.strip() or " " in host_value
                or host_value.startswith("-")):
            raise ValueError(
                _t("ssh.hosts[{name}]: 'host' darf keine Leerzeichen haben und nicht mit '-' beginnen, ist {host_value!r}", name=name, host_value=host_value))
        user = entry.get("user", "root")
        if not isinstance(user, str) or not _USER_RE.match(user):
            raise ValueError(_t("ssh.hosts[{name}]: ungültiger Benutzer {user!r}", name=name, user=user))
        port = entry.get("port", 22)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError(_t("ssh.hosts[{name}]: 'port' muss 1..65535 sein, ist {port!r}", name=name, port=port))
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError(_t("ssh.hosts[{name}]: 'key' muss ein nicht-leerer Pfadtext sein, ist {key!r}", name=name, key=key))
        hosts.append(SshHost(name=name, host=host_value, user=user, port=port, key=key))
    return hosts


def find_host(cfg: dict, name: str) -> SshHost:
    hosts = hosts_from_config(cfg)
    for host in hosts:
        if host.name == name:
            return host
    available = ", ".join(h.name for h in hosts) or "keine"
    raise ValueError(_t("Host '{name}' nicht in ssh.hosts (vorhanden: {available})", name=name, available=available))


def find_ssh_exe() -> str:
    exe = shutil.which("ssh")
    if exe:
        return exe
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "OpenSSH" / "ssh.exe"
    if candidate.is_file():
        return str(candidate)
    raise SshError(_t("ssh.exe nicht gefunden, Windows-Feature „OpenSSH-Client“ installieren"))


def ssh_argv(host: SshHost, *, ssh_exe: str, timeout_s: float, strict_host_key: bool = True) -> list[str]:
    strict = "yes" if strict_host_key else "accept-new"
    return [
        ssh_exe, "-i", str(host.key_path()), "-p", str(host.port),
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={ceil(timeout_s)}",
        "-o", f"StrictHostKeyChecking={strict}",
        "-o", "LogLevel=ERROR",
        "--", f"{host.user}@{host.host}", REMOTE_SCRIPT,
    ]


def default_runner(argv: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise SshError(_t("Host antwortet nicht nach {timeout:.0f} s", timeout=timeout)) from None
    return result.returncode, result.stdout, result.stderr


def _translate_ssh_error(stderr: str, host: SshHost) -> str:
    text = stderr or ""
    low = text.lower()
    if "permission denied" in low:
        return (_t("Anmeldung abgelehnt. Ist der Schlüssel {key_path} für {user}@{host} hinterlegt?", key_path=host.key_path(), user=host.user, host=host.host))
    if "host key verification failed" in low:
        return _t("Host-Schlüssel unbekannt: einmal `ssh {user}@{host}` in einer Konsole bestätigen", user=host.user, host=host.host)
    if "could not resolve" in low or "timed out" in low:
        return _t("Host nicht erreichbar")
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line or _t("SSH-Verbindung fehlgeschlagen")


def scan_host(host: SshHost, *, runner: Runner | None = None, timeout_s: float = 20.0,
              strict_host_key: bool = True, ssh_exe: str | None = None,
              key_exists: Callable[[Path], bool] = Path.exists) -> list[DiskRow]:
    key_path = host.key_path()
    if not key_exists(key_path):
        raise SshError(_t("SSH-Schlüssel {key_path} nicht gefunden", key_path=key_path))
    exe = ssh_exe if ssh_exe is not None else find_ssh_exe()
    argv = ssh_argv(host, ssh_exe=exe, timeout_s=timeout_s, strict_host_key=strict_host_key)
    run = runner if runner is not None else default_runner
    returncode, stdout, stderr = run(argv, timeout_s)
    if returncode == 255:
        raise SshError(_translate_ssh_error(stderr, host))
    if returncode != 0 and not stdout.strip():
        raise SshError(stderr.strip() or _t("ssh beendete sich mit Code {returncode}", returncode=returncode))
    return parse_output(host.name, stdout)


# ---------- Auswertung der Fake-/Remote-Ausgabe ----------

def _split_sections(stdout: str) -> tuple[str, str, str]:
    if "@@BYID@@" not in stdout:
        raise SshError(_t("lsblk-Ausgabe nicht lesbar, Antwort unvollständig (Marker fehlen)"))
    lsblk_part, _, rest = stdout.partition("@@BYID@@")
    byid_part, _, zpool_part = rest.partition("@@ZPOOL@@")
    return lsblk_part, byid_part, zpool_part


def _parse_byid_lines(text: str) -> list[tuple[str, str]]:
    """Zeilen aus `find -printf '%f %l'` ("name ../../sda") oder `ls -l`
    ("… name -> ../../sda") -> Liste (by-id-Name, Zielgerät ohne Pfad)."""
    pairs: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "->" in line:
            left, _, right = line.rpartition("->")
            tokens = left.strip().split()
            if not tokens:
                continue
            name = tokens[-1]
            target = right.strip()
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            name, target = parts
        if not target:
            continue
        device = target.rsplit("/", 1)[-1]
        pairs.append((name, device))
    return pairs


def _byid_rank(name: str) -> int:
    """Index in `BYID_PREFERENCE`, längere/spezifischere Präfixe zuerst geprüft, damit
    "nvme-eui." nicht fälschlich als "nvme-" zählt."""
    for idx, prefix in sorted(enumerate(BYID_PREFERENCE), key=lambda item: -len(item[1])):
        if name.startswith(prefix):
            return idx
    return len(BYID_PREFERENCE)


def _byid_sort_key(name: str) -> tuple:
    rank = _byid_rank(name)
    duplicate_suffix = 1 if _TRAILING_NUM_SUFFIX_RE.search(name) else 0
    return (rank, duplicate_suffix, len(name), name)


def _strip_partition_suffix(device: str) -> str:
    match = _NVME_PART_RE.match(device)
    if match:
        return match.group(1)
    match = _SD_PART_RE.match(device)
    if match:
        return match.group(1)
    return device


def _resolve_pool_device(path: str, byid_to_device: Mapping[str, str]) -> str | None:
    prefix = "/dev/disk/by-id/"
    if path.startswith(prefix):
        name = _PART_RE.sub("", path[len(prefix):])
        return byid_to_device.get(name)
    if path.startswith("/dev/"):
        return _strip_partition_suffix(path[len("/dev/"):])
    return None


def _parse_zpool(text: str, devices: dict[str, dict], byid_to_device: Mapping[str, str]) -> None:
    current_pool: str | None = None
    current_vdev: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pool_match = _POOL_LINE_RE.match(raw_line)
        if pool_match:
            current_pool = pool_match.group(1)
            current_vdev = None
            continue
        if current_pool is None:
            continue
        token = line.split()[0]
        if token == current_pool:
            current_vdev = None
            continue
        if _VDEV_RE.match(token):
            current_vdev = token
            continue
        if token.startswith("/dev/"):
            device = _resolve_pool_device(token, byid_to_device)
            if device is not None and device in devices:
                devices[device]["pool"] = current_pool
                devices[device]["vdev"] = current_vdev


def parse_output(host_name: str, stdout: str) -> list[DiskRow]:
    lsblk_part, byid_part, zpool_part = _split_sections(stdout)
    try:
        data = json.loads(lsblk_part)
    except json.JSONDecodeError as exc:
        raise SshError(_t("lsblk-Ausgabe nicht lesbar ({exc})", exc=exc)) from exc

    order: list[str] = []
    devices: dict[str, dict] = {}
    for entry in data.get("blockdevices", []) or []:
        if entry.get("type") != "disk":
            continue
        name = str(entry.get("name", "")).strip()
        if not name or name.startswith(VIRTUAL_PREFIXES):
            continue
        devices[name] = {
            "model": (entry.get("model") or "").strip(),
            "serial": (entry.get("serial") or "").strip(),
            "size": (entry.get("size") or "").strip(),
            "tran": (entry.get("tran") or "").strip(),
            "wwn": (entry.get("wwn") or "").strip(),
            "by_id": None,
            "pool": None,
            "vdev": None,
        }
        order.append(name)

    byid_to_device: dict[str, str] = {}
    candidates: dict[str, list[str]] = {name: [] for name in devices}
    for name, device in _parse_byid_lines(byid_part):
        if device not in devices or _PART_RE.search(name):
            continue
        candidates[device].append(name)
        byid_to_device.setdefault(name, device)

    for device, names in candidates.items():
        if names:
            devices[device]["by_id"] = min(names, key=_byid_sort_key)

    for info in devices.values():
        if not info["serial"] and info["by_id"]:
            try:
                disk_id: DiskId = parse_by_id(info["by_id"])
            except SerialNotDerivable:
                pass
            else:
                info["serial"] = disk_id.serial

    _parse_zpool(zpool_part, devices, byid_to_device)

    return [
        DiskRow(host=host_name, device=name, model=devices[name]["model"], serial=devices[name]["serial"],
                size=devices[name]["size"], tran=devices[name]["tran"], wwn=devices[name]["wwn"],
                by_id=devices[name]["by_id"], pool=devices[name]["pool"], vdev=devices[name]["vdev"])
        for name in order
    ]


def rows_for_template(disks: Sequence[DiskRow], slots: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    slots = slots or {}
    return [
        {"host": d.host, "slot": slots.get(d.device) or d.device, "sn": d.serial or (d.by_id or "")}
        for d in disks
    ]


def disks_to_table(disks: Sequence[DiskRow], slots: Mapping[str, str] | None = None) -> Table:
    slots = slots or {}
    headers = ("host", "slot", "sn", "model", "device", "by_id", "pool", "vdev", "size")
    host_name = disks[0].host if disks else ""
    rows = tuple(
        (d.host, slots.get(d.device) or d.device, d.serial or (d.by_id or ""), d.model, d.device,
         d.by_id or "", d.pool or "", d.vdev or "", d.size)
        for d in disks
    )
    return Table(headers=headers, rows=rows, source=f"SSH {host_name}")
