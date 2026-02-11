from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import Dict, List, Optional

import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
RUNS_DIR = OUTPUT_DIR / "runs"
LATEST_DIR = OUTPUT_DIR / "latest"

# Regex for parsing legs
PLAYER_RE = re.compile(r"^\s*(.*?)\s+(?:OVER|UNDER)\s+", re.UNICODE)
LEGS_SPLIT_RE = re.compile(r"\s*\|\|\s*|\s+\|\s+", re.UNICODE)  # accept both "||" and " | "

# -----------------------------
# Diversity policy (single truth)
# -----------------------------
# Hard invariant: within-slip unique player is always enforced unless --no-unique-player-enforce
# Portfolio rule: a player may appear in up to N slips within a given published file.
DEFAULT_MAX_SLIPS_PER_PLAYER = 5


@dataclass
class PublishSpec:
    tag: str
    min_minutes_to_start: int
    match_mode: str  # informational; currently only min-minutes is enforced


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _latest_run_dir(runs_dir: Path) -> Optional[Path]:
    if not runs_dir.exists():
        return None
    run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    if not run_dirs:
        return None
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return run_dirs[0]


def _read_csv(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        try:
            return pd.read_csv(path, encoding="utf-8", encoding_errors="ignore")
        except Exception:
            return None


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    _safe_mkdir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _expected_cols(n_legs: int) -> List[str]:
    cols = [
        "n_legs",
        "legs",
        "hit_prob",
        "ev_mult",
        "avg_p",
        "avg_fragility",
        "slip_key",
        "slip_agreement_score",
        "slip_agreement_tier",
        "slip_tag_set",
        "slip_tag",
        "slip_min_start_utc",
        "slip_has_unknown_start",
    ]
    for i in range(1, n_legs + 1):
        cols.append(f"leg_{i}")
    return cols


def _copy_placeholder(out_path: Path, expected_n_legs: int) -> None:
    _safe_mkdir(out_path.parent)
    pd.DataFrame(columns=_expected_cols(expected_n_legs)).to_csv(out_path, index=False, encoding="utf-8-sig")


def _split_legs(legs_val: object) -> List[str]:
    s = "" if legs_val is None else str(legs_val)
    s = s.strip()
    if not s or s.lower() == "nan":
        return []
    return [x.strip() for x in LEGS_SPLIT_RE.split(s) if x and x.strip()]


def _fallback_legs_from_columns(row: pd.Series) -> List[str]:
    legs: List[str] = []
    for i in range(1, 10):
        c = f"leg_{i}"
        if c not in row.index:
            continue
        v = row[c]
        if v is None:
            continue
        sv = str(v).strip()
        if not sv or sv.lower() == "nan":
            continue
        legs.append(sv)
    return legs


def _parse_player(leg: str) -> Optional[str]:
    m = PLAYER_RE.search(leg)
    if not m:
        return None
    name = (m.group(1) or "").strip()
    return name or None


def _players_from_legs_str(legs_val: object) -> List[str]:
    legs = _split_legs(legs_val)
    out: List[str] = []
    for leg in legs:
        p = _parse_player(leg)
        if p:
            out.append(p)
    return out


def _normalize_legs_and_enforce_unique_player_per_slip(
    df: pd.DataFrame, expected_n_legs: int, enforce_unique_player: bool = True
) -> pd.DataFrame:
    """
    Normalizes legs into a canonical ' | ' delimiter and enforces:
      - row has exactly expected_n_legs legs
      - (optional) within-slip unique player
    """
    if df is None or len(df) == 0:
        return df

    df = df.copy()

    legs_lists: List[List[str]] = []
    players_lists: List[List[str]] = []
    leg_counts: List[int] = []

    for _, row in df.iterrows():
        legs: List[str] = []
        if "legs" in df.columns:
            legs = _split_legs(row.get("legs"))

        # If legs string is missing/degenerate, fall back to leg_1..leg_n columns
        if len(legs) <= 1:
            legs2 = _fallback_legs_from_columns(row)
            if len(legs2) >= 2:
                legs = legs2

        legs = [str(x).strip() for x in legs if str(x).strip() and str(x).strip().lower() != "nan"]
        legs_lists.append(legs)
        leg_counts.append(len(legs))

        players: List[str] = []
        for leg in legs:
            p = _parse_player(leg)
            if p:
                players.append(p)
        players_lists.append(players)

    df["_legs_list"] = legs_lists
    df["_leg_count"] = leg_counts
    df["_players_list"] = players_lists

    # Ensure n_legs exists
    if "n_legs" not in df.columns:
        df["n_legs"] = expected_n_legs
    else:
        df["n_legs"] = pd.to_numeric(df["n_legs"], errors="coerce").fillna(expected_n_legs).astype(int)

    # Must match expected count
    df = df[df["_leg_count"] == expected_n_legs].copy()

    # Per-slip unique player (HARD invariant unless user disables)
    if enforce_unique_player:
        df = df[df["_players_list"].apply(lambda ps: (not ps) or (len(ps) == len(set(ps))))].copy()

    # Canonical legs string
    if "legs" in df.columns:
        df["legs"] = df["_legs_list"].apply(lambda xs: " | ".join(xs))

    df = df.drop(columns=["_legs_list", "_leg_count", "_players_list"], errors="ignore")
    return df


def _parse_utc(val: object) -> Optional[pd.Timestamp]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        ts = pd.to_datetime(s, utc=True)
        if pd.isna(ts):
            return None
        return ts
    except Exception:
        return None


def _slip_time_ok(row: pd.Series, spec: PublishSpec, now_utc: pd.Timestamp) -> bool:
    # If unknown start, allow
    if "slip_has_unknown_start" in row.index:
        try:
            if int(row["slip_has_unknown_start"]) == 1:
                return True
        except Exception:
            pass

    # If no timestamp, allow
    if "slip_min_start_utc" not in row.index:
        return True

    ts = _parse_utc(row.get("slip_min_start_utc"))
    if ts is None:
        return True

    cutoff = now_utc + pd.Timedelta(minutes=spec.min_minutes_to_start)
    return ts >= cutoff


def _filter_by_place_window(df: pd.DataFrame, spec: PublishSpec) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return df
    now_utc = pd.Timestamp.now(tz="UTC")
    mask = df.apply(lambda r: _slip_time_ok(r, spec, now_utc), axis=1)
    return df[mask].copy()


def _enforce_player_cap_within_file(df: pd.DataFrame, max_slips_per_player: int) -> pd.DataFrame:
    """
    Portfolio rule (within THIS CSV output):
      - A player may appear in up to max_slips_per_player slips.
      - If a slip would cause any included player to exceed the cap, drop the slip.
    """
    if df is None or len(df) == 0:
        return df
    if max_slips_per_player <= 0:
        # defensive: treat as "no slips allowed"
        return df.head(0)

    counts: Dict[str, int] = {}
    kept_rows = []

    for _, row in df.iterrows():
        players = _players_from_legs_str(row.get("legs", ""))

        # If we can't parse players reliably, keep the row (do not over-prune).
        if not players:
            kept_rows.append(row)
            continue

        violates = False
        for p in players:
            if counts.get(p, 0) >= max_slips_per_player:
                violates = True
                break
        if violates:
            continue

        kept_rows.append(row)
        for p in players:
            counts[p] = counts.get(p, 0) + 1

    if not kept_rows:
        return df.head(0)
    return pd.DataFrame(kept_rows)


def _publish_one_csv(
    in_path: Path,
    expected_n_legs: int,
    spec: PublishSpec,
    enforce_unique_player_per_slip: bool,
    enforce_player_cap_within_file: bool,
    max_slips_per_player: int,
) -> pd.DataFrame:
    df = _read_csv(in_path)
    if df is None:
        return pd.DataFrame(columns=_expected_cols(expected_n_legs))

    df = _normalize_legs_and_enforce_unique_player_per_slip(
        df, expected_n_legs, enforce_unique_player=enforce_unique_player_per_slip
    )
    df = _filter_by_place_window(df, spec)

    if df is None or len(df) == 0:
        return pd.DataFrame(columns=_expected_cols(expected_n_legs))

    for c in _expected_cols(expected_n_legs):
        if c not in df.columns:
            df[c] = pd.NA

    if ("ev_mult" in df.columns) and ("hit_prob" in df.columns):
        df["ev_mult"] = pd.to_numeric(df["ev_mult"], errors="coerce")
        df["hit_prob"] = pd.to_numeric(df["hit_prob"], errors="coerce")
        df = df.sort_values(["ev_mult", "hit_prob"], ascending=[False, False], na_position="last").reset_index(drop=True)

    if enforce_player_cap_within_file:
        df = _enforce_player_cap_within_file(df, max_slips_per_player=max_slips_per_player)

    return df


def _write_published(df: pd.DataFrame, out_path: Path, expected_n_legs: int) -> None:
    if df is None or len(df) == 0:
        _copy_placeholder(out_path, expected_n_legs)
        return

    cols = _expected_cols(expected_n_legs)
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA

    df = df[cols]
    _write_csv(df, out_path)


def _publish_product(
    *,
    run_dir: Path,
    spec: PublishSpec,
    product: str,
    run_subdir: str,
    enforce_unique_player_per_slip: bool,
    enforce_player_cap_within_file: bool,
    max_slips_per_player: int,
) -> None:
    tag_dir = LATEST_DIR / spec.tag
    out_dir = tag_dir / product
    _safe_mkdir(out_dir)

    src_base = run_dir / run_subdir

    for n in (3, 4, 5):
        src = src_base / f"recommended_{n}leg.csv"
        dst = out_dir / f"recommended_{n}leg.csv"
        df = _publish_one_csv(
            src,
            expected_n_legs=n,
            spec=spec,
            enforce_unique_player_per_slip=enforce_unique_player_per_slip,
            enforce_player_cap_within_file=enforce_player_cap_within_file,
            max_slips_per_player=max_slips_per_player,
        )
        _write_published(df, dst, expected_n_legs=n)


def _spec_for_tag(tag: str, min_minutes_to_start: Optional[int], match_mode: Optional[str]) -> PublishSpec:
    t = tag.strip().lower()
    mm = 0 if min_minutes_to_start is None else int(min_minutes_to_start)
    m = "any" if not match_mode else str(match_mode).strip().lower()
    return PublishSpec(tag=t, min_minutes_to_start=mm, match_mode=m)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Atlas: publish latest/<tag> outputs from most recent run (System/Windfall/AI/Capper)."
    )
    ap.add_argument("--tag", default="all", help="Tag to publish (all/early/main/late or custom).")
    ap.add_argument("--run-dir", default="", help="Optional explicit run dir; otherwise newest in data/output/runs.")
    ap.add_argument(
        "--no-unique-player-enforce",
        action="store_true",
        help="Disable per-slip unique-player enforcement at publish time.",
    )

    ap.add_argument("--min-minutes-to-start", type=int, default=None, help="Minimum minutes until earliest game start.")
    ap.add_argument("--match-mode", default=None, help="Compatibility: any|strict (informational).")

    ap.add_argument(
        "--max-slips-per-player",
        type=int,
        default=DEFAULT_MAX_SLIPS_PER_PLAYER,
        help=f"Portfolio cap within each output file (System/Windfall). Default: {DEFAULT_MAX_SLIPS_PER_PLAYER}",
    )

    args = ap.parse_args()

    enforce_unique_player_per_slip = not args.no_unique_player_enforce
    spec = _spec_for_tag(args.tag, args.min_minutes_to_start, args.match_mode)
    max_slips_per_player = int(args.max_slips_per_player)

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir(RUNS_DIR)
    if run_dir is None or not run_dir.exists():
        print(f"[PUBLISH] {_now_stamp()}  No run dir found under: {RUNS_DIR}")
        return 0

    print(f"[PUBLISH] {_now_stamp()}  run_dir={run_dir}")
    print(
        f"[PUBLISH] tag={spec.tag} min_minutes_to_start={spec.min_minutes_to_start} "
        f"match_mode={spec.match_mode} enforce_unique_player={enforce_unique_player_per_slip} "
        f"max_slips_per_player={max_slips_per_player}"
    )

    # Always publish System/Windfall into the requested tag bucket.
    _publish_product(
        run_dir=run_dir,
        spec=spec,
        product="System",
        run_subdir=".",
        enforce_unique_player_per_slip=enforce_unique_player_per_slip,
        enforce_player_cap_within_file=True,
        max_slips_per_player=max_slips_per_player,
    )
    _publish_product(
        run_dir=run_dir,
        spec=spec,
        product="Windfall",
        run_subdir="Windfall",
        enforce_unique_player_per_slip=enforce_unique_player_per_slip,
        enforce_player_cap_within_file=True,
        max_slips_per_player=max_slips_per_player,
    )

    # GameScript feeds (AI/Capper) are a single surface ONLY: latest/all.
    # They should never be bucketed into early/main/late because picks may span timelines.
    if spec.tag == "all":
        _publish_product(
            run_dir=run_dir,
            spec=spec,
            product="AI",
            run_subdir="AI",
            enforce_unique_player_per_slip=enforce_unique_player_per_slip,
            enforce_player_cap_within_file=False,
            max_slips_per_player=max_slips_per_player,
        )
        _publish_product(
            run_dir=run_dir,
            spec=spec,
            product="Capper",
            run_subdir="Capper",
            enforce_unique_player_per_slip=enforce_unique_player_per_slip,
            enforce_player_cap_within_file=False,
            max_slips_per_player=max_slips_per_player,
        )
    else:
        print(f"[PUBLISH] tag={spec.tag}: skipping AI/Capper (GameScript only publishes to latest/all)")

    print(f"[PUBLISH] wrote to: {LATEST_DIR / spec.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
