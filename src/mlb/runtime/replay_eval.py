"""Replay settlement and probability diagnostics for MLB scored runs."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from mlb.contracts.engine import BETTINGPROS_CONTEXT_FIELDS
from mlb.domain.scoring import hitter_fantasy_score, pitcher_fantasy_score
from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import candidate_run_dirs, ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.season_gamelogs import (
    append_boxscore_rows_to_season_gamelogs,
    load_season_gamelog_rows,
)

REPLAY_EVAL_VERSION = "statsapi_boxscore_replay_eval_v0"
SLIP_EVAL_VERSION = "atlas_mlb_slip_eval_v0"

EVAL_COLUMNS = (
    "run_id",
    "source_run_id",
    "snapshot_id",
    "source_projection_id",
    "event_id",
    "game_date",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "market",
    "line",
    "side",
    "actual_value",
    "actual_side",
    "result",
    "model_probability",
    "over_probability",
    "under_probability",
    "push_probability",
    "brier",
    "logloss",
    "settlement_status",
    "settlement_source",
    "settlement_game_pk",
    "settlement_person_id",
    "simulation_kernel_version",
    "simulation_n",
    "simulation_seed",
    "parameter_model_version",
    "calibration_version",
    "method",
    "kernel_version",
    "model_version",
    "confidence_tier",
    *BETTINGPROS_CONTEXT_FIELDS,
    "flags",
)

SLIP_EVAL_COLUMNS = (
    "run_id",
    "family",
    "label",
    "slip_id",
    "target_leg_count",
    "leg_count",
    "settled_leg_count",
    "win_count",
    "loss_count",
    "push_count",
    "unsettled_count",
    "result",
    "hit_prob",
    "payout_mult",
    "ev",
    "brier",
    "logloss",
    "legs",
    "leg_results",
)


def evaluate_scored_run_result(
    *,
    run_id: str | None = None,
    scored_legs_path: Path | None = None,
    root: Path | None = None,
) -> RuntimeCommandResult:
    manifest = evaluate_scored_run(run_id=run_id, scored_legs_path=scored_legs_path, root=root)
    lines = [
        "Evaluated MLB scored run:",
        f"  run_id: {manifest['run_id']}",
        f"  row_count: {manifest['row_count']}",
        f"  settled_count: {manifest['settled_count']}",
        f"  metric_count: {manifest['metric_count']}",
        f"  win_rate: {manifest['win_rate']}",
        f"  brier: {manifest['brier']}",
        f"  logloss: {manifest['logloss']}",
        f"  slip_count: {manifest['slip_eval']['slip_count']}",
        f"  slip_win_rate: {manifest['slip_eval']['win_rate']}",
        f"  slip_eval: {manifest['slip_eval']['slip_eval_path']}",
        f"  csv: {manifest['csv_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="evaluate_scored_run", payload=manifest, lines=tuple(lines))


def evaluate_scored_run(
    *,
    run_id: str | None = None,
    scored_legs_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    resolved_scored_path = _resolve_scored_legs_path(paths=paths, run_id=run_id, scored_legs_path=scored_legs_path)
    scored_payload = json.loads(resolved_scored_path.read_text(encoding="utf-8"))
    scored_legs = [row for row in scored_payload.get("scored_legs", []) if isinstance(row, dict)]
    resolved_run_id = run_id or str(scored_payload.get("run_id") or resolved_scored_path.parent.name)
    dates = sorted({str(row.get("game_date") or "") for row in scored_legs if row.get("game_date")})
    staged_boxscore_rows = _load_staged_boxscore_rows(paths=paths, dates=dates)
    season_gamelog_rows = _load_season_boxscore_rows(root=root, dates=dates)
    boxscore_rows = [*staged_boxscore_rows, *season_gamelog_rows]
    settlement_index = _SettlementIndex(boxscore_rows)
    rows = [_evaluate_leg(row, settlement_index=settlement_index) for row in scored_legs]
    season = _season_from_dates(dates)
    season_gamelog_manifest = (
        append_boxscore_rows_to_season_gamelogs(boxscore_rows=staged_boxscore_rows, season=season, root=root)
        if staged_boxscore_rows and season
        else None
    )

    output_dir = paths.eval / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "eval_legs.csv"
    json_path = output_dir / "eval_legs.json"
    summary_path = output_dir / "eval_summary.json"
    manifest_path = output_dir / "eval_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "replay_eval_version": REPLAY_EVAL_VERSION,
                "row_count": len(rows),
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    summary = _summary(rows)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    slip_eval = _evaluate_slips(
        run_id=resolved_run_id,
        run_dir=resolved_scored_path.parent,
        eval_rows=rows,
        output_dir=output_dir,
        paths=paths,
    )
    manifest = {
        "run_id": resolved_run_id,
        "source_run_id": str(scored_payload.get("source_run_id") or ""),
        "replay_eval_version": REPLAY_EVAL_VERSION,
        "scored_legs_path": str(resolved_scored_path),
        "dates": dates,
        "boxscore_row_count": len(boxscore_rows),
        "staged_boxscore_row_count": len(staged_boxscore_rows),
        "season_gamelog_row_count": len(season_gamelog_rows),
        "season_gamelogs": season_gamelog_manifest,
        "row_count": len(rows),
        "settled_count": summary["settled_count"],
        "metric_count": summary["metric_count"],
        "win_rate": summary["win_rate"],
        "brier": summary["brier"],
        "logloss": summary["logloss"],
        "result_counts": summary["result_counts"],
        "settlement_status_counts": summary["settlement_status_counts"],
        "market_summary": summary["market_summary"],
        "probability_path_counts": summary["probability_path_counts"],
        "sobol": summary["sobol"],
        "slip_eval": slip_eval,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "summary_path": str(summary_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.eval / "latest_eval_legs.csv"),
        "latest_json_path": str(paths.eval / "latest_eval_legs.json"),
        "latest_summary_path": str(paths.eval / "latest_eval_summary.json"),
        "latest_slip_eval_path": str(paths.eval / "latest_slip_eval.json"),
        "latest_eval_slips_csv_path": str(paths.eval / "latest_eval_slips.csv"),
        "latest_eval_slips_json_path": str(paths.eval / "latest_eval_slips.json"),
        "latest_manifest_path": str(paths.eval / "latest_eval_manifest.json"),
        "columns": list(EVAL_COLUMNS),
        "slip_columns": list(SLIP_EVAL_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.eval / "latest_eval_legs.csv")
    _copy_latest(json_path, paths.eval / "latest_eval_legs.json")
    _copy_latest(summary_path, paths.eval / "latest_eval_summary.json")
    _copy_latest(manifest_path, paths.eval / "latest_eval_manifest.json")
    from mlb.runtime.runtime_state import publish_eval_runtime_state

    manifest["runtime_state"] = publish_eval_runtime_state(eval_manifest=manifest, root=root)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(manifest_path, paths.eval / "latest_eval_manifest.json")
    return manifest


def _evaluate_leg(row: dict[str, Any], *, settlement_index: "_SettlementIndex") -> dict[str, Any]:
    side = str(row.get("side") or "").lower()
    match = settlement_index.match(row)
    actual_value = None
    status = "missing_boxscore_match"
    actual_side = ""
    result = ""
    brier = None
    logloss = None
    settlement_source = ""
    settlement_game_pk = 0
    settlement_person_id = 0
    flags = list(_tuple_flags(row.get("flags")))

    if match:
        actual_value = _actual_value(row.get("market"), match)
        if actual_value is None:
            status = "unsupported_or_no_action"
        else:
            status = "settled"
            actual_side = _actual_side(actual_value, _float(row.get("line")))
            result = _result_for_side(side=side, actual_side=actual_side)
            settlement_source = str(match.get("source") or "statsapi_boxscores_bulk")
            settlement_game_pk = _int(match.get("game_pk"))
            settlement_person_id = _int(match.get("person_id") or match.get("espn_player_id"))
            if result in {"win", "loss"}:
                probability = _clamp(_float(row.get("model_probability")), 1e-6, 1.0 - 1e-6)
                outcome = 1.0 if result == "win" else 0.0
                brier = round((probability - outcome) ** 2, 6)
                logloss = round(-(outcome * math.log(probability) + (1.0 - outcome) * math.log(1.0 - probability)), 6)
        flags.extend(match.get("_settlement_flags", ()))

    return {
        "run_id": str(row.get("run_id") or ""),
        "source_run_id": str(row.get("source_run_id") or ""),
        "snapshot_id": str(row.get("snapshot_id") or ""),
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "game_date": str(row.get("game_date") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "market": str(row.get("market") or ""),
        "line": _float(row.get("line")),
        "side": side,
        "actual_value": actual_value,
        "actual_side": actual_side,
        "result": result,
        "model_probability": _float(row.get("model_probability")),
        "over_probability": _float(row.get("over_probability")),
        "under_probability": _float(row.get("under_probability")),
        "push_probability": _float(row.get("push_probability")),
        "brier": brier,
        "logloss": logloss,
        "settlement_status": status,
        "settlement_source": settlement_source,
        "settlement_game_pk": settlement_game_pk,
        "settlement_person_id": settlement_person_id,
        "simulation_kernel_version": str(row.get("simulation_kernel_version") or ""),
        "simulation_n": _int(row.get("simulation_n")),
        "simulation_seed": _int(row.get("simulation_seed")),
        "parameter_model_version": str(row.get("parameter_model_version") or ""),
        "calibration_version": str(row.get("calibration_version") or ""),
        "method": str(row.get("method") or ""),
        "kernel_version": str(row.get("kernel_version") or ""),
        "model_version": str(row.get("model_version") or ""),
        "confidence_tier": str(row.get("confidence_tier") or ""),
        **_bettingpros_context_fields(row),
        "flags": tuple(dict.fromkeys(flag for flag in flags if flag)),
    }


class _SettlementIndex:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._exact: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        self._team: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._date_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            date = _row_date(row)
            name = _player_key(row.get("player_name"))
            team = canonical_team_abbr(row.get("team_name"))
            opponent = canonical_team_abbr(row.get("opponent_name"))
            if not date or not name:
                continue
            self._exact.setdefault((date, name, team, opponent), []).append(row)
            self._team.setdefault((date, name, team), []).append(row)
            self._date_name.setdefault((date, name), []).append(row)

    def match(self, leg: dict[str, Any]) -> dict[str, Any] | None:
        date = str(leg.get("game_date") or "")
        name = _player_key(leg.get("player_name"))
        team = canonical_team_abbr(leg.get("player_team"))
        opponent = canonical_team_abbr(leg.get("opponent"))
        for key in ((date, name, team, opponent),):
            match = self._select(self._exact.get(key, []))
            if match:
                return match
        if team:
            match = self._select(self._team.get((date, name, team), []))
            if match:
                return match
        return self._select(self._date_name.get((date, name), []))

    @staticmethod
    def _select(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not candidates:
            return None
        selected = dict(sorted(candidates, key=lambda row: (_int(row.get("game_pk")), _int(row.get("person_id"))))[0])
        if len(candidates) > 1:
            selected["_settlement_flags"] = ("multiple_boxscore_matches",)
        return selected


def _actual_value(market: Any, boxscore_row: dict[str, Any]) -> float | None:
    market_key = str(market or "")
    batting = boxscore_row.get("batting_stats") if isinstance(boxscore_row.get("batting_stats"), dict) else {}
    pitching = boxscore_row.get("pitching_stats") if isinstance(boxscore_row.get("pitching_stats"), dict) else {}
    if market_key in {
        "hits",
        "singles",
        "doubles",
        "triples",
        "total_bases",
        "hits_runs_rbis",
        "runs",
        "rbis",
        "home_runs",
        "plate_appearances",
        "walks",
        "stolen_bases",
        "hitter_strikeouts",
        "hitter_fantasy_score",
    }:
        if not batting:
            return None
        hits = _int(batting.get("hits"))
        doubles = _int(batting.get("doubles"))
        triples = _int(batting.get("triples"))
        home_runs = _int(batting.get("homeRuns"))
        singles = max(0, hits - doubles - triples - home_runs)
        if market_key == "hits":
            return float(hits)
        if market_key == "singles":
            return float(singles)
        if market_key == "doubles":
            return float(doubles)
        if market_key == "triples":
            return float(triples)
        if market_key == "total_bases":
            return float(_int(batting.get("totalBases")) or singles + doubles * 2 + triples * 3 + home_runs * 4)
        if market_key == "hits_runs_rbis":
            return float(hits + _int(batting.get("runs")) + _int(batting.get("rbi")))
        if market_key == "runs":
            return float(_int(batting.get("runs")))
        if market_key == "rbis":
            return float(_int(batting.get("rbi")))
        if market_key == "home_runs":
            return float(home_runs)
        if market_key == "plate_appearances":
            return float(_int(batting.get("plateAppearances")))
        if market_key == "walks":
            return float(_int(batting.get("baseOnBalls")))
        if market_key == "stolen_bases":
            return float(_int(batting.get("stolenBases")))
        if market_key == "hitter_strikeouts":
            return float(_int(batting.get("strikeOuts")))
        if market_key == "hitter_fantasy_score":
            return float(
                hitter_fantasy_score(
                    singles=singles,
                    doubles=doubles,
                    triples=triples,
                    home_runs=home_runs,
                    runs=_int(batting.get("runs")),
                    rbis=_int(batting.get("rbi")),
                    walks=_int(batting.get("baseOnBalls")),
                    hit_by_pitch=_int(batting.get("hitByPitch")),
                    stolen_bases=_int(batting.get("stolenBases")),
                )
            )
    if market_key in {
        "pitcher_strikeouts",
        "pitching_outs",
        "hits_allowed",
        "earned_runs_allowed",
        "walks_allowed",
        "pitches_thrown",
        "pitcher_fantasy_score",
    }:
        if not pitching:
            return None
        outs = _int(pitching.get("outs")) or _outs_from_innings(pitching.get("inningsPitched"))
        if market_key == "pitcher_strikeouts":
            return float(_int(pitching.get("strikeOuts")))
        if market_key == "pitching_outs":
            return float(outs)
        if market_key == "hits_allowed":
            return float(_int(pitching.get("hits")))
        if market_key == "earned_runs_allowed":
            return float(_int(pitching.get("earnedRuns")))
        if market_key == "walks_allowed":
            return float(_int(pitching.get("baseOnBalls")))
        if market_key == "pitches_thrown":
            return float(_int(pitching.get("pitchesThrown")) or _int(pitching.get("numberOfPitches")))
        if market_key == "pitcher_fantasy_score":
            quality_start = 1 if bool(boxscore_row.get("is_pitching_starter")) and outs >= 18 and _int(pitching.get("earnedRuns")) <= 3 else 0
            return float(
                pitcher_fantasy_score(
                    wins=_int(pitching.get("wins")),
                    quality_starts=quality_start,
                    earned_runs=_int(pitching.get("earnedRuns")),
                    strikeouts=_int(pitching.get("strikeOuts")),
                    outs=outs,
                )
            )
    return None


def _load_boxscore_rows(*, paths, dates: list[str]) -> list[dict[str, Any]]:
    return [*_load_staged_boxscore_rows(paths=paths, dates=dates), *_load_season_boxscore_rows(root=paths.repo_root, dates=dates)]


def _load_staged_boxscore_rows(*, paths, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    rows: list[dict[str, Any]] = []
    for base, filename in (
        (paths.staged / "statsapi_boxscores_bulk", "statsapi_boxscores_bulk.jsonl"),
        (paths.staged / "statsapi_boxscore", "statsapi_boxscore.jsonl"),
    ):
        if not base.exists():
            continue
        for path in sorted(base.glob(f"*/{filename}")):
            for row in _load_jsonl(path):
                if date_set and _row_date(row) not in date_set:
                    continue
                rows.append(row)
    return rows


def _load_season_boxscore_rows(*, root: Path | None, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    rows: list[dict[str, Any]] = []
    season = _season_from_dates(dates)
    for row in load_season_gamelog_rows(root=root, season=season if season else None):
        if date_set and _row_date(row) not in date_set:
            continue
        rows.append(row)
    return rows


def _season_from_dates(dates: list[str]) -> int:
    years = sorted({_int(str(day)[:4]) for day in dates if _int(str(day)[:4])})
    return years[-1] if years else 0


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metric_rows = [row for row in rows if row.get("result") in {"win", "loss"}]
    settled_rows = [row for row in rows if row.get("settlement_status") == "settled"]
    return {
        "row_count": len(rows),
        "settled_count": len(settled_rows),
        "metric_count": len(metric_rows),
        "win_rate": _rate(row.get("result") == "win" for row in metric_rows),
        "brier": _mean(row.get("brier") for row in metric_rows),
        "logloss": _mean(row.get("logloss") for row in metric_rows),
        "result_counts": _counts(row.get("result") or "unsettled" for row in rows),
        "settlement_status_counts": _counts(row.get("settlement_status") for row in rows),
        "market_summary": _market_summary(metric_rows),
        "probability_path_counts": _counts(_probability_path(row) for row in rows),
        "sobol": {
            "simulation_kernel_versions": _counts(row.get("simulation_kernel_version") for row in rows),
            "simulation_n": _counts(str(row.get("simulation_n")) for row in rows),
            "seed_count": len({row.get("simulation_seed") for row in rows if row.get("simulation_seed")}),
        },
    }


def _market_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_market: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_market.setdefault(str(row.get("market") or ""), []).append(row)
    return {
        market: {
            "metric_count": len(items),
            "win_rate": _rate(item.get("result") == "win" for item in items),
            "brier": _mean(item.get("brier") for item in items),
            "logloss": _mean(item.get("logloss") for item in items),
        }
        for market, items in sorted(by_market.items())
    }


def _evaluate_slips(
    *,
    run_id: str,
    run_dir: Path,
    eval_rows: list[dict[str, Any]],
    output_dir: Path,
    paths,
) -> dict[str, Any]:
    slip_specs = _load_slip_specs(run_dir)
    eval_index = _EvalLegIndex(eval_rows)
    evaluated_slips = [_evaluate_slip(spec, eval_index=eval_index, run_id=run_id) for spec in slip_specs]
    summary = _slip_summary(evaluated_slips)

    slip_eval_path = output_dir / "slip_eval.json"
    eval_slips_json_path = output_dir / "eval_slips.json"
    eval_slips_csv_path = output_dir / "eval_slips.csv"
    payload = {
        "run_id": run_id,
        "slip_eval_version": SLIP_EVAL_VERSION,
        "source_run_dir": str(run_dir),
        "slip_count": len(evaluated_slips),
        "summary": summary,
        "slips": evaluated_slips,
    }
    slip_eval_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    eval_slips_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_slip_eval_csv(eval_slips_csv_path, evaluated_slips)
    _copy_latest(slip_eval_path, paths.eval / "latest_slip_eval.json")
    _copy_latest(eval_slips_csv_path, paths.eval / "latest_eval_slips.csv")
    _copy_latest(eval_slips_json_path, paths.eval / "latest_eval_slips.json")
    return {
        "slip_eval_version": SLIP_EVAL_VERSION,
        "slip_count": len(evaluated_slips),
        "metric_count": summary["metric_count"],
        "settled_count": summary["settled_count"],
        "win_rate": summary["win_rate"],
        "brier": summary["brier"],
        "logloss": summary["logloss"],
        "result_counts": summary["result_counts"],
        "family_summary": summary["family_summary"],
        "slip_eval_path": str(slip_eval_path),
        "eval_slips_json_path": str(eval_slips_json_path),
        "eval_slips_csv_path": str(eval_slips_csv_path),
        "latest_slip_eval_path": str(paths.eval / "latest_slip_eval.json"),
        "latest_eval_slips_csv_path": str(paths.eval / "latest_eval_slips.csv"),
        "latest_eval_slips_json_path": str(paths.eval / "latest_eval_slips.json"),
        "columns": list(SLIP_EVAL_COLUMNS),
    }


def _load_slip_specs(run_dir: Path) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    slip_dir = run_dir / "slips"
    for family, prefix in (("System", "system"), ("Windfall", "windfall")):
        for path in sorted(slip_dir.glob(f"{prefix}_*leg.json")):
            payload = _load_json(path)
            legs = [leg for leg in payload.get("legs", []) if isinstance(leg, dict)]
            if not legs:
                continue
            target_leg_count = _int(payload.get("target_leg_count")) or len(legs)
            specs.append(
                {
                    "family": family,
                    "label": f"{target_leg_count}-leg",
                    "slip_id": f"{family}_{target_leg_count}leg",
                    "target_leg_count": target_leg_count,
                    "hit_prob": _float(payload.get("hit_prob")),
                    "payout_mult": _float(payload.get("payout_mult")),
                    "legs": legs,
                    "source_path": str(path),
                }
            )

    demonhunter_path = slip_dir / "demonhunter.json"
    if demonhunter_path.exists():
        payload = _load_json(demonhunter_path)
        for slip in payload.get("slips", []):
            if not isinstance(slip, dict):
                continue
            legs = [leg for leg in slip.get("legs", []) if isinstance(leg, dict)]
            if not legs:
                continue
            target_leg_count = _int(slip.get("target_leg_count")) or len(legs)
            specs.append(
                {
                    "family": "DemonHunter",
                    "label": f"{target_leg_count}-leg",
                    "slip_id": f"DemonHunter_{target_leg_count}leg",
                    "target_leg_count": target_leg_count,
                    "hit_prob": _float(slip.get("hit_prob")),
                    "payout_mult": _float(slip.get("payout_mult")),
                    "legs": legs,
                    "source_path": str(demonhunter_path),
                }
            )

    marketed_path = run_dir / "marketed_slips.json"
    if marketed_path.exists():
        payload = _load_json(marketed_path)
        for slip in payload.get("slips", []):
            if not isinstance(slip, dict):
                continue
            legs = [leg for leg in slip.get("legs", []) if isinstance(leg, dict)]
            if not legs:
                continue
            label = str(slip.get("label") or f"{len(legs)}-leg")
            specs.append(
                {
                    "family": "Marketed",
                    "label": label,
                    "slip_id": f"Marketed_{label}",
                    "target_leg_count": len(legs),
                    "hit_prob": _float(slip.get("hit_prob")),
                    "payout_mult": _float(slip.get("payout_mult")),
                    "legs": legs,
                    "source_path": str(marketed_path),
                }
            )
    return specs


def _evaluate_slip(spec: dict[str, Any], *, eval_index: "_EvalLegIndex", run_id: str) -> dict[str, Any]:
    legs = [leg for leg in spec.get("legs", []) if isinstance(leg, dict)]
    leg_results = [_evaluate_slip_leg(leg, eval_index=eval_index) for leg in legs]
    loss_count = sum(1 for leg in leg_results if leg["result"] == "loss")
    win_count = sum(1 for leg in leg_results if leg["result"] == "win")
    push_count = sum(1 for leg in leg_results if leg["result"] == "push")
    unsettled_count = sum(1 for leg in leg_results if leg["result"] in {"", "unsettled"})
    settled_leg_count = len(leg_results) - unsettled_count
    if not leg_results:
        result = "empty"
    elif loss_count:
        result = "loss"
    elif unsettled_count:
        result = "unsettled"
    elif push_count:
        result = "push"
    else:
        result = "win"

    hit_prob = _float(spec.get("hit_prob")) or _product(
        _float(leg.get("model_probability") or leg.get("p_cal")) for leg in leg_results
    )
    probability = _clamp(hit_prob, 1e-6, 1.0 - 1e-6)
    brier = None
    logloss = None
    if result in {"win", "loss"}:
        outcome = 1.0 if result == "win" else 0.0
        brier = round((probability - outcome) ** 2, 6)
        logloss = round(-(outcome * math.log(probability) + (1.0 - outcome) * math.log(1.0 - probability)), 6)
    payout = _float(spec.get("payout_mult"))
    return {
        "run_id": run_id,
        "family": str(spec.get("family") or ""),
        "label": str(spec.get("label") or ""),
        "slip_id": str(spec.get("slip_id") or ""),
        "source_path": str(spec.get("source_path") or ""),
        "target_leg_count": _int(spec.get("target_leg_count")) or len(legs),
        "leg_count": len(legs),
        "settled_leg_count": settled_leg_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "push_count": push_count,
        "unsettled_count": unsettled_count,
        "result": result,
        "hit_prob": round(hit_prob, 12),
        "payout_mult": payout,
        "ev": round(hit_prob * payout, 12) if payout else 0.0,
        "brier": brier,
        "logloss": logloss,
        "legs": [_slip_leg_label(leg) for leg in leg_results],
        "leg_results": leg_results,
    }


def _evaluate_slip_leg(leg: dict[str, Any], *, eval_index: "_EvalLegIndex") -> dict[str, Any]:
    match = eval_index.match(leg)
    result = str(match.get("result") or "unsettled") if match else "unsettled"
    return {
        "source_projection_id": str(
            leg.get("source_projection_id") or leg.get("projection_id") or (match or {}).get("source_projection_id") or ""
        ),
        "player_name": str(leg.get("player_name") or leg.get("player") or (match or {}).get("player_name") or ""),
        "player_team": str(leg.get("player_team") or leg.get("team") or (match or {}).get("player_team") or ""),
        "opponent": str(leg.get("opponent") or leg.get("opp") or (match or {}).get("opponent") or ""),
        "event_id": str(leg.get("event_id") or leg.get("game_id") or (match or {}).get("event_id") or ""),
        "market": str(leg.get("market") or leg.get("stat_raw") or (match or {}).get("market") or ""),
        "line": _float(leg.get("line") if leg.get("line") is not None else (match or {}).get("line")),
        "side": str(leg.get("side") or leg.get("direction") or (match or {}).get("side") or "").lower(),
        "tier": str(leg.get("tier") or ""),
        "model_probability": _float(leg.get("model_probability") or leg.get("p_cal") or (match or {}).get("model_probability")),
        "actual_value": (match or {}).get("actual_value"),
        "actual_side": str((match or {}).get("actual_side") or ""),
        "result": result,
        "settlement_status": str((match or {}).get("settlement_status") or "missing_eval_leg"),
        "settlement_source": str((match or {}).get("settlement_source") or ""),
    }


class _EvalLegIndex:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._projection: dict[str, dict[str, Any]] = {}
        self._exact: dict[str, dict[str, Any]] = {}
        for row in rows:
            projection_id = str(row.get("source_projection_id") or "")
            if projection_id:
                self._projection[projection_id] = row
            key = _eval_leg_key(row)
            if key:
                self._exact[key] = row

    def match(self, leg: dict[str, Any]) -> dict[str, Any] | None:
        projection_id = str(leg.get("source_projection_id") or leg.get("projection_id") or "")
        if projection_id and projection_id in self._projection:
            return self._projection[projection_id]
        return self._exact.get(_eval_leg_key(leg))


def _eval_leg_key(row: dict[str, Any]) -> str:
    player = str(row.get("player_id") or "").strip().lower()
    if not player:
        player = _player_key(row.get("player_name") or row.get("player"))
    event = str(row.get("event_id") or row.get("game_id") or "").strip().lower()
    market = str(row.get("market") or row.get("stat_raw") or row.get("source_market") or row.get("stat") or "").strip().lower()
    side = str(row.get("side") or row.get("direction") or "").strip().lower()
    line = f"{_float(row.get('line')):.6g}"
    return "|".join((player, event, market, line, side)) if player or market else ""


def _bettingpros_context_fields(row: dict[str, Any]) -> dict[str, Any]:
    external_available = _bool(row.get("external_market_context_available"))
    return {
        "external_market_context_available": external_available,
        "market_context_source_type": str(row.get("market_context_source_type") or "").strip()
        or ("external_bettingpros_mlb_props" if external_available else "prizepicks_line_only"),
        "external_market_context_source": str(row.get("external_market_context_source") or "").strip()
        or ("bettingpros_mlb_props" if external_available else ""),
        "prizepicks_line_only_market_context": _bool(row.get("prizepicks_line_only_market_context")) or not external_available,
        "bettingpros_recommended_side": str(row.get("bettingpros_recommended_side") or "").strip().lower(),
        "bettingpros_projection_value": _float(row.get("bettingpros_projection_value")),
        "bettingpros_projection_probability": _float(row.get("bettingpros_projection_probability")),
        "bettingpros_projection_expected_value": _float(row.get("bettingpros_projection_expected_value")),
        "bettingpros_projection_diff": _float(row.get("bettingpros_projection_diff")),
        "bettingpros_streak": _int(row.get("bettingpros_streak")),
        "bettingpros_streak_type": str(row.get("bettingpros_streak_type") or "").strip().lower(),
        "bettingpros_last_5_over_rate": _float(row.get("bettingpros_last_5_over_rate")),
        "bettingpros_last_5_under_rate": _float(row.get("bettingpros_last_5_under_rate")),
        "bettingpros_last_10_over_rate": _float(row.get("bettingpros_last_10_over_rate")),
        "bettingpros_last_10_under_rate": _float(row.get("bettingpros_last_10_under_rate")),
        "bettingpros_last_20_over_rate": _float(row.get("bettingpros_last_20_over_rate")),
        "bettingpros_last_20_under_rate": _float(row.get("bettingpros_last_20_under_rate")),
        "bettingpros_season_over_rate": _float(row.get("bettingpros_season_over_rate")),
        "bettingpros_season_under_rate": _float(row.get("bettingpros_season_under_rate")),
        "bettingpros_prior_season_over_rate": _float(row.get("bettingpros_prior_season_over_rate")),
        "bettingpros_prior_season_under_rate": _float(row.get("bettingpros_prior_season_under_rate")),
    }


def _slip_leg_label(leg: dict[str, Any]) -> str:
    return "{player} {side} {market} {line:g} -> {result}".format(
        player=str(leg.get("player_name") or ""),
        side=str(leg.get("side") or "").upper(),
        market=str(leg.get("market") or ""),
        line=_float(leg.get("line")),
        result=str(leg.get("result") or ""),
    )


def _slip_summary(slips: list[dict[str, Any]]) -> dict[str, Any]:
    metric_slips = [slip for slip in slips if slip.get("result") in {"win", "loss"}]
    settled_slips = [slip for slip in slips if slip.get("result") in {"win", "loss", "push"}]
    return {
        "slip_count": len(slips),
        "settled_count": len(settled_slips),
        "metric_count": len(metric_slips),
        "win_rate": _rate(slip.get("result") == "win" for slip in metric_slips),
        "brier": _mean(slip.get("brier") for slip in metric_slips),
        "logloss": _mean(slip.get("logloss") for slip in metric_slips),
        "result_counts": _counts(slip.get("result") or "unsettled" for slip in slips),
        "family_summary": _slip_family_summary(metric_slips, slips),
    }


def _slip_family_summary(metric_slips: list[dict[str, Any]], all_slips: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    families = sorted({str(slip.get("family") or "") for slip in all_slips})
    summary = {}
    for family in families:
        family_all = [slip for slip in all_slips if str(slip.get("family") or "") == family]
        family_metric = [slip for slip in metric_slips if str(slip.get("family") or "") == family]
        summary[family] = {
            "slip_count": len(family_all),
            "metric_count": len(family_metric),
            "win_rate": _rate(slip.get("result") == "win" for slip in family_metric),
            "brier": _mean(slip.get("brier") for slip in family_metric),
            "logloss": _mean(slip.get("logloss") for slip in family_metric),
            "result_counts": _counts(slip.get("result") or "unsettled" for slip in family_all),
        }
    return summary


def _resolve_scored_legs_path(*, paths, run_id: str | None, scored_legs_path: Path | None) -> Path:
    if scored_legs_path is not None:
        candidate = scored_legs_path / "scored_legs.json" if scored_legs_path.is_dir() else scored_legs_path
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Scored legs JSON not found: {candidate}")
    elif run_id:
        for runs_dir in candidate_run_dirs(paths):
            candidate = runs_dir / run_id / "scored_legs.json"
            if candidate.exists():
                return candidate
        candidate = paths.runs / run_id / "scored_legs.json"
    else:
        for runs_dir in candidate_run_dirs(paths):
            candidate = runs_dir / "latest_scored_legs.json"
            if candidate.exists():
                return candidate
        candidate = paths.runs / "latest_scored_legs.json"
    raise FileNotFoundError(f"Scored legs JSON not found: {candidate}")


def _actual_side(actual_value: float, line: float) -> str:
    if actual_value > line:
        return "over"
    if actual_value < line:
        return "under"
    return "push"


def _result_for_side(*, side: str, actual_side: str) -> str:
    if actual_side == "push":
        return "push"
    return "win" if side == actual_side else "loss"


def _probability_path(row: dict[str, Any]) -> str:
    return "|".join(
        str(row.get(key) or "")
        for key in ("method", "simulation_kernel_version", "parameter_model_version", "calibration_version")
    )


def _row_date(row: dict[str, Any]) -> str:
    official = str(row.get("official_date") or "")
    if official:
        return official
    game_date = str(row.get("game_date") or "")
    return game_date[:10]


def _outs_from_innings(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if "." not in text:
        return int(_float(text) * 3)
    whole, fraction = text.split(".", 1)
    return _int(whole) * 3 + _int(fraction[:1])


def _player_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=EVAL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in EVAL_COLUMNS})


def _write_slip_eval_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SLIP_EVAL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in SLIP_EVAL_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _mean(values) -> float | None:
    collected = [float(value) for value in values if value not in (None, "")]
    return round(sum(collected) / len(collected), 6) if collected else None


def _rate(values) -> float | None:
    collected = [bool(value) for value in values]
    return round(sum(1 for value in collected if value) / len(collected), 6) if collected else None


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return (value,) if value else ()
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed)
    return ()


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return "" if value is None else value


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _product(values) -> float:
    result = 1.0
    for value in values:
        result *= _clamp(float(value), 0.0, 1.0)
    return result
