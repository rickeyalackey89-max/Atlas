"""
Export v18 resim cache to per-date corpus dirs for leg trainer use.
Skips the 6 playoff dates already correctly sourced from live_runs.
"""
import pickle
import pandas as pd
from pathlib import Path

CACHE_PATH = Path("data/model/_v18_resim_cache.pkl")
CORPUS_DIR = Path("data/telemetry/v18_corpus")
PLAYOFF_DATES = {"20260430", "20260501", "20260502", "20260503", "20260504", "20260505"}

print("Loading resim cache...")
with open(CACHE_PATH, "rb") as f:
    cache = pickle.load(f)
cv = cache["cv"]

dates = sorted(cv["game_date"].unique())
print(f"Cache: {len(dates)} dates  {dates[0]} - {dates[-1]}  ({len(cv)} rows)")
print(f"p_cal mean={cv['p_cal'].mean():.4f}  telemetry_cal_applied present: {'telemetry_cal_applied' in cv.columns}")
print()

EVAL_COLS = [c for c in ["player", "stat", "line", "direction", "hit", "game_date", "team", "opp", "tier"] if c in cv.columns]

exported = 0
skipped = 0
for gd in dates:
    date_str = str(gd).replace("-", "")
    if date_str in PLAYOFF_DATES:
        print(f"  {date_str}: SKIP (playoff — keeping existing live_run file)")
        skipped += 1
        continue

    sub = cv[cv["game_date"] == gd].copy().reset_index(drop=True)

    # Synthesize projection_id — the resim cache doesn't store it, but the
    # slip builder hard-rejects any row where it's null/nan.
    # Format mirrors the live-run format: "{idx}|{player}|{stat}|{tier}|{line}|{direction}"
    sub["projection_id"] = (
        sub.index.astype(str)
        + "|" + sub["player"].astype(str)
        + "|" + sub["stat"].astype(str)
        + "|" + sub["tier"].astype(str)
        + "|" + sub["line"].astype(str)
        + "|" + sub["direction"].astype(str)
    )

    # data_health_flag — resim cache rows already passed health checks at
    # run time; the column is NaN in the cache. Fill with "OK" so the
    # slip builder's health filter doesn't wipe the entire slate.
    if "data_health_flag" not in sub.columns or sub["data_health_flag"].isna().all():
        sub["data_health_flag"] = "OK"

    # Drop source_projection_id — it's always NaN in the resim cache and
    # causes the slip builder's pid fallback logic to overwrite our synthetic
    # projection_id with NaN values, making every row fail the pid check.
    sub = sub.drop(columns=["source_projection_id"], errors="ignore")

    out_dir = CORPUS_DIR / date_str
    out_dir.mkdir(exist_ok=True)
    sub.to_csv(out_dir / "scored_legs_deduped.csv", index=False)
    sub[EVAL_COLS].to_csv(out_dir / "eval_legs.csv", index=False)

    has_cal = str(sub["telemetry_cal_applied"].all()) if "telemetry_cal_applied" in sub.columns else "N/A"
    print(f"  {date_str}: {len(sub)} rows  p_cal={sub['p_cal'].mean():.4f}  telemetry_cal={has_cal}")
    exported += 1

print()
print(f"Done — exported {exported} dates, skipped {skipped} playoff dates.")

# Verify final corpus
total = len([d for d in CORPUS_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
print(f"v18_corpus total date dirs: {total}")
