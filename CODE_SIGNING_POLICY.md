# Release signing and privacy policy

## How releases are built and published

Releases of Tapesmith are built from this repository by GitHub Actions
([.github/workflows/release.yml](.github/workflows/release.yml)) on GitHub hosted runners when the
maintainer pushes a version tag. The workflow runs the test suite, builds the web interface, the
wheel and the source distribution of the Python package `tapesmith`, downloads all wheels needed
on Windows (x64) for Python 3.11 and 3.12 and writes a lock list with the SHA-256 of every wheel.
A trial installation from exactly these wheels with `pip install --require-hashes` and the
self test of the installed version must pass.

Tapesmith has no code signing certificate and ships no executable of its own. It runs with the
signed Python interpreter from python.org (`pythonw.exe -m tapesmith...`); all native code comes
as unmodified wheels of the upstream projects from the Python Package Index (Qt for Python,
Pillow, cryptography, pydantic and others) and keeps the signature of their publisher or stays
unsigned.

- **Update manifest:** the manifest of each release (`manifest.json`, with version, channel and the
  full lock list) is signed with an Ed25519 key listed in
  [src/tapesmith/update/trusted_keys.json](src/tapesmith/update/trusted_keys.json). Signing runs in
  the GitHub environment `release`, which needs the approval of the maintainer. The installed app
  accepts an update only with a valid manifest signature and installs it with
  `pip install --require-hashes --only-binary=:all:`, so pip accepts only wheels whose SHA-256 is
  listed in the signed manifest.
- **PyPI:** the package is uploaded with PyPI Trusted Publishing (OpenID Connect from the workflow,
  no stored API token) from the GitHub environment `pypi`.
- **GitHub release:** `manifest.json`, `manifest.json.sig`, `lock.txt` and the wheel are attached to
  the release after the upload to PyPI.

## Team roles

- Committers and reviewers: the project maintainer (owner of the repository
  [github.com/essendyx/tapesmith](https://github.com/essendyx/tapesmith)). Contributions from others
  arrive as pull requests and are reviewed by the maintainer before they are merged.
- Approvers: the project maintainer (owner of the repository
  [github.com/essendyx/tapesmith](https://github.com/essendyx/tapesmith)).

All team members use multi factor authentication for GitHub and PyPI.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it.

In detail, Tapesmith makes the following network connections:

- **Printer:** a Bluetooth connection (serial port or Bluetooth LE) to the label printer you paired
  and selected. No other device is contacted.
- **Local web interface:** the print service listens on `127.0.0.1` only and opens the interface in
  your default browser. Access from your LAN is off unless you turn on `lan.enabled`, and then it
  requires an API token.
- **Update check (only with your consent):** the automatic update check is off by default. On the
  first start of the installed app the web interface asks once whether Tapesmith may check for
  updates; you can change the answer at any time under Settings > Updates (`update.enabled`). When
  it is on, or when you click "Check now", Tapesmith asks the GitHub REST API (`api.github.com`) for
  the latest release of this repository and, if you install an update, downloads the signed
  release files from GitHub and the packages listed in them from the Python Package Index
  (`pypi.org`, `files.pythonhosted.org`) with pip. Only the usual connection data (IP address, a user
  agent with the program or pip version) reaches GitHub and PyPI; no labels, settings or personal
  data are sent. See the
  [GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)
  and the [PyPI privacy notice](https://policies.python.org/pypi.org/Privacy-Notice/).
- **Optional integrations (only when you set them up):** Tapesmith ships without preset addresses or
  tokens, and every integration stays off until you enter its address and turn it on: MQTT broker
  (Home Assistant discovery), Telegram notifications through the Telegram Bot API (see the
  [Telegram privacy policy](https://telegram.org/privacy)), Paperless-ngx, Home Assistant, Proxmox VE,
  NetBox, an Obsidian vault via MCP, the short link service, SSH disk scans and DNS lookups of the
  plausibility check. These
  connect only to the servers you configure and only transfer the data needed for the feature you
  use.

Tapesmith contains no telemetry, no crash reporting and no advertising.
