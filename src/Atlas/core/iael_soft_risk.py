from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd


def apply_iael_soft_risk(scored: pd.DataFrame, iael_df: pd.DataFrame) -> pd.DataFrame:
    """Tag QUESTIONABLE exposure as soft risk without dropping or changing math."""

    out = scored.copy()
    try:
        from Atlas.core.iael_filter import normalize_person_name

        _ia = iael_df.copy() if iael_df is not None else pd.DataFrame()
        _ia["status"] = _ia["status"].astype(str).str.upper() if "status" in _ia.columns else ""
        _q = _ia[_ia["status"] == "QUESTIONABLE"].copy()

        def _norm_name(value: object) -> str:
            return str(normalize_person_name(value)).strip().lower()

        if _q.empty or "player" not in out.columns:
            out["is_questionable"] = 0
            out["q_out_frac"] = 0.0
            return out

        q_players = set(_q["player"].apply(_norm_name).astype(str)) if "player" in _q.columns else set()
        q_player_teams: dict[str, set[str]] = {}
        if "player" in _q.columns:
            team_col = "team_norm" if "team_norm" in _q.columns else ("team" if "team" in _q.columns else "")
            if team_col:
                _q["_team_u"] = _q[team_col].astype(str).str.upper().str.strip()
                for pn, teams in _q.groupby(_q["player"].apply(_norm_name).astype(str))["_team_u"]:
                    q_player_teams[str(pn)] = {str(team).upper().strip() for team in teams if str(team).strip()}

        q_map: dict[str, float] = {}
        if "player" in _q.columns:
            _q["_pn"] = _q["player"].apply(_norm_name).astype(str)
            if "out_frac" in _q.columns:
                q_out_frac = pd.to_numeric(_q["out_frac"], errors="coerce").fillna(0.0).astype(float)
                _q["_q_soft"] = q_out_frac.where(q_out_frac > 0.0, 0.5)
                q_map.update({str(k): float(v) for k, v in _q.groupby("_pn")["_q_soft"].max().astype(float).to_dict().items()})
            for pn in _q["_pn"].dropna().astype(str):
                q_map.setdefault(pn, 0.5)

        q_beneficiary_keys = _questionable_beneficiary_keys(q_players, _norm_name)

        has_role_outs = "role_ctx_outs" in out.columns
        candidate_col = "role_ctx_outs" if has_role_outs else "player"

        q_flags: list[int] = []
        q_fracs: list[float] = []
        for _, row in out.iterrows():
            names = _parse_name_list(row.get(candidate_col))
            if not names and candidate_col != "player":
                names = _parse_name_list(row.get("player"))

            row_team = str(row.get("team", "")).upper().strip()
            matched = [
                _norm_name(name)
                for name in names
                if _norm_name(name) in q_players
                and (not q_player_teams.get(_norm_name(name)) or row_team in q_player_teams.get(_norm_name(name), set()))
            ]
            row_stat = str(row.get("stat", row.get("stat_raw", ""))).upper().strip()
            row_player = _norm_name(row.get("player", ""))
            beneficiary_hit = (row_team, row_stat, row_player) in q_beneficiary_keys

            if matched or beneficiary_hit:
                q_flags.append(1)
                if matched:
                    q_fracs.append(max(float(q_map.get(name, 0.5)) for name in set(matched)))
                else:
                    q_fracs.append(0.5)
            else:
                q_flags.append(0)
                q_fracs.append(0.0)

        out["is_questionable"] = pd.Series(q_flags, index=out.index).astype(int)
        out["q_out_frac"] = pd.Series(q_fracs, index=out.index).astype(float)

        q_legs = int(out["is_questionable"].sum())
        if q_legs > 0:
            top = (
                out[out["is_questionable"] == 1]
                .groupby("player")
                .size()
                .sort_values(ascending=False)
                .head(10)
            )
            print(f"[IAEL][SOFT] QUESTIONABLE legs={q_legs} players={len(top)} (top10 by leg count):")
            print(top.to_string())
        return out
    except Exception as exc:
        out["is_questionable"] = 0
        out["q_out_frac"] = 0.0
        print(f"[IAEL][SOFT][WARN] soft-risk tagging skipped: {exc}")
        return out


def _questionable_beneficiary_keys(q_players: set[str], norm_name) -> set[tuple[str, str, str]]:
    q_beneficiary_keys: set[tuple[str, str, str]] = set()
    share_matrix_path = Path("data") / "model" / "share_matrix.csv"
    if not share_matrix_path.exists():
        return q_beneficiary_keys
    try:
        share_matrix = pd.read_csv(share_matrix_path, low_memory=False)
        if share_matrix.empty or not {"team", "out_player", "beneficiary_player", "stat"}.issubset(share_matrix.columns):
            return q_beneficiary_keys
        sm = share_matrix.copy()
        sm["team_u"] = sm["team"].astype(str).str.upper().str.strip()
        sm["out_canon"] = sm["out_player"].apply(norm_name)
        sm["ben_canon"] = sm["beneficiary_player"].apply(norm_name)
        sm["stat_u"] = sm["stat"].astype(str).str.upper().str.strip()
        impacted = sm[sm["out_canon"].isin(q_players)].copy()
        if not impacted.empty:
            q_beneficiary_keys = set(zip(impacted["team_u"], impacted["stat_u"], impacted["ben_canon"]))
    except Exception:
        return set()
    return q_beneficiary_keys


def _parse_name_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]

    text = str(value).strip()
    if not text or text in {"[]", "nan", "None"}:
        return []

    try:
        parsed = ast.literal_eval(text)
    except Exception:
        parsed = text

    if isinstance(parsed, (list, tuple, set)):
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(parsed, str):
        raw = parsed.strip()
        if not raw:
            return []
        for sep in ("|", ";", ","):
            if sep in raw:
                return [part.strip() for part in raw.split(sep) if part.strip()]
        return [raw]
    return [str(parsed)]
