"""Update-Quellen (Ordner, HTTPS, GitHub-Releases). Nur `httpx.MockTransport`, nie echtes Netz."""

from __future__ import annotations

import httpx
import pytest

from tapesmith.update import sources
from tapesmith.update.errors import UpdateError
from tapesmith.update.sources import FileSource, GitHubSource, UrlSource, parse_source


@pytest.fixture(autouse=True)
def kein_echtes_netz(monkeypatch):
    """Wächter: jede echte HTTP-Verbindung schlägt laut fehl."""
    def boom(self, request):
        raise AssertionError(f"echtes Netz benutzt: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)


# ---------- parse_source ----------

def test_parse_source_formen(tmp_path):
    assert isinstance(parse_source("github:your-org/tapesmith"), GitHubSource)
    assert isinstance(parse_source(f"file:{tmp_path}"), FileSource)
    src = parse_source("https://example.invalid/p12")
    assert isinstance(src, UrlSource) and src.base == "https://example.invalid/p12/"
    for bad in ("", "ftp://x", "github:ohne-repo", "file:", "https://a b", "https://x/#frag"):
        with pytest.raises(UpdateError) as info:
            parse_source(bad)
        assert info.value.code == "update.source_invalid"


def test_waechter_greift():
    with pytest.raises(AssertionError, match="echtes Netz"):
        httpx.get("https://example.invalid/")


# ---------- Ordner ----------

def test_file_quelle_mit_drei_dateien(tmp_path):
    (tmp_path / "manifest.json").write_bytes(b"{}")
    (tmp_path / "manifest.json.sig").write_bytes(b"c2ln")
    (tmp_path / "Tapesmith-portable-0.2.1.zip").write_bytes(b"z" * 1000)
    src = FileSource(tmp_path)
    assert src.fetch_manifest() == (b"{}", b"c2ln")
    seen = []
    dest = src.download("Tapesmith-portable-0.2.1.zip", tmp_path / "dl" / "p.zip",
                        progress=lambda done, total: seen.append((done, total)))
    assert dest.read_bytes() == b"z" * 1000
    assert seen[-1] == (1000, 1000)
    assert not (tmp_path / "dl" / "p.zip.part").exists()


def test_file_quelle_fehler(tmp_path):
    with pytest.raises(UpdateError) as info:
        FileSource(tmp_path / "fehlt").fetch_manifest()
    assert info.value.code == "update.source_unreachable"
    assert FileSource(tmp_path).fetch_manifest() is None
    with pytest.raises(UpdateError) as info:
        FileSource(tmp_path).download("gibtsnicht.zip", tmp_path / "x.zip")
    assert info.value.code == "update.download_failed"
    with pytest.raises(UpdateError) as info:
        FileSource(tmp_path).download("../boese.zip", tmp_path / "x.zip")
    assert info.value.code == "update.source_invalid"


# ---------- HTTPS ----------

def test_https_quelle_relativ_zur_basis(tmp_path):
    files = {"/u/p12/manifest.json": b"{}", "/u/p12/manifest.json.sig": b"c2ln",
             "/u/p12/Tapesmith-portable-0.2.1.zip": b"zip" * 100}
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = files.get(request.url.path)
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    src = UrlSource("https://updates.invalid/u/p12", transport=httpx.MockTransport(handler))
    assert src.fetch_manifest() == (b"{}", b"c2ln")
    dest = src.download("Tapesmith-portable-0.2.1.zip", tmp_path / "p.zip")
    assert dest.read_bytes() == b"zip" * 100
    assert all(r.url.host == "updates.invalid" for r in requests)


def test_https_ohne_manifest_und_fehler(tmp_path):
    src = UrlSource("https://updates.invalid/", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert src.fetch_manifest() is None
    with pytest.raises(UpdateError) as info:
        src.download("x.zip", tmp_path / "x.zip")
    assert info.value.code == "update.download_failed"
    assert not (tmp_path / "x.zip.part").exists()

    src = UrlSource("https://updates.invalid/", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(UpdateError) as info:
        src.fetch_manifest()
    assert info.value.code == "update.source_unreachable"


def test_https_verbindungsfehler_source_unreachable(tmp_path):
    def handler(request):
        raise httpx.ConnectError("kein Netz", request=request)

    src = UrlSource("https://updates.invalid/", transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateError) as info:
        src.fetch_manifest()
    assert info.value.code == "update.source_unreachable"
    with pytest.raises(UpdateError) as info:
        src.download("x.zip", tmp_path / "x.zip")
    assert info.value.code == "update.download_failed"


# ---------- GitHub ----------

def _asset(aid: int, name: str) -> dict:
    return {"id": aid, "name": name}


def _release(tag: str, base: int, *, prerelease=False, draft=False) -> dict:
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft,
            "assets": [_asset(base + 1, "manifest.json"), _asset(base + 2, "manifest.json.sig"),
                       _asset(base + 3, f"Tapesmith-portable-{tag[1:]}.zip")]}


RELEASES = [
    _release("v0.2.0", 100),
    _release("v0.3.0-beta.1", 200, prerelease=True),
    _release("v0.2.1", 300),
    _release("v0.9.0", 900, draft=True),
    {"tag_name": "nightly", "prerelease": False, "draft": False, "assets": []},
]


class GitHubMock:
    def __init__(self, releases=RELEASES, *, status: int = 200, redirect: bool = False):
        self.releases = releases
        self.status = status
        self.redirect = redirect
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "objects.githubusercontent.com":
            return httpx.Response(200, content=b"PAKET" * 10)
        if path == "/repos/your-org/tapesmith/releases":
            if self.status != 200:
                return httpx.Response(self.status, json={"message": "Not Found"})
            return httpx.Response(200, json=self.releases)
        if path.startswith("/repos/your-org/tapesmith/releases/assets/"):
            aid = int(path.rsplit("/", 1)[1])
            if self.redirect and aid % 100 == 3:
                return httpx.Response(302, headers={"Location": f"https://objects.githubusercontent.com/x/{aid}"})
            return httpx.Response(200, content=f"asset-{aid}".encode())
        return httpx.Response(404)


def _gh(mock, *, channel="stable"):
    return GitHubSource("your-org", "tapesmith", channel=channel, transport=httpx.MockTransport(mock))


def test_github_stable_waehlt_hoechste_stabile_version():
    mock = GitHubMock()
    src = _gh(mock)
    assert src.fetch_manifest() == (b"asset-301", b"asset-302")
    assert src.release_version == "0.2.1"
    first = mock.requests[0]
    assert str(first.url) == "https://api.github.com/repos/your-org/tapesmith/releases?per_page=20"
    assert first.headers["Accept"] == "application/vnd.github+json"
    assert first.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert "Authorization" not in first.headers
    assert mock.requests[1].headers["Accept"] == "application/octet-stream"


def test_github_beta_waehlt_prerelease():
    src = _gh(GitHubMock(), channel="beta")
    assert src.fetch_manifest() == (b"asset-201", b"asset-202")
    assert src.release_version == "0.3.0-beta.1"


def test_github_ohne_passendes_release():
    assert _gh(GitHubMock(releases=[_release("v0.5.0", 500, draft=True)])).fetch_manifest() is None


def test_github_download_weiterleitung(tmp_path):
    mock = GitHubMock(redirect=True)
    src = _gh(mock)
    src.fetch_manifest()
    dest = src.download("Tapesmith-portable-0.2.1.zip", tmp_path / "p.zip")
    assert dest.read_bytes() == b"PAKET" * 10
    asset_req, cdn_req = mock.requests[-2], mock.requests[-1]
    assert asset_req.url.path == "/repos/your-org/tapesmith/releases/assets/303"
    assert "Authorization" not in asset_req.headers
    assert cdn_req.url.host == "objects.githubusercontent.com"
    assert "Authorization" not in cdn_req.headers


def test_github_download_ohne_vorherige_pruefung(tmp_path):
    src = _gh(GitHubMock())
    dest = src.download("Tapesmith-portable-0.2.1.zip", tmp_path / "p.zip")
    assert dest.read_bytes() == b"asset-303"
    with pytest.raises(UpdateError) as info:
        src.download("fehlt.zip", tmp_path / "f.zip")
    assert info.value.code == "update.download_failed"


def test_github_ohne_token_ohne_kopf():
    """Das Repository ist öffentlich: nie ein Authorization-Kopf."""
    mock = GitHubMock()
    assert _gh(mock).fetch_manifest() is not None
    assert all("Authorization" not in r.headers for r in mock.requests)


def test_github_abgelehnt_bzw_repo_fehlt():
    for status in (401, 403, 429):
        with pytest.raises(UpdateError) as info:
            _gh(GitHubMock(status=status)).fetch_manifest()
        assert info.value.code == "update.source_unreachable"
        assert "60 je Stunde" in info.value.hint
    with pytest.raises(UpdateError) as info:
        _gh(GitHubMock(status=404)).fetch_manifest()
    assert info.value.code == "update.source_unreachable"
    assert "nicht gefunden" in str(info.value)
    with pytest.raises(UpdateError) as info:
        _gh(GitHubMock(status=500)).fetch_manifest()
    assert info.value.code == "update.source_unreachable"


def test_github_verbindungsfehler_source_unreachable():
    def handler(request):
        raise httpx.ConnectTimeout("zu langsam", request=request)

    src = GitHubSource("your-org", "tapesmith", transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateError) as info:
        src.fetch_manifest()
    assert info.value.code == "update.source_unreachable"


def test_zeitlimit_30s_je_anfrage():
    seen = []

    def handler(request):
        seen.append(request.extensions.get("timeout"))
        return httpx.Response(404)

    UrlSource("https://updates.invalid/", transport=httpx.MockTransport(handler)).fetch_manifest()
    assert sources.TIMEOUT_S == 30.0
    assert seen and seen[0]["connect"] == 30.0 and seen[0]["read"] == 30.0
