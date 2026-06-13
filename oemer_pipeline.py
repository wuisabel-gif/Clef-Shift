"""Run the oemer deep-learning OMR engine (isolated in .venv-oemer) and turn its
MusicXML output into note tokens the rest of Clef Shift already understands.

oemer reads real engraved scores far better than the in-house heuristic in
omr_pipeline.py: it recognises open noteheads, key signatures, accidentals, and
rhythm. It is heavy (onnxruntime + model checkpoints), so it lives in its own
virtualenv and is invoked as a subprocess, the same way server.py shells out to
tesseract and ghostscript.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
OEMER_PYTHON = ROOT / ".venv-oemer" / "bin" / "python"

# MusicXML <alter> -> accidental suffix used by the rest of the app.
ALTER_TO_ACC = {0: "", 1: "#", -1: "b", 2: "##", -2: "bb"}

# oemer hard-codes CoreMLExecutionProvider first, which fails on Apple Silicon
# ("Unable to compute the prediction using a neural network model"). We launch
# oemer through this bootstrap so onnxruntime is pinned to the CPU provider
# before any model loads. Done here rather than by editing the package so it
# survives reinstalls.
_BOOTSTRAP = (
    "import sys, onnxruntime as rt;"
    "_o = rt.InferenceSession;"
    "rt.InferenceSession = lambda p, *a, **k: _o(p, *a, **{**k, 'providers': ['CPUExecutionProvider']});"
    "from oemer.ete import main;"
    "sys.argv = ['oemer'] + sys.argv[1:];"
    "sys.exit(main())"
)


def oemer_available() -> bool:
    """True when the isolated oemer install is present."""
    return OEMER_PYTHON.exists()


def run_oemer(image_path: Path, timeout: int = 600) -> tuple[Optional[str], str]:
    """Run oemer on an image and return (musicxml_text, error_message).

    On the very first call oemer downloads its model checkpoints, so the first
    run can take a while; that is why the timeout is generous.
    """
    if not oemer_available():
        return None, "oemer is not installed"

    with tempfile.TemporaryDirectory(prefix="clef_oemer_") as temp_dir:
        work = Path(temp_dir)
        # Copy the image in so oemer's output lands in our temp dir, not next to
        # the caller's file.
        local_image = work / image_path.name
        shutil.copyfile(image_path, local_image)

        try:
            result = subprocess.run(
                [str(OEMER_PYTHON), "-c", _BOOTSTRAP, local_image.name],
                cwd=str(work),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None, "oemer timed out while reading the score"

        produced = sorted(work.glob("*.musicxml")) + sorted(work.glob("*.xml"))
        if not produced:
            detail = (result.stderr or result.stdout or "").strip()
            tail = detail.splitlines()[-1] if detail else "oemer produced no MusicXML"
            return None, f"oemer failed: {tail}"

        return produced[0].read_text(encoding="utf-8", errors="ignore"), ""


def musicxml_to_tokens(xml_text: str) -> tuple[list[str], Optional[int]]:
    """Parse MusicXML into pitch tokens (e.g. "Bb4") and the key signature fifths.

    Pitch tokens carry the *sounding* accidental, because MusicXML's <alter>
    already folds in the key signature.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], None

    # Strip any namespace so plain tag lookups work.
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    key_fifths: Optional[int] = None
    fifths_el = root.find(".//attributes/key/fifths")
    if fifths_el is not None and (fifths_el.text or "").strip().lstrip("-").isdigit():
        key_fifths = int(fifths_el.text.strip())

    tokens: list[str] = []
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue
        # Skip the lower notes of chords so we read one melodic line.
        if note.find("chord") is not None:
            continue
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step = (pitch.findtext("step") or "").strip().upper()
        octave = (pitch.findtext("octave") or "").strip()
        alter_text = (pitch.findtext("alter") or "0").strip()
        try:
            alter = int(float(alter_text))
        except ValueError:
            alter = 0
        if step not in "ABCDEFG" or not octave.lstrip("-").isdigit():
            continue
        tokens.append(f"{step}{ALTER_TO_ACC.get(alter, '')}{octave}")

    return tokens, key_fifths


def analyze_image(image_path: Path, timeout: int = 600) -> dict:
    """High-level entry point used by the server.

    Returns a dict with notes, the raw MusicXML, the key signature, and an error
    string when reading failed.
    """
    xml_text, error = run_oemer(image_path, timeout=timeout)
    if not xml_text:
        return {"success": False, "notes": [], "musicxml": "", "key_fifths": None, "error": error}

    tokens, key_fifths = musicxml_to_tokens(xml_text)
    return {
        "success": bool(tokens),
        "notes": tokens,
        "musicxml": xml_text,
        "key_fifths": key_fifths,
        "error": "" if tokens else "oemer ran but found no pitched notes",
    }
