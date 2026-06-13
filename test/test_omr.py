#!/usr/bin/env python3
"""Honesty-contract tests for the heuristic OMR fallback.

The fallback's job is deliberately narrow: read high-confidence *solid*
noteheads, reject the clef/key/time/tempo/beam metadata cleanly, and return NO
notes when uncertain. Open (half/whole) noteheads, accidentals and full rhythm
are the Audiveris path's responsibility, not the fallback's -- so these tests
assert the contract, not exact transcription.

Fixtures are rendered with LilyPond + Ghostscript; committed PNGs under
test/fixtures are used if present, so this runs without LilyPond. Pass --render
to regenerate them.  Run:  python3 test/test_omr.py
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

# A staff with a full metadata header (instrument name, clef, 4-flat key sig,
# time sig, tempo mark) plus beamed solid notes and open sustained notes -- the
# regression case for "do not hallucinate notes from the metadata region".
META_LY = r"""
\version "2.24.0"
\paper { oddFooterMarkup=##f oddHeaderMarkup=##f scoreTitleMarkup=##f paper-width=11\in line-width=10\in indent=0 }
\header { tagline=##f }
\score { \new Staff \with { instrumentName = "Flauta" } {
  \clef treble \key aes \major \time 4/4 \tempo 4 = 101
  r8 aes'8[ c''8 ees''8] des''2 | ees''1 |
} \layout {} }
"""


def render_fixtures() -> None:
    from PIL import Image, ImageChops, ImageDraw
    FIX.mkdir(parents=True, exist_ok=True)
    for name, src, autocrop in (("scale", SCALE_LY, False),
                                ("multi", MULTI_LY, False),
                                ("meta", META_LY, True)):
        ly = FIX / f"{name}.ly"
        ly.write_text(src)
        subprocess.run(["lilypond", "-o", str(FIX / name), str(ly)], check=True, capture_output=True)
        out = FIX / f"{name}.png"
        subprocess.run(["gs", "-sDEVICE=png16m", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                        "-r150" if autocrop else "-r200", "-dFirstPage=1", "-dLastPage=1",
                        f"-sOutputFile={out}", str(FIX / f"{name}.pdf")], check=True, capture_output=True)
        if autocrop:  # tighten to a single-line strip like a real scan
            im = Image.open(out).convert("RGB")
            l, t, r, b = ImageChops.invert(im.convert("L")).getbbox()
            im.crop((max(0, l - 24), max(0, t - 24), r + 24, b + 24)).save(out)
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

    print("Honesty: blank / text-only inputs must return no notes")
    for neg in ("blank", "textonly"):
        r = analyze_image(FIX / f"{neg}.png", "treble")
        passed &= check(f"{neg}.png returns no notes", not r.success and not r.notes, r.reason)

    print("Metadata: the flute fixture must not hallucinate notes from clef/key/time/tempo")
    r = analyze_image(FIX / "meta.png", "treble")
    meta_x = (r.detail.get("metadata_x") or [0])[0]
    xs = [a["x"] for a in r.detail.get("accepted_notes", [])]
    passed &= check("meta.png no notes in metadata zone", all(x > meta_x for x in xs),
                    f"content_start={meta_x}, note xs={[round(x) for x in xs]}")
    passed &= check("meta.png finds the real beamed notes", r.notes == ["A4", "C5", "E5"],
                    f"got {r.notes}")

    print("Detection: clean scores yield in-staff solid noteheads")
    r = analyze_image(FIX / "scale.png", "treble")
    passed &= check("scale.png one staff, finds notes", r.staff_count == 1 and len(r.notes) >= 12,
                    f"{len(r.notes)} notes, {r.staff_count} staff")
    r = analyze_image(FIX / "multi.png", "treble")
    passed &= check("multi.png two staves, finds notes", r.staff_count == 2 and len(r.notes) >= 18,
                    f"{len(r.notes)} notes, {r.staff_count} staves")

    print("Audiveris confidence gate: trust coherent reads, reject garbage")
    passed &= test_confidence_gate()

    print("\nRESULT:", "ALL PASS" if passed else "FAILURES")
    return 0 if passed else 1


def test_confidence_gate() -> bool:
    """Unit-test the Audiveris read sanity check (no engine/image needed)."""
    from audiveris_pipeline import assess_confidence

    # Two coherent 4/4 measures that add up -> trusted.
    good_xml = """<score-partwise><part>
    <measure number="1">
      <attributes><divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>A</step><alter>-1</alter><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration></note>
      <note><pitch><step>E</step><alter>-1</alter><octave>5</octave></pitch><duration>1</duration></note>
      <note><pitch><step>D</step><alter>-1</alter><octave>5</octave></pitch><duration>1</duration></note>
    </measure>
    <measure number="2">
      <note><pitch><step>E</step><alter>-1</alter><octave>5</octave></pitch><duration>4</duration></note>
    </measure></part></score-partwise>"""
    # Same notes, but both measures are badly over-filled (durations don't add up).
    bad_xml = good_xml.replace("<duration>1</duration>", "<duration>8</duration>") \
                      .replace("<duration>4</duration>", "<duration>9</duration>")

    ok = True
    a, _ = assess_confidence(good_xml, ["Ab4", "C5", "Eb5", "Db5", "Eb5"])
    ok &= check("trusts a coherent read", a)
    b, why = assess_confidence("", ["C5"])
    ok &= check("rejects too-few notes", not b, why)
    b, why = assess_confidence("", ["C5", "C12", "C5"])
    ok &= check("rejects out-of-range notes", not b, why)
    b, why = assess_confidence("", ["C2", "C7", "C2", "C7"])
    ok &= check("rejects erratic leaps (scattered)", not b, why)
    b, why = assess_confidence(bad_xml, ["Ab4", "C5", "Eb5", "Db5", "Eb5"])
    ok &= check("rejects measures that don't add up", not b, why)
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
