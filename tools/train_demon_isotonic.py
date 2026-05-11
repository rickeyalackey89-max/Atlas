#!/usr/bin/env python
"""
DEMON Isotonic Calibrator Trainer
==================================
Trains two isotonic curves from the v17 corpus CSVs:
  1. Global curve  : all non-DEMON legs  (GOBLIN + STANDARD), p_adj as x-axis
  2. DEMON curve   : DEMON-tier legs only, p_adj as x-axis

Why p_adj (not p_cal):
  In main.py, apply_calibration_to_column writes to out_col="p_cal" — it never
  touches p_adj.  At the time the calibration runs, scored["p_adj"] still holds
  the raw pre-calibration MC probability.  Using p_adj as the training x-axis
  makes training and inference identical (source_col = "p_adj" in both).

  Using p_cal from the corpus would mean training on the OLD isotonic's output
  (different scale for DEMON legs), causing a distribution mismatch at inference.

Output: data/model/telemetry_calibration.demon_isotonic.json
  - mode: isotonic_hybrid
  - meta.source_col: "p_adj"
  - meta.x/y_thresholds: global non-DEMON curve
  - meta.protected_tier: DEMON
  - meta.protected_calibration: DEMON-specific curve (source_col p_adj)

Usage:
  python tools/train_demon_isotonic.py
  python tools/train_demon_isotonic.py --dry-run   # diagnostics only, no write
  python tools/train_demon_isotonic.py --promote   # also updates active_calibration in config.yaml
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CORPUS_BASE = ROOT / "data" / "telemetry" / "v18_corpus"
OUTPUT_PATH = ROOT / "data" / "model" / "telemetry_calibration.demon_isotonic.json"
CONFIG_PATH = ROOT / "config.yaml"

# Regular-season dates in the v17 corpus
RUN_DATES = [
    "20260209", "20260210", "20260211", "20260212",
    "20260225", "20260226", "20260227", "20260228",
    "20260301", "20260302", "20260303", "20260304",
    "20260305", "20260306", "20260307", "20260308",
    "20260309", "20260310", "20260315", "20260316",
    "20260317", "20260318", "20260319", "20260320",
    "20260321", "20260322", "20260323", "20260324",
    "20260325", "20260326", "20260328", "20260330",
    "20260331", "20260401", "20260402", "20260403",
    "20260404", "20260405", "20260406", "20260407",
    "20260408", "20260409", "20260410", "20260412",
]

# Playoff / extra live run dirs
EXTRA_RUN_DIRS: list[Path] = [
    ROOT / "data" / "output"    / "runs"      / "20260430_182420",
    ROOT / "data" / "telemetry" / "live_runs"  / "20260501_110422",
    ROOT / "data" / "telemetry" / "live_runs"  / "20260502_110546",
]


# ── Corpus loading ─────────────────────────────────────────────────────

def _load_run_dir(run_dir: Path, date: str, rows: list) -> None:
    eval_files   = list(run_dir.rglob("eval_legs.csv"))
    scored_files = list(run_dir.rglob("scored_legs_deduped.csv"))
    if not eval_files or not scored_files:
        return

    eval_df   = pd.read_csv(eval_files[0],   low_memory=False)
    scored_df = pd.read_csv(scored_files[0], low_memory=False)

    if "p_adj" not in scored_df.columns:
        print(f"  [WARN] p_adj missing in {run_dir.name}, skipping")
        return

    # Build truth lookup keyed by (player, line, stat, direction)
    truth: dict[tuple, int] = {}
    for _, row in eval_df.iterrows():
        p = str(row.get("player", "")).strip().lower()
        l = float(row["line"]) if pd.notna(row.get("line")) else 0.0
        s = str(row.get("stat", "")).strip().upper()
        d = str(row.get("direction", "")).strip().lower()
        if pd.notna(row.get("hit")):
            truth[(p, l, s, d)] = int(row["hit"])

    tier_col = "tier" if "tier" in scored_df.columns else None

    for _, row in scored_df.iterrows():
        p  = str(row.get("player", "")).strip().lower()
        l  = float(row["line"]) if pd.notna(row.get("line")) else 0.0
        s  = str(row.get("stat", "")).strip().upper()
        d  = str(row.get("direction", "")).strip().lower()
        pa = float(row["p_adj"]) if pd.notna(row.get("p_adj")) else None
        ti = str(row.get(tier_col, "STANDARD")).strip().upper() if tier_col else "STANDARD"
        if pa is None:
            continue
        key = (p, l, s, d)
        if key in truth:
            rows.append({
                "date": date, "tier": ti, "direction": d,
                "p_adj": pa, "hit": truth[key],
            })


def load_corpus() -> pd.DataFrame:
    rows: list = []
    found = 0
    for date in RUN_DATES:
        run_dir = CORPUS_BASE / date
        if run_dir.exists():
            _load_run_dir(run_dir, date, rows)
            found += 1
    for run_dir in EXTRA_RUN_DIRS:
        if not run_dir.exists():
            print(f"  [WARN] Extra dir not found: {run_dir}")
            continue
        _load_run_dir(run_dir, run_dir.name[:8], rows)
        found += 1
    df = pd.DataFrame(rows)
    df["p_adj"] = pd.to_numeric(df["p_adj"], errors="coerce").clip(0.01, 0.99)
    df["hit"]   = pd.to_numeric(df["hit"],   errors="coerce")
    df = df.dropna(subset=["p_adj", "hit"])
    print(f"  {len(df):,} matched legs from {df['date'].nunique()} dates ({found} dirs scanned)")
    return df


# ── Isotonic fitting ───────────────────────────────────────────────────

def fit_isotonic(
    probs: np.ndarray,
    hits:  np.ndarray,
) -> tuple[list[float], list[float]]:
    ir = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir.fit(probs, hits)
    return ir.X_thresholds_.tolist(), ir.y_thresholds_.tolist()


# ── Diagnostics ────────────────────────────────────────────────────────

def gap_report(
    probs: np.ndarray,
    hits:  np.ndarray,
    cal:   np.ndarray,
    label: str,
) -> float:
    bins = [(0.0, 0.30), (0.30, 0.35), (0.35, 0.40),
            (0.40, 0.45), (0.45, 0.50), (0.50, 0.55),
            (0.55, 0.65), (0.65, 0.80), (0.80, 1.01)]
    print(f"\n  {label}  ({len(probs):,} legs, avg p_adj={probs.mean():.3f}, HR={hits.mean():.3f})")
    print(f"  {'Range':<12} {'N':>7} {'Before':>8} {'After':>8} {'Actual':>8} {'GapB':>7} {'GapA':>7}")
    print("  " + "-" * 61)
    for lo, hi in bins:
        m = (probs >= lo) & (probs < hi)
        n = m.sum()
        if n == 0:
            continue
        b   = float(probs[m].mean())
        a   = float(cal[m].mean())
        act = float(hits[m].mean())
        print(f"  {lo:.2f}-{hi:.2f}  {n:>7,}  {b:>7.3f}  {a:>7.3f}  {act:>7.3f}"
              f"  {act-b:>+7.3f}  {act-a:>+7.3f}")
    brier_b = float(np.mean((probs - hits) ** 2))
    brier_a = float(np.mean((cal   - hits) ** 2))
    print(f"  Brier: {brier_b:.6f} -> {brier_a:.6f}  (delta {brier_a-brier_b:+.6f})")
    return brier_a


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print diagnostics without writing files")
    parser.add_argument("--promote", action="store_true",
                        help="Update active_calibration in config.yaml")
    args = parser.parse_args()

    print("=" * 62)
    print("DEMON Isotonic Trainer  (source_col: p_adj)")
    print("=" * 62)

    print("\nLoading corpus from scored_legs_deduped.csv ...")
    df = load_corpus()

    demon    = df[df["tier"] == "DEMON"]
    nondemon = df[df["tier"] != "DEMON"]

    print(f"\n  DEMON    : {len(demon):>7,}  avg={demon['p_adj'].mean():.3f}  HR={demon['hit'].mean():.3f}")
    print(f"  Non-DEMON: {len(nondemon):>7,}  avg={nondemon['p_adj'].mean():.3f}  HR={nondemon['hit'].mean():.3f}")

    # ── Fit global (non-DEMON) curve ────────────────────────────────
    print("\nFitting global non-DEMON isotonic (p_adj) ...")
    g_prob = nondemon["p_adj"].to_numpy(float)
    g_hit  = nondemon["hit"].to_numpy(float)
    g_x, g_y = fit_isotonic(g_prob, g_hit)
    ir_g = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_g.fit(g_prob, g_hit)
    g_cal = ir_g.predict(g_prob)
    gap_report(g_prob, g_hit, g_cal, "Non-DEMON (Global)")

    # ── Fit DEMON-specific curve ────────────────────────────────────
    print("\nFitting DEMON isotonic (p_adj) ...")
    d_prob = demon["p_adj"].to_numpy(float)
    d_hit  = demon["hit"].to_numpy(float)
    d_x, d_y = fit_isotonic(d_prob, d_hit)
    ir_d = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_d.fit(d_prob, d_hit)
    d_cal = ir_d.predict(d_prob)
    gap_report(d_prob, d_hit, d_cal, "DEMON (Protected)")

    # ── Min-leg-prob impact ─────────────────────────────────────────
    print("\n  === DEMON legs clearing min_leg_prob thresholds ===")
    for thresh in (0.38, 0.40, 0.42, 0.45, 0.50):
        n_pass = int((d_cal >= thresh).sum())
        hr = float(d_hit[d_cal >= thresh].mean()) if n_pass else 0.0
        pct = 100 * n_pass / max(len(d_prob), 1)
        print(f"  p_cal >= {thresh:.2f}: {n_pass:>6,} ({pct:.1f}%)  actual HR: {hr:.3f}")

    if args.dry_run:
        print("\n[DRY RUN] Nothing written.")
        return

    # ── Backup existing file ────────────────────────────────────────
    if OUTPUT_PATH.exists():
        stamp = datetime.now().strftime("%Y%m%d")
        backup = OUTPUT_PATH.with_name(
            OUTPUT_PATH.stem + f"_{stamp}.bak.json"
        )
        shutil.copy2(OUTPUT_PATH, backup)
        print(f"\nBacked up to: {backup.name}")

    # ── Build and write output JSON ─────────────────────────────────
    calibration = {
        "mode": "isotonic_hybrid",
        "candidate": "demon_isotonic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trained_on": {
            "dates": int(df["date"].nunique()),
            "demon_legs": int(len(demon)),
            "nondemon_legs": int(len(nondemon)),
            "source_col": "p_adj",
            "trainer": "train_demon_isotonic.py",
        },
        "meta": {
            "family": "isotonic_hybrid",
            "mix": 1.0,
            "source_col": "p_adj",
            "x_thresholds": g_x,
            "y_thresholds": g_y,
            "protected_tier": "DEMON",
            "protected_calibration": {
                "mode": "isotonic_blend",
                "mix": 1.0,
                "source_col": "p_adj",
                "x_thresholds": d_x,
                "y_thresholds": d_y,
            },
        },
    }

    OUTPUT_PATH.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(f"Saved: {OUTPUT_PATH}")
    print(f"  Global breakpoints: {len(g_x)}  |  DEMON breakpoints: {len(d_x)}")
    print(f"  source_col = p_adj  (training / inference aligned)")

    if args.promote:
        import yaml
        cfg = yaml.safe_load(CONFIG_PATH.read_text())
        tel = cfg.setdefault("telemetry", {})
        old = tel.get("active_calibration", "?")
        tel["active_calibration"] = "demon_isotonic"
        tel["active_calibration_path"] = str(
            OUTPUT_PATH.relative_to(ROOT)
        ).replace("\\", "/")
        CONFIG_PATH.write_text(
            yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
        )
        print(f"Promoted in config.yaml: {old} -> demon_isotonic")
    else:
        print("\nAdd --promote to activate in config.yaml, or set manually:")
        print("  active_calibration: demon_isotonic")


if __name__ == "__main__":
    main()
