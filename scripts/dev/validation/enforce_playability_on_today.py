import os
import sys
import pandas as pd

# --- allow importing from /src (same pattern as our test script)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
sys.path.insert(0, SRC_PATH)

from playability import load_board_catalog, build_board_map, Leg, is_playable_leg  # noqa: E402


CATALOG_PATH = os.path.join(PROJECT_ROOT, "data", "board", "board_catalog.csv")
TODAY_PATH = os.path.join(PROJECT_ROOT, "data", "board", "today.csv")


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return ""


def _normalize_side(x) -> str:
    s = "" if x is None else str(x).strip().upper()
    # common PP wording
    if s in {"MORE", "OVER", "O"}:
        return "OVER"
    if s in {"LESS", "UNDER", "U"}:
        return "UNDER"
    return s


def main() -> int:
    if not os.path.exists(CATALOG_PATH):
        print(f"[ERROR] Missing catalog: {CATALOG_PATH}")
        return 2
    if not os.path.exists(TODAY_PATH):
        print(f"[ERROR] Missing today.csv: {TODAY_PATH}")
        return 2

    board_df = load_board_catalog(CATALOG_PATH)
    board_map = build_board_map(board_df)

    df = pd.read_csv(TODAY_PATH)
    if df.empty:
        print("[INFO] today.csv is empty — nothing to filter.")
        return 0

    # Detect columns (robust to your current schema)
    player_col = _find_col(df, ["player", "player_name", "name"])
    stat_col = _find_col(df, ["stat_type", "stat", "market", "prop_type"])
    line_col = _find_col(df, ["line", "prop_line", "projection", "value"])
    side_col = _find_col(df, ["side", "pick_side", "direction", "over_under", "ou"])

    missing = [("player", player_col), ("stat_type", stat_col), ("line", line_col), ("side", side_col)]
    missing = [label for label, col in missing if col == ""]
    if missing:
        print("[ERROR] Could not find required columns in today.csv.")
        print("Missing:", missing)
        print("Columns present:", list(df.columns))
        return 3

    # Evaluate playability row-by-row
    playable_flags = []
    drop_reasons = []

    for _, r in df.iterrows():
        player = str(r[player_col]).strip()
        stat_type = str(r[stat_col]).strip().upper()
        try:
            line = float(r[line_col])
        except Exception:
            line = float("nan")
        side = _normalize_side(r[side_col])

        if side not in {"OVER", "UNDER"}:
            playable_flags.append(False)
            drop_reasons.append(f"bad_side:{side}")
            continue

        if pd.isna(line):
            playable_flags.append(False)
            drop_reasons.append("bad_line")
            continue

        leg = Leg(player=player, stat_type=stat_type, line=float(line), side=side)

        ok = is_playable_leg(leg, board_map)
        playable_flags.append(ok)
        if not ok:
            drop_reasons.append("not_in_catalog_or_side_disallowed")
        else:
            drop_reasons.append("")

    df["_playable"] = playable_flags
    before = len(df)
    after = int(df["_playable"].sum())
    dropped = before - after

    # Report
    print("=" * 72)
    print("[PLAYABILITY FILTER]")
    print(f"Catalog: {CATALOG_PATH}")
    print(f"Input  : {TODAY_PATH}")
    print(f"Rows before: {before}")
    print(f"Rows after : {after}")
    print(f"Dropped    : {dropped}")
    print("=" * 72)

    if dropped > 0:
        # show top drop reasons
        tmp = df.loc[~df["_playable"]].copy()
        tmp["_reason"] = [dr for dr, ok in zip(drop_reasons, playable_flags) if not ok]
        print("[Top drop reasons]")
        print(tmp["_reason"].value_counts().head(10).to_string())
        print("=" * 72)

    # Overwrite today.csv with playable only
    out = df[df["_playable"]].drop(columns=["_playable"], errors="ignore")
    out.to_csv(TODAY_PATH, index=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())