# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

## What is signed

Release builds of Tapesmith are built from this repository by GitHub Actions
([.github/workflows/release.yml](.github/workflows/release.yml)) on GitHub hosted runners. The
workflow runs the test suite, builds the web interface and the portable app with PyInstaller and
submits the unsigned folder to SignPath. Only `Tapesmith.exe`, the one binary built from this
repository, is signed ([.signpath/artifact-configuration.xml](.signpath/artifact-configuration.xml));
its product name and version are checked during signing. The folder `_internal` contains
unmodified binaries of upstream open source projects (Python, Qt for Python, Pillow, cryptography
and others); they keep the signature of their publisher or stay unsigned, they are not signed with
the Tapesmith certificate. Every signing request is approved by hand in SignPath, and every release
additionally needs the approval of the maintainer in the GitHub environment `release`.

The update manifest of each release (`manifest.json`) is signed separately with an Ed25519 key
listed in [src/tapesmith/update/trusted_keys.json](src/tapesmith/update/trusted_keys.json); the app
installs updates only with a valid manifest signature and a matching SHA-256 of the zip file.

## Team roles

- Committers and reviewers: the project maintainer (owner of the repository
  [github.com/essendyx/tapesmith](https://github.com/essendyx/tapesmith)). Contributions from others
  arrive as pull requests and are reviewed by the maintainer before they are merged.
- Approvers: the project maintainer (owner of the repository
  [github.com/essendyx/tapesmith](https://github.com/essendyx/tapesmith)).

All team members use multi factor authentication for GitHub and SignPath.

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
  the latest release of this repository and, if you install an update, downloads the release files
  from GitHub. Only the usual connection data (IP address, a user agent with the program version)
  reaches GitHub; no labels, settings or personal data are sent. See the
  [GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).
- **Optional integrations (only when you set them up):** Tapesmith ships without preset addresses or
  tokens, and every integration stays off until you enter its address and turn it on: MQTT broker
  (Home Assistant discovery), Telegram notifications through the Telegram Bot API (see the
  [Telegram privacy policy](https://telegram.org/privacy)), Paperless-ngx, Home Assistant, Proxmox VE,
  NetBox, an Obsidian vault via MCP, the short link service, SSH disk scans and DNS lookups of the
  plausibility check. These
  connect only to the servers you configure and only transfer the data needed for the feature you
  use.

Tapesmith contains no telemetry, no crash reporting and no advertising.
