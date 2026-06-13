"""Optical music recognition (first-stage) for Clef Shift.

This module reads notation *directly* from a rendered/scanned score image and
returns detected note events. It is deliberately staff-aware: instead of doing
generic blob detection, it (1) finds the staff systems, (2) learns the staff
line spacing, and (3) scans for noteheads only at the discrete vertical
positions where notes can actually sit (lines, spaces, and ledger positions).

Pipeline:
    image -> adaptive binarize -> staff systems -> staff line removal ->
    staff-aware notehead scan -> stem gate -> pitch from staff position

It intentionally returns a rich ``DetectionResult`` (with a success flag, a
human-readable failure reason, and debug-image paths) so the rest of the app
can stay honest when detection fails instead of faking a conversion.

Current scope / known limits (tracked for follow-up phases):
  * Pitch is inferred from staff position only. Accidentals printed next to a
    note are NOT yet folded into the pitch (an F#5 currently reads as F5).
  * Duration is not yet read from notehead shape/beams; callers should treat
    durations as unknown. Open noteheads (half/whole) are under-detected
    because the scanner favors solid noteheads, and whole notes (no stem) are
    rejected by the stem gate. These are deliberate trade-offs for this phase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage


# --- pitch geometry -------------------------------------------------------

BOTTOM_DIATONIC = {
    "treble": ("E", 4),
    "bass": ("G", 2),
    "alto": ("F", 3),
}
STEP_NAMES = ["C", "D", "E", "F", "G", "A", "B"]
STEP_TO_INDEX = {step: idx for idx, step in enumerate(STEP_NAMES)}

# --- detector tuning ------------------------------------------------------
# All spatial thresholds are expressed as multiples of the measured staff
# spacing (distance between two adjacent staff lines), so the detector is
# resolution-independent.

TARGET_WIDTH = 1800          # upscale narrow images to roughly this width
ADAPTIVE_OFFSET = 12         # local-mean minus this -> ink (document binarization)
STAFF_OPEN_FRACTION = 0.28   # horizontal opening length as a fraction of width
STAFF_ROW_FRACTION = 0.35    # a staff-line row must keep >= this * max strength

NOTEHEAD_W = 1.20            # notehead window width  (x spacing units)
NOTEHEAD_H = 0.85            # notehead window height (x spacing units)
FILL_MIN = 0.42              # min ink fill ratio for a solid-notehead window
FILL_MAX = 0.95              # above this is a solid bar/blob, not a notehead
CORE_MIN = 0.85              # min ink fill of the notehead *core*. Solid heads
                             # are dense at the center; sharps/naturals/flats
                             # and the time-signature C are hollow there.
CORE_W = 0.32                # core window half-width  (x spacing units)
CORE_H = 0.30                # core window half-height (x spacing units)
SUPPRESS_DX = 0.70           # NMS: collapse candidates closer than this in x
SUPPRESS_DY = 0.80           # NMS: ... and this in y (in spacing units)
BEAM_MAX_W = 2.6             # max horizontal solid extent of a notehead. Beams
                             # are solid bars far wider than this, so this gate
                             # rejects beam segments that pass the fill/core test.
                             # Headroom above ~2.1s leaves ledger-line notes
                             # (whose ledger adds horizontal ink) intact.
STEM_MIN = 1.6               # required stem length (spacing units)
HEADER_TALL = 3.5            # clef/brace gate: taller than this (spacing units)
HEADER_WIDE = 2.0            # ... and wider than this. A stemmed note is tall
                             # but narrow, so this avoids skipping the 1st note.


@dataclass
class StaffGroup:
    lines: list[float]       # 5 line center y-positions, top -> bottom
    spacing: float
    x_start: float
    x_end: float


@dataclass
class NoteCandidate:
    x: float
    y: float
    staff_index: int
    step: int                # diatonic steps above the bottom staff line
    token: str
    fill: float
    has_stem: bool = False


@dataclass
class DetectionResult:
    success: bool
    reason: str
    notes: list[str]
    staff_count: int
    note_count: int
    spacing: float
    debug_dir: Optional[str] = None
    debug_images: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


# --- image loading & binarization ----------------------------------------

def load_gray(image_path: Path) -> np.ndarray:
    """Load as grayscale, upscaling small images so spacing has enough pixels."""
    image = Image.open(image_path).convert("L")
    if image.width < TARGET_WIDTH:
        scale = TARGET_WIDTH / image.width
        image = image.resize(
            (int(image.width * scale), int(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    return np.array(image, dtype=np.uint8)


def adaptive_binarize(gray: np.ndarray) -> np.ndarray:
    """Local-adaptive document threshold (robust to uneven lighting / scans).

    A pixel is ink if it is meaningfully darker than its local neighborhood.
    This is far more reliable on near-white pages than global Otsu, which
    degenerates when ink is a tiny fraction of the image.
    """
    g = gray.astype(np.float32)
    window = int(round(min(gray.shape) * 0.025))
    window += (window + 1) % 2  # force odd
    window = max(window, 15)
    local = ndimage.uniform_filter(g, size=window)
    return g < (local - ADAPTIVE_OFFSET)


# --- staff detection ------------------------------------------------------

def horizontal_opening(binary: np.ndarray, length: int) -> np.ndarray:
    """Keep only ink that belongs to a horizontal run of >= ``length`` pixels.

    Implemented with cumulative sums (erosion then dilation by a 1xL element)
    so it stays fast even for very long structuring elements. This isolates
    staff lines from noteheads, stems, and text.
    """
    height, width = binary.shape
    if length < 1 or length > width:
        return np.zeros_like(binary)

    cum = np.zeros((height, width + 1), dtype=np.int32)
    np.cumsum(binary, axis=1, out=cum[:, 1:])
    window = cum[:, length:] - cum[:, : width - length + 1]  # ink count per window
    eroded = window == length                                 # fully-ink window left-edges

    starts = eroded.shape[1]
    edge_cum = np.zeros((height, starts + 1), dtype=np.int32)
    np.cumsum(eroded, axis=1, out=edge_cum[:, 1:])

    ks = np.arange(width)
    lo = np.clip(ks - length + 1, 0, starts)
    hi = np.clip(ks + 1, 0, starts)
    return (edge_cum[:, hi] - edge_cum[:, lo]) > 0


def group_consecutive(rows: Iterable[int]) -> list[list[int]]:
    rows = list(rows)
    if not rows:
        return []
    groups: list[list[int]] = [[rows[0]]]
    for row in rows[1:]:
        if row <= groups[-1][-1] + 2:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def estimate_spacing(line_strength: np.ndarray, line_centers: list[float]) -> float:
    """Estimate staff line spacing.

    Primary signal is the autocorrelation of the staff-line row strength (its
    dominant short-range period is the spacing). Cross-checked against the
    median of adjacent line-center gaps.
    """
    centers_spacing = 0.0
    if len(line_centers) >= 2:
        diffs = np.diff(sorted(line_centers))
        small = diffs[diffs >= 2]
        if small.size:
            base = float(np.median(small))
            near = small[small <= base * 1.8]
            centers_spacing = float(np.median(near)) if near.size else base

    sig = line_strength - line_strength.mean()
    ac = np.correlate(sig, sig, mode="full")[len(sig) - 1:]
    lo, hi = 4, max(8, len(sig) // 8)
    auto_spacing = float(lo + int(np.argmax(ac[lo:hi]))) if hi > lo else 0.0

    if centers_spacing and auto_spacing:
        # Trust the line-center median, but only if autocorr broadly agrees.
        if 0.6 <= centers_spacing / auto_spacing <= 1.6:
            return centers_spacing
        return auto_spacing
    return centers_spacing or auto_spacing or 12.0


def group_into_staves(
    line_centers: list[float], spacing: float, x_start: float, x_end: float
) -> list[StaffGroup]:
    """Group detected line centers into 5-line systems.

    Tolerant: a system is accepted if at least 4 of 5 expected lines are found,
    so one broken/missing staff line does not lose the whole system. Missing
    lines are filled in by interpolation from the spacing.
    """
    centers = sorted(line_centers)
    used = [False] * len(centers)
    tol = spacing * 0.40
    staves: list[StaffGroup] = []

    for i, top in enumerate(centers):
        if used[i]:
            continue
        positions: list[float] = []
        matched: list[Optional[int]] = []
        for k in range(5):
            target = top + k * spacing
            best, best_d = None, tol
            for j, c in enumerate(centers):
                if used[j]:
                    continue
                d = abs(c - target)
                if d < best_d:
                    best_d, best = d, j
            if best is None:
                positions.append(target)
                matched.append(None)
            else:
                positions.append(centers[best])
                matched.append(best)

        if sum(1 for m in matched if m is not None) >= 4:
            for m in matched:
                if m is not None:
                    used[m] = True
            staves.append(
                StaffGroup(lines=positions, spacing=spacing, x_start=x_start, x_end=x_end)
            )
    return staves


def detect_staff_groups(binary: np.ndarray) -> tuple[list[StaffGroup], np.ndarray, float]:
    """Return (staff systems, staff-line mask, spacing)."""
    height, width = binary.shape
    length = max(20, int(width * STAFF_OPEN_FRACTION))
    lines_mask = horizontal_opening(binary, length)

    row_strength = lines_mask.sum(axis=1).astype(np.float32)
    if row_strength.max() <= 0:
        return [], lines_mask, 0.0

    strong_rows = np.where(row_strength >= row_strength.max() * STAFF_ROW_FRACTION)[0]
    row_groups = group_consecutive(strong_rows.tolist())
    line_centers = [float(np.mean(group)) for group in row_groups]
    if len(line_centers) < 4:
        return [], lines_mask, 0.0

    spacing = estimate_spacing(row_strength, line_centers)

    # Horizontal extent where staff lines actually run (skip page margins).
    col_strength = lines_mask.sum(axis=0)
    inked_cols = np.where(col_strength > col_strength.max() * 0.25)[0]
    x_start = float(inked_cols[0]) if inked_cols.size else 0.0
    x_end = float(inked_cols[-1]) if inked_cols.size else float(width - 1)

    staves = group_into_staves(line_centers, spacing, x_start, x_end)
    return staves, lines_mask, spacing


def remove_staff_lines(binary: np.ndarray, staves: list[StaffGroup]) -> np.ndarray:
    """Erase staff lines while preserving stems/noteheads that cross them.

    Within each line band, a pixel is only erased if there is no ink just
    above and below the band at that column (i.e. it is part of the thin
    horizontal line, not a vertical stroke passing through).
    """
    result = binary.copy()
    height = binary.shape[0]
    for staff in staves:
        half = max(1, int(round(staff.spacing * 0.16)))
        for line in staff.lines:
            row = int(round(line))
            top = max(0, row - half)
            bottom = min(height, row + half + 1)
            above_row = max(0, top - 1)
            below_row = min(height - 1, bottom)
            crossing = binary[above_row] & binary[below_row]  # vertical stroke -> keep
            band = result[top:bottom]
            band[:, ~crossing] = False
    return result


# --- notehead scanning ----------------------------------------------------

def integral_image(binary: np.ndarray) -> np.ndarray:
    integral = np.zeros((binary.shape[0] + 1, binary.shape[1] + 1), dtype=np.int32)
    integral[1:, 1:] = binary.astype(np.int32).cumsum(axis=0).cumsum(axis=1)
    return integral


def window_fill(integral: np.ndarray, cy: int, cx: int, half_h: int, half_w: int) -> float:
    """Ink fill ratio of a notehead-sized window centered at (cy, cx)."""
    h, w = integral.shape[0] - 1, integral.shape[1] - 1
    y0, y1 = max(0, cy - half_h), min(h, cy + half_h + 1)
    x0, x1 = max(0, cx - half_w), min(w, cx + half_w + 1)
    if y0 >= y1 or x0 >= x1:
        return 0.0
    total = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
    return float(total) / float((y1 - y0) * (x1 - x0))


def longest_vertical_run(strip: np.ndarray) -> int:
    """Longest run of consecutive ink in any single column of ``strip``."""
    if strip.size == 0:
        return 0
    best = 0
    for col in range(strip.shape[1]):
        run = 0
        for val in strip[:, col]:
            if val:
                run += 1
                best = max(best, run)
            else:
                run = 0
    return best


def horizontal_solid_extent(staff_removed: np.ndarray, cx: float, cy: float, spacing: float) -> float:
    """Width of the contiguous solid-ink band through (cx, cy).

    A notehead is a compact blob (~1.3 spacing wide); a beam is a long solid
    bar. Measuring how far solid ink extends horizontally separates them.
    """
    s = spacing
    half = max(1, int(round(0.22 * s)))
    cyi, cxi = int(round(cy)), int(round(cx))
    y0, y1 = max(0, cyi - half), min(staff_removed.shape[0], cyi + half + 1)
    strip = staff_removed[y0:y1]
    if strip.size == 0:
        return 0.0
    col_frac = strip.mean(axis=0)
    width = col_frac.shape[0]
    if cxi < 0 or cxi >= width or col_frac[cxi] < 0.5:
        return 0.0
    left = cxi
    while left > 0 and col_frac[left - 1] >= 0.55:
        left -= 1
    right = cxi
    while right < width - 1 and col_frac[right + 1] >= 0.55:
        right += 1
    return float(right - left + 1)


def has_stem(binary: np.ndarray, cx: float, cy: float, spacing: float) -> bool:
    """True if a vertical stem is attached to the right (up) or left (down)."""
    height = binary.shape[0]
    s = spacing
    stem_min = int(round(STEM_MIN * s))
    near = int(round(0.30 * s))
    far = int(round(0.85 * s))
    reach = int(round(2.6 * s))
    cxi, cyi = int(round(cx)), int(round(cy))

    # stem up: to the right of the notehead, going upward
    x0, x1 = cxi + near, cxi + far + 1
    y0, y1 = max(0, cyi - reach), min(height, cyi + near)
    if x1 > x0 and y1 > y0:
        if longest_vertical_run(binary[y0:y1, max(0, x0):x1]) >= stem_min:
            return True

    # stem down: to the left of the notehead, going downward
    x0, x1 = cxi - far, cxi - near + 1
    y0, y1 = max(0, cyi - near), min(height, cyi + reach)
    if x1 > x0 and y1 > y0:
        if longest_vertical_run(binary[y0:y1, max(0, x0):x1]) >= stem_min:
            return True
    return False


def header_skip_x(staff_removed: np.ndarray, staff: StaffGroup) -> float:
    """X coordinate after the leading clef (and any tall leading glyphs).

    Finds tall+wide connected components near the staff's left edge and returns
    the right edge of the leftmost one, so the clef/brace is not scanned as
    notes. Must run on the staff-line-removed image, otherwise the staff lines
    connect every glyph into one component spanning the whole system.
    """
    binary = staff_removed
    s = staff.spacing
    top = max(0, int(round(staff.lines[0] - 2 * s)))
    bottom = min(binary.shape[0], int(round(staff.lines[-1] + 2 * s)))
    left = int(round(staff.x_start))
    right = min(binary.shape[1], int(round(staff.x_start + 12 * s)))
    if right <= left or bottom <= top:
        return staff.x_start

    region = binary[top:bottom, left:right]
    labels, count = ndimage.label(region)
    if count == 0:
        return staff.x_start
    skip = staff.x_start
    for comp in ndimage.find_objects(labels):
        ys, xs = comp
        comp_h = ys.stop - ys.start
        comp_w = xs.stop - xs.start
        # Clef/brace: both tall and wide. A stemmed note is tall but narrow,
        # so requiring width here keeps the first note from being skipped.
        if comp_h >= HEADER_TALL * s and comp_w >= HEADER_WIDE * s:
            skip = max(skip, left + xs.stop + 0.3 * s)
    return skip


def note_token_from_step(step: int, staff: StaffGroup, source_clef: str) -> tuple[str, int]:
    """Map a diatonic step offset above the bottom line to (token, octave)."""
    bottom_step, bottom_octave = BOTTOM_DIATONIC[source_clef]
    bottom_index = bottom_octave * 7 + STEP_TO_INDEX[bottom_step]
    diatonic_index = bottom_index + step
    octave, step_index = divmod(diatonic_index, 7)
    return f"{STEP_NAMES[step_index]}{octave}", octave


def detect_notes_in_staff(
    staff_removed: np.ndarray,
    binary: np.ndarray,
    staff: StaffGroup,
    staff_index: int,
    source_clef: str,
    raw_candidates: list[tuple[float, float]],
) -> list[NoteCandidate]:
    """Scan one staff for noteheads at discrete staff positions."""
    s = staff.spacing
    half_h = max(2, int(round(NOTEHEAD_H * s / 2)))
    half_w = max(3, int(round(NOTEHEAD_W * s / 2)))
    integral = integral_image(staff_removed)
    bottom_line = staff.lines[-1]

    left = max(int(round(header_skip_x(staff_removed, staff))), int(round(staff.x_start)))
    right = int(round(staff.x_end))

    # Candidate scan: for each pitch row (half-spacing steps from a couple
    # ledger lines below to several above), slide the notehead window in x.
    candidates: list[NoteCandidate] = []
    for step in range(-5, 18):
        cy = bottom_line - step * (s / 2.0)
        cyi = int(round(cy))
        if cyi < 0 or cyi >= staff_removed.shape[0]:
            continue
        x = left
        step_x = max(1, half_w // 2)
        while x <= right:
            fill = window_fill(integral, cyi, x, half_h, half_w)
            if FILL_MIN <= fill <= FILL_MAX:
                raw_candidates.append((float(x), cy))
                candidates.append(
                    NoteCandidate(
                        x=float(x), y=cy, staff_index=staff_index, step=step,
                        token="", fill=fill,
                    )
                )
            x += step_x

    # Non-max suppression: collapse the many overlapping hits (a real notehead
    # fires at several adjacent x offsets and pitch rows) down to one per note,
    # keeping the highest-fill hit -> best-aligned pitch row.
    candidates.sort(key=lambda c: c.fill, reverse=True)
    kept: list[NoteCandidate] = []
    for cand in candidates:
        if any(
            abs(cand.x - k.x) < SUPPRESS_DX * s and abs(cand.y - k.y) < SUPPRESS_DY * s
            for k in kept
        ):
            continue
        kept.append(cand)

    # Core + stem gates. Core fill rejects hollow glyphs (sharps, naturals,
    # flats, the time-signature C) that pass the looser window-fill test. The
    # stem gate rejects remaining stray marks; real notes here carry a stem.
    core_h = max(1, int(round(CORE_H * s)))
    core_w = max(1, int(round(CORE_W * s)))
    accepted: list[NoteCandidate] = []
    for cand in kept:
        core = window_fill(integral, int(round(cand.y)), int(round(cand.x)), core_h, core_w)
        if core < CORE_MIN:
            continue
        if horizontal_solid_extent(staff_removed, cand.x, cand.y, s) > BEAM_MAX_W * s:
            continue
        if not has_stem(staff_removed, cand.x, cand.y, s):
            continue
        cand.has_stem = True
        token, _octave = note_token_from_step(cand.step, staff, source_clef)
        cand.token = token
        accepted.append(cand)

    accepted.sort(key=lambda c: c.x)
    return accepted


# --- debug rendering ------------------------------------------------------

def _to_rgb(gray: np.ndarray) -> Image.Image:
    return Image.fromarray(gray).convert("RGB")


def write_debug_images(
    debug_dir: Path,
    gray: np.ndarray,
    binary: np.ndarray,
    staves: list[StaffGroup],
    raw_candidates: list[tuple[float, float]],
    accepted: list[NoteCandidate],
) -> list[str]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # 01 threshold
    thr = Image.fromarray(np.where(binary, 0, 255).astype(np.uint8)).convert("RGB")
    p = debug_dir / "01_threshold.png"
    thr.save(p)
    written.append(str(p))

    # 02 staff overlay
    img = _to_rgb(gray)
    draw = ImageDraw.Draw(img)
    for staff in staves:
        for line in staff.lines:
            draw.line([(staff.x_start, line), (staff.x_end, line)], fill=(220, 30, 30), width=1)
        top = staff.lines[0] - staff.spacing * 4
        bottom = staff.lines[-1] + staff.spacing * 4
        draw.rectangle([staff.x_start, top, staff.x_end, bottom], outline=(30, 140, 30))
    p = debug_dir / "02_staff_overlay.png"
    img.save(p)
    written.append(str(p))

    # 03 raw candidates
    img = _to_rgb(gray)
    draw = ImageDraw.Draw(img)
    for cx, cy in raw_candidates:
        draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], outline=(210, 160, 0))
    p = debug_dir / "03_candidates.png"
    img.save(p)
    written.append(str(p))

    # 04 accepted notes
    img = _to_rgb(gray)
    draw = ImageDraw.Draw(img)
    for note in accepted:
        r = 6
        draw.ellipse(
            [note.x - r, note.y - r, note.x + r, note.y + r],
            outline=(20, 110, 220), width=2,
        )
        draw.text((note.x - 6, note.y - 22), note.token, fill=(20, 110, 220))
    p = debug_dir / "04_accepted_notes.png"
    img.save(p)
    written.append(str(p))

    return written


# --- top-level API --------------------------------------------------------

def analyze_image(
    image_path: Path,
    source_clef: str = "treble",
    debug: bool = False,
    debug_dir: Optional[Path] = None,
) -> DetectionResult:
    """Read notes directly from a score image. Honest about failure."""
    if source_clef not in BOTTOM_DIATONIC:
        source_clef = "treble"

    try:
        gray = load_gray(Path(image_path))
    except Exception as exc:  # noqa: BLE001 - report any decode failure honestly
        return DetectionResult(
            success=False, reason=f"Could not open image: {exc}",
            notes=[], staff_count=0, note_count=0, spacing=0.0,
        )

    binary = adaptive_binarize(gray)
    if not binary.any():
        return DetectionResult(
            success=False,
            reason="Image appears blank after thresholding (no ink detected).",
            notes=[], staff_count=0, note_count=0, spacing=0.0,
        )

    staves, _lines_mask, spacing = detect_staff_groups(binary)
    detail: dict = {
        "image_size": [int(gray.shape[1]), int(gray.shape[0])],
        "spacing": round(spacing, 2),
        "staff_count": len(staves),
        "staves": [[round(v, 1) for v in s.lines] for s in staves],
    }

    if not staves:
        result = DetectionResult(
            success=False,
            reason=(
                "No staff systems detected. The image may not contain printed "
                "five-line staves, or the contrast/resolution is too low."
            ),
            notes=[], staff_count=0, note_count=0, spacing=spacing, detail=detail,
        )
        _maybe_write_debug(debug, debug_dir, image_path, gray, binary, staves, [], [], result)
        return result

    staff_removed = remove_staff_lines(binary, staves)
    raw_candidates: list[tuple[float, float]] = []
    accepted: list[NoteCandidate] = []
    for idx, staff in enumerate(staves):
        accepted.extend(
            detect_notes_in_staff(
                staff_removed, binary, staff, idx, source_clef, raw_candidates
            )
        )

    accepted.sort(key=lambda c: (c.staff_index, c.x))
    notes = [c.token for c in accepted]
    detail["raw_candidate_count"] = len(raw_candidates)
    detail["accepted_notes"] = [
        {"staff": c.staff_index, "x": round(c.x, 1), "y": round(c.y, 1),
         "token": c.token, "fill": round(c.fill, 3)}
        for c in accepted
    ]

    if not notes:
        result = DetectionResult(
            success=False,
            reason=(
                f"Found {len(staves)} staff system(s) but no noteheads. The "
                "notation may be too faint, handwritten, or low resolution."
            ),
            notes=[], staff_count=len(staves), note_count=0, spacing=spacing,
            detail=detail,
        )
        _maybe_write_debug(
            debug, debug_dir, image_path, gray, binary, staves, raw_candidates, accepted, result
        )
        return result

    result = DetectionResult(
        success=True,
        reason=f"Detected {len(notes)} note(s) across {len(staves)} staff system(s).",
        notes=notes, staff_count=len(staves), note_count=len(notes), spacing=spacing,
        detail=detail,
    )
    _maybe_write_debug(
        debug, debug_dir, image_path, gray, binary, staves, raw_candidates, accepted, result
    )
    return result


def _maybe_write_debug(
    debug: bool,
    debug_dir: Optional[Path],
    image_path: Path,
    gray: np.ndarray,
    binary: np.ndarray,
    staves: list[StaffGroup],
    raw_candidates: list[tuple[float, float]],
    accepted: list[NoteCandidate],
    result: DetectionResult,
) -> None:
    if not debug:
        return
    target = Path(debug_dir) if debug_dir else Path(image_path).resolve().parent / "debug"
    try:
        images = write_debug_images(target, gray, binary, staves, raw_candidates, accepted)
        report = {
            "success": result.success,
            "reason": result.reason,
            "notes": result.notes,
            **result.detail,
        }
        report_path = target / "detection_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        result.debug_dir = str(target)
        result.debug_images = images + [str(report_path)]
    except Exception as exc:  # noqa: BLE001 - debug output must never break detection
        result.detail["debug_error"] = str(exc)


def detect_notes(image_path: Path, source_clef: str = "treble") -> list[str]:
    """Backwards-compatible wrapper returning just the note tokens."""
    return analyze_image(image_path, source_clef).notes
