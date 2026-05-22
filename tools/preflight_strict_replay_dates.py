#!/usr/bin/env python
"""Preflight strict replay source coverage before running an NBA corpus.

This tool does not score or replay. It checks whether each requested replay
date has the pinned source inputs required for strict-fidelity replay so a
corpus run cannot finish hours later and then discover it was contaminated.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import batch_replay_backfill as brb  # noqa: E402
import replay_bundle as rb  # noqa: E402


DEFAULT_DATES = [
    "20260430",
    "20260501",
    "20260502",
    "20260503",
    "20260504",
    "20260505",
    "20260506",
    "20260507",
    "20260508",
    "20260509",
    "20260510",
    "20260511",
    "20260512",
    "20260513",
    "20260515",
    "20260517",
    "20260518",
    "20260519",
    "20260520",
]


def _iso(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}"


def _count_csv_rows(path: Path | None) -> int:
    if not path or not path.is_file():
        return 0
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            return max(0, sum(1 for _ in csv.DictReader(f)))
    except Exception:
        return 0


def _data_dir_from_bundle(bundle_path: Path, workspace: Path) -> Path:
    rb._extract_bundle(bundle_path, workspace)
    data_dir = workspace / "data"
    if data_dir.is_dir():
        return data_dir
    candidates = [p for p in workspace.rglob("data") if p.is_dir() and (p / "board").is_dir()]
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"Bundle extract missing expected data folder: {bundle_path}")


def _find_bundle_raw(data_dir: Path) -> Path | None:
    raw_dir = data_dir / "raw"
    if raw_dir.is_dir():
        candidates = sorted(p for p in raw_dir.rglob("*.json") if p.is_file())
        if candidates:
            return candidates[0]
    return rb._find_unique_file(data_dir, "*.json", parent_name="raw")


def _record_source(name: str, path: Path | None, *, rows: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "path": str(path) if path else None,
        "exists": bool(path and path.is_file()),
    }
    if rows is not None:
        payload["rows"] = rows
    elif path and path.suffix.lower() == ".csv":
        payload["rows"] = _count_csv_rows(path)
    return payload


def _audit_bundle_date(date: str, bundle_path: Path, gamelog_dates: set[str]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    sources: list[dict[str, Any]] = []
    line_status = {"ok": False, "reason": "not_checked"}
    role_status = {"ok": False, "paths": {}}
    injury_status = {"ok": False, "paths": {}}

    target_utc, target_local = brb._bundle_capture_times(bundle_path, date)
    with tempfile.TemporaryDirectory(prefix=f"atlas_preflight_{date}_") as tmp:
        workspace = Path(tmp)
        try:
            data_dir = _data_dir_from_bundle(bundle_path, workspace)
        except Exception as exc:
            failures.append(f"bundle_extract_failed:{exc}")
            data_dir = workspace / "data"

        raw_path = _find_bundle_raw(data_dir) if data_dir.exists() else None
        sources.append(_record_source("prizepicks_raw_bundle", raw_path))
        if not raw_path:
            failures.append("missing_bundle_prizepicks_raw")

        bundled_priors = data_dir / "input" / "external_priors_today.csv"
        sources.append(_record_source("external_priors_bundle", bundled_priors))
        if not bundled_priors.is_file():
            failures.append("missing_bundle_external_priors")

        rotowire_path = data_dir / "input" / "rotowire_lines.json"
        sources.append(_record_source("game_lines_bundle", rotowire_path))
        if not rotowire_path.is_file():
            failures.append("missing_bundle_game_lines")
        else:
            ok, reason = rb._game_line_context_status(rotowire_path, game_date=_iso(date))
            line_status = {"ok": ok, "reason": reason}
            if not ok:
                failures.append(f"unusable_game_lines:{reason}")

        snapshot_dir = rb._find_dashboard_snapshot_dir(data_dir)
        if snapshot_dir:
            inv = snapshot_dir / "injury_invalidations_latest.json"
            status = snapshot_dir / "status_latest.json"
            norm = snapshot_dir / "normalized_latest.json"
            injury_status = {
                "ok": inv.is_file() and status.is_file() and norm.is_file(),
                "paths": {
                    "snapshot_dir": str(snapshot_dir),
                    "invalidations": str(inv),
                    "status": str(status),
                    "normalized": str(norm),
                },
            }
        else:
            iael_dir = rb._find_best_iael_archive_dir(ROOT, target_utc)
            norm_path = rb._find_best_normalized_snapshot(ROOT, target_local)
            injury_status = {
                "ok": bool(
                    iael_dir
                    and (iael_dir / "injury_invalidations.json").is_file()
                    and (iael_dir / "status.json").is_file()
                    and norm_path
                    and norm_path.is_file()
                ),
                "paths": {
                    "iael_dir": str(iael_dir) if iael_dir else None,
                    "normalized": str(norm_path) if norm_path else None,
                },
            }
        if not injury_status["ok"]:
            failures.append("missing_injury_context")

        role_paths = rb._find_bundle_role_metrics_artifacts(data_dir)
        if not role_paths:
            role_paths = rb._find_best_role_metrics_artifacts(ROOT, target_utc)
        role_status = {
            "ok": bool(role_paths.get("ATLAS_ROLE_METRICS_PATH")),
            "paths": {k: str(v) for k, v in role_paths.items()},
        }
        if not role_status["ok"]:
            failures.append("missing_role_metrics")

    oa_path = brb._find_oddsapi_archive(date)
    archive_paths = brb._archive_market_source_paths(date, target_utc)
    bp_path = archive_paths.get("ATLAS_BETTINGPROS_PROPS_CSV_PATH")
    dk_path = archive_paths.get("ATLAS_DRAFTKINGS_PROPS_CSV_PATH")
    gh_path = archive_paths.get("ATLAS_GITHUB_PROP_ODDS_CSV_PATH")

    market_sources = [
        _record_source("oddsapi_overlay", oa_path),
        _record_source("bettingpros_overlay", bp_path),
        _record_source("draftkings_overlay", dk_path),
        _record_source("github_prop_odds_overlay", gh_path),
    ]
    overlay_rows = sum(int(src.get("rows") or 0) for src in market_sources)
    if overlay_rows <= 0 and _count_csv_rows(bundle_path.parent / "__never_exists__.csv") <= 0:
        warnings.append("no_market_overlay_rows_found")
    if not gh_path:
        warnings.append("no_github_prop_odds_overlay")

    if date not in gamelog_dates:
        failures.append("missing_gamelog_truth")

    return {
        "date": date,
        "date_iso": _iso(date),
        "source_type": "bundle",
        "source": str(bundle_path),
        "target_utc": target_utc.isoformat() if target_utc else None,
        "target_local": target_local.isoformat() if target_local else None,
        "verdict": "PASS" if not failures else "FAIL",
        "failures": failures,
        "warnings": warnings,
        "sources": sources,
        "market_sources": market_sources,
        "market_overlay_rows": overlay_rows,
        "game_line_context": line_status,
        "injury_context": injury_status,
        "role_metrics_context": role_status,
        "gamelog_truth": {"ok": date in gamelog_dates},
    }


def _audit_raw_date(date: str, raw_path: Path, gamelog_dates: set[str]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    target_utc, target_local = brb._raw_capture_times(raw_path, date)

    iael_dir = brb._find_best_iael_archive_dir(date, target_utc)
    roto_path = brb._find_rotowire_for_date(date, target_utc)
    norm_path = brb._find_best_normalized(date, target_local)
    role_paths = rb._find_best_role_metrics_artifacts(ROOT, target_utc)
    gamelogs_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
    market_paths = brb._archive_market_source_paths(date, target_utc)
    oa_path = brb._find_oddsapi_archive(date)

    if not raw_path.is_file():
        failures.append("missing_prizepicks_raw")
    if date not in gamelog_dates or not gamelogs_path.is_file():
        failures.append("missing_gamelog_truth")
    if not iael_dir:
        failures.append("missing_iael_archive")
    if not norm_path:
        failures.append("missing_normalized_injury_snapshot")
    if not role_paths.get("ATLAS_ROLE_METRICS_PATH"):
        failures.append("missing_role_metrics")

    line_status = {"ok": False, "reason": "missing_rotowire_lines"}
    if roto_path:
        ok, reason = brb._game_line_context_status(roto_path, game_date=_iso(date))
        line_status = {"ok": ok, "reason": reason}
        if not ok:
            failures.append(f"unusable_game_lines:{reason}")
    else:
        failures.append("missing_game_lines")

    market_sources = [
        _record_source("oddsapi_overlay", oa_path),
        _record_source("bettingpros_overlay", market_paths.get("ATLAS_BETTINGPROS_PROPS_CSV_PATH")),
        _record_source("draftkings_overlay", market_paths.get("ATLAS_DRAFTKINGS_PROPS_CSV_PATH")),
        _record_source("github_prop_odds_overlay", market_paths.get("ATLAS_GITHUB_PROP_ODDS_CSV_PATH")),
    ]
    overlay_rows = sum(int(src.get("rows") or 0) for src in market_sources)
    if overlay_rows <= 0:
        failures.append("missing_pinned_market_priors")
    if not market_paths.get("ATLAS_GITHUB_PROP_ODDS_CSV_PATH"):
        warnings.append("no_github_prop_odds_overlay")

    return {
        "date": date,
        "date_iso": _iso(date),
        "source_type": "raw",
        "source": str(raw_path),
        "target_utc": target_utc.isoformat() if target_utc else None,
        "target_local": target_local.isoformat() if target_local else None,
        "verdict": "PASS" if not failures else "FAIL",
        "failures": failures,
        "warnings": warnings,
        "sources": [
            _record_source("prizepicks_raw", raw_path),
            _record_source("game_lines_archive", roto_path),
            _record_source("gamelogs", gamelogs_path),
        ],
        "market_sources": market_sources,
        "market_overlay_rows": overlay_rows,
        "game_line_context": line_status,
        "injury_context": {
            "ok": bool(iael_dir and norm_path),
            "paths": {
                "iael_dir": str(iael_dir) if iael_dir else None,
                "normalized": str(norm_path) if norm_path else None,
            },
        },
        "role_metrics_context": {
            "ok": bool(role_paths.get("ATLAS_ROLE_METRICS_PATH")),
            "paths": {k: str(v) for k, v in role_paths.items()},
        },
        "gamelog_truth": {"ok": date in gamelog_dates},
    }


def audit_dates(dates: list[str]) -> dict[str, Any]:
    bundle_map = brb._build_bundle_map()
    raw_map = brb._build_raw_json_map()
    gamelog_dates = brb._get_gamelog_dates()
    no_game_dates = [d for d in dates if d not in gamelog_dates]

    date_results: list[dict[str, Any]] = []
    for date in dates:
        if date in bundle_map:
            result = _audit_bundle_date(date, bundle_map[date], gamelog_dates)
        elif date in raw_map:
            result = _audit_raw_date(date, raw_map[date], gamelog_dates)
        else:
            result = {
                "date": date,
                "date_iso": _iso(date),
                "source_type": "missing",
                "source": None,
                "verdict": "FAIL",
                "failures": ["missing_bundle_or_raw_snapshot"],
                "warnings": [],
                "market_sources": [],
                "market_overlay_rows": 0,
                "gamelog_truth": {"ok": date in gamelog_dates},
            }
        date_results.append(result)

    failed = [r for r in date_results if r.get("verdict") != "PASS"]
    passed = [r for r in date_results if r.get("verdict") == "PASS"]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "requested_dates": dates,
        "no_game_dates": no_game_dates,
        "verdict": "PASS" if not failed else "FAIL",
        "pass_count": len(passed),
        "fail_count": len(failed),
        "date_results": date_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight strict replay dates before corpus replay.")
    parser.add_argument("--dates", nargs="*", default=DEFAULT_DATES, help="Replay dates as YYYYMMDD.")
    parser.add_argument("--out", default="", help="Output JSON path. Default: data/model/candidates/strict_replay_preflight_<stamp>.json")
    args = parser.parse_args()

    dates = [d.strip() for d in args.dates if d and d.strip()]
    payload = audit_dates(dates)
    out_path = Path(args.out) if args.out else ROOT / "data" / "model" / "candidates" / f"strict_replay_preflight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"[PREFLIGHT] verdict={payload['verdict']} pass={payload['pass_count']} fail={payload['fail_count']}")
    for row in payload["date_results"]:
        status = row.get("verdict")
        date = row.get("date")
        source_type = row.get("source_type")
        overlay_rows = row.get("market_overlay_rows")
        failures = ", ".join(row.get("failures") or [])
        warnings = ", ".join(row.get("warnings") or [])
        suffix = f" failures=[{failures}]" if failures else ""
        if warnings:
            suffix += f" warnings=[{warnings}]"
        print(f"  {date} {status} source={source_type} overlays={overlay_rows}{suffix}")
    print(f"[PREFLIGHT] wrote {out_path}")
    return 0 if payload["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
