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
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from score_pipeline import musicxml_to_tokens

ROOT = Path(__file__).resolve().parent

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
    return {
        "success": bool(tokens),
        "notes": tokens,
        "musicxml": xml_text,
        "key_fifths": key_fifths,
        "error": "" if tokens else "Audiveris ran but found no pitched notes",
    }
