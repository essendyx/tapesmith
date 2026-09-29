# Contributing to Tapesmith

Thanks for your interest! Bug reports, feature ideas and pull requests are welcome.

## Before you start

- For larger changes please open an issue first, so we can agree on the approach.
- Tapesmith targets Windows 10 and 11 with Python 3.11 or newer. The web UI uses React, TypeScript
  and Vite (Node.js 20 or newer).
- User facing texts exist in German and English (`src/tapesmith/locales`, `web/src/locales`).
  Please update both.

## Development setup

```
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
cd web
npm ci
```

## Rules for code and tests

- Write a failing test first, then the code. The whole suite must pass without warnings:
  `.venv\Scripts\python -m pytest -q -W error` and `npm run check` in `web/`.
- Tests never print, never open real COM ports, Bluetooth or network services and never read or
  write the real data folder. The test configuration sets `TAPESMITH_HOME` to a temporary folder;
  keep it that way for manual runs too.
- Hardware tests are marked `@pytest.mark.hardware` and only run with `--hardware`.
- Printer dimensions come from the device profile only; do not hard code dot counts.
- The protocol byte stream (`src/tapesmith/protocol`, `tests/golden`) must not change unless the
  change is intended and explained in the pull request.
- Never commit secrets, tokens, real host names, IP addresses or serial numbers. Use neutral
  examples: `192.0.2.0/24` or `198.51.100.0/24`, `example.com`, `server01`, `Max Mustermann`.
- After changing the web UI, rebuild it with `python tools\build_web.py` and commit
  `src/tapesmith/webui/static`.

## Privacy check

`tests/test_keine_privaten_daten.py` can scan the repository for identifiers that must never be
published. Put one regular expression per line into a private file outside the repository and run:

```
set TAPESMITH_PRIVATE_PATTERNS=C:\path\to\my-patterns.txt
.venv\Scripts\python -m pytest tests\test_keine_privaten_daten.py
```

Without the variable the test is skipped; a generic check for private IPv4 host addresses always runs.

## Pull requests

- Keep pull requests focused, describe what changed and how you tested it.
- By contributing you agree that your contribution is licensed under the MIT License.
