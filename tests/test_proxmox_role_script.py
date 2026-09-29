"""Skript deploy/infra/proxmox-tapesmith-role.sh, statisch und mit Attrappen (nie echter Host)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "infra" / "proxmox-tapesmith-role.sh"
BASE_PRIVS = "VM.Audit,Sys.Audit,Datastore.Audit,SDN.Audit,Pool.Audit,Mapping.Audit"
MUTATING = ("role add", "role modify", "user add", "acl modify", "token add")

FAKE_PVEUM = r"""#!/usr/bin/env bash
echo "$*" >> "$PVEUM_LOG"
case "$1 $2 $3" in
  "user token list") printf '%s' "${FAKE_TOKENS:-[]}" ;;
  "user token add") printf '%s' '{"full-tokenid":"tapesmith@pve!label","value":"00000000-fake-secret"}' ;;
  "role list "*) printf '%s' "${FAKE_ROLES:-[]}" ;;
  "user list "*) printf '%s' "${FAKE_USERS:-[]}" ;;
  "user permissions "*) echo "/ VM.Audit (*)" ;;
esac
exit 0
"""

FAKE_PVEVERSION = """#!/usr/bin/env bash
echo "pve-manager/${FAKE_PVE:-9.0.3}/abcdef (running kernel: 6.14.8-2-pve)"
"""


def _bash() -> str:
    bash = shutil.which("bash")
    if bash and "system32" in bash.lower():
        bash = None  # WSL-Starter, nicht Git Bash
    if not bash:
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if git_bash.is_file() else None
    if not bash:
        pytest.skip("bash nicht gefunden")
    return bash


def test_static_content():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    for needle in ("VM.GuestAgent.Audit", "VM.Monitor", "--privsep 0", "python3 -c", ".proxmox_tapesmith_token"):
        assert needle in text
    assert "\u2013" not in text and "\u2014" not in text
    assert "\r\n" not in text
    assert " jq " not in text


@pytest.fixture
def run_script(tmp_path):
    bash = _bash()
    fakes = tmp_path / "bin"
    fakes.mkdir()
    (fakes / "pveum").write_text(FAKE_PVEUM, encoding="utf-8", newline="\n")
    (fakes / "pveversion").write_text(FAKE_PVEVERSION, encoding="utf-8", newline="\n")
    python = Path(sys.executable).as_posix()
    (fakes / "python3").write_text(f'#!/usr/bin/env bash\nexec "{python}" "$@"\n', encoding="utf-8", newline="\n")
    for name in ("pveum", "pveversion", "python3"):
        (fakes / name).chmod(0o755)
    log = tmp_path / "pveum.log"

    def run(*args, pve="9.0.3", roles=None, users=None, tokens=None):
        if log.exists():
            log.unlink()
        env = dict(os.environ)
        env.update({"PATH": str(fakes) + os.pathsep + env.get("PATH", ""), "PVEUM_LOG": log.as_posix(),
                    "FAKE_PVE": pve, "FAKE_ROLES": json.dumps(roles or []),
                    "FAKE_USERS": json.dumps(users or []), "FAKE_TOKENS": json.dumps(tokens or [])})
        proc = subprocess.run([bash, SCRIPT.as_posix(), *args], env=env, capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return proc, calls

    return run


def _has(calls, needle):
    return any(needle in c for c in calls)


def test_first_run_creates_everything(run_script):
    proc, calls = run_script()
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert _has(calls, "role add TapesmithAudit")
    role_add = next(c for c in calls if "role add" in c)
    assert f"{BASE_PRIVS},VM.GuestAgent.Audit" in role_add
    assert "VM.Monitor" not in role_add
    assert _has(calls, "user add tapesmith@pve")
    assert _has(calls, "acl modify / --users tapesmith@pve --roles TapesmithAudit")
    token_add = next(c for c in calls if "token add" in c)
    assert "--privsep 0" in token_add
    assert "tapesmith@pve!label=00000000-fake-secret" in proc.stdout
    assert ".proxmox_tapesmith_token" in proc.stdout


def test_second_run_changes_nothing(run_script):
    privs = f"{BASE_PRIVS},VM.GuestAgent.Audit"
    proc, calls = run_script(roles=[{"roleid": "TapesmithAudit", "privs": ",".join(reversed(privs.split(",")))}],
                             users=[{"userid": "tapesmith@pve"}], tokens=[{"tokenid": "label"}])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    for needle in ("role add", "role modify", "user add", "token add"):
        assert not _has(calls, needle), needle
    assert "Token existiert" in proc.stdout
    assert _has(calls, "user permissions tapesmith@pve")


def test_changed_privs_are_modified(run_script):
    proc, calls = run_script(roles=[{"roleid": "TapesmithAudit", "privs": "VM.Audit"}],
                             users=[{"userid": "tapesmith@pve"}], tokens=[{"tokenid": "label"}])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert _has(calls, "role modify TapesmithAudit")
    assert not _has(calls, "role add")


def test_pve8_uses_vm_monitor(run_script):
    proc, calls = run_script(pve="8.4.1")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    role_add = next(c for c in calls if "role add" in c)
    assert "VM.Monitor" in role_add and "VM.GuestAgent.Audit" not in role_add


def test_dry_run_changes_nothing(run_script):
    proc, calls = run_script("--dry-run")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    for needle in MUTATING:
        assert not _has(calls, needle), needle
    assert "[dry-run] pveum role add" in proc.stdout
    assert "[dry-run] pveum user token add" in proc.stdout


def test_custom_names(run_script):
    proc, calls = run_script("--user", "label@pam", "--token", "t1", "--role", "R1")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert _has(calls, "role add R1")
    assert _has(calls, "user token add label@pam t1")


def test_unknown_option(run_script):
    proc, _calls = run_script("--quatsch")
    assert proc.returncode == 2
