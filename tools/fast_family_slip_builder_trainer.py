#!/usr/bin/env python
"""Fast family-specific slip builder trainer.

This is intentionally not the old 12-hour exhaustive trainer. It reuses the
same live builders, scores compact policy variants against strict-fidelity
replay outputs, and reports Marketed/System/Windfall/DemonHunter separately.

Examples:
    py tools/fast_family_slip_builder_trainer.py --dates 20260510 20260520
    py tools/fast_family_slip_builder_trainer.py --families Marketed System
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from Atlas.core.marketed_slip_builder import build_marketed_slips
from Atlas.core.slip_quality_gate import apply_public_portfolio_exposure
from Atlas.runtime.slip_eval import _TruthIndex, _legs_from_recommended_row, _score_slip
from Atlas.stages.optimize.build_slips_today import run_build_slips


DEFAULT_PREFIX = "strict_fidelity_corpus_20260430_20260520_v2_"
FAMILY_ALIASES = {
    "market": "Marketed",
    "marketed": "Marketed",
    "system": "System",
    "windfall": "Windfall",
    "demon": "DemonHunter",
    "demonhunter": "DemonHunter",
}


@dataclass(frozen=True)
class ReplayInput:
    date_key: str
    replay_root: Path
    run_dir: Path
    scored_path: Path
    eval_path: Path
    strict_audit_path: Path
    strict_verdict: str


def _deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_update(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _date_from_replay_name(name: str, prefix: str) -> str | None:
    if not name.startswith(prefix):
        return None
    suffix = name[len(prefix) :]
    return suffix if re.fullmatch(r"\d{8}", suffix) else None


def _latest_file(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def discover_replays(
    *,
    telemetry_root: Path,
    prefix: str,
    dates: set[str] | None,
    include_20260430: bool,
    allow_non_strict: bool,
) -> list[ReplayInput]:
    replay_base = telemetry_root / "replay_runs"
    if not replay_base.is_dir():
        raise SystemExit(f"Missing replay telemetry dir: {replay_base}")

    inputs: list[ReplayInput] = []
    for replay_root in sorted(replay_base.iterdir()):
        if not replay_root.is_dir():
            continue
        date_key = _date_from_replay_name(replay_root.name, prefix)
        if not date_key:
            continue
        if date_key == "20260430" and not include_20260430:
            continue
        if dates and date_key not in dates:
            continue

        scored_path = _latest_file(list(replay_root.rglob("runs/*/scored_legs_deduped.csv")))
        if scored_path is None:
            raise SystemExit(f"{date_key}: missing scored_legs_deduped.csv under {replay_root}")
        run_dir = scored_path.parent
        eval_path = run_dir / "eval_legs.csv"
        strict_audit_path = run_dir / "strict_replay_fidelity_audit.json"
        if not eval_path.is_file():
            raise SystemExit(f"{date_key}: missing eval_legs.csv under {run_dir}")
        if not strict_audit_path.is_file():
            raise SystemExit(f"{date_key}: missing strict_replay_fidelity_audit.json under {run_dir}")

        strict_payload = json.loads(strict_audit_path.read_text(encoding="utf-8"))
        verdict = str(strict_payload.get("verdict") or strict_payload.get("status") or "").upper()
        if verdict != "PASS" and not allow_non_strict:
            raise SystemExit(f"{date_key}: strict fidelity audit is {verdict or 'UNKNOWN'}; refusing trainer run")

        inputs.append(
            ReplayInput(
                date_key=date_key,
                replay_root=replay_root,
                run_dir=run_dir,
                scored_path=scored_path,
                eval_path=eval_path,
                strict_audit_path=strict_audit_path,
                strict_verdict=verdict,
            )
        )

    if not inputs:
        raise SystemExit(f"No replay inputs found for prefix={prefix!r}")
    return inputs


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Config did not load as mapping: {path}")
    return data


def _load_day(replay: ReplayInput) -> tuple[pd.DataFrame, pd.DataFrame, _TruthIndex]:
    scored = pd.read_csv(replay.scored_path, low_memory=False)
    eval_df = pd.read_csv(replay.eval_path, low_memory=False)
    required = {"player", "stat", "line", "direction", "tier", "p_cal"}
    missing = sorted(required - set(scored.columns))
    if missing:
        raise SystemExit(f"{replay.date_key}: scored file missing required columns: {missing}")
    if "projection_id" not in scored.columns:
        scored = scored.copy()
        scored["projection_id"] = scored.index.astype(str)
    return scored, eval_df, _TruthIndex(eval_df)


def _variant_catalog() -> list[tuple[str, dict[str, Any]]]:
    """Small, auditable policy set. No broad grid explosion."""

    return [
        ("current", {}),
        (
            "sg_robust_plus",
            {
                "single_game_mode": {
                    "selection_surface": {"robustness_weight": 1.20},
                    "slip_rules": {
                        "max_role_shooter_overs": 1,
                        "max_fg3m_overs": 1,
                        "min_avg_robustness_by_legs": {"2": 0.00, "3": -0.01, "4": 0.00},
                    },
                },
                "public_slip_quality": {
                    "score": {
                        "single_game_robustness_w": 0.12,
                        "single_game_dependency_w": 0.13,
                    }
                },
            },
        ),
        (
            "public_quality_plus",
            {
                "public_slip_quality": {
                    "min_survival_score_by_legs": {"2": 0.56, "3": 0.57, "4": 0.56, "5": 0.55},
                    "single_game_min_survival_score_by_legs": {"2": 0.58, "3": 0.60},
                    "score": {
                        "avg_fragility_penalty_w": 0.40,
                        "pen_total_w": 0.35,
                        "single_game_robustness_w": 0.10,
                    },
                }
            },
        ),
        (
            "marketed_floor_plus",
            {
                "marketed_slips": {
                    "min_raw_thresholds": {"GOBLIN": 0.70, "STANDARD": 0.57, "DEMON": 0.52},
                    "single_game_caps_by_legs": {"2": 1, "3": 2, "4": 2, "5": 2},
                }
            },
        ),
        (
            "demonhunter_selective",
            {
                "demonhunter": {
                    "by_legs": {
                        "2": {"min_leg_prob": 0.58, "max_same_stat": 0},
                        "3": {"min_leg_prob": 0.58, "max_same_stat": 0},
                        "4": {"min_leg_prob": 0.58, "max_same_stat": 2},
                        "5": {"min_leg_prob": 0.58, "max_same_stat": 0},
                    }
                }
            },
        ),
    ]


def _selected_variants(max_variants: int | None) -> list[tuple[str, dict[str, Any]]]:
    variants = _variant_catalog()
    if max_variants is not None and max_variants > 0:
        variants = variants[: int(max_variants)]
    return variants


def _families(values: list[str]) -> set[str]:
    if not values:
        return {"Marketed", "System", "Windfall", "DemonHunter"}
    out: set[str] = set()
    for value in values:
        fam = FAMILY_ALIASES.get(str(value).strip().lower())
        if not fam:
            raise SystemExit(f"Unknown family {value!r}; use Marketed/System/Windfall/DemonHunter")
        out.add(fam)
    return out


def _frames_from_built(built: Any) -> dict[str, pd.DataFrame | None]:
    return {
        "System_2leg": built.sys2,
        "System_3leg": built.sys3,
        "System_4leg": built.sys4,
        "System_5leg": built.sys5,
        "Windfall_2leg": built.wind2,
        "Windfall_3leg": built.wind3,
        "Windfall_4leg": built.wind4,
        "Windfall_5leg": built.wind5,
        "DemonHunter": built.demonhunter,
    }


def _family_from_frame_name(name: str) -> str:
    if name.startswith("System"):
        return "System"
    if name.startswith("Windfall"):
        return "Windfall"
    if name.startswith("DemonHunter"):
        return "DemonHunter"
    return name


def _slip_label_from_frame_name(name: str, row: pd.Series) -> str:
    n_legs = int(float(row.get("n_legs", 0) or 0))
    if not n_legs:
        match = re.search(r"_(\d)leg", name)
        n_legs = int(match.group(1)) if match else 0
    return f"{n_legs}-leg" if n_legs else name


def _score_recommended_frame(
    *,
    frame: pd.DataFrame | None,
    family: str,
    output_name: str,
    truth: _TruthIndex,
    rows_per_output: int,
    scope: str,
    variant: str,
    date_key: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for slip_index, (_, row) in enumerate(frame.head(rows_per_output).reset_index(drop=True).iterrows(), start=1):
        legs = _legs_from_recommended_row(row)
        if not legs:
            continue
        n_legs = int(float(row.get("n_legs", len(legs)) or len(legs)))
        scored = _score_slip(
            family=family,
            slip_label=_slip_label_from_frame_name(output_name, row),
            n_legs=n_legs,
            source_file=output_name,
            slip_index=slip_index,
            row=row,
            legs=legs,
            truth=truth,
        )
        scored.update({"variant": variant, "date": date_key, "scope": scope, "output_name": output_name})
        rows.append(scored)
    return rows


def _score_marketed(
    *,
    slips: list[dict[str, Any]],
    truth: _TruthIndex,
    rows_per_output: int,
    scope: str,
    variant: str,
    date_key: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slip_index, slip in enumerate((slips or [])[:rows_per_output], start=1):
        legs = list(slip.get("legs") or [])
        if not legs:
            continue
        n_legs = int(float(slip.get("n_legs", len(legs)) or len(legs)))
        scored = _score_slip(
            family="Marketed",
            slip_label=str(slip.get("label") or f"{n_legs}-leg"),
            n_legs=n_legs,
            source_file="marketed_slips",
            slip_index=slip_index,
            row=pd.Series(slip),
            legs=legs,
            truth=truth,
        )
        scored.update({"variant": variant, "date": date_key, "scope": scope, "output_name": f"Marketed_{n_legs}leg"})
        rows.append(scored)
    return rows


def _score_outputs(
    *,
    frames: dict[str, pd.DataFrame | None],
    marketed_slips: list[dict[str, Any]],
    truth: _TruthIndex,
    families: set[str],
    rows_per_output: int,
    scope: str,
    variant: str,
    date_key: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if "Marketed" in families:
        rows.extend(
            _score_marketed(
                slips=marketed_slips,
                truth=truth,
                rows_per_output=rows_per_output,
                scope=scope,
                variant=variant,
                date_key=date_key,
            )
        )
    for output_name, frame in frames.items():
        family = _family_from_frame_name(output_name)
        if family not in families:
            continue
        rows.extend(
            _score_recommended_frame(
                frame=frame,
                family=family,
                output_name=output_name,
                truth=truth,
                rows_per_output=rows_per_output,
                scope=scope,
                variant=variant,
                date_key=date_key,
            )
        )
    return rows


def _build_for_day(scored: pd.DataFrame, cfg: dict[str, Any]) -> tuple[dict[str, pd.DataFrame | None], list[dict[str, Any]], dict[str, Any]]:
    optimizer_cfg = cfg.get("optimizer", {}) or {}
    top_n = int(optimizer_cfg.get("top_n_slips", 10) or 10)
    seed = int(optimizer_cfg.get("seed", 7) or 7)
    pricing_engine = str(cfg.get("pricing_engine", "power") or "power")
    slip_rank_cfg = cfg.get("slip_rank", {}) or {}
    primary_sort_mode = str(slip_rank_cfg.get("primary_mode", "ev") or "ev").strip().lower()
    if primary_sort_mode in {"win", "winprob", "hit_prob"}:
        primary_sort_mode = "hit"
    if primary_sort_mode not in {"ev", "hit", "hybrid"}:
        primary_sort_mode = "ev"

    built = run_build_slips(
        scored_for_optimizer=scored,
        top_n=top_n,
        seed=seed,
        pricing_engine=pricing_engine,
        cfg=cfg,
        sort_mode=primary_sort_mode,
    )
    frames = _frames_from_built(built)
    marketed_slips, _ = build_marketed_slips(scored, cfg) if cfg.get("marketed_slips", {}).get("enabled", False) else ([], None)
    portfolio = apply_public_portfolio_exposure(frames, marketed_slips, cfg, scored)
    return frames, marketed_slips, {
        "frames": portfolio.frames,
        "marketed_slips": portfolio.marketed_slips,
        "manifest": portfolio.manifest,
    }


def _csv_row(slip: dict[str, Any]) -> dict[str, Any]:
    legs = slip.get("legs") or []
    return {
        "variant": slip.get("variant"),
        "scope": slip.get("scope"),
        "date": slip.get("date"),
        "family": slip.get("family"),
        "output_name": slip.get("output_name"),
        "slip_label": slip.get("slip_label"),
        "n_legs": slip.get("n_legs"),
        "status": slip.get("status"),
        "all_hit": slip.get("all_hit"),
        "hit_count": slip.get("hit_count"),
        "truth_legs": slip.get("truth_legs"),
        "void_count": slip.get("void_count"),
        "hit_prob": slip.get("hit_prob"),
        "payout_mult": slip.get("payout_mult"),
        "ev_mult": slip.get("ev_mult"),
        "public_survival_score": slip.get("public_survival_score"),
        "public_quality_pass": slip.get("public_quality_pass"),
        "public_quality_reasons": slip.get("public_quality_reasons"),
        "leg_summary": " | ".join(str(leg.get("label", "")) for leg in legs),
    }


def _summaries(rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.DataFrame([_csv_row(row) for row in rows])
    if df.empty:
        return df, df

    df["is_win"] = df["status"].eq("win").astype(int)
    df["is_loss"] = df["status"].eq("loss").astype(int)
    df["is_void"] = df["status"].eq("void").astype(int)
    df["graded"] = df["is_win"] + df["is_loss"]
    df["n_legs_num"] = pd.to_numeric(df["n_legs"], errors="coerce").fillna(0)
    df["hit_count_num"] = pd.to_numeric(df["hit_count"], errors="coerce").fillna(0)
    df["weighted_points"] = df["is_win"] * df["n_legs_num"] * 10.0 + df["hit_count_num"]
    df["weighted_possible"] = df["graded"] * df["n_legs_num"] * 10.0 + df["n_legs_num"]

    grouped = (
        df.groupby(["variant", "scope", "family", "n_legs"], dropna=False)
        .agg(
            slips=("status", "size"),
            graded=("graded", "sum"),
            wins=("is_win", "sum"),
            losses=("is_loss", "sum"),
            voids=("is_void", "sum"),
            leg_hits=("hit_count_num", "sum"),
            truth_legs=("truth_legs", "sum"),
            weighted_points=("weighted_points", "sum"),
            weighted_possible=("weighted_possible", "sum"),
            avg_hit_prob=("hit_prob", "mean"),
        )
        .reset_index()
    )
    grouped["win_rate"] = grouped["wins"] / grouped["graded"].replace({0: pd.NA})
    grouped["leg_hit_rate"] = grouped["leg_hits"] / grouped["truth_legs"].replace({0: pd.NA})
    grouped["weighted_score"] = grouped["weighted_points"] / grouped["weighted_possible"].replace({0: pd.NA})

    variant_summary = (
        df.groupby(["variant", "scope"], dropna=False)
        .agg(
            slips=("status", "size"),
            graded=("graded", "sum"),
            wins=("is_win", "sum"),
            losses=("is_loss", "sum"),
            voids=("is_void", "sum"),
            leg_hits=("hit_count_num", "sum"),
            truth_legs=("truth_legs", "sum"),
            weighted_points=("weighted_points", "sum"),
            weighted_possible=("weighted_possible", "sum"),
        )
        .reset_index()
    )
    variant_summary["win_rate"] = variant_summary["wins"] / variant_summary["graded"].replace({0: pd.NA})
    variant_summary["leg_hit_rate"] = variant_summary["leg_hits"] / variant_summary["truth_legs"].replace({0: pd.NA})
    variant_summary["weighted_score"] = variant_summary["weighted_points"] / variant_summary["weighted_possible"].replace({0: pd.NA})
    return grouped, variant_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--dates", nargs="*", default=None, help="YYYYMMDD replay dates to include.")
    parser.add_argument("--families", nargs="*", default=["Marketed", "System", "Windfall", "DemonHunter"])
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--rows-per-output", type=int, default=1)
    parser.add_argument("--max-variants", type=int, default=0, help="0 means all compact variants.")
    parser.add_argument("--include-20260430", action="store_true")
    parser.add_argument("--allow-non-strict", action="store_true")
    args = parser.parse_args(argv)

    dates = {str(d) for d in args.dates} if args.dates else None
    families = _families(args.families)
    config = _load_config(Path(args.config))
    variants = _selected_variants(args.max_variants if args.max_variants > 0 else None)
    replays = discover_replays(
        telemetry_root=ROOT / "data" / "telemetry",
        prefix=args.prefix,
        dates=dates,
        include_20260430=bool(args.include_20260430),
        allow_non_strict=bool(args.allow_non_strict),
    )

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "model" / "builder_trainers" / f"fast_family_builder_{_now_tag()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[FAST_BUILDER] strict preflight passed", flush=True)
    print(f"[FAST_BUILDER] dates={len(replays)} variants={len(variants)} families={sorted(families)}", flush=True)
    print(f"[FAST_BUILDER] out_dir={out_dir}", flush=True)

    rows: list[dict[str, Any]] = []
    preflight_rows: list[dict[str, Any]] = []
    for replay in replays:
        scored, eval_df, truth = _load_day(replay)
        preflight_rows.append(
            {
                "date": replay.date_key,
                "run_dir": str(replay.run_dir),
                "scored_rows": int(len(scored)),
                "eval_rows": int(len(eval_df)),
                "strict_verdict": replay.strict_verdict,
                "scored_path": str(replay.scored_path),
                "eval_path": str(replay.eval_path),
            }
        )

    pd.DataFrame(preflight_rows).to_csv(out_dir / "fast_builder_preflight.csv", index=False)

    for v_idx, (variant_name, patch) in enumerate(variants, start=1):
        cfg = _deep_update(config, patch)
        print(f"[FAST_BUILDER] variant {v_idx}/{len(variants)}: {variant_name}", flush=True)
        for r_idx, replay in enumerate(replays, start=1):
            scored, _, truth = _load_day(replay)
            frames, marketed_slips, portfolio = _build_for_day(scored, cfg)
            rows.extend(
                _score_outputs(
                    frames=frames,
                    marketed_slips=marketed_slips,
                    truth=truth,
                    families=families,
                    rows_per_output=max(1, int(args.rows_per_output)),
                    scope="family_raw",
                    variant=variant_name,
                    date_key=replay.date_key,
                )
            )
            rows.extend(
                _score_outputs(
                    frames=portfolio["frames"],
                    marketed_slips=portfolio["marketed_slips"],
                    truth=truth,
                    families=families,
                    rows_per_output=max(1, int(args.rows_per_output)),
                    scope="portfolio",
                    variant=variant_name,
                    date_key=replay.date_key,
                )
            )
            if r_idx % 5 == 0 or r_idx == len(replays):
                print(f"  - {variant_name}: {r_idx}/{len(replays)} dates", flush=True)

    slip_rows = pd.DataFrame([_csv_row(row) for row in rows])
    family_summary, variant_summary = _summaries(rows)

    slip_rows.to_csv(out_dir / "fast_builder_slip_rows.csv", index=False)
    family_summary.to_csv(out_dir / "fast_builder_family_summary.csv", index=False)
    variant_summary.to_csv(out_dir / "fast_builder_variant_summary.csv", index=False)

    best = {}
    if not variant_summary.empty:
        portfolio_rows = variant_summary[variant_summary["scope"].eq("portfolio")].copy()
        portfolio_rows = portfolio_rows.sort_values(["weighted_score", "win_rate"], ascending=[False, False])
        if not portfolio_rows.empty:
            best = portfolio_rows.iloc[0].to_dict()

    payload = {
        "source": "fast_family_slip_builder_trainer",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "prefix": args.prefix,
        "dates": [r.date_key for r in replays],
        "families": sorted(families),
        "variants": [name for name, _ in variants],
        "rows_per_output": int(args.rows_per_output),
        "best_portfolio_variant": best,
        "outputs": {
            "preflight": str((out_dir / "fast_builder_preflight.csv").resolve()),
            "slip_rows": str((out_dir / "fast_builder_slip_rows.csv").resolve()),
            "family_summary": str((out_dir / "fast_builder_family_summary.csv").resolve()),
            "variant_summary": str((out_dir / "fast_builder_variant_summary.csv").resolve()),
        },
    }
    (out_dir / "fast_builder_summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("[FAST_BUILDER] complete", flush=True)
    print(f"[FAST_BUILDER] best_portfolio_variant={best.get('variant')} weighted_score={best.get('weighted_score')}", flush=True)
    print(f"[FAST_BUILDER] summary={out_dir / 'fast_builder_summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
