"""DataMatrix. Encoder ppf-datamatrix (rein Python, quadratisch), Selbsttest per zxing-cpp,
sofern der Decoder geladen werden kann (sonst Warnung, render.zxing)."""

from PIL import Image
from ppf.datamatrix import DataMatrix

from tapesmith.render.codes import CodeResult, self_test_code
from tapesmith.render.zxing import NOT_READ_WARNING
from tapesmith.i18n import _t

QUIET_MODULES = 1
MIN_MODULE_DOTS = 2
WARN_MODULE_DOTS = 3


def datamatrix_matrix(data: str) -> list[list[bool]]:
    matrix = DataMatrix(data).matrix
    return [[bool(v) for v in row] for row in matrix]


def render_datamatrix(data: str, max_dots: int, module: int | None = None) -> CodeResult:
    if not data:
        raise ValueError(_t("DataMatrix ohne Inhalt"))
    matrix = datamatrix_matrix(data)
    n = len(matrix)
    if module is None:
        module = max_dots // n
    elif module * n > max_dots:
        raise ValueError(_t("DataMatrix passt nicht: braucht {value} Punkte, verfügbar {max_dots}", value=module * n, max_dots=max_dots))

    if module < MIN_MODULE_DOTS:
        raise ValueError(
            _t("DataMatrix passt nicht lesbar auf das Band ({n} Module, Modul {module} Punkte), kürzer fassen", n=n, module=module)
        )

    warnings: list[str] = []
    if module < WARN_MODULE_DOTS:
        warnings.append(_t("DataMatrix-Modul nur {module} Punkte (< {warn_module_dots}), eventuell nicht scanbar", module=module, warn_module_dots=WARN_MODULE_DOTS))

    size = n * module
    image = Image.new("1", (size, size), 255)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                image.paste(0, (x * module, y * module, (x + 1) * module, (y + 1) * module))

    quiet = max(QUIET_MODULES * module, 2)
    verified = self_test_code(image, data, "DataMatrix", quiet)
    if verified is False:
        raise ValueError(_t("DataMatrix nicht lesbar (Selbsttest)"))
    if verified is None:
        warnings.append(_t(NOT_READ_WARNING))

    return CodeResult(image, "datamatrix", module, quiet, bool(verified), tuple(warnings))
