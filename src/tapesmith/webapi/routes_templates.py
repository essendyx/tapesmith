"""Routen /api/v1 (Bereich templates, gallery, batch).

Routenreihenfolge: feste Pfade vor Pfaden mit `{name}`, sonst behandelt Starlette
z. B. "lint" als Vorlagennamen. Reihenfolge in dieser Datei: Liste, feste Pfade, dann
Parameterpfade (siehe Kommentare je Abschnitt).
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import re
import tempfile
import zipfile
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from tapesmith import config as config_mod
from tapesmith import i18n, modules, paths
from tapesmith.dataimport import batch as dataimport_batch
from tapesmith.dataimport.mapping import ColumnMapping, MappingStore
from tapesmith.document.generators import get_generator, raster_export
from tapesmith.document.model import DocumentError, document_from_dict
from tapesmith.document.model import texts as document_texts
from tapesmith.errors import EXIT_TEMPLATE
from tapesmith.fileutil import atomic_write_text
from tapesmith.gui.preview_model import design_image, plan_for_preview
from tapesmith.tape.profiles import TapeProfile, find_tape
from tapesmith.tape.suitability import suitability_reason
from tapesmith.templates import gallery as gallery_mod
from tapesmith.templates import store
from tapesmith.templates.fill import form_fields, input_fields, resolve_values
from tapesmith.templates.lint import lint_templates
from tapesmith.templates.model import (PLACEHOLDER, SCHEMA_VERSION, Field, Template, TemplateError,
                                      template_from_dict, template_to_dict)
from tapesmith.templates.render import render_template
from tapesmith.webapi import access, batchapi
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.webapi.printing import options_from_json, submit_labels
from tapesmith.i18n import N_, _t

router = APIRouter()

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DEFAULT_CATEGORY = N_("Eigene")
_THUMB_CACHE_MAX = 300


# ================================================================ Hilfsfunktionen


def _find_or_404(name: str) -> Template:
    # Nur reine Vorlagennamen zulassen: store.find_template lädt sonst jede Datei, auf die ein
    # (absoluter/relativer) Pfad zeigt, auch außerhalb von user_dir()/builtin_dir().
    if not _NAME_RE.match(name):
        raise NotFound(_t("Vorlage '{name}' nicht gefunden", name=name))
    try:
        return store.find_template(name)
    except TemplateError as exc:
        raise NotFound(str(exc)) from exc


def _is_builtin(t: Template) -> bool:
    if t.path is None:
        return True
    try:
        return t.path.resolve().is_relative_to(store.builtin_dir().resolve())
    except OSError:
        return False


def _default_hint(f: Field, t: Template | None) -> str | None:
    """Standardwert eines leeren Felds als Platzhalter: bei Generator-Vorlagen der gleichnamige
    Generator-Parameter (z. B. raster_mm), sofern das Feld selbst keinen Standard hat."""
    if t is None or f.default or t.generator is None or f.type != "input":
        return None
    params = dict(getattr(get_generator(t.generator.name), "PARAMS", {}))
    params.update(t.generator.params)
    value = params.get(f.id)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value:g}"


def _field_json(f: Field, t: Template | None = None) -> dict:
    size_field = t.text_size_field if t is not None else None
    return {
        "id": f.id, "label": f.label, "type": f.type, "default": f.default,
        "required": f.required, "secret": f.secret, "choices": list(f.choices),
        "choice_labels": dict(f.choice_labels),
        "max_len": f.max_len, "multiline": f.multiline,
        "role": "text_size" if size_field is not None and f is size_field else None,
        "default_hint": _default_hint(f, t),
    }


def template_summary_json(t: Template, favs: set[str]) -> dict:
    """`TemplateSummary` einer Vorlage (öffentlich für Fassade, Familie, MCP)."""
    return {
        "name": t.name, "title": t.display_title, "description": t.description,
        "category": t.category or _t("Allgemein"),
        "tags": list(t.tags), "kind": t.kind, "builtin": _is_builtin(t),
        "favorite": t.name in favs, "target": t.target, "tapes": list(t.tapes),
        "default_copies": t.default_copies,
        "input_fields": [_field_json(f, t) for f in input_fields(t)],
        "sample": gallery_mod.sample_values(t),
    }


_summary_json = template_summary_json


def _detail_json(t: Template, favs: set[str], tape: TapeProfile | None) -> dict:
    data = _summary_json(t, favs)
    data["fields"] = [_field_json(f, t) for f in form_fields(t)]
    data["path"] = str(t.path) if t.path is not None else None
    data["definition"] = template_to_dict(t)
    data["tape_reason"] = suitability_reason(t.name, tape, t.tapes) if tape is not None else None
    return data


def _image_bytes(image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _calib_mtime() -> float:
    try:
        return paths.calibration_path().stat().st_mtime
    except OSError:
        return 0.0


def _template_mtime(t: Template) -> float:
    if t.path is None:
        return 0.0
    try:
        return t.path.stat().st_mtime
    except OSError:
        return 0.0


# ================================================================ Anfragekörper


class SaveTemplateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    description: str = ""
    category: str = ""
    tags: list[str] = []
    document: dict | None = None
    definition: dict | None = None
    overwrite: bool = False


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    package_b64: str
    overwrite: bool = False


class ExportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    names: list[str]


class ParseFileBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    data_b64: str


class AssignmentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    values: dict[str, str] = {}


class FavoriteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    favorite: bool


class BatchTableBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: dict


class BatchRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str
    source: dict
    mapping: dict[str, str] | None = None
    selected: list[int] | None = None
    fixed: dict[str, str] = {}
    chain: bool = False
    cut_marks: bool = True


class BatchPrintBody(BatchRequestBody):
    options: dict | None = None


# ================================================================ Vorlagen: Liste


@router.get("/templates")
def list_templates(ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    favs = set(gallery_mod.favorites(cfg))
    return {"templates": [_summary_json(t, favs) for t in _visible_templates(cfg)]}


def _visible_templates(cfg: dict) -> list:
    """Alle Vorlagen ohne die Vorlagen ausgeschalteter Module."""
    hidden = modules.hidden_templates(cfg)
    return [t for t in store.list_templates() if t.name not in hidden]


# ---------------------------------------------------------------- feste Pfade


@router.post("/templates")
def create_template(body: SaveTemplateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if not _NAME_RE.match(body.name):
        raise TemplateError(
            _t("Vorlagenname '{name}' ungültig (a-z, A-Z, 0-9, Punkt, Unterstrich, Bindestrich)", name=body.name))
    if body.document is None and body.definition is None:
        raise TemplateError(_t("Entweder document oder definition angeben"))
    if body.document is not None and body.definition is not None:
        raise TemplateError(_t("document und definition schließen sich aus"))

    if body.definition is not None:
        data = dict(body.definition)
        data["name"] = body.name
        if body.description:
            data["description"] = body.description
        if body.category:
            data["category"] = body.category
        if body.tags:
            data["tags"] = list(body.tags)
    else:
        try:
            doc = document_from_dict(body.document)
        except DocumentError as exc:
            raise TemplateError(str(exc)) from exc
        fields: list[Field] = []
        known: set[str] = set()
        for text in document_texts(doc):
            for placeholder, _filters in PLACEHOLDER.findall(text):
                if placeholder not in known:
                    fields.append(Field(id=placeholder, label=placeholder.capitalize(), type="input"))
                    known.add(placeholder)
        new_template = Template(
            name=body.name, description=body.description, fields=tuple(fields), layout={},
            schema_version=SCHEMA_VERSION, document=doc, category=body.category or _t(_DEFAULT_CATEGORY),
            tags=tuple(body.tags),
        )
        data = template_to_dict(new_template)

    target = store.user_dir() / f"{body.name}{store.SUFFIX}"
    template = template_from_dict(data, path=target)  # wirft TemplateError bei Ungültigem
    if target.exists() and not body.overwrite:
        raise TemplateError(_t("Vorlage '{name}' gibt es schon", name=body.name))
    atomic_write_text(target, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    favs = set(gallery_mod.favorites(ctx.config()))
    return _detail_json(template, favs, ctx.tape())


@router.get("/templates/lint")
def lint(ctx: ApiContext = Depends(get_ctx)) -> dict:
    issues = lint_templates(store.list_templates(), ctx.profile(), now=ctx.now())
    return {"issues": [{"template": i.template, "level": i.level, "message": i.message} for i in issues]}


@router.post("/templates/import")
def import_templates(body: ImportBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        raw = base64.b64decode(body.package_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(_t("Paket nicht lesbar: {exc}", exc=exc)) from exc
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "import.zip"
        path.write_bytes(raw)
        try:
            imported = gallery_mod.import_package(path, store.user_dir(), overwrite=body.overwrite)
        except zipfile.BadZipFile as exc:
            raise ValueError(_t("Paket ist kein gültiges Zip: {exc}", exc=exc)) from exc
    return {"imported": imported}


@router.post("/templates/export")
def export_templates(body: ExportBody, ctx: ApiContext = Depends(get_ctx)) -> Response:
    templates = [_find_or_404(name) for name in body.names]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.zip"
        gallery_mod.export_package(templates, path)
        data = path.read_bytes()
    filename = f"vorlagen-{ctx.now().strftime('%Y%m%d')}.zip"
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/templates/parse-file")
def parse_file(body: ParseFileBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        raw = base64.b64decode(body.data_b64, validate=True)
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TemplateError(_t("Vorlagendatei nicht lesbar: {exc}", exc=exc)) from exc
    template = template_from_dict(data, path=None)
    return {"definition": template_to_dict(template), "name": template.name}


# ---------------------------------------------------------------- Parameterpfade


@router.get("/templates/{name}")
def get_template(name: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    template = _find_or_404(name)
    favs = set(gallery_mod.favorites(ctx.config()))
    return _detail_json(template, favs, ctx.tape())


@router.delete("/templates/{name}")
def delete_template(name: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if not _NAME_RE.match(name):
        raise TemplateError(
            _t("Vorlagenname '{name}' ungültig (a-z, A-Z, 0-9, Punkt, Unterstrich, Bindestrich)", name=name))
    files = [store.user_dir() / f"{name}{suffix}" for suffix in store.SUFFIXES]
    found = [f for f in files if f.is_file()]
    if found:
        for file in found:
            file.unlink()
        return {}
    _find_or_404(name)  # wirft 404, wenn unbekannt
    raise TemplateError(_t("Mitgelieferte Vorlagen können nicht gelöscht werden"))


@router.post("/templates/{name}/assignment")
def export_assignment(name: str, body: AssignmentBody | None = None,
                      ctx: ApiContext = Depends(get_ctx)) -> Response:
    template = _find_or_404(name)
    if template.generator is None or template.generator.name != "raster":
        raise TemplateError(_t("Vorlage hat keine Belegung"))
    values = dict(body.values) if body is not None else {}
    resolved = resolve_values(template, values, ctx.now(), ctx.counters())
    tr = render_template(template, resolved.values, ctx.profile(), tape=ctx.tape())
    if tr.generator is None:
        raise TemplateError(_t("Vorlage hat keine Belegung"))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}-belegung.csv"
        raster_export.export_assignment(tr.generator, path)
        data = path.read_bytes()
    return Response(content=data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}-belegung.csv"'})


# ================================================================ Galerie: feste Pfade zuerst


@router.get("/gallery")
def gallery(query: str = "", category: str = "", ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    hidden = modules.hidden_templates(cfg)
    templates = _visible_templates(cfg)
    if query:
        templates = gallery_mod.search_templates(templates, query)
    if category:
        templates = [t for t in templates if (t.category or _t("Allgemein")) == category]
    groups = gallery_mod.group_by_category(templates)
    favs = set(gallery_mod.favorites(cfg))
    categories = [{"name": name, "templates": [_summary_json(t, favs) for t in items]}
                 for name, items in groups.items()]
    return {
        "categories": categories,
        "favorites": [name for name in gallery_mod.favorites(cfg) if name not in hidden],
        "recent": [name for name in gallery_mod.recent_template_names(ctx.history()) if name not in hidden],
        "templates_dir": str(store.user_dir()),
    }


@router.get("/gallery/thumb/{name}.png")
def gallery_thumb(name: str, tape: str | None = None, ctx: ApiContext = Depends(get_ctx)) -> Response:
    template = _find_or_404(name)
    tape_profile = find_tape(tape) if tape else ctx.tape()
    cache: OrderedDict = ctx.extras.setdefault("templates.thumbs", OrderedDict())
    key = (name, tape_profile.id, _template_mtime(template), _calib_mtime(), i18n.language())
    cached = cache.get(key)
    if cached is not None:
        cache.move_to_end(key)
        return Response(content=cached, media_type="image/png")
    try:
        values = gallery_mod.sample_values(template)
        resolved = resolve_values(template, values, ctx.now(), ctx.counters())
        tr = render_template(template, resolved.values, ctx.profile(), tape=tape_profile)
        plan_data = plan_for_preview([tr.result.head], ctx.profile())
        image = design_image(plan_data, ctx.profile(), tape_profile)
    except (TemplateError, ValueError) as exc:
        raise NotFound(str(exc)) from exc
    data = _image_bytes(image)
    cache[key] = data
    if len(cache) > _THUMB_CACHE_MAX:
        cache.popitem(last=False)
    return Response(content=data, media_type="image/png")


@router.post("/gallery/favorites/{name}")
def set_favorite(name: str, body: FavoriteBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    current = gallery_mod.favorites(cfg)
    if body.favorite != (name in current):
        current = gallery_mod.toggle_favorite(cfg, name, config_mod.save_config)
        ctx.publish("config", {"keys": ["gui.favorites"]})
    return {"favorites": list(current)}


# ================================================================ Serien/Import


@router.post("/batch/table")
def batch_table(body: BatchTableBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    table = batchapi.load_source(ctx, body.source)
    if table is None:
        raise ValueError(_t("Diese Quelle enthält keine Tabelle"))
    return {"headers": list(table.headers), "rows": [list(r) for r in table.rows], "source_name": table.source}


@router.post("/batch/plan")
def batch_plan(body: BatchRequestBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    template = _find_or_404(body.template)
    rows, mapping, headers = batchapi.build_rows(ctx, template, body.source, body.mapping, body.selected,
                                                 body.fixed)
    plan_result = batchapi.plan(ctx, template, rows)
    return batchapi.plan_json(ctx, plan_result, mapping, headers, chain=body.chain, cut_marks=body.cut_marks)


@router.post("/batch/print")
def batch_print(body: BatchPrintBody, request: Request, ctx: ApiContext = Depends(get_ctx)):
    template = _find_or_404(body.template)
    rows, mapping, headers = batchapi.build_rows(ctx, template, body.source, body.mapping, body.selected,
                                                 body.fixed)
    plan_result = batchapi.plan(ctx, template, rows)
    if plan_result.errors:
        error = error_json("TemplateError", _t("{count} Zeile(n) fehlerhaft", count=len(plan_result.errors)),
                           exit_code=EXIT_TEMPLATE, details={"errors": list(plan_result.errors)})
        return JSONResponse(error, status_code=422)
    if headers:
        MappingStore().save(template.name, headers, ColumnMapping(columns=mapping))
    opts = options_from_json(body.options)
    meta = dataimport_batch.batch_meta(plan_result, access.job_origin(request))
    counters = ctx.counters()
    result = submit_labels(ctx, plan_result.labels, meta, opts,
                           on_done=lambda _outcome: dataimport_batch.commit_counters(plan_result, counters))
    return result


@router.post("/batch/contact-sheet")
def batch_contact_sheet(body: BatchRequestBody, ctx: ApiContext = Depends(get_ctx)) -> Response:
    template = _find_or_404(body.template)
    rows, _mapping, _headers = batchapi.build_rows(ctx, template, body.source, body.mapping, body.selected,
                                                    body.fixed)
    plan_result = batchapi.plan(ctx, template, rows)
    image = dataimport_batch.contact_sheet(plan_result, ctx.profile(), tape=ctx.tape())
    return Response(content=_image_bytes(image), media_type="image/png")
