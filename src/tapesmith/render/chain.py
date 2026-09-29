"""Kopien und Kettendruck: Kopfbilder mehrerer Labels zu Jobs planen, mit
gestrichelten Schnittlinien zwischen den Labels desselben Jobs und einer
Bandbilanz (gespartes Band gegenüber Einzeldruck).

Arbeitet ausschließlich auf Kopfbildern (Breite ``profile.head_dots``, Modus
"1", 0 = schwarz), damit Text-, Vorlagen- und Bild-Labels gleich behandelt
werden. Reine Bildlogik, kein Drucker.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.render.compose import mm_to_rows, rows_to_mm
from tapesmith.i18n import _t

MAX_JOB_MM = 200.0  # sichere Maximallänge Inhalt je Job
CUT_GAP_MM = 1.0  # Weißraum vor und nach der Schnittlinie
CUT_LINE_ROWS = 2  # Dicke der Schnittlinie in Zeilen
DASH_DOTS = 6  # Strich
GAP_DOTS = 4  # Lücke

MAX_ROWS_PER_JOB = 65535  # Protokollgrenze


@dataclass(frozen=True)
class ChainJob:
    head: Image.Image  # Kopfbild des Jobs (Breite head_dots)
    label_indices: tuple[int, ...]  # Indizes in der expandierten Labelliste
    length_mm: float  # Inhalt inkl. Schnittzonen (rows_to_mm)
    tape_mm: float  # length_mm + leader_mm + trailer_mm


@dataclass(frozen=True)
class TapeBalance:
    labels: int
    jobs: int
    chain_mm: float  # Summe tape_mm aller Jobs dieses Plans
    single_mm: float  # Summe (Label + leader + trailer) je Label einzeln

    @property
    def saved_mm(self) -> float:
        return self.single_mm - self.chain_mm

    def text(self) -> str:
        if self.labels == 1:
            return _t("1 Label: {chain_mm:.0f} mm Band", chain_mm=self.chain_mm)
        if self.saved_mm > 1e-6:
            return (_t("{labels} Labels: {chain_mm:.0f} mm statt {single_mm:.0f} mm ({saved_mm:.0f} mm gespart)", labels=self.labels, chain_mm=self.chain_mm, single_mm=self.single_mm, saved_mm=self.saved_mm))
        return _t("{labels} Labels: {chain_mm:.0f} mm Band ({jobs} Jobs)", labels=self.labels, chain_mm=self.chain_mm, jobs=self.jobs)


@dataclass(frozen=True)
class ChainPlan:
    jobs: tuple[ChainJob, ...]
    balance: TapeBalance
    chained: bool
    warnings: tuple[str, ...]


def expand_copies(heads: Sequence[Image.Image], copies: int) -> list[Image.Image]:
    if copies < 1:
        raise ValueError(_t("Kopien müssen ≥ 1 sein"))
    result: list[Image.Image] = []
    for head in heads:
        result.extend([head] * copies)
    return result


def cut_mark(profile: DeviceProfile) -> Image.Image:
    gap_rows = mm_to_rows(CUT_GAP_MM, profile)
    height = 2 * gap_rows + CUT_LINE_ROWS
    img = Image.new("1", (profile.head_dots, height), 255)
    period = DASH_DOTS + GAP_DOTS
    for y in range(gap_rows, gap_rows + CUT_LINE_ROWS):
        for x in range(profile.content_offset, profile.content_offset + profile.content_dots):
            if (x - profile.content_offset) % period < DASH_DOTS:
                img.putpixel((x, y), 0)
    return img


def _blank_separator(profile: DeviceProfile) -> Image.Image:
    gap_rows = mm_to_rows(CUT_GAP_MM, profile)
    height = 2 * gap_rows + CUT_LINE_ROWS
    return Image.new("1", (profile.head_dots, height), 255)


def _stack(pieces: Sequence[Image.Image], head_dots: int) -> Image.Image:
    total_height = sum(piece.height for piece in pieces)
    img = Image.new("1", (head_dots, total_height), 255)
    y = 0
    for piece in pieces:
        img.paste(piece.convert("1"), (0, y))
        y += piece.height
    return img


def _check_width(heads: Sequence[Image.Image], profile: DeviceProfile) -> None:
    if not heads:
        raise ValueError(_t("Keine Labels zum Drucken"))
    for i, head in enumerate(heads):
        if head.width != profile.head_dots:
            raise ValueError(
                _t("Label {value} ist {width} Punkte breit statt {head_dots}", value=i + 1, width=head.width, head_dots=profile.head_dots))


def _check_row_limit(height: int, job_no: int) -> None:
    if height > MAX_ROWS_PER_JOB:
        raise ValueError(
            _t("Job {job_no} ist {height} Zeilen lang (> {max_rows_per_job} Zeilen erlaubt)", job_no=job_no, height=height, max_rows_per_job=MAX_ROWS_PER_JOB))


def _make_job(pieces: Sequence[Image.Image], indices: tuple[int, ...],
              profile: DeviceProfile, job_no: int) -> ChainJob:
    head = _stack(pieces, profile.head_dots)
    _check_row_limit(head.height, job_no)
    length_mm = rows_to_mm(head.height, profile)
    tape_mm = length_mm + profile.leader_mm + profile.trailer_mm
    return ChainJob(head=head, label_indices=indices, length_mm=length_mm, tape_mm=tape_mm)


def _single_mm(heads: Sequence[Image.Image], profile: DeviceProfile) -> float:
    return sum(rows_to_mm(head.height, profile) + profile.leader_mm + profile.trailer_mm
               for head in heads)


def plan_single(heads: Sequence[Image.Image], profile: DeviceProfile) -> ChainPlan:
    _check_width(heads, profile)
    jobs = tuple(_make_job([head], (i,), profile, job_no=i + 1)
                 for i, head in enumerate(heads))
    single_mm = _single_mm(heads, profile)
    chain_mm = sum(job.tape_mm for job in jobs)
    balance = TapeBalance(labels=len(heads), jobs=len(jobs), chain_mm=chain_mm, single_mm=single_mm)
    return ChainPlan(jobs=jobs, balance=balance, chained=False, warnings=())


def plan_chain(heads: Sequence[Image.Image], profile: DeviceProfile, *,
               max_job_mm: float = MAX_JOB_MM, cut_marks: bool = True) -> ChainPlan:
    _check_width(heads, profile)
    separator = cut_mark(profile) if cut_marks else _blank_separator(profile)

    jobs: list[ChainJob] = []
    warnings: list[str] = []

    current_pieces: list[Image.Image] = []
    current_indices: list[int] = []
    current_rows = 0

    def flush():
        if current_pieces:
            jobs.append(_make_job(list(current_pieces), tuple(current_indices), profile,
                                   job_no=len(jobs) + 1))

    for i, head in enumerate(heads):
        label_rows = head.height
        label_mm = rows_to_mm(label_rows, profile)
        if label_mm > max_job_mm:
            flush()
            current_pieces = []
            current_indices = []
            current_rows = 0
            jobs.append(_make_job([head], (i,), profile, job_no=len(jobs) + 1))
            warnings.append(
                _t("Label {value} ist {label_mm:.0f} mm lang (> {max_job_mm:.0f} mm), wird einzeln gedruckt", value=i + 1, label_mm=label_mm, max_job_mm=max_job_mm))
            continue

        if current_pieces:
            new_rows = current_rows + separator.height + label_rows
        else:
            new_rows = label_rows

        if current_pieces and rows_to_mm(new_rows, profile) > max_job_mm:
            flush()
            current_pieces = [head]
            current_indices = [i]
            current_rows = label_rows
        else:
            if current_pieces:
                current_pieces.append(separator)
            current_pieces.append(head)
            current_indices.append(i)
            current_rows = new_rows

    flush()

    if len(jobs) > 1:
        warnings.append(
            _t("Kette auf {count} Jobs aufgeteilt (max. {max_job_mm:.0f} mm je Job)", count=len(jobs), max_job_mm=max_job_mm))

    single_mm = _single_mm(heads, profile)
    chain_mm = sum(job.tape_mm for job in jobs)
    balance = TapeBalance(labels=len(heads), jobs=len(jobs), chain_mm=chain_mm, single_mm=single_mm)
    chained = len(heads) > 1
    return ChainPlan(jobs=tuple(jobs), balance=balance, chained=chained, warnings=tuple(warnings))


def chain_preview(plan: ChainPlan, profile: DeviceProfile, scale: int = 2) -> Image.Image:
    lead = mm_to_rows(profile.leader_mm, profile)
    trail = mm_to_rows(profile.trailer_mm, profile)
    boundary = 4

    contents = [job.head.rotate(90, expand=True) for job in plan.jobs]
    total_width = sum(lead + content.width + trail for content in contents)
    total_width += boundary * max(len(plan.jobs) - 1, 0)

    canvas = Image.new("L", (total_width, profile.head_dots), 255)
    x = 0
    for i, content in enumerate(contents):
        if i > 0:
            canvas.paste(80, (x, 0, x + boundary, profile.head_dots))
            x += boundary
        canvas.paste(200, (x, 0, x + lead, profile.head_dots))
        x += lead
        canvas.paste(content.convert("L"), (x, 0))
        x += content.width
        canvas.paste(200, (x, 0, x + trail, profile.head_dots))
        x += trail

    return canvas.resize((canvas.width * scale, canvas.height * scale), Image.NEAREST)
