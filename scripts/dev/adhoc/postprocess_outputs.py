import os
import glob
import shutil
from dataclasses import dataclass
from typing import Optional, Dict, Tuple

import pandas as pd

OUTPUT_DIR_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "output")


@dataclass
class LatestSet:
    scored_legs: Optional[str]
    scored_legs_deduped: Optional[str]
    rec4: Optional[str]
    rec5: Optional[str]
    rec4_risky: Optional[str]
    rec5_risky: Optional[str]


def _latest_file(pattern: str) -> Optional[str]:
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


def find_latest_outputs(output_dir: str) -> LatestSet:
    return LatestSet(
        scored_legs=_latest_file(os.path.join(output_dir, "scored_legs_*.csv")),
        scored_legs_deduped=_latest_file(os.path.join(output_dir, "scored_legs_deduped_*.csv")),
        rec4=_latest_file(os.path.join(output_dir, "recommended_4leg_*.csv")),
        rec5=_latest_file(os.path.join(output_dir, "recommended_5leg_*.csv")),
        rec4_risky=_latest_file(os.path.join(output_dir, "recommended_4leg_risky_*.csv")),
        rec5_risky=_latest_file(os.path.join(output_dir, "recommended_5leg_risky_*.csv")),
    )


def confidence_bucket(min_p_eff: float, avg_fragility: float, max_same: float) -> str:
    if (min_p_eff >= 0.78) and (avg_fragility <= 0.35) and (max_same <= 2):
        return "SAFE"
    if (min_p_eff >= 0.72) and (avg_fragility <= 0.50) and (max_same <= 3):
        return "AGGRESSIVE"
    return "LOTTO"


def add_confidence_buckets(recommended_csv: str) -> None:
    df = pd.read_csv(recommended_csv)
    need = {"min_p_eff", "avg_fragility", "max_same"}
    if not need.issubset(set(df.columns)):
        return

    def _row_bucket(r):
        try:
            return confidence_bucket(float(r["min_p_eff"]), float(r["avg_fragility"]), float(r["max_same"]))
        except Exception:
            return "LOTTO"

    df["confidence_bucket"] = df.apply(_row_bucket, axis=1)

    cols = list(df.columns)
    if "tier" in cols:
        cols.remove("confidence_bucket")
        idx = cols.index("tier") + 1
        cols.insert(idx, "confidence_bucket")
        df = df[cols]

    df.to_csv(recommended_csv, index=False)


def add_under_direction_bias(scored_csv: str) -> None:
    df = pd.read_csv(scored_csv)
    if "p_eff" not in df.columns or "direction" not in df.columns:
        return

    rate_std = df["rate_std"] if "rate_std" in df.columns else 0.0
    blowout = df["blowout_risk"] if "blowout_risk" in df.columns else 0.0

    rs = pd.to_numeric(rate_std, errors="coerce").fillna(0.0).clip(lower=0.0)
    br = pd.to_numeric(blowout, errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)
    p = pd.to_numeric(df["p_eff"], errors="coerce").fillna(0.0)

    penalty = (rs / (rs + 1.0)).clip(0.0, 1.0) * 0.03
    boost = br * 0.02

    is_under = df["direction"].astype(str).str.upper().eq("UNDER")
    p_biased = p.copy()
    p_biased[is_under] = (p[is_under] - penalty[is_under] + boost[is_under]).clip(0.0, 1.0)

    df["p_eff_biased"] = p_biased
    df.to_csv(scored_csv, index=False)


def clear_folder(folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            os.remove(path)


def copy_into_latest(latest_dir: str, latest: LatestSet) -> Dict[str, str]:
    os.makedirs(latest_dir, exist_ok=True)

    mapping: Dict[str, Tuple[Optional[str], str]] = {
        "scored_legs.csv": (latest.scored_legs, "scored_legs.csv"),
        "scored_legs_deduped.csv": (latest.scored_legs_deduped, "scored_legs_deduped.csv"),

        "recommended_4leg.csv": (latest.rec4, "recommended_4leg.csv"),
        "recommended_5leg.csv": (latest.rec5, "recommended_5leg.csv"),

        # NEW: risky recs
        "recommended_4leg_risky.csv": (latest.rec4_risky, "recommended_4leg_risky.csv"),
        "recommended_5leg_risky.csv": (latest.rec5_risky, "recommended_5leg_risky.csv"),
    }

    out_paths: Dict[str, str] = {}

    for _, (src, dest_name) in mapping.items():
        if src is None:
            continue
        dest = os.path.join(latest_dir, dest_name)
        shutil.copy2(src, dest)
        out_paths[dest_name] = dest

    # Confidence buckets (apply to both normal + risky if present)
    for name in [
        "recommended_4leg.csv",
        "recommended_5leg.csv",
        "recommended_4leg_risky.csv",
        "recommended_5leg_risky.csv",
    ]:
        if name in out_paths:
            add_confidence_buckets(out_paths[name])

    # Under bias column (scored files)
    if "scored_legs.csv" in out_paths:
        add_under_direction_bias(out_paths["scored_legs.csv"])
    if "scored_legs_deduped.csv" in out_paths:
        add_under_direction_bias(out_paths["scored_legs_deduped.csv"])

    return out_paths


def main():
    # Allow optional args:
    #   python tools/postprocess_outputs.py [tag]
    # tag -> latest/<tag> folder
    import sys

    tag = sys.argv[1] if len(sys.argv) > 1 else "all"

    output_dir = OUTPUT_DIR_DEFAULT
    latest_dir = os.path.join(output_dir, "latest", tag)

    latest = find_latest_outputs(output_dir)

    # Require at least something to copy
    if (
        latest.rec4 is None
        and latest.rec5 is None
        and latest.rec4_risky is None
        and latest.rec5_risky is None
    ):
        raise RuntimeError("No recommended outputs found to postprocess (normal or risky).")

    clear_folder(latest_dir)
    copied = copy_into_latest(latest_dir, latest)

    print(f"✅ Updated latest folder: {latest_dir}")
    for k, v in copied.items():
        print(f" - {k}: {v}")


if __name__ == "__main__":
    main()