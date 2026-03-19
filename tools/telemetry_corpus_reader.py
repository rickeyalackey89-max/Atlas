from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import hashlib
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

ID_RE = re.compile(r"\[id:(\d+)\]")
RECOMMENDED_RE = re.compile(r"recommended_(\d)leg(_winprob)?\.csv$", re.IGNORECASE)
RUN_DIR_RE = re.compile(r"^\d{8}_\d{6}$")


@dataclass
class CorpusPaths:
    corpus_input: Path
    corpus_root: Path
    extracted_tmp: Optional[Path]
    runs_dir: Path


class ReaderError(RuntimeError):
    pass


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if pd.isna(x):
            return default
        return int(x)
    except Exception:
        return default


def _normalize_id_token(x: Any) -> Optional[str]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    s = str(x).strip()
    if not s:
        return None
    if s.endswith('.0'):
        try:
            s = str(int(float(s)))
        except Exception:
            pass
    if '|' in s:
        lead = s.split('|', 1)[0].strip()
        if lead:
            s = lead
    return s


def _mean(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return float("nan")
    s = pd.to_numeric(series, errors="coerce")
    return float(s.mean()) if s.notna().any() else float("nan")


def _std(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return float("nan")
    s = pd.to_numeric(series, errors="coerce")
    return float(s.std(ddof=0)) if s.notna().any() else float("nan")


def _weighted_mean(series: pd.Series, weights: pd.Series) -> float:
    s = pd.to_numeric(series, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    mask = s.notna() & w.notna()
    if not mask.any():
        return float("nan")
    denom = float(w[mask].sum())
    if denom == 0.0:
        return float("nan")
    return float((s[mask] * w[mask]).sum() / denom)


def _brier_from_arrays(p: pd.Series, y: pd.Series) -> float:
    p = pd.to_numeric(p, errors="coerce")
    y = pd.to_numeric(y, errors="coerce")
    mask = p.notna() & y.notna()
    if not mask.any():
        return float("nan")
    return float(((p[mask] - y[mask]) ** 2).mean())


def _logloss_from_arrays(p: pd.Series, y: pd.Series) -> float:
    p = pd.to_numeric(p, errors="coerce").clip(1e-6, 1 - 1e-6)
    y = pd.to_numeric(y, errors="coerce")
    mask = p.notna() & y.notna()
    if not mask.any():
        return float("nan")
    pp = p[mask]
    yy = y[mask]
    return float((-(yy * np.log(pp) + (1.0 - yy) * np.log(1.0 - pp))).mean())


def _ece_from_arrays(p: pd.Series, y: pd.Series, buckets: int = 10) -> float:
    df = pd.DataFrame({"p": pd.to_numeric(p, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if df.empty:
        return float("nan")
    bins = pd.interval_range(start=0.0, end=1.0, periods=buckets)
    df["bucket"] = pd.cut(df["p"].clip(0.0, 1.0), bins=bins, include_lowest=True)
    total = len(df)
    ece = 0.0
    for _, grp in df.groupby("bucket", observed=False):
        if grp.empty:
            continue
        ece += (len(grp) / total) * abs(float(grp["p"].mean()) - float(grp["y"].mean()))
    return float(ece)


def _ensure_output_dir(base_root: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base_root / ".atlas_audit" / "diagnostics" / "telemetry_corpus" / ts
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception as exc:
        raise ReaderError(f"Failed reading {path}: {exc}") from exc


def _round_value(v: Any, ndigits: int = 6) -> Any:
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return round(v, ndigits)
    if isinstance(v, dict):
        return {k: _round_value(x, ndigits) for k, x in v.items()}
    if isinstance(v, list):
        return [_round_value(x, ndigits) for x in v]
    return v


def _sha256_file(path: Optional[Path]) -> Optional[str]:
    if not path or not Path(path).exists() or not Path(path).is_file():
        return None
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _top_value_counts(series: pd.Series, limit: int = 10) -> List[Dict[str, Any]]:
    if series is None or len(series) == 0:
        return []
    s = series.dropna()
    if s.empty:
        return []
    counts = s.astype(str).value_counts(dropna=False).head(limit)
    return [{"value": idx, "count": int(val)} for idx, val in counts.items()]


def _runtime_identity_summary(scored_df: pd.DataFrame, args: argparse.Namespace) -> Dict[str, Any]:
    identity_cols = [
        'prob_model_mode', 'prob_active_experiments', 'prob_experiment_flags',
        'telemetry_cal_key', 'telemetry_k_shrink', 'telemetry_under_penalty',
        'telemetry_mult', 'telemetry_bucket_mult', 'telemetry_cal_applied',
        'p_cal_src', 'p_adj_pre_frag_under', 'frag_under_mult', 'frag_under_applied',
    ]
    present_cols = [c for c in identity_cols if c in scored_df.columns]
    column_presence = {c: (c in scored_df.columns) for c in identity_cols}
    active_modes = _top_value_counts(scored_df['prob_model_mode']) if 'prob_model_mode' in scored_df.columns else []
    active_experiments = _top_value_counts(scored_df['prob_active_experiments']) if 'prob_active_experiments' in scored_df.columns else []
    experiment_flags = _top_value_counts(scored_df['prob_experiment_flags']) if 'prob_experiment_flags' in scored_df.columns else []
    telemetry_keys = _top_value_counts(scored_df['telemetry_cal_key']) if 'telemetry_cal_key' in scored_df.columns else []
    p_cal_src = _top_value_counts(scored_df['p_cal_src']) if 'p_cal_src' in scored_df.columns else []
    proof_stats = {}
    if 'telemetry_cal_applied' in scored_df.columns:
        proof_stats['telemetry_applied_share'] = _mean(pd.to_numeric(scored_df['telemetry_cal_applied'], errors='coerce'))
    if 'frag_under_applied' in scored_df.columns:
        proof_stats['frag_under_applied_share'] = _mean(pd.to_numeric(scored_df['frag_under_applied'], errors='coerce'))
    if 'frag_under_mult' in scored_df.columns:
        proof_stats['frag_under_mult_mean'] = _mean(scored_df['frag_under_mult'])
    notes = []
    if 'prob_model_mode' not in scored_df.columns:
        notes.append('prob_model_mode missing; runtime mode cannot be fully proven from scored legs alone.')
    if 'prob_active_experiments' not in scored_df.columns:
        notes.append('prob_active_experiments missing; active experiment registry cannot be fully proven from scored legs alone.')
    if 'p_cal_src' not in scored_df.columns:
        notes.append('p_cal_src missing; calibration source distribution cannot be fully summarized.')
    return {
        'columns_present': present_cols,
        'column_presence': column_presence,
        'prob_model_mode_distribution': active_modes,
        'prob_active_experiments_distribution': active_experiments,
        'prob_experiment_flags_distribution': experiment_flags,
        'telemetry_cal_key_distribution': telemetry_keys,
        'p_cal_src_distribution': p_cal_src,
        'proof_stats': _round_value(proof_stats),
        'file_hashes': {
            'config_yaml_sha256': _sha256_file(args.config_path),
            'calibration_json_sha256': _sha256_file(args.calibration_json_path) if getattr(args, 'calibration_json_path', None) else None,
            'calibration_py_sha256': _sha256_file(args.calibration_py_path) if getattr(args, 'calibration_py_path', None) else None,
            'calibration_map_py_sha256': _sha256_file(args.calibration_map_py_path) if getattr(args, 'calibration_map_py_path', None) else None,
        },
        'notes': notes,
    }


def _scorecard_summary(summary: Dict[str, Any], calib_recs: Dict[str, Any], protected_surfaces: Dict[str, Any]) -> Dict[str, Any]:
    metrics = summary.get('primary_corpus_metrics', {}) or {}
    top_candidates = []
    for cand in calib_recs.get('candidate_scores', [])[:5]:
        top_candidates.append({
            'candidate': cand.get('candidate'),
            'brier': cand.get('brier'),
            'logloss': cand.get('logloss'),
            'ece': cand.get('ece'),
            'improvement_vs_current': cand.get('improvement_vs_current'),
            'pass_share': ((cand.get('gate_summary') or {}).get('pass_share')),
            'overall_clear': ((cand.get('gate_summary') or {}).get('overall_clear')),
            'severe_regressions': ((cand.get('gate_summary') or {}).get('severe_regressions')),
        })
    return _round_value({
        'runs_read': summary.get('primary_runs_read'),
        'settled_eval_rows': metrics.get('settled_eval_rows'),
        'mean_hit': metrics.get('mean_hit'),
        'mean_p_adj': metrics.get('mean_p_adj'),
        'mean_p_cal': metrics.get('mean_p_cal'),
        'brier_p_adj': metrics.get('brier_p_adj'),
        'brier_p_cal': metrics.get('brier_p_cal'),
        'logloss_p_adj': metrics.get('logloss_p_adj'),
        'logloss_p_cal': metrics.get('logloss_p_cal'),
        'games_used_lt5_share': metrics.get('games_used_lt5_share'),
        'role_ctx_outs_used_share': metrics.get('role_ctx_outs_used_share'),
        'questionable_share': metrics.get('questionable_share'),
        'protected_surfaces': protected_surfaces,
        'top_calibration_candidates': top_candidates,
    })




def _protected_surface_summary(leaderboard: List[Dict[str, Any]], primary_label: str) -> Dict[str, Any]:
    row = None
    for item in leaderboard or []:
        if item.get('label') == primary_label:
            row = item
            break
    if row is None and leaderboard:
        row = leaderboard[0]
    if row is None:
        return {}
    return _round_value({
        'label': row.get('label'),
        'strict3': row.get('strict3'),
        'strict4': row.get('strict4'),
        'strict5': row.get('strict5'),
        'hit3': row.get('hit3'),
        'hit4': row.get('hit4'),
        'hit5': row.get('hit5'),
        'dominant_positive': row.get('dominant_positive'),
        'dominant_negative': row.get('dominant_negative'),
    })


def _promotion_blocker_hypotheses(winner_gate: Dict[str, Any], calibration_gate: Dict[str, Any], calibration_improved: bool) -> List[str]:
    hints: List[str] = []
    if not winner_gate.get('overall_clear', False):
        pass_share = _safe_float(winner_gate.get('pass_share'), float('nan'))
        severe = _safe_int(winner_gate.get('severe_regressions'), 0)
        if math.isfinite(pass_share) and pass_share <= 0.0:
            hints.append('variant_breadth_failure')
        elif math.isfinite(pass_share) and pass_share < 1.0:
            hints.append('variant_time_window_instability')
        if severe > 0:
            hints.append('protected_surface_or_regime_regressions')
    if calibration_improved and calibration_gate.get('overall_clear', False):
        hints.append('calibration_only_lead_not_variant_promotion')
    if not hints:
        hints.append('no_clear_blocker_detected')
    return hints

def _knob_advisor_summary(config_recs: Dict[str, Any], calib_recs: Dict[str, Any], runtime_identity: Dict[str, Any]) -> Dict[str, Any]:
    suggested_config_paths = [r.get('path') for r in config_recs.get('recommendations', []) if r.get('apply_now')]
    calibration_mode = calib_recs.get('mode')
    top_candidate = ((calib_recs.get('candidate_scores') or [{}])[0]) if calib_recs.get('candidate_scores') else {}
    top_candidate_name = top_candidate.get('candidate')
    top_improvement = top_candidate.get('improvement_vs_current')
    top_gate = (top_candidate.get('gate_summary') or {}) if isinstance(top_candidate, dict) else {}
    top_overall_clear = bool(top_gate.get('overall_clear', False)) if top_gate else False
    top_pass_share = _safe_float(top_gate.get('pass_share'), float('nan')) if top_gate else float('nan')
    top_severe = _safe_int(top_gate.get('severe_regressions'), 0) if top_gate else 0
    likely_seam = 'reader_policy_strictness'
    next_test = 'diagnostic_only'
    advisory_class = 'no_clear_lead'
    rationale_parts: List[str] = []

    if calibration_mode not in (None, 'keep_identity'):
        likely_seam = 'telemetry_overlay'
        next_test = 'single_raw_sanity'
        advisory_class = 'calibration_only_lead'
        rationale_parts.append(f"Calibration candidate {top_candidate_name} improved corpus Brier and is being treated as an artifact-level overlay lead.")
    elif runtime_identity.get('column_presence', {}).get('frag_under_applied'):
        likely_seam = 'fragility_path'
        next_test = 'diagnostic_only'
        advisory_class = 'core_path_diagnostic'
        rationale_parts.append('Fragility proof fields are present, so the next seam to isolate is the fragility/close-adjustment path rather than the raw kernel.')
    elif runtime_identity.get('column_presence', {}).get('p_cal_src'):
        likely_seam = 'late_calibration'
        advisory_class = 'calibration_path_diagnostic'
        rationale_parts.append('Calibration source tracking is present, which supports a late-calibration / telemetry interpretation before touching core math.')

    if math.isfinite(_safe_float(top_improvement, float('nan'))) and _safe_float(top_improvement, float('nan')) > 0:
        rationale_parts.append(f"Top calibration candidate improvement vs current is {round(_safe_float(top_improvement), 6)}.")
    if top_gate:
        rationale_parts.append(
            f"Calibration gate status: overall_clear={top_overall_clear}, pass_share={round(top_pass_share, 4) if math.isfinite(top_pass_share) else None}, severe_regressions={top_severe}."
        )
    if advisory_class == 'calibration_only_lead' and top_overall_clear and (not math.isfinite(top_pass_share) or top_pass_share >= 1.0) and top_severe == 0:
        rationale_parts.append('This looks like a clean calibration-only lead rather than evidence for a broader config or model promotion.')
    if not rationale_parts and calib_recs.get('reason'):
        rationale_parts.append(str(calib_recs.get('reason')))
    return _round_value({
        'likely_implicated_seam': likely_seam,
        'suggested_next_test_size': next_test,
        'suggested_config_paths': suggested_config_paths,
        'calibration_mode': calibration_mode,
        'advisory_class': advisory_class,
        'top_calibration_candidate': top_candidate_name,
        'top_calibration_candidate_improvement': top_improvement,
        'top_calibration_gate_overall_clear': top_gate.get('overall_clear') if top_gate else None,
        'top_calibration_gate_pass_share': top_gate.get('pass_share') if top_gate else None,
        'top_calibration_gate_severe_regressions': top_gate.get('severe_regressions') if top_gate else None,
        'reason': ' '.join(rationale_parts).strip() if rationale_parts else calib_recs.get('reason'),
    })


def _promotion_guard_summary(primary_label: str, config_recs: Dict[str, Any], calib_recs: Dict[str, Any]) -> Dict[str, Any]:
    leaderboard = config_recs.get('leaderboard', [])
    winner = leaderboard[0] if leaderboard else {}
    winner_label = winner.get('label', primary_label)
    winner_gate = (((config_recs.get('recommendations') or [{}])[0]).get('gate_summary') if config_recs.get('recommendations') else {}) or {}
    top_candidate = ((calib_recs.get('candidate_scores') or [{}])[0]) if calib_recs.get('candidate_scores') else {}
    calibration_gate = (top_candidate.get('gate_summary') or {}) if isinstance(top_candidate, dict) else {}
    top_candidate_name = top_candidate.get('candidate') if isinstance(top_candidate, dict) else None
    top_improvement = _safe_float(top_candidate.get('improvement_vs_current'), float('nan')) if isinstance(top_candidate, dict) else float('nan')
    calibration_improved = math.isfinite(top_improvement) and top_improvement > 0
    blockers: List[Dict[str, Any]] = []
    reasons: List[str] = []
    verdict = 'keep_current_standard'

    if winner_label != primary_label:
        reasons.append(f'Variant winner is {winner_label}, not the primary corpus.')
    else:
        reasons.append('Primary corpus remains the top-ranked config winner, so no config promotion is supported.')

    if not winner_gate.get('overall_clear', False):
        blockers.append({
            'category': 'variant_gate_failure',
            'detail': 'Variant evidence did not clear regime/time-window promotion gates.',
            'pass_share': winner_gate.get('pass_share'),
            'severe_regressions': winner_gate.get('severe_regressions'),
        })
        reasons.append('Variant evidence did not clear regime/time-window promotion gates.')

    if winner_label == primary_label:
        blockers.append({
            'category': 'primary_retains_config_lead',
            'detail': 'The primary corpus still leads the config leaderboard, so no config patch is justified.',
            'winner_label': winner_label,
        })

    if calib_recs.get('mode') == 'keep_identity':
        blockers.append({
            'category': 'calibration_policy_hold',
            'detail': 'Calibration alternatives did not justify promotion over current identity/locked state.',
            'top_candidate': top_candidate_name,
            'improvement_vs_current': top_improvement if math.isfinite(top_improvement) else None,
            'overall_clear': calibration_gate.get('overall_clear'),
            'pass_share': calibration_gate.get('pass_share'),
            'severe_regressions': calibration_gate.get('severe_regressions'),
        })
        reasons.append('Calibration alternatives did not justify promotion over current identity/locked state.')

    if calibration_improved:
        blockers.append({
            'category': 'calibration_only_candidate',
            'detail': 'The leading candidate improves calibration, but the improvement is being treated as calibration-only rather than full variant promotion evidence.',
            'top_candidate': top_candidate_name,
            'improvement_vs_current': top_improvement if math.isfinite(top_improvement) else None,
        })
        reasons.append(f'Calibration candidate {top_candidate_name} improved corpus calibration, but that is being treated as informative rather than promotable under the current policy gates.')

    blocker_hypotheses = _promotion_blocker_hypotheses(winner_gate, calibration_gate, calibration_improved)

    if not blockers:
        verdict = 'promote_candidate_ready_for_review'
        reasons = ['Variant and calibration gates cleared for human review.']
    elif calibration_improved:
        verdict = 'keep_current_standard_with_calibration_only_lead'

    return _round_value({
        'verdict': verdict,
        'winner_label': winner_label,
        'primary_label': primary_label,
        'top_calibration_candidate': top_candidate_name,
        'top_calibration_candidate_improvement': top_improvement if math.isfinite(top_improvement) else None,
        'calibration_candidate_improved': calibration_improved,
        'calibration_candidate_class': 'calibration_only_lead' if calibration_improved else 'none',
        'variant_gate_overall_clear': winner_gate.get('overall_clear'),
        'variant_gate_pass_share': winner_gate.get('pass_share'),
        'variant_gate_severe_regressions': winner_gate.get('severe_regressions'),
        'calibration_gate_overall_clear': calibration_gate.get('overall_clear'),
        'calibration_gate_pass_share': calibration_gate.get('pass_share'),
        'calibration_gate_severe_regressions': calibration_gate.get('severe_regressions'),
        'blockers': blockers,
        'blocker_hypotheses': blocker_hypotheses,
        'reasons': reasons,
    })


def _infer_label(path: Path) -> str:
    stem = path.stem if path.suffix.lower() == ".zip" else path.name
    return stem


def _prepare_corpus(corpus_input: Path) -> CorpusPaths:
    extracted_tmp: Optional[Path] = None
    corpus_root = corpus_input
    force_recursive_run_search = False
    if corpus_input.suffix.lower() == ".zip":
        extracted_tmp = Path(tempfile.mkdtemp(prefix="atlas_corpus_"))
        with zipfile.ZipFile(corpus_input) as zf:
            zf.extractall(extracted_tmp)
        roots = [p for p in extracted_tmp.iterdir() if p.is_dir()]
        top_level_runs = extracted_tmp / "runs"
        nested_corpus_roots = [p for p in roots if p.name != "runs" and (p / "runs").exists()]
        if top_level_runs.exists() and nested_corpus_roots:
            corpus_root = extracted_tmp
            force_recursive_run_search = True
        elif top_level_runs.exists():
            corpus_root = extracted_tmp
        elif len(roots) == 1:
            corpus_root = roots[0]
        elif roots:
            runs_candidates = [p for p in roots if (p / "runs").exists()]
            # Some corpus zips contain multiple top-level corpus folders rather than
            # a single wrapper directory. In that layout we need the extraction root
            # so nested runs under each corpus folder can all be discovered.
            corpus_root = extracted_tmp if len(runs_candidates) > 1 else (runs_candidates[0] if runs_candidates else roots[0])
            force_recursive_run_search = len(runs_candidates) > 1
        else:
            raise ReaderError(f"Zip {corpus_input} did not extract a corpus folder")
    if not corpus_root.exists():
        raise ReaderError(f"Corpus root does not exist: {corpus_root}")
    runs_dir = corpus_root / "runs"
    if force_recursive_run_search or not runs_dir.exists():
        runs_dir = corpus_root
    if not runs_dir.exists():
        raise ReaderError(f"Corpus root is missing readable run folders: {corpus_root}")
    return CorpusPaths(corpus_input=corpus_input, corpus_root=corpus_root, extracted_tmp=extracted_tmp, runs_dir=runs_dir)


def _looks_like_run_dir(p: Path) -> bool:
    if not p.is_dir():
        return False
    if RUN_DIR_RE.match(p.name):
        return True
    if (p / "eval_legs.csv").exists() or (p / "scored_legs_deduped.csv").exists():
        return True
    return False


def _iter_run_dirs(runs_dir: Path) -> List[Path]:
    direct = sorted([p for p in runs_dir.iterdir() if _looks_like_run_dir(p)], key=lambda p: p.name)
    if direct:
        return direct

    nested = []
    for path in runs_dir.rglob("*"):
        if not path.is_dir() or not _looks_like_run_dir(path):
            continue
        if path.parent.name == "runs" or RUN_DIR_RE.match(path.name):
            nested.append(path)

    return sorted(nested, key=lambda p: p.relative_to(runs_dir).as_posix())


def _parse_leg_ids(row: pd.Series) -> List[str]:
    ids: List[str] = []
    for col in [c for c in row.index if c.startswith("leg_")]:
        m = ID_RE.search(str(row[col]))
        if m:
            ids.append(m.group(1))
    return ids


def _slip_metrics_from_file(path: Path, eval_lookup: Dict[str, float], category: str, mode: str) -> Dict[str, Any]:
    df = _read_csv(path)
    if df.empty:
        return {
            "category": category,
            "mode": mode,
            "n_legs": None,
            "slip_count": 0,
            "mean_hit_prob": float("nan"),
            "mean_ev_mult": float("nan"),
            "strict_win_rate": float("nan"),
            "mean_q_leg_count": float("nan"),
        }
    strict_results: List[float] = []
    for _, row in df.iterrows():
        ids = _parse_leg_ids(row)
        vals = [eval_lookup.get(i) for i in ids] if ids else []
        strict_results.append(1.0 if vals and all(v == 1.0 for v in vals) else (0.0 if vals and all(v is not None for v in vals) else float("nan")))
    df = df.copy()
    df["strict_win"] = strict_results
    n_legs = None
    m = RECOMMENDED_RE.search(path.name)
    if m:
        n_legs = int(m.group(1))
    return {
        "category": category,
        "mode": mode,
        "n_legs": n_legs,
        "slip_count": int(len(df)),
        "mean_hit_prob": _mean(df["hit_prob"]) if "hit_prob" in df.columns else float("nan"),
        "mean_ev_mult": _mean(df["ev_mult"]) if "ev_mult" in df.columns else float("nan"),
        "strict_win_rate": _mean(df["strict_win"]) if "strict_win" in df.columns else float("nan"),
        "mean_q_leg_count": _mean(df["q_leg_count"]) if "q_leg_count" in df.columns else float("nan"),
    }


def _extract_config_values(cfg: Dict[str, Any]) -> Dict[str, Any]:
    coeffs_default = (((cfg.get("pp_kernel") or {}).get("coeffs") or {}).get("DEFAULT") or {}).get("STANDARD") or {}
    slip_rank = cfg.get("slip_rank") or {}
    slip_build = cfg.get("slip_build") or {}
    return {
        "pp_kernel.coeffs.DEFAULT.STANDARD.a": coeffs_default.get("a"),
        "pp_kernel.coeffs.DEFAULT.STANDARD.b": coeffs_default.get("b"),
        "slip_rank.ev_payout_power": slip_rank.get("ev_payout_power"),
        "slip_build.target_pool_mult": slip_build.get("target_pool_mult"),
        "slip_build.phase1_frac": slip_build.get("phase1_frac"),
        "slip_build.phase1_pool_frac": slip_build.get("phase1_pool_frac"),
        "slip_build.beam_width": slip_build.get("beam_width"),
        "slip_build.max_slips_per_player": slip_build.get("max_slips_per_player"),
    }


def _bucket_table(df: pd.DataFrame, p_col: str, y_col: str = "hit", buckets: int = 10) -> List[Dict[str, Any]]:
    if p_col not in df.columns or y_col not in df.columns or df.empty:
        return []
    work = df[[p_col, y_col]].copy()
    work[p_col] = pd.to_numeric(work[p_col], errors="coerce")
    work[y_col] = pd.to_numeric(work[y_col], errors="coerce")
    work = work.dropna()
    if work.empty:
        return []
    bins = pd.interval_range(start=0.0, end=1.0, periods=buckets)
    work["bucket"] = pd.cut(work[p_col].clip(0.0, 1.0), bins=bins, include_lowest=True)
    rows = []
    for bucket, grp in work.groupby("bucket", observed=False):
        if grp.empty:
            continue
        mean_pred = float(grp[p_col].mean())
        mean_hit = float(grp[y_col].mean())
        rows.append({
            "bucket": str(bucket),
            "count": int(len(grp)),
            "mean_pred": mean_pred,
            "mean_hit": mean_hit,
            "gap": mean_pred - mean_hit,
            "abs_gap": abs(mean_pred - mean_hit),
        })
    return rows


def _transform_identity(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df.get("p_adj", pd.Series()), errors="coerce").clip(0.0, 1.0)


def _transform_shrink(df: pd.DataFrame, k: float) -> pd.Series:
    p = pd.to_numeric(df.get("p_adj", pd.Series()), errors="coerce").clip(0.0, 1.0)
    return (0.5 + k * (p - 0.5)).clip(0.0, 1.0)


def _transform_under_penalty(df: pd.DataFrame, penalty: float, k: float = 1.0) -> pd.Series:
    p = _transform_shrink(df, k)
    if {"tier", "direction"}.issubset(df.columns):
        tier = df["tier"].astype(str).str.upper().str.strip()
        direction = df["direction"].astype(str).str.upper().str.strip()
        mask = (tier == "STANDARD") & (direction == "UNDER")
        p.loc[mask] = (p.loc[mask] * penalty).clip(0.0, 1.0)
    return p


def _derive_stat_direction_mult(df: pd.DataFrame, min_count: int = 250, max_deviation: float = 0.04) -> Dict[str, float]:
    required = {"stat", "direction", "p_adj", "hit"}
    if not required.issubset(df.columns):
        return {}
    work = df[list(required)].copy()
    work["stat"] = work["stat"].astype(str).str.upper().str.strip()
    work["direction"] = work["direction"].astype(str).str.upper().str.strip()
    work["p_adj"] = pd.to_numeric(work["p_adj"], errors="coerce")
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    work = work.dropna()
    if work.empty:
        return {}
    rows = []
    for (stat, direction), grp in work.groupby(["stat", "direction"], observed=False):
        if len(grp) < min_count:
            continue
        gap = float(grp["hit"].mean() - grp["p_adj"].mean())
        gap = max(-max_deviation, min(max_deviation, gap))
        rows.append((f"{stat}|{direction}", 1.0 + gap))
    return dict(rows)


def _transform_stat_direction(df: pd.DataFrame, mult_map: Dict[str, float], k: float = 1.0, under_penalty: float = 1.0) -> pd.Series:
    p = _transform_under_penalty(df, under_penalty, k=k)
    if not mult_map or not {"stat", "direction"}.issubset(df.columns):
        return p
    key = df["stat"].astype(str).str.upper().str.strip() + "|" + df["direction"].astype(str).str.upper().str.strip()
    mult = key.map(mult_map).fillna(1.0).astype(float)
    return (p * mult).clip(0.0, 1.0)


def _derive_stat_direction_mult_rolectx(df: pd.DataFrame, role_ctx_on: bool = False, min_count: int = 200, max_deviation: float = 0.04) -> Dict[str, float]:
    required = {"stat", "direction", "p_adj", "hit", "role_ctx_outs_used"}
    if not required.issubset(df.columns):
        return {}
    work = df[list(required)].copy()
    if role_ctx_on:
        work = work[pd.to_numeric(work["role_ctx_outs_used"], errors="coerce") > 0]
    else:
        work = work[pd.to_numeric(work["role_ctx_outs_used"], errors="coerce") <= 0]
    work["stat"] = work["stat"].astype(str).str.upper().str.strip()
    work["direction"] = work["direction"].astype(str).str.upper().str.strip()
    work["p_adj"] = pd.to_numeric(work["p_adj"], errors="coerce")
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    work = work.dropna()
    if work.empty:
        return {}
    rows = []
    for (stat, direction), grp in work.groupby(["stat", "direction"], observed=False):
        if len(grp) < min_count:
            continue
        gap = float(grp["hit"].mean() - grp["p_adj"].mean())
        gap = max(-max_deviation, min(max_deviation, gap))
        rows.append((f"{stat}|{direction}", 1.0 + gap))
    return dict(rows)


def _transform_stat_direction_rolectx(df: pd.DataFrame, mult_map: Dict[str, float], role_ctx_on: bool = False, k: float = 1.0, under_penalty: float = 1.0) -> pd.Series:
    p = _transform_under_penalty(df, under_penalty, k=k)
    if not mult_map or not {"stat", "direction", "role_ctx_outs_used"}.issubset(df.columns):
        return p
    key = df["stat"].astype(str).str.upper().str.strip() + "|" + df["direction"].astype(str).str.upper().str.strip()
    mult = key.map(mult_map).fillna(1.0).astype(float)
    role_mask = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce") > 0
    if role_ctx_on:
        # apply multiplier only where role context is on
        applied_mult = role_mask.map({True: 1.0, False: 0.0}).astype(float)
    else:
        # apply multiplier only where role context is off
        applied_mult = (~role_mask).map({True: 1.0, False: 0.0}).astype(float)
    # final multiplier: if applied_mult==1 -> mult, else -> 1.0
    out_mult = pd.Series(np.where(applied_mult.to_numpy() == 1.0, mult.to_numpy(), 1.0), index=df.index).astype(float)
    return (p * out_mult).clip(0.0, 1.0)


def _derive_telemetry_key_mult(df: pd.DataFrame, key_col: str = "telemetry_cal_key", min_count: int = 100, max_deviation: float = 0.05, prior_strength: float = 10.0) -> Dict[str, float]:
    required = {key_col, "p_adj", "hit"}
    if not required.issubset(df.columns):
        return {}
    work = df[[key_col, "p_adj", "hit"]].copy()
    work[key_col] = work[key_col].astype(str).str.upper().str.strip()
    work["p_adj"] = pd.to_numeric(work["p_adj"], errors="coerce")
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    work = work.dropna()
    if work.empty:
        return {}
    # Beta-Binomial posterior mean shrinkage per-key
    # prior_strength acts as pseudo-counts (alpha+beta). We center the prior
    # around the global hit-rate so posterior mean reflects both data and prior.
    global_mean = float(work["hit"].mean())
    prior_a = float(prior_strength) * global_mean
    prior_b = float(prior_strength) * (1.0 - global_mean)
    rows = []
    for key, grp in work.groupby(key_col, observed=False):
        count = len(grp)
        if count < min_count:
            continue
        k_hits = float(grp["hit"].sum())
        mean_pred = float(grp["p_adj"].mean())
        # posterior mean of true hit rate
        post_mean = (k_hits + prior_a) / (count + prior_a + prior_b)
        gap = post_mean - mean_pred
        gap = max(-max_deviation, min(max_deviation, gap))
        rows.append((key, 1.0 + float(gap)))
    return dict(rows)


def _transform_telemetry_key(df: pd.DataFrame, mult_map: Dict[str, float], key_col: str = "telemetry_cal_key", k: float = 1.0, under_penalty: float = 1.0) -> pd.Series:
    p = _transform_under_penalty(df, under_penalty, k=k)
    if not mult_map or key_col not in df.columns:
        return p
    key = df[key_col].astype(str).str.upper().str.strip()
    mult = key.map(mult_map).fillna(1.0).astype(float)
    return (p * mult).clip(0.0, 1.0)

def _transform_telemetry_key_role_off(df: pd.DataFrame, mult_map: Dict[str, float], key_col: str = "telemetry_cal_key", role_col: str = "role_ctx_outs_used", k: float = 1.0, under_penalty: float = 1.0) -> pd.Series:
    """
    Conservative variant: apply per-telemetry-key multipliers only to rows
    where role context is not in effect (role_ctx_outs_used == 0 or missing).
    """
    # Build per-row new multiplier from key map
    if not mult_map or key_col not in df.columns:
        return _transform_under_penalty(df, under_penalty, k=k)
    key = df[key_col].astype(str).str.upper().str.strip()
    new_mult = key.map(mult_map).fillna(1.0).astype(float)

    # Determine role-off mask: treat missing/NaN as role-off (apply multipliers)
    if role_col in df.columns:
        try:
            role_vals = pd.to_numeric(df[role_col], errors="coerce")
            role_off = role_vals.fillna(0) <= 0
        except Exception:
            role_off = pd.Series(True, index=df.index)
    else:
        role_off = pd.Series(True, index=df.index)

    # If runtime-scored baseline exists (p_cal) and telemetry multipliers were
    # already applied at scoring time (telemetry_mult), adjust p_cal by the
    # ratio new_mult / existing_mult for role-off rows so role-on rows remain
    # identical to baseline (avoids unintentional removal of current telemetry).
    if "p_cal" in df.columns and "telemetry_mult" in df.columns:
        p_base = pd.to_numeric(df["p_cal"], errors="coerce").clip(0.0, 1.0)
        existing_mult = pd.to_numeric(df["telemetry_mult"], errors="coerce").fillna(1.0)
        existing_mult = existing_mult.replace(0.0, 1.0)
        ratio = (new_mult / existing_mult).astype(float)
        applied_ratio = pd.Series(1.0, index=df.index)
        applied_ratio[role_off] = ratio[role_off]
        return (p_base * applied_ratio).clip(0.0, 1.0)

    # Fallback: apply new multiplier against p_adj (legacy behavior)
    p = _transform_under_penalty(df, under_penalty, k=k)
    applied_mult = pd.Series(1.0, index=df.index)
    applied_mult[role_off] = new_mult[role_off]
    return (p * applied_mult).clip(0.0, 1.0)


def _transform_telemetry_key_role_on_blend(df: pd.DataFrame, mult_map: Dict[str, float], key_col: str = "telemetry_cal_key", role_col: str = "role_ctx_outs_used", blend: float = 0.1, k: float = 1.0, under_penalty: float = 1.0) -> pd.Series:
    """
    Apply per-telemetry-key multipliers fully to role-off rows, and a
    blended fraction of the multiplier to role-on rows. `blend` in [0,1]
    controls how much of the full multiplier is applied to role-on rows
    (0 => no change, 1 => full multiplier).
    """
    if not mult_map or key_col not in df.columns:
        return _transform_under_penalty(df, under_penalty, k=k)
    key = df[key_col].astype(str).str.upper().str.strip()
    new_mult = key.map(mult_map).fillna(1.0).astype(float)

    # Determine role_on mask: treat missing/NaN as role-off
    if role_col in df.columns:
        try:
            role_vals = pd.to_numeric(df[role_col], errors="coerce")
            role_on = role_vals.fillna(0) > 0
        except Exception:
            role_on = pd.Series(False, index=df.index)
    else:
        role_on = pd.Series(False, index=df.index)

    role_off = ~role_on

    # If runtime-scored baseline exists (p_cal) and telemetry_mult exists,
    # apply ratios so existing telemetry is adjusted rather than overwritten.
    if "p_cal" in df.columns and "telemetry_mult" in df.columns:
        p_base = pd.to_numeric(df["p_cal"], errors="coerce").clip(0.0, 1.0)
        existing_mult = pd.to_numeric(df["telemetry_mult"], errors="coerce").fillna(1.0)
        existing_mult = existing_mult.replace(0.0, 1.0)
        ratio = (new_mult / existing_mult).astype(float)
        applied_ratio = pd.Series(1.0, index=df.index)
        applied_ratio[role_off] = ratio[role_off]
        applied_ratio[role_on] = (1.0 + blend * (ratio[role_on] - 1.0))
        return (p_base * applied_ratio).clip(0.0, 1.0)

    # Fallback: apply blended multiplier against p_adj/under-penalized p
    p = _transform_under_penalty(df, under_penalty, k=k)
    applied_mult = pd.Series(1.0, index=df.index)
    applied_mult[role_off] = new_mult[role_off]
    applied_mult[role_on] = (1.0 + blend * (new_mult[role_on] - 1.0))
    return (p * applied_mult).clip(0.0, 1.0)


def _payload_prefix_allowed(value: Any, prefixes: Optional[List[str]], excludes: Optional[List[str]] = None) -> bool:
    src = str(value).strip().lower()
    if prefixes:
        if not src:
            return False
        allowed = any(src.startswith(str(prefix).strip().lower()) for prefix in prefixes if str(prefix).strip())
    else:
        allowed = True
    if not allowed:
        return False
    if excludes:
        for prefix in excludes:
            prefix_text = str(prefix).strip().lower()
            if prefix_text and src.startswith(prefix_text):
                return False
    return True


def _current_payload_row_multiplier(df: pd.DataFrame, payload: Any) -> pd.Series:
    if df.empty or not isinstance(payload, dict):
        return pd.Series(1.0, index=df.index, dtype=float)

    if {"stat", "direction"}.issubset(df.columns):
        key_series = df["stat"].astype(str).str.upper().str.strip() + "|" + df["direction"].astype(str).str.upper().str.strip()
    elif "telemetry_cal_key" in df.columns:
        key_series = df["telemetry_cal_key"].astype(str).str.upper().str.strip()
    else:
        key_series = pd.Series("", index=df.index, dtype=str)

    role_vals = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce") if "role_ctx_outs_used" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)
    role_on = role_vals.fillna(0) > 0
    role_off = ~role_on

    mult_map = payload.get("mult") if isinstance(payload.get("mult"), dict) else {}
    mult_on_map = payload.get("mult_rolectx_on") if isinstance(payload.get("mult_rolectx_on"), dict) else {}
    mult_off_map = payload.get("mult_rolectx_off") if isinstance(payload.get("mult_rolectx_off"), dict) else {}

    def _lookup(map_obj: Any) -> pd.Series:
        if not map_obj:
            return pd.Series(1.0, index=df.index, dtype=float)
        mapped = key_series.map({str(k).upper().strip(): _safe_float(v, 1.0) for k, v in map_obj.items()}).fillna(1.0).astype(float)
        return mapped

    if mult_on_map or mult_off_map:
        mult = pd.Series(1.0, index=df.index, dtype=float)
        if role_on.any():
            on_mult = _lookup(mult_on_map or mult_map)
            mult.loc[role_on] = on_mult.loc[role_on]
        if role_off.any():
            off_mult = _lookup(mult_off_map or mult_map)
            mult.loc[role_off] = off_mult.loc[role_off]
    else:
        mult = _lookup(mult_map)

    if {"tier", "direction"}.issubset(df.columns):
        under_penalty = _safe_float(payload.get("standard_under_penalty"), 1.0)
        if under_penalty != 1.0:
            tier = df["tier"].astype(str).str.upper().str.strip()
            direction = df["direction"].astype(str).str.upper().str.strip()
            under_mask = (tier == "STANDARD") & (direction == "UNDER")
            mult.loc[under_mask] = mult.loc[under_mask] * under_penalty

    return mult.clip(0.0, 10.0)


def _transform_live_payload_softened(
    df: pd.DataFrame,
    payload: Any,
    soften: float = 0.5,
    focus: str = "all",
) -> pd.Series:
    if df.empty or not isinstance(payload, dict):
        return pd.to_numeric(df.get("p_cal", df.get("p_adj", pd.Series(dtype=float))), errors="coerce").clip(0.0, 1.0)

    base = pd.to_numeric(df["p_cal"] if "p_cal" in df.columns else df.get("p_adj", pd.Series(dtype=float)), errors="coerce").clip(0.0, 1.0)
    if base.empty:
        base = _transform_identity(df)

    current_mult = _current_payload_row_multiplier(df, payload)

    focus = str(focus).strip().lower()
    if "role_ctx_outs_used" in df.columns:
        role_vals = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce")
        role_on = role_vals.fillna(0) > 0
    else:
        role_on = pd.Series(False, index=df.index)
    role_off = ~role_on

    apply_mask = pd.Series(True, index=df.index)
    if focus in {"role_ctx_on", "role_on", "on"}:
        apply_mask = role_on
    elif focus in {"role_ctx_off", "role_off", "off"}:
        apply_mask = role_off

    allowed_mask = pd.Series(True, index=df.index)
    if "p_cal_src" in df.columns:
        apply_only_prefixes = payload.get("apply_only_p_cal_src_prefixes")
        exclude_prefixes = payload.get("exclude_p_cal_src_prefixes")
        if apply_only_prefixes or exclude_prefixes:
            allowed_mask = df["p_cal_src"].map(lambda v: _payload_prefix_allowed(v, apply_only_prefixes, exclude_prefixes))

    target_mask = apply_mask & allowed_mask
    desired_mult = current_mult.copy()
    desired_mult.loc[target_mask] = 1.0 + (current_mult.loc[target_mask] - 1.0) * float(soften)

    safe_current = current_mult.replace(0.0, 1.0)
    ratio = pd.Series(1.0, index=df.index, dtype=float)
    ratio.loc[target_mask] = (desired_mult.loc[target_mask] / safe_current.loc[target_mask]).astype(float)
    return (base * ratio).clip(0.0, 1.0)


def _transform_live_payload_targeted(
    df: pd.DataFrame,
    payload: Any,
    target_keys: List[str],
    soften: float = 0.5,
    focus: str = "all",
) -> pd.Series:
    if df.empty or not isinstance(payload, dict):
        return pd.to_numeric(df.get("p_cal", df.get("p_adj", pd.Series(dtype=float))), errors="coerce").clip(0.0, 1.0)
    if not target_keys:
        return _transform_live_payload_softened(df, payload, soften=soften, focus=focus)

    base = pd.to_numeric(df["p_cal"] if "p_cal" in df.columns else df.get("p_adj", pd.Series(dtype=float)), errors="coerce").clip(0.0, 1.0)
    if base.empty:
        base = _transform_identity(df)

    current_mult = _current_payload_row_multiplier(df, payload)
    key_series = (
        df["telemetry_cal_key"].astype(str).str.upper().str.strip()
        if "telemetry_cal_key" in df.columns
        else (df["stat"].astype(str).str.upper().str.strip() + "|" + df["direction"].astype(str).str.upper().str.strip())
        if {"stat", "direction"}.issubset(df.columns)
        else pd.Series("", index=df.index, dtype=str)
    )

    focus = str(focus).strip().lower()
    if "role_ctx_outs_used" in df.columns:
        role_vals = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce")
        role_on = role_vals.fillna(0) > 0
    else:
        role_on = pd.Series(False, index=df.index)
    role_off = ~role_on

    apply_mask = pd.Series(True, index=df.index)
    if focus in {"role_ctx_on", "role_on", "on"}:
        apply_mask = role_on
    elif focus in {"role_ctx_off", "role_off", "off"}:
        apply_mask = role_off

    allowed_mask = pd.Series(True, index=df.index)
    if "p_cal_src" in df.columns:
        apply_only_prefixes = payload.get("apply_only_p_cal_src_prefixes")
        exclude_prefixes = payload.get("exclude_p_cal_src_prefixes")
        if apply_only_prefixes or exclude_prefixes:
            allowed_mask = df["p_cal_src"].map(lambda v: _payload_prefix_allowed(v, apply_only_prefixes, exclude_prefixes))

    target_mask = apply_mask & allowed_mask & key_series.isin({str(key).upper().strip() for key in target_keys})
    if not target_mask.any():
        return base

    desired_mult = current_mult.copy()
    desired_mult.loc[target_mask] = 1.0 + (current_mult.loc[target_mask] - 1.0) * float(soften)
    safe_current = current_mult.replace(0.0, 1.0)
    ratio = pd.Series(1.0, index=df.index, dtype=float)
    ratio.loc[target_mask] = (desired_mult.loc[target_mask] / safe_current.loc[target_mask]).astype(float)
    return (base * ratio).clip(0.0, 1.0)


def _blend_probability_series(base: pd.Series, correction: pd.Series, mask: pd.Series, mix: float) -> pd.Series:
    if base.empty or correction.empty:
        return base
    out = pd.to_numeric(base, errors="coerce").clip(0.0, 1.0).copy()
    corr = pd.to_numeric(correction, errors="coerce").clip(0.0, 1.0)
    if not isinstance(mask, pd.Series):
        mask = pd.Series(mask, index=out.index)
    mask = mask.reindex(out.index).fillna(False).astype(bool)
    if not mask.any():
        return out
    out.loc[mask] = (out.loc[mask] * (1.0 - mix) + corr.loc[mask] * mix).clip(0.0, 1.0)
    return out


def _score_calibration_candidate(df: pd.DataFrame, name: str, p: pd.Series, meta: Dict[str, Any]) -> Dict[str, Any]:
    y = pd.to_numeric(df.get("hit", pd.Series()), errors="coerce")
    return {
        "candidate": name,
        "brier": _brier_from_arrays(p, y),
        "logloss": _logloss_from_arrays(p, y),
        "ece": _ece_from_arrays(p, y),
        "meta": meta,
    }


def analyze_run(run_dir: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]], pd.DataFrame]:
    run_id = run_dir.name
    eval_path = run_dir / "eval_legs.csv"
    scored_path = run_dir / "scored_legs_deduped.csv"
    if not eval_path.exists() or not scored_path.exists():
        raise ReaderError(f"Run {run_id} is missing eval_legs.csv or scored_legs_deduped.csv")
    eval_df = _read_csv(eval_path)
    scored_df = _read_csv(scored_path)
    if "source_projection_id" not in eval_df.columns or "hit" not in eval_df.columns:
        raise ReaderError(f"Run {run_id} eval_legs.csv is missing source_projection_id/hit")
    eval_lookup: Dict[str, float] = {}
    for v, hit in zip(eval_df["source_projection_id"], eval_df["hit"]):
        key = _normalize_id_token(v)
        if key is None:
            continue
        eval_lookup[key] = _safe_float(hit)
        raw = str(v).strip()
        if raw and raw != key:
            eval_lookup[raw] = _safe_float(hit)
    slip_rows = []
    for folder_name, category in [(None, "top"), ("System", "system"), ("Windfall", "windfall")]:
        base = run_dir if folder_name is None else run_dir / folder_name
        if not base.exists():
            continue
        for path in sorted(base.glob("recommended_*leg*.csv")):
            mode = "winprob" if "_winprob" in path.name.lower() else "ev"
            metrics = _slip_metrics_from_file(path, eval_lookup, category=category, mode=mode)
            metrics["run_id"] = run_id
            slip_rows.append(metrics)
    scored = scored_df.copy()
    if "hit" not in scored.columns:
        key_col = None
        if "projection_id" in scored.columns and "projection_id" in eval_df.columns:
            key_col = "projection_id"
        elif "source_projection_id" in scored.columns and "source_projection_id" in eval_df.columns:
            key_col = "source_projection_id"
        if key_col is not None:
            hit_map = eval_df[[key_col, "hit"]].drop_duplicates().copy()
            scored = scored.merge(hit_map, on=key_col, how="left")
    for col in ["p_adj", "p_cal", "hit", "games_used", "role_ctx_outs_used", "q_out_frac", "is_questionable"]:
        if col in scored.columns:
            scored[col] = pd.to_numeric(scored[col], errors="coerce")
    scored["run_id"] = run_id
    run_metrics = {
        "run_id": run_id,
        "eval_rows": int(len(eval_df)),
        "settled_eval_rows": int(pd.to_numeric(eval_df["hit"], errors="coerce").notna().sum()) if "hit" in eval_df.columns else 0,
        "mean_hit": _mean(scored["hit"]) if "hit" in scored.columns else float("nan"),
        "mean_p_adj": _mean(scored["p_adj"]) if "p_adj" in scored.columns else float("nan"),
        "mean_p_cal": _mean(scored["p_cal"]) if "p_cal" in scored.columns else float("nan"),
        "brier_p_adj": _brier_from_arrays(scored["p_adj"], scored["hit"]) if {"p_adj", "hit"}.issubset(scored.columns) else float("nan"),
        "brier_p_cal": _brier_from_arrays(scored["p_cal"], scored["hit"]) if {"p_cal", "hit"}.issubset(scored.columns) else float("nan"),
        "logloss_p_adj": _logloss_from_arrays(scored["p_adj"], scored["hit"]) if {"p_adj", "hit"}.issubset(scored.columns) else float("nan"),
        "logloss_p_cal": _logloss_from_arrays(scored["p_cal"], scored["hit"]) if {"p_cal", "hit"}.issubset(scored.columns) else float("nan"),
        "games_used_min": _safe_float(scored["games_used"].min()) if "games_used" in scored.columns else float("nan"),
        "games_used_lt5_share": float((scored["games_used"] < 5).mean()) if "games_used" in scored.columns else float("nan"),
        "role_ctx_outs_used_share": float((scored["role_ctx_outs_used"] > 0).mean()) if "role_ctx_outs_used" in scored.columns else float("nan"),
        "questionable_share": _mean(scored["is_questionable"]) if "is_questionable" in scored.columns else float("nan"),
        "q_out_frac_mean": _mean(scored["q_out_frac"]) if "q_out_frac" in scored.columns else float("nan"),
        "p_cal_equal_p_adj_share": float((scored["p_cal"].round(8) == scored["p_adj"].round(8)).mean()) if {"p_cal", "p_adj"}.issubset(scored.columns) else float("nan"),
    }
    return {
        "run_metrics": run_metrics,
        "p_adj_buckets": _bucket_table(scored, "p_adj"),
        "p_cal_buckets": _bucket_table(scored, "p_cal") if "p_cal" in scored.columns else [],
    }, slip_rows, scored


def _summarize_slips(slip_df: pd.DataFrame) -> pd.DataFrame:
    if slip_df.empty:
        return pd.DataFrame(columns=["category", "mode", "n_legs", "slip_count", "mean_hit_prob", "mean_ev_mult", "strict_win_rate", "mean_q_leg_count"])
    return slip_df.groupby(["category", "mode", "n_legs"], dropna=False).agg(
        slip_count=("slip_count", "sum"),
        mean_hit_prob=("mean_hit_prob", "mean"),
        mean_ev_mult=("mean_ev_mult", "mean"),
        strict_win_rate=("strict_win_rate", "mean"),
        mean_q_leg_count=("mean_q_leg_count", "mean"),
    ).reset_index()


def _summarize_slips_per_run(raw_slip_df: pd.DataFrame) -> pd.DataFrame:
    if raw_slip_df.empty:
        return pd.DataFrame(columns=["run_id", "category", "mode", "n_legs", "slip_count", "mean_hit_prob", "mean_ev_mult", "strict_win_rate", "mean_q_leg_count"])
    return raw_slip_df.groupby(["run_id", "category", "mode", "n_legs"], dropna=False).agg(
        slip_count=("slip_count", "sum"),
        mean_hit_prob=("mean_hit_prob", "mean"),
        mean_ev_mult=("mean_ev_mult", "mean"),
        strict_win_rate=("strict_win_rate", "mean"),
        mean_q_leg_count=("mean_q_leg_count", "mean"),
    ).reset_index()


def _corpus_metrics_from_per_run(per_run_df: pd.DataFrame) -> Dict[str, Any]:
    w = per_run_df["settled_eval_rows"] if "settled_eval_rows" in per_run_df.columns else pd.Series(dtype=float)
    return {
        "eval_rows": int(per_run_df["eval_rows"].sum()),
        "settled_eval_rows": int(per_run_df["settled_eval_rows"].sum()),
        "mean_hit": _weighted_mean(per_run_df["mean_hit"] if "mean_hit" in per_run_df.columns else pd.Series(dtype=float), w),
        "mean_p_adj": _weighted_mean(per_run_df["mean_p_adj"] if "mean_p_adj" in per_run_df.columns else pd.Series(dtype=float), w),
        "mean_p_cal": _weighted_mean(per_run_df["mean_p_cal"] if "mean_p_cal" in per_run_df.columns else pd.Series(dtype=float), w),
        "brier_p_adj": _weighted_mean(per_run_df["brier_p_adj"] if "brier_p_adj" in per_run_df.columns else pd.Series(dtype=float), w),
        "brier_p_cal": _weighted_mean(per_run_df["brier_p_cal"] if "brier_p_cal" in per_run_df.columns else pd.Series(dtype=float), w),
        "logloss_p_adj": _weighted_mean(per_run_df["logloss_p_adj"] if "logloss_p_adj" in per_run_df.columns else pd.Series(dtype=float), w),
        "logloss_p_cal": _weighted_mean(per_run_df["logloss_p_cal"] if "logloss_p_cal" in per_run_df.columns else pd.Series(dtype=float), w),
        "games_used_lt5_share": _weighted_mean(per_run_df["games_used_lt5_share"] if "games_used_lt5_share" in per_run_df.columns else pd.Series(dtype=float), w),
        "role_ctx_outs_used_share": _weighted_mean(per_run_df["role_ctx_outs_used_share"] if "role_ctx_outs_used_share" in per_run_df.columns else pd.Series(dtype=float), w),
        "questionable_share": _weighted_mean(per_run_df["questionable_share"] if "questionable_share" in per_run_df.columns else pd.Series(dtype=float), w),
        "q_out_frac_mean": _weighted_mean(per_run_df["q_out_frac_mean"] if "q_out_frac_mean" in per_run_df.columns else pd.Series(dtype=float), w),
        "p_cal_equal_p_adj_share": _weighted_mean(per_run_df["p_cal_equal_p_adj_share"] if "p_cal_equal_p_adj_share" in per_run_df.columns else pd.Series(dtype=float), w),
        "run_count": int(len(per_run_df)),
    }


def _pick_summary_metric(system_ev_summary: pd.DataFrame, n: int, col: str) -> float:
    sub = system_ev_summary[system_ev_summary["n_legs"] == n]
    return _safe_float(sub[col].iloc[0]) if not sub.empty else float("nan")


def _pick_run_metric(system_ev_per_run: pd.DataFrame, n: int, col: str) -> pd.Series:
    sub = system_ev_per_run[system_ev_per_run["n_legs"] == n].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    return pd.to_numeric(sub[col], errors="coerce")




def _window_groups_from_run_ids(run_ids: List[str]) -> List[Tuple[str, List[str]]]:
    ordered = sorted([str(x) for x in run_ids if pd.notna(x)])
    if not ordered:
        return []
    groups: List[Tuple[str, List[str]]] = [("all_runs", ordered)]
    if len(ordered) >= 4:
        mid = len(ordered) // 2
        groups.append(("older_half", ordered[:mid]))
        groups.append(("recent_half", ordered[mid:]))
    if len(ordered) >= 6:
        tail = max(2, len(ordered) // 3)
        groups.append(("recent_third", ordered[-tail:]))
    return groups


def _pav_fit(y: np.ndarray) -> np.ndarray:
    """Pool-Adjacent-Violators (PAV) isotonic regression on 1D array y.

    Returns fitted values (same length) that are non-decreasing.
    """
    y_arr = np.asarray(y, dtype=float)
    n = len(y_arr)
    if n == 0:
        return np.array([], dtype=float)
    # Initialize blocks
    avgs: List[float] = []
    sizes: List[int] = []
    for v in y_arr.tolist():
        avgs.append(float(v))
        sizes.append(1)
        # Merge while last average < previous average (violates monotonicity)
        while len(avgs) >= 2 and avgs[-2] > avgs[-1]:
            s = avgs[-2] * sizes[-2] + avgs[-1] * sizes[-1]
            sz = sizes[-2] + sizes[-1]
            avg = s / sz
            avgs[-2] = avg
            sizes[-2] = sz
            avgs.pop()
            sizes.pop()
    # Expand blocks back into fitted array
    fitted = np.empty(n, dtype=float)
    idx = 0
    for avg, sz in zip(avgs, sizes):
        fitted[idx : idx + sz] = avg
        idx += sz
    return fitted


def _transform_isotonic_cv(df: pd.DataFrame, source_col: str = "p_adj", y_col: str = "hit", n_splits: int = 5, random_seed: int = 7) -> pd.Series:
    """Cross-validated isotonic mapping of `source_col` -> hit.

    Returns a pd.Series of calibrated probabilities aligned with df.index.
    Uses run-based folds when `run_id` is present, otherwise positional K-fold.
    """
    out = pd.Series(np.nan, index=df.index, dtype=float)
    if df.empty or source_col not in df.columns or y_col not in df.columns:
        return out
    p_full = pd.to_numeric(df[source_col], errors="coerce")
    y_full = pd.to_numeric(df[y_col], errors="coerce")
    n = len(df)
    if n == 0:
        return out

    # Determine fold indices
    if "run_id" in df.columns and df["run_id"].notna().sum() >= n_splits:
        runs = list(df["run_id"].astype(str).unique())
        rng = np.random.RandomState(random_seed)
        rng.shuffle(runs)
        folds: List[List[str]] = [[] for _ in range(n_splits)]
        for i, r in enumerate(runs):
            folds[i % n_splits].append(r)
        for fold_runs in folds:
            test_mask = df["run_id"].astype(str).isin(fold_runs)
            train_mask = ~test_mask
            if train_mask.sum() < 50:
                continue
            train_p = p_full[train_mask].dropna()
            train_y = y_full[train_mask].dropna()
            test_p = p_full[test_mask]
            if train_p.empty or train_p.nunique() < 2:
                continue
            order = np.argsort(train_p.to_numpy())
            p_sorted = train_p.to_numpy()[order]
            y_sorted = train_y.to_numpy()[order]
            fitted = _pav_fit(y_sorted)
            # aggregate duplicates in xp for stable interpolation
            xp = p_sorted
            fp = fitted
            uniq_x = []
            uniq_fp = []
            if len(xp) > 0:
                cur_x = xp[0]
                acc = [fp[0]]
                for xv, fv in zip(xp[1:], fp[1:]):
                    if xv == cur_x:
                        acc.append(fv)
                    else:
                        uniq_x.append(cur_x)
                        uniq_fp.append(float(np.mean(acc)))
                        cur_x = xv
                        acc = [fv]
                uniq_x.append(cur_x)
                uniq_fp.append(float(np.mean(acc)))
            if len(uniq_x) == 0:
                continue
            if len(uniq_x) == 1:
                preds = np.full(test_p.shape, uniq_fp[0], dtype=float)
            else:
                preds = np.interp(test_p.fillna(uniq_x[0]).to_numpy(), np.array(uniq_x), np.array(uniq_fp), left=uniq_fp[0], right=uniq_fp[-1])
            out[test_mask] = preds
    else:
        # positional K-fold
        rng = np.random.RandomState(random_seed)
        perm = rng.permutation(n)
        folds_list = [f.tolist() for f in np.array_split(perm, n_splits)]
        for fold in folds_list:
            if len(fold) == 0:
                continue
            test_pos = fold
            train_pos = np.setdiff1d(np.arange(n), test_pos).tolist()
            train_p = p_full.iloc[train_pos].dropna()
            train_y = y_full.iloc[train_pos].dropna()
            test_p = p_full.iloc[test_pos]
            if train_p.empty or train_p.nunique() < 2:
                continue
            order = np.argsort(train_p.to_numpy())
            p_sorted = train_p.to_numpy()[order]
            y_sorted = train_y.to_numpy()[order]
            fitted = _pav_fit(y_sorted)
            # aggregate duplicates
            xp = p_sorted
            fp = fitted
            uniq_x = []
            uniq_fp = []
            if len(xp) > 0:
                cur_x = xp[0]
                acc = [fp[0]]
                for xv, fv in zip(xp[1:], fp[1:]):
                    if xv == cur_x:
                        acc.append(fv)
                    else:
                        uniq_x.append(cur_x)
                        uniq_fp.append(float(np.mean(acc)))
                        cur_x = xv
                        acc = [fv]
                uniq_x.append(cur_x)
                uniq_fp.append(float(np.mean(acc)))
            if len(uniq_x) == 0:
                continue
            if len(uniq_x) == 1:
                preds = np.full(len(test_pos), uniq_fp[0], dtype=float)
            else:
                preds = np.interp(test_p.fillna(uniq_x[0]).to_numpy(), np.array(uniq_x), np.array(uniq_fp), left=uniq_fp[0], right=uniq_fp[-1])
            out.iloc[test_pos] = pd.Series(preds, index=[out.index[i] for i in test_pos])

    # fill any remaining NA with a global fit on all data
    if out.isna().any():
        train_p = p_full.dropna()
        train_y = y_full.dropna()
        if not train_p.empty and train_p.nunique() >= 1:
            order = np.argsort(train_p.to_numpy())
            p_sorted = train_p.to_numpy()[order]
            y_sorted = train_y.to_numpy()[order]
            fitted = _pav_fit(y_sorted)
            xp = p_sorted
            fp = fitted
            uniq_x = []
            uniq_fp = []
            cur_x = None
            for xv, fv in zip(xp, fp):
                if cur_x is None:
                    cur_x = xv
                    acc = [fv]
                elif xv == cur_x:
                    acc.append(fv)
                else:
                    uniq_x.append(cur_x)
                    uniq_fp.append(float(np.mean(acc)))
                    cur_x = xv
                    acc = [fv]
            if cur_x is not None:
                uniq_x.append(cur_x)
                uniq_fp.append(float(np.mean(acc)))
            if len(uniq_x) == 1:
                out[out.isna()] = uniq_fp[0]
            elif len(uniq_x) > 1:
                out[out.isna()] = np.interp(p_full[out.isna()].fillna(uniq_x[0]).to_numpy(), np.array(uniq_x), np.array(uniq_fp), left=uniq_fp[0], right=uniq_fp[-1])

    return out.clip(0.0, 1.0)


def _slice_scored_windows(scored_df: pd.DataFrame) -> List[Tuple[str, pd.DataFrame]]:
    if scored_df.empty or "run_id" not in scored_df.columns:
        return [("all_runs", scored_df)]
    groups = []
    for name, ids in _window_groups_from_run_ids(scored_df["run_id"].dropna().astype(str).unique().tolist()):
        groups.append((name, scored_df[scored_df["run_id"].astype(str).isin(ids)].copy()))
    return groups


def _calibration_regime_slices(scored_df: pd.DataFrame) -> List[Tuple[str, pd.DataFrame]]:
    slices: List[Tuple[str, pd.DataFrame]] = []
    for name, sub in _slice_scored_windows(scored_df):
        if len(sub) >= 200:
            slices.append((name, sub))
    if "direction" in scored_df.columns:
        for direction in ["OVER", "UNDER"]:
            sub = scored_df[scored_df["direction"].astype(str).str.upper().str.strip() == direction]
            if len(sub) >= 200:
                slices.append((f"direction_{direction.lower()}", sub.copy()))
    if "games_used" in scored_df.columns:
        buckets = [("games_lt5", scored_df[pd.to_numeric(scored_df["games_used"], errors="coerce") < 5]), ("games_5to9", scored_df[(pd.to_numeric(scored_df["games_used"], errors="coerce") >= 5) & (pd.to_numeric(scored_df["games_used"], errors="coerce") < 10)]), ("games_10plus", scored_df[pd.to_numeric(scored_df["games_used"], errors="coerce") >= 10])]
        for name, sub in buckets:
            if len(sub) >= 200:
                slices.append((name, sub.copy()))
    if "role_ctx_outs_used" in scored_df.columns:
        off = scored_df[pd.to_numeric(scored_df["role_ctx_outs_used"], errors="coerce") <= 0]
        on = scored_df[pd.to_numeric(scored_df["role_ctx_outs_used"], errors="coerce") > 0]
        if len(off) >= 200:
            slices.append(("role_ctx_off", off.copy()))
        if len(on) >= 200:
            slices.append(("role_ctx_on", on.copy()))
    return slices


def _evaluate_calibration_gates(scored_df: pd.DataFrame, candidate_p: pd.Series, baseline_p: pd.Series) -> Dict[str, Any]:
    slices = _calibration_regime_slices(scored_df)
    rows: List[Dict[str, Any]] = []
    pass_count = 0
    severe_regressions = 0
    eligible = 0
    for name, sub in slices:
        idx = sub.index
        cand_brier = _brier_from_arrays(candidate_p.loc[idx], sub.get("hit", pd.Series()))
        base_brier = _brier_from_arrays(baseline_p.loc[idx], sub.get("hit", pd.Series()))
        if not (math.isfinite(cand_brier) and math.isfinite(base_brier)):
            continue
        eligible += 1
        delta = base_brier - cand_brier
        passed = delta >= 0.0005
        severe = delta <= -0.0010
        pass_count += int(passed)
        severe_regressions += int(severe)
        rows.append({"slice": name, "rows": int(len(sub)), "delta_brier": delta, "pass": passed, "severe_regression": severe})
    pass_share = (pass_count / eligible) if eligible else 0.0
    overall_clear = pass_share >= 0.70 and severe_regressions == 0
    return {"eligible_slices": eligible, "pass_count": pass_count, "pass_share": pass_share, "severe_regressions": severe_regressions, "overall_clear": overall_clear, "slice_rows": rows}


def _variant_window_metrics(per_run_df: pd.DataFrame, slip_per_run_df: pd.DataFrame, run_ids: List[str]) -> Dict[str, float]:
    sub_slips = slip_per_run_df[(slip_per_run_df["category"] == "system") & (slip_per_run_df["mode"] == "ev") & (slip_per_run_df["run_id"].astype(str).isin(run_ids))].copy()
    out: Dict[str, float] = {}
    for n in [3,4,5]:
        sub = sub_slips[sub_slips["n_legs"] == n]
        out[f"strict{n}"] = _mean(sub.get("strict_win_rate", pd.Series(dtype=float)))
        out[f"hit{n}"] = _mean(sub.get("mean_hit_prob", pd.Series(dtype=float)))
        out[f"ev{n}"] = _mean(sub.get("mean_ev_mult", pd.Series(dtype=float)))
    per = per_run_df[per_run_df["run_id"].astype(str).isin(run_ids)]
    out["games_used_lt5_share"] = _mean(per.get("games_used_lt5_share", pd.Series(dtype=float)))
    return out


def _evaluate_variant_evidence(candidate_entry: Dict[str, Any], baseline_entry: Dict[str, Any]) -> Dict[str, Any]:
    run_ids = sorted(set(candidate_entry["per_run_df"]["run_id"].astype(str).tolist()) & set(baseline_entry["per_run_df"]["run_id"].astype(str).tolist()))
    groups = _window_groups_from_run_ids(run_ids)
    rows: List[Dict[str, Any]] = []
    pass_count = 0
    eligible = 0
    severe_regressions = 0
    for name, ids in groups:
        cand = _variant_window_metrics(candidate_entry["per_run_df"], candidate_entry["slip_per_run_df"], ids)
        base = _variant_window_metrics(baseline_entry["per_run_df"], baseline_entry["slip_per_run_df"], ids)
        gate_pass = True
        gate_severe = False
        detail = {"window": name, "run_count": len(ids)}
        for metric, tol, floor in [("strict3", 0.0025, -0.0040), ("strict4", 0.0025, -0.0040), ("hit3", 0.0020, -0.0040), ("hit4", 0.0020, -0.0040)]:
            delta = cand.get(metric, float('nan')) - base.get(metric, float('nan')) if math.isfinite(cand.get(metric, float('nan'))) and math.isfinite(base.get(metric, float('nan'))) else float('nan')
            detail[f"delta_{metric}"] = delta
            if math.isfinite(delta):
                eligible += 1
                if delta >= -tol:
                    pass_count += 1
                else:
                    gate_pass = False
                if delta <= floor:
                    gate_severe = True
                    severe_regressions += 1
        sample_delta = cand.get("games_used_lt5_share", float('nan')) - base.get("games_used_lt5_share", float('nan')) if math.isfinite(cand.get("games_used_lt5_share", float('nan'))) and math.isfinite(base.get("games_used_lt5_share", float('nan'))) else float('nan')
        detail["delta_games_used_lt5_share"] = sample_delta
        if math.isfinite(sample_delta) and sample_delta > 0.01:
            gate_pass = False
        detail["pass"] = gate_pass
        detail["severe_regression"] = gate_severe
        rows.append(detail)
    pass_share = (pass_count / eligible) if eligible else 0.0
    overall_clear = pass_share >= 0.70 and severe_regressions == 0
    return {"eligible_checks": eligible, "pass_count": pass_count, "pass_share": pass_share, "severe_regressions": severe_regressions, "overall_clear": overall_clear, "window_rows": rows}


def _score_variant(
    config_values: Dict[str, Any],
    per_run_df: pd.DataFrame,
    slip_metrics_df: pd.DataFrame,
    slip_per_run_df: pd.DataFrame,
    primary_reference: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    system_ev = slip_metrics_df[(slip_metrics_df["category"] == "system") & (slip_metrics_df["mode"] == "ev")].copy()
    system_ev_per_run = slip_per_run_df[(slip_per_run_df["category"] == "system") & (slip_per_run_df["mode"] == "ev")].copy()

    strict3 = _pick_summary_metric(system_ev, 3, "strict_win_rate")
    strict4 = _pick_summary_metric(system_ev, 4, "strict_win_rate")
    strict5 = _pick_summary_metric(system_ev, 5, "strict_win_rate")
    ev3 = _pick_summary_metric(system_ev, 3, "mean_ev_mult")
    ev4 = _pick_summary_metric(system_ev, 4, "mean_ev_mult")
    ev5 = _pick_summary_metric(system_ev, 5, "mean_ev_mult")
    hit3 = _pick_summary_metric(system_ev, 3, "mean_hit_prob")
    hit4 = _pick_summary_metric(system_ev, 4, "mean_hit_prob")
    hit5 = _pick_summary_metric(system_ev, 5, "mean_hit_prob")

    strict3_std = _std(_pick_run_metric(system_ev_per_run, 3, "strict_win_rate"))
    strict4_std = _std(_pick_run_metric(system_ev_per_run, 4, "strict_win_rate"))
    strict5_std = _std(_pick_run_metric(system_ev_per_run, 5, "strict_win_rate"))

    corpus_metrics = _corpus_metrics_from_per_run(per_run_df)
    components: Dict[str, float] = {}
    components["realized_core"] = (
        1.00 * (strict3 if math.isfinite(strict3) else 0.0)
        + 0.80 * (strict4 if math.isfinite(strict4) else 0.0)
        + 0.55 * (strict5 if math.isfinite(strict5) else 0.0)
    )
    components["pricing_secondary"] = 0.012 * sum(v for v in [ev3, ev4, ev5] if math.isfinite(v))
    components["stability_penalty"] = -1.00 * sum(v for v in [strict3_std, strict4_std, strict5_std] if math.isfinite(v))
    components["sample_penalty"] = -0.20 * (corpus_metrics.get("games_used_lt5_share") or 0.0)

    protection_penalty = 0.0
    consistency_bonus = 0.0
    relative: Dict[str, float] = {}
    if primary_reference is not None:
        for name, cur, weight, tol in [
            ("strict3", strict3, 4.0, 0.0025),
            ("strict4", strict4, 3.0, 0.0025),
            ("strict5", strict5, 2.0, 0.0025),
            ("hit3", hit3, 6.0, 0.0020),
            ("hit4", hit4, 5.0, 0.0020),
            ("hit5", hit5, 3.0, 0.0020),
        ]:
            ref = primary_reference.get(name, float("nan"))
            delta = cur - ref if math.isfinite(cur) and math.isfinite(ref) else float("nan")
            relative[f"delta_{name}"] = delta
            if math.isfinite(delta):
                if delta < -tol:
                    protection_penalty += weight * abs(delta + tol)
                else:
                    consistency_bonus += min(delta, 0.02) * (0.25 * weight)
        for name, cur, weight in [("ev3", ev3, 0.10), ("ev4", ev4, 0.08), ("ev5", ev5, 0.06)]:
            ref = primary_reference.get(name, float("nan"))
            delta = cur - ref if math.isfinite(cur) and math.isfinite(ref) else float("nan")
            relative[f"delta_{name}"] = delta
            if math.isfinite(delta):
                consistency_bonus += weight * max(-0.5, min(0.5, delta))
        relative["delta_games_used_lt5_share"] = (corpus_metrics.get("games_used_lt5_share") or 0.0) - (primary_reference.get("corpus_metrics", {}).get("games_used_lt5_share") or 0.0)
        if math.isfinite(relative["delta_games_used_lt5_share"]):
            if relative["delta_games_used_lt5_share"] > 0.005:
                protection_penalty += 0.75 * relative["delta_games_used_lt5_share"]
            else:
                consistency_bonus += 0.05 * abs(min(0.0, relative["delta_games_used_lt5_share"]))
    components["short_slip_protection_penalty"] = -protection_penalty
    components["relative_consistency_bonus"] = consistency_bonus

    score = sum(components.values())
    dominant_positive = max(components.items(), key=lambda kv: kv[1])[0] if components else None
    dominant_negative = min(components.items(), key=lambda kv: kv[1])[0] if components else None
    return {
        "score": score,
        "config_values": config_values,
        "strict3": strict3,
        "strict4": strict4,
        "strict5": strict5,
        "ev3": ev3,
        "ev4": ev4,
        "ev5": ev5,
        "hit3": hit3,
        "hit4": hit4,
        "hit5": hit5,
        "strict3_std": strict3_std,
        "strict4_std": strict4_std,
        "strict5_std": strict5_std,
        "corpus_metrics": corpus_metrics,
        "score_components": components,
        "relative_metrics": relative,
        "dominant_positive": dominant_positive,
        "dominant_negative": dominant_negative,
    }


def _regime_tables(scored_df: pd.DataFrame, slip_metrics_df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    if scored_df.empty:
        return out
    work = scored_df.copy()
    if {"p_adj", "hit"}.issubset(work.columns):
        out["direction_split"] = []
        if "direction" in work.columns:
            rows = []
            for direction, grp in work.groupby(work["direction"].astype(str).str.upper().str.strip(), observed=False):
                p_adj = grp["p_adj"] if "p_adj" in grp.columns else pd.Series(dtype=float)
                p_cal = grp["p_cal"] if "p_cal" in grp.columns else pd.Series(dtype=float)
                hit = grp["hit"] if "hit" in grp.columns else pd.Series(dtype=float)
                rows.append({
                    "direction": direction,
                    "count": int(len(grp)),
                    "mean_p_adj": _mean(p_adj),
                    "mean_p_cal": _mean(p_cal) if "p_cal" in grp.columns else float("nan"),
                    "hit_rate": _mean(hit),
                    "brier_p_adj": _brier_from_arrays(p_adj, hit),
                })
            out["direction_split"] = rows
        if "stat" in work.columns:
            rows = []
            for stat, grp in work.groupby(work["stat"].astype(str).str.upper().str.strip(), observed=False):
                if len(grp) < 50:
                    continue
                p_adj = grp["p_adj"] if "p_adj" in grp.columns else pd.Series(dtype=float)
                hit = grp["hit"] if "hit" in grp.columns else pd.Series(dtype=float)
                rows.append({
                    "stat": stat,
                    "count": int(len(grp)),
                    "mean_p_adj": _mean(p_adj),
                    "hit_rate": _mean(hit),
                    "brier_p_adj": _brier_from_arrays(p_adj, hit),
                })
            rows.sort(key=lambda r: (-r["count"], r["stat"]))
            out["stat_split"] = rows[:25]
        if "role_ctx_outs_used" in work.columns:
            rows = []
            for label, grp in [("outs_used_off", work[work["role_ctx_outs_used"] <= 0]), ("outs_used_on", work[work["role_ctx_outs_used"] > 0])]:
                p_adj = grp["p_adj"] if "p_adj" in grp.columns else pd.Series(dtype=float)
                hit = grp["hit"] if "hit" in grp.columns else pd.Series(dtype=float)
                rows.append({
                    "bucket": label,
                    "count": int(len(grp)),
                    "mean_p_adj": _mean(p_adj),
                    "hit_rate": _mean(hit),
                    "brier_p_adj": _brier_from_arrays(p_adj, hit),
                })
            out["role_ctx_split"] = rows
        if "games_used" in work.columns:
            bins = [(-1, 4, "lt5"), (4, 9, "5to9"), (9, 19, "10to19"), (19, 9999, "20plus")]
            rows = []
            for lo, hi, label in bins:
                grp = work[(work["games_used"] > lo) & (work["games_used"] <= hi)]
                p_adj = grp["p_adj"] if "p_adj" in grp.columns else pd.Series(dtype=float)
                hit = grp["hit"] if "hit" in grp.columns else pd.Series(dtype=float)
                rows.append({
                    "bucket": label,
                    "count": int(len(grp)),
                    "mean_p_adj": _mean(p_adj),
                    "hit_rate": _mean(hit),
                    "brier_p_adj": _brier_from_arrays(p_adj, hit),
                })
            out["games_used_split"] = rows
    if not slip_metrics_df.empty:
        out["slip_split"] = [{str(k): v for k, v in row.items()} for row in slip_metrics_df.to_dict(orient="records")]
    return out


def _drift_table(per_run_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if per_run_df.empty:
        return []
    work = per_run_df.sort_values("run_id").copy()
    rows: List[Dict[str, Any]] = []
    for _, row in work.iterrows():
        rows.append({
            "run_id": row["run_id"],
            "mean_hit": _safe_float(row.get("mean_hit")),
            "mean_p_adj": _safe_float(row.get("mean_p_adj")),
            "mean_p_cal": _safe_float(row.get("mean_p_cal")),
            "brier_p_adj": _safe_float(row.get("brier_p_adj")),
            "brier_p_cal": _safe_float(row.get("brier_p_cal")),
            "games_used_lt5_share": _safe_float(row.get("games_used_lt5_share")),
            "role_ctx_outs_used_share": _safe_float(row.get("role_ctx_outs_used_share")),
        })
    return rows


def build_calibration_recommendations(scored_df: pd.DataFrame, current_json: Any, current_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if scored_df.empty or not {"p_adj", "hit"}.issubset(scored_df.columns):
        return {"mode": "keep_identity", "confidence": "low", "reason": "Insufficient telemetry for calibration analysis", "candidate_scores": []}
    p_cal_series = scored_df["p_cal"] if "p_cal" in scored_df.columns else pd.Series(dtype=float)
    baseline_p = pd.to_numeric(p_cal_series, errors="coerce") if not p_cal_series.empty else _transform_identity(scored_df)
    if baseline_p.isna().all():
        baseline_p = _transform_identity(scored_df)
    raw_candidates: List[Tuple[str, pd.Series, Dict[str, Any]]] = []
    raw_candidates.append(("identity", _transform_identity(scored_df), {"family": "identity"}))

    if isinstance(current_json, dict):
        weak_over_keys = ["RA|OVER", "PA|OVER", "PR|OVER", "PRA|OVER", "REB|OVER", "AST|OVER", "PTS|OVER"]
        for soften in [0.75, 0.50, 0.25]:
            raw_candidates.append((
                f"live_soft_all_{soften:.2f}",
                _transform_live_payload_softened(scored_df, current_json, soften=soften, focus="all"),
                {"family": "live_payload_soften", "focus": "all", "soften": soften},
            ))
            raw_candidates.append((
                f"live_targeted_weak_over_all_{soften:.2f}",
                _transform_live_payload_targeted(scored_df, current_json, weak_over_keys, soften=soften, focus="all"),
                {"family": "live_payload_targeted", "focus": "all", "soften": soften, "target_keys": weak_over_keys},
            ))
        if "role_ctx_outs_used" in scored_df.columns:
            raw_candidates.append((
                "live_soft_role_ctx_on_0.50",
                _transform_live_payload_softened(scored_df, current_json, soften=0.50, focus="role_ctx_on"),
                {"family": "live_payload_soften", "focus": "role_ctx_on", "soften": 0.50},
            ))
            raw_candidates.append((
                "live_soft_role_ctx_off_0.50",
                _transform_live_payload_softened(scored_df, current_json, soften=0.50, focus="role_ctx_off"),
                {"family": "live_payload_soften", "focus": "role_ctx_off", "soften": 0.50},
            ))
            raw_candidates.append((
                "live_targeted_weak_over_role_ctx_on_0.50",
                _transform_live_payload_targeted(scored_df, current_json, weak_over_keys, soften=0.50, focus="role_ctx_on"),
                {"family": "live_payload_targeted", "focus": "role_ctx_on", "soften": 0.50, "target_keys": weak_over_keys},
            ))

    for k in [0.96, 0.92, 0.88]:
        raw_candidates.append((f"shrink_{k}", _transform_shrink(scored_df, k), {"family": "shrink", "k": k}))
    for penalty in [0.98, 0.96, 0.94]:
        raw_candidates.append((f"under_penalty_{penalty}", _transform_under_penalty(scored_df, penalty=penalty, k=1.0), {"family": "under_penalty", "penalty": penalty}))
    # telemetry-key based multipliers (per telemetry_cal_key with partial pooling)
    telemetry_cfg = (current_cfg or {}).get("telemetry", {}) if current_cfg is not None else {}
    t_min_count = int(telemetry_cfg.get("min_count", 100))
    t_pooling_tau = float(telemetry_cfg.get("pooling_tau", 200.0))
    t_max_deviation = float(telemetry_cfg.get("max_deviation", 0.05))
    t_prior_strength = float(telemetry_cfg.get("prior_strength", 10.0))
    t_isotonic_kfold = int(telemetry_cfg.get("isotonic_kfold", 5))
    stat_dir_min = int(telemetry_cfg.get("stat_direction_min_count", 250))
    stat_dir_max_dev = float(telemetry_cfg.get("stat_direction_max_deviation", 0.04))
    rolectx_min = int(telemetry_cfg.get("rolectx_min_count", 200))
    rolectx_max_dev = float(telemetry_cfg.get("rolectx_max_deviation", 0.04))

    mult_map = _derive_stat_direction_mult(scored_df, min_count=stat_dir_min, max_deviation=stat_dir_max_dev)
    if mult_map:
        raw_candidates.append(("stat_direction_light", _transform_stat_direction(scored_df, mult_map, k=0.96, under_penalty=0.98), {"family": "stat_direction", "mult_map": mult_map}))

    telemetry_map = _derive_telemetry_key_mult(scored_df, key_col="telemetry_cal_key", min_count=t_min_count, max_deviation=t_max_deviation, prior_strength=t_prior_strength)
    if telemetry_map:
        raw_candidates.append(("telemetry_key_light", _transform_telemetry_key(scored_df, telemetry_map, key_col="telemetry_cal_key", k=0.96, under_penalty=0.98), {"family": "telemetry_key", "mult_map": telemetry_map}))
        # Conservative variant: only apply telemetry-key multipliers to rows without role-context
        if "role_ctx_outs_used" in scored_df.columns:
            raw_candidates.append(("telemetry_key_role_off_light", _transform_telemetry_key_role_off(scored_df, telemetry_map, key_col="telemetry_cal_key", role_col="role_ctx_outs_used", k=0.96, under_penalty=0.98), {"family": "telemetry_key_role_off", "mult_map": telemetry_map}))
            # Blend variant: apply full multipliers to role-off and a small
            # blended fraction to role-on rows to cautiously extend benefits.
            raw_candidates.append(("telemetry_key_role_on_blend", _transform_telemetry_key_role_on_blend(scored_df, telemetry_map, key_col="telemetry_cal_key", role_col="role_ctx_outs_used", blend=0.1, k=0.96, under_penalty=0.98), {"family": "telemetry_key_role_on_blend", "mult_map": telemetry_map, "blend": 0.1}))
            if "run_id" in scored_df.columns:
                base_role_off = _transform_telemetry_key_role_off(scored_df, telemetry_map, key_col="telemetry_cal_key", role_col="role_ctx_outs_used", k=0.96, under_penalty=0.98)
                role_on_blend = _transform_telemetry_key_role_on_blend(scored_df, telemetry_map, key_col="telemetry_cal_key", role_col="role_ctx_outs_used", blend=0.1, k=0.96, under_penalty=0.98)
                role_on_mask = pd.to_numeric(scored_df["role_ctx_outs_used"], errors="coerce") > 0
                run_ids = sorted(scored_df["run_id"].astype(str).dropna().unique().tolist())
                recent_third_ids = set(run_ids[-max(2, len(run_ids) // 3):]) if run_ids else set()
                recent_mask = scored_df["run_id"].astype(str).isin(recent_third_ids)
                weak_over_mask = scored_df["telemetry_cal_key"].astype(str).str.upper().str.strip().isin({"RA|OVER", "PA|OVER", "PR|OVER", "PRA|OVER", "REB|OVER", "AST|OVER", "PTS|OVER"})
                hybrid_masks = {
                    "role_ctx_on": role_on_mask & weak_over_mask,
                    "recent_third": recent_mask & weak_over_mask,
                    "role_ctx_on_recent_third": role_on_mask & recent_mask & weak_over_mask,
                }
                recent_third_micro_mask = recent_mask & weak_over_mask
                for mix in [0.10, 0.20]:
                    for focus_name, mask in hybrid_masks.items():
                        raw_candidates.append((
                            f"hybrid_role_off_plus_onblend_{focus_name}_{mix:.2f}",
                            _blend_probability_series(base_role_off, role_on_blend, mask, mix),
                            {"family": "hybrid_role_off_plus_onblend", "focus": focus_name, "mix": mix, "base": "telemetry_key_role_off_light", "correction": "telemetry_key_role_on_blend"},
                        ))
                for mix in [0.02, 0.05]:
                    raw_candidates.append((
                        f"hybrid_role_off_plus_onblend_recent_third_micro_{mix:.2f}",
                        _blend_probability_series(base_role_off, role_on_blend, recent_third_micro_mask, mix),
                        {"family": "hybrid_role_off_plus_onblend_micro", "focus": "recent_third", "mix": mix, "base": "telemetry_key_role_off_light", "correction": "telemetry_key_role_on_blend"},
                    ))
            # If a calibration JSON was supplied and contains explicit multipliers
            # and a blend fraction, evaluate that exact payload as an additional
            # candidate so users can test supplied artifacts (e.g. blend tweaks).
            if current_json and isinstance(current_json, dict) and current_json.get("mult") is not None:
                try:
                    supplied_mult = current_json.get("mult", {})
                    blend_value = current_json.get("blend")
                    supplied_blend = _safe_float(blend_value) if blend_value is not None else None
                    supplied_k = float(current_json.get("k_shrink", 0.96))
                    supplied_up = float(current_json.get("standard_under_penalty", 0.98))
                    if supplied_blend is not None:
                        raw_candidates.append(("telemetry_key_role_on_blend_supplied", _transform_telemetry_key_role_on_blend(scored_df, supplied_mult, key_col="telemetry_cal_key", role_col="role_ctx_outs_used", blend=supplied_blend, k=supplied_k, under_penalty=supplied_up), {"family": "telemetry_key_role_on_blend_supplied", "mult_map": supplied_mult, "blend": supplied_blend}))
                except Exception:
                    # Best-effort: ignore malformed supplied payloads
                    pass
    # Cross-validated isotonic stacker (maps p_adj -> calibrated p using PAV)
    try:
        isotonic_pred = _transform_isotonic_cv(scored_df, source_col="p_adj", y_col="hit", n_splits=t_isotonic_kfold)
        if not isotonic_pred.isna().all():
            raw_candidates.append(("isotonic_cv", isotonic_pred, {"family": "isotonic_cv", "kfold": t_isotonic_kfold}))
    except Exception:
        pass
    # role-context aware stat|direction multipliers (derive separately on rows where role context applied or not)
    if "role_ctx_outs_used" in scored_df.columns:
        rolectx_off_map = _derive_stat_direction_mult_rolectx(scored_df, role_ctx_on=False, min_count=rolectx_min, max_deviation=rolectx_max_dev)
        if rolectx_off_map:
            raw_candidates.append(("stat_direction_rolectx_off", _transform_stat_direction_rolectx(scored_df, rolectx_off_map, role_ctx_on=False, k=0.96, under_penalty=0.98), {"family": "stat_direction_rolectx", "role_ctx": "off", "mult_map": rolectx_off_map}))
        rolectx_on_map = _derive_stat_direction_mult_rolectx(scored_df, role_ctx_on=True, min_count=rolectx_min, max_deviation=rolectx_max_dev)
        if rolectx_on_map:
            raw_candidates.append(("stat_direction_rolectx_on", _transform_stat_direction_rolectx(scored_df, rolectx_on_map, role_ctx_on=True, k=0.96, under_penalty=0.98), {"family": "stat_direction_rolectx", "role_ctx": "on", "mult_map": rolectx_on_map}))
    candidates: List[Dict[str, Any]] = []
    hit_series = scored_df["hit"] if "hit" in scored_df.columns else pd.Series(dtype=float)
    current_brier = _brier_from_arrays(baseline_p, hit_series)
    for name, p, meta in raw_candidates:
        cand = _score_calibration_candidate(scored_df, name, p, meta)
        gate = _evaluate_calibration_gates(scored_df, p, baseline_p)
        cand["gate_summary"] = gate
        cand["improvement_vs_current"] = current_brier - cand["brier"] if math.isfinite(current_brier) and math.isfinite(cand["brier"]) else float("nan")
        gate_bonus = 0.0005 * gate["pass_count"]
        severe_penalty = 0.005 * gate["severe_regressions"]
        cand["gated_score"] = (cand["improvement_vs_current"] if math.isfinite(cand["improvement_vs_current"]) else -1e9) + gate_bonus - severe_penalty
        candidates.append(cand)
    candidates = sorted(candidates, key=lambda x: (-x["gated_score"], x["brier"], x["logloss"], x["ece"], x["candidate"]))
    best = candidates[0]
    improvement = current_brier - best["brier"] if math.isfinite(current_brier) and math.isfinite(best["brier"]) else 0.0
    mode = "keep_identity"
    confidence = "high"
    reason = "Calibration alternatives do not clear the regime/time-window promotion gates."
    suggested_payload: Dict[str, Any] = {"mode": "keep_identity"}
    apply_now = False
    if best["candidate"] != "identity" and improvement >= 0.0015 and best["gate_summary"]["overall_clear"] and best["gate_summary"]["pass_share"] >= 0.70:
        mode = "fit_candidate"
        confidence = "medium"
        reason = f"Candidate {best['candidate']} cleared overall and regime/time-window gates with corpus Brier improvement {round(improvement, 6)}."
        suggested_payload = {"mode": best["meta"]["family"], "candidate": best["candidate"], "meta": best["meta"]}
    elif best["candidate"] == "identity":
        reason = "Identity remains the best or statistically tied calibration candidate on the joined corpus."
    return {
        "mode": mode,
        "confidence": confidence,
        "reason": reason,
        "current_brier_proxy": current_brier,
        "candidate_scores": candidates,
        "suggested_payload": suggested_payload,
        "apply_now": apply_now,
        "current_json_present": current_json is not None,
    }


def build_logic_recommendations(calibration_py_path: Optional[Path], calibration_map_py_path: Optional[Path], calib_recs: Dict[str, Any]) -> Dict[str, Any]:
    recs = []
    for target in [calibration_py_path, calibration_map_py_path]:
        if not target:
            continue
        rec_type = "keep" if calib_recs.get("mode") == "keep_identity" else "inspect"
        reason = "No structural calibration logic change is supported by the corpus yet." if rec_type == "keep" else "Artifact-level candidate improved, but logic changes should be reviewed manually after artifact validation."
        recs.append({
            "target_file": str(target),
            "recommendation_type": rec_type,
            "reason": reason,
            "risk": "low" if rec_type == "keep" else "medium",
        })
    return {"recommendations": recs}


def build_config_recommendations(current_config_values: Dict[str, Any], primary_label: str, variant_rankings: List[Dict[str, Any]], variant_entries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    winner = variant_rankings[0]
    recs: List[Dict[str, Any]] = []
    win_cfg = winner.get("config_values", {})
    threshold = 0.01
    score_gap = winner["score"] - variant_rankings[1]["score"] if len(variant_rankings) > 1 else 0.0
    gate_summary = {"overall_clear": False, "pass_share": 0.0, "window_rows": []}
    if winner["label"] != primary_label and winner["label"] in variant_entries and primary_label in variant_entries:
        gate_summary = _evaluate_variant_evidence(variant_entries[winner["label"]], variant_entries[primary_label])
    promote = winner["label"] != primary_label and score_gap > threshold and gate_summary.get("overall_clear", False)
    for path, cur_val in current_config_values.items():
        suggested = win_cfg.get(path, cur_val)
        if promote and suggested != cur_val:
            reason = f"Variant {winner['label']} led the corpus leaderboard by score gap {round(score_gap, 6)} and cleared regime/time-window gates for promotion."
            confidence = "medium"
            apply_now = True
        else:
            suggested = cur_val
            reason = "Current value remains the leading or statistically tied corpus choice after regime/time-window gates."
            confidence = "high"
            apply_now = False
        recs.append({
            "path": path,
            "current_value": cur_val,
            "suggested_value": suggested,
            "confidence": confidence,
            "reason": reason,
            "apply_now": apply_now,
            "winner_label": winner["label"],
            "winner_score": winner["score"],
            "gate_summary": gate_summary,
        })
    return {"recommendations": recs, "leaderboard": variant_rankings}


def _merge_patch(current_cfg: Dict[str, Any], config_recs: Dict[str, Any]) -> Dict[str, Any]:
    cfg = json.loads(json.dumps(current_cfg))
    for rec in config_recs["recommendations"]:
        if not rec.get("apply_now"):
            continue
        path = rec["path"].split(".")
        cursor = cfg
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = rec["suggested_value"]
    return cfg


def _read_corpus(corpus_input: Path) -> Tuple[CorpusPaths, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, List[Dict[str, Any]]]:
    paths = _prepare_corpus(corpus_input)
    run_payloads: List[Dict[str, Any]] = []
    slip_rows: List[Dict[str, Any]] = []
    scored_parts: List[pd.DataFrame] = []
    skipped_runs: List[Dict[str, Any]] = []
    try:
        for run_dir in _iter_run_dirs(paths.runs_dir):
            try:
                payload, run_slip_rows, scored = analyze_run(run_dir)
            except ReaderError as exc:
                skipped_runs.append({"run_id": run_dir.name, "reason": str(exc)})
                continue
            run_payloads.append(payload)
            slip_rows.extend(run_slip_rows)
            scored_parts.append(scored)
        if not run_payloads:
            skipped_msg = f"; skipped={len(skipped_runs)}" if skipped_runs else ""
            raise ReaderError(f"No readable runs found under {paths.runs_dir}{skipped_msg}")
        per_run = pd.DataFrame([x["run_metrics"] for x in run_payloads])
        raw_slip_df = pd.DataFrame(slip_rows)
        slip_df = _summarize_slips(raw_slip_df)
        slip_per_run_df = _summarize_slips_per_run(raw_slip_df)
        scored_df = pd.concat(scored_parts, ignore_index=True) if scored_parts else pd.DataFrame()
        if skipped_runs:
            per_run.attrs["skipped_runs"] = skipped_runs
        return paths, per_run, slip_df, slip_per_run_df, scored_df, run_payloads
    except Exception:
        if paths.extracted_tmp and paths.extracted_tmp.exists():
            shutil.rmtree(paths.extracted_tmp, ignore_errors=True)
        raise


def _load_variant_manifest(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path:
        return []
    data = _load_json(path)
    if isinstance(data, dict) and "variants" in data:
        data = data["variants"]
    if not isinstance(data, list):
        raise ReaderError("Variant manifest must be a list or an object with variants[]")
    out = []
    for item in data:
        out.append({
            "label": item["label"],
            "corpus_input": Path(item["corpus_input"]),
            "config_path": Path(item["config_path"]) if item.get("config_path") else None,
        })
    return out


def _variant_entry(label: str, corpus_input: Path, config_path: Optional[Path]) -> Dict[str, Any]:
    return {"label": label, "corpus_input": corpus_input, "config_path": config_path}


def _build_markdown(summary: Dict[str, Any], config_recs: Dict[str, Any], calib_recs: Dict[str, Any], logic_recs: Dict[str, Any]) -> str:
    lines = ["# Telemetry Corpus Reader — Full Reader v1.4", ""]
    lines.append(f"Generated: `{summary['generated_at']}`")
    lines.append("")
    lines.append("## Primary corpus")
    lines.append(f"- Label: `{summary['primary_label']}`")
    lines.append(f"- Runs read: `{summary['primary_runs_read']}`")
    lines.append(f"- Settled legs: `{summary['primary_corpus_metrics']['settled_eval_rows']}`")
    lines.append("")
    runtime_identity = summary.get('runtime_identity', {}) or {}
    scorecard = summary.get('scorecard', {}) or {}
    knob_advisor = summary.get('knob_advisor', {}) or {}
    promotion_guard = summary.get('promotion_guard', {}) or {}
    lines.append("## Runtime identity")
    for row in runtime_identity.get('prob_model_mode_distribution', [])[:5]:
        lines.append(f"- prob_model_mode `{row['value']}`: {row['count']}")
    for row in runtime_identity.get('prob_active_experiments_distribution', [])[:5]:
        lines.append(f"- prob_active_experiments `{row['value']}`: {row['count']}")
    if runtime_identity.get('notes'):
        for note in runtime_identity['notes']:
            lines.append(f"- note: {note}")
    lines.append("")
    lines.append("## Scorecard")
    lines.append(f"- Brier p_adj: `{scorecard.get('brier_p_adj')}`")
    lines.append(f"- Brier p_cal: `{scorecard.get('brier_p_cal')}`")
    lines.append(f"- Logloss p_adj: `{scorecard.get('logloss_p_adj')}`")
    lines.append(f"- Logloss p_cal: `{scorecard.get('logloss_p_cal')}`")
    lines.append(f"- games_used_lt5_share: `{scorecard.get('games_used_lt5_share')}`")
    protected = scorecard.get('protected_surfaces', {}) or {}
    if protected:
        lines.append(f"- Protected surfaces [{protected.get('label')}]: strict3=`{protected.get('strict3')}` strict4=`{protected.get('strict4')}` strict5=`{protected.get('strict5')}` hit3=`{protected.get('hit3')}` hit4=`{protected.get('hit4')}` hit5=`{protected.get('hit5')}`")
        if protected.get('dominant_positive') or protected.get('dominant_negative'):
            lines.append(f"- Protected surface tilt: pos=`{protected.get('dominant_positive')}` neg=`{protected.get('dominant_negative')}`")
    lines.append("")
    lines.append("## Knob advisor")
    lines.append(f"- Likely seam: `{knob_advisor.get('likely_implicated_seam')}`")
    lines.append(f"- Suggested next test size: `{knob_advisor.get('suggested_next_test_size')}`")
    lines.append(f"- Advisory class: `{knob_advisor.get('advisory_class')}`")
    if knob_advisor.get('top_calibration_candidate'):
        lines.append(f"- Top calibration candidate: `{knob_advisor.get('top_calibration_candidate')}`")
    if knob_advisor.get('top_calibration_candidate_improvement') is not None:
        lines.append(f"- Candidate improvement vs current: `{knob_advisor.get('top_calibration_candidate_improvement')}`")
    if knob_advisor.get('top_calibration_gate_overall_clear') is not None:
        lines.append(f"- Candidate gate clear: `{knob_advisor.get('top_calibration_gate_overall_clear')}` pass_share=`{knob_advisor.get('top_calibration_gate_pass_share')}` severe_regressions=`{knob_advisor.get('top_calibration_gate_severe_regressions')}`")
    lines.append(f"- Reason: {knob_advisor.get('reason')}")
    lines.append("")
    lines.append("## Promotion guard")
    lines.append(f"- Verdict: `{promotion_guard.get('verdict')}`")
    if promotion_guard.get('top_calibration_candidate'):
        lines.append(f"- Top calibration candidate: `{promotion_guard.get('top_calibration_candidate')}` improvement=`{promotion_guard.get('top_calibration_candidate_improvement')}` improved=`{promotion_guard.get('calibration_candidate_improved')}`")
    for blocker in promotion_guard.get('blockers', []):
        lines.append(f"- blocker[{blocker.get('category')}]: {blocker.get('detail')}")
    for hint in promotion_guard.get('blocker_hypotheses', []):
        lines.append(f"- blocker_hypothesis: `{hint}`")
    for reason in promotion_guard.get('reasons', []):
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("## Variant leaderboard")
    for row in config_recs["leaderboard"]:
        lines.append(f"- `{row['label']}` score={round(row['score'], 6)} strict3={round(_safe_float(row['strict3'], 0.0), 4)} strict4={round(_safe_float(row['strict4'], 0.0), 4)} strict5={round(_safe_float(row['strict5'], 0.0), 4)} hit3={round(_safe_float(row['hit3'], 0.0), 4)} hit4={round(_safe_float(row['hit4'], 0.0), 4)} pos={row.get('dominant_positive')} neg={row.get('dominant_negative')}")
    lines.append("")
    lines.append("## Config recommendations")
    for rec in config_recs["recommendations"]:
        lines.append(f"- `{rec['path']}` -> `{rec['suggested_value']}` ({rec['confidence']}); {rec['reason']}")
    lines.append("")
    lines.append("## Calibration recommendation")
    lines.append(f"- Mode: `{calib_recs['mode']}` ({calib_recs['confidence']}); {calib_recs['reason']}")
    top_candidates = calib_recs.get("candidate_scores", [])[:5]
    for cand in top_candidates:
        lines.append(f"  - `{cand['candidate']}` brier={round(_safe_float(cand['brier']), 6)} logloss={round(_safe_float(cand['logloss']), 6)} ece={round(_safe_float(cand['ece']), 6)}")
    lines.append("")
    lines.append("## Logic recommendations")
    for rec in logic_recs["recommendations"]:
        lines.append(f"- `{rec['target_file']}` -> {rec['recommendation_type']}; {rec['reason']}")
    return "\n".join(lines) + "\n"


def run_reader(args: argparse.Namespace) -> Path:
    output_dir = _ensure_output_dir(args.output_root or args.corpus_input)
    current_cfg = _load_yaml(args.config_path)
    current_config_values = _extract_config_values(current_cfg)
    primary_label = args.primary_label or _infer_label(args.corpus_input)
    primary_paths, primary_per_run, primary_slips, primary_slips_per_run, primary_scored, primary_payloads = _read_corpus(args.corpus_input)
    calibration_json = _load_json(args.calibration_json_path) if args.calibration_json_path and args.calibration_json_path.exists() else None

    variant_entry_list: List[Dict[str, Any]] = [_variant_entry(primary_label, args.corpus_input, args.config_path)]
    variant_entry_list.extend(_load_variant_manifest(args.variant_manifest_json))
    for corpus_input in args.comparison_corpus_input or []:
        label = _infer_label(corpus_input)
        cfg_path = None
        if args.comparison_config_map and str(corpus_input) in args.comparison_config_map:
            cfg_path = Path(args.comparison_config_map[str(corpus_input)])
        variant_entry_list.append(_variant_entry(label, corpus_input, cfg_path))

    seen = set()
    normalized_entries = []
    for entry in variant_entry_list:
        if entry["label"] in seen:
            continue
        seen.add(entry["label"])
        normalized_entries.append(entry)

    variant_rankings = []
    variant_entries: Dict[str, Dict[str, Any]] = {}
    primary_corpus_metrics = _corpus_metrics_from_per_run(primary_per_run)
    regime_tables = _regime_tables(primary_scored, primary_slips)
    drift_rows = _drift_table(primary_per_run)
    primary_reference = _score_variant(current_config_values, primary_per_run, primary_slips, primary_slips_per_run, None)
    try:
        for entry in normalized_entries:
            if entry["label"] == primary_label:
                per_run_df, slip_metrics, slip_per_run_df = primary_per_run, primary_slips, primary_slips_per_run
                cfg_values = current_config_values
            else:
                paths, per_run_df, slip_metrics, slip_per_run_df, _, _ = _read_corpus(entry["corpus_input"])
                cfg_values = current_config_values
                if entry.get("config_path") and Path(entry["config_path"]).exists():
                    cfg_values = _extract_config_values(_load_yaml(Path(entry["config_path"])))
                if paths.extracted_tmp and paths.extracted_tmp.exists():
                    shutil.rmtree(paths.extracted_tmp, ignore_errors=True)
            scored = _score_variant(cfg_values, per_run_df, slip_metrics, slip_per_run_df, primary_reference)
            scored["label"] = entry["label"]
            variant_rankings.append(scored)
            variant_entries[entry["label"]] = {"score": scored, "per_run_df": per_run_df, "slip_metrics_df": slip_metrics, "slip_per_run_df": slip_per_run_df, "config_values": cfg_values}
        variant_rankings = sorted(variant_rankings, key=lambda x: (-x["score"], x["label"]))
        for i, row in enumerate(variant_rankings, start=1):
            row["rank"] = i

        config_recs = build_config_recommendations(current_config_values, primary_label, variant_rankings, variant_entries)
        calib_recs = build_calibration_recommendations(primary_scored, calibration_json, current_cfg)
        logic_recs = build_logic_recommendations(args.calibration_py_path, args.calibration_map_py_path, calib_recs)
        proposed_cfg = _merge_patch(current_cfg, config_recs)
        proposed_cal_json = calib_recs.get("suggested_payload", {"mode": "keep_identity"})

        runtime_identity = _runtime_identity_summary(primary_scored, args)
        protected_surfaces = _protected_surface_summary(variant_rankings, primary_label)
        scorecard = _scorecard_summary({
            "primary_runs_read": int(len(primary_per_run)),
            "primary_corpus_metrics": primary_corpus_metrics,
        }, calib_recs, protected_surfaces)
        knob_advisor = _knob_advisor_summary(config_recs, calib_recs, runtime_identity)
        promotion_guard = _promotion_guard_summary(primary_label, config_recs, calib_recs)

        summary = {
            "generated_at": _now_utc(),
            "primary_label": primary_label,
            "corpus_input": str(args.corpus_input),
            "primary_runs_read": int(len(primary_per_run)),
            "primary_corpus_metrics": _round_value(primary_corpus_metrics),
            "primary_bucket_tables": {
                "p_adj": [p["p_adj_buckets"] for p in primary_payloads],
                "p_cal": [p["p_cal_buckets"] for p in primary_payloads],
            },
            "regime_tables": _round_value(regime_tables),
            "drift_rows": _round_value(drift_rows),
            "variant_labels": [x["label"] for x in variant_rankings],
            "runtime_identity": _round_value(runtime_identity),
            "scorecard": _round_value(scorecard),
            "knob_advisor": _round_value(knob_advisor),
            "promotion_guard": _round_value(promotion_guard),
        }

        (output_dir / "corpus_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (output_dir / "runtime_identity.json").write_text(json.dumps(_round_value(runtime_identity), indent=2), encoding="utf-8")
        (output_dir / "corpus_summary.md").write_text(_build_markdown(summary, _round_value(config_recs), _round_value(calib_recs), _round_value(logic_recs)), encoding="utf-8")
        (output_dir / "config_recommendations.json").write_text(json.dumps(_round_value(config_recs), indent=2), encoding="utf-8")
        (output_dir / "calibration_recommendations.json").write_text(json.dumps(_round_value(calib_recs), indent=2), encoding="utf-8")
        (output_dir / "logic_recommendations.json").write_text(json.dumps(_round_value(logic_recs), indent=2), encoding="utf-8")
        (output_dir / "candidate_scores.json").write_text(json.dumps(_round_value({"variant_rankings": variant_rankings, "calibration_candidates": calib_recs.get("candidate_scores", [])}), indent=2), encoding="utf-8")
        primary_per_run.round(6).to_csv(output_dir / "per_run_metrics.csv", index=False)
        primary_slips.round(6).to_csv(output_dir / "corpus_metrics.csv", index=False)
        pd.DataFrame(_round_value(drift_rows)).to_csv(output_dir / "drift_metrics.csv", index=False)
        with pd.ExcelWriter(output_dir / "regime_tables.xlsx") as writer:
            for name, rows in regime_tables.items():
                pd.DataFrame(rows).to_excel(writer, sheet_name=name[:31], index=False)
        (output_dir / "proposed_config_patch.yaml").write_text(yaml.safe_dump(proposed_cfg, sort_keys=False), encoding="utf-8")
        (output_dir / "proposed_calibration.json").write_text(json.dumps(_round_value(proposed_cal_json), indent=2), encoding="utf-8")
        (output_dir / "patch_plan.json").write_text(json.dumps(_round_value({
            "config_apply_now": [r for r in config_recs["recommendations"] if r.get("apply_now")],
            "calibration_apply_now": calib_recs.get("apply_now", False),
            "logic_recommendations": logic_recs["recommendations"],
        }), indent=2), encoding="utf-8")
        return output_dir
    finally:
        if primary_paths.extracted_tmp and primary_paths.extracted_tmp.exists():
            shutil.rmtree(primary_paths.extracted_tmp, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Atlas Full Reader v1.3: corpus telemetry reader, variant comparer, calibration suggester, patch writer, and hardened variant ranker.")
    p.add_argument("--corpus-input", type=Path, required=True, help="Primary corpus folder or zip with runs/")
    p.add_argument("--primary-label", type=str, default=None, help="Optional friendly name for the primary corpus")
    p.add_argument("--config-path", type=Path, required=True, help="Path to current config.yaml")
    p.add_argument("--calibration-json-path", type=Path, default=None, help="Optional calibration json path")
    p.add_argument("--calibration-py-path", type=Path, default=None, help="Optional calibration.py path")
    p.add_argument("--calibration-map-py-path", type=Path, default=None, help="Optional calibration_map.py path")
    p.add_argument("--output-root", type=Path, default=None, help="Atlas root for .atlas_audit output")
    p.add_argument("--comparison-corpus-input", type=Path, action="append", default=[], help="Optional comparison corpus path or zip. Repeat for multiple variants.")
    p.add_argument("--comparison-config-map-json", type=Path, default=None, help="Optional JSON mapping of comparison corpus path strings to config yaml paths.")
    p.add_argument("--variant-manifest-json", type=Path, default=None, help="Optional JSON manifest for named comparison variants.")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.comparison_config_map = _load_json(args.comparison_config_map_json) if args.comparison_config_map_json and args.comparison_config_map_json.exists() else None
    out = run_reader(args)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
