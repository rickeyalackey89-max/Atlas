"""tools/oracle_tuner.py

Oracle Tuner: read a run folder + config.yaml and print diagnostics + knob suggestions.

Usage:
  py tools/oracle_tuner.py --run-id 20260302_055941
  py tools/oracle_tuner.py --run-dir data/output/runs/20260302_055941 --config config.yaml

This tool is READ-ONLY by default. Use --write-report to emit JSON into .atlas_audit/diagnostics.
"""

from __future__ import annotations

import argparse
import json
import re
import math
from pathlib import Path
from typing import Any, cast, Iterator, Tuple

import pandas as pd
import numpy as np
import yaml

# -------------------------
# Oracle rule helpers
# -------------------------

def _safe_get(d: dict, key: str, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default

def _as_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _med(stats: dict) -> float | None:
    # Oracle slip stats objects typically carry hit_prob quantiles
    # Use median if present, else fallback to p50, else None.
    return _as_float(stats.get("hp_med") or stats.get("hit_prob_med") or stats.get("p50") or stats.get("median"), None)

def _ev_med(stats: dict) -> float | None:
    return _as_float(stats.get("ev_med") or stats.get("ev_mult_med") or stats.get("median_ev") or stats.get("ev_median"), None)

def _name_key(path_or_name: str) -> str:
    # Normalize file name keys, just in case caller passes full path
    return str(path_or_name).replace("\\", "/").split("/")[-1]

def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding='utf-8')) or {}


def _resolve_iael_path_for_run(run_dir: Path, root: Path) -> Path:
    candidate_status = [
        run_dir / "dashboard" / "status_latest.json",
        run_dir.parent / "dashboard" / "status_latest.json",
        run_dir.parent.parent / "dashboard" / "status_latest.json",
    ]
    for p in candidate_status:
        if p.exists():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                doc = None
            if isinstance(doc, dict):
                norm_path = doc.get("norm_path")
                if norm_path:
                    np = Path(str(norm_path))
                    if np.exists():
                        return np

    candidate_meta = [
        run_dir / "meta.json",
        run_dir.parent / "meta.json",
        run_dir.parent.parent / "meta.json",
    ]
    for p in candidate_meta:
        if p.exists():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                doc = None
            if isinstance(doc, dict):
                injury_snapshot_path = doc.get("injury_snapshot_path")
                if injury_snapshot_path:
                    ip = Path(str(injury_snapshot_path))
                    if ip.exists():
                        return ip

    raise FileNotFoundError(
        f"No run-specific injury snapshot found for run_dir={run_dir}. "
        "Checked dashboard/status_latest.json -> norm_path and meta.json -> injury_snapshot_path."
    )


def _player_key(x: str | None) -> str:
    s = str(x or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def _iael_team_to_abbrev(team: str | None) -> str | None:
    if not team:
        return None
    t = str(team).strip()

    # IAEL seems to use CamelCase full names like "BostonCeltics"
    # Map those to standard NBA abbreviations used in scored_legs_deduped ("BOS", "DAL", etc.)
    MAP = {
        "AtlantaHawks": "ATL",
        "BostonCeltics": "BOS",
        "BrooklynNets": "BKN",
        "CharlotteHornets": "CHA",
        "ChicagoBulls": "CHI",
        "ClevelandCavaliers": "CLE",
        "DallasMavericks": "DAL",
        "DenverNuggets": "DEN",
        "DetroitPistons": "DET",
        "GoldenStateWarriors": "GSW",
        "HoustonRockets": "HOU",
        "IndianaPacers": "IND",
        "LAClippers": "LAC",
        "LosAngelesClippers": "LAC",
        "LALakers": "LAL",
        "LosAngelesLakers": "LAL",
        "MemphisGrizzlies": "MEM",
        "MiamiHeat": "MIA",
        "MilwaukeeBucks": "MIL",
        "MinnesotaTimberwolves": "MIN",
        "NewOrleansPelicans": "NOP",
        "NewYorkKnicks": "NYK",
        "OklahomaCityThunder": "OKC",
        "OrlandoMagic": "ORL",
        "Philadelphia76ers": "PHI",
        "PhoenixSuns": "PHX",
        "PortlandTrailBlazers": "POR",
        "SacramentoKings": "SAC",
        "SanAntonioSpurs": "SAS",
        "TorontoRaptors": "TOR",
        "UtahJazz": "UTA",
        "WashingtonWizards": "WAS",
    }

    # quick direct hit
    if t in MAP:
        return MAP[t]

    # tolerate spacing/underscores/hyphens
    t2 = t.replace(" ", "").replace("_", "").replace("-", "")
    if t2 in MAP:
        return MAP[t2]

    # if IAEL ever returns abbrev already, pass through
    if len(t2) == 3 and t2.isalpha():
        return t2.upper()

    return None


def _artifact_team_to_abbrev(team: str | None) -> str | None:
    if not team:
        return None

    raw = str(team).strip()
    if not raw:
        return None

    # preserve letters only, case-insensitive
    t = re.sub(r"[^A-Za-z]", "", raw)
    if not t:
        return None

    tu = t.upper()

    # already an abbreviation
    if len(tu) == 3 and tu.isalpha():
        return tu

    # accept common artifact spellings / full names / nicknames
    ARTIFACT_MAP = {
        "ATL": "ATL",
        "ATLANTA": "ATL",
        "ATLANTAHAWKS": "ATL",

        "BOS": "BOS",
        "BOSTON": "BOS",
        "BOSTONCELTICS": "BOS",

        "BKN": "BKN",
        "BROOKLYN": "BKN",
        "BROOKLYNNETS": "BKN",

        "CHA": "CHA",
        "CHARLOTTE": "CHA",
        "CHARLOTTEHORNETS": "CHA",

        "CHI": "CHI",
        "CHICAGO": "CHI",
        "CHICAGOBULLS": "CHI",

        "CLE": "CLE",
        "CLEVELAND": "CLE",
        "CLEVELANDCAVALIERS": "CLE",

        "DAL": "DAL",
        "DALLAS": "DAL",
        "DALLASMAVERICKS": "DAL",

        "DEN": "DEN",
        "DENVER": "DEN",
        "DENVERNUGGETS": "DEN",

        "DET": "DET",
        "DETROIT": "DET",
        "DETROITPISTONS": "DET",

        "GSW": "GSW",
        "GOLDENSTATE": "GSW",
        "GOLDENSTATEWARRIORS": "GSW",

        "HOU": "HOU",
        "HOUSTON": "HOU",
        "HOUSTONROCKETS": "HOU",

        "IND": "IND",
        "INDIANA": "IND",
        "INDIANAPACERS": "IND",

        "LAC": "LAC",
        "LACLIPPERS": "LAC",
        "LOSANGELESCLIPPERS": "LAC",
        "CLIPPERS": "LAC",

        "LAL": "LAL",
        "LALAKERS": "LAL",
        "LOSANGELESLAKERS": "LAL",
        "LAKERS": "LAL",

        "MEM": "MEM",
        "MEMPHIS": "MEM",
        "MEMPHISGRIZZLIES": "MEM",

        "MIA": "MIA",
        "MIAMI": "MIA",
        "MIAMIHEAT": "MIA",

        "MIL": "MIL",
        "MILWAUKEE": "MIL",
        "MILWAUKEEBUCKS": "MIL",

        "MIN": "MIN",
        "MINNESOTA": "MIN",
        "MINNESOTATIMBERWOLVES": "MIN",

        "NOP": "NOP",
        "NEWORLEANS": "NOP",
        "NEWORLEANSPelicans".upper(): "NOP",
        "PELICANS": "NOP",

        "NYK": "NYK",
        "NEWYORK": "NYK",
        "NEWYORKKNICKS": "NYK",
        "KNICKS": "NYK",

        "OKC": "OKC",
        "OKLAHOMACITY": "OKC",
        "OKLAHOMACITYTHUNDER": "OKC",
        "THUNDER": "OKC",

        "ORL": "ORL",
        "ORLANDO": "ORL",
        "ORLANDOMAGIC": "ORL",

        "PHI": "PHI",
        "PHILADELPHIA": "PHI",
        "PHILADELPHIA76ERS": "PHI",
        "SIXERS": "PHI",

        "PHX": "PHX",
        "PHOENIX": "PHX",
        "PHOENIXSUNS": "PHX",
        "SUNS": "PHX",

        "POR": "POR",
        "PORTLAND": "POR",
        "PORTLANDTRAILBLAZERS": "POR",
        "TRAILBLAZERS": "POR",
        "BLAZERS": "POR",

        "SAC": "SAC",
        "SACRAMENTO": "SAC",
        "SACRAMENTOKINGS": "SAC",
        "KINGS": "SAC",

        "SAS": "SAS",
        "SANANTONIO": "SAS",
        "SANANTONIOSPURS": "SAS",
        "SPURS": "SAS",

        "TOR": "TOR",
        "TORONTO": "TOR",
        "TORONTORAPTORS": "TOR",
        "RAPTORS": "TOR",

        "UTA": "UTA",
        "UTAH": "UTA",
        "UTAHJAZZ": "UTA",
        "JAZZ": "UTA",

        "WAS": "WAS",
        "WASHINGTON": "WAS",
        "WASHINGTONWIZARDS": "WAS",
        "WIZARDS": "WAS",
    }

    return ARTIFACT_MAP.get(tu)


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def _quantiles(s: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(s, errors='coerce')
    s = s.dropna()
    if len(s) == 0:
        return {}
    return {
        'min': float(s.min()),
        'p01': float(s.quantile(0.01)),
        'p05': float(s.quantile(0.05)),
        'p25': float(s.quantile(0.25)),
        'med': float(s.median()),
        'p75': float(s.quantile(0.75)),
        'p95': float(s.quantile(0.95)),
        'max': float(s.max()),
    }



def _std_iqr(s: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) == 0:
        return {}
    q25 = float(s.quantile(0.25))
    q75 = float(s.quantile(0.75))
    return {
        "std": float(np.std(s.to_numpy(dtype=float), ddof=0)),
        "iqr": float(q75 - q25),
    }

def _iter_leg_cols(df: pd.DataFrame) -> list[str]:
    leg_cols = [c for c in df.columns if str(c).lower().startswith("leg_")]
    leg_cols = sorted(
        leg_cols,
        key=lambda x: int(str(x).split("_")[1]) if str(x).split("_")[1].isdigit() else 9999,
    )
    return leg_cols

def _split_legs_blob(blob: str) -> list[str]:
    if not isinstance(blob, str):
        return []
    s = blob.strip()
    if not s:
        return []
    if " | " in s:
        parts = [p.strip() for p in s.split(" | ")]
    elif "|" in s:
        parts = [p.strip() for p in s.split("|")]
    else:
        parts = [s]
    return [p for p in parts if p]

_TIER_RE = re.compile(r"\((STANDARD|GOBLIN|DEMON)\)", re.IGNORECASE)

def _extract_tier_from_leg_blob(leg: str) -> str | None:
    m = _TIER_RE.search(leg or "")
    return m.group(1).upper() if m else None

def _extract_player_from_leg_blob(leg: str) -> str | None:
    if not isinstance(leg, str):
        return None
    if " OVER " in leg:
        return leg.split(" OVER ", 1)[0].strip() or None
    if " UNDER " in leg:
        return leg.split(" UNDER ", 1)[0].strip() or None
    return None

def _tier_mix_from_slips(df: pd.DataFrame) -> dict[str, int]:
    counts = {"STANDARD": 0, "GOBLIN": 0, "DEMON": 0, "OTHER": 0}

    leg_cols = _iter_leg_cols(df)
    if leg_cols:
        for c in leg_cols:
            for v in df[c].dropna().astype(str).tolist():
                tier = None
                if "|" in v:
                    parts = v.split("|")
                    if len(parts) >= 4:
                        tier = parts[3].strip().upper()
                if not tier:
                    tier = _extract_tier_from_leg_blob(v)
                if not tier:
                    continue
                if tier in counts:
                    counts[tier] += 1
                else:
                    counts["OTHER"] += 1
        return counts

    legs_col = _find_col(df, ["legs"])
    if not legs_col:
        return counts

    for blob in df[legs_col].dropna().astype(str).tolist():
        for leg in _split_legs_blob(blob):
            tier = _extract_tier_from_leg_blob(leg)
            if not tier:
                continue
            if tier in counts:
                counts[tier] += 1
            else:
                counts["OTHER"] += 1
    return counts

def _player_exposure_from_slips(df: pd.DataFrame) -> dict[str, Any]:
    exp: dict[str, int] = {}
    leg_cols = _iter_leg_cols(df)

    if leg_cols:
        for _, row in df.iterrows():
            seen = set()
            for c in leg_cols:
                v = row.get(c, None)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    continue
                s = str(v)
                player = None
                if "|" in s:
                    parts = s.split("|")
                    if len(parts) >= 2:
                        player = parts[1].strip()
                if not player:
                    player = _extract_player_from_leg_blob(s)
                if player:
                    seen.add(player)
            for p in seen:
                exp[p] = exp.get(p, 0) + 1
    else:
        legs_col = _find_col(df, ["legs"])
        if not legs_col:
            return {"players": 0, "max": 0, "top10": []}
        for blob in df[legs_col].dropna().astype(str).tolist():
            seen = set()
            for leg in _split_legs_blob(blob):
                player = _extract_player_from_leg_blob(leg)
                if player:
                    seen.add(player)
            for p in seen:
                exp[p] = exp.get(p, 0) + 1

    if not exp:
        return {"players": 0, "max": 0, "top10": []}

    top = sorted(exp.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return {
        "players": int(len(exp)),
        "max": int(max(exp.values())),
        "top10": [{"player": k, "count": int(v)} for k, v in top],
    }


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None

def _read_json(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def analyze(run_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {'run_dir': str(run_dir)}

    # Load legs
    legs_path = run_dir / 'scored_legs_deduped.csv'
    legs = _read_csv(legs_path)
    if legs is None:
        out['legs_error'] = f'missing_or_unreadable:{legs_path}'
        legs = pd.DataFrame()

    # ----------------------------
    # IAEL coverage audit (Goal 1)
    # ----------------------------
    ROOT = Path(__file__).resolve().parents[1]
    IAEL_MISS_P_ADJ_CUTOFF = 0.70
    IAEL_PLAYER_OUT_FRAC_THRESHOLD = 0.08  # Gate: require >= 8% out_frac to be eligible
    iael_path = _resolve_iael_path_for_run(run_dir=run_dir, root=ROOT)

    iael_audit: dict[str, Any] = {
        "iael_path": str(iael_path),
        "cutoff_p_adj": IAEL_MISS_P_ADJ_CUTOFF,
        "player_out_frac_threshold": IAEL_PLAYER_OUT_FRAC_THRESHOLD,
    }

    iael_doc = _read_json(iael_path)
    if iael_doc is None:
        iael_audit["error"] = f"missing_or_unreadable:{iael_path}"
        out["iael_audit"] = iael_audit
    else:
        # meta (best-effort; tolerate schema drift)
        meta = {}
        for k in ["report_label", "pulled_at_local", "url", "source_url", "report_date", "report_time"]:
            if k in iael_doc:
                meta[k] = iael_doc.get(k)
        iael_audit["meta"] = meta

        rows = iael_doc.get("rows", []) or iael_doc.get("data", []) or []
        if not isinstance(rows, list):
            rows = []
        
        # IAEL "hard invalid" teams + players (outs/injuries)
        hard_rows = [r for r in rows if isinstance(r, dict) and r.get("hard_invalid") is True]
        impact_rows = []

        teams_with_outs = sorted({t for r in hard_rows if (t := _iael_team_to_abbrev(r.get("team")))})
        # teams_with_impact_outs will be computed from eligible_out_players after gating
        teams_with_impact_outs = []

        iael_audit["n_teams_with_hard_invalids"] = int(len(teams_with_outs))
        iael_audit["n_teams_with_impact_outs"] = int(len(teams_with_impact_outs))

        # sample raw team names from the IAEL document (fallback safe)
        teams_raw = [r.get("team") for r in rows if isinstance(r, dict) and r.get("team")]
        iael_audit["iael_raw_team_sample"] = teams_raw[:25]
        iael_audit["teams_with_hard_invalids_abbrev"] = teams_with_outs

        out_players_by_team_all: dict[str, list[str]] = {}

        for r in hard_rows:
            t_raw = r.get("team")
            p = r.get("player")
            t = _iael_team_to_abbrev(t_raw) if t_raw else None
            if t and p:
                out_players_by_team_all.setdefault(t, []).append(p)

        def _iael_is_impact_out(r: dict) -> bool:
            # STRICT: only count as impact if reason indicates a real NBA availability event.
            status = str(r.get("status") or "").strip().lower()
            reason = str(r.get("reason") or "").strip().lower()

            # probable is never impact
            if status == "probable" or r.get("tag_probable") is True:
                return False

            # Only consider these statuses as "outs context"
            # (IAEL hard_invalid rows may include other labels; keep strict)
            allowed_status = {"out", "doubtful", "questionable"}
            if status and status not in allowed_status:
                return False

            # If reason is missing, strict mode => do NOT treat as impact
            if not reason:
                return False

            # Exclude obvious non-impact categories
            non_impact = [
                "gleague", "g league", "g-league",
                "two-way", "two way",
                "assignment", "on assignment",
                "g league two-way", "gleague-two-way",
            ]
            if any(k in reason for k in non_impact):
                return False

            # Include only real availability categories
            impact = [
                "injury", "illness", "soreness",
                "sprain", "strain", "fracture", "concussion",
                "impingement",
                "rest", "suspension",
                "not with team", "personal", "family",
                "return to competition", "conditioning",
                # common body parts to catch terse reasons
                "ankle", "knee", "hamstring", "groin", "back", "foot", "wrist", "shoulder",
            ]
            return any(k in reason for k in impact)

        # Recompute impact rows now that the helper is defined, and populate impact maps
        impact_rows = [r for r in hard_rows if _iael_is_impact_out(r)]

        role_allocator_cfg = (cfg.get("role_allocator") or {}) if isinstance(cfg, dict) else {}
        role_ctx_cfg = (cfg.get("role_ctx") or {}) if isinstance(cfg, dict) else {}

        TEAMSHARE_MIN_GAMES_FOR_PATTERN = int(
            role_allocator_cfg.get("min_games_for_pattern")
            or role_ctx_cfg.get("min_games_for_pattern")
            or 8
        )
        TEAMSHARE_REL_EFFECTIVE_THRESHOLD = float(
            role_allocator_cfg.get("teamshare_rel_effective_threshold")
            or role_ctx_cfg.get("teamshare_rel_effective_threshold")
            or 0.25
        )

        share_matrix = pd.DataFrame()
        share_players_by_team: dict[str, set[str]] = {}
        sm_team_col: str | None = None
        sm_stat_col: str | None = None
        sm_player_col: str | None = None
        sm_games_col: str | None = None

        try:
            sm_path = Path("data/model/share_matrix.csv")
            if sm_path.exists():
                share_matrix = pd.read_csv(sm_path)

                sm_team_col = _find_col(share_matrix, ["team", "team_abbrev", "team_u"])
                sm_stat_col = _find_col(share_matrix, ["stat", "stat_type"])
                sm_player_col = _find_col(share_matrix, ["out_player", "player", "player_name", "name", "player_key"])
                sm_games_col = _find_col(share_matrix, ["games", "n_games", "games_played"])

                if sm_team_col and sm_player_col:
                    tmp = share_matrix[[sm_team_col, sm_player_col]].copy()
                    tmp[sm_team_col] = tmp[sm_team_col].astype(str).str.strip().str.upper()
                    tmp[sm_player_col] = tmp[sm_player_col].astype(str).str.strip().map(_player_key)
                    for t, g in tmp.groupby(sm_team_col):
                        share_players_by_team[str(t)] = set(g[sm_player_col].dropna().tolist())
        except Exception:
            share_matrix = pd.DataFrame()
            share_players_by_team = {}
            sm_team_col = None
            sm_stat_col = None
            sm_player_col = None
            sm_games_col = None


        def _teamshare_support_stats_oracle(*, team_u: str, stat_u: str, out_list: list[tuple[str, float]]) -> dict[str, float]:
            if share_matrix is None or share_matrix.empty or not out_list:
                return {
                    "supported_outs": 0.0,
                    "effective_outs": 0.0,
                    "rel_wmean": 0.0,
                    "rel_min": float("nan"),
                    "rel_max": float("nan"),
                }

            if not (sm_team_col and sm_stat_col and sm_player_col and sm_games_col):
                return {
                    "supported_outs": 0.0,
                    "effective_outs": 0.0,
                    "rel_wmean": 0.0,
                    "rel_min": float("nan"),
                    "rel_max": float("nan"),
                }

            sm = share_matrix
            team_ser = sm[sm_team_col].astype(str).str.upper().str.strip()
            stat_ser = sm[sm_stat_col].astype(str).str.upper().str.strip()
            out_ser = sm[sm_player_col].astype(str).str.strip().map(_player_key)
            games_ser = pd.to_numeric(sm[sm_games_col], errors="coerce")

            base = (team_ser == str(team_u).upper().strip()) & (stat_ser == str(stat_u).upper().strip())
            if not bool(base.any()):
                return {
                    "supported_outs": 0.0,
                    "effective_outs": 0.0,
                    "rel_wmean": 0.0,
                    "rel_min": float("nan"),
                    "rel_max": float("nan"),
                }

            min_g = float(max(1, int(TEAMSHARE_MIN_GAMES_FOR_PATTERN)))
            thr = float(np.clip(TEAMSHARE_REL_EFFECTIVE_THRESHOLD, 0.0, 1.0))

            supported = 0.0
            effective = 0.0
            rels: list[float] = []
            w_sum = 0.0
            s_sum = 0.0

            for out_p, frac in out_list:
                op = _player_key(str(out_p))
                if not op:
                    continue

                m = base & (out_ser == op)
                if not bool(m.any()):
                    continue

                vals = games_ser[m].to_numpy(dtype=float)
                if len(vals) == 0:
                    continue

                gmax = float(np.nanmax(vals))
                if not np.isfinite(gmax) or gmax <= 0:
                    continue

                rel = float(min(1.0, gmax / min_g))
                supported += 1.0
                rels.append(rel)

                if rel >= thr:
                    effective += 1.0

                f = float(frac)
                w_sum += f
                s_sum += f * rel

            rel_wmean = float(s_sum / w_sum) if w_sum > 0 else 0.0
            return {
                "supported_outs": float(supported),
                "effective_outs": float(effective),
                "rel_wmean": rel_wmean,
                "rel_min": float(np.nanmin(rels)) if rels else float("nan"),
                "rel_max": float(np.nanmax(rels)) if rels else float("nan"),
            }

        eligible_out_players: dict[str, list[str]] = {}
        out_list_by_team: dict[str, list[tuple[str, float]]] = {}
        eligible_impact_out_players_count = 0

        for r in impact_rows:
            out_frac = _as_float(r.get("out_frac"), 0.0)
            if out_frac < IAEL_PLAYER_OUT_FRAC_THRESHOLD:
                continue
            t_raw = r.get("team")
            p = r.get("player") or r.get("player_name") or r.get("name")
            t = _iael_team_to_abbrev(t_raw) if t_raw else None
            if not (t and p):
                continue

            eligible_out_players.setdefault(t, []).append(p)
            out_list_by_team.setdefault(t, []).append((str(p), float(out_frac)))
            eligible_impact_out_players_count += 1

        teams_with_impact_outs = sorted(eligible_out_players.keys())
        iael_audit["teams_with_impact_outs_abbrev"] = teams_with_impact_outs
        iael_audit["n_teams_with_impact_outs"] = int(len(teams_with_impact_outs))
        iael_audit["eligible_impact_out_players_count"] = int(eligible_impact_out_players_count)
        iael_audit["teamshare_min_games_for_pattern"] = int(TEAMSHARE_MIN_GAMES_FOR_PATTERN)
        iael_audit["teamshare_rel_effective_threshold"] = float(TEAMSHARE_REL_EFFECTIVE_THRESHOLD)

        out_players_by_team = eligible_out_players

        if len(legs) == 0:
            iael_audit["warning"] = "legs_empty_no_team_coverage"
            out["iael_audit"] = iael_audit
        else:
            team_col = _find_col(legs, ["team"])
            outs_used_col = _find_col(legs, ["role_ctx_outs_used", "role_ctx_outs", "outs_used"])
            padj_col = _find_col(legs, ["p_adj", "pcal", "p_cal"])
            prole_col = _find_col(legs, ["p_role"])
            player_col = _find_col(legs, ["player", "name"])
            stat_col = _find_col(legs, ["stat", "stat_type"])
            tier_col = _find_col(legs, ["tier"])
            dir_col = _find_col(legs, ["direction", "side"])

            iael_audit["cols"] = {
                "team": team_col,
                "outs_used": outs_used_col,
                "p_adj": padj_col,
                "p_role": prole_col,
                "player": player_col,
                "stat": stat_col,
                "tier": tier_col,
                "direction": dir_col,
            }

            if not team_col or not outs_used_col or not padj_col:
                iael_audit["error"] = "missing_required_columns_for_iael_audit"
                out["iael_audit"] = iael_audit
            else:
                ou = pd.to_numeric(legs[outs_used_col], errors="coerce").fillna(0.0)
                p_adj_num = pd.to_numeric(legs[padj_col], errors="coerce")
                reason_col = _find_col(legs, ["role_ctx_reason"])

                leg_team_abbrev = legs[team_col].map(_artifact_team_to_abbrev)
                support_cache: dict[tuple[str, str], dict[str, float]] = {}
                actual_outs_cache: dict[tuple[str, str], float] = {}
                actual_team_used_cache: dict[str, bool] = {}

                if stat_col:
                    all_team_stats = (
                        pd.DataFrame({"team_abbrev": leg_team_abbrev, "stat_u": legs[stat_col]})
                        .dropna()
                        .astype(str)
                        .drop_duplicates()
                        .values.tolist()
                    )
                    for t, s_raw in all_team_stats:
                        s = str(s_raw).upper().strip()
                        if t in out_list_by_team:
                            support_cache[(t, s)] = _teamshare_support_stats_oracle(
                                team_u=t,
                                stat_u=s,
                                out_list=out_list_by_team.get(t, [])
                            )

                    # actual usage by team/stat from scored legs
                    legs_team_stat = pd.DataFrame({
                        "team_abbrev": leg_team_abbrev,
                        "stat_u": legs[stat_col].astype(str).str.upper().str.strip(),
                        "outs_used_num": ou,
                    })

                    actual_used = (
                        legs_team_stat
                        .dropna(subset=["team_abbrev", "stat_u"])
                        .groupby(["team_abbrev", "stat_u"], dropna=False)["outs_used_num"]
                        .max()
                    )

                    for (t, s), mx in cast(Iterator[Tuple[Tuple[str, str], float]], actual_used.items()):
                        actual_outs_cache[(str(t), str(s))] = float(mx)

                    actual_team_used = (
                        legs_team_stat
                        .dropna(subset=["team_abbrev"])
                        .groupby(["team_abbrev"], dropna=False)["outs_used_num"]
                        .max()
                    )

                    for t, mx in cast(Iterator[Tuple[str, float]], actual_team_used.items()):
                        actual_team_used_cache[str(t)] = float(mx) > 0.0

                    support_backed_players_count = 0
                    for t, plist in out_players_by_team.items():
                        team_backed = actual_team_used_cache.get(t, False)
                        if not team_backed:
                            for p in plist:
                                for stat_probe in ("PTS", "REB", "AST", "FG3M", "PR", "PA", "RA", "PRA"):
                                    s = _teamshare_support_stats_oracle(
                                        team_u=t,
                                        stat_u=stat_probe,
                                        out_list=[(str(p), 1.0)]
                                    )
                                    if s.get("supported_outs", 0.0) > 0:
                                        team_backed = True
                                        break
                                if team_backed:
                                    break
                        if team_backed:
                            support_backed_players_count += int(len(plist))

                    iael_audit["support_backed_players_count"] = int(support_backed_players_count)

                # use a locally-named list with Any for values to avoid invariant-list typing errors
                team_cov_list: list[dict[str, Any]] = []
                for t in teams_with_impact_outs:
                    m = (leg_team_abbrev == t)
                    n_legs = int(m.sum())
                    artifact_teams = sorted({str(x).strip() for x in legs.loc[m, team_col].dropna().astype(str).tolist() if str(x).strip()})
                    if n_legs == 0:
                        team_cov_list.append({"team": t, "artifact_teams": artifact_teams, "n_legs": 0, "n_outs_used_gt0": 0, "share_outs_used_gt0": None, "n_iael_eligible_out_players": int(len(out_players_by_team.get(t, []))), "teamshare_supported_stats": 0, "teamshare_effective_stats": 0, "teamshare_rel_wmean_avg": None})
                        continue
                    m_ou = m & (ou > 0)
                    n_ou = int(m_ou.sum())
                    stats_for_team = [v for (tt, _), v in support_cache.items() if tt == t]
                    supported_stats = int(sum(1 for v in stats_for_team if _as_float(v.get("supported_outs"), 0.0) > 0))
                    effective_stats = int(sum(1 for v in stats_for_team if _as_float(v.get("effective_outs"), 0.0) > 0))
                    rel_vals = [_as_float(v.get("rel_wmean"), None) for v in stats_for_team if _as_float(v.get("supported_outs"), 0.0) > 0]
                    rel_avg = float(np.mean([x for x in rel_vals if x is not None])) if rel_vals else None
                    team_cov_list.append({"team": t, "artifact_teams": artifact_teams, "n_legs": n_legs, "n_outs_used_gt0": n_ou, "share_outs_used_gt0": float(n_ou / n_legs) if n_legs > 0 else None, "n_iael_eligible_out_players": int(len(out_players_by_team.get(t, []))), "teamshare_supported_stats": supported_stats, "teamshare_effective_stats": effective_stats, "teamshare_rel_wmean_avg": rel_avg})

                team_cov_sorted = sorted(team_cov_list, key=lambda d: _as_float(d.get("share_outs_used_gt0"), 1.0))
                iael_audit["team_coverage"] = cast(list[dict[str, object]], team_cov_sorted)

                m_out_team = leg_team_abbrev.isin(teams_with_impact_outs)
                m_miss = m_out_team & (ou <= 0) & p_adj_num.notna() & (p_adj_num >= IAEL_MISS_P_ADJ_CUTOFF)

                if reason_col and reason_col in legs.columns:
                    rr = legs[reason_col].astype(str).str.strip().str.lower()
                    EXCLUDE_REASONS = {"no_beneficiary_match", "combo_no_effect"}
                    m_miss = m_miss & (~rr.isin(EXCLUDE_REASONS))

                if stat_col:
                    support_backed_mask = []
                    support_effective_mask = []
                    impact_out_team_values = []

                    for _, row in legs.iterrows():
                        t = _artifact_team_to_abbrev(row.get(team_col, ""))
                        s = str(row.get(stat_col, "")).upper().strip()

                        sup = support_cache.get((t or "", s), {}) if t else {}
                        actual_used = actual_outs_cache.get((t or "", s), 0.0) if t else 0.0
                        actual_team_used = actual_team_used_cache.get((t or ""), False) if t else False

                        is_backed = (_as_float(sup.get("supported_outs"), 0.0) > 0) or (float(actual_used) > 0.0) or bool(actual_team_used)
                        is_effective = (_as_float(sup.get("effective_outs"), 0.0) > 0) or (float(actual_used) > 0.0) or bool(actual_team_used)
                        leg_team_abbrev = legs[team_col].map(_artifact_team_to_abbrev)

                        support_backed_mask.append(is_backed)
                        support_effective_mask.append(is_effective)
                        impact_out_team_values.append(t if t in teams_with_impact_outs else None)

                    support_backed_mask = pd.Series(support_backed_mask, index=legs.index)
                    support_effective_mask = pd.Series(support_effective_mask, index=legs.index)
                    impact_out_team_series = pd.Series(impact_out_team_values, index=legs.index)
                else:
                    support_backed_mask = pd.Series(False, index=legs.index)
                    support_effective_mask = pd.Series(False, index=legs.index)
                    impact_out_team_series = pd.Series(None, index=legs.index)

                miss_df = legs.loc[m_miss & support_effective_mask].copy()
                support_gap_df = legs.loc[m_miss & (~support_effective_mask) & support_backed_mask].copy()
                no_support_df = legs.loc[m_miss & (~support_backed_mask)].copy()
                for _df in (miss_df, support_gap_df, no_support_df):
                    if len(_df) > 0:
                        _df["impact_out_team"] = impact_out_team_series.loc[_df.index]

                def _top_rows(df_in: pd.DataFrame) -> list[dict[str, Any]]:
                    if len(df_in) == 0:
                        return []
                    d = df_in.copy()
                    d["_p_adj_num"] = pd.to_numeric(d[padj_col], errors="coerce")
                    show_cols: list[str] = []
                    for c in [team_col, player_col, stat_col, tier_col, dir_col, outs_used_col, reason_col, prole_col, padj_col]:
                        if c and c in d.columns and c not in show_cols:
                            show_cols.append(c)
                    return cast(list[dict[str, Any]], d.sort_values("_p_adj_num", ascending=False).head(50)[show_cols].to_dict(orient="records"))

                iael_audit["possible_misses_count"] = int(len(miss_df))
                iael_audit["possible_misses_top50"] = _top_rows(miss_df)
                iael_audit["support_gap_count"] = int(len(support_gap_df))
                iael_audit["support_gap_top50"] = _top_rows(support_gap_df)
                iael_audit["no_teamshare_support_count"] = int(len(no_support_df))
                iael_audit["no_teamshare_support_top50"] = _top_rows(no_support_df)

                try:
                    worst5 = team_cov_sorted[:5]
                    print(
                        f"[IAEL] Loaded teams_with_impact_outs={len(teams_with_impact_outs)} "
                        f"support_backed_players_count={support_backed_players_count} "
                        f"min_games_for_pattern={TEAMSHARE_MIN_GAMES_FOR_PATTERN} "
                        f"rel_effective_threshold={TEAMSHARE_REL_EFFECTIVE_THRESHOLD} "
                        f"cutoff_p_adj={IAEL_MISS_P_ADJ_CUTOFF}"
                    )
                    if meta:
                        rl = meta.get("report_label") or ""
                        pa = meta.get("pulled_at_local") or ""
                        print(f"[IAEL] Report: {rl} pulled_at={pa}")
                    if worst5:
                        print("[IAEL] Lowest coverage teams (worst 5): " + ", ".join(
                            f"{d['team']}:{(d['share_outs_used_gt0'] if d['share_outs_used_gt0'] is not None else 'NA')}"
                            for d in worst5
                        ))
                    print(
                        f"[IAEL] possible_misses_count={iael_audit.get('possible_misses_count', 0)} "
                        f"support_gap_count={iael_audit.get('support_gap_count', 0)} "
                        f"no_teamshare_support_count={iael_audit.get('no_teamshare_support_count', 0)}"
                    )
                except Exception:
                    pass

                out["iael_audit"] = iael_audit
    
    # Probability distributions
    pcal = _find_col(legs, ['p_cal'])
    padj = _find_col(legs, ['p_adj'])
    pfor = _find_col(legs, ['p_for_cal'])
    out['legs_rows'] = int(len(legs))
    if pcal:
        out['p_cal'] = _quantiles(legs[pcal])
    if padj:
        out['p_adj'] = _quantiles(legs[padj])
    if pfor:
        out['p_for_cal'] = _quantiles(legs[pfor])

    games_used_col = _find_col(legs, ['games_used'])
    if games_used_col:
        gu = pd.to_numeric(legs[games_used_col], errors='coerce').fillna(0).astype(int)
        out['games_used'] = {
            'min': int(gu.min()),
            'p10': int(gu.quantile(0.10)),
            'med': int(gu.median()),
            'p90': int(gu.quantile(0.90)),
            'max': int(gu.max()),
        }

    
    # ---------------------------------
    # A) Probability pipeline audit
    # ---------------------------------
    tier_col = _find_col(legs, ['tier', 'leg_tier', 'tier_name'])
    stat_col = _find_col(legs, ['stat', 'stat_type'])
    dir_col = _find_col(legs, ['direction', 'dir'])
    prole = _find_col(legs, ['p_role'])
    # Use configured rails when available
    # Use p_floor/p_cap computed above for audit + saturation heuristics

    def _floor_cap_share(s: pd.Series) -> dict[str, float]:
        x = pd.to_numeric(s, errors='coerce')
        x = x.dropna()
        if len(x) == 0:
            return {'floor_share': 0.0, 'cap_share': 0.0}
        # guard against p_floor/p_cap being None or not yet defined
        try:
            pf = p_floor if p_floor is not None else 0.0
        except NameError:
            pf = 0.0
        try:
            pc = p_cap if p_cap is not None else 1.0
        except NameError:
            pc = 1.0
        return {
            'floor_share': float((x <= (pf + 1e-9)).mean()),
            'cap_share': float((x >= (pc - 1e-9)).mean()),
        }

    prob_audit: dict[str, Any] = {}
    if len(legs) > 0:
        # overall
        overall: dict[str, Any] = {}
        if prole:
            overall['p_role'] = {**_quantiles(legs[prole]), **_floor_cap_share(legs[prole])}
        if padj:
            overall['p_adj'] = {**_quantiles(legs[padj]), **_floor_cap_share(legs[padj])}
        if pcal:
            overall['p_cal'] = {**_quantiles(legs[pcal]), **_floor_cap_share(legs[pcal])}
        if games_used_col:
            gu = pd.to_numeric(legs[games_used_col], errors='coerce').fillna(0)
            overall['games_used_lt5_share'] = float((gu < 5).mean())
        if dir_col:
            d = legs[dir_col].astype(str).str.upper()
            overall['over_share'] = float((d == 'OVER').mean())
            overall['under_share'] = float((d == 'UNDER').mean())
        prob_audit['overall'] = overall

        # by tier (compact)
        if tier_col:
            by_tier: dict[str, Any] = {}
            for tval, gdf in legs.groupby(legs[tier_col].astype(str).str.upper()):
                if not tval or tval == 'NAN':
                    continue
                entry: dict[str, Any] = {'rows': int(len(gdf))}
                if prole:
                    entry['p_role'] = {**_quantiles(gdf[prole]), **_floor_cap_share(gdf[prole])}
                if padj:
                    entry['p_adj'] = {**_quantiles(gdf[padj]), **_floor_cap_share(gdf[padj])}
                if pcal:
                    entry['p_cal'] = {**_quantiles(gdf[pcal]), **_floor_cap_share(gdf[pcal])}
                if games_used_col:
                    gu = pd.to_numeric(gdf[games_used_col], errors='coerce').fillna(0)
                    entry['games_used_lt5_share'] = float((gu < 5).mean())
                if dir_col:
                    d = gdf[dir_col].astype(str).str.upper()
                    entry['over_share'] = float((d == 'OVER').mean())
                    entry['under_share'] = float((d == 'UNDER').mean())
                # delta_role (how much role adjustment is happening)
                if prole and padj:
                    dr = pd.to_numeric(gdf[padj], errors='coerce') - pd.to_numeric(gdf[prole], errors='coerce')
                    entry['delta_p_adj_minus_p_role'] = _quantiles(dr)
                by_tier[tval] = entry
            prob_audit['by_tier'] = by_tier

    out['prob_audit'] = prob_audit

    # ---------------------------------
    # B) role_ctx audit (if columns exist)
    # ---------------------------------
    role_mult_col = _find_col(legs, ['role_ctx_mult'])
    outs_used_col = _find_col(legs, ['role_ctx_outs_used'])
    role_audit: dict[str, Any] = {}

    def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
        try:
            aa = pd.to_numeric(a, errors='coerce')
            bb = pd.to_numeric(b, errors='coerce')
            m = aa.notna() & bb.notna()
            if int(m.sum()) < 20:
                return None
            return float(np.corrcoef(aa[m], bb[m])[0, 1])
        except Exception:
            return None

    if len(legs) > 0 and role_mult_col:
        rm = pd.to_numeric(legs[role_mult_col], errors='coerce')
        role_audit['role_ctx_mult'] = {**_quantiles(rm), **_std_iqr(rm)}
        # extremes (by abs(log(mult)))
        with np.errstate(divide='ignore', invalid='ignore'):
            score = np.abs(np.log(rm.astype(float)))
        topk = legs.copy()
        topk['_abs_log_role_mult'] = score
        topk = topk.replace([np.inf, -np.inf], np.nan).dropna(subset=['_abs_log_role_mult'])
        topk = topk.sort_values('_abs_log_role_mult', ascending=False).head(10)

        # identify columns for display
        player_col = _find_col(legs, ['player', 'name'])
        key_col = _find_col(legs, ['prop_key', 'key', 'projection_id'])
        cols = []
        for c in [key_col, player_col, stat_col, tier_col, dir_col, role_mult_col, outs_used_col, padj, prole, pcal]:
            if c and c in legs.columns and c not in cols:
                cols.append(c)

        role_audit['extremes_top10'] = topk[cols].to_dict(orient='records') if cols else topk.head(10).to_dict(orient='records')

        if outs_used_col:
            # group split (outs used vs not): does role_ctx actually move final p?
            ou = pd.to_numeric(legs[outs_used_col], errors="coerce").fillna(0.0)
            m_out = (ou > 0)
            m_no = ~m_out

            def _med(s: pd.Series, m: pd.Series) -> float | None:
                try:
                    ss = pd.to_numeric(s, errors="coerce")
                    vv = ss[m & ss.notna()]
                    if len(vv) < 20:
                        return None
                    return float(vv.median())
                except Exception:
                    return None

            role_audit["group_medians"] = {
                "outs_used_gt0": {
                    "n": int(m_out.sum()),
                    "role_ctx_mult_median": _med(rm, m_out),
                    **({"p_role_median": _med(legs[prole], m_out)} if prole else {}),
                    **({"p_adj_median":  _med(legs[padj],  m_out)} if padj else {}),
                    **({"delta_p_adj_minus_p_role_median": _med(
                        pd.to_numeric(legs[padj], errors="coerce") - pd.to_numeric(legs[prole], errors="coerce"),
                        m_out
                    )} if (prole and padj) else {}),
                },
                "outs_used_eq0": {
                    "n": int(m_no.sum()),
                    "role_ctx_mult_median": _med(rm, m_no),
                    **({"p_role_median": _med(legs[prole], m_no)} if prole else {}),
                    **({"p_adj_median":  _med(legs[padj],  m_no)} if padj else {}),
                    **({"delta_p_adj_minus_p_role_median": _med(
                        pd.to_numeric(legs[padj], errors="coerce") - pd.to_numeric(legs[prole], errors="coerce"),
                        m_no
                    )} if (prole and padj) else {}),
                },
            }
    
        if prole and padj:
            dr = pd.to_numeric(legs[padj], errors='coerce') - pd.to_numeric(legs[prole], errors='coerce')
            role_audit['corr_role_mult_vs_delta_p'] = _safe_corr(rm, dr)
    
    # --- Outs-day "PP trap" diagnostics (audit only) ---
    if padj and padj in legs.columns:
        p_adj_num = pd.to_numeric(legs[padj], errors="coerce")

        # shares of very-high p_adj among outs-context rows
        m_ctx = (ou > 0) & p_adj_num.notna()
        if int(m_ctx.sum()) > 0:
            role_audit["outs_ctx_p_adj_ge_0.85_share"] = float((p_adj_num[m_ctx] >= 0.85).mean())
            role_audit["outs_ctx_p_adj_ge_0.90_share"] = float((p_adj_num[m_ctx] >= 0.90).mean())
            role_audit["outs_ctx_p_adj_ge_0.95_share"] = float((p_adj_num[m_ctx] >= 0.95).mean())

            # top danger legs on outs-days: highest p_adj
            danger = legs.loc[m_ctx].copy()
            danger["_p_adj_num"] = p_adj_num[m_ctx]
            show_cols = []
            for c in [key_col, player_col, stat_col, tier_col, dir_col, outs_used_col, role_mult_col, prole, padj, pcal]:
                if c and c in danger.columns and c not in show_cols:
                    show_cols.append(c)

            role_audit["outs_ctx_top10_by_p_adj"] = (
                danger.sort_values("_p_adj_num", ascending=False).head(10)[show_cols].to_dict(orient="records")
                if show_cols else danger.sort_values("_p_adj_num", ascending=False).head(10).to_dict(orient="records")
            )

    # if we can compute delta, show outs-context "boost vs role" (p_adj - p_role)
    if prole and padj and prole in legs.columns and padj in legs.columns:
        p_role_num = pd.to_numeric(legs[prole], errors="coerce")
        p_adj_num  = pd.to_numeric(legs[padj], errors="coerce")
        delta = (p_adj_num - p_role_num)

        m_ctx = (ou > 0) & delta.notna()
        if int(m_ctx.sum()) > 0:
            danger2 = legs.loc[m_ctx].copy()
            danger2["_delta_num"] = delta[m_ctx]

            show_cols2 = []
            for c in [key_col, player_col, stat_col, tier_col, dir_col, outs_used_col, role_mult_col, prole, padj, pcal]:
                if c and c in danger2.columns and c not in show_cols2:
                    show_cols2.append(c)

            role_audit["outs_ctx_top10_by_delta_p_adj_minus_p_role"] = (
                danger2.sort_values("_delta_num", ascending=False).head(10)[show_cols2].to_dict(orient="records")
                if show_cols2 else danger2.sort_values("_delta_num", ascending=False).head(10).to_dict(orient="records")
            )

    out['role_ctx_audit'] = role_audit

    # Slips: collect recommended files recursively
    slip_files = sorted([p for p in run_dir.rglob('recommended_*leg*.csv') if p.is_file()])
    out['slip_files'] = [str(p.relative_to(run_dir)) for p in slip_files]

    slip_summaries = []
    for p in slip_files:
        df = _read_csv(p)
        if df is None or len(df) == 0:
            continue
        hp_col = _find_col(df, ['hit_prob', 'win_prob'])
        ev_col = _find_col(df, ['ev_mult', 'rank_ev'])
        if not hp_col:
            continue
        summ = {
            'file': str(p.relative_to(run_dir)),
            'rows': int(len(df)),
            'hit_prob': _quantiles(df[hp_col]),
        }
        if ev_col:
            summ['ev'] = _quantiles(df[ev_col])

        # Payout/pricing stats (added; do not remove existing fields)
        pay_col = _find_col(df, ['payout_mult'])
        pay_eff_col = _find_col(df, ['payout_mult_eff'])
        ker_col = _find_col(df, ['kernel_mult'])

        if pay_col:
            summ['payout_mult'] = {**_quantiles(df[pay_col]), **_std_iqr(df[pay_col])}
        if pay_eff_col:
            summ['payout_mult_eff'] = {**_quantiles(df[pay_eff_col]), **_std_iqr(df[pay_eff_col])}
        if ker_col:
            summ['kernel_mult'] = {**_quantiles(df[ker_col]), **_std_iqr(df[ker_col])}

        # Composition / exposure
        summ['tier_mix_legs'] = _tier_mix_from_slips(df)
        summ['player_exposure'] = _player_exposure_from_slips(df)

        slip_summaries.append(summ)
    out['slips'] = slip_summaries
    # ---------------------------------
    # C) Kernel suggester (advisory-only)
    # ---------------------------------
    kernel_suggestions: dict[str, Any] = {}
    try:
        # compute std(logit(p_adj)) for STANDARD legs
        if len(legs) > 0 and padj and tier_col:
            std_mask = legs[tier_col].astype(str).str.upper() == 'STANDARD'
            p_std = pd.to_numeric(legs.loc[std_mask, padj], errors='coerce').dropna()
            # derive p_floor/p_cap from config if available, else sensible defaults and clamp
            prob_cfg = (cfg.get('probability') or {}) if isinstance(cfg, dict) else {}
            p_floor = _as_float(prob_cfg.get('p_floor'), None)
            p_cap = _as_float(prob_cfg.get('p_cap'), None)
            # fallback to top-level keys or defaults
            if p_floor is None:
                p_floor = _as_float(cfg.get('p_floor'), 0.0)
            if p_cap is None:
                p_cap = _as_float(cfg.get('p_cap'), 1.0)
            # ensure numeric and in [0,1], with sensible fallback if invalid
            try:
                p_floor = max(0.0, min(1.0, float(p_floor)))
            except Exception:
                p_floor = 0.0
            try:
                p_cap = max(0.0, min(1.0, float(p_cap)))
            except Exception:
                p_cap = 1.0
            if p_floor >= p_cap:
                # enforce minimal separation if misconfigured
                p_floor = 0.0
                p_cap = 1.0
            p_std = p_std.clip(lower=p_floor, upper=p_cap)
            if len(p_std) >= 50:
                logit = np.log(p_std / (1.0 - p_std))
                std_logit = float(logit.std(ddof=0))
                kernel_suggestions['std_logit_p_adj_STANDARD'] = std_logit

                # helper to compute sigma_leg from a slip file by log(kernel_mult)
                def _sigma_leg_from_file(relpath: Path | str, nlegs: int) -> float | None:
                    pth = run_dir / relpath
                    df = _read_csv(pth)
                    if df is None or len(df) == 0:
                        return None
                    ker_col = _find_col(df, ['kernel_mult'])
                    if not ker_col:
                        return None
                    km = pd.to_numeric(df[ker_col], errors='coerce').dropna()
                    km = km[km > 0]
                    if len(km) < 10:
                        return None
                    sig = float(np.log(km).std(ddof=0) / math.sqrt(nlegs))
                    return sig

                # gather current per-leg discrimination for System vs Windfall (if present)
                def _is_windfall(p: Path) -> bool:
                    return any(part.lower() == "windfall" for part in p.parts)

                def _pick_file(name: str, want_windfall: bool) -> Path | None:
                    # pick the first matching file under run_dir by path classification
                    for p in run_dir.rglob(name):
                        if _is_windfall(p) == want_windfall:
                            return p
                    return None

                sys4p = _pick_file("recommended_4leg.csv", want_windfall=False)
                sys5p = _pick_file("recommended_5leg.csv", want_windfall=False)
                wf4p  = _pick_file("recommended_4leg.csv", want_windfall=True)
                wf5p  = _pick_file("recommended_5leg.csv", want_windfall=True)

                sigma_sys4 = _sigma_leg_from_file(sys4p.relative_to(run_dir), 4) if sys4p else None
                sigma_sys5 = _sigma_leg_from_file(sys5p.relative_to(run_dir), 5) if sys5p else None
                sigma_wf4  = _sigma_leg_from_file(wf4p.relative_to(run_dir), 4) if wf4p else None
                sigma_wf5  = _sigma_leg_from_file(wf5p.relative_to(run_dir), 5) if wf5p else None

                kernel_suggestions["sigma_leg_system_4"]   = sigma_sys4
                kernel_suggestions["sigma_leg_system_5"]   = sigma_sys5
                kernel_suggestions["sigma_leg_windfall_4"] = sigma_wf4
                kernel_suggestions["sigma_leg_windfall_5"] = sigma_wf5

                # choose a target sigma_leg:
                # prefer matching Windfall if available, else n-average of current System * 1.10
                target = None
                if sigma_wf4 is not None and sigma_wf5 is not None:
                    target = float(0.5 * (sigma_wf4 + sigma_wf5))
                    kernel_suggestions['target_sigma_leg_reason'] = 'match_windfall_avg'
                elif sigma_wf4 is not None:
                    target = float(sigma_wf4)
                    kernel_suggestions['target_sigma_leg_reason'] = 'match_windfall_4'
                elif sigma_wf5 is not None:
                    target = float(sigma_wf5)
                    kernel_suggestions['target_sigma_leg_reason'] = 'match_windfall_5'
                else:
                    # fallback: increase current system average by 10%
                    cur = [v for v in [sigma_sys4, sigma_sys5] if v is not None]
                    if cur:
                        target = float(np.mean(cur) * 1.10)
                        kernel_suggestions['target_sigma_leg_reason'] = 'system_avg_plus_10pct'

                kernel_suggestions['target_sigma_leg'] = target

                # compute b suggestions if possible
                if target is not None:
                    # anchor at p0=0.75 by default (or cfg override)
                    p0 = float((cfg.get("pp_kernel", {}) or {}).get("p0", 0.75))
                    p0 = p0 if 0 < p0 < 1 else 0.75
                    logit_p0 = math.log(p0 / (1.0 - p0))
                    kernel_suggestions["p0"] = p0

                    # --- Suggestion 1: theoretical solve from std(logit(p_adj))) ---
                    # (only if std_logit is defined/usable)
                    if std_logit is not None and std_logit > 1e-9:
                        b_suggest_logit = -float(target / std_logit)
                        a_suggest_logit = -b_suggest_logit * logit_p0
                        kernel_suggestions["suggest_STANDARD_b_from_logit"] = b_suggest_logit
                        kernel_suggestions["suggest_STANDARD_a_from_logit"] = a_suggest_logit

                    # --- Suggestion 2: slip-space ratio solve from observed sigma_leg(System) ---
                    # compute current average sigma from available system sigmas
                    cur_vals = [v for v in (sigma_sys4, sigma_sys5) if v is not None]
                    cur_sigma = float(np.mean(cur_vals)) if cur_vals else None
                    kernel_suggestions["cur_sigma_leg_system_avg"] = cur_sigma

                    b_current = None
                    try:
                        coeffs = (cfg.get("pp_kernel", {}) or {}).get("coeffs", {}) or {}
                        # prefer first non-DEFAULT stat block that has STANDARD.b
                        stat_keys = [k for k in coeffs.keys() if str(k).upper() != "DEFAULT"]
                        for k in stat_keys:
                            try:
                                b_current = float(coeffs[k]["STANDARD"]["b"])
                                kernel_suggestions["b_current_source"] = str(k)
                                break
                            except Exception:
                                continue
                        # fallback to DEFAULT
                        if b_current is None:
                            b_current = float(coeffs.get("DEFAULT", {}).get("STANDARD", {}).get("b"))
                            kernel_suggestions["b_current_source"] = "DEFAULT"
                    except Exception:
                        b_current = None

                    kernel_suggestions["b_current"] = b_current

                    b_ratio_raw = None
                    a_ratio_raw = None
                    b_ratio_step = None
                    a_ratio_step = None

                    if b_current is not None and cur_sigma is not None and cur_sigma > 0:
                        ratio = float(target / cur_sigma)
                        kernel_suggestions["sigma_ratio_target_over_current"] = ratio

                        # raw ratio solve (informational; can be a big jump)
                        ratio_cap = float((cfg.get("pp_kernel", {}) or {}).get("ratio_cap", 1.5))
                        ratio_step = min(ratio, ratio_cap)
                        b_ratio_step = float(b_current * ratio_step)
                        a_ratio_step = -b_ratio_step * logit_p0

                    kernel_suggestions["suggest_STANDARD_b_from_sigma_ratio_raw"] = b_ratio_raw
                    kernel_suggestions["suggest_STANDARD_a_from_sigma_ratio_raw"] = a_ratio_raw
                    kernel_suggestions["suggest_STANDARD_b_from_sigma_ratio_step"] = b_ratio_step
                    kernel_suggestions["suggest_STANDARD_a_from_sigma_ratio_step"] = a_ratio_step
    
    except Exception as e:
        kernel_suggestions['error'] = str(e)

    out['kernel_suggestions'] = kernel_suggestions



    # Knob suggestions
    recs: list[dict[str, Any]] = []
    # Use p_floor/p_cap computed above for audit + saturation heuristics
    # derive p_floor/p_cap from config if available, else sensible defaults and clamp
    prob_cfg = (cfg.get('probability') or {}) if isinstance(cfg, dict) else {}
    p_floor = _as_float(prob_cfg.get('p_floor'), None)
    p_cap = _as_float(prob_cfg.get('p_cap'), None)
    # fallback to top-level keys or defaults
    if p_floor is None:
        p_floor = _as_float(cfg.get('p_floor'), 0.0)
    if p_cap is None:
        p_cap = _as_float(cfg.get('p_cap'), 1.0)
    # ensure numeric and in [0,1], with sensible fallback if invalid
    try:
        p_floor = max(0.0, min(1.0, float(p_floor)))
    except Exception:
        p_floor = 0.0
    try:
        p_cap = max(0.0, min(1.0, float(p_cap)))
    except Exception:
        p_cap = 1.0
    if p_floor >= p_cap:
        # enforce minimal separation if misconfigured
        p_floor = 0.0
        p_cap = 1.0

    # Saturation heuristics
    if pcal and len(legs) > 0:
        s = pd.to_numeric(legs[pcal], errors='coerce')
        floor_share = float((s <= (p_floor + 1e-9)).mean())
        cap_share = float((s >= (p_cap - 1e-9)).mean())
        out['p_cal_floor_share'] = floor_share
        out['p_cal_cap_share'] = cap_share
        if floor_share > 0.03:
            recs.append({
                'area': 'probability',
                'signal': f'p_cal floor share {floor_share:.3%} > 3%',
                'suggest': [
                    {'key': 'probability.p_floor', 'delta': 'raise slightly OR fix variance floors'},
                    {'key': 'probability.role_ctx.variance_k', 'delta': 'increase if too conservative'},
                ]
            })
        if cap_share > 0.03:
            recs.append({
                'area': 'probability',
                'signal': f'p_cal cap share {cap_share:.3%} > 3%',
                'suggest': [
                    {'key': 'probability.p_cap', 'delta': 'lower slightly OR tighten clamps'},
                    {'key': 'probability.role_ctx.projection_clamp_hi', 'delta': 'tighten'},
                ]
            })

    # Slip-level hit_prob targets
    # heuristic thresholds by legs count
    targets = (cfg.get('slip_build', {}) or {}).get('min_slip_hit_prob_by_legs', {3:0.08,4:0.05,5:0.03})
    for summ in slip_summaries:
        fname = summ['file']
        hp_med = summ.get('hit_prob', {}).get('med', None)
        if hp_med is None:
            continue
        legs_n = 3 if '3leg' in fname else 4 if '4leg' in fname else 5 if '5leg' in fname else None
        if legs_n and isinstance(targets, dict) and str(legs_n) in targets:
            tgt = float(targets[str(legs_n)])
        elif legs_n and isinstance(targets, dict) and legs_n in targets:
            tgt = float(targets[legs_n])
        else:
            tgt = None
        if tgt is not None and hp_med < tgt:
            recs.append({
                'area': 'slip_build',
                'signal': f'{fname} hit_prob median {hp_med:.4f} < target {tgt:.4f}',
                'suggest': [
                    {'key': 'slip_rank.ev_payout_power', 'delta': 'decrease (less EV aggression)'},
                    {'key': 'slip_build.min_leg_p_cal', 'delta': 'increase (raise leg floor)'},
                    {'key': 'slip_build.target_pool_mult', 'delta': 'increase (more candidates)'}
                ]
            })
    
    # -------------------------
    # WinProb integrity checks
    # -------------------------
    # Build quick lookup by filename
    _by = {s.get("file"): s for s in slip_summaries if s.get("file")}

    EPS_HP = 0.002
    EV_RATIO_BAD = 1.25

    def _get_med(d, key):
        try:
            v = (((d or {}).get(key) or {}).get("med"))
            return float(v) if v is not None else None
        except Exception:
            return None

    for legs in (3, 4, 5):
        base = f"recommended_{legs}leg.csv"
        wp = f"recommended_{legs}leg_winprob.csv"

        ev_sum = _by.get(base)
        wp_sum = _by.get(wp)
        if not ev_sum or not wp_sum:
            continue

        hp_ev = _get_med(ev_sum, "hit_prob")
        hp_wp = _get_med(wp_sum, "hit_prob")
        ev_ev = _get_med(ev_sum, "ev")
        ev_wp = _get_med(wp_sum, "ev")

        if hp_ev is None or hp_wp is None:
            recs.append({
                "area": "winprob",
                "signal": f"{wp} missing hit_prob med; cannot validate winprob baseline",
                "suggest": [{"key": "oracle", "delta": "ensure hit_prob column is detected"}],
            })
            continue

        dh = abs(hp_wp - hp_ev)

        # EV-contamination (kept, but now safe): hit_prob unchanged while ev shifts materially
        if ev_ev is not None and ev_wp is not None and dh < EPS_HP and ev_ev > 0:
            ratio = ev_wp / ev_ev
            if ratio > EV_RATIO_BAD:
                recs.append({
                    "area": "winprob",
                    "signal": f"{wp} appears EV-contaminated: ev_med ratio {ratio:.2f} while hit_prob med Δ={dh:.4f}",
                    "suggest": [
                        {"key": "src/Atlas/core/slip_builders.py", "delta": "winprob sort/selection must be hit_prob-only (no score_adj, no ev tie-break)"},
                    ],
                })

        # Collapse check (upgraded): use slip_key overlap instead of only median
        # If the lists are basically the same slips, objectives aren't separating.
        p_base = run_dir / base
        p_wp = run_dir / wp
        dfb = _read_csv(p_base)
        dfw = _read_csv(p_wp)

        if dfb is not None and dfw is not None and "slip_key" in dfb.columns and "slip_key" in dfw.columns:
            A = set(dfb["slip_key"].dropna().astype(str).tolist())
            B = set(dfw["slip_key"].dropna().astype(str).tolist())
            if A and B:
                jacc = len(A & B) / len(A | B)
                # Only flag collapse when overlap is very high (median-only was too noisy)
                if jacc >= 0.95:
                    recs.append({
                        "area": "winprob",
                        "signal": f"{base} vs {wp} collapse: slip_key overlap {jacc:.2%} (hit_prob med Δ={dh:.4f})",
                        "suggest": [
                            {"key": "oracle", "delta": "winprob separation is low (lists nearly identical)"},
                            {"key": "slip_build.target_pool_mult", "delta": "increase (more candidates)"},
                            {"key": "slip_build.phase1_frac", "delta": "decrease (less early lock-in)"},
                        ],
                    })

            # WinProb not pure probability: hit_prob unchanged but EV jumps
            if ev_ev is not None and ev_wp is not None and dh < EPS_HP and ev_ev > 0:
                ratio = ev_wp / ev_ev
                if ratio > EV_RATIO_BAD:
                    recs.append({
                        "area": "winprob",
                        "signal": f"{wp} appears EV-contaminated: ev_med ratio {ratio:.2f} while hit_prob med Δ={dh:.4f}",
                        "suggest": [
                            {"key": "src/Atlas/core/slip_builders.py", "delta": "winprob sort must be hit_prob-only (no score_adj, no ev_mult tie-break)"},
                            {"key": "slip_build.target_pool_mult", "delta": "increase if still collapsed after sort fix"},
                        ],
                    })

            # WinProb collapse: objectives not separating
            if dh < EPS_HP:
                recs.append({
                    "area": "winprob",
                    "signal": f"{base} vs {wp} hit_prob med collapse (Δ={dh:.4f})",
                    "suggest": [
                        {"key": "src/Atlas/core/slip_builders.py", "delta": "ensure winprob sort is hit_prob-only"},
                        {"key": "slip_build.beam_width", "delta": "increase (more portfolio exploration)"},
                        {"key": "slip_build.phase1_frac", "delta": "decrease (less early lock-in)"},
                    ],
                })

    out['recommendations'] = recs
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--run-id', type=str)
    g.add_argument('--run-dir', type=str)
    ap.add_argument('--config', type=str, default='config.yaml')
    ap.add_argument('--write-report', action='store_true')
    args = ap.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else Path('data/output/runs') / args.run_id
    cfg = _load_yaml(Path(args.config))

    rep = analyze(run_dir=run_dir, cfg=cfg)
    print(json.dumps(rep, indent=2))

    if args.write_report:
        audit = Path('.atlas_audit') / 'diagnostics'
        audit.mkdir(parents=True, exist_ok=True)
        rid = args.run_id or run_dir.name
        outp = audit / f'oracle_{rid}.json'
        outp.write_text(json.dumps(rep, indent=2), encoding='utf-8')
        print(f'WROTE {outp}')


if __name__ == '__main__':
    main()
