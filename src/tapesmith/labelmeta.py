"""Job-Metadaten (`JobMeta`) für Text-, Vorlagen-, QR- und Bild-Labels an einer Stelle.

CLI und GUI bauen `JobMeta` nur über diese Funktionen, damit sensible Werte überall
gleich maskiert werden. Kein Qt, kein argparse, kein `cli_cmds`.
"""

import dataclasses
import json
from collections.abc import Sequence

from tapesmith.jobs import JobMeta, spec_to_dict
from tapesmith.render.compose import LabelSpec
from tapesmith.render.qrcontent import QrContent
from tapesmith.templates.fill import REDACTED, redact, redact_text
from tapesmith.templates.model import Template


def text_meta(spec: LabelSpec, source: str = "cli") -> JobMeta:
    """Job-Metadaten für ein freies Textlabel (`p12 text`)."""
    title = " ".join(line for line in spec.lines if line.strip())
    if not title and spec.qr:
        title = spec.qr
    return JobMeta(source=source, kind="text", title=title, spec=spec_to_dict(spec),
                   values={}, sensitive=False)


def template_meta(template: Template, values: dict[str, str], spec: LabelSpec, *,
                  kind: str = "template", title_prefix: str = "", source: str = "cli") -> JobMeta:
    """Job-Metadaten einer gefüllten Vorlage, ohne Klartext sensibler Werte."""
    sensitive = any(f.secret for f in template.fields)
    parts = [*spec.lines, *([spec.qr] if spec.qr else [])]
    title = redact_text(" ".join(p for p in parts if p), template, values)
    return JobMeta(source=source, kind=kind, template=template.name, title=title_prefix + title,
                   values=redact(template, values), sensitive=sensitive,
                   spec=None if sensitive else spec_to_dict(spec))


# Schlüssel in `values` eines sensiblen WLAN-QR-Eintrags (Nachdruck ohne Vorlage, ohne Klartext)
QR_KIND_KEY = "qr_kind"
QR_SPEC_KEY = "qr_spec"
WIFI_PASSWORD_KEY = "password"


def qr_meta(content: QrContent, lines: Sequence[str] = (), source: str = "cli",
            spec: LabelSpec | None = None, *, kind: str = "qr", title_prefix: str = "") -> JobMeta:
    """Job-Metadaten für ein QR-Label (`p12 qr`, QR-Assistent).

    Ein WLAN-QR mit Passwort speichert weder Bild noch Spec. Damit „Erneut drucken“ trotzdem
    geht, landen SSID, Sicherheitsart, „versteckt“ und das Layout (Spec ohne QR-Inhalt) in
    `values`, das Passwort nur maskiert; beim Nachdruck wird es neu abgefragt."""
    title = title_prefix + " ".join([content.display, *lines])
    values = {"qr": content.display}
    if content.secret and content.kind == "wifi" and spec is not None:
        layout = spec_to_dict(dataclasses.replace(spec, qr=None))
        values |= {QR_KIND_KEY: "wifi", **dict(content.params), WIFI_PASSWORD_KEY: REDACTED,
                   QR_SPEC_KEY: json.dumps(layout, ensure_ascii=False, sort_keys=True)}
    return JobMeta(source=source, kind=kind, title=title, values=values,
                   sensitive=content.secret,
                   spec=None if (content.secret or spec is None) else spec_to_dict(spec))


def image_meta(name: str, source: str = "cli") -> JobMeta:
    """Job-Metadaten für ein vorhandenes Bild (`p12 print --image`)."""
    return JobMeta(source=source, kind="image", title=name)
