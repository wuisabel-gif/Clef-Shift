#!/usr/bin/env python3
"""Run Audiveris on every corpus image, compare its read to the known ground
truth, label it, and record the gate features.

Comparison is on MIDI pitch (spelling-agnostic, so Db vs C# doesn't matter),
via normalized edit distance. A read is labeled should_accept=True when it
agrees with the ground truth at >= A_GOOD. The result is train/data/dataset.jsonl
-- the real data the gate's thresholds get calibrated against.

Run: python3 train/collect.py   (slow: Audiveris is ~10-20s per image)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(__file__).resolve().parent / "data"

from audiveris_pipeline import (  # noqa: E402
    run_audiveris, _midi, _measure_coherence, WILD_JUMP_SEMITONES, GRADE_HEAD_FLOOR,
)
from score_pipeline import musicxml_to_tokens  # noqa: E402

A_GOOD = 0.85  # agreement at/above this => read is correct => the gate SHOULD accept it


def edit_distance(a: list, b: list) -> int:
    n, m = len(a), len(b)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, m + 1):
            prev, dp[j] = dp[j], min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
    return dp[m]


def agreement(gt: list, aud: list) -> float:
    if not gt and not aud:
        return 1.0
    if not gt or not aud:
        return 0.0
    return 1.0 - edit_distance(gt, aud) / max(len(gt), len(aud))


def features(xml: str, tokens: list[str], grades: dict | None) -> dict:
    midis = [m for m in (_midi(t) for t in tokens) if m is not None]
    jumps = [abs(midis[i + 1] - midis[i]) for i in range(len(midis) - 1)]
    wild = (sum(j > WILD_JUMP_SEMITONES for j in jumps) / len(jumps)) if jumps else 0.0
    bad, total = _measure_coherence(xml)
    has_grades = bool(grades and grades.get("head_count"))
    return {
        "note_count": len(tokens),
        "wild_frac": round(wild, 3),
        "measures_bad_frac": round(bad / total, 3) if total else 0.0,
        "measures_total": total,
        "mean_ctx": grades["mean_ctx"] if has_grades else None,
        "min_ctx": grades["min_ctx"] if has_grades else None,
        "head_count": grades["head_count"] if has_grades else None,
        "weak_frac": round(
            sum(1 for h in grades["heads"] if h["ctx"] < GRADE_HEAD_FLOOR) / grades["head_count"], 3
        ) if has_grades else None,
    }


def _meta(item: dict) -> dict:
    return {"image": item["image"], "piece": item["piece"], "quality": item["quality"],
            "gt": item["gt_tokens"]}


def main() -> None:
    manifest = json.loads((DATA / "manifest.json").read_text())
    rows = []
    for item in manifest:
        xml, grades, err = run_audiveris(Path(item["image"]))
        if not xml:
            rows.append({**_meta(item), "audiveris_ok": False, "notes": [], "agreement": 0.0,
                         "should_accept": False, "features": None, "note": err[:80]})
            print(f'{item["piece"]:8} {item["quality"]:5} -> NO OUTPUT')
            continue
        tokens, _key = musicxml_to_tokens(xml)
        aud_midi = [_midi(t) for t in tokens]
        agr = agreement(item["gt_midi"], aud_midi)
        feat = features(xml, tokens, grades)
        rows.append({**_meta(item), "audiveris_ok": True, "notes": tokens, "agreement": round(agr, 3),
                     "should_accept": agr >= A_GOOD, "features": feat})
        print(f'{item["piece"]:8} {item["quality"]:5} -> agr={agr:.2f} notes={len(tokens):2} '
              f'mean_ctx={feat["mean_ctx"]} meas_bad={feat["measures_bad_frac"]} '
              f'good={agr >= A_GOOD}')
    (DATA / "dataset.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(f'\nwrote {len(rows)} rows -> {DATA / "dataset.jsonl"}')


if __name__ == "__main__":
    main()
