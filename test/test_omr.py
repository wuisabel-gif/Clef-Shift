#!/usr/bin/env python3
"""Regression tests for the staff-aware OMR detector.

Fixtures are rendered with LilyPond + Ghostscript (see render_fixtures()).
Run:  python3 test/test_omr.py
The committed PNGs under test/fixtures are used if present, so the test runs
without LilyPond installed; pass --render to regenerate them.

Pitches are checked by letter+octave only. Accidentals printed beside a note
are NOT yet folded into the pitch (see omr_pipeline docstring), so F#5 is
expected to read as F5 in these fixtures.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from omr_pipeline import analyze_image  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"

SCALE_LY = r"""
\version "2.24.0"
\paper { oddFooterMarkup=##f oddHeaderMarkup=##f scoreTitleMarkup=##f }
\header { tagline=##f }
\score { \new Staff { \clef treble \time 4/4
  g'4 a'4 b'4 c''4 | d''4 e''4 fis''4 g''4 |
  a''4 b''4 c'''4 b''4 | a''4 g''4 fis''4 e''4 |
} \layout {} }
"""

MULTI_LY = r"""
\version "2.24.0"
\paper { oddFooterMarkup=##f oddHeaderMarkup=##f scoreTitleMarkup=##f ragged-right=##f line-width=14\cm }
\header { tagline=##f }
\score { \new Staff { \clef treble \time 4/4
  c'8 d'8 e'8 f'8 g'8 a'8 b'8 c''8 | d''4 e''4 f''4 g''4 \break
  a'4 b'4 c''4 d''4 | e''8 d''8 c''8 b'8 a'8 g'8 f'8 e'8 |
} \layout {} }
"""

# Expected letter+octave (F#->F since accidentals are not read yet).
SCALE_EXPECTED = ["G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5",
                  "A5", "B5", "C6", "B5", "A5", "G5", "F5", "E5"]
MULTI_EXPECTED = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5",
                  "A4", "B4", "C5", "D5", "E5", "D5", "C5", "B4", "A4", "G4", "F4", "E4"]


def render_fixtures() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    for name, src in (("scale", SCALE_LY), ("multi", MULTI_LY)):
        ly = FIX / f"{name}.ly"
        ly.write_text(src)
        subprocess.run(["lilypond", "-o", str(FIX / name), str(ly)], check=True,
                       capture_output=True)
        subprocess.run(["gs", "-sDEVICE=png16m", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                        "-r200", "-dFirstPage=1", "-dLastPage=1",
                        f"-sOutputFile={FIX / (name + '.png')}", str(FIX / f"{name}.pdf")],
                       check=True, capture_output=True)
    # blank + text-only (no staff) negative fixtures
    from PIL import Image, ImageDraw
    Image.new("L", (800, 600), 255).save(FIX / "blank.png")
    img = Image.new("L", (1200, 400), 255)
    d = ImageDraw.Draw(img)
    d.text((40, 60), "Violin Sonata in A", fill=0)
    d.text((40, 160), "Allegro moderato — no staff lines here", fill=0)
    img.save(FIX / "textonly.png")


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    if "--render" in sys.argv or not (FIX / "scale.png").exists():
        print("Rendering fixtures with LilyPond...")
        render_fixtures()

    passed = True
    print("Detecting notes from rendered notation:")

    r = analyze_image(FIX / "scale.png", "treble")
    passed &= check("scale.png pitches", r.notes == SCALE_EXPECTED,
                    f"{len(r.notes)} notes" if r.notes == SCALE_EXPECTED else f"got {r.notes}")
    passed &= check("scale.png one staff", r.staff_count == 1)

    r = analyze_image(FIX / "multi.png", "treble")
    passed &= check("multi.png pitches", r.notes == MULTI_EXPECTED,
                    f"{len(r.notes)} notes" if r.notes == MULTI_EXPECTED else f"got {r.notes}")
    passed &= check("multi.png two staves", r.staff_count == 2, f"{r.staff_count} staves")

    r = analyze_image(FIX / "textonly.png", "treble")
    passed &= check("textonly.png fails honestly", not r.success and not r.notes, r.reason)

    r = analyze_image(FIX / "blank.png", "treble")
    passed &= check("blank.png fails honestly", not r.success and not r.notes, r.reason)

    print("\nRESULT:", "ALL PASS" if passed else "FAILURES")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
