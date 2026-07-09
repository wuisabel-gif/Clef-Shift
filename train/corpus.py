#!/usr/bin/env python3
"""Generate a labeled corpus of score images for calibrating the OMR gate.

Each piece's notes are KNOWN (we wrote the LilyPond), so the ground truth is
exact -- no fallible reader needed. Each piece is rendered at several quality
levels (clean -> degraded) to push Audiveris across its accuracy range, so the
dataset contains both good and bad reads, each with a correct label.

Output: train/data/images/*.{png,jpg} and train/data/manifest.json
Run:    python3 train/corpus.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(__file__).resolve().parent / "data"
IMG = DATA / "images"

# (name, LilyPond body, ground-truth sounding pitch tokens in order).
# Covers: C major, a flat key, a sharp key, a pickup/anacrusis measure, open
# (half/whole) noteheads, and beams with rests -- so the calibration set is not
# all clean quarter-note lines in one key.
PIECES = [
    ("cmajor",
     r"\clef treble \time 4/4 c'4 d'4 e'4 f'4 | g'4 a'4 b'4 c''4 |",
     ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]),
    ("fmajor",  # 1 flat (Bb)
     r"\key f \major \clef treble \time 4/4 f'4 g'4 a'4 bes'4 | c''4 d''4 e''4 f''4 |",
     ["F4", "G4", "A4", "Bb4", "C5", "D5", "E5", "F5"]),
    ("dmajor",  # 2 sharps (F#, C#)
     r"\key d \major \clef treble \time 4/4 d'4 e'4 fis'4 g'4 | a'4 b'4 cis''4 d''4 |",
     ["D4", "E4", "F#4", "G4", "A4", "B4", "C#5", "D5"]),
    ("triad",
     r"\clef treble \time 4/4 c'4 e'4 g'4 c''4 | g'4 e'4 c'4 r4 |",
     ["C4", "E4", "G4", "C5", "G4", "E4", "C4"]),
    ("mixed",  # a rest
     r"\clef treble \time 4/4 r4 c'8 d'8 e'4 f'4 | g'2 a'4 b'4 |",
     ["C4", "D4", "E4", "F4", "G4", "A4", "B4"]),
    ("pickup",  # anacrusis: first bar is intentionally short
     r"\clef treble \time 4/4 \partial 4 g'4 | c''2 b'4 a'4 | g'4 f'4 e'4 d'4 |",
     ["G4", "C5", "B4", "A4", "G4", "F4", "E4", "D4"]),
    ("sustained",  # open noteheads: whole + half notes
     r"\clef treble \time 4/4 c'1 | g'2 e'2 |",
     ["C4", "G4", "E4"]),
    ("beams_rests",  # beamed eighths interrupted by rests
     r"\clef treble \time 4/4 c'8 d'8 e'8 f'8 r8 g'8 a'8 b'8 | c''4 r4 g'4 e'4 |",
     ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "G4", "E4"]),
]

LY_TMPL = (
    '\\version "2.24.0"\n'
    "\\paper { oddFooterMarkup=##f oddHeaderMarkup=##f scoreTitleMarkup=##f }\n"
    "\\header { tagline=##f }\n"
    "\\score { \\new Staff { __BODY__ } \\layout {} }\n"
)


def _render_base(name: str, body: str) -> Image.Image:
    DATA.mkdir(parents=True, exist_ok=True)
    ly = DATA / f"{name}.ly"
    ly.write_text(LY_TMPL.replace("__BODY__", body))
    # -dno-point-and-click: otherwise the PDF embeds absolute source paths
    subprocess.run(["lilypond", "-dno-point-and-click", "-o", str(DATA / name), str(ly)],
                   check=True, capture_output=True)
    base = DATA / f"{name}_base.png"
    subprocess.run(["gs", "-sDEVICE=png16m", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-r200",
                    "-dFirstPage=1", "-dLastPage=1", f"-sOutputFile={base}", str(DATA / f"{name}.pdf")],
                   check=True, capture_output=True)
    return Image.open(base).convert("RGB")


def _skew(img: Image.Image, angle: float = 1.6) -> Image.Image:
    """Slight rotation, as if the page was scanned/photographed crooked."""
    return img.rotate(angle, expand=True, resample=Image.BICUBIC, fillcolor=(255, 255, 255))


def _noise(img: Image.Image, sigma: float = 22.0) -> Image.Image:
    """Sensor/scan grain."""
    arr = np.asarray(img).astype(np.float32)
    arr += np.random.default_rng(0).normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _low_contrast(img: Image.Image) -> Image.Image:
    """Faint print / washed-out photocopy: lower contrast + slight brightening."""
    out = ImageEnhance.Contrast(img).enhance(0.55)
    return ImageEnhance.Brightness(out).enhance(1.12)


def _variants(base: Image.Image) -> list[tuple[str, Image.Image, str]]:
    w, h = base.width, base.height
    small = base.resize((int(w * 0.6), int(h * 0.6)))
    return [
        ("clean", base, "png"),
        ("blur", base.filter(ImageFilter.GaussianBlur(1.2)), "png"),
        ("jpeg", base.resize((int(w * 0.7), int(h * 0.7))), "jpg"),     # compression artifacts
        ("skew", _skew(base), "png"),                                    # crooked scan
        ("noise", _noise(small), "png"),                                 # grain + downscale
        ("lowcontrast", _low_contrast(small), "png"),                    # faint photocopy
        ("photo", _noise(_skew(_low_contrast(small), 1.0), 14.0), "jpg"),  # combined phone-photo
    ]


def render_corpus() -> None:
    from audiveris_pipeline import _midi
    IMG.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, body, gt in PIECES:
        base = _render_base(name, body)
        gt_midi = [_midi(t) for t in gt]
        for quality, im, ext in _variants(base):
            path = IMG / f"{name}_{quality}.{ext}"
            im.save(path, quality=35) if ext == "jpg" else im.save(path)
            manifest.append({"image": str(path.relative_to(ROOT)), "piece": name, "quality": quality,
                             "gt_tokens": gt, "gt_midi": gt_midi})
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"rendered {len(manifest)} images across {len(PIECES)} pieces "
          f"({len(manifest) // len(PIECES)} quality levels each) -> {DATA / 'manifest.json'}")


if __name__ == "__main__":
    render_corpus()
