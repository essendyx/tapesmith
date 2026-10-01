"""Update-Quellen: GitHub-Releases, Ordner bzw. Freigabe, HTTP(S)-Basis-URL.

Jede Quelle liefert `manifest.json` und `manifest.json.sig` (`fetch_manifest`, `None`: kein
passendes Release; mit `version` genau dieses Release), nennt mit `list_releases` alle über Python
installierbaren Releases (für die Versionsauswahl; Signaturen prüft der Dienst vor der Installation), lädt einzelne Release-Dateien gestreamt nach `<ziel>.part`, das erst am Ende
umbenannt wird (`download`), und nennt mit `pip_options` den Paketindex für pip: GitHub und
HTTP(S) nutzen PyPI, ein Ordner mit Wheels (direkt oder in `wheels`) wird zum einzigen Index
(`--no-index --find-links`, z. B. eine Freigabe im Firmennetz). HTTP läuft nur über `httpx` mit injizierbarem `transport` (Tests:
`httpx.MockTransport`), Zeitlimit 30 s je Anfrage. Das Repository ist öffentlich: GitHub wird ohne
Token abgefragt."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin

import httpx

from tapesmith.install.layout import parse_version
from tapesmith.update.errors import UpdateError
from tapesmith.update.manifest import check_file_name
from tapesmith.i18n import N_, _t

MANIFEST_NAME = "manifest.json"
SIGNATURE_NAME = "manifest.json.sig"
LOCK_NAME = "lock.txt"
TIMEOUT_S = 30.0
CHUNK = 256 * 1024
GITHUB_API = "https://api.github.com"
LIMIT_HINT = N_("Später erneut versuchen: GitHub begrenzt Abrufe ohne Anmeldung auf 60 je Stunde.")

Progress = Callable[[int, int | None], None]

_GITHUB_RE = re.compile(r"^github:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")


@dataclass(frozen=True)
class ReleaseInfo:
    """Ein über Python installierbares Release der Quelle (ungeprüft: nur für die Auswahl)."""
    version: str
    published: str | None = None
    prerelease: bool = False
    notes: str = ""


class Source(Protocol):
    description: str

    def fetch_manifest(self, version: str | None = None) -> tuple[bytes, bytes] | None: ...

    def list_releases(self) -> list[ReleaseInfo]: ...

    def download(self, name: str, dest: Path, progress: Progress | None = None) -> Path: ...

    def pip_options(self) -> dict: ...


def _user_agent() -> str:
    try:
        from tapesmith import __version__
    except ImportError:  # pragma: no cover
        return "tapesmith"
    return f"tapesmith/{__version__}"


def _manifest_info(data: bytes, *, any_schema: bool = False) -> ReleaseInfo | None:
    """Version, Datum, Kanal und Notizen aus einem (noch ungeprüften) Manifest; None, wenn es kein
    Python-Release (Schema 2) ist oder nicht lesbar. `any_schema`: auch ältere Manifeste (zum
    Finden einer bestimmten Version; ob sie installierbar ist, entscheidet der Dienst)."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("version"), str):
        return None
    if raw.get("schema") != 2 and not any_schema:
        return None
    try:
        parse_version(raw["version"])
    except ValueError:
        return None
    notes = raw.get("notes") if isinstance(raw.get("notes"), str) else ""
    published = raw.get("published") if isinstance(raw.get("published"), str) else None
    return ReleaseInfo(version=raw["version"], published=published, prerelease=raw.get("channel") != "stable",
                       notes=notes)


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(TIMEOUT_S), transport=transport, follow_redirects=True,
                        headers={"User-Agent": _user_agent()})


def _unreachable(where: str, exc: BaseException | None = None) -> UpdateError:
    detail = f": {type(exc).__name__}" if exc is not None else ""
    return UpdateError("update.source_unreachable", _t("Update-Quelle nicht erreichbar ({where}){detail}", where=where, detail=detail),
                       hint=_t("Netzwerk und Update-Quelle prüfen, später erneut versuchen."))


def _stream_to(response_cm, dest: Path, progress: Progress | None, where: str) -> Path:
    """Schreibt eine gestreamte Antwort nach `dest.part` und benennt am Ende um."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with response_cm as response:
            if response.status_code != 200:
                raise UpdateError("update.download_failed",
                                  _t("Download fehlgeschlagen ({where}): HTTP {status_code}", where=where, status_code=response.status_code))
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else None
            done = 0
            with open(part, "wb") as fh:
                for chunk in response.iter_bytes(CHUNK):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise UpdateError("update.download_failed", _t("Download abgebrochen ({where}): {name}", where=where, name=type(exc).__name__),
                          hint=_t("Netzwerk prüfen und erneut versuchen.")) from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    return dest


# ---------- Ordner bzw. Freigabe ----------

class FileSource:
    """`file:<Ordner>` (auch UNC): die drei Dateien liegen direkt im Ordner (neueste Version) und
    optional je Version in einem Unterordner (`<Ordner>\\0.4.2\\manifest.json` usw.)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.description = _t("Ordner {folder}", folder=self.folder)
        self._selected = self.folder

    def pip_options(self) -> dict:
        """Wheels im Ordner der gewählten Version (oder in `wheels`): pip nur aus diesem Ordner,
        sonst PyPI."""
        for base in dict.fromkeys((self._selected, self.folder)):
            for candidate in (base / "wheels", base):
                if candidate.is_dir() and any(candidate.glob("*.whl")):
                    return {"find_links": [str(candidate)], "no_index": True}
        return {}

    def _release_dirs(self) -> list[Path]:
        if not self.folder.is_dir():
            raise _unreachable(str(self.folder))
        dirs = [self.folder] if (self.folder / MANIFEST_NAME).is_file() else []
        try:
            dirs += sorted(d for d in self.folder.iterdir() if d.is_dir() and (d / MANIFEST_NAME).is_file())
        except OSError as exc:
            raise _unreachable(str(self.folder), exc) from exc
        return dirs

    def _read(self, folder: Path) -> tuple[bytes, bytes]:
        try:
            return (folder / MANIFEST_NAME).read_bytes(), (folder / SIGNATURE_NAME).read_bytes()
        except OSError as exc:
            raise UpdateError("update.source_invalid",
                              _t("Signatur oder Manifest in {folder} nicht lesbar: {exc}", folder=folder, exc=exc)) from exc

    def _infos(self, any_schema: bool = False) -> list[tuple[Path, ReleaseInfo]]:
        result = []
        for folder in self._release_dirs():
            try:
                info = _manifest_info((folder / MANIFEST_NAME).read_bytes(), any_schema=any_schema)
            except OSError:
                continue
            if info is not None:
                result.append((folder, info))
        return result

    def list_releases(self) -> list[ReleaseInfo]:
        found: dict[str, ReleaseInfo] = {}
        for _folder, info in self._infos():
            found.setdefault(info.version, info)
        return list(found.values())

    def fetch_manifest(self, version: str | None = None) -> tuple[bytes, bytes] | None:
        if version is None:
            if not self.folder.is_dir():
                raise _unreachable(str(self.folder))
            if not (self.folder / MANIFEST_NAME).is_file():
                return None
            self._selected = self.folder
            return self._read(self.folder)
        for folder, info in self._infos(any_schema=True):
            if info.version == version:
                self._selected = folder
                return self._read(folder)
        return None

    def download(self, name: str, dest: Path, progress: Progress | None = None) -> Path:
        src = self._selected / check_file_name(name)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            total = src.stat().st_size
            done = 0
            with open(src, "rb") as fin, open(part, "wb") as fout:
                for chunk in iter(lambda: fin.read(CHUNK), b""):
                    fout.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
        except OSError as exc:
            part.unlink(missing_ok=True)
            raise UpdateError("update.download_failed", _t("Paket {name} nicht lesbar: {exc}", name=name, exc=exc)) from exc
        os.replace(part, dest)
        return dest


# ---------- HTTP(S)-Basis-URL ----------

class UrlSource:
    """`https://…/`: die drei Dateien liegen relativ zur Basis-URL."""

    def __init__(self, base: str, *, transport: httpx.BaseTransport | None = None):
        self.base = base if base.endswith("/") else base + "/"
        self.transport = transport
        self.description = _t("Adresse {base}", base=self.base)

    def pip_options(self) -> dict:
        return {}

    def _url(self, name: str) -> str:
        return urljoin(self.base, check_file_name(name))

    def _get(self, client: httpx.Client, name: str, *, required: bool) -> bytes | None:
        try:
            response = client.get(self._url(name))
        except httpx.HTTPError as exc:
            raise _unreachable(self.base, exc) from exc
        if response.status_code == 404 and not required:
            return None
        if response.status_code != 200:
            raise _unreachable(f"{self.base}, HTTP {response.status_code}")
        return response.content

    def fetch_manifest(self, version: str | None = None) -> tuple[bytes, bytes] | None:
        """Unter einer Adresse liegt nur eine Version: mit `version` nur, wenn sie passt."""
        with _client(self.transport) as client:
            manifest = self._get(client, MANIFEST_NAME, required=False)
            if manifest is None:
                return None
            if version is not None:
                info = _manifest_info(manifest, any_schema=True)
                if info is None or info.version != version:
                    return None
            signature = self._get(client, SIGNATURE_NAME, required=True)
        return manifest, signature or b""

    def list_releases(self) -> list[ReleaseInfo]:
        with _client(self.transport) as client:
            manifest = self._get(client, MANIFEST_NAME, required=False)
        info = _manifest_info(manifest) if manifest is not None else None
        return [info] if info is not None else []

    def download(self, name: str, dest: Path, progress: Progress | None = None) -> Path:
        with _client(self.transport) as client:
            return _stream_to(client.stream("GET", self._url(name)), dest, progress, name)


# ---------- GitHub-Releases ----------

class GitHubSource:
    """`github:<owner>/<repo>`: höchste Version aus Tags `v<version>`, `draft` nie, `prerelease`
    nur im Kanal `beta`. Assets über die Asset-API (`Accept: application/octet-stream`), ohne Token
    (öffentliches Repository)."""

    def __init__(self, owner: str, repo: str, *, channel: str = "stable",
                 transport: httpx.BaseTransport | None = None):
        self.owner = owner
        self.repo = repo
        self.channel = channel
        self.transport = transport
        self.description = f"GitHub {owner}/{repo}"
        self._assets: dict[str, int] | None = None
        self.release_version: str | None = None

    def pip_options(self) -> dict:
        return {}

    def _headers(self, accept: str) -> dict:
        return {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}

    def _api(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.owner}/{self.repo}{path}"

    def _check_status(self, response: httpx.Response, what: str) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in (401, 403, 429):
            raise UpdateError("update.source_unreachable",
                              _t("GitHub lehnt den Abruf ab (HTTP {status}, {what})", status=status, what=what), hint=_t(LIMIT_HINT))
        if status == 404:
            raise _unreachable(_t("{owner}/{repo} nicht gefunden", owner=self.owner, repo=self.repo))
        raise _unreachable(f"GitHub HTTP {status}")

    @staticmethod
    def _usable(release) -> tuple | None:
        """Versionsschlüssel eines brauchbaren Releases (kein Entwurf, Tag `v<version>`, Manifest
        und Signatur vorhanden), sonst None."""
        if not isinstance(release, dict) or release.get("draft"):
            return None
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith("v"):
            return None
        try:
            key = parse_version(tag[1:])
        except ValueError:
            return None
        names = {a.get("name") for a in release.get("assets") or [] if isinstance(a, dict)}
        if MANIFEST_NAME not in names or SIGNATURE_NAME not in names:
            return None
        return key

    def _select(self, releases: list, version: str | None = None) -> dict | None:
        """Höchste passende Version; mit `version` genau diese (auch eine Vorabversion: wer sie
        ausdrücklich wählt, bekommt sie, den Kanal prüft der Dienst)."""
        best: tuple[tuple, dict] | None = None
        for release in releases:
            key = self._usable(release)
            if key is None:
                continue
            if version is not None:
                if str(release["tag_name"])[1:] == version:
                    return release
                continue
            if release.get("prerelease") and self.channel != "beta":
                continue
            if best is None or key > best[0]:
                best = (key, release)
        return best[1] if best else None

    def _releases(self, client: httpx.Client) -> list:
        try:
            response = client.get(self._api("/releases"), params={"per_page": 100},
                                  headers=self._headers("application/vnd.github+json"))
        except httpx.HTTPError as exc:
            raise _unreachable("api.github.com", exc) from exc
        self._check_status(response, "Releases")
        try:
            releases = response.json()
        except ValueError as exc:
            raise _unreachable(_t("GitHub-Antwort ist kein JSON")) from exc
        return releases if isinstance(releases, list) else []

    @staticmethod
    def _summary(body: object) -> str:
        """Erster Absatz der Release-Beschreibung (ohne den Installationshinweis)."""
        if not isinstance(body, str):
            return ""
        for part in body.replace("\r\n", "\n").split("\n\n"):
            text = part.strip()
            if text and not text.startswith(("Installation", "Install")):
                return text[:500]
        return ""

    def list_releases(self) -> list[ReleaseInfo]:
        """Alle Releases mit Manifest, Signatur und Lock-Liste (also über Python installierbar),
        Vorabversionen markiert. Ein einziger Abruf der GitHub-API, keine Manifeste."""
        with _client(self.transport) as client:
            releases = self._releases(client)
        result = []
        for release in releases:
            if self._usable(release) is None:
                continue
            names = {a.get("name") for a in release.get("assets") or [] if isinstance(a, dict)}
            if LOCK_NAME not in names:
                continue
            published = release.get("published_at") if isinstance(release.get("published_at"), str) else None
            result.append(ReleaseInfo(version=str(release["tag_name"])[1:], published=published,
                                      prerelease=bool(release.get("prerelease")),
                                      notes=self._summary(release.get("body"))))
        return result

    def _list_and_select(self, client: httpx.Client, version: str | None = None) -> None:
        release = self._select(self._releases(client), version)
        if release is None:
            self._assets = {}
            self.release_version = None
            return
        self.release_version = str(release["tag_name"])[1:]
        self._assets = {str(a["name"]): int(a["id"]) for a in release.get("assets") or []
                        if isinstance(a, dict) and "name" in a and "id" in a}

    def _asset_url(self, name: str) -> str:
        assert self._assets is not None
        if name not in self._assets:
            raise UpdateError("update.download_failed", _t("Release enthält die Datei {name} nicht", name=name))
        return self._api(f"/releases/assets/{self._assets[name]}")

    def _get_asset(self, client: httpx.Client, name: str) -> bytes:
        try:
            response = client.get(self._asset_url(name), headers=self._headers("application/octet-stream"))
        except httpx.HTTPError as exc:
            raise _unreachable(_t("GitHub-Asset"), exc) from exc
        self._check_status(response, name)
        return response.content

    def fetch_manifest(self, version: str | None = None) -> tuple[bytes, bytes] | None:
        with _client(self.transport) as client:
            self._list_and_select(client, version)
            if not self._assets:
                return None
            return self._get_asset(client, MANIFEST_NAME), self._get_asset(client, SIGNATURE_NAME)

    def download(self, name: str, dest: Path, progress: Progress | None = None) -> Path:
        with _client(self.transport) as client:
            if self._assets is None:
                self._list_and_select(client)
            url = self._asset_url(name)
            return _stream_to(client.stream("GET", url, headers=self._headers("application/octet-stream")),
                              dest, progress, name)


def parse_source(text: str, *, transport: httpx.BaseTransport | None = None,
                 channel: str = "stable") -> Source:
    """Quelle aus `update.source`. Unbekannte Form: `update.source_invalid`."""
    value = (text or "").strip()
    match = _GITHUB_RE.match(value)
    if match:
        return GitHubSource(match.group(1), match.group(2), channel=channel, transport=transport)
    if value.startswith("file:") and value[len("file:"):].strip():
        return FileSource(Path(value[len("file:"):]))
    if value.startswith(("https://", "http://")) and " " not in value and "#" not in value:
        return UrlSource(value, transport=transport)
    raise UpdateError("update.source_invalid",
                      _t("Update-Quelle {text!r} ungültig: github:<owner>/<repo>, file:<Ordner> oder https://…", text=text),
                      hint=_t("Update-Quelle in den Einstellungen prüfen."))
