"""Vorschau-Modell für das Band in echter Größe, ohne Qt.

Plant *exakt* so, wie `PrintPipeline.plan` plant (`expand_copies`, `plan_single`/`plan_chain`),
damit die Vorschau immer WYSIWYG bleibt: die Ansicht „Druckbild“ zeigt genau die Bits, die
gesendet werden. Vor-/Nachlauf und Bandbilanz werden als „ca.“/„geschätzt“ ausgewiesen, solange
`leader`/`trailer` nicht in `profile.verified` stehen.

Alle Bilder werden ohne Pixel-für-Pixel-Python-Schleifen über die volle Fläche aufgebaut: die
Ink/Band-Färbung läuft über eine Maske (`Image.point`/`Image.paste`), nur die schmalen,
nicht bedruckbaren Randzeilen (wenige Zeilen, siehe `DeviceProfile.content_offset`) werden
zeilenweise nachgezeichnet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.render.chain import ChainJob, ChainPlan, TapeBalance, expand_copies, plan_chain, plan_single
from tapesmith.render.compose import mm_to_rows
from tapesmith.tape.preview import colorize
from tapesmith.tape.profiles import TapeProfile
from tapesmith.i18n import _t

JOB_GAP = 6                     # Punkte Abstand zwischen Jobs in den zusammengesetzten Ansichten
HATCH_PERIOD = 4                # Schraffur-Periode (Punkte)
DESIGN_COLORS = {
    "tape": (255, 255, 255), "ink": (0, 0, 0), "leader": (200, 200, 200),
    "margin": (225, 225, 225), "hatch": (170, 170, 170), "cut": (90, 90, 90),
    "gap": (243, 243, 243),
}


@dataclass(frozen=True)
class PreviewData:
    design: Image.Image                    # "RGB", Querformat, 1 Pixel = 1 Druckpunkt
    raster: Image.Image                    # "1", Querformat, alle Jobs nebeneinander, JOB_GAP weiße Spalten dazwischen
    raster_jobs: tuple[Image.Image, ...]   # je Job: job.head.rotate(90, expand=True), exakt die gesendeten Bits
    content_mm: float                      # Summe job.length_mm
    content_dots: int                      # Summe job.head.height
    leader_trailer_mm: float               # len(jobs) * (leader_mm + trailer_mm)
    tape_mm: float                         # plan.balance.chain_mm
    labels: int                            # plan.balance.labels
    jobs: int
    estimated: bool                        # not {"leader", "trailer"} <= set(profile.verified)
    info: str
    warnings: tuple[str, ...]              # plan.warnings


def plan_for_preview(heads: Sequence[Image.Image], profile: DeviceProfile, *, copies: int = 1,
                      chain: bool = False, cut_marks: bool = True) -> ChainPlan:
    """Plant genau wie `PrintPipeline.plan`: `expand_copies` gefolgt von `plan_chain`/`plan_single`.
    `copies < 1` wirft `ValueError` (über `expand_copies`)."""
    expanded = expand_copies(list(heads), copies)
    if chain:
        return plan_chain(expanded, profile, cut_marks=cut_marks)
    return plan_single(expanded, profile)


def info_text(content_mm: float, content_dots: int, leader_trailer_mm: float, tape_mm: float,
              estimated: bool, balance: TapeBalance | None = None) -> str:
    text = (_t("Inhalt {content_mm:.0f} mm ({content_dots} Punkte) + Vor-/Nachlauf ca. {leader_trailer_mm:.0f} mm = ca. {tape_mm:.0f} mm Band", content_mm=content_mm, content_dots=content_dots, leader_trailer_mm=leader_trailer_mm, tape_mm=tape_mm))
    if estimated:
        text += _t(" (geschätzt)")
    if balance is not None and balance.labels > 1:
        text += f" · {balance.text()}"
    return text


def _content_rgb(content: Image.Image, profile: DeviceProfile, tape: TapeProfile | None = None) -> Image.Image:
    """Querformat-Inhalt (Modus "1") in Farbe: ohne Band schwarz -> "ink", weiß -> "tape";
    mit Band über `tape.preview.colorize` (Druckfarbe/Bandfarbe, Schachbrett bei transparent).
    Zeilen außerhalb des bedruckbaren Bereichs bleiben schraffiert ("hatch"/"margin"), außer wo
    Tinte liegt. `tape=None` ist bitgleich zum bisherigen Verhalten."""
    ink_mask = content.convert("L").point(lambda p: 255 if p < 128 else 0)
    if tape is None:
        rgb = Image.new("RGB", content.size, DESIGN_COLORS["tape"])
        rgb.paste(DESIGN_COLORS["ink"], (0, 0), ink_mask)
    else:
        rgb = colorize(content, tape)

    head_dots = profile.head_dots
    outside = [x for x in range(head_dots)
               if x < profile.content_offset or x >= profile.content_offset + profile.content_dots]
    if outside:
        mask_px = ink_mask.load()
        rgb_px = rgb.load()
        width = content.width
        for x_head in outside:
            y = head_dots - 1 - x_head
            for col in range(width):
                if mask_px[col, y]:
                    continue  # Tinte bleibt "ink"
                rgb_px[col, y] = (DESIGN_COLORS["hatch"] if (col + y) % HATCH_PERIOD == 0
                                  else DESIGN_COLORS["margin"])
    return rgb


def _job_segment(job: ChainJob, profile: DeviceProfile, lead: int, trail: int,
                  tape: TapeProfile | None = None) -> Image.Image:
    content = job.head.rotate(90, expand=True)
    content_rgb = _content_rgb(content, profile, tape)
    width = lead + content.width + trail
    seg = Image.new("RGB", (width, profile.head_dots), DESIGN_COLORS["leader"])
    seg.paste(content_rgb, (lead, 0))
    seg.paste(DESIGN_COLORS["cut"], (0, 0, 1, profile.head_dots))
    seg.paste(DESIGN_COLORS["cut"], (width - 1, 0, width, profile.head_dots))
    return seg


def design_image(plan: ChainPlan, profile: DeviceProfile, tape: TapeProfile | None = None) -> Image.Image:
    """Band mit grauem Vor-/Nachlauf, Schnittkanten und schraffierten nicht bedruckbaren Rändern,
    je Job nebeneinander (dazwischen `JOB_GAP` Spalten in "gap"). `tape=None` ist bitgleich zum
    bisherigen Verhalten (schwarz/weiß)."""
    lead = mm_to_rows(profile.leader_mm, profile)
    trail = mm_to_rows(profile.trailer_mm, profile)
    segments = [_job_segment(job, profile, lead, trail, tape) for job in plan.jobs]

    total_width = sum(seg.width for seg in segments) + JOB_GAP * max(len(segments) - 1, 0)
    canvas = Image.new("RGB", (total_width, profile.head_dots), DESIGN_COLORS["gap"])
    x = 0
    for i, seg in enumerate(segments):
        if i > 0:
            x += JOB_GAP
        canvas.paste(seg, (x, 0))
        x += seg.width
    return canvas


def raster_image(plan: ChainPlan) -> tuple[Image.Image, tuple[Image.Image, ...]]:
    """Exakt das 1-Bit-Raster, das gesendet wird: je Job `job.head.rotate(90, expand=True)`,
    nebeneinander mit `JOB_GAP` weißen Spalten dazwischen."""
    raster_jobs = tuple(job.head.rotate(90, expand=True) for job in plan.jobs)
    height = raster_jobs[0].height
    total_width = sum(im.width for im in raster_jobs) + JOB_GAP * max(len(raster_jobs) - 1, 0)

    canvas = Image.new("1", (total_width, height), 255)
    x = 0
    for i, im in enumerate(raster_jobs):
        if i > 0:
            x += JOB_GAP
        canvas.paste(im, (x, 0))
        x += im.width
    return canvas, raster_jobs


def build_preview(plan: ChainPlan, profile: DeviceProfile, tape: TapeProfile | None = None) -> PreviewData:
    jobs = plan.jobs
    content_mm = sum(job.length_mm for job in jobs)
    content_dots = sum(job.head.height for job in jobs)
    leader_trailer_mm = len(jobs) * (profile.leader_mm + profile.trailer_mm)
    tape_mm = plan.balance.chain_mm
    estimated = not {"leader", "trailer"} <= set(profile.verified)

    design = design_image(plan, profile, tape)
    raster, raster_jobs = raster_image(plan)
    info = info_text(content_mm, content_dots, leader_trailer_mm, tape_mm, estimated,
                      balance=plan.balance)
    if tape is not None:
        info += _t(" · Band: {name}", name=tape.name)

    return PreviewData(
        design=design, raster=raster, raster_jobs=raster_jobs,
        content_mm=content_mm, content_dots=content_dots,
        leader_trailer_mm=leader_trailer_mm, tape_mm=tape_mm,
        labels=plan.balance.labels, jobs=len(jobs),
        estimated=estimated, info=info, warnings=plan.warnings,
    )
