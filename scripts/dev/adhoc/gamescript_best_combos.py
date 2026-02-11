import re
import json
import csv
from pathlib import Path
from datetime import datetime
from itertools import combinations

ROOT = Path(r"C:\Users\rick\projects\Atlas")

# You can point this to your daily to-dos folder on your machine
GAMESCRIPT_TXT = ROOT / "daily to-dos" / "Gamescript picks.txt"

# Prefer latest run scored legs (most accurate)
RUNS_DIR = ROOT / "data" / "output" / "runs"
DASH_DIR = ROOT / "data" / "output" / "dashboard"

OUT_4 = DASH_DIR / "gamescript_best_4leg.json"
OUT_5 = DASH_DIR / "gamescript_best_5leg.json"

# ---------- Helpers ----------

def latest_run_dir() -> Path:
    dirs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not dirs:
        raise FileNotFoundError(f"No run dirs found in {RUNS_DIR}")
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)[0]

def load_scored_legs(run_dir: Path) -> list[dict]:
    # Prefer deduped; fall back to scored_legs.csv
    p = run_dir / "scored_legs_deduped.csv"
    if not p.exists():
        p = run_dir / "scored_legs.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing scored legs in {run_dir}")

    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def parse_gamescript_txt(path: Path) -> list[dict]:
    """
    Very tolerant parser. It tries to extract:
    - player name
    - stat keyword
    - line number
    Examples it can handle:
      "Collin Gillespie 10+ Points"
      "Victor Wembanyama 8+ Rebounds"
      "Tyrese Maxey 6+ Assists"
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    picks = []

    stat_map = {
        "points": "PTS",
        "rebounds": "REB",
        "assists": "AST",
        "3ptm": "FG3M",
        "3pm": "FG3M",
        "threes": "FG3M",
        "pra": "PRA",
        "pr": "PR",
        "ra": "RA",
        "pa": "PA",
    }

    for ln in lines:
        # Find "number+" like 10+  /  2+ etc
        m = re.search(r"(\d+(?:\.\d+)?)\s*\+", ln)
        if not m:
            continue
        line_val = m.group(1)

        # crude stat detection
        stat_key = None
        for k in stat_map:
            if k in ln.lower():
                stat_key = stat_map[k]
                break
        if not stat_key:
            continue

        # Player name = everything before the number+
        player = ln[:m.start()].strip(" -•\t")
        if not player:
            continue

        picks.append({
            "raw": ln,
            "player": player,
            "stat": stat_key,
            "line": line_val,
        })

    return picks

def match_to_atlas(gs_pick: dict, scored_rows: list[dict]) -> dict | None:
    """
    Match by player+stat+line. If your scored CSV uses different column names,
    adjust the keys below.
    """
    player_key_candidates = ["player", "player_name", "name"]
    stat_key_candidates = ["stat"]
    line_key_candidates = ["line", "projection", "pp_line"]

    def get(row, keys):
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return None

    target_player = norm(gs_pick["player"])
    target_stat = norm(gs_pick["stat"])
    target_line = str(gs_pick["line"]).strip()

    for row in scored_rows:
        rp = get(row, player_key_candidates)
        rs = get(row, stat_key_candidates)
        rl = get(row, line_key_candidates)

        if rp is None or rs is None or rl is None:
            continue

        if norm(rp) == target_player and norm(rs) == target_stat and str(rl).strip() == target_line:
            # Pick a score column if present
            score = None
            for sk in ["score", "atlas_score", "model_score", "edge", "ev"]:
                if sk in row and row[sk] not in ("", None):
                    try:
                        score = float(row[sk])
                        break
                    except:
                        pass

            # Get team/game if present for correlation controls
            team = row.get("team") or row.get("player_team") or None
            game = row.get("game") or row.get("matchup") or row.get("game_id") or None

            return {
                "player": rp,
                "stat": rs,
                "line": rl,
                "score": score,
                "team": team,
                "game": game,
                "raw_gamescript": gs_pick["raw"],
            }

    return None

def combo_ok(combo: list[dict]) -> bool:
    # Constraints (tunable)
    max_per_team = 2
    max_per_game = 2

    players = [norm(c["player"]) for c in combo]
    if len(set(players)) != len(players):
        return False

    # team constraint
    teams = [norm(c["team"]) for c in combo if c.get("team")]
    for t in set(teams):
        if teams.count(t) > max_per_team:
            return False

    # game constraint
    games = [norm(c["game"]) for c in combo if c.get("game")]
    for g in set(games):
        if games.count(g) > max_per_game:
            return False

    return True

def combo_score(combo: list[dict]) -> float:
    # If score missing, treat as very low
    s = 0.0
    for c in combo:
        s += (c["score"] if isinstance(c.get("score"), (int, float)) else -999.0)
    return s

def best_combo(cands: list[dict], k: int) -> dict | None:
    best = None
    for combo in combinations(cands, k):
        combo = list(combo)
        if not combo_ok(combo):
            continue
        sc = combo_score(combo)
        if best is None or sc > best["combo_score"]:
            best = {"combo": combo, "combo_score": sc}
    return best

# ---------- Main ----------

def main():
    DASH_DIR.mkdir(parents=True, exist_ok=True)

    run_dir = latest_run_dir()
    scored = load_scored_legs(run_dir)

    gs_picks = parse_gamescript_txt(GAMESCRIPT_TXT)
    matched = []
    unmatched = []

    for p in gs_picks:
        m = match_to_atlas(p, scored)
        if m:
            matched.append(m)
        else:
            unmatched.append(p)

    # Sort candidates by score desc (unknown score last)
    matched.sort(key=lambda r: (r["score"] is None, -(r["score"] or -999.0)))

    b4 = best_combo(matched, 4) if len(matched) >= 4 else None
    b5 = best_combo(matched, 5) if len(matched) >= 5 else None

    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "gamescript_source": str(GAMESCRIPT_TXT),
        "gamescript_pick_count": len(gs_picks),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "notes": "Best combos are chosen from Gamescript candidates using Atlas scores + diversification constraints.",
    }

    OUT_4.write_text(json.dumps({
        **meta,
        "k": 4,
        "best": b4,
        "top_candidates_preview": matched[:15],
        "unmatched_preview": unmatched[:15],
    }, indent=2), encoding="utf-8")

    OUT_5.write_text(json.dumps({
        **meta,
        "k": 5,
        "best": b5,
        "top_candidates_preview": matched[:15],
        "unmatched_preview": unmatched[:15],
    }, indent=2), encoding="utf-8")

    print(f"Wrote {OUT_4}")
    print(f"Wrote {OUT_5}")

if __name__ == "__main__":
    main()