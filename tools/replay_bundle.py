from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from Atlas.runtime.replay_eval import backfill_latest_replay_eval_legs


ROLE_METRICS_FAMILIES: dict[str, list[str]] = {
    "scoring": [
        "role_metrics_usg_pct",
        "role_metrics_ts_pct",
        "role_metrics_sq",
        "role_metrics_ftr",
    ],
    "rebound": [
        "role_metrics_trb_pct",
        "role_metrics_orb_pct",
        "role_metrics_drb_pct",
    ],
    "assist": [
        "role_metrics_ast_pct",
        "role_metrics_touches",
        "role_metrics_ast_usg",
        "role_metrics_bc",
        "role_metrics_load",
        "role_metrics_pr",
    ],
    "threes": [
        "role_metrics_three_par",
        "role_metrics_sq",
        "role_metrics_ts_pct",
    ],
    "impact_priors": [
        "role_metrics_darko",
        "role_metrics_vorp",
        "role_metrics_cpm",
        "role_metrics_drip_total",
    ],
}

ROLE_METRICS_STAT_FAMILY_MAP: dict[str, str] = {
    "PTS": "scoring",
    "PA": "scoring",
    "PR": "scoring",
    "PRA": "scoring",
    "REB": "rebound",
    "RA": "rebound",
    "AST": "assist",
    "FG3M": "threes",
    "3PM": "threes",
    "THREES": "threes",
}


def _role_metrics_payload_summary(df: pd.DataFrame) -> dict[str, object]:
    rows = int(len(df))
    snapshot_rows = int(df.get("role_metrics_snapshot_id", pd.Series(dtype=object)).fillna("").astype(str).str.len().gt(0).sum()) if rows else 0
    role_ctx_on_rows = int(pd.to_numeric(df.get("role_ctx_outs_used", pd.Series(dtype=float)), errors="coerce").fillna(0).gt(0).sum()) if rows else 0

    families: dict[str, object] = {}
    warnings: list[str] = []
    for family, columns in ROLE_METRICS_FAMILIES.items():
        available = [col for col in columns if col in df.columns]
        per_column: list[dict[str, object]] = []
        populated_rows_any = pd.Series(False, index=df.index) if rows else pd.Series(dtype=bool)
        for col in available:
            series = pd.to_numeric(df[col], errors="coerce")
            populated = int(series.notna().sum())
            populated_rows_any = populated_rows_any | series.notna()
            per_column.append({
                "column": col,
                "populated_rows": populated,
                "populated_share": round(float(populated / rows), 6) if rows else 0.0,
            })
        populated_any = int(populated_rows_any.sum()) if rows and available else 0
        family_summary = {
            "available_columns": available,
            "missing_columns": [col for col in columns if col not in available],
            "populated_rows_any": populated_any,
            "populated_share_any": round(float(populated_any / rows), 6) if rows else 0.0,
            "per_column": per_column,
        }
        families[family] = family_summary
        if family == "assist" and populated_any == 0:
            warnings.append("assist_family_metrics_missing_or_null")
        if family == "rebound" and populated_any == 0:
            warnings.append("rebound_family_metrics_missing_or_null")
        if family == "scoring" and populated_any == 0:
            warnings.append("scoring_family_metrics_missing_or_null")

    assist_contract_required = [
        "role_metrics_ast_pct",
        "role_metrics_touches",
        "role_metrics_ast_usg",
        "role_metrics_bc",
        "role_metrics_load",
        "role_metrics_pr",
    ]
    assist_present = [col for col in assist_contract_required if col in df.columns]
    assist_populated = [
        col
        for col in assist_present
        if pd.to_numeric(df[col], errors="coerce").notna().any()
    ]

    settled = df[pd.to_numeric(df.get("hit", pd.Series(dtype=float)), errors="coerce").isin([0, 1])].copy()
    family_report: list[dict[str, object]] = []
    if not settled.empty and "stat" in settled.columns:
        settled["_family"] = settled["stat"].astype(str).str.upper().map(lambda x: ROLE_METRICS_STAT_FAMILY_MAP.get(str(x), "other"))
        for family_name, grp in settled.groupby("_family", observed=False):
            if grp.empty:
                continue
            family_report.append({
                "family": family_name,
                "rows": int(len(grp)),
                "mean_brier_p_adj": round(float(pd.to_numeric(grp.get("brier_p_adj", pd.Series(dtype=float)), errors="coerce").mean()), 6),
                "mean_usage_metric_mult": round(float(pd.to_numeric(grp.get("usage_metric_mult", pd.Series(dtype=float)), errors="coerce").fillna(1.0).mean()), 6),
                "mean_usage_scoring_mult": round(float(pd.to_numeric(grp.get("usage_scoring_mult", pd.Series(dtype=float)), errors="coerce").fillna(1.0).mean()), 6),
                "mean_usage_assist_mult": round(float(pd.to_numeric(grp.get("usage_assist_mult", pd.Series(dtype=float)), errors="coerce").fillna(1.0).mean()), 6),
                "mean_usage_rebound_mult": round(float(pd.to_numeric(grp.get("usage_rebound_mult", pd.Series(dtype=float)), errors="coerce").fillna(1.0).mean()), 6),
                "mean_usage_threes_mult": round(float(pd.to_numeric(grp.get("usage_threes_mult", pd.Series(dtype=float)), errors="coerce").fillna(1.0).mean()), 6),
            })
        def _sort_key(row: dict[str, object]) -> tuple[float, str]:
            b = float(row.get("mean_brier_p_adj") or 0.0)  # type: ignore[arg-type]
            return (-b, str(row.get("family") or ""))
        family_report.sort(key=_sort_key)

    warnings = sorted(set(warnings))
    return {
        "rows": rows,
        "snapshot_rows": snapshot_rows,
        "snapshot_share": round(float(snapshot_rows / rows), 6) if rows else 0.0,
        "role_ctx_on_rows": role_ctx_on_rows,
        "role_ctx_on_share": round(float(role_ctx_on_rows / rows), 6) if rows else 0.0,
        "active_tuning_families": ["scoring", "rebound"],
        "diagnostic_only_families": ["assist", "threes", "impact_priors"],
        "assist_payload_contract": {
            "required_columns": assist_contract_required,
            "present_columns": assist_present,
            "populated_columns": assist_populated,
            "missing_columns": [col for col in assist_contract_required if col not in assist_present],
            "ready": len(assist_populated) == len(assist_contract_required),
        },
        "families": families,
        "family_contribution_report": family_report,
        "warnings": warnings,
    }


def _write_role_metrics_payload_summary(eval_path: Path) -> Path | None:
    if not eval_path.exists() or not eval_path.is_file():
        return None
    try:
        df = pd.read_csv(eval_path)
    except Exception:
        return None

    summary = _role_metrics_payload_summary(df)
    summary_path = eval_path.parent / "role_metrics_payload_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md_lines = ["# Role Metrics Payload Summary", ""]
    md_lines.append(f"- Rows: `{summary['rows']}`")
    md_lines.append(f"- Snapshot rows: `{summary['snapshot_rows']}` ({summary['snapshot_share']})")
    md_lines.append(f"- Role-context active rows: `{summary['role_ctx_on_rows']}` ({summary['role_ctx_on_share']})")
    _active_families: list[str] = summary.get("active_tuning_families") or []  # type: ignore[assignment]
    md_lines.append(f"- Active tuning families: `{', '.join(_active_families)}`")
    _warnings: list[str] = summary.get("warnings") or []  # type: ignore[assignment]
    if _warnings:
        md_lines.append(f"- Warnings: `{', '.join(_warnings)}`")
    assist_contract: dict[str, object] = summary.get("assist_payload_contract") or {}  # type: ignore[assignment]
    if assist_contract:
        md_lines.append(f"- Assist payload ready: `{assist_contract.get('ready')}`")
        missing: list[str] = assist_contract.get("missing_columns") or []  # type: ignore[assignment]
        if missing:
            md_lines.append(f"- Assist payload missing: `{', '.join(missing)}`")
    md_lines.append("")
    md_lines.append("## Family Coverage")
    _families: dict[str, dict[str, object]] = summary.get("families") or {}  # type: ignore[assignment]
    for family, family_summary in _families.items():
        md_lines.append(f"- `{family}` populated_rows_any=`{family_summary.get('populated_rows_any')}` share=`{family_summary.get('populated_share_any')}`")
        missing: list[str] = family_summary.get("missing_columns") or []  # type: ignore[assignment]
        if missing:
            md_lines.append(f"  - missing: `{', '.join(missing)}`")
    _family_report: list[dict[str, object]] = summary.get("family_contribution_report") or []  # type: ignore[assignment]
    if _family_report:
        md_lines.append("")
        md_lines.append("## Family Contribution Report")
        for row in _family_report:
            md_lines.append(
                f"- `{row.get('family')}` rows=`{row.get('rows')}` brier=`{row.get('mean_brier_p_adj')}` metric_mult=`{row.get('mean_usage_metric_mult')}` scoring=`{row.get('mean_usage_scoring_mult')}` assist=`{row.get('mean_usage_assist_mult')}` rebound=`{row.get('mean_usage_rebound_mult')}` threes=`{row.get('mean_usage_threes_mult')}`"
            )
    (eval_path.parent / "role_metrics_payload_summary.md").write_text("\n".join(md_lines), encoding="utf-8")
    return summary_path


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return start.resolve()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _resolve_bundle_path(repo_root: Path, bundle: str) -> Path:
    """Resolve a bundle zip path from either a full path, a filename, or a run-id."""
    p = Path(bundle).expanduser()
    if p.suffix.lower() == ".zip" and p.is_file():
        return p.resolve()

    bundles_dir = repo_root / "data" / "bundles"

    # Accept 'atlas_bundle_<id>.zip'
    if bundle.lower().endswith(".zip"):
        cand = bundles_dir / bundle
        if cand.is_file():
            return cand.resolve()

    # Accept bare run id like '20260219_062634'
    cand = bundles_dir / f"atlas_bundle_{bundle}.zip"
    if cand.is_file():
        return cand.resolve()

    raise FileNotFoundError(f"Could not find bundle zip for: {bundle} (looked in {bundles_dir})")


def _extract_bundle(bundle_zip: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_zip, "r") as z:
        z.extractall(dest_dir)


def _find_unique_file(root: Path, filename: str, *, parent_name: str | None = None) -> Path | None:
    matches = [p for p in root.rglob(filename) if p.is_file()]
    if parent_name is not None:
        matches = [p for p in matches if p.parent.name == parent_name]
    if len(matches) == 1:
        return matches[0].resolve()
    return None


def _find_dashboard_snapshot_dir(data_dir: Path) -> Path | None:
    candidates: list[Path] = []
    runs_root = data_dir / "output" / "runs"
    if runs_root.is_dir():
        for run_dir in runs_root.iterdir():
            dash = run_dir / "dashboard"
            if (
                dash.is_dir()
                and (dash / "injury_invalidations_latest.json").is_file()
                and (dash / "status_latest.json").is_file()
                and (dash / "normalized_latest.json").is_file()
            ):
                candidates.append(dash)

    if candidates:
        candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
        return candidates[0].resolve()
    return None


def _find_bundle_role_metrics_artifacts(data_dir: Path) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}

    dashboard_candidates: list[Path] = []
    top_dashboard = data_dir / "output" / "dashboard"
    if top_dashboard.is_dir():
        dashboard_candidates.append(top_dashboard)

    runs_root = data_dir / "output" / "runs"
    if runs_root.is_dir():
        for run_dir in runs_root.iterdir():
            dash = run_dir / "dashboard"
            if dash.is_dir():
                dashboard_candidates.append(dash)

    for dash in dashboard_candidates:
        json_path = dash / "role_metrics_latest.json"
        html_path = dash / "role_metrics_latest.html"
        manifest_path = dash / "role_metrics_snapshot_manifest.json"
        if json_path.is_file():
            artifacts["ATLAS_ROLE_METRICS_PATH"] = json_path.resolve()
        if html_path.is_file():
            artifacts["ATLAS_ROLE_METRICS_HTML_PATH"] = html_path.resolve()
        if manifest_path.is_file():
            artifacts["ATLAS_ROLE_METRICS_MANIFEST_PATH"] = manifest_path.resolve()
        if artifacts.get("ATLAS_ROLE_METRICS_PATH"):
            return artifacts

    return artifacts


def _role_metrics_candidate_metadata(json_path: Path, manifest_path: Path | None = None) -> tuple[datetime | None, str | None]:
    candidates: list[str] = []
    game_dates: list[str] = []
    if manifest_path is not None and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key in ("fetched_at", "generated_at", "generated_at_utc"):
                value = str(manifest.get(key, "")).strip()
                if value:
                    candidates.append(value)
            game_date = str(manifest.get("game_date", "")).strip()
            if game_date:
                game_dates.append(game_date)
        except Exception:
            pass

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        for key in ("fetched_at", "generated_at", "generated_at_utc"):
            value = str(payload.get(key, "")).strip()
            if value:
                candidates.append(value)
        game_date = str(payload.get("game_date", "")).strip()
        if game_date:
            game_dates.append(game_date)
    except Exception:
        pass

    for value in candidates:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc), (game_dates[0] if game_dates else None)
        except Exception:
            continue

    try:
        return datetime.fromtimestamp(json_path.stat().st_mtime, tz=timezone.utc), (game_dates[0] if game_dates else None)
    except OSError:
        return None, (game_dates[0] if game_dates else None)


def _score_candidate_datetime(candidate_dt: datetime | None, candidate_game_date: str | None, target_utc: datetime | None) -> tuple[int, int, float, int]:
    if candidate_game_date and target_utc is not None:
        try:
            target_date = target_utc.date()
            game_date = datetime.strptime(candidate_game_date, "%Y-%m-%d").date()
            day_delta = (game_date - target_date).days
            game_date_penalty = 0
            game_date_future_penalty = 1 if day_delta > 0 else 0
            game_date_distance = abs(day_delta)
        except Exception:
            game_date_penalty = 1
            game_date_distance = 10**6
            game_date_future_penalty = 1
    else:
        game_date_penalty = 1
        game_date_distance = 10**6
        game_date_future_penalty = 1

    if candidate_dt is None or target_utc is None:
        return (game_date_penalty, game_date_distance, game_date_future_penalty, 1)
    delta_seconds = (candidate_dt - target_utc).total_seconds()
    future_penalty = 1 if delta_seconds > 0 else 0
    return (game_date_penalty, game_date_distance, abs(delta_seconds), future_penalty)


def _find_best_role_metrics_artifacts(repo_root: Path, target_utc: datetime | None) -> dict[str, Path]:
    candidates: list[tuple[tuple[int, int, float, int, int], dict[str, Path]]] = []

    def add_candidate(priority: int, json_path: Path, html_path: Path | None = None, manifest_path: Path | None = None) -> None:
        if not json_path.is_file():
            return
        candidate_dt, candidate_game_date = _role_metrics_candidate_metadata(json_path, manifest_path)
        score = (*_score_candidate_datetime(candidate_dt, candidate_game_date, target_utc), priority)
        artifacts: dict[str, Path] = {
            "ATLAS_ROLE_METRICS_PATH": json_path.resolve(),
        }
        if html_path is not None and html_path.is_file():
            artifacts["ATLAS_ROLE_METRICS_HTML_PATH"] = html_path.resolve()
        if manifest_path is not None and manifest_path.is_file():
            artifacts["ATLAS_ROLE_METRICS_MANIFEST_PATH"] = manifest_path.resolve()
        candidates.append((score, artifacts))

    if target_utc is not None:
        archives_root = repo_root / "data" / "archives" / "iael"
        if archives_root.is_dir():
            for json_path in archives_root.rglob("role_metrics_latest.json"):
                folder = json_path.parent
                add_candidate(
                    0,
                    json_path,
                    folder / "role_metrics_latest.html",
                    folder / "role_metrics_snapshot_manifest.json",
                )

    dashboard_dir = repo_root / "data" / "output" / "dashboard"
    add_candidate(
        1,
        dashboard_dir / "role_metrics_latest.json",
        dashboard_dir / "role_metrics_latest.html",
        dashboard_dir / "role_metrics_snapshot_manifest.json",
    )

    snapshots_root = repo_root / "data" / "output" / "role_metrics" / "snapshots"
    if snapshots_root.is_dir():
        for json_path in snapshots_root.rglob("*.json"):
            if json_path.name.endswith("manifest.json"):
                continue
            html_path = json_path.with_suffix(".html")
            add_candidate(2, json_path, html_path, None)

    replay_root = repo_root / "data" / "telemetry" / "replay_runs"
    if replay_root.is_dir():
        for json_path in replay_root.rglob("role_metrics_latest.json"):
            folder = json_path.parent
            add_candidate(
                3,
                json_path,
                folder / "role_metrics_latest.html",
                folder / "role_metrics_snapshot_manifest.json",
            )

    if not candidates:
        return {}

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _role_metrics_required(env: dict[str, str], repo_root: Path) -> bool:
    config_path = Path(env.get("ATLAS_CONFIG_PATH") or (repo_root / "config.yaml")).resolve()
    if not config_path.is_file():
        return False
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    role_cfg = cfg.get("role_ctx") or {}
    return bool(role_cfg.get("enabled", False))


def _load_bundle_manifest(workspace: Path) -> dict | None:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _bundle_target_datetimes(bundle_zip: Path, workspace: Path) -> tuple[datetime | None, datetime | None]:
    manifest = _load_bundle_manifest(workspace) or {}
    generated_at_utc = (manifest.get("generated_at_utc") or "").strip()
    if generated_at_utc:
        try:
            utc_dt = datetime.fromisoformat(generated_at_utc)
            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(tzinfo=timezone.utc)
            local_dt = utc_dt.astimezone(ZoneInfo("America/Chicago"))
            return utc_dt, local_dt
        except Exception:
            pass

    stem = bundle_zip.stem
    parts = stem.split("_")
    if len(parts) >= 4:
        run_id = "_".join(parts[-2:])
        try:
            local_dt = datetime.strptime(run_id, "%Y%m%d_%H%M%S").replace(tzinfo=ZoneInfo("America/Chicago"))
            return local_dt.astimezone(timezone.utc), local_dt
        except Exception:
            pass

    return None, None


def _find_best_iael_archive_dir(repo_root: Path, target_utc: datetime | None) -> Path | None:
    if target_utc is None:
        return None

    date_dir = repo_root / "data" / "archives" / "iael" / f"{target_utc:%Y}" / f"{target_utc:%Y-%m-%d}"
    if not date_dir.is_dir():
        return None

    candidates: list[tuple[float, int, Path]] = []
    for child in date_dir.iterdir():
        if not child.is_dir():
            continue
        invalidations = child / "injury_invalidations.json"
        status = child / "status.json"
        if not (invalidations.is_file() and status.is_file()):
            continue
        try:
            child_dt = datetime.strptime(child.name, "%Y%m%d_%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta_seconds = (child_dt - target_utc).total_seconds()
        future_penalty = 1 if delta_seconds > 0 else 0
        candidates.append((abs(delta_seconds), future_penalty, child.resolve()))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[1], item[0]))
    return candidates[0][2]


def _find_best_normalized_snapshot(repo_root: Path, target_local: datetime | None) -> Path | None:
    if target_local is None:
        return None

    normalized_dir = repo_root / "data" / "output" / "injury" / "normalized"
    if not normalized_dir.is_dir():
        return None

    prefix = f"{target_local:%Y-%m-%d}_"
    candidates: list[tuple[float, int, Path]] = []
    for child in normalized_dir.iterdir():
        if not child.is_file() or child.suffix.lower() != ".json" or not child.name.startswith(prefix):
            continue
        try:
            child_dt = datetime.strptime(child.stem, "%Y-%m-%d_%I_%M%p").replace(tzinfo=ZoneInfo("America/Chicago"))
        except ValueError:
            continue
        delta_seconds = (child_dt - target_local).total_seconds()
        future_penalty = 1 if delta_seconds > 0 else 0
        candidates.append((abs(delta_seconds), future_penalty, child.resolve()))

    if not candidates:
        latest = normalized_dir / "latest.json"
        return latest.resolve() if latest.is_file() else None

    candidates.sort(key=lambda item: (item[1], item[0]))
    return candidates[0][2]


CSV_FIELDS = [
    "source", "league", "player", "stat", "asof_ts", "projection",
    "confidence", "over_prob", "under_prob", "over_rating", "under_rating",
    "opp_rank", "notes",
]


def _merge_priors_with_oddsapi(bundled_priors: Path, oddsapi_csv: Path) -> Path:
    """Merge bundled BettingPros priors with OddsAPI historical data into a temp CSV."""
    existing_rows: list[dict[str, str]] = []
    if bundled_priors.is_file():
        with bundled_priors.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("source", "").strip().lower() != "oddsapi":
                    existing_rows.append(row)

    oa_rows: list[dict[str, str]] = []
    if oddsapi_csv.is_file():
        with oddsapi_csv.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                oa_rows.append(row)

    all_rows = existing_rows + oa_rows
    merged = bundled_priors.parent / "external_priors_merged.csv"
    with merged.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            safe_row = {k: row.get(k, "") for k in CSV_FIELDS}
            writer.writerow(safe_row)

    print(f"[REPLAY_BUNDLE] Merged priors: {len(existing_rows)} existing + {len(oa_rows)} oddsapi = {len(all_rows)} total")
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Atlas sandbox replay from a FULL_RUN bundle zip (bundle-first, deterministic)."
    )
    ap.add_argument(
        "bundle",
        help=(
            "Bundle id or path. Examples: 20260219_062634, atlas_bundle_20260219_062634.zip, or full path to a .zip"
        ),
    )
    ap.add_argument("--scenario-id", default="", help="Scenario id used for output/archives folder naming.")
    ap.add_argument("--keep-workspace", action="store_true", help="Keep extracted bundle workspace (debug).")
    ap.add_argument("--oddsapi-overlay", default="", help="Path to OddsAPI historical CSV to merge into bundled priors.")
    args = ap.parse_args()

    repo_root = find_repo_root(Path(__file__).parent)
    bundle_zip = _resolve_bundle_path(repo_root, args.bundle)

    scenario_id = (args.scenario_id or bundle_zip.stem).replace(" ", "_")
    ts = _utc_stamp()

    analysis_root = repo_root / "archives" / "bundles" / scenario_id / "analysis" / ts
    workspace = analysis_root / "workspace"
    logs_dir = analysis_root / "logs"

    # Replay contract: outputs go to data/telemetry/replay_runs/<scenario_id>/<ts>/...
    out_dir = (repo_root / "data" / "telemetry" / "replay_runs" / scenario_id / ts).resolve()

    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    _extract_bundle(bundle_zip, workspace)

    data_dir = workspace / "data"
    if not data_dir.is_dir():
        # Older bundles may nest; try best-effort search
        candidates = [p for p in workspace.rglob("data") if p.is_dir() and (p / "board").is_dir()]
        if candidates:
            data_dir = candidates[0]
        else:
            raise FileNotFoundError(f"Bundle extract missing expected 'data/' folder: {bundle_zip}")

    replay_truth_path = repo_root / "data" / "telemetry" / "Last 10" / "Last10.csv"

    # Prefer bundled gamelogs, fall back to repo cache for reconstruction-only fallback.
    bundled_gamelogs = data_dir / "gamelogs" / "nba_gamelogs.csv"
    repo_gamelogs = repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"
    gamelogs_path = bundled_gamelogs if bundled_gamelogs.is_file() else repo_gamelogs
    if not gamelogs_path.is_file():
        print(f"[REPLAY_BUNDLE] Missing gamelogs: {bundled_gamelogs} and {repo_gamelogs}")
        return 2

    env = os.environ.copy()
    env["ATLAS_AUTHORITY"] = "replay"
    env["ATLAS_STRICT_REPLAY"] = "1"
    env["ATLAS_DATA_DIR"] = str(data_dir)
    env["ATLAS_OUT_DIR"] = str(out_dir)
    env["ATLAS_GAMELOGS_PATH"] = str(gamelogs_path)

    raw_path = _find_unique_file(data_dir, "*.json", parent_name="raw")
    if raw_path is not None:
        env["ATLAS_REPLAY_RAW"] = str(raw_path)

    rotowire_path = _find_unique_file(data_dir, "rotowire_lines.json", parent_name="input")
    if rotowire_path is not None:
        env["ATLAS_ROTOWIRE_LINES_PATH"] = str(rotowire_path)

    snapshot_dir = _find_dashboard_snapshot_dir(data_dir)
    if snapshot_dir is not None:
        env["ATLAS_IAEL_SNAPSHOT_DIR"] = str(snapshot_dir)
        env["ATLAS_IAEL_INVALIDATIONS_PATH"] = str(snapshot_dir / "injury_invalidations_latest.json")
        env["ATLAS_IAEL_STATUS_PATH"] = str(snapshot_dir / "status_latest.json")
        env["ATLAS_IAEL_NORMALIZED_PATH"] = str(snapshot_dir / "normalized_latest.json")
    else:
        target_utc, target_local = _bundle_target_datetimes(bundle_zip, workspace)
        archive_dir = _find_best_iael_archive_dir(repo_root, target_utc)
        normalized_path = _find_best_normalized_snapshot(repo_root, target_local)
        if archive_dir is not None:
            env["ATLAS_IAEL_INVALIDATIONS_PATH"] = str(archive_dir / "injury_invalidations.json")
            env["ATLAS_IAEL_STATUS_PATH"] = str(archive_dir / "status.json")
            print(f"[REPLAY_BUNDLE] IAEL archive fallback={archive_dir}")
        if normalized_path is not None:
            env["ATLAS_IAEL_NORMALIZED_PATH"] = str(normalized_path)
            print(f"[REPLAY_BUNDLE] normalized fallback={normalized_path}")

    target_utc, _target_local = _bundle_target_datetimes(bundle_zip, workspace)
    role_metrics_artifacts = _find_bundle_role_metrics_artifacts(data_dir)
    if not role_metrics_artifacts:
        role_metrics_artifacts = _find_best_role_metrics_artifacts(repo_root, target_utc)
    for key, path in role_metrics_artifacts.items():
        env[key] = str(path)
    if role_metrics_artifacts.get("ATLAS_ROLE_METRICS_PATH"):
        print(f"[REPLAY_BUNDLE] role metrics json={role_metrics_artifacts['ATLAS_ROLE_METRICS_PATH']}")
        if role_metrics_artifacts.get("ATLAS_ROLE_METRICS_HTML_PATH"):
            print(f"[REPLAY_BUNDLE] role metrics html={role_metrics_artifacts['ATLAS_ROLE_METRICS_HTML_PATH']}")
        if role_metrics_artifacts.get("ATLAS_ROLE_METRICS_MANIFEST_PATH"):
            print(f"[REPLAY_BUNDLE] role metrics manifest={role_metrics_artifacts['ATLAS_ROLE_METRICS_MANIFEST_PATH']}")
    elif _role_metrics_required(env, repo_root):
        print("[REPLAY_BUNDLE] Missing pinned role-metrics artifacts for role_ctx-enabled replay.")
        print("[REPLAY_BUNDLE] Expected bundle dashboard role_metrics_latest.json or explicit ATLAS_ROLE_METRICS_* paths.")
        return 2

    cmd = [sys.executable, "-m", "Atlas.engine.main"]

    # Pin external priors from bundle (deterministic replay), merging OddsAPI overlay if provided
    bundled_priors = data_dir / "input" / "external_priors_today.csv"
    oddsapi_overlay = Path(args.oddsapi_overlay) if args.oddsapi_overlay else None
    if bundled_priors.is_file() and oddsapi_overlay and oddsapi_overlay.is_file():
        # Merge bundled BettingPros + OddsAPI historical into one file
        merged = _merge_priors_with_oddsapi(bundled_priors, oddsapi_overlay)
        env["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(merged)
        print(f"[REPLAY_BUNDLE] external priors merged: bundle + oddsapi -> {merged}")
    elif oddsapi_overlay and oddsapi_overlay.is_file() and not bundled_priors.is_file():
        # No bundle priors, but OddsAPI available — use OddsAPI alone
        env["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(oddsapi_overlay)
        print(f"[REPLAY_BUNDLE] external priors from oddsapi only={oddsapi_overlay}")
    elif bundled_priors.is_file():
        env["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(bundled_priors)
        print(f"[REPLAY_BUNDLE] external priors pinned={bundled_priors}")
    else:
        print("[REPLAY_BUNDLE] No bundled external_priors_today.csv — priors will use repo default")

    # Rebuild share matrix with this bundle's IAEL snapshot (mimics live orchestrator Stage 3)
    sm_cmd = [sys.executable, str(repo_root / "tools" / "build_share_matrix.py")]
    print(f"[REPLAY_BUNDLE] Rebuilding share matrix with pinned IAEL")
    sm_result = subprocess.run(sm_cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    if sm_result.returncode != 0:
        tail = "\n".join((sm_result.stderr or "").splitlines()[-10:])
        print(f"[REPLAY_BUNDLE] WARN share matrix build failed: {tail}")
    else:
        sm_path = repo_root / "data" / "model" / "share_matrix.csv"
        if sm_path.exists():
            try:
                sm_rows = sum(1 for _ in open(sm_path, encoding="utf-8")) - 1
                print(f"[REPLAY_BUNDLE] share_matrix.csv rebuilt: {sm_rows} rows")
            except Exception:
                pass

    stdout_path = logs_dir / "engine_stdout.txt"
    stderr_path = logs_dir / "engine_stderr.txt"

    print(f"[REPLAY_BUNDLE] bundle={bundle_zip}")
    print(f"[REPLAY_BUNDLE] scenario_id={scenario_id}")
    print(f"[REPLAY_BUNDLE] analysis_root={analysis_root}")
    print(f"[REPLAY_BUNDLE] data_dir={data_dir}")
    print(f"[REPLAY_BUNDLE] out_dir={out_dir}")
    print(f"[REPLAY_BUNDLE] running: {' '.join(cmd)}")

    p = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    stdout_path.write_text(p.stdout or "", encoding="utf-8")
    stderr_path.write_text(p.stderr or "", encoding="utf-8")

    print(f"[REPLAY_BUNDLE] exit_code={p.returncode}")
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").splitlines()[-40:])
        print("[REPLAY_BUNDLE] engine stderr tail:")
        print(tail)
        return p.returncode

    eval_path = backfill_latest_replay_eval_legs(
        output_root=out_dir,
        gamelogs_path=[replay_truth_path, bundled_gamelogs, repo_gamelogs],
        repo_root=repo_root,
        python_executable=sys.executable,
    )
    print(f"[REPLAY_BUNDLE] eval_legs={eval_path}")
    summary_path = _write_role_metrics_payload_summary(eval_path)
    if summary_path is not None:
        print(f"[REPLAY_BUNDLE] role_metrics_payload_summary={summary_path}")

    print("[REPLAY_BUNDLE] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
