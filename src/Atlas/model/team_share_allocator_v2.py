from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from Atlas.core.share_name_key import share_name_key
from Atlas.model.share_matrix_contract import REQUIRED_COLUMNS


STAT_FAMILIES = ("PTS", "REB", "AST")

_TEAM_NAME_TO_ABBR = {
    "ATLANTAHAWKS": "ATL",
    "BOSTONCELTICS": "BOS",
    "BROOKLYNNETS": "BKN",
    "CHARLOTTEHORNETS": "CHA",
    "CHICAGOBULLS": "CHI",
    "CLEVELANDCAVALIERS": "CLE",
    "DALLASMAVERICKS": "DAL",
    "DENVERNUGGETS": "DEN",
    "DETROITPISTONS": "DET",
    "GOLDENSTATEWARRIORS": "GSW",
    "HOUSTONROCKETS": "HOU",
    "INDIANAPACERS": "IND",
    "LACLIPPERS": "LAC",
    "LALAKERS": "LAL",
    "MEMPHISGRIZZLIES": "MEM",
    "MIAMIHEAT": "MIA",
    "MILWAUKEEBUCKS": "MIL",
    "MINNESOTATIMBERWOLVES": "MIN",
    "NEWORLEANSPELICANS": "NOP",
    "NEWYORKKNICKS": "NYK",
    "OKLAHOMACITYTHUNDER": "OKC",
    "ORLANDOMAGIC": "ORL",
    "PHILADELPHIA76ERS": "PHI",
    "PHOENIXSUNS": "PHX",
    "PORTLANDTRAILBLAZERS": "POR",
    "SACRAMENTOKINGS": "SAC",
    "SANANTONIOSPURRS": "SAS",
    "TORONTORAPTORS": "TOR",
    "UTAHJAZZ": "UTA",
    "WASHINGTONWIZARDS": "WAS",
}


@dataclass(frozen=True)
class OutgoingPlayerClass:
    label: str
    transfer_fraction: float
    depth_multiplier: float


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return float(min(upper, max(lower, float(value))))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        result = float(value)
        if not np.isfinite(result):
            return float(default)
        return float(result)
    except Exception:
        return float(default)


def _norm_team(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    up = raw.upper()
    if len(up) == 3 and up.isalpha():
        return up
    key = re.sub(r"[^A-Z]", "", up)
    if key in _TEAM_NAME_TO_ABBR:
        return _TEAM_NAME_TO_ABBR[key]
    return up[:3] if len(up) >= 3 else up


def _stat_alias(stat: str) -> str:
    return {
        "3PM": "PTS",
        "3PTM": "PTS",
        "FG3M": "PTS",
        "FG3": "PTS",
        "3P": "PTS",
    }.get(str(stat or "").upper().strip(), str(stat or "").upper().strip())


def classify_outgoing_player(
    *,
    usage: float,
    minutes: float,
    team_depth: float,
    role_index: float,
    odarko: float = 0.0,
    copm: float = 0.0,
) -> OutgoingPlayerClass:
    """
    Classify the outgoing player by leverage and likely replaceability.

    usage is expected to be a 0..1 share-like value, minutes are raw minutes,
    role_index is normalized to 0..1 within the team.
    odarko/copm are offensive DARKO and CPM ratings from CraftedNBA — higher
    values indicate greater offensive impact that will be missed when out.
    """
    usage = max(0.0, float(usage))
    minutes = max(0.0, float(minutes))
    team_depth = max(0.0, float(team_depth))
    role_index = max(0.0, float(role_index))
    odarko = _safe_float(odarko, 0.0)
    copm = _safe_float(copm, 0.0)

    # Advanced-metric bump: high-impact players (by DARKO/CPM) can be promoted
    # one tier above what box-score usage alone suggests.  The bump is bounded
    # so it cannot skip more than one tier.
    adv_bump = False
    if odarko >= 3.0 or copm >= 3.0:
        adv_bump = True

    if usage >= 0.28 or minutes >= 30.0 or role_index >= 0.75:
        return OutgoingPlayerClass(label="star", transfer_fraction=0.72, depth_multiplier=max(0.35, 1.0 - 0.20 * team_depth))
    if usage >= 0.16 or minutes >= 24.0 or role_index >= 0.50 or (adv_bump and (usage >= 0.12 or minutes >= 20.0)):
        label = "core_adv" if adv_bump and usage < 0.16 and minutes < 24.0 and role_index < 0.50 else "core"
        return OutgoingPlayerClass(label=label, transfer_fraction=0.54, depth_multiplier=max(0.45, 1.0 - 0.15 * team_depth))
    if usage >= 0.08 or minutes >= 14.0 or role_index >= 0.25 or (adv_bump and (usage >= 0.05 or minutes >= 10.0)):
        label = "role_adv" if adv_bump and usage < 0.08 and minutes < 14.0 and role_index < 0.25 else "role"
        return OutgoingPlayerClass(label=label, transfer_fraction=0.32, depth_multiplier=max(0.60, 1.0 - 0.10 * team_depth))
    return OutgoingPlayerClass(label="bench", transfer_fraction=0.12, depth_multiplier=max(0.80, 1.0 - 0.05 * team_depth))


def compute_redistribution_cap(*, base_transfer_fraction: float, team_depth: float, multi_out_penalty: float = 0.0) -> float:
    team_depth = max(0.0, float(team_depth))
    base_transfer_fraction = max(0.0, float(base_transfer_fraction))
    multi_out_penalty = max(0.0, float(multi_out_penalty))
    cap = base_transfer_fraction * max(0.60, 1.0 - multi_out_penalty)
    return float(min(0.95, max(0.0, cap)))


def validate_allocator_output(df: pd.DataFrame) -> None:
    required = set(REQUIRED_COLUMNS)
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"allocator output missing required columns: {missing}")


def _normalize_iael_df(iael_df: pd.DataFrame) -> pd.DataFrame:
    if iael_df is None or not isinstance(iael_df, pd.DataFrame) or iael_df.empty:
        return pd.DataFrame()

    df = iael_df.copy()
    cols = {c.lower(): c for c in df.columns}

    team_col = cols.get("team") or cols.get("team_u") or cols.get("team_norm")
    player_col = cols.get("player") or cols.get("player_norm") or cols.get("out_player") or cols.get("name")
    status_col = cols.get("status") or cols.get("iael_status") or cols.get("injury_status")
    out_frac_col = cols.get("out_frac")

    if not team_col or not player_col:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["team"] = df[team_col].astype(str)
    out["team_u"] = out["team"].map(_norm_team)
    out["player"] = df[player_col].astype(str).str.strip()
    out["player_key"] = out["player"].map(share_name_key)

    if status_col:
        out["status"] = df[status_col].astype(str).str.upper().str.strip()
    else:
        out["status"] = "OUT"

    if out_frac_col:
        out["out_frac"] = pd.to_numeric(df[out_frac_col], errors="coerce").fillna(0.0).clip(lower=0.0)
    else:
        def _out_frac(status: str) -> float:
            if status in {"OUT", "O", "DOUBTFUL", "D"}:
                return 1.0
            if status in {"QUESTIONABLE", "Q"}:
                return 0.5
            return 0.0

        out["out_frac"] = out["status"].map(_out_frac)

    out = out[(out["team_u"] != "") & (out["player_key"] != "") & (out["out_frac"] > 0.0)].copy()
    if out.empty:
        return pd.DataFrame()
    return out.drop_duplicates(subset=["team_u", "player_key", "status"]).reset_index(drop=True)


def _load_json_df(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return pd.DataFrame()
    if isinstance(obj, dict):
        rows = obj.get("invalidated_players") or obj.get("rows") or []
        if isinstance(rows, list) and rows:
            return pd.DataFrame(rows)
    return pd.DataFrame()


def load_iael_snapshot(*, invalidations_path: str | Path | None = None, status_path: str | Path | None = None) -> pd.DataFrame:
    """
    Load the freshest IAEL snapshot available for the current run.

    Priority:
    1. explicit invalidations_path/status_path
    2. ATLAS_IAEL_INVALIDATIONS_PATH / ATLAS_IAEL_STATUS_PATH
    3. ATLAS_IAEL_SNAPSHOT_DIR/{injury_invalidations_latest.json,status_latest.json}
    4. data/output/dashboard/{injury_invalidations_latest.json,status_latest.json}
    """
    candidates: list[Path] = []

    if invalidations_path is not None:
        candidates.append(Path(invalidations_path))
    if status_path is not None:
        candidates.append(Path(status_path))

    env_invalid = os.environ.get("ATLAS_IAEL_INVALIDATIONS_PATH")
    if env_invalid:
        candidates.append(Path(env_invalid))

    env_status = os.environ.get("ATLAS_IAEL_STATUS_PATH")
    if env_status:
        candidates.append(Path(env_status))

    snapshot_dir = os.environ.get("ATLAS_IAEL_SNAPSHOT_DIR")
    if snapshot_dir:
        snap = Path(snapshot_dir)
        candidates.extend([snap / "injury_invalidations_latest.json", snap / "status_latest.json"])

    candidates.extend(
        [
            Path("data") / "output" / "dashboard" / "injury_invalidations_latest.json",
            Path("data") / "output" / "dashboard" / "status_latest.json",
        ]
    )

    for cand in candidates:
        df = _load_json_df(cand)
        if not df.empty:
            normalized = _normalize_iael_df(df)
            if not normalized.empty:
                return normalized

    return pd.DataFrame()


def _normalize_logs(gamelogs: pd.DataFrame, recent_days: int) -> pd.DataFrame:
    if gamelogs is None or not isinstance(gamelogs, pd.DataFrame) or gamelogs.empty:
        return pd.DataFrame()

    required = {"team", "player", "game_date", "minutes", "pts", "reb", "ast"}
    missing = [c for c in required if c not in gamelogs.columns]
    if missing:
        return pd.DataFrame()

    df = gamelogs.copy()
    df["team_u"] = df["team"].astype(str).map(_norm_team)
    df["player"] = df["player"].astype(str).str.strip()
    df["player_key"] = df["player"].map(share_name_key)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.normalize()

    for col in ("minutes", "pts", "reb", "ast"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "usg_proxy" in df.columns:
        df["usg_proxy"] = pd.to_numeric(df["usg_proxy"], errors="coerce").fillna(0.0)
    else:
        df["usg_proxy"] = np.nan

    df = df[(df["team_u"] != "") & (df["player_key"] != "") & df["game_date"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    if int(recent_days) > 0:
        cut = df["game_date"].max()
        if pd.notna(cut):
            df = df[df["game_date"] >= (cut - pd.Timedelta(days=int(recent_days)))].copy()

    if df.empty:
        return pd.DataFrame()

    team_date = df.groupby(["team_u", "game_date"], as_index=False).agg(
        team_pts=("pts", "sum"),
        team_reb=("reb", "sum"),
        team_ast=("ast", "sum"),
        team_min=("minutes", "sum"),
    )
    df = df.merge(team_date, on=["team_u", "game_date"], how="left")

    for stat, team_total in (("pts", "team_pts"), ("reb", "team_reb"), ("ast", "team_ast"), ("minutes", "team_min")):
        share_col = f"{stat}_share"
        df[share_col] = df[stat] / df[team_total].replace({0.0: np.nan})
        df[share_col] = pd.to_numeric(df[share_col], errors="coerce").fillna(0.0).clip(lower=0.0)

    return df


def _team_depth_score(team_base: pd.DataFrame) -> float:
    if team_base is None or team_base.empty:
        return 0.0
    minutes = pd.to_numeric(team_base["avg_min"], errors="coerce").fillna(0.0).clip(lower=0.0)
    total = float(minutes.sum())
    if total <= 0:
        return 0.0
    shares = minutes / total
    hhi = float((shares ** 2).sum())
    return _clamp(1.0 - hhi, 0.0, 1.0)


def _player_role_index(team_base: pd.DataFrame, player_key: str) -> float:
    if team_base is None or team_base.empty or "avg_min" not in team_base.columns:
        return 0.0
    team_max = float(pd.to_numeric(team_base["avg_min"], errors="coerce").fillna(0.0).max())
    if team_max <= 0:
        return 0.0
    row = team_base.loc[team_base["player_key"] == player_key]
    if row.empty:
        return 0.0
    return _clamp(float(row.iloc[0]["avg_min"]) / team_max, 0.0, 1.0)


def _stat_mix_for_out(out_row: pd.Series) -> dict[str, float]:
    raw = {stat: max(0.0, _safe_float(out_row.get(f"avg_{stat.lower()}_share", 0.0))) for stat in STAT_FAMILIES}
    total = float(sum(raw.values()))
    if total <= 0:
        return {stat: 1.0 / len(STAT_FAMILIES) for stat in STAT_FAMILIES}
    return {stat: raw[stat] / total for stat in STAT_FAMILIES}


def _candidate_score(row: pd.Series, stat_u: str, team_max_min: float) -> float:
    stat_share = max(0.0, _safe_float(row.get(f"avg_{stat_u.lower()}_share", 0.0)))
    min_share = 0.0
    if team_max_min > 0:
        min_share = max(0.0, _safe_float(row.get("avg_min", 0.0)) / team_max_min)
    role_headroom = 0.40 + 0.60 * _clamp(float(row.get("role_index", 0.0)), 0.0, 1.0)

    # Advanced-metric capability boost: players with higher offensive DARKO or
    # DRIP projections are better positioned to absorb extra production.
    # The boost is multiplicative and capped at 1.25x so it nudges without
    # overwhelming the box-score signal.
    odarko = _safe_float(row.get("odarko", 0.0), 0.0)
    drip_off = _safe_float(row.get("drip_offense", 0.0), 0.0)
    adv_best = max(odarko, drip_off)
    if adv_best >= 1.0:
        # Linear ramp from 1.0x at adv_best=1.0 to 1.25x at adv_best>=5.0
        adv_mult = 1.0 + 0.0625 * min(adv_best - 1.0, 4.0)
    else:
        adv_mult = 1.0

    raw = (0.70 * stat_share + 0.30 * min_share) * role_headroom * adv_mult
    return max(0.0, raw)


def _finalize_share_matrix(
    df: pd.DataFrame,
    *,
    min_pattern_games: int,
    keep_zero_weights: bool,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    out = df.copy()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    out["games"] = pd.to_numeric(out["games"], errors="coerce").fillna(0).astype(int)

    if not keep_zero_weights:
        out = out[out["weight"] > 1e-12].copy()

    if int(min_pattern_games) > 0:
        out = out[out["games"] >= int(min_pattern_games)].copy()

    if out.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    out = out.reset_index(drop=True)
    validate_allocator_output(out)
    return out


def build_share_matrix_v2(
    gamelogs: pd.DataFrame,
    *,
    iael_df: pd.DataFrame | None = None,
    role_metrics_df: pd.DataFrame | None = None,
    recent_days: int = 140,
    min_rotation_games: int = 6,
    min_rotation_avg_min: float = 8.0,
    min_pattern_games: int = 3,
    keep_zero_weights: bool = False,
) -> pd.DataFrame:
    """
    Build a run-scoped share matrix from fresh gamelogs and the current IAEL snapshot.

    The allocator is intentionally conservative:
    - higher leverage injuries export more share
    - deeper teams absorb less of that share
    - multiple outs reduce the redistributable budget

    role_metrics_df (optional): CraftedNBA snapshot with odarko, copm, drip_offense
    columns keyed by player_key.  Used to improve outgoing-player classification
    and candidate absorption scoring.
    """
    logs = _normalize_logs(gamelogs, recent_days=recent_days)
    if logs.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    if iael_df is None or iael_df.empty:
        iael = load_iael_snapshot()
    else:
        iael = _normalize_iael_df(iael_df)

    if iael.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    active = logs[logs["minutes"] > 0].copy()
    if active.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    base = active.groupby(["team_u", "player_key"], as_index=False).agg(
        player=("player", "last"),
        games=("game_date", "nunique"),
        avg_min=("minutes", "mean"),
        avg_pts=("pts", "mean"),
        avg_reb=("reb", "mean"),
        avg_ast=("ast", "mean"),
        avg_pts_share=("pts_share", "mean"),
        avg_reb_share=("reb_share", "mean"),
        avg_ast_share=("ast_share", "mean"),
    )
    if base.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    team_max_minutes = base.groupby("team_u")["avg_min"].max().to_dict()
    base["role_index"] = base.apply(lambda r: _player_role_index(base.loc[base["team_u"] == r["team_u"]], r["player_key"]), axis=1)

    # Merge CraftedNBA advanced metrics (DARKO, CPM, DRIP) onto base for
    # smarter outgoing-player classification and candidate absorption scoring.
    _ADV_COLS = ["odarko", "copm", "drip_offense"]
    for col in _ADV_COLS:
        base[col] = 0.0
    if role_metrics_df is not None and not role_metrics_df.empty:
        rm = role_metrics_df.copy()
        if "player_key" not in rm.columns and "player" in rm.columns:
            rm["player_key"] = rm["player"].astype(str).map(share_name_key)
        if "player_key" in rm.columns:
            avail = [c for c in _ADV_COLS if c in rm.columns]
            if avail:
                rm_dedup = rm.drop_duplicates(subset=["player_key"], keep="last")
                merge_cols = ["player_key"] + avail
                base = base.merge(
                    rm_dedup[merge_cols].rename(columns={c: f"_rm_{c}" for c in avail}),
                    on="player_key",
                    how="left",
                )
                for c in avail:
                    base[c] = pd.to_numeric(base[f"_rm_{c}"], errors="coerce").fillna(0.0)
                    base.drop(columns=[f"_rm_{c}"], inplace=True)

    base_lookup = {
        (str(r["team_u"]), str(r["player_key"])): r
        for _, r in base.iterrows()
    }

    rows: list[dict[str, Any]] = []

    for team_u, team_ia in iael.groupby("team_u"):
        team_u = str(team_u)
        team_base = base[base["team_u"] == team_u].copy()
        if team_base.empty:
            continue

        team_depth = _team_depth_score(team_base)
        team_max_min = float(team_max_minutes.get(team_u, 0.0) or 0.0)
        if team_max_min <= 0:
            team_max_min = float(pd.to_numeric(team_base["avg_min"], errors="coerce").fillna(0.0).max() or 1.0)

        team_candidates = team_base.copy()
        team_candidates = team_candidates[team_candidates["player_key"].isin(team_base["player_key"].tolist())].copy()
        if team_candidates.empty:
            continue

        outs = team_ia[team_ia["out_frac"] > 0].copy()
        if outs.empty:
            continue

        out_keys = {str(v) for v in outs["player_key"].tolist()}
        if out_keys:
            team_candidates = team_candidates[~team_candidates["player_key"].isin(out_keys)].copy()
        if team_candidates.empty:
            continue

        n_outs = int(len(outs))
        multi_out_penalty = min(0.55, max(0.0, 0.12 * max(0, n_outs - 1)))

        candidate_map = {
            str(r["player_key"]): r
            for _, r in team_candidates.iterrows()
        }

        for _, out_row in outs.iterrows():
            out_key = str(out_row["player_key"])
            out_base = base_lookup.get((team_u, out_key))
            if out_base is None:
                continue

            out_avg_min = _safe_float(out_base.get("avg_min", 0.0))
            out_usage = float(np.nanmean([
                _safe_float(out_base.get("avg_pts_share", np.nan), default=np.nan),
                _safe_float(out_base.get("avg_reb_share", np.nan), default=np.nan),
                _safe_float(out_base.get("avg_ast_share", np.nan), default=np.nan),
            ]))
            if not np.isfinite(out_usage):
                out_usage = 0.0

            role_index = _clamp(out_avg_min / team_max_min if team_max_min > 0 else 0.0, 0.0, 1.0)
            cls = classify_outgoing_player(
                usage=out_usage,
                minutes=out_avg_min,
                team_depth=team_depth,
                role_index=role_index,
                odarko=_safe_float(out_base.get("odarko", 0.0)),
                copm=_safe_float(out_base.get("copm", 0.0)),
            )
            out_frac = _clamp(_safe_float(out_row.get("out_frac", 0.0)), 0.0, 1.0)
            transfer = compute_redistribution_cap(
                base_transfer_fraction=cls.transfer_fraction * out_frac * cls.depth_multiplier,
                team_depth=team_depth,
                multi_out_penalty=multi_out_penalty,
            )
            if transfer <= 0:
                continue

            stat_mix = _stat_mix_for_out(out_base)
            out_display = str(out_base.get("player", out_row.get("player", out_key)))
            out_canon = share_name_key(out_display)
            team_label = str(out_row.get("team_u", team_u))

            for stat_u in STAT_FAMILIES:
                stat_share = float(stat_mix.get(stat_u, 0.0))
                if stat_share <= 0:
                    continue

                candidate_scores: dict[str, float] = {}
                for cand_key, cand_row in candidate_map.items():
                    if cand_key == out_key:
                        continue
                    candidate_scores[cand_key] = _candidate_score(cand_row, stat_u, team_max_min)

                total_score = float(sum(candidate_scores.values()))
                if total_score <= 0:
                    count = max(1, len(candidate_scores))
                    candidate_scores = {k: 1.0 / count for k in candidate_scores.keys()}
                    total_score = 1.0

                for cand_key, score in candidate_scores.items():
                    cand_row = candidate_map[cand_key]
                    weight = transfer * stat_share * (score / total_score)
                    if weight <= 0:
                        continue

                    out_games = int(_safe_float(out_base.get("games", 0.0), default=0.0))
                    cand_games = int(_safe_float(cand_row.get("games", 0.0), default=0.0))
                    support_games = max(1, min(out_games, cand_games))

                    rows.append(
                        {
                            "team": team_label,
                            "out_player": out_display,
                            "beneficiary_player": str(cand_row.get("player", cand_key)),
                            "stat": stat_u,
                            "games": support_games,
                            "weight": float(weight),
                            "team_u": team_label,
                            "stat_u": stat_u,
                            "out_canon": out_canon,
                            "ben_canon": share_name_key(str(cand_row.get("player", cand_key))),
                        }
                    )

    if not rows:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    out = pd.DataFrame(rows)
    out = (
        out.groupby(["team", "out_player", "beneficiary_player", "stat"], as_index=False)
        .agg(
            games=("games", "max"),
            weight=("weight", "sum"),
            team_u=("team_u", "first"),
            stat_u=("stat_u", "first"),
            out_canon=("out_canon", "first"),
            ben_canon=("ben_canon", "first"),
        )
        .reset_index(drop=True)
    )

    return _finalize_share_matrix(out, min_pattern_games=min_pattern_games, keep_zero_weights=keep_zero_weights)
