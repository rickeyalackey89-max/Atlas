"""Normalize DraftKings Pick6 MLB rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.fetchers.draftkings import DRAFTKINGS_MLB_PICK6_SOURCE
from mlb.normalizers.prizepicks import normalize_player_name
from mlb.normalizers.slate_dates import local_slate_date
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

PICK6_MARKET_ALIASES = {
    "Batter Fantasy Points": "hitter_fantasy_score",
    "Hitter Fantasy Points": "hitter_fantasy_score",
    "Pitcher Fantasy Points": "pitcher_fantasy_score",
    "Hits + Runs + RBIs": "hits_runs_rbis",
    "Strikeouts Thrown": "pitcher_strikeouts",
    "Total Bases (From Hits)": "total_bases",
    "Home Runs": "home_runs",
    "Doubles": "doubles",
    "Hits": "hits",
    "Stolen Bases": "stolen_bases",
}


def normalize_draftkings_pick6(payload: dict[str, Any], *, snapshot_id: str = "", pulled_at_utc: str = "") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for group in payload.get("category_responses", []) or []:
        pick_group_id = group.get("pick_group_id")
        pick_group_state = str(group.get("pick_group_state") or "")
        for category in group.get("categories", []) or []:
            category_payload = category.get("payload") or {}
            category_id = int(category.get("category_id") or category_payload.get("pickCategoryId") or 0)
            market_by_id = category_payload.get("pickSixMarketById") or {}
            entity_by_id = category_payload.get("entityInfoByDkId") or {}
            competition_by_id = category_payload.get("competitionById") or {}
            team_by_id = category_payload.get("displayTeamById") or {}
            category_name = str(((category_payload.get("pickCategoryById") or {}).get(str(category_id)) or {}).get("categoryName") or "")
            for pickcard in (category_payload.get("pickCardByPickableId") or {}).values():
                if not isinstance(pickcard, dict):
                    continue
                entity = (pickcard.get("entities") or [{}])[0]
                dk_id = str(entity.get("dkId") or "")
                comp_id = str((entity.get("compIds") or [""])[0])
                entity_info = entity_by_id.get(dk_id) or {}
                competition = competition_by_id.get(comp_id) or {}
                start_time = str(competition.get("startTime") or "")
                player_name = normalize_player_name(str(entity_info.get("fullName") or entity_info.get("name") or ""))
                team_context = ((competition.get("entityCompByDkId") or {}).get(dk_id) or {})
                home_team, away_team, player_team, opponent = _teams(competition, team_context, team_by_id)
                for market_row in pickcard.get("activePickableMarkets", []) or []:
                    source_market = str((market_by_id.get(str(market_row.get("pickSixMarketId"))) or {}).get("name") or "")
                    market = PICK6_MARKET_ALIASES.get(source_market)
                    if not market:
                        rejects.append(_reject(snapshot_id, pickcard, market_row, source_market, "unsupported_market"))
                        continue
                    line = _to_float(market_row.get("targetValue"))
                    if not player_name or line is None:
                        rejects.append(_reject(snapshot_id, pickcard, market_row, source_market, "missing_player_or_line"))
                        continue
                    key = (
                        pick_group_id,
                        pickcard.get("pickableId"),
                        market_row.get("pickableMarketId"),
                        comp_id,
                        dk_id,
                        market,
                        line,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "snapshot_id": snapshot_id,
                            "source": DRAFTKINGS_MLB_PICK6_SOURCE,
                            "pick_group_id": pick_group_id,
                            "pick_group_state": pick_group_state,
                            "pick_category_id": category_id,
                            "pick_category_name": category_name,
                            "pickable_id": pickcard.get("pickableId"),
                            "pickable_market_id": market_row.get("pickableMarketId"),
                            "pick_six_market_id": market_row.get("pickSixMarketId"),
                            "source_market": source_market,
                            "market": market,
                            "line": line,
                            "player_dk_id": dk_id,
                            "player_name": player_name,
                            "player_norm": player_name.lower(),
                            "competition_id": comp_id,
                            "game_date": local_slate_date(start_time, fallback=start_time[:10]),
                            "commence_time": start_time,
                            "home_team": home_team,
                            "away_team": away_team,
                            "player_team": player_team,
                            "opponent": opponent,
                            "position": str(team_context.get("position") or ""),
                            "is_live": bool(market_row.get("isLive")),
                            "is_paused": bool(market_row.get("isPaused")),
                            "promo_pick_type_id": market_row.get("promoPickTypeId"),
                            "active_selections": market_row.get("activeSelections") or [],
                            "pulled_at_utc": pulled_at_utc,
                        }
                    )

    return {
        "snapshot_id": snapshot_id,
        "source": DRAFTKINGS_MLB_PICK6_SOURCE,
        "row_count": len(rows),
        "rejected_count": len(rejects),
        "rows": rows,
        "rejects": rejects,
    }


def write_draftkings_pick6_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or DRAFTKINGS_MLB_PICK6_SOURCE)
    normalized = normalize_draftkings_pick6(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or ""),
        pulled_at_utc=str(manifest.get("pulled_at_utc") or ""),
    )
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / DRAFTKINGS_MLB_PICK6_SOURCE / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "draftkings_pick6_props.jsonl"
    compatible_rows_path = output_dir / "oddsapi_props.jsonl"
    rejects_path = output_dir / "draftkings_pick6_rejected.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    _write_jsonl(rows_path, normalized["rows"])
    compatible_rows = _to_oddsapi_compatible_rows(normalized["rows"])
    _write_jsonl(compatible_rows_path, compatible_rows)
    _write_jsonl(rejects_path, normalized["rejects"])
    written = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": DRAFTKINGS_MLB_PICK6_SOURCE,
        "row_count": normalized["row_count"],
        "compatible_row_count": len(compatible_rows),
        "rejected_count": normalized["rejected_count"],
        "rows_path": str(rows_path),
        "compatible_rows_path": str(compatible_rows_path),
        "rejects_path": str(rejects_path),
        "output_dir": str(output_dir),
        "compatible_artifact": "oddsapi_props.jsonl",
    }
    manifest_path.write_text(json.dumps(written, indent=2, sort_keys=True), encoding="utf-8")
    return written


def _teams(competition: dict[str, Any], team_context: dict[str, Any], team_by_id: dict[str, Any]) -> tuple[str, str, str, str]:
    home_id = str(competition.get("homeTeamId") or "")
    away_id = str(competition.get("awayTeamId") or "")
    player_team_id = str(team_context.get("teamId") or "")
    home = str((team_by_id.get(home_id) or {}).get("name") or "")
    away = str((team_by_id.get(away_id) or {}).get("name") or "")
    player_team = str((team_by_id.get(player_team_id) or {}).get("name") or "")
    opponent = ""
    if player_team_id and player_team_id == home_id:
        opponent = away
    elif player_team_id and player_team_id == away_id:
        opponent = home
    return home, away, player_team, opponent


def _reject(snapshot_id: str, pickcard: dict[str, Any], market_row: dict[str, Any], source_market: str, reason: str) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "pickable_id": pickcard.get("pickableId"),
        "pickable_market_id": market_row.get("pickableMarketId"),
        "pick_six_market_id": market_row.get("pickSixMarketId"),
        "source_market": source_market,
        "reason": reason,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _to_oddsapi_compatible_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compatible: list[dict[str, Any]] = []
    for row in rows:
        compatible.append(
            {
                "snapshot_id": str(row.get("snapshot_id") or ""),
                "source": DRAFTKINGS_MLB_PICK6_SOURCE,
                "event_id": f"draftkings_pick6_{row.get('competition_id') or ''}",
                "source_event_id": str(row.get("competition_id") or ""),
                "sport_key": "baseball_mlb",
                "league": "MLB",
                "game_date": str(row.get("game_date") or ""),
                "commence_time": str(row.get("commence_time") or ""),
                "home_team": str(row.get("home_team") or ""),
                "away_team": str(row.get("away_team") or ""),
                "player_id": str(row.get("player_dk_id") or ""),
                "player_name": str(row.get("player_name") or ""),
                "player_norm": str(row.get("player_norm") or "").lower(),
                "player_team": str(row.get("player_team") or ""),
                "market": str(row.get("market") or ""),
                "source_market": str(row.get("source_market") or ""),
                "source_market_id": row.get("pick_six_market_id"),
                "line": _to_float(row.get("line")) or 0.0,
                "over_prob": 0.5,
                "under_prob": 0.5,
                "n_books": 1,
                "books": [
                    {
                        "book_id": 12,
                        "book_key": "draftkings_pick6",
                        "book_title": "DraftKings Pick6",
                        "book_last_update": str(row.get("pulled_at_utc") or ""),
                        "source_market": str(row.get("source_market") or ""),
                        "over_price": 0,
                        "under_price": 0,
                        "over_prob": 0.5,
                        "under_prob": 0.5,
                        "line": _to_float(row.get("line")) or 0.0,
                        "price_model": "line_only_pick6",
                    }
                ],
                "pulled_at_utc": str(row.get("pulled_at_utc") or ""),
                "snapshot_timestamp": str(row.get("pulled_at_utc") or ""),
                "draftkings_pick6": {
                    "pick_group_id": row.get("pick_group_id"),
                    "pick_group_state": row.get("pick_group_state"),
                    "pick_category_id": row.get("pick_category_id"),
                    "pick_category_name": row.get("pick_category_name"),
                    "pickable_id": row.get("pickable_id"),
                    "pickable_market_id": row.get("pickable_market_id"),
                    "pick_six_market_id": row.get("pick_six_market_id"),
                    "promo_pick_type_id": row.get("promo_pick_type_id"),
                    "is_live": bool(row.get("is_live")),
                    "is_paused": bool(row.get("is_paused")),
                    "line_only_context": True,
                },
            }
        )
    return compatible


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
