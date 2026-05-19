from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import pandas as pd

from Atlas.core.slip_composition_policy import (
    composition_drop_reason_for_item,
    infer_slate_game_count,
    leg_parts_from_marketed_slip,
    leg_parts_from_slip_row,
)
from Atlas.core.slip_family_diversity import (
    player_keys_from_marketed_slip,
    player_keys_from_slip_row,
    prop_keys_from_marketed_slip,
    prop_keys_from_slip_row,
)


PUBLIC_QUALITY_COLUMNS = [
    "public_survival_score",
    "public_quality_pass",
    "public_quality_reasons",
    "slip_consensus_legs",
    "slip_consensus_share",
    "public_portfolio_status",
    "public_portfolio_reason",
]


@dataclass(frozen=True)
class PortfolioQualityResult:
    frames: dict[str, pd.DataFrame | None]
    marketed_slips: list[dict[str, Any]]
    manifest: dict[str, Any]


def public_slip_quality_enabled(cfg: Mapping[str, Any] | None) -> bool:
    section = _section(cfg)
    return bool(section.get("enabled", False))


def build_slip_consensus_counts(
    frames_by_family: Mapping[str, Iterable[pd.DataFrame | None]],
    marketed_slips: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Count in how many distinct public families each exact prop appears."""

    family_keys: dict[str, set[str]] = {}
    for family, frames in frames_by_family.items():
        keys: set[str] = set()
        for frame in frames or []:
            if frame is None or frame.empty:
                continue
            for _, row in frame.iterrows():
                keys.update(prop_keys_from_slip_row(row))
        if keys:
            family_keys[str(family)] = keys

    if marketed_slips:
        keys = set()
        for slip in marketed_slips:
            keys.update(prop_keys_from_marketed_slip(slip))
        if keys:
            family_keys["Marketed"] = keys

    counts: dict[str, int] = {}
    for keys in family_keys.values():
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return counts


def annotate_slip_frame(
    frame: pd.DataFrame | None,
    cfg: Mapping[str, Any] | None,
    *,
    family: str,
    consensus_counts: Mapping[str, int] | None = None,
) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return frame

    out = frame.copy()
    rows = [
        _score_recommended_row(row, cfg, family=family, consensus_counts=consensus_counts or {})
        for _, row in out.iterrows()
    ]
    for col in PUBLIC_QUALITY_COLUMNS:
        out[col] = [row.get(col) for row in rows]
    return out


def filter_slip_frame(
    frame: pd.DataFrame | None,
    cfg: Mapping[str, Any] | None,
    *,
    family: str,
    consensus_counts: Mapping[str, int] | None = None,
) -> pd.DataFrame | None:
    annotated = annotate_slip_frame(frame, cfg, family=family, consensus_counts=consensus_counts)
    if annotated is None or annotated.empty:
        return annotated
    if not public_slip_quality_enabled(cfg):
        return annotated
    return annotated[annotated["public_quality_pass"].map(bool)].reset_index(drop=True)


def annotate_marketed_slips(
    slips: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any] | None,
    *,
    family: str = "Marketed",
    consensus_counts: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for slip in slips or []:
        annotated = dict(slip)
        annotated.update(
            _score_marketed_slip(
                slip,
                cfg,
                family=family,
                consensus_counts=consensus_counts or {},
            )
        )
        out.append(annotated)
    return out


def filter_marketed_slips(
    slips: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any] | None,
    *,
    family: str = "Marketed",
    consensus_counts: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    annotated = annotate_marketed_slips(slips, cfg, family=family, consensus_counts=consensus_counts)
    if not public_slip_quality_enabled(cfg):
        return annotated
    return [slip for slip in annotated if bool(slip.get("public_quality_pass", True))]


def apply_public_portfolio_exposure(
    frames: Mapping[str, pd.DataFrame | None],
    marketed_slips: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any] | None,
    slate_source: pd.DataFrame | None = None,
) -> PortfolioQualityResult:
    """Hard cap exact prop exposure across public outputs.

    This pass runs after all public families are built. It does not rewrite leg
    probabilities; it only drops full slips whose exact player/direction/stat/line
    would already be exposed by a higher-priority public output.
    """

    section = _section(cfg)
    exposure = section.get("exposure", {}) if isinstance(section.get("exposure"), dict) else {}
    enabled = public_slip_quality_enabled(cfg) and bool(exposure.get("enabled", True))
    max_repeats = int(exposure.get("max_exact_prop_repeats_across_public", 1) or 1)
    max_player_repeats = int(exposure.get("max_player_repeats_across_public", 1) or 0)
    priority = [str(x) for x in exposure.get("priority", ["Marketed", "System", "Windfall", "DemonHunter"])]
    slate_games = infer_slate_game_count(slate_source)

    kept_frames = {name: _ensure_quality_columns(frame) for name, frame in frames.items()}
    kept_marketed = annotate_marketed_slips(marketed_slips, cfg, family="Marketed")

    if not enabled:
        manifest = _manifest(enabled=False, kept_frames=kept_frames, kept_marketed=kept_marketed, drops=[])
        return PortfolioQualityResult(kept_frames, kept_marketed, manifest)

    items: list[dict[str, Any]] = []
    pre_drops: list[dict[str, Any]] = []
    for slip_index, slip in enumerate(kept_marketed):
        leg_parts = leg_parts_from_marketed_slip(slip)
        items.append(
            {
                "kind": "marketed",
                "family": "Marketed",
                "name": "Marketed",
                "index": slip_index,
                "keys": prop_keys_from_marketed_slip(slip),
                "player_keys": player_keys_from_marketed_slip(slip),
                "n_legs": int(_float(slip.get("n_legs"), len(leg_parts)) or len(leg_parts)),
                "leg_parts": leg_parts,
                "quality_pass": bool(slip.get("public_quality_pass", True)),
                "survival_score": _float(slip.get("public_survival_score"), 0.0),
            }
        )

    for name, frame in kept_frames.items():
        family = _family_from_name(name)
        if frame is None or frame.empty:
            continue
        if not _family_enabled_for_slate(family, section, exposure, slate_games):
            for idx, row in frame.iterrows():
                pre_drops.append(
                    _drop_record(
                        {
                            "kind": "frame",
                            "family": family,
                            "name": name,
                            "index": idx,
                            "survival_score": _float(row.get("public_survival_score"), 0.0),
                            "player_keys": player_keys_from_slip_row(row),
                        },
                        "family_disabled_for_slate",
                        prop_keys_from_slip_row(row),
                    )
                )
            continue
        for idx, row in frame.iterrows():
            leg_parts = leg_parts_from_slip_row(row)
            items.append(
                {
                    "kind": "frame",
                    "family": family,
                    "name": name,
                    "index": idx,
                    "keys": prop_keys_from_slip_row(row),
                    "player_keys": player_keys_from_slip_row(row),
                    "n_legs": int(_float(row.get("n_legs"), len(leg_parts)) or len(leg_parts)),
                    "leg_parts": leg_parts,
                    "quality_pass": bool(row.get("public_quality_pass", True)),
                    "survival_score": _float(row.get("public_survival_score"), 0.0),
                }
            )

    priority_index = {family: i for i, family in enumerate(priority)}
    items.sort(
        key=lambda item: (
            priority_index.get(str(item["family"]), len(priority_index) + 1),
            -float(item.get("survival_score", 0.0)),
            str(item["name"]),
            int(item["index"]),
        )
    )

    counts: dict[str, int] = {}
    player_counts: dict[str, int] = {}
    kept_item_ids: set[tuple[str, str, int]] = set()
    drops: list[dict[str, Any]] = list(pre_drops)

    for item in items:
        item_id = (str(item["kind"]), str(item["name"]), int(item["index"]))
        keys = {key for key in item.get("keys", set()) if key}
        player_keys = {key for key in item.get("player_keys", set()) if key}
        composition_reason = composition_drop_reason_for_item(item, section, slate_games)
        if composition_reason:
            drops.append(_drop_record(item, composition_reason, keys))
            continue
        if not item.get("quality_pass", True):
            drops.append(_drop_record(item, "quality_gate_failed", keys))
            continue
        if keys and any(counts.get(key, 0) >= max_repeats for key in keys):
            drops.append(_drop_record(item, "exact_prop_exposure_cap", keys))
            continue
        if max_player_repeats > 0 and player_keys and any(player_counts.get(key, 0) >= max_player_repeats for key in player_keys):
            drops.append(_drop_record(item, "player_exposure_cap", keys))
            continue
        kept_item_ids.add(item_id)
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
        for key in player_keys:
            player_counts[key] = player_counts.get(key, 0) + 1

    final_marketed: list[dict[str, Any]] = []
    for idx, slip in enumerate(kept_marketed):
        item_id = ("marketed", "Marketed", idx)
        if item_id in kept_item_ids:
            out = dict(slip)
            out["public_portfolio_status"] = "kept"
            out["public_portfolio_reason"] = ""
            final_marketed.append(out)

    final_frames: dict[str, pd.DataFrame | None] = {}
    for name, frame in kept_frames.items():
        if frame is None or frame.empty:
            final_frames[name] = frame
            continue
        kept_indices = [
            idx for idx in frame.index
            if ("frame", name, int(idx)) in kept_item_ids
        ]
        out = frame.loc[kept_indices].copy()
        if not out.empty:
            out["public_portfolio_status"] = "kept"
            out["public_portfolio_reason"] = ""
        final_frames[name] = out.reset_index(drop=True)

    manifest = _manifest(enabled=True, kept_frames=final_frames, kept_marketed=final_marketed, drops=drops)
    manifest["max_exact_prop_repeats_across_public"] = max_repeats
    manifest["max_player_repeats_across_public"] = max_player_repeats
    manifest["priority"] = priority
    manifest["slate_games"] = slate_games
    manifest["two_game_4_5_composition"] = section.get("two_game_4_5_composition", {})
    return PortfolioQualityResult(final_frames, final_marketed, manifest)


def _score_recommended_row(
    row: pd.Series,
    cfg: Mapping[str, Any] | None,
    *,
    family: str,
    consensus_counts: Mapping[str, int],
) -> dict[str, Any]:
    n_legs = int(_float(row.get("n_legs"), 0) or 0)
    keys = prop_keys_from_slip_row(row)
    avg_p = _float(row.get("avg_p"), _float(row.get("hit_prob"), 0.0) ** (1 / max(n_legs, 1)))
    min_p = _float(row.get("min_p"), avg_p)
    avg_frag = _float(row.get("avg_fragility"), 0.0)
    pen_total = _float(row.get("pen_total"), 0.0)
    minute_risk_legs = int(_float(row.get("minute_risk_legs"), 0.0) or 0)
    q_leg_count = int(_float(row.get("q_leg_count"), 0.0) or 0)
    hit_prob = _float(row.get("hit_prob"), 0.0)
    single_game = _is_single_game_row(row)
    consensus_legs = sum(1 for key in keys if int(consensus_counts.get(key, 0)) >= 2)
    consensus_share = consensus_legs / max(len(keys), 1)

    score = _survival_score(
        cfg,
        n_legs=n_legs,
        avg_p=avg_p,
        min_p=min_p,
        avg_fragility=avg_frag,
        pen_total=pen_total,
        minute_risk_legs=minute_risk_legs,
        q_leg_count=q_leg_count,
        consensus_legs=consensus_legs,
        single_game=single_game,
        single_game_avg_robustness=_float(row.get("single_game_avg_robustness_score"), 0.0),
        single_game_dependency=_float(row.get("single_game_avg_script_dependency_score"), 0.0),
    )
    passed, reasons = _quality_pass(
        cfg,
        family=family,
        n_legs=n_legs,
        single_game=single_game,
        score=score,
        hit_prob=hit_prob,
        minute_risk_legs=minute_risk_legs,
        q_leg_count=q_leg_count,
    )
    return {
        "public_survival_score": score,
        "public_quality_pass": passed,
        "public_quality_reasons": ",".join(reasons),
        "slip_consensus_legs": int(consensus_legs),
        "slip_consensus_share": float(consensus_share),
        "public_portfolio_status": "",
        "public_portfolio_reason": "",
    }


def _score_marketed_slip(
    slip: Mapping[str, Any],
    cfg: Mapping[str, Any] | None,
    *,
    family: str,
    consensus_counts: Mapping[str, int],
) -> dict[str, Any]:
    legs = list(slip.get("legs", []) or [])
    n_legs = int(_float(slip.get("n_legs"), len(legs)) or len(legs))
    keys = prop_keys_from_marketed_slip(dict(slip))
    leg_probs = [_float(leg.get("p_cal"), _float(leg.get("p_cal_marketed"), 0.5)) for leg in legs]
    avg_p = sum(leg_probs) / len(leg_probs) if leg_probs else 0.0
    min_p = min(leg_probs) if leg_probs else avg_p
    avg_frag = _mean_leg_field(legs, "fragility", 0.0)
    minute_risk_legs = sum(1 for leg in legs if _float(leg.get("minute_risk_penalty"), 0.0) > 0.0)
    q_leg_count = sum(1 for leg in legs if _float(leg.get("is_questionable"), 0.0) > 0.0)
    hit_prob = _float(slip.get("hit_prob"), 0.0)
    single_game = bool(slip.get("single_game_anchor_legs") is not None or slip.get("single_game_avg_robustness_score") is not None)
    consensus_legs = sum(1 for key in keys if int(consensus_counts.get(key, 0)) >= 2)
    consensus_share = consensus_legs / max(len(keys), 1)
    score = _survival_score(
        cfg,
        n_legs=n_legs,
        avg_p=avg_p,
        min_p=min_p,
        avg_fragility=avg_frag,
        pen_total=0.0,
        minute_risk_legs=minute_risk_legs,
        q_leg_count=q_leg_count,
        consensus_legs=consensus_legs,
        single_game=single_game,
        single_game_avg_robustness=_float(slip.get("single_game_avg_robustness_score"), 0.0),
        single_game_dependency=_float(slip.get("single_game_avg_script_dependency_score"), 0.0),
    )
    passed, reasons = _quality_pass(
        cfg,
        family=family,
        n_legs=n_legs,
        single_game=single_game,
        score=score,
        hit_prob=hit_prob,
        minute_risk_legs=minute_risk_legs,
        q_leg_count=q_leg_count,
    )
    return {
        "public_survival_score": score,
        "public_quality_pass": passed,
        "public_quality_reasons": ",".join(reasons),
        "slip_consensus_legs": int(consensus_legs),
        "slip_consensus_share": float(consensus_share),
        "public_portfolio_status": "",
        "public_portfolio_reason": "",
    }


def _survival_score(
    cfg: Mapping[str, Any] | None,
    *,
    n_legs: int,
    avg_p: float,
    min_p: float,
    avg_fragility: float,
    pen_total: float,
    minute_risk_legs: int,
    q_leg_count: int,
    consensus_legs: int,
    single_game: bool,
    single_game_avg_robustness: float,
    single_game_dependency: float,
) -> float:
    score_cfg = _section(cfg).get("score", {})
    if not isinstance(score_cfg, dict):
        score_cfg = {}
    score = (0.65 * float(min_p)) + (0.35 * float(avg_p))
    score += float(score_cfg.get("consensus_bonus_per_leg", 0.025) or 0.0) * float(consensus_legs)
    score -= float(score_cfg.get("avg_fragility_penalty_w", 0.35) or 0.0) * max(float(avg_fragility) - 0.25, 0.0)
    score -= float(score_cfg.get("pen_total_w", 0.30) or 0.0) * max(float(pen_total), 0.0)
    score -= float(score_cfg.get("minute_risk_penalty", 0.05) or 0.0) * float(max(minute_risk_legs, 0))
    score -= float(score_cfg.get("q_leg_penalty", 0.04) or 0.0) * float(max(q_leg_count, 0))
    if single_game:
        score += float(score_cfg.get("single_game_robustness_w", 0.08) or 0.0) * (float(single_game_avg_robustness) - 0.50)
        score -= float(score_cfg.get("single_game_dependency_w", 0.10) or 0.0) * max(float(single_game_dependency), 0.0)
    return float(max(0.0, min(1.0, score)))


def _quality_pass(
    cfg: Mapping[str, Any] | None,
    *,
    family: str,
    n_legs: int,
    single_game: bool,
    score: float,
    hit_prob: float,
    minute_risk_legs: int,
    q_leg_count: int,
) -> tuple[bool, list[str]]:
    section = _section(cfg)
    if not bool(section.get("enabled", False)):
        return True, []
    reasons: list[str] = []

    thresholds_key = "single_game_min_survival_score_by_legs" if single_game else "min_survival_score_by_legs"
    floor = _by_legs(section.get(thresholds_key), n_legs)
    if floor is not None and float(score) < float(floor):
        reasons.append("survival_score_below_floor")

    hit_key = "single_game_min_hit_prob_by_legs" if single_game else "min_hit_prob_by_legs"
    hit_floor = _by_legs(section.get(hit_key), n_legs)
    if hit_floor is not None and float(hit_prob) < float(hit_floor):
        reasons.append("hit_prob_below_floor")

    max_mr = _by_legs(section.get("max_minute_risk_legs_by_legs"), n_legs)
    if max_mr is not None and int(minute_risk_legs) > int(max_mr):
        reasons.append("minute_risk_legs_exceeded")

    max_q = _by_legs(section.get("max_q_legs_by_legs"), n_legs)
    if max_q is not None and int(q_leg_count) > int(max_q):
        reasons.append("q_leg_count_exceeded")

    return len(reasons) == 0, reasons


def _ensure_quality_columns(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    if frame is None:
        return None
    out = frame.copy()
    for col in PUBLIC_QUALITY_COLUMNS:
        if col not in out.columns:
            if col == "public_quality_pass":
                out[col] = True
            elif col in {"public_survival_score", "slip_consensus_share"}:
                out[col] = 0.0
            elif col == "slip_consensus_legs":
                out[col] = 0
            else:
                out[col] = ""
    return out


def _manifest(
    *,
    enabled: bool,
    kept_frames: Mapping[str, pd.DataFrame | None],
    kept_marketed: list[dict[str, Any]],
    drops: list[dict[str, Any]],
) -> dict[str, Any]:
    kept_counts = {
        name: int(0 if frame is None else len(frame))
        for name, frame in kept_frames.items()
    }
    kept_counts["Marketed"] = len(kept_marketed)
    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled": bool(enabled),
        "kept_counts": kept_counts,
        "dropped_count": len(drops),
        "drops": drops,
    }


def _drop_record(item: Mapping[str, Any], reason: str, keys: set[str]) -> dict[str, Any]:
    return {
        "family": str(item.get("family", "")),
        "name": str(item.get("name", "")),
        "index": int(item.get("index", 0)),
        "reason": reason,
        "prop_keys": sorted(keys),
        "player_keys": sorted({key for key in item.get("player_keys", set()) if key}),
        "survival_score": float(item.get("survival_score", 0.0) or 0.0),
    }


def _section(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cfg, Mapping):
        return {}
    section = cfg.get("public_slip_quality", {}) or {}
    return section if isinstance(section, dict) else {}


def _family_from_name(name: str) -> str:
    text = str(name)
    if text.lower().startswith("system"):
        return "System"
    if text.lower().startswith("windfall"):
        return "Windfall"
    if text.lower().startswith("demonhunter"):
        return "DemonHunter"
    if text.lower().startswith("marketed"):
        return "Marketed"
    return text.split("_", 1)[0]


def _family_enabled_for_slate(
    family: str,
    section: Mapping[str, Any],
    exposure: Mapping[str, Any],
    slate_games: int | None,
) -> bool:
    if family != "DemonHunter":
        return True
    enabled = bool(section.get("include_demonhunter", True))
    by_games = section.get("include_demonhunter_by_slate_games")
    if not isinstance(by_games, Mapping):
        by_games = exposure.get("include_demonhunter_by_slate_games")
    if slate_games is not None and isinstance(by_games, Mapping):
        override = _by_legs(by_games, int(slate_games))
        if override is None:
            override = by_games.get("default")
        if override is not None:
            enabled = bool(override)
    return enabled


def _is_single_game_row(row: pd.Series) -> bool:
    for key in ("single_game_slate", "single_game_profile_active"):
        try:
            if bool(row.get(key, False)):
                return True
        except Exception:
            pass
    return any(str(col).startswith("single_game_") for col in row.index)


def _by_legs(mapping: Any, n_legs: int) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    if n_legs in mapping:
        return mapping[n_legs]
    key = str(int(n_legs))
    return mapping.get(key)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _mean_leg_field(legs: list[Any], key: str, default: float) -> float:
    vals = [_float(leg.get(key), default) for leg in legs if hasattr(leg, "get")]
    return float(sum(vals) / len(vals)) if vals else float(default)
