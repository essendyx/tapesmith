# Tapesmith: User manual (English)

Detailed manual for Tapesmith, the Windows application for the Phomemo P12 label printer
(Bluetooth, 12 mm tape). The short overview is in the [README](../README.md); the same manual in
German is [handbuch.md](handbuch.md).

Tapesmith speaks English and German. With the default setting it follows the Windows display
language of the PC it runs on: German on a German Windows, English for every other language (see
“Language” below). Command line options, subcommands, template IDs and a few configuration values
are German identifiers and stay the same in both languages.

## Quick start

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\p12 doctor
.venv\Scripts\p12 print-image label.png        # width 96 or up to 88 dots
.venv\Scripts\p12 --transport file:job.bin calibrate edge   # dry run
.venv\Scripts\p12 verify                       # guided test series (own console window)
.venv\Scripts\p12 text "pmx10 SSD-1" "SN 274913" --max-mm 40 --preview v.png   # text with auto-fit, preview first
.venv\Scripts\p12 text "SSD-1" --qr S4EWNX0R123456                            # QR on the left, text on the right
.venv\Scripts\p12 template list                                               # templates
.venv\Scripts\p12 template print datentraeger-qr --set sn=ata-SanDisk_SDSSDHP256G_112233274913
.venv\Scripts\python -m pytest                 # without printer
.venv\Scripts\python -m pytest --hardware      # with printer
```
Exit codes: 0 ok, 1 error/configuration, 5 printer unreachable, 6 template or variable missing/invalid, 7 printer busy.

Your own templates (`*.tapesmith.json`) live in `%APPDATA%\Tapesmith\templates` and override built in templates with the same name.

## Command line

Every print (`text`, `template print`, `print-image`, `print`, `qr`, `reprint`) goes through the
print pipeline: status query first (warning only, never blocks), misprint protection with
confirmation, copies and chains, history, export and a clean cancel with Ctrl+C (the rest is filled
with white, then fed out).

```
p12 status                                    # battery, lid, tape, firmware (--json)
p12 setup --test-label                        # find the port, test it, save it in config.json
p12 text "SSD-1" --copies 4 --chain           # 4 copies as a chain with cut lines (saves leader/trailer)
p12 text "Cable 01" --copies 10 --chain --yes # confirm questions (many copies/overlength) in advance
p12 text "SSD-1" --export label.pdf           # also store as PDF/PNG/PBM (the extension decides the format)
p12 text "pmx10 SSD-1 SN 274913" --size 60 --max-mm 30   # does not fit -> suggestions "--fix …"
p12 text "pmx10 SSD-1 SN 274913" --size 60 --max-mm 30 --fix laenger
echo pmx10 | p12 print                        # text from stdin
p12 print --image logo.png --fit              # image, shrink images that are too large
p12 qr wifi --ssid Guest --password-prompt    # never pass the password as an argument (shell history)
p12 history 274913                            # search the history (substrings too)
p12 reprint last                              # reprint the last job (copies/chain like the original)
p12 reprint 17 --copies 1                     # entry 17, your own copy count wins
p12 reprint last --prompt pw                  # sensitive template: enter the field again hidden
```

Common print options: `--preview FILE.png` (preview only, with a tape balance for copies/chains),
`--copies N`, `--chain`, `--no-cut-marks`, `-y/--yes`, `--export FILE`.

`reprint`: sensitive templates (e.g. Wi-Fi password) store neither the image nor the plain text; when
reprinting, enter the field hidden with `--prompt FIELD`. Wi-Fi QR codes from `p12 qr wifi` or the QR
page store the SSID, security type and layout, the password only masked: `p12 reprint last --prompt password`
(the web interface asks for it hidden on “Print again”). `--set FIELD=VALUE` works too but ends up in
the shell history. If a job contained several different labels, `reprint` prints only the first one
(in the CLI every command creates exactly one label per job anyway).

Legacy commands (compatibility with phomemo-p12-tools): `phomemo_render_label` and `phomemo_print_p12`
are installed as well and point to the new commands.

Errors appear as plain text with a hint on what to do (`-> …`). Exit codes are unchanged:
0 ok, 1 error/configuration/not confirmed/canceled, 5 unreachable or print incomplete,
6 template/variable, 7 busy (also a COM port held by another program). 2 to 4 are reserved
(argparse uses 2 for usage errors).

Messages and help texts of the command line follow the language setting (see “Language”);
`TAPESMITH_LANG=en` or `TAPESMITH_LANG=de` forces a language, for example in scripts that expect fixed
messages. Exit codes, options and subcommands are the same in both languages.

### Misprint protection and `config.json`

`%APPDATA%\Tapesmith\config.json` (all keys optional):

| Key | Default | Effect |
|---|---|---|
| `guard.confirm_label_mm` | 150 | longer label -> confirmation |
| `guard.confirm_copies` | 5 | more copies -> confirmation |
| `guard.max_label_mm` | 500 | hard limit per label |
| `guard.max_request_mm` | 2000 | hard limit of tape per job |
| `guard.max_copies` | 50 | hard limit of copies |
| `connect_timeout_s` | 5 | used by the CLI: hard timeout when opening the port (printer switched off -> exit 5 after about 5 s) |
| `idle_timeout_s` | 300 | used by the print service (web interface, tray): the connection is closed after this many seconds of idle time (0 = right after printing); the CLI disconnects after every command |
| `gui.ctrl_enter_only` | false | quick print in the web interface: only Ctrl+Enter prints, Enter = new line |

Without a terminal (script, pipe) nothing is printed when a confirmation is needed (exit 1); pass `--yes` then.
Chains are split into jobs of at most 200 mm content.

## Quick print and status bar

The user interface is a web interface that runs in the default browser (`p12 app`, see
“Web interface” below); the former Qt main window no longer exists. The rules for quick print are
unchanged. `p12 gui` still works and redirects to `p12 app` with a note. Self-test without printer
(never prints, writes no user data, needs no Qt): `p12 gui --selftest` (`--selftest-out file.txt`
writes the result to a file; the last line is “Selbsttest ok” in every language, exit 0).

The status bar shows the connection (“P12 · connected” and so on, never only as a color), progress,
“Cancel” and messages in plain text: warnings (e.g. lid open) as a note without blocking the print;
errors (e.g. “Printer unreachable”) with a hint on what to do. The only dialog while printing is the
confirmation of the misprint protection (overlength, many copies).

Quick print keys:
- **Enter** prints exactly 1 label, but only if the preview matches the current text.
- **Ctrl+Enter** and “Print” print with the chosen number of copies or as a chain.
- **Shift+Enter** inserts a new line.
- **Paste** never prints; text pasted with several lines is checked first (press Enter twice).
- Setting “Only print with Ctrl+Enter” (`gui.ctrl_enter_only`): Enter = new line.

Preview “Design/Print image”: “Print image” shows exactly the dots that are sent; leader, trailer
and tape usage are marked as “about”/estimated. The Python core always renders preview and print
image (WYSIWYG), the web interface only shows the finished images.

Cancel: “Cancel” in the progress bar or Esc; the rest of the label is filled with white and fed out.
Connection: the print service keeps the connection and disconnects after `idle_timeout_s` seconds of
idle time. History: search, “Print again”, export (PNG/PDF/PBM).

## Editor and content

**Editor** (page 2, Ctrl+2): place objects freely: text, QR, barcode (Code128), DataMatrix, icon, line,
arrow, frame, warning bar, image. Add them from the palette or, when the canvas has the focus, with a
letter: T text, Q QR, B barcode, D DataMatrix, I icon, L line, A arrow, R frame, W warning bar,
M image. More keys: arrow keys move (grid), Del deletes, Ctrl+Z/Ctrl+Y (or Ctrl+Shift+Z)
undo/redo, Ctrl+D duplicate, Ctrl+R/Ctrl+Shift+R rotate, Ctrl+M mirror, Ctrl+A select all, Esc clear
the selection, Ctrl+P print, Ctrl+S save. Layers, properties, history (jump to a step),
align/distribute, grid and snapping (`gui.editor_grid_dots`, `gui.editor_snap`). Errors (e.g. a code
does not fit) are marked on the object; only a label without errors is printed. Documents can be
saved/opened and stored as a template.

**Codes:** Code128 (module 2 or 3 dots, optionally with plain text) and DataMatrix (square, module
size automatic). Every code is read back by a self-test before printing (zxing-cpp).

**Icons:** Tabler Icons (MIT license, `icons/LICENSE-tabler.txt`) and a selection of Simple Icons
(CC0, `icons/simple/LICENSE-simple-icons.txt`). The Simple Icons logos are trademarks of their owners
(`icons/simple/MARKEN.txt`); CC0 applies only to the graphics files, not to the trademark rights. Your
own icons (PNG) are stored in `%APPDATA%\Tapesmith\icons`.

**Images:** import with threshold, dithering (Floyd-Steinberg/Bayer), inversion; the image is
embedded (the document stays a single file).

**Templates v2 and gallery:** templates can contain a complete object document or a generator
(cable flag, cable wrap, grid), plus category, sample values and target product. The **gallery**
(page 3, Ctrl+3) shows all templates with a preview, search, favorites (“Pin”, `gui.favorites`) as
well as “Edit in editor” and “Series/import…”; “Use” jumps to the templates page. Your own template
folder: `templates_dir`. Check all templates with sample and maximum data: `p12 template lint`. Grid
templates (patch panel, switch, fuse box, assortment): the button **“Export assignment…”** on the
templates page writes the assignment as a table. **Font size:** grid templates set all fields in one
uniform size by default (the largest in which every field fits) with at least 1 mm padding to the
divider lines. Every template with automatically fitted text has the field `schriftgroesse`: `auto`,
`auto-feld` (grid only, every field separately) or a text height in mm (`--set schriftgroesse=3.5`).
If a fixed size does not fit, it is reduced with a warning, never cut off. In the template format the
optional key `text_height` sets the default (`false` hides the field).

**Translating templates:** a template can carry a block `translations` with one object per language
(currently `en`). When the template is loaded in that language, the block replaces the display name
(`title`), description, category, keywords (`tags`), sample values (`sample`), the lines of the short
form (`lines`, same number as `layout.lines`), the texts of document objects (`texts`, per object ID)
and per field (`fields.<id>`) the label (`label`), default value (`default`), choices (`choices`, same
number), lookup table (`map`) and choice labels (`choice_labels`). The ID (`name`) stays the same in
all languages (history, CLI, favorites). `choice_labels` also exists without a translation: it shows a
readable text for choice values that are identifiers (e.g. `haengt`); the value itself is what is
printed and stored. A lookup table also finds the values of the other languages (reprint from the
history). Example:

```json
"translations": {
  "en": {
    "title": "freezer",
    "description": "Frozen food with shelf life ...",
    "category": "Household",
    "fields": {"kategorie": {"label": "Category", "choices": ["Meat", "Fish"]},
               "tage": {"map": {"Meat": "180", "Fish": "120"}}},
    "texts": {"text1": "{inhalt}\nFrozen {eingefroren}"},
    "sample": {"inhalt": "Goulash", "kategorie": "Meat"}
  }
}
```

Older app versions do not know the key and reject such templates. `p12 template lint` checks every
language of the block with sample and maximum data and reports gaps (description, category, keywords,
field labels, choice labels) as warnings. All built in templates are fully translated; so are the tape
profiles (`tapes.json`) and target objects (`targets.json`) via `translations.<language>.name` (and
`note`).

**Series/import:** `p12 batch TEMPLATE --data list.csv|.xlsx` (columns are mapped to fields, `--map`,
`--save-mapping`), `--lines -`, `--clipboard`, `--series port=1..24`, `--contact-sheet overview.png`,
`--dry-run`. In the web interface: “Series/import…” on the templates page or in the gallery.

**Tape:** `p12 tape list`, `p12 tape set weiss-schwarz`, `p12 tape roll` (remaining tape estimate),
`p12 tape new-roll`, `p12 tape empty` (the roll was empty → learn the length factor); in the web
interface under Settings. Rolls and factor apply **per tape**; every print (web interface, tray and
CLI) subtracts the content plus leader/trailer from the roll of the selected tape and warns if it is
not enough. The preview on all pages shows the tape and ink color. On dark tape (white/gold on black)
QR, Code128 and DataMatrix are printed **inverted** (the modules stay unprinted, the quiet zone is
printed) so that scanners can read them. This also applies to quick print (optional field “QR”) and
the QR assistant.

**Cut pause:** between the print jobs of a job (copies/series without a chain: after every label)
printing pauses (`cut_pause_s`: not set = no pause, `0` = until “Continue”, `> 0` = automatically after
that many seconds; CLI `--cut-pause SEC`). The web interface shows a bar “Cut label 1/3, then
‘Continue’” at the top; **Space** or “Continue” resumes (Space only works during the pause).

**Calibration:** feed under Settings (“Print ruler (100 mm)”, enter the measured length, “Apply”) or
`p12 calibrate ruler`. Screen (“Calibrate screen…”, `gui.screen_px_per_mm`) makes the editor show real
millimeters at 100 %.

New `config.json` keys:

| Key | Default | Effect |
|---|---|---|
| `tape.current` | `schwarz-weiss` | loaded tape (preview color, inversion of codes, suitability check) |
| `templates_dir` | not set | your own template folder instead of `%APPDATA%\Tapesmith\templates` |
| `cut_pause_s` | not set | cut pause: none / `0` until “Continue” / seconds |
| `gui.screen_px_per_mm` | not set | screen calibration for the editor |
| `gui.favorites` | `[]` | favorites of the gallery |
| `gui.editor_grid_dots` | 8 | grid spacing in the editor (dots) |
| `gui.editor_snap` | true | snap to the grid/to objects |

The self-test (`p12 gui --selftest`) also checks document, codes, icons, inverted codes on dark tape and template lint.

## Service and Windows

All print paths (web interface, CLI, tray, hotkey, context menu/URI) go through a shared background
service when possible. On top of that come the queue, a tray app with a global hotkey, clipboard
printing, Windows integration, a command palette, the drive and SSH disk scanner, the status display,
experimental transports (BLE/USB/block mode), an extended history (archive, statistics, inventory),
backup/number ranges and developer tools (raw commands, density test strips).

### Print service p12d

`p12d` starts when needed (from the web interface, the CLI or the tray app) and keeps running in the
**user context** (no Windows service, no admin rights needed). There is at most one instance per user
**and** app folder (that is, per `TAPESMITH_HOME`).

```
p12 daemon start                # starts the service (if it is not running yet)
p12 daemon status                # PID, version, connection, queue
p12 daemon stop                  # stops the service (--force also during a print job)
p12 daemon restart
```

The service also contains the HTTP API of the web interface (see “Web interface”).
Log: `%APPDATA%\Tapesmith\logs\p12d.log`. If no service can be reached or started, the CLI or the tray
app prints **directly** (same pipeline); force this with `--no-daemon` or the environment variable
`TAPESMITH_NO_DAEMON=1`. Diagnostics/setup (`doctor`, `probe`, `verify`, `setup`, `raw`, `density`)
briefly reserve the printer at the running service (lease) instead of blocking it. The connection uses
a named pipe that **only your own Windows user** can open (no network service, no access from outside).
Requests from the CLI carry its language, so messages of the service come back in the language of the
CLI.

The legacy command `phomemo_print_p12` (compatibility with phomemo-p12-tools) still prints directly to
the COM port. If the service is running, it may report “busy” (exit 7); then use `p12 daemon stop` or
the same print via `p12 print`/`p12 text`.

### Queue

`p12 queue list|cancel|dup|move|retry|pause|resume` and the **Queue** page show and control the jobs of
the service. If the printer cannot be reached when sending, the service queues the job (state
`wartet`, waiting) and retries automatically with a backoff (30 s → 5 min), faster if a passive BLE
advertisement probe (`queue.probe`) detects the switched on printer earlier. Turn this off with
`queue.auto_retry=false` or `queue.probe=off`. Sensitive jobs (e.g. Wi-Fi password) are **never**
written to disk, only kept in memory; they are lost when the service stops (shown as such). By default
the web interface/tray/hotkey queue offline jobs automatically; the CLI only with `--queue` (changeable
with `queue.cli_default`). If the lid is **verified** open, the automatic queue pauses until it is
closed again.

### Tray app and hotkeys

`p12 tray` (or `pythonw -m tapesmith.gui.tray` in the installed app) starts the tray app in the notification
area. **The tray app never opens a window of its own**, no dialog, no popup and no message box. Only
the icon and its context menu are native; everything that needs an interface opens a new tab in the
default browser (with a fresh session each time). Notes and errors come as Windows notifications of the
tray icon.

| Trigger | Effect |
|---|---|
| Left click on the icon, “Open web interface” | web interface (start page) in the browser |
| **Ctrl+Alt+L** (`hotkey.quick`), “Quick print” | `/schnelldruck` in the browser |
| **Ctrl+Alt+Shift+L** (`hotkey.clipboard`), “Clipboard to quick print” | `/schnelldruck?text=…` prefilled with the text of the clipboard (at most 500 characters, URL encoded); printing only happens in the browser |
| “History” | `/verlauf` |
| “Printer status” | Settings, section Connection |
| “Log and diagnostics” | Settings, section Help and diagnostics |
| “Settings” | Settings, section Tray and hotkeys |
| Update note at the top of the menu | Settings, section Updates |
| Favorite with missing input | `/aktion?uri=tapesmith://print?…` |

These work directly without an interface: print favorites, reprint recent labels, test label,
pause/resume the queue, “Start with Windows” and Quit.

**All settings of the tray app are in the web interface** under Settings, section “Tray and hotkeys”
(hotkeys on/off, both hotkeys, notifications, favorites); autostart is switched in “Windows
integration” (or with the check mark in the tray menu). The tray app checks the configuration file
every 2 s and applies changes without a restart. When saving, the web interface checks the hotkeys like
the former tray dialog did: a valid key, two different hotkeys and **no AltGr collision**. On a German
keyboard Ctrl+Alt is practically AltGr, which is why e.g. `Ctrl+Alt+Q` (produces “@” with AltGr) is
rejected.

The tray app registers the hotkeys without a window (`RegisterHotKey` with hwnd NULL, the message
arrives as a thread message in the Qt message loop).

Favorites in the tray menu (`tray.favorites`), each entry with title, template and fixed values:

```json
"tray": {"favorites": [{"title": "Opened on", "template": "geoeffnet-am", "values": {}}]}
```

**Test mode without a browser:** if `TAPESMITH_BROWSER_LOG=<file>` is set, the tray app (or `p12 app`)
starts neither the print service nor the browser but only appends the route (without token) to this
file. This way a built tray can be checked without a tab opening.

### Clipboard

Ctrl+Alt+Shift+L (or “Clipboard to quick print” in the tray menu) opens quick print in the browser
prefilled with the text of the clipboard; it never prints directly. The detection of clipboard kinds
(`tapesmith.clipboard`) is still used by the self-test and the web interface:

| Kind in the clipboard | Suggestion |
|---|---|
| serial number / `by-id` name | template `datentraeger` |
| IPv4 address | template `ip-label` |
| MAC address | monospace, normalized (`AA:BB:CC:DD:EE:FF`) |
| URL | QR code + host name (long URL: note about short links) |
| one line | text |
| two lines | two lines, font size 44 |
| three lines or more | question “one label per line?” with a tape balance |
| image | rasterized |

### Context menu and URI

```
p12 integrate install|uninstall|status [--context] [--uri] [--autostart] [--dry-run]
```

Writes only below `HKCU` (no admin rights) and is idempotent. **You run this command yourself**, no
script and no automation does. `p12 integrate install --context --uri` creates right-click entries for
the file types from `integration.FILE_ACTIONS` (`.csv`/`.xlsx` as a series, images, `.txt` line by line,
`*.tapesmith.json` as a template, folders “Name as label”/“QR with UNC path”) and the URI scheme
`tapesmith://…`. The entries are written in the current language. Example link (e.g. from Obsidian):

```
tapesmith://print?template=datentraeger&host=pmx10&sn=274913
```

Such a link opens the web interface in the default browser **prefilled**; printing only happens after
the user confirms, never automatically. On Windows 11 the new context menu entries are often under
“Show more options” (Shift+F10). After switching from the Qt interface, run the command once more so
that the entries open the web interface instead of the old Qt interface.

### Command palette and hotkeys

**Ctrl+K** opens the command palette (fuzzy search over templates, recent actions, tape profiles,
e.g. “ssd” for the disk template, “again” for “print last again”, “tape” for a tape profile). More
hotkeys: **Ctrl+P** print, **Ctrl+D** duplicate (in the editor), **Ctrl+Shift+V** open the clipboard as
series data, **Ctrl+1…8** switch between the pages of the core app, **Ctrl+,** settings.

### Drive assistant

Page **Disks** (module Disks, tab “Drives”) or `p12 drives [label E:]` on the command line: detects
connected removable drives (USB stick, SD card) and suggests a short label, e.g.
“Name · 64 GB · exFAT”.

### Status display

Status chip, window title and tray tooltip show **only verified** values without an addition; others
with the addition “(unconfirmed)”, missing ones as “not available”. The **tape** is never shown as “ok”
in the chip (the P12 does not detect an empty roll reliably). The detail panel also shows firmware,
serial number, MAC, transport and the **last response** as hex. The status is only queried while the
interface is visible (interval `status.poll_s`) or when you click the chip.

### Experimental: block mode, BLE, USB

`block_rows` in `calibration.json` turns on block transfer (0 = off, default; otherwise ≤ 255 lines
per block). BLE transport: `p12 ble scan` searches for devices, `--transport ble[:address]` connects
without Windows pairing (never at the same time as the classic SPP connection). USB: `p12 usb` detects
the P12 via VID 0x4C4A/PID 0x4155; USB printing is only possible if `"experimental": ["usb"]` is set in
`calibration.json`. All three count as **experimental** and are not yet fully verified on the hardware
(see `docs/hardware/README.md`).

### SSH disk scanner

Example configuration (only an example, no preset):

```json
"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root", "key": "%USERPROFILE%\\.ssh\\id_ed25519_homelab"}]}
```

`p12 disks hosts|scan|print` reads the disks of a configured homelab host via SSH and prints them as a
series with the template `datentraeger`; in the web interface the **Disks** page (tab “SSH”) does this.
It needs the Windows feature “OpenSSH Client”; on the first connection the host key must be confirmed
once (`ssh.strict_host_key`). The SSH key is stored in the configuration **only as a path**, never its
content.

### History, archive, statistics, inventory

- **Archive:** `archive.dir` stores print jobs as JSON+PNG in a (Git) folder; sensitive fields are
  masked and archived without an image. `archive.git_commit=true` commits automatically afterwards,
  it **never** pushes. `p12 archive add last|<ID>` archives afterwards, `p12 archive scan <path>`
  checks a file or folder for secrets.
- **Statistics:** `p12 stats --by monat|vorlage|quelle|art|rolle` (month, template, source, kind, roll)
  shows the tape usage grouped.
- **Inventory:** `p12 inv box add|list|show|rm`, `p12 inv add|rm|mv|find|lend|return|loans`,
  `p12 inv label box|content|loan` and the “Inventory” page manage boxes with contents and a lending
  list including QR labels.

### Backup, configuration as code, number ranges

`p12 backup create|restore|list` backs up configuration, calibration, counters, rolls, history,
inventory and queue as a zip; `backup.auto_daily=true` lets the service back up automatically every
day. `p12 config export|import <folder>` stores the configuration as a readable folder suitable for
Git. Central number ranges: `numbering.dir` points to a shared folder (e.g. a share or Git repo):
**all** print paths with template counters (CLI, web interface, tray, series, SSH series, inventory)
then count there, so that a second PC does not assign duplicate numbers. Manage them with
`p12 nummern list|define|reserve|void|export|import`.

### Developer tools

`p12 raw` sends single raw commands (hex) and decodes the response. A **block list** checks every
command first: known queries (`1F 11 xx`) are allowed, **ESC 7 is blocked** (heating parameters, can
overheat the print head), everything unknown only with `--unsafe` **and** an explicit input of “JA” or
“YES”. `p12 raw --listen 10` then listens for unsolicited messages (e.g. when opening/closing the lid).
`p12 density` prints experimental density test strips; since no density command is known for the P12,
the command warns first that the printer prints darker after a print from **Print Master** until the
next restart (“Print Master effect”). The chosen value is only stored in the tape profile, never sent
automatically. Guide for a Bluetooth capture (the safest way to a real density command):
`docs/hardware/hci-snoop.md`.

### New settings

New keys in `%APPDATA%\Tapesmith\config.json` (query/change also via `p12 config get|set <key>`):

| Key | Default | Effect |
|---|---|---|
| `daemon.enabled` | `true` | web interface/CLI/tray use the print service |
| `daemon.spawn` | `true` | start the service when needed |
| `daemon.connect_timeout_s` | `2.0` | wait for the pipe |
| `daemon.start_timeout_s` | `10.0` | wait after starting |
| `daemon.idle_exit_s` | `1800` | the service stops after idle time (no pipe client, no open browser tab with the interface, no waiting jobs); 0 = never |
| `queue.enabled` | `true` | queue offline jobs (web interface/tray/hotkey) |
| `queue.auto_retry` | `true` | automatic reprint |
| `queue.backoff_start_s` / `queue.backoff_max_s` | `30` / `300` | backoff |
| `queue.probe` | `"auto"` | `auto` · `ble` · `connect` · `off` |
| `queue.cli_default` | `false` | the CLI queues without `--queue` |
| `status.poll_s` | `120` | status query while the interface is visible (browser tab in the foreground); 0 = only on click |
| `hotkey.enabled` | `true` | global hotkeys of the tray app |
| `hotkey.quick` | `"Ctrl+Alt+L"` | opens `/schnelldruck` in the browser |
| `hotkey.clipboard` | `"Ctrl+Alt+Shift+L"` | opens `/schnelldruck` with the text of the clipboard |
| `tray.favorites` | `[]` | favorites in the tray menu |
| `tray.toast_s` | `3` | no effect (formerly the preview toast), only validated |
| `tray.notify` | `true` | Windows notifications |
| `ble.address` | `null` | fixed BLE address |
| `ble.names` | `["P12","P12 PRO","P12PRO"]` | device names for search/probe |
| `ble.scan_timeout_s` | `8.0` | BLE search |
| `ssh.hosts` | `[]` | SSH hosts (key only as a path) |
| `ssh.timeout_s` | `20` | SSH timeout |
| `ssh.strict_host_key` | `true` | only known host keys |
| `archive.dir` | `null` | archive folder (off = null) |
| `archive.git_commit` | `false` | commit after the secret scan (never push) |
| `backup.dir` | `null` | backup folder (default `<app folder>\backups`) |
| `backup.keep` | `10` | keep this many backups |
| `backup.auto_daily` | `false` | the service backs up daily |
| `numbering.dir` | `null` | central folder for number ranges/counters |

## Modules

Tapesmith consists of the **core app** and **modules**. The core app is always there: quick print,
editor, gallery, templates, QR code, history, queue, statistics, access and settings. Modules are built
in additional areas for special tasks; they are **off** at first.

| Module (`id`) | Purpose | Page | CLI | own templates | Settings |
|---|---|---|---|---|---|
| Inventory (`inventar`) | boxes, contents and lending | Inventory | `inv` | `aufbewahrungsbox` | none |
| Disks (`datentraeger`) | drives of this PC, SSH disk scanner, disk replacement (ZFS) | Disks (tabs Drives, SSH scanner, Replace disk) | `drives`, `disks`, `platte` | `datentraeger`, `datentraeger-qr`, `platte-defekt` | SSH hosts (`ssh.*`) |
| Proxmox (`proxmox`) | VMs and containers from Proxmox VE | Homelab › Proxmox | `proxmox` | `vm-lxc`, `vm-lxc-qr` | `proxmox.*` |
| Paperless (`paperless`) | ASN numbers and warranty labels | Homelab › Paperless | `asn`, `garantie` | `asn`, `garantie`, `garantie-qr` | `paperless.*` |
| Home Assistant (`homeassistant`) | batteries and maintenance | Homelab › Home Assistant | `batterie` | `batterie` | `homeassistant.*` |
| Obsidian vault (`vault`) | labels from notes, note entry after printing | Homelab › Obsidian vault | `vault`, `asset-notiz` | none | `obsidian.*` |
| Assets (`assets`) | asset numbers with QR code and short link | Homelab › Assets | `asset`, `kurz` | `asset-tag`, `asset-kurz` | `assets.*`, `shortlink.*` |
| Cables (`kabel`) | cable IDs according to TIA-606, NetBox import | Homelab › Cables | `kabel` | none | `kabel.*` |
| Classifieds (`kleinanzeigen`) | items for sale with price and QR code | Homelab › Classifieds | `ka` | `ka-artikel` | `kleinanzeigen.*` |
| Serial number scan (`snscan`) | serial number from a photo of the sticker | Homelab › Serial number scan | `sn-scan` | none | none |

**Turning modules on and off:** Settings › Modules (one switch per module with an explanation and an
example) or `tapesmith module list`, `tapesmith module enable <id> [<id> …]`,
`tapesmith module disable <id>`, `tapesmith module enable --all`. The change applies immediately,
without a restart: the service reads `config.json` on every request, the web interface reloads the
sidebar, command palette and gallery. The list is stored in `config.json`:

| Key | Default | Effect |
|---|---|---|
| `modules.enabled` | `[]` | enabled modules (IDs as above); unknown IDs are ignored |

**Modules that are off appear nowhere:** not in the sidebar, the command palette, the gallery and the
template list (their templates are hidden, `tapesmith template list` too), the tray menu (favorites
with module templates), the settings and the homelab overview. The homelab overview only shows enabled
integration modules; if none is on, the Homelab entry disappears from the sidebar. Opening a page of a
module that is off directly shows only a note with the way to the modules. The API routes of a module
that is off answer with **HTTP 409** and the error code `module.disabled` (module in `details.module`),
CLI commands with exit code 1 and the plain text “Module X is turned off, turn it on under Settings >
Modules or with `tapesmith module enable X`”. The hotkeys Ctrl+1 to Ctrl+8 always belong to the pages
of the core app.

**Module settings:** every enabled module with settings has its own card in Settings right below
“Modules” (Disks: SSH hosts from `config.json`; the homelab modules: their sections from
`homelab.json`). Token fields only accept references; “Check” shows without network access whether the
service is entered and the token is found. The former page Homelab › Settings redirects to Settings ›
Modules.

**Switching over and older configurations:** if you switch from “P12 Label”, you keep everything: the
data migration sets `modules.enabled` to the modules for which data or settings exist (inventory
database with entries, `ssh.hosts` or SSH scans, sections in `homelab.json`, asset and classifieds
database, cable register, printed module templates in the history); if a file is not readable, all of
them to be safe. The same applies to a `config.json` without `modules` (e.g. from version 0.3.0): then
the detected modules apply, and the print service writes the list on its next start.

The description of the modules exists once in the code (`src/tapesmith/modules.py`, texts in
`src/tapesmith/locales/<language>/modules.json`); the web interface reads the same description from
`web/src/modules/registry.json` (regenerate with `python -m tapesmith.modules --write-web`) or at
runtime from `GET /api/v1/modules` (`PUT /api/v1/modules/<id>` with `{"enabled": true}` switches it).

## Settings: visible, Advanced, `config.json` only

The Settings page shows at the top what you need every day: printer (status, search and test, test
label), tape and roll, calibration, screen, printing (only Ctrl+Enter prints, cut pause, ask from label
length and copy count), queue (active, automatic reprint), editor (snap, grid spacing in mm), tray and
hotkeys, interface (language, color scheme), modules and their settings cards, updates (check for
updates, install automatically, channel), backup (daily backup, number, back up now), Windows
integration (autostart), access as well as help and diagnostics (with version, uptime, PID and paths of
the print service). Every number field shows its unit in the field.

At the end of the page there is the collapsed section **Advanced** (its state applies per browser; a
link `/einstellungen?abschnitt=<card>` to a card in it opens it): MAC address and transport, limits
for label length, job length and copies, backup folder, templates folder, archive folder and Git
versioning, web port, Bluetooth LE (experimental), context menu and `tapesmith://`, configuration as
code and the plausibility check.

**Only in `config.json`** (no row in the interface, set with `p12 config set`): `connect_timeout_s`
(connection timeout), `idle_timeout_s` (disconnect after idle time), `queue.probe`,
`queue.backoff_start_s`, `queue.backoff_max_s`, `queue.cli_default`, `status.poll_s`,
`gui.screen_px_per_mm` (set by “Calibrate screen”), `gui.editor_grid_dots` (the grid spacing in print
dots, 8 per mm; the interface shows it in mm), `update.source`, `update.check_interval_h`,
`update.idle_min`, `update.keep_versions`, `numbering.dir` and `daemon.idle_exit_s`.

## Web interface

The user interface is a web interface (React, TypeScript, Fluent UI) that runs **only in the default
browser**. There is no window of its own: only the tray icon and its context menu are native (Qt stays
only for that). The quick print popup, the clipboard toast and the tray settings dialog are gone,
browser tabs do their jobs.

```
p12 app                    # start the print service when needed, open the interface in the default browser
p12 app --route /verlauf   # start directly on a page
```

`tapesmith` (without console), `python -m tapesmith.gui`, `p12 gui`, the Start menu shortcut, the tray
menu, the context menu, `tapesmith://` links and the restart after an update open the browser as well;
in the installed app this is `pythonw -m tapesmith.webui.browser`. If the print service does not
start, `p12 app` ends with exit 1 and the message on stderr; without a console (`pythonw`) it goes to
`<app folder>\logs\app.log` (no message window). `--browser` (formerly: browser instead of window) is
still accepted and has no effect anymore, `--compact` no longer exists.

**Architecture:** the print service p12d includes an HTTP API that binds **only** to `127.0.0.1`
(port `web.port`, default 8712). Every API request needs a session token that the service creates anew
on every start and stores in `%APPDATA%\Tapesmith\web\session.json`; `p12 app` appends it to the address
as a fragment (`http://127.0.0.1:8712/…#t=…`, the fragment is never sent to the server). The interface
moves it into the session storage of the tab on start and removes it from the address bar right away.
A browser without a token only shows the note “Please open via ‘p12 app’”. By default the interface
cannot be reached from the network; LAN access, permanent API tokens and `/docs` are described in
“LAN and automation”. The Python core always renders preview and print image, printing uses the same
pipeline as the CLI and the tray (misprint protection, history, remaining tape, cut pause, queue).

Every request of the interface carries its language (header `X-Tapesmith-Language`; images, links and
the event stream use the parameter `lang`), so messages, warnings, status texts and templates of the
service come back in the language of the interface.

**Pages** (on the left in the navigation; the core app with Ctrl+1 to Ctrl+8 in this order, below it the enabled modules):

| Page | Content |
|---|---|
| Quick print (start) | text, Enter prints, copies/chain, recent texts, optional QR |
| Editor | place objects freely, layers, properties, grid, undo |
| Gallery | all templates with a preview, favorites, search |
| Templates | fill in the fields, series/import (CSV, XLSX, clipboard), export the assignment |
| QR code | URL, text, Wi-Fi, business card |
| History | search, print again, export, open in the editor |
| Queue | jobs of the service, pause, retry |
| Statistics | tape usage, rolls |
| Inventory (module) | boxes, contents, lending, labels |
| Disks (module) | drives, SSH disk scanner as a series, disk replacement (ZFS) |
| Homelab (modules) | overview of the enabled homelab modules |
| Settings (Ctrl+,) | printer, tape and roll, calibration, modules, updates, backup, integration; less common items under “Advanced” |
| Access | LAN access, API tokens, family, MCP, hot folder, MQTT, Telegram, status of the additional services |

On top of that there is the standalone phone page `/familie` for family tokens, without navigation.

Hotkeys everywhere: **Ctrl+K** command palette, **Ctrl+P** print the current label, **Ctrl+Shift+V**
clipboard as series data, **Esc** cancel the running print, **Space** resumes a cut pause. In the
editor also the hotkeys from “Editor and content”.

**Appearance:** light/dark and accent color follow Windows; the interface adapts to the size of the
browser window (in narrow windows the navigation collapses).

New `config.json` keys:

| Key | Default | Effect |
|---|---|---|
| `web.port` | `8712` | port (127.0.0.1 only), applies after a restart of the print service; the environment variable `TAPESMITH_WEB_PORT` overrides it. The web interface always runs (an old entry `web.enabled` is ignored). |

**Development:** `cd web && npm ci && npm run dev` starts the Vite development server, `npm run check`
checks types, ESLint and Vitest. `python tools/build_web.py` (with `--install` first `npm ci`) builds
the interface into `src/tapesmith/webui/static/`; this folder is checked in so that runtime and
wheel need no Node.

**After the update:** run `p12 integrate install --context --uri` once so that the context menu and
`tapesmith://` links open the web interface in the browser. An old entry `app.quick_window` in
`config.json` is ignored (the hotkey always opens `/schnelldruck` in the browser).

**Screenshots:** `docs/screenshots/index.md` shows every page in light/dark and desktop/phone width,
also in English (main pages, desktop) and at 200 % zoom, with demo data (file transport, no real
device, no real user data). To take them again (axe-core comes from `web/node_modules`, so run
`npm ci` in the folder `web` once first):

```
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python tools\screenshots.py [--langs de,en] [--sizes desktop,handy,zoom200] [--only verlauf]
```

The tool is a smoke test at the same time: console errors, failed `/api/` calls, axe findings in a
real Chromium (WCAG 2 A, AA and 2.1 AA including color contrast) and horizontal overflow lead to
exit 1. The English pass sets the service language to English (as on an English Windows). Details in
`tools/screenshots.py`.

## Homelab integrations

The homelab tools are modules (see [Modules](#modules)). If at least one is enabled, the sidebar has an
entry **Homelab** (`/homelab`) with an overview: one tile per enabled module with its state from
`GET /api/v1/homelab/check` (“set up”, “token missing”, “not set up” or “no service needed”). Disk
replacement belongs to the Disks module and is a tab there. No integration prints by itself: single
labels go through the normal print path, series through the series dialog of the Templates page
(`/vorlagen?vorlage=<name>&import=<id>`). Every print command knows `--preview FILE.png` (preview only,
no print); series commands also `--dry-run` and `--contact-sheet`. All routes are under
`/api/v1/homelab` and need the session token.

| Function | Page | CLI (examples) |
|---|---|---|
| **Disk replacement:** find failed, missing or OFFLINE devices in the ZFS pool, detect the new disk by comparing with the last scan, `zpool replace` only for copying, labels for old and new. | Disks › Replace disk | `p12 platte status pmx10`, `p12 platte label pmx10 --alt ata-OLD --neu sdc --slot SSD-2 --preview disk.png` |
| **Proxmox:** VMs and LXCs with IP (guest agent or LXC config); if a permission is missing, “IP unknown” is shown. | Proxmox | `p12 proxmox list pmx10`, `p12 proxmox print pmx10 --typ lxc --preview guests.png` |
| **Paperless ASN:** next ASN from Paperless, local reservation (no duplicates), discard misprints. Before printing a series, stick one label on and scan it once. | Paperless | `p12 asn next`, `p12 asn reserve 10 --print --dry-run`, `p12 asn reserve 1 --print --preview asn.png`, `p12 asn void ASN00042 --grund misprint` |
| **Warranty:** search the invoice in Paperless, label `garantie-qr` with a document link and the end of the warranty. | Paperless | `p12 garantie suche --haendler Mindfactory`, `p12 garantie print 17 --preview warranty.png` |
| **Obsidian vault:** read the notes of the allowed folders, frontmatter as values, note entry “Label printed: …” after printing, snippet (Markdown line, PNG attachment, changelog draft). | Obsidian vault | `p12 vault list Hosts`, `p12 vault print Hosts/pmx10 --template host-ip --preview host.png`, `p12 vault snippet --kopieren` |
| **Asset tags and short links:** numbers `HL-0001` exactly once, register with status, QR with a short link; without a short link service the QR contains the long address (warning). Preview, `--dry-run` and the label request of the web page only calculate the short URL (no network, no token); only the real print or the creation sets the link, an existing target is kept. `p12 kurz set` also takes over the target into the asset (`ziel`) or the item (`anzeige`). Optional vault note `Assets/HL-0001`. | Assets | `p12 asset neu --bezeichnung NAS --dry-run`, `p12 asset print HL-0001 --preview asset.png`, `p12 kurz set HL-0001 https://target.example`, `p12 asset-notiz HL-0001` |
| **Plausibility:** check the SN against the last SSH scan, the asset and cable register and the vault, the host name via DNS. Conflicts are warnings, printing only happens after “Print anyway”. Part of the core app (Settings › Advanced › Plausibility check). | in the print dialogs | `p12 plausi datentraeger host=pmx10 sn=S5Y1NX0R123456` |
| **Cables:** NetBox cable export (CSV) with a stored column mapping, IDs according to TIA-606 (`R1.U01:P01`), cable register with duplicate check. | Cables | `p12 kabel netbox cables.csv --dry-run`, `p12 kabel ids --schema R1 --units 1 --ports 1-24 --print --preview cables.png` |
| **Batteries and maintenance:** devices with a battery from Home Assistant, battery type per device, labels `batterie` and `wartung`, optional to-do in HA. | Home Assistant | `p12 batterie list`, `p12 batterie wartung "UPS battery" --intervall 36 --preview maintenance.png` |
| **Scan serial number:** evaluate a photo of the manufacturer sticker, the best SN is preselected. | Serial number scan | `p12 sn-scan sticker.jpg --print --host pmx10 --slot SSD-1 --preview sn.png` |
| **Classifieds:** items `KA-001` with the status available, reserved, sold (values `verfügbar`, `reserviert`, `verkauft`); label with a QR code to the ad and a “reserved” label. | Classifieds | `p12 ka neu "Monitor 27 inch" --preis 80 --preview ka.png`, `p12 ka print KA-001 --reserviert --preview res.png` |

`p12 disks scan|print` and the Disks page additionally store every successful SSH scan in the scan
cache (`<app folder>\homelab\scans\<host>.json`); disk replacement and plausibility read it. If storing
fails, the scan still succeeds (only a log entry).

### Settings file `homelab.json`

A separate file `<app folder>\homelab.json` (not `config.json`), editable in Settings (one card per
enabled module; `plausi.*` under Advanced › Plausibility check) or with
`p12 homelab show|set|check|path`. The file only contains differences from the defaults.

| Key | Default | Effect |
|---|---|---|
| `paperless.url` | `null` | Paperless API, e.g. `http://paperless.example.com:8000` |
| `paperless.public_url` | `null` | address for document links in the QR (otherwise `url`) |
| `paperless.token_ref` | `null` | token reference, e.g. `keyring:tapesmith/paperless` |
| `paperless.asn_range` / `asn_prefix` / `asn_width` | `asn` / `ASN` / `5` | number range and form of the ASN (prefix like `PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX`) |
| `paperless.warranty_fields` | `Kaufdatum`, `Garantie Monate`, `Garantie bis` | names of the custom fields |
| `proxmox.hosts` | `[]` | list `{"name", "url", "token_ref", "verify_tls"}` |
| `obsidian.mcp_url` | `null` | Obsidian MCP (without token, LAN only), e.g. `http://notes.example.com:8092/mcp` |
| `obsidian.vault_dir` | `null` | local vault folder: PNG attachments and fallback for reading (notes, frontmatter) if the MCP is unreachable |
| `obsidian.attachments_dir` | `Anhänge/Labels` | attachment folder in the vault |
| `obsidian.folders` | `["Hosts", "Dienste"]` | allowed folders (plus always `Assets`) |
| `obsidian.append_after_print` | `false` | append the note entry automatically after printing |
| `shortlink.base_url` | `null` | public address of the short link service (without it: long QR contents) |
| `shortlink.admin_url` | `null` | admin API in the LAN (otherwise `base_url`) |
| `shortlink.token_ref` | `null` | admin token (secret reference) |
| `homeassistant.url` | `null` | Home Assistant, e.g. `http://homeassistant.example.com:8123` |
| `homeassistant.token_ref` | `null` | long-lived token (secret reference) |
| `homeassistant.todo_entity` | `null` | e.g. `todo.maintenance` for reminders |
| `homeassistant.battery_below` | `101` | only devices below this charge level (101 = all) |
| `assets.range` / `prefix` / `width` / `check_digit` | `asset` / `HL-` / `4` / `false` | asset numbers |
| `kleinanzeigen.range` / `prefix` / `width` | `ka` / `KA-` / `3` | item numbers |
| `kabel.range` / `prefix` / `width` | `kabel` / `K-` / `3` | free cable IDs |
| `kabel.tia_pattern` | `{rack}.U{unit:02}:P{port:02}` | TIA-606 schema |
| `plausi.networks` | `["192.168.0.0/16"]` | expected networks for IP fields |
| `plausi.dns_check` | `true` | check host names via DNS |
| `*.timeout_s` | `10.0` | timeout per service |

Number ranges (`p12 nummern`): `asn`, `asset`, `ka`, `kabel`. A missing range is created on first use
with the prefix and width from `homelab.json`.

### Tokens

Tokens are never stored in `homelab.json`, only references to them:

- `file:<path>`: first non-empty line of the file. The file belongs in a folder outside of any repo
  that only your own user can read. There are no default paths: you enter every reference yourself.
- `keyring:<service>/<user>`: Windows Credential Manager; store it with
  `p12 homelab secret tapesmith/paperless` (asks hidden, or `--stdin`).
- `env:<NAME>`: environment variable.

If a token is missing, the message is `Token missing: <service> (<reference>)` with a hint on how to
store it (web API: status 424). `p12 homelab check` and the overview show the state without network
access. Unreachable services result in status 503 or exit code 5.

### Services and storage

- **Short link service:** a small redirect service of its own in `deploy/shortlink/` (container, SQLite
  under `/data`, admin API with a bearer token, IDs in capital letters for small QR codes), setup in
  `deploy/shortlink/README.md`.
- **Proxmox:** a read-only role of its own with the guest agent permission via the idempotent script
  `deploy/infra/proxmox-tapesmith-role.sh` (`--dry-run` first); enter the token as a secret reference
  (Credential Manager or file) in `proxmox.hosts[].token_ref`.
- **Data storage:** `<app folder>\homelab\` with `assets.sqlite3`, `kleinanzeigen.sqlite3`,
  `kabel.json`, `batterietypen.json` and `scans\`. `p12 backup` does not back up `homelab.json` and this
  folder yet; back up the folder yourself if needed.

## LAN and automation

The print service p12d can also be used from the home network and by automations: a family print page
for phones, short endpoints, MCP for Claude, a hot folder, a PowerShell module, Home Assistant and
Telegram. Everything runs in the service or talks to it via HTTP; p12d stays the only owner of the
printer connection, and every job goes through the same pipeline (misprint protection, quotas,
history, queue, remaining tape).

Detailed operations documentation: [`deploy/infra/README.md`](../deploy/infra/README.md) (LAN, tokens,
MQTT, Telegram, hot folder, MCP, troubleshooting), [`deploy/homeassistant/README.md`](../deploy/homeassistant/README.md)
and [`deploy/powershell/Tapesmith/README.md`](../deploy/powershell/Tapesmith/README.md).

### Default: local only

Without further steps the service only listens on `127.0.0.1:8712`. Nothing can be reached from the
network. LAN access needs three steps:

1. A firewall rule once **as administrator**: `.\deploy\infra\setup-tapesmith-lan.ps1`
   (idempotent; `-Status` checks without admin rights, `-Remove` undoes it). The app itself never
   creates a firewall rule.
2. `p12 config set lan.enabled true` (or the “Access” page in the interface).
3. `p12 daemon restart`, because the binding (`lan.bind`, default `0.0.0.0`) only applies after a
   restart.

From the LAN only addresses from `lan.allowed_networks` (default `192.168.0.0/16`, ideally restrict it
to your own network) have access. `/health` and the files of the interface work there without a token
(LAN clients only get `ok`, `app`, `version` from `/health`); everything under `/api/` and `/mcp` needs
a token. Foreign host headers (DNS rebinding) and foreign `Origin` values are rejected with 403. After
10 wrong tokens in 10 minutes a LAN address is blocked for 15 minutes (429 with `Retry-After`);
localhost is never blocked.

`lan.public_url` (default `null`) is an optional fixed name instead of the IP, e.g.
`http://p12pc.fritz.box:8712`, if a DNS or router entry exists in the home network. If set, it also
counts as an allowed host (host check, DNS rebinding protection) and appears as the first entry of the
family links (`p12 token add … --rolle familie`, “Access” page) and in the PowerShell examples; without
`lan.public_url` family links use the local LAN addresses instead. Only an `http://`/`https://` URL
without a path, via `p12 config set lan.public_url …` or the “Access” page.

### Tokens and roles

```
p12 token add Phone-Anna --rolle familie     # the plain text appears exactly now, never again
p12 token add Scripts --rolle drucken
p12 token list
p12 token revoke Phone-Anna                  # applies immediately, also in the running service
```

| Role | may |
|---|---|
| `admin` (administration) | everything, including settings, the “Access” page and tokens |
| `drucken` (print) | print, preview, status, queue, templates, gallery, history, series, MCP, family routes |
| `familie` (family) | only the family print page (`/api/v1/familie/...`) |

Tokens are stored only as SHA-256 hashes in `%APPDATA%\Tapesmith\access\tokens.json`. Creating and
revoking also works in the interface on the **Access** page (there also LAN, family, MCP, hot folder,
MQTT and Telegram including the status of the additional services). Send tokens as
`Authorization: Bearer <token>`, as `X-P12-Token` or, for GET only, as `?t=<token>`.

### Family page

`http://<PC-IP>:8712/familie` is a standalone phone page with a family token. For a token with the role
`familie` the CLI and the “Access” page show the finished link `http://<PC-IP>:8712/familie#t=<token>`;
open it on the phone and save it as a bookmark. Only the templates from `family.templates` are offered
(default `gefriergut`, `geoeffnet-am`, `vorratsdose`, `schule`, `eigentum`), with a preview and at most
5 copies per print. In addition the built in special template “Free text” (`family.freetext_enabled`,
on by default): a single multiline text field without a stored template, at most 200 characters. Other
pages and data (history, settings) return nothing with this token. The family page follows the
language of the phone.

### Short endpoints (REST)

A stable short interface under `/api/v1` for the roles `admin` and `drucken`:

| Method path | Purpose |
|---|---|
| `POST /print` | print a template (`{"template", "values", "copies", "confirmed"}`) or a source |
| `POST /print/text` | text label (`{"text": "Line 1\nLine 2"}` or `{"lines": [...]}`) |
| `GET /preview.png` | preview (`?template=…&values=<JSON>` or `?text=…`, `raster=1` for the print image) |
| `GET /jobs`, `DELETE /jobs/{id}` | view the queue, remove a job |
| `GET /docs` | plain HTML overview of all routes with the allowed roles; schema under `/api/v1/openapi.json` |

```powershell
$env:P12_TOKEN = "<token with role drucken>"
curl.exe -H "Authorization: Bearer $env:P12_TOKEN" -H "Content-Type: application/json" `
  -H "Accept-Language: en" `
  -d '{\"template\": \"gefriergut\", \"values\": {\"inhalt\": \"Goulash\"}}' `
  http://<PC-IP>:8712/api/v1/print
curl.exe -H "Authorization: Bearer $env:P12_TOKEN" -o preview.png "http://<PC-IP>:8712/api/v1/preview.png?text=Hello"
```

The result is an `OutcomeJson` with `status` (`ok`, `wartet`, `bestätigung_nötig`, `abgelehnt`, …: stable
values) and `reasons` (texts in the language of the request: `Accept-Language`,
`X-Tapesmith-Language` or `?lang=en`).

### Limits for external access

Jobs with an API token run as source `api`, MCP as `mcp`, plus `mqtt` and `hotfolder`. These sources
cannot confirm questions of the misprint protection: above 5 copies (`guard.confirm_copies`) or above
150 mm label length (`guard.confirm_label_mm`) the service rejects the job (`abgelehnt`, “Source api
cannot confirm”). `confirmed: true` only confirms the tape question there (the template does not suit
the loaded tape). In addition the hourly quotas from `guard.quotas` apply (default `api` and `mcp` 20
jobs or 1000 mm, `mqtt` 10 or 500 mm, `hotfolder` 30 or 1500 mm). Family, MCP, MQTT and hot folder
check the copy limit in advance.

### MCP for Claude

```
p12 mcp --config      # shows the setup for Claude Code, starts nothing
```

`p12 mcp` is a stdio server that talks to the local service via HTTP; the service also offers `/mcp`
(Streamable HTTP, token required, role `admin` or `drucken`, can be turned off with `mcp.http = false`).
Tools: `list_templates`, `label_preview`, `label_print`, `printer_status`, `print_history`,
`queue_list`. Printing only happens with the `preview_id` from `label_preview` and `confirm=true`, at
most 5 copies.

### Hot folder, PowerShell, Home Assistant, Telegram

- **Hot folder:** `p12 config set hotfolder.enabled true`; folder `hotfolder.dir`, default
  `%APPDATA%\Tapesmith\hotfolder`. `*.json` (`{"template", "values", "copies"}`, `vars` as an alias),
  `*.txt`, `*.csv`, `*.png`. Printed files move to `done\`, errors to `error\` with a `.log`.
  `p12 hotfolder status`, `p12 hotfolder run-once`.
- **PowerShell module:** `Import-Module .\deploy\powershell\Tapesmith`, then `Get-P12Status`,
  `Send-P12Label -Template gefriergut -Values @{inhalt='Soup'} -WhatIf`, pipeline from
  `Get-PhysicalDisk` or `Import-Csv`. Talks to the REST API (locally via `session.json`, in the LAN with
  a token).
- **Home Assistant (MQTT):** `p12 secret set mqtt`, `p12 config set mqtt.enabled true`. Device
  “Labeldrucker P12” via discovery (connection, battery, lid, queue, test label button), printing via
  `tapesmith/print/set`. `p12 mqtt discovery`, `p12 mqtt status`.
- **Telegram:** bot token as a secret reference in `telegram.token_ref` (Credential Manager or file),
  `p12 config set telegram.chat_id <ID>`, `p12 config set telegram.enabled true`, `p12 telegram test`.
  Messages about a stuck queue, offline, print errors and low remaining tape, with quiet times. The
  messages are written in the language of the service.

Hot folder, MQTT, Telegram and MCP apply without a restart (the service checks the configuration every
5 s); only `lan.*` needs `p12 daemon restart`. Secrets are never stored in `config.json`, only
references (`keyring:tapesmith/mqtt`, `file:<path>`, `env:<NAME>`); `p12 secret set|check`.

### Deliberate deviations: LAN and automation

- **API tokens:** are not stored in the Credential Manager but only as SHA-256 hashes in
  `%APPDATA%\Tapesmith\access\tokens.json` (the plain text exactly once when created). Reason: several
  tokens with roles and revocation, the service must check them without a user session, a hash cannot
  be reversed. Third-party secrets (MQTT password, Telegram bot token) are still stored in the
  Credential Manager or the token file. `/docs` is a plain HTML overview instead of Swagger UI (no
  scripts from a CDN).
- **MCP:** printing only with the `preview_id` from `label_preview` and `confirm=true`; at most 5
  copies per print (source `mcp`).
- **Hot folder:** default folder `%APPDATA%\Tapesmith\hotfolder` instead of `C:\P12\inbox` (changeable
  via `hotfolder.dir`). The JSON field is called `values`, `vars` counts as an alias. Identical jobs of a
  file are combined into copies (debouncing); at most 5 copies per job.
- **PowerShell:** the module talks REST instead of the named pipe.
- **MQTT:** the print topic is `tapesmith/print/set` (prefix `mqtt.base_topic`, default `tapesmith`)
  instead of `p12/print/set`; `mqtt.base_topic = "p12"` gives the short form. No tape sensor
  (unverified). At most 5 copies per job.
- **Family:** at most 5 copies per print, even if `family.max_copies` is larger.
- **Telegram:** no messages about an empty tape or the battery.
- **Across the board:** non-interactive sources (`api`, `mcp`, `mqtt`, `hotfolder`) cannot confirm
  questions of the misprint protection: above 5 copies or above 150 mm label length the job is
  rejected; `confirmed` only confirms the tape question there.

Checks on the device and in the home network: [`docs/hardware/README.md`](hardware/README.md), section
“LAN und Automatisierung: Prüfungen am Gerät und im Heimnetz” (German).

## Finishing touches

The finishing touches bring the interface to a calm, consistent Fluent 2 level, make it fully usable
with the keyboard and screen readers, add editor tabs with crash recovery, an installation without
admin rights, signed updates and English as a second language. Version: **0.2.0** (first installable
version).

### Language

- English and German are supported. Setting **Settings › Interface › Language** (`app.language`):
  `auto` (default, “same as Windows”), `de` or `en`. With `auto` the **Windows display language** of the
  PC that runs Tapesmith applies everywhere: German on a German Windows, English for every other
  language.
- With `auto` the web interface takes over the language reported by the service (`resolved_language`
  in `GET /api/v1/app`), not the one of the browser. Only if the service reports none, the first browser
  language with German or English applies. The family page `/familie` always follows the language of
  the phone. The change applies immediately, without a restart; `<html lang>` follows, all data is
  reloaded in the new language.
- The tray app (menu, notes, tooltip, status) follows the same setting.
- **Texts of the service** (status values and status details, warnings of the renderers and
  generators, plausibility and misprint protection messages, error messages and hints of the API,
  self-test, support report, Telegram messages, templates, tape and target names) come in the language
  of the request: header `X-Tapesmith-Language` (set by the interface), parameter `lang` (images, links,
  event stream) or `Accept-Language`, otherwise `app.language` or the Windows display language. Error
  messages still carry a stable code (`error.code`, e.g. `printer.busy`).
- **CLI:** output and help texts also follow `app.language` or the Windows display language.
  `TAPESMITH_LANG=de` or `TAPESMITH_LANG=en` forces a language (for scripts that expect fixed messages,
  `TAPESMITH_LANG=de` is recommended). Exit codes (0, 1, 5, 6, 7), option names, subcommands, template
  IDs and status values (e.g. `wartet`, `läuft`) are the same in all languages. Jobs via the print
  service return their messages in the language of the CLI.
- The last line of the self-test stays `Selbsttest ok` (a fixed marker for update and build), the other
  lines are translated.
- Translations: `web/src/locales/<language>/` (interface), `src/tapesmith/locales/<language>/` (tray,
  error codes, modules) and the message catalog `src/tapesmith/locales/messages/en.json` (the German
  text is the key, maintained with `python tools/i18n_messages.py`). Tests check that every text is
  translated and that English responses, templates and CLI help texts contain no German leftovers.

### Appearance and accessibility

- **Color scheme** (`app.theme`): `system` (“same as Windows”, follows the Windows color mode live),
  `hell` (light) or `dunkel` (dark). The tape preview always keeps the real tape color.
- Windows **contrast themes** (e.g. “Desert”, “Night sky”) are detected (`forced-colors`): borders
  instead of shadows, system colors, visible focus.
- **Reduced motion:** if “Animation effects” are off in Windows (`prefers-reduced-motion`), all
  transitions and fade-ins are dropped.
- **Zoom up to 200 %:** browser or window zoom and Windows scaling up to 200 % without horizontal
  scrolling of the page; wide tables scroll in their own frame that can be reached with Tab.
- **Hotkey overview:** `?` or `F1` (outside of input fields) shows all hotkeys of the current page and
  the global ones, with a search.
- **Skip link:** the first Tab on every page shows “Skip to content”, past the sidebar and the header.
- Every page is checked in Vitest with axe-core (German and English, basic, filled and empty state),
  contrasts additionally in a real Chromium via the screenshot tool (light and dark). Dialogs trap the
  focus and return it to the trigger when closing; icon-only buttons have a translated name and
  tooltip; status is never shown only by color.

### Editor tabs and recovery

- The editor opens up to **12 tabs** (one per document). Hotkeys: **Ctrl+Alt+T** new tab, **Ctrl+Alt+W**
  close the tab, **Ctrl+Page Down** / **Ctrl+Page Up** next or previous tab.
- **Autosave:** every tab is saved as a draft in the print service 1.5 s after the last change
  (`%APPDATA%\Tapesmith\drafts\<id>.json`, at most 50 drafts of 2 MB each). Every browser tab reports to
  the service every 30 s (heartbeat).
- **Recovery:** drafts of a tab that was not closed regularly (crash, ended process, service restart)
  are offered on the next start: in the editor as the dialog “Restore drafts?” (Restore, Discard,
  Later), on other pages as a note with “Restore in editor”. Directly: `/editor?wiederherstellen=1`.
- **Question when closing:** if you close or reload the browser tab with unsaved editor tabs, the
  browser asks with its own dialog (`beforeunload`); “Stay” keeps the page open. The drafts are kept
  even after leaving and are offered on the next start.
- The old single draft `documents\_entwurf.p12doc.json` is taken over once on the first start as the
  orphaned draft “Entwurf”.

### Installation without admin rights

Tapesmith is distributed through Python (package `tapesmith` on PyPI) and runs with the signed Python
from python.org. It has no executable of its own, so Windows Smart App Control does not block it,
although Tapesmith itself carries no code signing certificate.

1. Install Python (3.12, 3.11 works too), for example in a normal terminal without admin rights:

   ```
   winget install Python.Python.3.12
   ```

2. Get Tapesmith for the current user and set it up:

   ```
   py -m pip install --user tapesmith
   py -m tapesmith install
   ```

- Folder: `%LOCALAPPDATA%\Programs\Tapesmith\versions\<version>\` is one Python environment (venv) per
  version with exactly this Tapesmith release, `current` is a directory junction to the active
  version, `install.json` holds version, previous version, failed versions and the base Python. The
  environment variable `TAPESMITH_INSTALL_ROOT` or `--root` selects another folder.
- The installation creates the environment with the running Python (`--python` picks another one),
  installs Tapesmith into it with pip (ready made wheels only, `--only-binary=:all:`) and runs the
  self test of the new environment. Only then does it switch over.
- Everything starts as `current\Scripts\pythonw.exe -m …`: Start menu “Tapesmith”
  (`-m tapesmith.webui.browser`), autostart of the tray app (`HKCU\…\Run`, value “Tapesmith”,
  `-m tapesmith.gui.tray`), `tapesmith://`, `p12label://` and the context menu. Entry under
  **Settings › Apps › Installed apps** (HKCU, publisher “Tapesmith contributors”) with uninstall
  (`pythonw -m tapesmith uninstall`).
- **Uninstall** via “Installed apps”, the Start menu shortcut “Tapesmith deinstallieren” or
  `py -m tapesmith uninstall`: the program folder, Start menu and registry entries are removed.
  **User data in `%APPDATA%\Tapesmith` (settings, history, drafts) is kept.** The package used for the
  setup is removed with `py -m pip uninstall tapesmith`.
- Options: `install [--root D] [--python P] [--no-shortcuts] [--no-registry] [--no-autostart]
  [--no-start] [--no-open] [--quiet] [--force]`, for tests without PyPI `--wheel FILE`,
  `--find-links FOLDER`, `--no-index` and `--lock lock.txt`; `uninstall [--root D] [--no-shortcuts]
  [--no-registry] [--quiet]`.
- The result goes to the console and to `<app folder>\logs\install.log` or `uninstall.log`, exit code
  0 ok, 1 error. After a successful installation the tray app and the web interface start in the
  default browser (`--no-open` or `--quiet`: only the tray app, `--no-start`: nothing).
- `py -m tapesmith install --status [--json]` shows root, active version, junction, base Python and
  the kind of installation without changing anything.
- **Smart App Control:** `python.exe` and `pythonw.exe` from python.org are signed, all native parts
  (Qt, Pillow, cryptography, pydantic and others) come unmodified as wheels of their projects from
  PyPI. The small `.exe` launchers that pip creates for command line entry points are not used by the
  installed app; if Smart App Control blocks them, use `py -m tapesmith …` instead of `tapesmith …`.
- **Long paths:** Qt (PySide6) ships very long file names. With a very long user name pip can hit the
  260 character limit (message about “Long Path Support”); then allow long paths in Windows (once,
  with admin rights, `LongPathsEnabled`) or pick a shorter folder with `--root`.
- **Moving from the portable build (up to 0.3) or from a source checkout:** run the two commands of
  step 2. `tapesmith install` stops the old Tapesmith, takes over the installation folder, replaces
  autostart, Start menu and the entry under “Installed apps” and removes the old `Tapesmith.exe`. If
  the autostart points to a Python environment outside the installation (for example
  `C:\src\tapesmith\.venv`), Tapesmith is stopped there and the autostart is switched; the environment
  itself is left alone. User data stays as it is.

### Updates

- **Only with consent:** the automatic check (`update.enabled`) is off until you agree. On the
  first start of the installed app the web interface asks once (“Check for updates automatically?”);
  both answers are saved (`update.asked`), and the switch under Settings › Updates changes it later.
  Without consent Tapesmith does not connect to the update source on its own; “Check now” still works.
- **Sources** (`update.source`): `github:essendyx/tapesmith` (default, GitHub releases via the REST
  API, packages from PyPI), `file:<folder>` (folder or file share with `manifest.json`,
  `manifest.json.sig` and `lock.txt`; if the wheels are there as well, directly or under `wheels\`,
  pip installs only from that folder) or an `https://…/` base address.
- **Without a token:** the repository is public, GitHub is queried without sign-in (at most 60 requests
  per hour and address). An old entry `update.token_ref` in `config.json` is ignored.
- **Channel** `stable` or `beta` (pre-releases such as `0.4.0b1`); check interval `update.check_interval_h`.
- **Process:** load the manifest and check its Ed25519 signature. The manifest holds version, channel
  and a complete lock list (every package with version and the SHA-256 of all wheels for Windows x64
  and the supported Python versions). From it the updater writes `lock.txt`, creates the new
  environment `versions\<v>` with the base Python of the installation and installs with
  `pip install --require-hashes --only-binary=:all: -r lock.txt`, so only files whose checksum is in
  the signed manifest. Then it checks the installed version and runs the self test
  (`pythonw -m tapesmith.selftest`) in the new environment. Switching only happens when **idle**:
  automatically (`update.auto_install`) only if the service has not printed for `update.idle_min`
  minutes and no browser tab with the interface has been open for 120 s; “Install now” in Settings ›
  Updates only requires “no job active, queue empty” and asks first because the service restarts
  briefly. Afterwards the interface opens with the new version in a new browser tab (the old tab loses
  its session and can be closed).
- **Fallback:** if the new service does not report the new version within 60 s, the updater rolls back
  to the previous version automatically and remembers the failed version (it is never offered
  automatically again). If the self test already fails, nothing is switched. `update.keep_versions`
  older versions are kept.
- CLI: `py -m tapesmith update status [--json]`, `… update check`, `… update install [--yes]`,
  `… update rollback [--yes]` (in a development environment also `p12 update …`).
- **Signing keys:** only manifests whose signature matches a key in
  `src/tapesmith/update/trusted_keys.json` are accepted; without a matching key the page reports
  “No trusted signing key” and there are no updates.
- **Publishing a release:** push the tag `v<version>`; the workflow `.github/workflows/release.yml`
  builds wheel and sdist, creates lock list and manifest, signs it, publishes to PyPI and creates the
  GitHub release (details in `deploy/infra/README.md`).

### Report a problem

**Settings › Help and diagnostics › Report a problem** or `p12 report --out FILE.zip` creates a zip with
`bericht.txt` (version, Windows, portable or installed, transport, printer status, queue), the masked
`config.json` and the last 512 KB of every log file. Tokens, passwords and keys are removed (`***`),
secret references stay as references. Nothing is sent: you pass the zip on yourself. The report text is
written in the current language.

### New `config.json` keys

| Key | Default | Effect |
|---|---|---|
| `app.language` | `"auto"` | language of the interface, tray app, service and CLI: `auto` (Windows display language), `de`, `en` |
| `app.theme` | `"system"` | color scheme: `system`, `hell`, `dunkel` |
| `update.enabled` | `false` | check for updates regularly (off until you agree, see Updates) |
| `update.asked` | `false` | the web interface has asked once about the automatic check |
| `update.source` | `"github:essendyx/tapesmith"` | update source: `github:owner/repo`, `file:<folder>` or `https://…` |
| `update.channel` | `"stable"` | `stable` or `beta` |
| `update.check_interval_h` | `24` | check interval in hours (1 to 720) |
| `update.auto_install` | `false` | install automatically when idle |
| `update.idle_min` | `10` | minutes of idle time before the automatic update (1 to 1440) |
| `update.keep_versions` | `2` | older versions that stay in the program folder (1 to 5) |

### Deliberate deviations: interface, installation and update

- No Mica effect (the interface runs in the browser), calm Fluent surfaces instead; the color scheme
  can also be set to light or dark permanently.
- Tabs exist in the editor (labels are created freely there); “Report a problem” sends nothing.
- Installation through Python (`py -m tapesmith install`) instead of Inno Setup or an executable of
  its own; update signature Ed25519 over a manifest with the SHA-256 of all packages instead of
  Authenticode (no code signing certificate); the file association stays with the
  context menu for `*.tapesmith.json`.
- No choice of units (sizes stay in mm and print dots). Option names and subcommands of the CLI,
  template IDs and status values are German identifiers and stay the same in all languages.

## Building and checking the package

Wheel and sdist are built with `python -m build` (in the development venv from `pip install -e ".[dev]"`):

```
.venv\Scripts\python tools\build_web.py
.venv\Scripts\python -m build
```

Result: `dist\tapesmith-<version>-py3-none-any.whl` and `dist\tapesmith-<version>.tar.gz`. The wheel
contains the built web interface (`tapesmith/webui/static`), fonts, templates, icons and the
translation catalogs; settings and history live independently of it in `%APPDATA%\Tapesmith`. A trial
installation without PyPI, registry or Start menu (for example in a throwaway environment under
`%TEMP%`):

```
py -m venv %TEMP%\ts-probe
%TEMP%\ts-probe\Scripts\python -m pip install dist\tapesmith-<version>-py3-none-any.whl
set TAPESMITH_INSTALL_ROOT=%TEMP%\ts-probe-root
set TAPESMITH_HOME=%TEMP%\ts-probe-home
%TEMP%\ts-probe\Scripts\python -m tapesmith install --wheel dist\tapesmith-<version>-py3-none-any.whl --no-registry --no-shortcuts --no-start
```

The built in self test (`python -m tapesmith.selftest --selftest-out selftest.txt`; last line
“Selbsttest ok”) runs on every installation and every update in the new environment. It also checks
the web API (without a port), the built interface, uvicorn and the browser start (address with token,
without a real browser), the translation catalogs (de/en with the same keys, message catalog
readable), the update signature (Ed25519 in memory, `trusted_keys.json` readable) and the installation
layout (create, switch and remove a junction in a temp folder). The app icon
`src/tapesmith/icons/app.ico` is created by `tools/make_app_icon.py` (`--check` verifies it).

Hardware findings: [`docs/hardware/README.md`](hardware/README.md)
