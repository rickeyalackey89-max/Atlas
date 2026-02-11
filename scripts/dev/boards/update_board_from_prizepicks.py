import json
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
RAW_PATH = PROJECT_ROOT / "data" / "board" / "prizepicks_raw.json"
OUT_PATH = PROJECT_ROOT / "data" / "board" / "today.csv"

# Map PrizePicks stat names -> your model stat codes
STAT_MAP = {
    "Points": "PTS",
    "Rebounds": "REB",
    "Assists": "AST",
    "3-PT Made": "FG3M",
    "3-Pointers Made": "FG3M",
    "PRA": "PRA",  # sometimes appears as an abbreviation
    "Pts+Rebs+Asts": "PRA",
    "Points + Rebounds + Assists": "PRA",
    "Pts+Rebs": "PR",
    "Points + Rebounds": "PR",
    "Pts+Asts": "PA",
    "Points + Assists": "PA",
    "Rebs+Asts": "RA",
    "Rebounds + Assists": "RA",
}

def load_payload() -> dict:
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Missing: {RAW_PATH}\n"
            "Save the PrizePicks projections JSON to this path and retry."
        )
    return json.loads(RAW_PATH.read_text(encoding="utf-8"))

def build_lookup(included: list[dict]) -> tuple[dict, dict]:
    players_by_id = {}
    stat_by_id = {}

    for obj in included or []:
        t = obj.get("type")
        oid = str(obj.get("id"))
        attrs = obj.get("attributes") or {}

        if t in ("new_player", "player"):
            players_by_id[oid] = attrs
        elif t == "stat_type":
            stat_by_id[oid] = attrs

    return players_by_id, stat_by_id

def normalize_projection_rows(payload: dict) -> pd.DataFrame:
    data = payload.get("data") or []
    included = payload.get("included") or []
    players_by_id, stat_by_id = build_lookup(included)

    rows = []
    for p in data:
        attrs = p.get("attributes") or {}
        rel = p.get("relationships") or {}

        # Player
        player_rel = (
            rel.get("new_player", {}).get("data")
            or rel.get("player", {}).get("data")
            or {}
        )
        player_id = str(player_rel.get("id", ""))
        player_attrs = players_by_id.get(player_id, {})
        player_name = (
            player_attrs.get("display_name")
            or player_attrs.get("name")
            or attrs.get("description")
            or ""
        )
        player_name = str(player_name).strip()
        if not player_name:
            continue

        # Stat type
        stat_rel = rel.get("stat_type", {}).get("data") or {}
        stat_id = str(stat_rel.get("id", ""))
        stat_attrs = stat_by_id.get(stat_id, {})
        stat_name = stat_attrs.get("name") or attrs.get("stat_type") or attrs.get("stat_display_name") or ""
        stat_name = str(stat_name).strip()

        # Line
        line = attrs.get("line_score", None)
        if line is None:
            line = attrs.get("score", None)
        if line is None:
            continue

        # Map stat name to model code
        stat_code = STAT_MAP.get(stat_name)
        if not stat_code:
            # try a looser normalization
            key = stat_name.replace(" ", "").replace("-", "").replace("_", "")
            stat_code = STAT_MAP.get(key)
        if not stat_code:
            continue

        proj_id = str(p.get("id"))

        # Tag (optional)
        tag = str(attrs.get("odds_type") or "").upper().strip()

        # We write BOTH directions; main.py will dedupe later by p_adj
        for direction in ("OVER", "UNDER"):
            rows.append(
                {
                    "projection_id": proj_id,
                    "player": player_name,
                    "stat": stat_code,
                    "direction": direction,
                    "line": float(line),
                    "tag": tag,
                    "team": "",
                    "opp": "",
                    "home": 0,
                }
            )

    return pd.DataFrame(rows)

def main():
    payload = load_payload()
    board = normalize_projection_rows(payload)

    if board.empty:
        raise RuntimeError(
            "No usable projections found in prizepicks_raw.json.\n"
            "This usually means the JSON format changed or STAT_MAP is missing entries."
        )

    board = board.drop_duplicates(
        subset=["projection_id", "player", "stat", "direction", "line"],
        keep="last",
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    board.to_csv(OUT_PATH, index=False)

    print(f"Wrote: {OUT_PATH}")
    print(f"Rows: {len(board)}")

if __name__ == "__main__":
    main()
