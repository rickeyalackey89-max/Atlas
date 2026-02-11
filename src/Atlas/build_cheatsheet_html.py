#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path
from datetime import datetime

import pandas as pd


# ----------------------------
# Canonicalization helpers
# ----------------------------
def _canon_player(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()

def _canon_market(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).upper()

def _canon_dir(s: object) -> str:
    t = str(s or "").strip().upper()
    if t in {"OVER", "O", "MORE"}:
        return "OVER"
    if t in {"UNDER", "U", "LESS"}:
        return "UNDER"
    return t


# ----------------------------
# File discovery
# ----------------------------
from Atlas.runtime.paths import find_repo_root

def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _auto_find_scored(root: Path) -> Path | None:
    # Prefer latest/all
    cand = list((root / "data" / "output").rglob("scored_legs*.csv"))
    if not cand:
        # fallback: any CSV that looks like scored legs
        cand = list((root / "data" / "output").rglob("*scored*legs*.csv"))
    if not cand:
        return None
    # pick newest modified
    cand.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cand[0]


# ----------------------------
# Preparation / joins
# ----------------------------
def _prepare(bp_path: Path, board_path: Path, scored_path: Path | None) -> pd.DataFrame:
    bp = pd.read_csv(bp_path)
    board = pd.read_csv(board_path)

    scored = None
    if scored_path and scored_path.exists():
        scored = pd.read_csv(scored_path)

    # ---- BP normalization
    bp2 = bp.copy()
    # Expected columns from parse_bettingpros_paste.py:
    # player, market_key, prop, pick, line, proj, proj_diff, stars, ev_pct, hit_*, signal_strength
    if "market_key" not in bp2.columns:
        # attempt fallback
        bp2["market_key"] = bp2.get("prop", "")

    bp2["player_key"] = bp2["player"].map(_canon_player)

    def _bp_market_to_pp(mk: str) -> str:
        x = _canon_market(mk)
        # Normalize common BettingPros combo representations to PrizePicks/Atlas codes
        if x in {"PTS+AST", "PTS+ASTS"}:
            return "PA"
        if x in {"PTS+REB", "PTS+REBS"}:
            return "PR"
        if x in {"REB+AST", "REBS+AST"}:
            return "RA"
        if x in {"PTS+REB+AST", "PTS+REBS+AST"}:
            return "PRA"
        return x

    bp2["market_key2"] = bp2["market_key"].astype(str).map(_bp_market_to_pp)
    bp2["bp_dir"] = bp2.get("pick", "").map(_canon_dir)
    bp2["line"] = pd.to_numeric(bp2.get("line", None), errors="coerce")

    # ---- Board normalization
    b2 = board.copy()

    # Common columns in today.csv: player, stat, direction, line, tier, projection_id, more_allowed, less_allowed, ...
    # Some files may have different names; be defensive.
    if "player" not in b2.columns and "name" in b2.columns:
        b2["player"] = b2["name"]
    if "stat" not in b2.columns and "market_key" in b2.columns:
        b2["stat"] = b2["market_key"]

    b2["player_key"] = b2["player"].map(_canon_player)
    b2["stat_key2"] = b2.get("stat", "").map(_canon_market)
    b2["pp_dir"] = b2.get("direction", "").map(_canon_dir)
    b2["pp_line"] = pd.to_numeric(b2.get("line", None), errors="coerce")

    # ---- Scored normalization
    s2 = None
    if scored is not None:
        s2 = scored.copy()
        if "player" not in s2.columns and "name" in s2.columns:
            s2["player"] = s2["name"]
        if "stat" not in s2.columns and "market_key" in s2.columns:
            s2["stat"] = s2["market_key"]
        s2["player_key"] = s2["player"].map(_canon_player)
        s2["stat_key2"] = s2.get("stat", "").map(_canon_market)
        s2["model_dir"] = s2.get("direction", "").map(_canon_dir)
        s2["model_line"] = pd.to_numeric(s2.get("line", None), errors="coerce")

    # Merge BP -> board on (player, stat, line, direction)
    # Direction is important for "OVER/UNDER" matching.
    b2m = b2.drop(columns=["line"], errors="ignore")

    m = bp2.merge(
        b2m,
        how="left",
        left_on=["player_key", "market_key2", "line", "bp_dir"],
        right_on=["player_key", "stat_key2", "pp_line", "pp_dir"],
        suffixes=("_bp", "_pp"),
    )

    # Merge in model scored legs similarly (if present)
    if s2 is not None:
        s2m = s2.drop(columns=["line"], errors="ignore")
        m = m.merge(
            s2m,
            how="left",
            left_on=["player_key", "market_key2", "line", "bp_dir"],
            right_on=["player_key", "stat_key2", "model_line", "model_dir"],
            suffixes=("", "_model"),
        )

    # Diagnostics
    m["matched_atlas"] = (~m.get("p_adj").isna()) if "p_adj" in m.columns else (~m.get("p").isna())
    # Determine a reason for unmatched
    def _reason(row) -> str:
        if bool(row.get("matched_atlas", False)):
            return ""
        mk = str(row.get("market_key2", "") or "")
        if "+" in mk or mk in {"PTS+AST","PTS+REB","REB+AST","PRA","PR","RA"}:
            return "Combo market not modeled (dropped by fetch/model)"
        return "No Atlas match (player/stat/line/direction mismatch)"
    m["unmatched_reason"] = m.apply(_reason, axis=1)

    # Nice display columns
    # BettingPros side
    m.rename(columns={
        "proj": "BettingPros Projection",
        "proj_diff": "BettingPros Projection Diff",
        "stars": "BettingPros Stars",
        "ev_pct": "BettingPros EV%",
        "hit_L5": "BettingPros Hit L5%",
        "hit_L15": "BettingPros Hit L15%",
        "hit_season": "BettingPros Hit Season%",
        "hit_h2h": "BettingPros Hit H2H%",
        "signal_strength": "BettingPros Signal Strength",
        "pick": "BettingPros Pick",
        "prop": "BettingPros Market",
    }, inplace=True)

    # PrizePicks side (board)
    pp_rename = {}
    if "tier" in m.columns: pp_rename["tier"] = "PrizePicks Tier"
    if "projection_id" in m.columns: pp_rename["projection_id"] = "PrizePicks Projection ID"
    if "more_allowed" in m.columns: pp_rename["more_allowed"] = "PrizePicks More Allowed"
    if "less_allowed" in m.columns: pp_rename["less_allowed"] = "PrizePicks Less Allowed"
    if "pp_dir" in m.columns: pp_rename["pp_dir"] = "PrizePicks Direction"
    m.rename(columns=pp_rename, inplace=True)

    # Atlas (your model) rename – keep it human
    atlas_rename = {
        "p": "Atlas Probability",
        "p_close": "Atlas Probability (Close)",
        "p_adj": "Atlas Probability (Adjusted)",
        "p_eff": "Atlas Probability (Effective)",
        "p_combo": "Atlas Probability (Combo)",
        "ev": "Atlas EV",
        "fragility": "Atlas Fragility",
        "minutes_s": "Atlas Minutes Sensitivity",
        "blowout_risk": "Atlas Blowout Risk",
        "min_mean": "Atlas Minutes Mean",
        "min_std": "Atlas Minutes Std",
        "games_used": "Atlas Games Used",
    }
    for k,v in list(atlas_rename.items()):
        if k not in m.columns:
            atlas_rename.pop(k, None)
    m.rename(columns=atlas_rename, inplace=True)

    # Clean up internal join-key columns (keep some helpful ones)
    drop_cols = []
    for c in ["player_key","market_key2","stat_key2","pp_line","model_line","bp_dir","pp_dir","model_dir"]:
        if c in m.columns:
            drop_cols.append(c)
    # also drop any leftover join artifacts we don't want
    m.drop(columns=drop_cols, inplace=True, errors="ignore")

    # Ensure core columns exist
    if "player" not in m.columns and "player_bp" in m.columns:
        m["player"] = m["player_bp"]

    # Add a clean “Market Key” and “Line” for display
    if "market_key" in m.columns:
        m.rename(columns={"market_key": "Market Key"}, inplace=True)
    if "line" in m.columns:
        m.rename(columns={"line": "Line"}, inplace=True)

    # Keep a sensible column order: Identity -> BP -> PP -> Atlas -> Diagnostics
    cols = list(m.columns)

    def _pull(prefixes):
        out = []
        for p in prefixes:
            for c in cols:
                if c.startswith(p) and c not in out:
                    out.append(c)
        return out

    identity = [c for c in ["player", "matchup", "Market Key", "BettingPros Market", "BettingPros Pick", "Line"] if c in cols]
    bp_cols = _pull(["BettingPros "])
    pp_cols = _pull(["PrizePicks "])
    atlas_cols = _pull(["Atlas "])
    diag = [c for c in ["matched_atlas", "unmatched_reason"] if c in cols]

    ordered = []
    for grp in [identity, bp_cols, pp_cols, atlas_cols, diag]:
        for c in grp:
            if c in cols and c not in ordered:
                ordered.append(c)
    # append any remaining
    for c in cols:
        if c not in ordered:
            ordered.append(c)

    m = m[ordered].copy()

    # Sort: matched first, then strongest BP signal
    if "matched_atlas" in m.columns:
        m.sort_values(by=["matched_atlas", "BettingPros Stars", "BettingPros EV%"], ascending=[False, False, False], inplace=True, na_position="last")
    return m


# ----------------------------
# HTML
# ----------------------------
def _to_html(df: pd.DataFrame, out_path: Path, title: str) -> None:
    # DataTables via CDN (works best when phone has internet)
    datatables_css = "https://cdn.datatables.net/1.13.8/css/jquery.dataTables.min.css"
    datatables_js = "https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"
    jquery_js = "https://code.jquery.com/jquery-3.7.1.min.js"

    # Build table HTML safely
    headers = list(df.columns)
    rows = df.to_dict(orient="records")

    def td(v):
        if pd.isna(v):
            return ""
        if isinstance(v, float):
            # pretty float
            if abs(v) >= 100:
                s = f"{v:.1f}"
            elif abs(v) >= 10:
                s = f"{v:.2f}"
            else:
                s = f"{v:.4f}"
            return html.escape(s)
        return html.escape(str(v))

    # We'll tag matched rows with a class to enable toggle
    # matched_atlas column may be bool or missing
    matched_col = "matched_atlas" if "matched_atlas" in headers else None

    tr_lines = []
    for r in rows:
        matched = bool(r.get(matched_col, False)) if matched_col else True
        cls = "matched" if matched else "unmatched"
        tr_lines.append(
            "<tr class='%s'>%s</tr>" % (
                cls,
                "".join(f"<td>{td(r.get(h))}</td>" for h in headers)
            )
        )

    # Simple mobile-friendly styling
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="{datatables_css}"/>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 14px; }}
    h1 {{ font-size: 18px; margin: 0 0 8px 0; }}
    .meta {{ font-size: 12px; color: #555; margin-bottom: 10px; }}
    .controls {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin: 10px 0 10px 0; }}
    .pill {{ font-size: 12px; padding: 6px 10px; border: 1px solid #ddd; border-radius: 999px; background:#fafafa; }}
    table.dataTable tbody tr.unmatched {{ opacity: 0.65; }}
    /* Make it more phone-friendly */
    table.dataTable {{ width: 100% !important; }}
    .dataTables_wrapper .dataTables_filter input {{ width: 180px; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <div class="meta">
    Source: BettingPros (market) vs <b>Atlas</b> (model) • Generated: {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}
  </div>

  <div class="controls">
    <label class="pill">
      <input type="checkbox" id="toggleUnmatched" /> Show unmatched (no Atlas match)
    </label>
    <span class="pill">Tip: search player name, sort by “BettingPros EV%”, or filter “PrizePicks Tier”.</span>
  </div>

  <table id="tbl" class="display" style="width:100%">
    <thead>
      <tr>
        {''.join(f'<th>{html.escape(h)}</th>' for h in headers)}
      </tr>
    </thead>
    <tbody>
      {''.join(tr_lines)}
    </tbody>
  </table>

  <script src="{jquery_js}"></script>
  <script src="{datatables_js}"></script>
  <script>
    $(document).ready(function() {{
      var table = $('#tbl').DataTable({{
        pageLength: 50,
        order: [],
        scrollX: true
      }});

      function applyUnmatchedFilter() {{
        var show = $('#toggleUnmatched').is(':checked');
        if (show) {{
          // show all
          table.rows('.unmatched').nodes().to$().show();
        }} else {{
          // hide unmatched
          table.rows('.unmatched').nodes().to$().hide();
        }}
      }}

      // Hide unmatched by default
      applyUnmatchedFilter();

      $('#toggleUnmatched').on('change', function() {{
        applyUnmatchedFilter();
      }});
    }});
  </script>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")


def main() -> int:
    root = _project_root()
    ap = argparse.ArgumentParser(description="Build merged BettingPros vs Atlas cheat sheet HTML.")
    ap.add_argument("--bp", default=str(root / "data" / "input" / "bettingpros_signals_today.csv"), help="Path to BettingPros signals CSV")
    ap.add_argument("--board", default=str(root / "data" / "board" / "today.csv"), help="Path to PrizePicks today board CSV")
    ap.add_argument("--scored", default="", help="Path to scored_legs CSV (optional; auto-detected if omitted)")
    ap.add_argument("--out", default=str(root / "data" / "output" / "latest" / "all" / "cheatsheet_merged.html"), help="Output HTML path")
    ap.add_argument("--title", default="BettingPros vs Atlas — Daily Cheat Sheet", help="HTML title")
    args = ap.parse_args()

    bp = Path(args.bp)
    board = Path(args.board)

    if not bp.exists():
        print(f"Missing BettingPros signals: {bp}")
        return 2
    if not board.exists():
        print(f"Missing today board: {board}")
        return 2

    scored = Path(args.scored) if args.scored else _auto_find_scored(root)
    if scored and not scored.exists():
        scored = None

    df = _prepare(bp, board, scored)
    out = Path(args.out)
    _to_html(df, out, args.title)

    reminder = f"Wrote {out} (rows={len(df)})"
    if scored:
        reminder += f"\nUsed scored_legs: {scored}"
    else:
        reminder += "\nNo scored_legs detected — Atlas columns may be limited."
    print(reminder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
