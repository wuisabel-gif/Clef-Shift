"""Run the Audiveris OMR engine as a subprocess and turn its MusicXML output
into note tokens the rest of Clef Shift understands.

Audiveris is a mature open-source optical music recognition engine. It reads
real engraved scores well — open noteheads, key signatures, accidentals and
rhythm — and exports MusicXML, fast (seconds, not minutes). It is built once via
`gradlew installDist` (see README) and invoked here through its generated
launcher, the same way server.py shells out to tesseract and ghostscript.
"""
from __future__ import annotations

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


def assess_confidence(xml_text: str, tokens: list[str]) -> tuple[bool, str]:
    """Decide whether an Audiveris read is trustworthy. (ok, reason_if_not)."""
    if len(tokens) < MIN_NOTES:
        return False, f"only {len(tokens)} note(s) read"
    midis = [_midi(t) for t in tokens]
    if any(m is None or m < MIDI_LOW or m > MIDI_HIGH for m in midis):
        return False, "notes fall outside a plausible pitch range"
    jumps = [abs(midis[i + 1] - midis[i]) for i in range(len(midis) - 1)]
    if jumps and sum(j > WILD_JUMP_SEMITONES for j in jumps) / len(jumps) >= WILD_JUMP_FRACTION:
        return False, "notes jump erratically (incoherent line)"
    bad, total = _measure_coherence(xml_text)
    if total >= 2 and bad / total > MEASURE_BAD_FRACTION:
        return False, "measures do not add up to the time signature"
    return True, ""

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


def run_audiveris(image_path: Path, timeout: int = 300) -> tuple[Optional[str], str]:
    """Run Audiveris in batch/export mode and return (musicxml_text, error)."""
    if not audiveris_available():
        return None, "Audiveris is not installed"

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
            return None, "Audiveris timed out while reading the score"

        xml_text = _extract_musicxml(out_dir)
        if not xml_text:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else "Audiveris produced no MusicXML"
            return None, f"Audiveris failed: {tail}"
        return xml_text, ""


def analyze_image(image_path: Path, timeout: int = 300) -> dict:
    """High-level entry point used by the server.

    Returns a dict with notes, the raw MusicXML, the key signature, and an error
    string when reading failed.
    """
    xml_text, error = run_audiveris(image_path, timeout=timeout)
    if not xml_text:
        return {"success": False, "notes": [], "musicxml": "", "key_fifths": None, "error": error}

    tokens, key_fifths = musicxml_to_tokens(xml_text)
    if not tokens:
        return {"success": False, "notes": [], "musicxml": xml_text, "key_fifths": key_fifths,
                "error": "Audiveris ran but found no pitched notes"}

    ok, reason = assess_confidence(xml_text, tokens)
    if not ok:
        # Reject an incoherent read rather than emit likely-garbage notes.
        return {"success": False, "notes": [], "musicxml": xml_text, "key_fifths": key_fifths,
                "error": f"Audiveris read rejected as low-confidence: {reason}"}

    return {
        "success": True,
        "notes": tokens,
        "musicxml": xml_text,
        "key_fifths": key_fifths,
        "error": "",
    }
