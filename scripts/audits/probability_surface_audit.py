"""Probability surface audit for NBA live/replay runs.

This is a run-level contract check for probability-affecting columns. It is
designed to catch dead context, silent defaults, bad lineage, and market-prior
precedence drift before a run is used for replay corpus or LODO training.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

PROBABILITY_CHAIN = ["p", "p_role", "p_adj", "p_for_cal", "p_catboost", "p_cal", "p_cal_marketed"]
GAME_CONTEXT = ["spread_ok", "game_spread", "game_total", "game_total_norm", "q_blowout"]
MARKET_CONTEXT = [
    "external_prior_n",
    "external_prior_sources",
    "external_prior_cap_applied",
    "external_prior_delta_p",
    "external_prior_probability_applied",
    "external_prior_market_prob",
    "external_prior_market_divergence",
    "external_prior_exact_market",
]
ROLE_CONTEXT = [
    "role_ctx_mult",
    "role_ctx_rate_mult",
    "role_metrics_mult",
    "role_ctx_outs_used",
    "role_ctx_bump",
    "zero_dnp_mult",
]
CAT_CONTEXT = [
    "catboost_feature_source",
    "catboost_feature_count",
    "catboost_defaulted_features",
    "catboost_scale_spread_ok_rate",
    "catboost_scale_game_total_nonzero_rate",
    "catboost_scale_q_blowout_unique",
]
SINGLE_GAME_CONTEXT = [
    "single_game_robustness_score",
    "single_game_script_dependency_score",
    "single_game_slate_severity_score",
    "single_game_slate_severity_label",
]

# Sportsbooks generally do not publish official player-prop markets for these
# PP stats. Missing exact market probability for these rows is expected, so
# audits should report them separately instead of treating them as DK/BP misses.
EXPECTED_UNMARKETED_EXACT_STATS = {"FTA"}


def _latest_run_dir() -> Path:
    runs = ROOT / "data" / "output" / "runs"
    candidates = [p for p in runs.iterdir() if p.is_dir()] if runs.exists() else []
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {runs}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _num(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.astype("float64")


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    values = df[col]
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    text = values.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def _describe_numeric(df: pd.DataFrame, col: str) -> dict[str, Any]:
    if col not in df.columns:
        return {"status": "missing"}
    values = _num(df, col)
    finite = values.replace([np.inf, -np.inf], np.nan)
    non_null = finite.dropna()
    filled = finite.fillna(0.0)
    unique = int(non_null.nunique(dropna=True))
    nonzero_rate = float((filled.abs() > 1e-12).mean()) if len(filled) else 0.0
    if non_null.empty:
        status = "all_null"
    elif nonzero_rate == 0.0:
        status = "constant_zero"
    elif unique <= 1:
        status = "constant_nonzero"
    else:
        status = "active"
    return {
        "status": status,
        "rows": int(len(values)),
        "null_rows": int(values.isna().sum()),
        "nan_rate": float(values.isna().mean()) if len(values) else 1.0,
        "unique_count": unique,
        "nonzero_rate": nonzero_rate,
        "mean": float(non_null.mean()) if not non_null.empty else None,
        "min": float(non_null.min()) if not non_null.empty else None,
        "max": float(non_null.max()) if not non_null.empty else None,
        "p10": float(non_null.quantile(0.10)) if not non_null.empty else None,
        "p50": float(non_null.quantile(0.50)) if not non_null.empty else None,
        "p90": float(non_null.quantile(0.90)) if not non_null.empty else None,
    }


def _describe_text(df: pd.DataFrame, col: str) -> dict[str, Any]:
    if col not in df.columns:
        return {"status": "missing"}
    values = df[col].fillna("").astype(str)
    return {
        "status": "active" if values.nunique(dropna=False) > 1 else "constant",
        "rows": int(len(values)),
        "unique_count": int(values.nunique(dropna=False)),
        "top_values": {str(k): int(v) for k, v in values.value_counts(dropna=False).head(12).to_dict().items()},
    }


def _column_summary(df: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in columns:
        if col in {"external_prior_sources", "catboost_feature_source", "catboost_defaulted_features", "single_game_slate_severity_label"}:
            out[col] = _describe_text(df, col)
        else:
            out[col] = _describe_numeric(df, col)
    return out


def _market_context_summary(df: pd.DataFrame) -> dict[str, Any]:
    out = _column_summary(df, MARKET_CONTEXT)
    if df.empty:
        out["coverage"] = {
            "rows": 0,
            "market_eligible_rows": 0,
            "expected_unmarketed_rows": 0,
            "expected_unmarketed_stats": {},
        }
        return out

    stat = (
        df["stat"].fillna("").astype(str).str.strip().str.upper()
        if "stat" in df.columns
        else pd.Series("", index=df.index)
    )
    expected_unmarketed = stat.isin(EXPECTED_UNMARKETED_EXACT_STATS)
    eligible = ~expected_unmarketed
    prior_n = _num(df, "external_prior_n", 0.0).fillna(0.0)
    exact = _bool(df, "external_prior_exact_market")
    rows = int(len(df))
    eligible_rows = int(eligible.sum())
    expected_rows = int(expected_unmarketed.sum())
    stat_counts = {
        str(k): int(v)
        for k, v in stat[expected_unmarketed].value_counts(dropna=False).to_dict().items()
    }
    out["coverage"] = {
        "rows": rows,
        "external_prior_share_all": float((prior_n > 0).mean()) if rows else 0.0,
        "exact_market_share_all": float(exact.mean()) if rows else 0.0,
        "market_eligible_rows": eligible_rows,
        "expected_unmarketed_rows": expected_rows,
        "expected_unmarketed_stats": stat_counts,
        "external_prior_share_market_eligible": float((prior_n[eligible] > 0).mean()) if eligible_rows else 0.0,
        "exact_market_share_market_eligible": float(exact[eligible].mean()) if eligible_rows else 0.0,
        "exact_market_missing_market_eligible_rows": int((eligible & ~exact).sum()),
        "note": "Expected-unmarketed stats are excluded from market-eligible exact coverage.",
    }
    return out


def _source_manifest(run_dir: Path) -> dict[str, Any]:
    candidates = [
        ROOT / "data" / "output" / "runs_manifest" / run_dir.name / "source_context_manifest.json",
        run_dir.parent.parent / "runs_manifest" / run_dir.name / "source_context_manifest.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"path": str(path), "read_error": str(exc)}
            data["path"] = str(path)
            return data
    return {"path": None, "missing": True}


def _probability_failures(scored: pd.DataFrame) -> list[str]:
    failures: list[str] = []
    for col in ["p", "p_role", "p_adj", "p_for_cal", "p_catboost", "p_cal"]:
        if col not in scored.columns:
            failures.append(f"missing_probability_column:{col}")
            continue
        vals = _num(scored, col)
        if vals.isna().any():
            failures.append(f"null_probability_column:{col}:{int(vals.isna().sum())}")
        bad = vals[(vals < -1e-9) | (vals > 1 + 1e-9)]
        if len(bad):
            failures.append(f"probability_out_of_range:{col}:{len(bad)}")
    return failures


def _game_context_failures(scored: pd.DataFrame) -> list[str]:
    failures: list[str] = []
    if scored.empty:
        return ["empty_scored_frame"]
    spread_ok = _bool(scored, "spread_ok")
    total = _num(scored, "game_total_norm", 0.0).fillna(0.0)
    q = _num(scored, "q_blowout", np.nan)
    if float(spread_ok.mean()) < 0.99:
        failures.append(f"spread_context_incomplete:{float(spread_ok.mean()):.3f}")
    if float((total.abs() > 1e-12).mean()) < 0.99:
        failures.append(f"game_total_context_dead:{float((total.abs() > 1e-12).mean()):.3f}")
    if q.dropna().empty:
        failures.append("q_blowout_missing")
    elif int(q.nunique(dropna=True)) <= 1 and (float(spread_ok.mean()) < 0.99 or float((total.abs() > 1e-12).mean()) < 0.99):
        failures.append("q_blowout_constant_because_game_context_dead")
    return failures


def _market_failures(scored: pd.DataFrame) -> list[str]:
    failures: list[str] = []
    prior_n = _num(scored, "external_prior_n", 0.0).fillna(0.0)
    applied = _bool(scored, "external_prior_probability_applied")
    delta = _num(scored, "external_prior_delta_p", 0.0).fillna(0.0)
    cap = _num(scored, "external_prior_cap_applied", 0.0).fillna(0.0).abs()
    exact = _bool(scored, "external_prior_exact_market")
    sources = scored.get("external_prior_sources", pd.Series("", index=scored.index)).fillna("").astype(str).str.lower()
    if (prior_n > 0).any() and "external_prior_market_prob" not in scored.columns:
        failures.append("market_prior_rows_without_market_prob_column")
    cap_bad = delta.abs() > (cap + 1e-9)
    if cap_bad.any():
        failures.append(f"external_prior_delta_exceeds_cap:{int(cap_bad.sum())}")
    flag_bad = applied.ne(delta.abs() > 1e-12)
    if flag_bad.any():
        failures.append(f"external_prior_applied_flag_delta_mismatch:{int(flag_bad.sum())}")
    anchor_on_exact = exact & sources.str.contains("anchor", regex=False, na=False)
    if anchor_on_exact.any():
        failures.append(f"exact_market_sources_include_anchor:{int(anchor_on_exact.sum())}")
    return failures


def _cat_failures(scored: pd.DataFrame) -> list[str]:
    failures: list[str] = []
    if "catboost_defaulted_features" not in scored.columns:
        failures.append("missing_catboost_defaulted_features_column")
    else:
        defaulted = sorted(set(x for x in scored["catboost_defaulted_features"].fillna("").astype(str).tolist() if x))
        if defaulted:
            failures.append("catboost_defaulted_features:" + ",".join(defaulted))
    if "catboost_feature_count" in scored.columns:
        counts = sorted(set(pd.to_numeric(scored["catboost_feature_count"], errors="coerce").dropna().astype(int).tolist()))
        if len(counts) != 1:
            failures.append(f"catboost_feature_count_not_constant:{counts}")
    return failures


def audit_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    scored = _read_csv(run_dir / "scored_legs_deduped.csv")
    scored_full = _read_csv(run_dir / "scored_legs.csv")
    frame = scored if not scored.empty else scored_full

    failures: list[str] = []
    warnings: list[str] = []
    failures.extend(_probability_failures(frame))
    failures.extend(_game_context_failures(frame))
    failures.extend(_market_failures(frame))
    failures.extend(_cat_failures(frame))

    single_game_active = bool(_bool(frame, "single_game_slate").any()) if "single_game_slate" in frame.columns else False
    if "single_game_robustness_score" in frame.columns:
        robust = _num(frame, "single_game_robustness_score", np.nan)
        if single_game_active and robust.dropna().nunique() <= 3 and len(frame) > 100:
            warnings.append("single_game_robustness_score_low_separation")
    else:
        if single_game_active:
            warnings.append("single_game_robustness_score_missing")

    manifest = _source_manifest(run_dir)
    if manifest.get("missing"):
        failures.append("missing_source_context_manifest")

    payload = {
        "schema": "nba_probability_surface_audit_v1",
        "verdict": "FAIL" if failures else ("WARN" if warnings else "PASS"),
        "failures": failures,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "rows": {
            "scored_legs": int(len(scored_full)),
            "scored_legs_deduped": int(len(scored)),
        },
        "probability_chain": _column_summary(frame, PROBABILITY_CHAIN),
        "game_context": _column_summary(frame, GAME_CONTEXT),
        "market_context": _market_context_summary(frame),
        "role_context": _column_summary(frame, ROLE_CONTEXT),
        "cat_context": _column_summary(frame, CAT_CONTEXT),
        "single_game_context": _column_summary(frame, SINGLE_GAME_CONTEXT),
        "source_context_manifest": manifest,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit probability-affecting NBA scored-leg columns.")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    result = audit_run(run_dir)
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0 if result["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
