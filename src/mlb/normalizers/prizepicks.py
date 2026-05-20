"""Normalization helpers for MLB source data."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.domain.markets import COMBO_MARKETS, PRIZEPICKS_MARKET_ALIASES, SUPPORTED_MARKETS
from mlb.normalizers.slate_dates import local_slate_date
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload


def normalize_player_name(value: str) -> str:
    name = re.sub(r"\s+", " ", value or "").strip()
    return name


def normalize_market(value: str) -> str:
    market = PRIZEPICKS_MARKET_ALIASES.get(value)
    if market:
        return market
    key = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return key


def is_supported_market(value: str) -> bool:
    return normalize_market(value) in SUPPORTED_MARKETS


@dataclass(frozen=True)
class BoardNormalizationResult:
    run_id: str
    snapshot_id: str
    rows: tuple[dict[str, Any], ...]
    rejects: tuple[dict[str, Any], ...]
    output_dir: Path | None = None
    metadata: dict[str, Any] | None = None


def normalize_prizepicks_board(
    payload: dict[str, Any],
    *,
    snapshot_id: str = "",
    pulled_at_utc: str = "",
    run_id: str | None = None,
) -> BoardNormalizationResult:
    """Convert a PrizePicks MLB payload into canonical candidate rows."""

    included = payload.get("included", []) or []
    players_by_id: dict[str, dict[str, Any]] = {}
    games_by_id: dict[str, dict[str, Any]] = {}

    for item in included:
        item_id = _clean_str(item.get("id"))
        item_type = _clean_str(item.get("type"))
        if not item_id:
            continue
        if item_type in {"new_player", "player"}:
            players_by_id[item_id] = item.get("attributes", {}) or {}
        elif item_type == "game":
            games_by_id[item_id] = item.get("attributes", {}) or {}

    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    resolved_run_id = run_id or snapshot_id or _default_run_id()

    for item in payload.get("data", []) or []:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes", {}) or {}
        rel = item.get("relationships", {}) or {}
        projection_id = _clean_str(item.get("id"))
        source_market = _clean_str(
            attr.get("stat_type") or attr.get("stat_type_display") or attr.get("stat_display_name")
        )
        market = normalize_market(source_market)
        player_id = _relationship_id(rel, "new_player") or _relationship_id(rel, "player")
        player = players_by_id.get(player_id, {})
        player_name = normalize_player_name(
            _clean_str(player.get("display_name") or player.get("name") or attr.get("name"))
        )
        game_id = _relationship_id(rel, "game") or _clean_str(attr.get("game_id"))
        game = games_by_id.get(game_id, {})
        start_time_utc = _to_utc_iso(game.get("start_time") or attr.get("start_time"))
        player_team = _clean_str(player.get("team") or attr.get("description"))
        opponent = _opponent_from_game(game, player_team)
        line = _to_float(attr.get("line_score"))

        reject_reason = _projection_reject_reason(
            player_name=player_name,
            market=market,
            source_market=source_market,
            line=line,
        )
        if reject_reason:
            rejects.append(
                {
                    "snapshot_id": snapshot_id,
                    "source": "prizepicks",
                    "source_projection_id": projection_id,
                    "reason": reject_reason,
                    "player_name": player_name,
                    "source_market": source_market,
                    "market": market,
                    "line": attr.get("line_score"),
                }
            )
            continue

        rows.append(
            {
                "snapshot_id": snapshot_id,
                "source": "prizepicks",
                "source_projection_id": projection_id,
                "event_id": game_id,
                "league": "MLB",
                "game_date": _slate_date_from_utc_iso(start_time_utc),
                "start_time_utc": start_time_utc,
                "player_id": player_id,
                "player_name": player_name,
                "player_team": player_team,
                "opponent": opponent,
                "market": market,
                "source_market": source_market,
                "line": line,
                "side": None,
                "player_position": _clean_str(player.get("position")),
                "odds": None,
                "book": None,
                "platform": "PrizePicks",
                "is_live": bool(attr.get("is_live") or attr.get("in_game")),
                "is_combo": bool(player.get("combo")) or market in COMBO_MARKETS,
                "combo_player_ids": tuple(),
                "status": _clean_str(attr.get("status") or "active"),
                "tier": _tier_from_odds_type(attr.get("odds_type")),
                "updated_at": _clean_str(attr.get("updated_at")),
                "pulled_at_utc": pulled_at_utc,
            }
        )

    return BoardNormalizationResult(
        run_id=resolved_run_id,
        snapshot_id=snapshot_id,
        rows=tuple(rows),
        rejects=tuple(rejects),
    )


def write_prizepicks_board_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> BoardNormalizationResult:
    """Normalize a raw PrizePicks snapshot and write staged board artifacts."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    result = normalize_prizepicks_board(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or ""),
        pulled_at_utc=str(manifest.get("pulled_at_utc") or ""),
        run_id=run_id,
    )
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "board" / result.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_path = output_dir / "normalized_board.jsonl"
    rejects_path = output_dir / "rejected_board.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    _write_jsonl(normalized_path, result.rows)
    _write_jsonl(rejects_path, result.rejects)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": result.run_id,
                "snapshot_id": result.snapshot_id,
                "source": "prizepicks",
                "normalized_count": len(result.rows),
                "rejected_count": len(result.rejects),
                "normalized_path": str(normalized_path),
                "rejects_path": str(rejects_path),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return BoardNormalizationResult(
        run_id=result.run_id,
        snapshot_id=result.snapshot_id,
        rows=result.rows,
        rejects=result.rejects,
        output_dir=output_dir,
        metadata=result.metadata,
    )


def normalize_prizepicks_csv_file(
    csv_path: Path,
    *,
    snapshot_id: str = "",
    pulled_at_utc: str = "",
    run_id: str | None = None,
) -> BoardNormalizationResult:
    """Convert a GitHub-imported PrizePicks CSV export into canonical board rows."""

    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    seen_projection_ids: set[str] = set()
    source_row_count = 0
    mlb_row_count = 0
    skipped_non_mlb_count = 0
    duplicate_projection_count = 0
    resolved_pulled_at = _to_utc_iso(pulled_at_utc)

    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for raw_row in reader:
            source_row_count += 1
            if _clean_str(raw_row.get("league")).upper() != "MLB":
                skipped_non_mlb_count += 1
                continue

            mlb_row_count += 1
            projection_id = _clean_str(raw_row.get("projection_id"))
            dedupe_key = projection_id or _csv_row_key(raw_row)
            if dedupe_key in seen_projection_ids:
                duplicate_projection_count += 1
                continue
            seen_projection_ids.add(dedupe_key)

            row_pulled_at = _to_utc_iso(raw_row.get("scraped_at")) or resolved_pulled_at
            if row_pulled_at and not resolved_pulled_at:
                resolved_pulled_at = row_pulled_at

            source_market = _clean_str(raw_row.get("stat_type"))
            market = normalize_market(source_market)
            player_name = normalize_player_name(_clean_str(raw_row.get("player")))
            start_time_utc = _to_utc_iso(raw_row.get("start_time"))
            player_team = _clean_str(raw_row.get("team")).upper()
            opponent = _clean_str(raw_row.get("description")).upper()
            line = _to_float(raw_row.get("line"))

            reject_reason = _projection_reject_reason(
                player_name=player_name,
                market=market,
                source_market=source_market,
                line=line,
            )
            if reject_reason:
                rejects.append(
                    {
                        "snapshot_id": snapshot_id,
                        "source": "prizepicks",
                        "source_projection_id": projection_id,
                        "reason": reject_reason,
                        "player_name": player_name,
                        "source_market": source_market,
                        "market": market,
                        "line": raw_row.get("line"),
                    }
                )
                continue

            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "source": "prizepicks",
                    "source_projection_id": projection_id,
                    "event_id": _csv_event_id(
                        game_date=_slate_date_from_utc_iso(start_time_utc),
                        start_time_utc=start_time_utc,
                        player_team=player_team,
                        opponent=opponent,
                    ),
                    "league": "MLB",
                    "game_date": _slate_date_from_utc_iso(start_time_utc),
                    "start_time_utc": start_time_utc,
                    "player_id": "",
                    "player_name": player_name,
                    "player_team": player_team,
                    "opponent": opponent,
                    "market": market,
                    "source_market": source_market,
                    "line": line,
                    "side": None,
                    "player_position": _clean_str(raw_row.get("position")),
                    "odds": None,
                    "book": None,
                    "platform": "PrizePicks",
                    "is_live": False,
                    "is_combo": market in COMBO_MARKETS,
                    "combo_player_ids": tuple(),
                    "status": "active",
                    "tier": _tier_from_odds_type(raw_row.get("odds_type")),
                    "updated_at": row_pulled_at,
                    "pulled_at_utc": row_pulled_at,
                    "import_source": "github_csv",
                    "source_csv_path": str(csv_path),
                }
            )

    resolved_snapshot_id = snapshot_id or _csv_snapshot_id(csv_path, resolved_pulled_at)
    resolved_run_id = run_id or resolved_snapshot_id
    if not snapshot_id:
        for row in rows:
            row["snapshot_id"] = resolved_snapshot_id
        for reject in rejects:
            reject["snapshot_id"] = resolved_snapshot_id
    metadata = {
        "source_csv_path": str(csv_path),
        "source_row_count": source_row_count,
        "mlb_row_count": mlb_row_count,
        "skipped_non_mlb_count": skipped_non_mlb_count,
        "duplicate_projection_count": duplicate_projection_count,
        "deduped_mlb_projection_count": len(seen_projection_ids),
        "pulled_at_utc": resolved_pulled_at,
    }
    return BoardNormalizationResult(
        run_id=resolved_run_id,
        snapshot_id=resolved_snapshot_id,
        rows=tuple(rows),
        rejects=tuple(rejects),
        metadata=metadata,
    )


def write_prizepicks_csv_normalization(
    csv_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> BoardNormalizationResult:
    """Normalize a GitHub-imported PrizePicks CSV export and write staged board artifacts."""

    result = normalize_prizepicks_csv_file(csv_path, run_id=run_id)
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "board" / result.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_path = output_dir / "normalized_board.jsonl"
    rejects_path = output_dir / "rejected_board.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    _write_jsonl(normalized_path, result.rows)
    _write_jsonl(rejects_path, result.rejects)
    manifest = {
        "run_id": result.run_id,
        "snapshot_id": result.snapshot_id,
        "source": "prizepicks",
        "import_source": "github_csv",
        "normalized_count": len(result.rows),
        "rejected_count": len(result.rejects),
        "normalized_path": str(normalized_path),
        "rejects_path": str(rejects_path),
    }
    manifest.update(result.metadata or {})
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return BoardNormalizationResult(
        run_id=result.run_id,
        snapshot_id=result.snapshot_id,
        rows=result.rows,
        rejects=result.rejects,
        output_dir=output_dir,
        metadata=result.metadata,
    )


def _write_jsonl(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _projection_reject_reason(*, player_name: str, market: str, source_market: str, line: float | None) -> str:
    if not player_name:
        return "missing_player"
    if not source_market:
        return "missing_market"
    if market not in SUPPORTED_MARKETS:
        return "unsupported_market"
    if line is None:
        return "missing_or_invalid_line"
    return ""


def _relationship_id(relationships: dict[str, Any], name: str) -> str:
    return _clean_str((((relationships.get(name) or {}).get("data") or {}).get("id")))


def _opponent_from_game(game: dict[str, Any], team: str) -> str:
    teams = ((game.get("metadata") or {}).get("game_info") or {}).get("teams") or {}
    home = _clean_str((teams.get("home") or {}).get("abbreviation"))
    away = _clean_str((teams.get("away") or {}).get("abbreviation"))
    if team == home:
        return away
    if team == away:
        return home
    return ""


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_utc_iso(value: Any) -> str:
    raw = _clean_str(value)
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _slate_date_from_utc_iso(value: Any) -> str:
    return local_slate_date(value)


def _tier_from_odds_type(value: Any) -> str:
    odds_type = _clean_str(value).upper()
    if "DEMON" in odds_type:
        return "DEMON"
    if "GOBLIN" in odds_type:
        return "GOBLIN"
    return "STANDARD"


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _default_run_id() -> str:
    return f"board_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _csv_row_key(row: dict[str, Any]) -> str:
    return "|".join(
        _clean_str(row.get(field))
        for field in ("player", "team", "description", "stat_type", "line", "start_time", "odds_type")
    )


def _csv_event_id(*, game_date: str, start_time_utc: str, player_team: str, opponent: str) -> str:
    teams = "-".join(sorted(team for team in (player_team, opponent) if team))
    pieces = ["csv"]
    if game_date:
        pieces.append(game_date)
    if teams:
        pieces.append(teams)
    if start_time_utc:
        pieces.append(start_time_utc)
    return ":".join(pieces)


def _csv_snapshot_id(csv_path: Path, pulled_at_utc: str) -> str:
    if pulled_at_utc:
        parsed = _to_snapshot_timestamp(pulled_at_utc)
        if parsed:
            return f"github_prizepicks_csv_{parsed}"
    match = re.search(r"prizepicks_(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})Z", csv_path.name)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return f"github_prizepicks_csv_{year}{month}{day}T{hour}{minute}{second}Z"
    return f"github_prizepicks_csv_{csv_path.stem}"


def _to_snapshot_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
