#!/usr/bin/env python3
"""Acceptance test for the Swan Lake fixture.

A metadata-rich violin page (title, composer, "Violin Solo", tempo, chord
symbols, dynamics, bar numbers) must yield REAL staff notes and never
hallucinate from any of that non-note text. Honesty rule: a partial-but-real
read OR no notes is acceptable; a confident fake short sequence is not.

Image resolution order:
  1) SWAN_LAKE_IMAGE env var
  2) test/fixtures/swan_lake_scene_page_1.png   (the real Tchaikovsky page)
  3) test/fixtures/swan_lake_style.png          (reproduction with the same
     hazards -- NOT the exact page; used only until the real one is provided)
If none exist, the test SKIPS with instructions.

Run: python3 test/test_swan_lake.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "test" / "fixtures"

from audiveris_pipeline import analyze_image as audiveris_analyze  # noqa: E402
from omr_pipeline import analyze_image as heuristic_analyze  # noqa: E402

# The exact metadata-hallucination pattern this fixture must never reproduce.
KNOWN_BAD = ["Ab4", "Bb3", "C4", "C#4", "C#4", "Ab4", "Bb3"]
MIN_NOTES = 20  # a multi-system page yields many notes, not a tiny cluster


def find_image() -> tuple[Path | None, bool]:
    env = os.environ.get("SWAN_LAKE_IMAGE")
    candidates = [env, FIX / "swan_lake_scene_page_1.png", FIX / "swan_lake_style.png"]
    for c in candidates:
        if c and Path(c).exists():
            p = Path(c)
            return p, ("scene_page" in p.name or c == env)
    return None, False


def main() -> int:
    img, _ = find_image()
    if not img:
        print("SKIP: no Swan Lake image found. Drop the real page at\n"
              "      test/fixtures/swan_lake_scene_page_1.png  (or set SWAN_LAKE_IMAGE).")
        return 0

    is_real = "scene_page" in img.name
    label = "REAL Tchaikovsky page" if is_real else "REPRODUCTION (swan_lake_style, not the exact page)"
    print(f"Swan Lake fixture on: {img.name}   [{label}]")

    a = audiveris_analyze(img)
    # Heuristic run also produces the requested debug overlays.
    h = heuristic_analyze(img, "treble", debug=True, debug_dir=ROOT / "debug" / "swan_lake")

    notes = a["notes"] if a["success"] else h.notes
    engine = "audiveris" if a["success"] else ("heuristic" if h.notes else "none")
    print(f"  audiveris: success={a['success']} notes={len(a['notes'])} "
          f"key_fifths={a['key_fifths']} confidence={a['confidence']}")
    print(f"  heuristic: success={h.success} notes={len(h.notes)} systems={h.staff_count}")
    print(f"  -> using {engine}: {len(notes)} notes; overlays in debug/swan_lake/")

    passed = True

    def chk(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        passed = passed and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    chk("not the known metadata-hallucination pattern", notes != KNOWN_BAD)

    if notes:
        chk("many real notes, not a short hallucinated list", len(notes) >= MIN_NOTES, f"{len(notes)} notes")
        if a["success"] and a["key_fifths"] is not None:
            chk("treble source read with 2 sharps", a["key_fifths"] == 2, f"fifths={a['key_fifths']}")
        if h.staff_count:
            chk("notes found across multiple systems", h.staff_count >= 2, f"{h.staff_count} systems")
    else:
        # Per the fixture's pass/fail rule, honest "no notes" is acceptable.
        chk("returned no notes (honest) rather than metadata garbage", True,
            "no confident read -> nothing emitted")

    print("RESULT:", "ALL PASS" if passed else "FAILURES")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
