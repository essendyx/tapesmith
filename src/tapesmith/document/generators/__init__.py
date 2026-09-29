"""Registry der Generator-Vorlagen (Kabelfahne, Kabelwickel, Raster).

Ein Generator-Modul liefert `PARAMS: dict[str, object]` (Standardwerte) und
`generate(params: dict, values: dict[str, str], profile: DeviceProfile) -> GeneratorOutput`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from types import ModuleType

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.model import LabelDocument
from tapesmith.i18n import _t

GENERATORS = {
    "kabelfahne": "tapesmith.document.generators.kabelfahne",
    "kabelwickel": "tapesmith.document.generators.kabelwickel",
    "raster": "tapesmith.document.generators.raster",
}


@dataclass(frozen=True)
class GeneratorRef:
    name: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratorOutput:
    document: LabelDocument
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)


def get_generator(name: str) -> ModuleType:
    module_name = GENERATORS.get(name)
    if module_name is None:
        raise ValueError(_t("Generator '{name}' nicht verfügbar", name=name))
    try:
        return import_module(module_name)
    except ImportError as exc:
        raise ValueError(_t("Generator '{name}' nicht verfügbar", name=name)) from exc


def run_generator(ref: GeneratorRef, values: dict[str, str], profile: DeviceProfile) -> GeneratorOutput:
    module = get_generator(ref.name)
    params = dict(getattr(module, "PARAMS", {}))
    unknown = set(ref.params) - set(params)
    if unknown:
        raise ValueError(_t("Generator '{name}': unbekannte Parameter {sorted}", name=ref.name, sorted=sorted(unknown)))
    params.update(ref.params)
    return module.generate(params, values, profile)
