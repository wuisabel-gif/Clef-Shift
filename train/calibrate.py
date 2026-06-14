#!/usr/bin/env python3
"""Calibrate the Audiveris confidence-gate thresholds against the labeled data.

Honesty-first objective: find a `mean_ctx >= T AND measures_bad_frac <= M` rule
that NEVER accepts a bad read if possible, then accepts as many good reads as it
can. Reports the confusion outcome and writes train/data/gate_params.json, which
assess_confidence() can load instead of the hand-set constants.

Run: python3 train/calibrate.py
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def main() -> None:
    rows = [json.loads(line) for line in (DATA / "dataset.jsonl").read_text().splitlines() if line.strip()]
    graded = [r for r in rows
              if r.get("audiveris_ok") and r.get("features") and r["features"].get("mean_ctx") is not None]
    if not graded:
        print("No graded reads to calibrate on (Audiveris produced no usable reads).")
        return

    goods = [r for r in graded if r["should_accept"]]
    bads = [r for r in graded if not r["should_accept"]]
    print(f"graded reads: {len(graded)}  (correct={len(goods)}, wrong={len(bads)})")
    for r in graded:
        f = r["features"]
        print(f'  {r["piece"]:8} {r["quality"]:5} agr={r["agreement"]:.2f} '
              f'mean_ctx={f["mean_ctx"]:.2f} meas_bad={f["measures_bad_frac"]:.2f} '
              f'{"GOOD" if r["should_accept"] else "BAD"}')

    ctx_values = sorted({round(r["features"]["mean_ctx"], 3) for r in graded})
    candidates_T = [0.0] + [c - 0.001 for c in ctx_values] + [1.01]
    candidates_M = [0.0, 0.25, 0.5, 0.75, 1.01]

    best = None
    for T in candidates_T:
        for M in candidates_M:
            def accepts(r):
                return r["features"]["mean_ctx"] >= T and r["features"]["measures_bad_frac"] <= M
            tp = sum(1 for r in goods if accepts(r))
            fp = sum(1 for r in bads if accepts(r))
            fn = sum(1 for r in goods if not accepts(r))
            # prefer: zero false-accepts, then most good accepted, then fewest good missed
            score = (fp == 0, tp, -fn)
            if best is None or score > best[0]:
                best = (score, T, M, tp, fp, fn)

    _, T, M, tp, fp, fn = best
    print(f"\nchosen rule: mean_ctx >= {T:.3f}  AND  measures_bad_frac <= {M}")
    print(f"  accepts {tp}/{len(goods)} correct reads")
    print(f"  accepts {fp}/{len(bads)} wrong reads   <-- honesty metric (want 0)")
    params = {
        "CTX_MEAN_MIN": round(T, 3),
        "MEASURE_BAD_FRACTION": M,
        "calibrated_on": len(graded),
        "accepts_correct": f"{tp}/{len(goods)}",
        "accepts_wrong": f"{fp}/{len(bads)}",
    }
    (DATA / "gate_params.json").write_text(json.dumps(params, indent=2))
    print("wrote", DATA / "gate_params.json")


if __name__ == "__main__":
    main()
