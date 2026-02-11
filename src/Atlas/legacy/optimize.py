from __future__ import annotations

"""
Optimizer (Atlas 2.0)

Public entrypoints expected by src/main.py:
- build_candidates(scored_df, pool_size)
- recommend_slips(candidates, n_legs, payout_power_mult, payout_flex, rules, top_n)

Design goals:
- Deterministic, fast, robust.
- Never returns empty outputs if candidates exist (under default rules).
- Tier-aware (basic): upstream enforces playability; we still enforce one-player-per-slip here.
- Supports optional constraints via `rules` dict:
    - seed (int)
    - max_same_team_legs (int)
    - max_same_stat_family (int)
    - max_combo_stats (int)          # distinct stat families allowed in a slip
    - search_mode (str)              # "greedy" (default) or "random"
    - max_attempts (int)             # for random mode
    - min_overs_per_slip (int)       # enforce minimum OVER legs per slip (used for risky pool)

Portfolio diversity (post-pass; safe + non-fragile):
    - max_leg_uses (int)             # max times a projection_id can appear across selected slips
    - min_new_legs_per_slip (int)    # each selected slip must add >= K new leg-ids vs already selected
    - max_anchor_overlap (int)       # max overlap vs most recently selected slip
    - diversity_enabled (bool)       # default True

HARD invariants (locked):
- ONE-PLAYER-PER-SLIP (within a slip)
- MAX-1-PLAYER-USE across the published portfolio (at selection time)
- NO "backfill relax" that violates invariants (we’d rather return fewer slips)
"""

import random
import re
from typing import Any, Iterable

import pandas as pd


# -----------------------------
# Stat family helpers
# -----------------------------

STAT_FAMILY = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "FG3M": "FG3M",
    "3PM": "FG3M",
    "PA": "PA",
    "PR": "PR",
    "RA": "RA",
    "PRA": "PRA",
    "PTS_REB": "PTS_REB",
    "PTS_AST": "PTS_AST",
    "REB_AST": "REB_AST",
}


def _family(stat: Any) -> str:
    s = str(stat or "").strip().upper()
    return STAT_FAMILY.get(s, s or "UNK")


def _as_float(x: Any, default: float | None = None) -> float | None:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return default
        return float(x)
    except Exception:
        return default


def _prod(xs: Iterable[float]) -> float:
    out = 1.0
    for v in xs:
        out *= float(v)
    return out


def _fmt_line(x: Any) -> str:
    v = _as_float(x, None)
    if v is None:
        return str(x).strip()
    return f"{v:g}"


def _is_over(r: pd.Series) -> bool:
    return str(r.get("direction", "")).strip().upper() == "OVER"


def _format_leg(r: pd.Series) -> str:
    player = str(r.get("player", "")).strip()
    direction = str(r.get("direction", "")).strip().upper()
    stat = str(r.get("stat", "")).strip().upper()
    line = _fmt_line(r.get("line", ""))
    tier = str(r.get("tier", "STANDARD")).strip().upper() or "STANDARD"
    pid = r.get("projection_id", "")
    try:
        pid_s = str(int(pid))
    except Exception:
        pid_s = str(pid).strip()
    return f"{player} {direction} {stat} {line} ({tier}) [id:{pid_s}]"


def _slip_key(rows: list[pd.Series]) -> str:
    parts = []
    for r in rows:
        pid = r.get("projection_id", "")
        if pd.isna(pid):
            pid = ""
        parts.append(str(pid))
    return "|".join(parts)


# -----------------------------
# Candidate builder
# -----------------------------

def build_candidates(scored: pd.DataFrame, pool_size: int = 250) -> pd.DataFrame:
    if scored is None or len(scored) == 0:
        return pd.DataFrame()

    df = scored.copy()

    p_col = None
    for c in ["p_eff", "p_combo", "p_adj", "p", "p_close"]:
        if c in df.columns:
            p_col = c
            break

    if p_col is None:
        df["p_eff"] = 0.50
    else:
        df["p_eff"] = pd.to_numeric(df[p_col], errors="coerce").fillna(0.50).clip(0, 1)

    df["edge_score"] = df["p_eff"] - 0.5

    if "prop_key" not in df.columns:
        tier = df["tier"].astype(str).str.strip().str.upper() if "tier" in df.columns else "STANDARD"
        line_num = pd.to_numeric(df.get("line", pd.Series([pd.NA] * len(df))), errors="coerce")
        df["prop_key"] = (
            df.get("player", "").astype(str).str.strip()
            + "|"
            + df.get("stat", "").astype(str).str.strip().str.upper()
            + "|"
            + line_num.astype(str)
            + "|"
            + tier.astype(str)
        )

    frag_col = None
    for c in ["fragility", "avg_fragility"]:
        if c in df.columns:
            frag_col = c
            break

    if frag_col is None:
        br = pd.to_numeric(df.get("blowout_risk", 0.20), errors="coerce").fillna(0.20).clip(0, 1)
        ms = pd.to_numeric(df.get("minutes_s", 0.60), errors="coerce").fillna(0.60).clip(0, 1)
        df["fragility"] = (0.60 * br + 0.40 * (1.0 - ms)).clip(0, 1)
    else:
        df["fragility"] = pd.to_numeric(df[frag_col], errors="coerce").fillna(0.30).clip(0, 1)

    if "type" not in df.columns:
        df["type"] = df["tier"].astype(str).str.upper().str.strip() if "tier" in df.columns else "STANDARD"

    df["stat_family"] = df.get("stat", "").apply(_family)

    df = df.sort_values(["p_eff", "edge_score"], ascending=[False, False], na_position="last")
    pool_size = int(pool_size) if pool_size is not None else 250
    pool_size = max(1, pool_size)
    return df.head(pool_size).reset_index(drop=True)


# -----------------------------
# Slip scoring
# -----------------------------

def _score_slip(
    rows: list[pd.Series],
    n_legs: int,
    payout_power_mult: Any,
    payout_flex: Any,
) -> dict[str, Any]:
    ps = [float(r.get("p_eff", 0.5)) for r in rows]
    hit_prob = _prod(ps)

    ev_mult = 0.0
    power_mult = _as_float(payout_power_mult, None)
    if power_mult is not None:
        ev_mult = hit_prob * power_mult

    if isinstance(payout_flex, dict) and payout_flex:
        dp = [1.0] + [0.0] * n_legs
        for pi in ps:
            nxt = [0.0] * (n_legs + 1)
            for k in range(n_legs + 1):
                if dp[k] == 0:
                    continue
                nxt[k] += dp[k] * (1.0 - pi)
                if k + 1 <= n_legs:
                    nxt[k + 1] += dp[k] * pi
            dp = nxt

        flex_ev = 0.0
        for k, mult in payout_flex.items():
            try:
                kk = int(k)
                mm = float(mult)
            except Exception:
                continue
            if 0 <= kk <= n_legs:
                flex_ev += dp[kk] * mm

        ev_mult = max(ev_mult, flex_ev)

    avg_p = sum(ps) / len(ps) if ps else 0.0
    avg_frag = float(pd.Series([r.get("fragility", 0.3) for r in rows]).astype(float).mean())

    return {
        "n_legs": n_legs,
        "legs": " | ".join([_format_leg(r) for r in rows]),
        "hit_prob": hit_prob,
        "ev_mult": float(ev_mult),
        "avg_p": float(avg_p),
        "avg_fragility": float(avg_frag),
        "slip_key": _slip_key(rows),
    }


# -----------------------------
# Portfolio diversity (post-pass, HARD invariants)
# -----------------------------

_ID_RE = re.compile(r"\[id:(\d+)\]")
_PLAYER_RE = re.compile(r"^(.*)\s+(OVER|UNDER)\s+", re.IGNORECASE)


def _leg_ids_from_legs(legs: Any) -> list[str]:
    if legs is None:
        return []
    return _ID_RE.findall(str(legs))


def _players_from_legs(legs: Any) -> list[str]:
    if legs is None:
        return []
    parts = str(legs).split(" | ")
    out: list[str] = []
    for p in parts:
        m = _PLAYER_RE.match(p.strip())
        if not m:
            continue
        player = m.group(1).strip()
        if player:
            out.append(player)
    return out


def _apply_portfolio_diversity(
    ranked: pd.DataFrame,
    top_n: int,
    n_legs: int,
    min_overs_per_slip: int,
    rules: dict[str, Any],
) -> pd.DataFrame:
    if ranked is None or len(ranked) == 0:
        return ranked

    diversity_enabled = bool(rules.get("diversity_enabled", True))
    if not diversity_enabled:
        return ranked.head(top_n).reset_index(drop=True)

    # HARD: max-1 player use across portfolio
    max_player_uses = 1

    is_risky = min_overs_per_slip >= 2
    # Keep these conservative; do NOT relax them to "fill"
    max_leg_uses = int(rules.get("max_leg_uses", 1 if is_risky else 1))
    min_new_legs = int(rules.get("min_new_legs_per_slip", 2 if is_risky else 1))
    max_anchor_overlap = int(rules.get("max_anchor_overlap", max(0, n_legs - 1)))

    ranked = ranked.copy()
    ranked["_leg_ids"] = ranked["legs"].apply(_leg_ids_from_legs)
    ranked["_players"] = ranked["legs"].apply(_players_from_legs)

    selected_rows = []
    used_counts: dict[str, int] = {}
    used_players: dict[str, int] = {}
    used_set: set[str] = set()
    last_ids: set[str] = set()

    def _accept(row_ids: set[str], row_players: list[str]) -> bool:
        # If we can't parse ids, accept (rare)
        if not row_ids:
            return True

        # HARD: no repeated players across portfolio
        if row_players:
            for pl in row_players:
                if used_players.get(pl, 0) >= max_player_uses:
                    return False

        # Cap repeated leg usage across portfolio
        if any(used_counts.get(i, 0) >= max_leg_uses for i in row_ids):
            return False

        # Require new legs vs portfolio
        if len(row_ids - used_set) < min_new_legs:
            return False

        # Avoid "swap-one-leg" syndrome vs last slip
        if last_ids and len(row_ids & last_ids) > max_anchor_overlap:
            return False

        return True

    for _, row in ranked.iterrows():
        ids = set(row["_leg_ids"] or [])
        players = list(row.get("_players") or [])
        if not _accept(ids, players):
            continue

        selected_rows.append(row)
        for pl in players:
            used_players[pl] = used_players.get(pl, 0) + 1
        for i in ids:
            used_counts[i] = used_counts.get(i, 0) + 1
        used_set |= ids
        last_ids = ids

        if len(selected_rows) >= top_n:
            break

    # HARD: no relaxation backfill. Return fewer slips if needed.
    if len(selected_rows) < top_n:
        try:
            print(f"[DIVERSITY] HARD max_player_uses=1 produced {len(selected_rows)}/{top_n} slips (n_legs={n_legs}, risky={is_risky})")
        except Exception:
            pass

    final = pd.DataFrame(selected_rows).head(top_n)
    final = final.drop(columns=["_leg_ids", "_players"], errors="ignore")
    return final.reset_index(drop=True)


# -----------------------------
# Public API: recommend_slips
# -----------------------------

def recommend_slips(
    candidates: pd.DataFrame,
    n_legs: int,
    payout_power_mult: Any,
    payout_flex: Any,
    rules: dict[str, Any] | None = None,
    top_n: int = 25,
) -> pd.DataFrame:
    rules = rules or {}
    if candidates is None or len(candidates) == 0:
        return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility"])

    n_legs = int(n_legs)
    top_n = int(top_n)

    seed = int(rules.get("seed", 7))
    rng = random.Random(seed)

    mode = str(rules.get("search_mode", "greedy")).strip().lower()
    max_attempts = int(rules.get("max_attempts", 5000))

    max_same_team = int(rules.get("max_same_team_legs", 10))
    max_same_family = int(rules.get("max_same_stat_family", 10))
    max_combo_fams = int(rules.get("max_combo_stats", 10))

    min_overs_per_slip = int(rules.get("min_overs_per_slip", 0) or 0)
    min_overs_per_slip = max(0, min(min_overs_per_slip, n_legs))

    df = candidates.copy().reset_index(drop=True)

    df["p_eff"] = pd.to_numeric(df.get("p_eff", 0.5), errors="coerce").fillna(0.5).clip(0, 1)
    if "team" not in df.columns:
        df["team"] = ""
    else:
        df["team"] = df["team"].astype(str)

    if "stat_family" not in df.columns:
        df["stat_family"] = df.get("stat", "").apply(_family)
    else:
        df["stat_family"] = df["stat_family"].apply(_family)

    if "prop_key" not in df.columns:
        df["prop_key"] = df.index.astype(str)
    else:
        df["prop_key"] = df["prop_key"].astype(str)

    df = df.sort_values(["p_eff"], ascending=[False]).reset_index(drop=True)

    def ok_add(current: list[pd.Series], cand: pd.Series) -> bool:
        cur_keys = {str(r.get("prop_key", "")) for r in current}
        if str(cand.get("prop_key", "")) in cur_keys:
            return False

        # HARD: one-player-per-slip (within slip)
        cand_player = str(cand.get("player", "")).strip()
        if cand_player:
            for r in current:
                if str(r.get("player", "")).strip() == cand_player:
                    return False

        if max_same_team < 10:
            team = str(cand.get("team", "")).strip()
            if team:
                ct = sum(1 for r in current if str(r.get("team", "")).strip() == team)
                if ct >= max_same_team:
                    return False

        fam = _family(cand.get("stat_family", cand.get("stat", "")))
        ct_f = sum(1 for r in current if _family(r.get("stat_family", r.get("stat", ""))) == fam)
        if ct_f >= max_same_family:
            return False

        fams = {_family(r.get("stat_family", r.get("stat", ""))) for r in current}
        fams.add(fam)
        if len(fams) > max_combo_fams:
            return False

        return True

    slips: list[dict[str, Any]] = []
    seen: set[str] = set()

    # -----------------------------
    # Greedy generator
    # -----------------------------
    if mode != "random":
        # Expand starts to increase portfolio-diversity headroom
        starts = min(len(df), max(200, top_n * 40))

        for i in range(starts):
            cur: list[pd.Series] = [df.iloc[i]]

            if min_overs_per_slip > 0:
                for j in range(len(df)):
                    if len(cur) >= n_legs:
                        break
                    if sum(1 for r in cur if _is_over(r)) >= min_overs_per_slip:
                        break
                    cand = df.iloc[j]
                    if _is_over(cand) and ok_add(cur, cand):
                        cur.append(cand)

                for j in range(len(df)):
                    if len(cur) >= n_legs:
                        break
                    cand = df.iloc[j]
                    if ok_add(cur, cand):
                        cur.append(cand)
            else:
                for j in range(len(df)):
                    if len(cur) >= n_legs:
                        break
                    cand = df.iloc[j]
                    if ok_add(cur, cand):
                        cur.append(cand)

            if len(cur) != n_legs:
                continue

            if min_overs_per_slip > 0 and sum(1 for r in cur if _is_over(r)) < min_overs_per_slip:
                continue

            rec = _score_slip(cur, n_legs, payout_power_mult, payout_flex)
            if rec["slip_key"] in seen:
                continue
            seen.add(rec["slip_key"])
            slips.append(rec)

    # -----------------------------
    # Random generator (top-up pool)
    # -----------------------------
    if mode == "random" and len(slips) < top_n:
        idxs = list(range(len(df)))

        for _ in range(max_attempts):
            rng.shuffle(idxs)
            cur: list[pd.Series] = []

            for ix in idxs:
                if len(cur) >= n_legs:
                    break
                cand = df.iloc[ix]
                if ok_add(cur, cand):
                    cur.append(cand)

            if len(cur) != n_legs:
                continue

            if min_overs_per_slip > 0 and sum(1 for r in cur if _is_over(r)) < min_overs_per_slip:
                continue

            rec = _score_slip(cur, n_legs, payout_power_mult, payout_flex)
            if rec["slip_key"] in seen:
                continue

            seen.add(rec["slip_key"])
            slips.append(rec)

            if len(slips) >= top_n * 25:
                break

    if not slips:
        return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility"])

    out = pd.DataFrame(slips)

    out = out.sort_values(["ev_mult", "hit_prob"], ascending=[False, False]).drop_duplicates("slip_key")

    # Give the selector more headroom (avoid starving diversity)
    scan_cap = int(rules.get("diversity_scan_cap", max(5000, top_n * 500)))
    out = out.head(scan_cap)

    final = _apply_portfolio_diversity(
        ranked=out,
        top_n=top_n,
        n_legs=n_legs,
        min_overs_per_slip=min_overs_per_slip,
        rules=rules,
    )

    keep = ["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility"]
    for c in keep:
        if c not in final.columns:
            final[c] = 0.0
    final = final[keep].reset_index(drop=True)

    return final