# Tapesmith

**Label studio for the Phomemo P12.**

Tapesmith is a Windows application for the Phomemo P12 Bluetooth label printer (12 mm tape). It
replaces the phone app with a fast local print service, a browser based editor, a template gallery,
a command line and optional integrations for home labs and home automation. Everything runs on your
own PC; nothing is sent to a cloud service.

![Quick print (light)](docs/screenshots/schnelldruck-hell-desktop-en.png)

## Screenshots

| Editor | Template gallery |
|---|---|
| ![Editor](docs/screenshots/editor-hell-desktop-en.png) | ![Gallery](docs/screenshots/galerie-hell-desktop-en.png) |
| **Print history** | **Settings (dark)** |
| ![History](docs/screenshots/verlauf-hell-desktop-en.png) | ![Settings](docs/screenshots/einstellungen-dunkel-desktop-en.png) |

More screenshots (German and English, light and dark, desktop and phone):
[docs/screenshots](docs/screenshots/index.md). All screenshots are taken from neutral demo data.

## Features

- **Quick print** from the browser, the tray icon or a global hotkey (Ctrl+Alt+L), with automatic
  text fitting and a live preview at real size.
- **Editor** with text, QR codes, Code128, DataMatrix, icons, shapes and images, multiple tabs,
  undo, autosave and crash recovery.
- **Template gallery** with more than 30 built in templates (storage, kitchen, office, network
  and power labels, cable flags, grid strips for patch panels and fuse boxes) and your own
  templates as JSON files.
- **Series printing** from CSV, Excel or the clipboard, numbering ranges and counters.
- **Print service** that owns the printer connection: queue with automatic retry, print history,
  statistics, tape roll tracking and misprint protection.
- **Command line** (`tapesmith`, short alias `p12`) for scripts, plus a PowerShell module.
- **Accessibility and languages:** keyboard operation, screen reader labels, high contrast, dark
  mode. English and German throughout: web interface, tray, print service messages, built in
  templates and command line follow the Windows display language (any language other than German
  gives English), or the setting `app.language`; `TAPESMITH_LANG=en` forces a language for the CLI.
- **Installer without admin rights** and signed automatic updates with rollback.

### Optional modules

Everything beyond the core app is a built in module that is off until you turn it on under
Settings > Modules (or `tapesmith module enable <id>`). Modules that are off appear nowhere in the
interface. Available: Inventory (boxes, contents, lending), Drives (drives of this PC, SSH disk scanner
and ZFS disk replacement assistant), Proxmox VE (VM and container labels), Paperless-ngx (ASN and
warranty labels), Home Assistant (battery and maintenance labels), Obsidian vault via MCP, Assets with
short links (`deploy/shortlink`), NetBox cable import, classifieds and a serial number scan from a
photo. Tapesmith ships without any preset addresses or tokens. Also part of the core app: MQTT discovery
for Home Assistant, Telegram notifications, a hot folder and an MCP server for AI assistants.
Setup notes: [docs/manual.md](docs/manual.md) (English), [docs/handbuch.md](docs/handbuch.md) (German)
and [deploy/](deploy/).

## Installation

Signed release builds are published on the releases page once code signing through the SignPath
Foundation is set up (see [Code signing policy](#code-signing-policy)). Until then, build Tapesmith
from source as described under [Development](#development).

1. Download `Tapesmith-portable-<version>.zip` from the
   [releases page](https://github.com/essendyx/tapesmith/releases) and unpack it.
2. Either run `Tapesmith.exe` directly (portable) or double click `Installieren.cmd` to install it
   for the current user under `%LOCALAPPDATA%\Programs\Tapesmith` (no admin rights, start menu
   entry, entry under Installed apps, optional autostart of the tray icon).
3. Pair the printer in Windows Bluetooth settings, then run `tapesmith setup` (or use the settings
   page) to pick the printer.

Your settings and history live in `%APPDATA%\Tapesmith`. Uninstalling never deletes them.

**Upgrading from "P12 Label" (0.2.x):** on first start Tapesmith copies `%APPDATA%\P12Label` to
`%APPDATA%\Tapesmith` once (the old folder stays as a backup), and the installer removes the program
files, start menu entry, autostart and uninstall entry of the old installation. Links using
`p12label://` keep working as an alias of `tapesmith://`; old `P12LABEL_*` environment variables
still work as a fallback for `TAPESMITH_*`.

## Security

- The print service listens on `127.0.0.1` only. Access from your LAN is opt in (`lan.enabled`),
  limited to configured private networks and always requires an API token (roles: admin, print,
  family). Tokens are stored as SHA-256 hashes only.
- Host and Origin headers are checked (DNS rebinding protection), failed logins are rate limited.
- Secrets never go into configuration files: settings hold references such as
  `keyring:tapesmith/mqtt` (Windows Credential Manager), `file:<path>` or `env:<NAME>`.
- Updates are only installed if the manifest carries a valid Ed25519 signature from a key listed
  in `src/tapesmith/update/trusted_keys.json`.
- The automatic update check is off until you agree: the web interface asks once on the first start
  of the installed app (Settings > Updates changes it later).

Please report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

- Committers and reviewers: the project maintainer (owner of
  [github.com/essendyx/tapesmith](https://github.com/essendyx/tapesmith))
- Approvers: the project maintainer (owner of
  [github.com/essendyx/tapesmith](https://github.com/essendyx/tapesmith))

Privacy: This program will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it. Which connections
Tapesmith makes, what is signed and how releases are built: [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md).

## Development

Requirements: Windows 10 or 11, Python 3.11 or newer, Node.js 20 or newer (only to build the web UI).

```
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest -q
cd web && npm ci && npm run check
python tools\build_web.py          # builds the web UI into src/tapesmith/webui/static
python tools\build_portable.py --zip
```

Tests never print, never open real COM ports, Bluetooth or network services and never touch your
real data folder (they run with `TAPESMITH_HOME` set to a temporary folder). Hardware tests are
marked `@pytest.mark.hardware` and only run with `--hardware`. See [CONTRIBUTING.md](CONTRIBUTING.md).

Documentation: user manual in English [docs/manual.md](docs/manual.md) and German
[docs/handbuch.md](docs/handbuch.md), hardware and protocol findings
[docs/hardware/README.md](docs/hardware/README.md), operations notes
[deploy/infra/README.md](deploy/infra/README.md). Translations: `web/src/locales/`,
`src/tapesmith/locales/` and the message catalog `src/tapesmith/locales/messages/en.json`
(maintained with `python tools/i18n_messages.py`).

## License

Tapesmith is released under the [MIT License](LICENSE). Third party components and their licenses
are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Acknowledgements

The P12 print protocol was first documented by the
[phomemo-p12-tools](https://github.com/soburi/phomemo-p12) project (MIT License, Copyright (c) 2022
Timo "polskafan" Dobbrick, packaged by TOKITA Hiroshi). Tapesmith keeps a byte compatible reference
stream in its tests and offers the old `phomemo_render_label` and `phomemo_print_p12` commands for
compatibility. Icons come from [Tabler Icons](https://tabler.io/icons) (MIT) and
[Simple Icons](https://simpleicons.org/) (CC0); label fonts are DejaVu.

Tapesmith is an independent project and not affiliated with Phomemo.
