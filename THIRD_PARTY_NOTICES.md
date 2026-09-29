# Third party notices

Tapesmith itself is licensed under the MIT License (see `LICENSE`). It bundles or builds on the
following third party works. Full license texts of bundled assets are included next to the assets.

## Bundled assets

| Component | Where | License |
|---|---|---|
| Tabler Icons, Copyright (c) 2020-2025 Paweł Kuna | `src/tapesmith/icons/tabler-icons.ttf`, `tabler-index.json` | MIT, see `src/tapesmith/icons/LICENSE-tabler.txt` |
| Simple Icons | `src/tapesmith/icons/simple/*.png` | CC0 1.0, see `src/tapesmith/icons/simple/LICENSE-simple-icons.txt`. The logos remain trademarks of their owners and are only used to label your own devices and services, see `MARKEN.txt`. |
| DejaVu fonts (DejaVu Sans, DejaVu Sans Bold, DejaVu Sans Mono), Bitstream Vera Copyright (c) 2003 Bitstream, Inc., Arev glyphs Copyright (c) 2006 Tavmjong Bah, DejaVu changes in the public domain | `src/tapesmith/fonts/*.ttf` | Bitstream Vera / Arev font license, see `src/tapesmith/fonts/LICENSE` |

## Protocol reference

| Component | Use | License |
|---|---|---|
| [phomemo-p12-tools](https://github.com/soburi/phomemo-p12) 0.0.5, Copyright (c) 2022 Timo "polskafan" Dobbrick | Documentation of the P12 print protocol; optional test dependency (`golden` extra) that produces the reference byte stream in `tests/golden/`. The command names `phomemo_render_label` and `phomemo_print_p12` are kept for compatibility. | MIT |

MIT License text for phomemo-p12-tools:

```
Copyright (c) 2022 Timo 'polskafan' Dobbrick

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Python dependencies (from `pyproject.toml`)

Installed separately (not vendored). The portable build bundles the runtime dependencies.

| Package | License |
|---|---|
| Pillow | MIT-CMU (HPND) |
| pyserial | BSD-3-Clause |
| segno | BSD-3-Clause |
| zxing-cpp | Apache-2.0 |
| PySide6 (Qt for Python) | LGPL-3.0 (or GPL-2.0/GPL-3.0) |
| ppf-datamatrix | MIT |
| openpyxl | MIT |
| bleak | MIT |
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| mcp (Model Context Protocol SDK) | MIT |
| paho-mqtt | EPL-2.0 or EDL-1.0 (BSD-3-Clause) |
| keyring | MIT |
| httpx | BSD-3-Clause |
| cryptography | Apache-2.0 or BSD-3-Clause |
| pytest, pytest-qt (development) | MIT |
| PyInstaller (build only) | GPL-2.0-or-later with bootloader exception |
| Playwright (screenshots only) | Apache-2.0 |

PySide6 is used under the LGPL: the portable build ships the unmodified Qt libraries as separate
files, which can be replaced by the user.

## Web UI dependencies (from `web/package.json`)

Bundled into `src/tapesmith/webui/static`:

| Package | License |
|---|---|
| @fluentui/react-components, @fluentui/react-icons | MIT |
| @tanstack/react-query | MIT |
| i18next, react-i18next | MIT |
| konva, react-konva | MIT |
| react, react-dom | MIT |
| react-router-dom | MIT |

Development and build tools (not bundled): TypeScript (Apache-2.0), Vite, Vitest, ESLint,
typescript-eslint, Testing Library, jsdom, globals (MIT), axe-core (MPL-2.0).
