"""Run the Audiveris OMR engine as a subprocess and turn its MusicXML output
into note tokens the rest of Clef Shift understands.

Audiveris is a mature open-source optical music recognition engine. It reads
real engraved scores well — open noteheads, key signatures, accidentals and
rhythm — and exports MusicXML, fast (seconds, not minutes). It is built once via
`gradlew installDist` (see README) and invoked here through its generated
launcher, the same way server.py shells out to tesseract and ghostscript.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

from score_pipeline import musicxml_to_tokens

ROOT = Path(__file__).resolve().parent

# --- confidence gate ------------------------------------------------------
# Audiveris is accurate on clean scans but can misread a poor upload into
# garbage (sometimes derived from the clef/key/time region). Rather than pass
# that through, we sanity-check the read and, if it looks incoherent, return no
# notes -- honouring "no notes rather than wrong notes" for the Audiveris path
# too. A token-level gate cannot catch a misread that happens to look like a
# plausible short note list; the measure-duration check is the strongest signal
# because metadata misreads usually break the bar arithmetic.

MIN_NOTES = 2                # fewer than this from a whole page is suspicious
MIDI_LOW, MIDI_HIGH = 21, 108  # A0..C8 -- real notation lives well inside this
WILD_JUMP_SEMITONES = 24    # a leap larger than two octaves between adjacent notes
WILD_JUMP_FRACTION = 0.5    # ... this fraction of leaps being wild = scattered
MEASURE_BAD_FRACTION = 0.5  # ... this fraction of measures not adding up = garbage

# Audiveris assigns every recognised symbol a contextual grade (0..1) in its
# .omr project file. On a clean read, noteheads score ~0.85-0.94 (open heads a
# bit lower). A misread that the classifier was unsure about scores low, so the
# mean head grade is the strongest "is this trustworthy" signal we have.
# Thresholds are deliberately lenient (clean reads sit well above them) and the
# numbers are surfaced so they can be tightened once a real garbage read is in
# hand.
CTX_MEAN_MIN = 0.55         # reject if the mean notehead contextual grade is below this
GRADE_HEAD_FLOOR = 0.35     # a notehead grade below this counts as "weak"
GRADE_WEAK_FRACTION = 0.5   # reject if more than this fraction of heads are weak

# These two thresholds are the ones the calibration loop (train/) tunes. If a
# calibrated gate_params.json is present and valid, we use it; otherwise we fall
# back to the hand-set guesses above. Either way the gate stays honest.
_GATE_PARAM_PATHS = [
    os.environ.get("AUDIVERIS_GATE_PARAMS"),
    str(ROOT / "gate_params.json"),
    str(ROOT / "train" / "data" / "gate_params.json"),
]


def _load_gate_params() -> Optional[dict]:
    """Load calibrated thresholds, failing safe to None on any problem."""
    for candidate in _GATE_PARAM_PATHS:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            ctx = float(data["CTX_MEAN_MIN"])
            mbf = float(data["MEASURE_BAD_FRACTION"])
            if 0.0 <= ctx <= 1.0 and 0.0 <= mbf <= 1.01:
                return {"CTX_MEAN_MIN": ctx, "MEASURE_BAD_FRACTION": mbf, "path": str(path)}
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError):
            continue  # malformed -> ignore, fall back
    return None


_GATE_PARAMS = _load_gate_params()
if _GATE_PARAMS:
    ACTIVE_CTX_MEAN_MIN = _GATE_PARAMS["CTX_MEAN_MIN"]
    ACTIVE_MEASURE_BAD_FRACTION = _GATE_PARAMS["MEASURE_BAD_FRACTION"]
    GATE_SOURCE = f"calibrated ({_GATE_PARAMS['path']})"
else:
    ACTIVE_CTX_MEAN_MIN = CTX_MEAN_MIN
    ACTIVE_MEASURE_BAD_FRACTION = MEASURE_BAD_FRACTION
    GATE_SOURCE = "fallback (hand-set guesses)"


def gate_threshold_info() -> dict:
    """Which thresholds the gate is using right now (for logging/UI)."""
    return {
        "source": GATE_SOURCE,
        "ctx_mean_min": ACTIVE_CTX_MEAN_MIN,
        "measure_bad_fraction": ACTIVE_MEASURE_BAD_FRACTION,
    }


def parse_omr_grades(omr_path: Path) -> Optional[dict]:
    """Read per-notehead recognition grades from an Audiveris .omr project file.

    The .omr is a zip of sheet#N.xml files; each recognised notehead is a
    ``<head ... grade=".." ctx-grade=".." shape=".." pitch="..">`` element.
    Returns aggregate + per-head grades, or None if the file can't be read.
    """
    heads: list[dict] = []
    try:
        with zipfile.ZipFile(omr_path) as archive:
            sheets = [n for n in archive.namelist() if n.endswith(".xml") and "sheet#" in n]
            for name in sheets:
                data = archive.read(name).decode("utf-8", errors="ignore")
                for tag in re.findall(r"<head\b[^>]*>", data):
                    g = re.search(r'\bgrade="([0-9.]+)"', tag)
                    if not g:
                        continue
                    c = re.search(r'\bctx-grade="([0-9.]+)"', tag)
                    sh = re.search(r'\bshape="([A-Z_]+)"', tag)
                    p = re.search(r'\bpitch="(-?\d+)"', tag)
                    grade = float(g.group(1))
                    heads.append({
                        "shape": sh.group(1) if sh else "",
                        "grade": grade,
                        "ctx": float(c.group(1)) if c else grade,
                        "pitch": int(p.group(1)) if p else None,
                    })
    except (zipfile.BadZipFile, OSError):
        return None

    if not heads:
        return {"head_count": 0, "heads": [], "mean_grade": 0.0, "min_grade": 0.0,
                "mean_ctx": 0.0, "min_ctx": 0.0}
    grades = [h["grade"] for h in heads]
    ctxs = [h["ctx"] for h in heads]
    return {
        "head_count": len(heads),
        "heads": heads,
        "mean_grade": round(sum(grades) / len(grades), 3),
        "min_grade": round(min(grades), 3),
        "mean_ctx": round(sum(ctxs) / len(ctxs), 3),
        "min_ctx": round(min(ctxs), 3),
    }

_TOKEN_RE = re.compile(r"^([A-G])([#b]?)(-?\d+)$")
_STEP_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _midi(token: str) -> Optional[int]:
    m = _TOKEN_RE.match(token.strip())
    if not m:
        return None
    step, acc, octave = m.group(1), m.group(2), int(m.group(3))
    semi = _STEP_SEMI[step] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return (octave + 1) * 12 + semi


def _measure_coherence(xml_text: str) -> tuple[int, int]:
    """Return (malformed_measures, total_checkable_measures).

    A measure is malformed when its notes/rests do not sum to the duration the
    time signature implies -- a common symptom of a garbled OMR read.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return 0, 0
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    divisions = beats = beat_type = None
    bad = total = 0
    for measure in root.iter("measure"):
        d = measure.find(".//divisions")
        if d is not None and (d.text or "").strip().isdigit():
            divisions = int(d.text)
        t = measure.find(".//time")
        if t is not None:
            b, bt = t.findtext("beats"), t.findtext("beat-type")
            if b and b.strip().isdigit():
                beats = int(b)
            if bt and bt.strip().isdigit():
                beat_type = int(bt)
        if not (divisions and beats and beat_type):
            continue
        expected = divisions * beats * 4 / beat_type
        dur = 0
        for note in measure.iter("note"):
            if note.find("chord") is not None:
                continue
            dt = note.findtext("duration")
            if dt and dt.strip().lstrip("-").isdigit():
                dur += int(dt)
        total += 1
        if abs(dur - expected) > max(1.0, 0.1 * expected):
            bad += 1
    return bad, total


def assess_confidence(
    xml_text: str, tokens: list[str], grades: Optional[dict] = None
) -> tuple[bool, str, list[dict]]:
    """Decide whether an Audiveris read is trustworthy.

    Returns (ok, reason_if_not, decision_path). The decision_path lists every
    check with its result and a human-readable detail, so callers can show
    exactly why a read was accepted or rejected and whether the rejection came
    from the MusicXML measure math, the Audiveris grades, or the token sanity
    checks.
    """
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str, source: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "source": source})

    midis = [_midi(t) for t in tokens]

    record("note_count", len(tokens) >= MIN_NOTES, f"{len(tokens)} note(s)", "tokens")

    in_range = bool(midis) and all(m is not None and MIDI_LOW <= m <= MIDI_HIGH for m in midis)
    record("pitch_range", in_range, "all within A0–C8" if in_range else "a note is out of range", "tokens")

    valid = [m for m in midis if m is not None]
    jumps = [abs(valid[i + 1] - valid[i]) for i in range(len(valid) - 1)]
    wild = (sum(j > WILD_JUMP_SEMITONES for j in jumps) / len(jumps)) if jumps else 0.0
    record("erratic_leaps", wild < WILD_JUMP_FRACTION, f"{round(wild * 100)}% of steps leap >2 octaves", "tokens")

    bad, total = _measure_coherence(xml_text)
    meas_ok = not (total >= 2 and bad / total > ACTIVE_MEASURE_BAD_FRACTION)
    record("measure_arithmetic", meas_ok,
           f"{bad}/{total} measures don't add up (allowed ≤{ACTIVE_MEASURE_BAD_FRACTION:g})", "musicxml")

    if grades and grades.get("head_count", 0) > 0:
        mean_ctx = grades["mean_ctx"]
        weak_frac = sum(1 for h in grades["heads"] if h["ctx"] < GRADE_HEAD_FLOOR) / grades["head_count"]
        grades_ok = mean_ctx >= ACTIVE_CTX_MEAN_MIN and weak_frac <= GRADE_WEAK_FRACTION
        record("audiveris_grades", grades_ok,
               f"mean ctx-grade {mean_ctx:.2f} (min {grades['min_ctx']:.2f}), "
               f"{round(weak_frac * 100)}% below {GRADE_HEAD_FLOOR}; "
               f"need mean ≥{ACTIVE_CTX_MEAN_MIN:g} [{GATE_SOURCE.split()[0]}]", "audiveris")
    else:
        record("audiveris_grades", True, "no .omr grade data available", "audiveris")

    failed = [c for c in checks if not c["ok"]]
    reason = "; ".join(f'{c["check"]} [{c["source"]}]: {c["detail"]}' for c in failed)
    return (not failed), reason, checks

# Launcher produced by `gradlew :app:installDist`. The Audiveris checkout lives
# beside the project (it is vendor code, kept out of this repo). Override with
# the AUDIVERIS_CMD env var if it lives elsewhere.
_DEFAULT_LAUNCHER = ROOT.parent / "audiveris-src" / "app" / "build" / "install" / "app" / "bin" / "Audiveris"
AUDIVERIS_CMD = Path(os.environ.get("AUDIVERIS_CMD", str(_DEFAULT_LAUNCHER)))

# Audiveris 5.10.2 needs Java 25; its launcher honours JAVA_HOME. The system
# `java` may be older, so we point at the JDK used to build it.
AUDIVERIS_JAVA_HOME = os.environ.get(
    "AUDIVERIS_JAVA_HOME",
    "/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home",
)


def audiveris_available() -> bool:
    """True when the built Audiveris launcher is present."""
    return AUDIVERIS_CMD.exists()


def _extract_musicxml(out_dir: Path) -> Optional[str]:
    """Find the MusicXML Audiveris exported (compressed .mxl or plain .xml)."""
    for mxl in sorted(out_dir.rglob("*.mxl")):
        try:
            with zipfile.ZipFile(mxl) as archive:
                members = [
                    name for name in archive.namelist()
                    if name.lower().endswith((".xml", ".musicxml")) and "META-INF" not in name
                ]
                if members:
                    return archive.read(members[0]).decode("utf-8", errors="ignore")
        except zipfile.BadZipFile:
            continue
    for xml in sorted(out_dir.rglob("*.musicxml")) + sorted(out_dir.rglob("*.xml")):
        if "META-INF" in str(xml):
            continue
        return xml.read_text(encoding="utf-8", errors="ignore")
    return None


def run_audiveris(image_path: Path, timeout: int = 300) -> tuple[Optional[str], Optional[dict], str]:
    """Run Audiveris in batch/export mode.

    Returns (musicxml_text, grade_info, error). grade_info is parsed from the
    .omr project file (per-notehead recognition grades) when available.
    """
    if not audiveris_available():
        return None, None, "Audiveris is not installed"

    env = dict(os.environ)
    if AUDIVERIS_JAVA_HOME:
        env["JAVA_HOME"] = AUDIVERIS_JAVA_HOME

    with tempfile.TemporaryDirectory(prefix="clef_aud_") as temp_dir:
        out_dir = Path(temp_dir)
        try:
            result = subprocess.run(
                [str(AUDIVERIS_CMD), "-batch", "-export", "-output", str(out_dir), "--", str(image_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return None, None, "Audiveris timed out while reading the score"

        grades = None
        omr_files = sorted(out_dir.rglob("*.omr"))
        if omr_files:
            grades = parse_omr_grades(omr_files[0])

        xml_text = _extract_musicxml(out_dir)
        if not xml_text:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else "Audiveris produced no MusicXML"
            return None, grades, f"Audiveris failed: {tail}"
        return xml_text, grades, ""


def analyze_image(image_path: Path, timeout: int = 300) -> dict:
    """High-level entry point used by the server.

    Returns a dict with notes, the raw MusicXML, the key signature, and an error
    string when reading failed.
    """
    xml_text, grades, error = run_audiveris(image_path, timeout=timeout)
    if not xml_text:
        return {"success": False, "notes": [], "musicxml": "", "key_fifths": None,
                "confidence": None, "grades": grades, "decision_path": [], "error": error}

    tokens, key_fifths = musicxml_to_tokens(xml_text)
    ok, reason, decision_path = assess_confidence(xml_text, tokens, grades)
    confidence = grades.get("mean_ctx") if grades and grades.get("head_count") else None

    accepted = ok and bool(tokens)
    return {
        "success": accepted,
        "notes": tokens if accepted else [],
        "musicxml": xml_text,
        "key_fifths": key_fifths,
        "confidence": confidence,
        "grades": grades,
        "decision_path": decision_path,
        "gate_source": GATE_SOURCE,
        "gate_thresholds": gate_threshold_info(),
        "error": "" if accepted else (
            f"Audiveris read rejected (low confidence): {reason}" if reason
            else "Audiveris ran but found no pitched notes"
        ),
    }
