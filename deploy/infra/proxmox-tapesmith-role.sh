#!/usr/bin/env bash
# Legt auf einem Proxmox-Host die Read-only-Rolle, den Benutzer und das API-Token für tapesmith an.
#
# Aufruf auf dem Proxmox-Host als root:
#   bash proxmox-tapesmith-role.sh [--dry-run] [--user tapesmith@pve] [--token label] [--role TapesmithAudit]
#
# Jeder Schritt ist idempotent: vorhandene Rolle, Benutzer, ACL und Token bleiben erhalten, die
# Rechte der Rolle werden nur geändert, wenn sie abweichen. Mit --dry-run werden nur die Befehle
# angezeigt, nichts wird verändert. Das Secret eines neuen Tokens wird nie in eine Datei geschrieben,
# sondern einmalig ausgegeben.

set -euo pipefail

DRY_RUN=0
PVE_USER="tapesmith@pve"
TOKEN_NAME="label"
ROLE="TapesmithAudit"

usage() {
  echo "Aufruf: $0 [--dry-run] [--user USER@REALM] [--token NAME] [--role ROLLE]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --user) PVE_USER="${2:?--user braucht einen Wert}"; shift 2 ;;
    --token) TOKEN_NAME="${2:?--token braucht einen Wert}"; shift 2 ;;
    --role) ROLE="${2:?--role braucht einen Wert}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Ändernden Befehl ausführen bzw. bei --dry-run nur anzeigen.
change() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] $*"
  else
    echo "+ $*"
    "$@"
  fi
}

# JSON-Auswertung mit python3 (auf Proxmox vorhanden), ohne jq.
# json_has FELD WERT: gibt "ja" aus, wenn die Liste auf stdin einen Eintrag mit FELD == WERT enthält.
json_has() {
  python3 -c '
import json, sys
field, value = sys.argv[1], sys.argv[2]
try:
    data = json.load(sys.stdin)
except ValueError:
    data = []
found = any(isinstance(e, dict) and str(e.get(field)) == value for e in (data or []))
sys.stdout.write("ja" if found else "nein")
' "$1" "$2"
}

# role_privs_state ROLLE RECHTE: "fehlt", "gleich" oder "abweichend" (Rechte der Rolle aus stdin).
role_privs_state() {
  python3 -c '
import json, sys
role, wanted = sys.argv[1], set(p for p in sys.argv[2].split(",") if p)
try:
    data = json.load(sys.stdin)
except ValueError:
    data = []
for entry in data or []:
    if isinstance(entry, dict) and entry.get("roleid") == role:
        privs = entry.get("privs") or ""
        if isinstance(privs, str):
            have = set(p.strip() for p in privs.split(",") if p.strip())
        elif isinstance(privs, dict):
            have = set(k for k, v in privs.items() if v)
        else:
            have = set(privs)
        sys.stdout.write("gleich" if have == wanted else "abweichend")
        break
else:
    sys.stdout.write("fehlt")
' "$1" "$2"
}

# token_value: Secret aus der JSON-Ausgabe von "pveum user token add".
token_value() {
  python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    data = {}
sys.stdout.write(str(data.get("value", "")) if isinstance(data, dict) else "")
'
}

# 1. Voraussetzungen und Hauptversion
if ! command -v pveum >/dev/null 2>&1; then
  echo "pveum nicht gefunden: Skript auf dem Proxmox-Host ausführen" >&2
  exit 1
fi
if ! command -v pveversion >/dev/null 2>&1; then
  echo "pveversion nicht gefunden: Skript auf dem Proxmox-Host ausführen" >&2
  exit 1
fi
VERSION_LINE="$(pveversion | head -n 1)"
MAJOR="$(printf '%s\n' "$VERSION_LINE" | sed -n 's#.*pve-manager/\([0-9][0-9]*\)\..*#\1#p' | head -n 1)"
if [ -z "$MAJOR" ]; then
  echo "Proxmox-Version nicht erkannt: $VERSION_LINE" >&2
  exit 1
fi
echo "Proxmox VE $MAJOR erkannt ($VERSION_LINE)"

# 2. Rolle mit Leserechten (PVE 9: VM.GuestAgent.Audit, PVE 8: VM.Monitor für den Guest-Agent)
PRIVS="VM.Audit,Sys.Audit,Datastore.Audit,SDN.Audit,Pool.Audit,Mapping.Audit"
if [ "$MAJOR" -ge 9 ]; then
  PRIVS="$PRIVS,VM.GuestAgent.Audit"
else
  PRIVS="$PRIVS,VM.Monitor"
fi
ROLE_STATE="$(pveum role list --output-format json | role_privs_state "$ROLE" "$PRIVS")"
case "$ROLE_STATE" in
  fehlt) change pveum role add "$ROLE" -privs "$PRIVS" ;;
  abweichend) change pveum role modify "$ROLE" -privs "$PRIVS" ;;
  *) echo "Rolle $ROLE vorhanden, Rechte stimmen" ;;
esac

# 3. Benutzer
USER_EXISTS="$(pveum user list --output-format json | json_has userid "$PVE_USER")"
if [ "$USER_EXISTS" = "ja" ]; then
  echo "Benutzer $PVE_USER vorhanden"
else
  change pveum user add "$PVE_USER" --comment "tapesmith Read-only"
fi

# 4. ACL auf / (pveum acl modify ist idempotent)
change pveum acl modify / --users "$PVE_USER" --roles "$ROLE"

# 5. Token (Secret nur einmal sichtbar, wird nicht gespeichert)
TOKEN_EXISTS="nein"
if [ "$USER_EXISTS" = "ja" ]; then
  TOKEN_EXISTS="$(pveum user token list "$PVE_USER" --output-format json | json_has tokenid "$TOKEN_NAME")"
fi
if [ "$TOKEN_EXISTS" = "ja" ]; then
  echo "Token existiert, Secret nicht erneut abrufbar; bei Verlust mit pveum user token remove $PVE_USER $TOKEN_NAME neu anlegen"
elif [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] pveum user token add $PVE_USER $TOKEN_NAME --privsep 0 --comment tapesmith"
else
  echo "+ pveum user token add $PVE_USER $TOKEN_NAME --privsep 0 --comment tapesmith"
  SECRET="$(pveum user token add "$PVE_USER" "$TOKEN_NAME" --privsep 0 --comment "tapesmith" --output-format json | token_value)"
  if [ -z "$SECRET" ]; then
    echo "Token angelegt, Secret nicht erkannt: Ausgabe von pveum prüfen" >&2
    exit 1
  fi
  echo
  echo "Token angelegt. Das Secret wird nur jetzt angezeigt und nirgends gespeichert."
  echo "Auf dem Windows-PC als Datei C:\\Tokens\\.proxmox_tapesmith_token ablegen, Inhalt (eine Zeile):"
  echo "${PVE_USER}!${TOKEN_NAME}=${SECRET}"
  echo
fi

# 6. Ergebnis anzeigen
if [ "$DRY_RUN" -eq 1 ] && [ "$USER_EXISTS" != "ja" ]; then
  echo "[dry-run] pveum user permissions $PVE_USER --path /"
else
  pveum user permissions "$PVE_USER" --path /
fi
echo "Fertig."
