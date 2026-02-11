import sys
import json
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import pandas as pd

# -----------------------------
# Config: choose the raw file
# -----------------------------
ROOT = find_repo_root(Path(__file__))
RAW_NAME = "prizepicks_20260202_204354.json"  # <-- change this to the exact raw you want
raw = ROOT / "data" / "raw" / RAW_NAME

# Ensure project root is on path so `import tools...` works
sys.path.insert(0, str(ROOT))

import tools.fetch_prizepicks_today as f  # noqa: E402


def main() -> None:
    if not raw.exists():
        raise FileNotFoundError(f"Raw file not found: {raw}")

    payload = json.loads(raw.read_text(encoding="utf-8"))
    data = payload.get("data", []) or []
    included = payload.get("included", []) or []

    # Build players map (id -> attributes)
    players: dict[str, dict] = {}
    for inc in included:
        if inc.get("type") in ("player", "new_player"):
            pid = str(inc.get("id") or "").strip()
            attr = inc.get("attributes", {}) or {}
            players[pid] = {"name": attr.get("name"), "team": attr.get("team")}

    rows: list[dict] = []

    for item in data:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes", {}) or {}
        rel = item.get("relationships", {}) or {}

        player_id = f._clean_str(
            ((rel.get("new_player") or {}).get("data") or {}).get("id")
            or ((rel.get("player") or {}).get("data") or {}).get("id")
        )

        p = players.get(player_id, {})
        player_name = f._clean_str(p.get("name"))

        # fallback
        if not player_name:
            player_name = f._clean_str(
                attr.get("description") or attr.get("player_name") or attr.get("name")
            )

        if not player_name:
            continue

        # Skip combo players like "A + B"
        if f._is_combo_player_name(player_name):
            continue

        stat = f._norm_stat(
            attr.get("stat_type")
            or attr.get("stat_type_display")
            or attr.get("stat_display_name")
        )
        if not stat:
            continue

        line = attr.get("line_score")
        if line is None:
            line = attr.get("flash_sale_line_score")
        if line is None:
            line = attr.get("line") or attr.get("score") or attr.get("projection")

        try:
            line = float(line) if line is not None else None
        except Exception:
            line = None

        rows.append(
            {
                "projection_id": f._clean_str(item.get("id")),
                "player": player_name,
                "stat": stat,
                "line": line,
                "tag": f._infer_tag(attr.get("odds_type")),
                # include a few extra fields to mirror the fetcher's shape
                "team": f._clean_str(p.get("team")) or f._clean_str(attr.get("team") or attr.get("team_abbr")),
                "opp": f._clean_str(attr.get("opponent")),
                "home": 1 if f._clean_str(attr.get("home")) in ("1", "True", "true") else 0,
                "game_date": f._clean_str(attr.get("game_date")),
            }
        )

    base = pd.DataFrame(rows)

    print("RAW FILE:", raw.name)
    print("data items:", len(data), "included items:", len(included))
    print("base rows:", len(base))
    if base.empty:
        print("❌ base is empty (collapse is upstream of mainline selection)")
        return

    print("base line non-null:", int(base["line"].notna().sum()))
    print("base line dtype:", base["line"].dtype)
    print("base sample rows:\n", base.head(3).to_string(index=False))

    # Mirror fetcher guard + line coercion
    base2 = base.copy()
    base2["player"] = base2["player"].fillna("").astype(str)
    base2["stat"] = base2["stat"].fillna("").astype(str)
    base2 = base2[(base2["player"].str.strip() != "") & (base2["stat"].str.strip() != "")].copy()

    base2["line"] = pd.to_numeric(base2["line"], errors="coerce")
    base2 = base2[base2["line"].notna()].copy()

    print("after base guards:", len(base2))
    if base2.empty:
        print("❌ base2 is empty after guards (player/stat/line filtering nuked it)")
        return

    filtered = (
        base2.groupby(["player", "stat"], group_keys=False)
        .apply(f._pick_main_line)
        .reset_index(drop=True)
    )

    print("filtered rows:", len(filtered))
    print("filtered columns:", list(filtered.columns))

    if filtered.empty:
        print("❌ FILTERED IS EMPTY (unexpected if base2 non-empty)")
        return

    print("filtered head:\n", filtered.head(3).to_string(index=False))

    recs = filtered.to_dict("records")
    print("filtered record keys sample:", sorted(recs[0].keys()))
    print("sample record:", recs[0])

    # Expansion exactly like fetcher (keep same columns)
    expanded_rows: list[dict] = []
    for d in recs:
        for direction in ("OVER", "UNDER"):
            expanded_rows.append(
                {
                    "projection_id": d.get("projection_id", ""),
                    "player": d.get("player", ""),
                    "stat": d.get("stat", ""),
                    "direction": direction,
                    "line": d.get("line", ""),
                    "tag": d.get("tag", ""),
                    "team": d.get("team", ""),
                    "opp": d.get("opp", ""),
                    "home": d.get("home", 0),
                    "game_date": d.get("game_date", ""),
                }
            )

    df = pd.DataFrame(expanded_rows)

    print("expanded rows (pre):", len(df))
    if df.empty:
        print("❌ expanded df is empty (filtered had records but expansion produced none)")
        return

    print("expanded sample (pre):\n", df.head(5).to_string(index=False))

    coerced = pd.to_numeric(df["line"], errors="coerce")
    print("expanded coerced non-null:", int(coerced.notna().sum()), "of", len(coerced))

    # Mirror fetcher final guards
    df["line"] = coerced
    df = df[df["line"].notna()].copy()

    df["player"] = df["player"].fillna("").astype(str)
    df["stat"] = df["stat"].fillna("").astype(str)
    bad = (df["player"].str.strip() == "") | (df["stat"].str.strip() == "")
    if bad.any():
        df = df.loc[~bad].copy()

    print("final df rows (post guards):", len(df))
    print("final df sample:\n", df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
