"""Runtime artifact writer for MLB StatsAPI transaction context."""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.market_context import latest_engine_board_path
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

TRANSACTION_CONTEXT_VERSION = "statsapi_transaction_context_v0"
DEFAULT_LOOKBACK_DAYS = 14

TRANSACTION_CONTEXT_COLUMNS = (
    "run_id",
    "source_projection_id",
    "event_id",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "game_date",
    "market",
    "line",
    "tier",
    "transaction_source_available",
    "transaction_context_available",
    "recent_transaction_count",
    "recent_callup_count",
    "recent_option_count",
    "recent_injury_status_count",
    "last_transaction_date",
    "last_transaction_type_code",
    "last_transaction_type_desc",
    "last_transaction_description",
    "transaction_volatility_score",
    "transaction_context_flags",
)


def build_transaction_context_result(
    *,
    engine_board_path: Path | None = None,
    roster_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> RuntimeCommandResult:
    manifest = build_transaction_context_artifacts(
        engine_board_path=engine_board_path,
        roster_context_path=roster_context_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
        lookback_days=lookback_days,
    )
    lines = [
        "Built MLB transaction context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  transaction_source_row_count: {manifest['transaction_source_row_count']}",
        f"  row_count: {manifest['row_count']}",
        f"  source_available_rate: {manifest['source_available_rate']}",
        f"  recent_transaction_rate: {manifest['recent_transaction_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
    ]
    return RuntimeCommandResult(name="build_transaction_context", payload=manifest, lines=tuple(lines))


def build_transaction_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    roster_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    source_path = engine_board_path or latest_engine_board_path(root=root)
    engine_board = _load_json(source_path)
    source_run_id = str(engine_board.get("run_id") or source_path.parent.name)
    source_rows = [row for row in engine_board.get("rows", []) if isinstance(row, dict)]
    filtered_rows = _filter_rows_by_date(source_rows, game_date)
    resolved_run_id = run_id or game_date or source_run_id

    transaction_rows = _load_staged_jsonl(paths.staged / "statsapi_transactions", "statsapi_transactions.jsonl")
    roster_rows = _load_context_rows(roster_context_path)
    transaction_index = _index_transactions(transaction_rows)

    rows = [
        _transaction_context_row(
            row,
            run_id=resolved_run_id,
            transactions=_match_transactions(
                row,
                transaction_index,
                roster_row=roster_rows.get(_matchup_key(row)),
                lookback_days=lookback_days,
            ),
            source_available=bool(transaction_rows),
        )
        for row in filtered_rows
    ]

    output_dir = paths.features / "transaction_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "transaction_context.csv"
    json_path = output_dir / "transaction_context.json"
    manifest_path = output_dir / "transaction_context_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "transaction_context_version": TRANSACTION_CONTEXT_VERSION,
                "row_count": len(rows),
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "source_run_id": source_run_id,
        "source_engine_board_path": str(source_path),
        "roster_context_path": str(roster_context_path) if roster_context_path else "",
        "game_date": game_date or "",
        "lookback_days": lookback_days,
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "transaction_context_version": TRANSACTION_CONTEXT_VERSION,
        "transaction_source_row_count": len(transaction_rows),
        "source_available_rate": _true_rate(row["transaction_source_available"] for row in rows),
        "recent_transaction_rate": _true_rate(row["transaction_context_available"] for row in rows),
        "transaction_context_flag_counts": _flag_counts(row["transaction_context_flags"] for row in rows),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "transaction_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "transaction_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "transaction_context" / "latest_manifest.json"),
        "columns": list(TRANSACTION_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "transaction_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "transaction_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "transaction_context" / "latest_manifest.json")
    return manifest


def _transaction_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    transactions: list[dict[str, Any]],
    source_available: bool,
) -> dict[str, Any]:
    transactions = sorted(transactions, key=lambda item: _date_key(item.get("date") or item.get("effective_date")))
    last = transactions[-1] if transactions else {}
    callups = [item for item in transactions if _bool(item.get("is_callup"))]
    options = [item for item in transactions if _bool(item.get("is_optioned"))]
    injury = [item for item in transactions if _bool(item.get("is_injury_status"))]
    flags: list[str] = []
    if not source_available:
        flags.append("no_statsapi_transaction_snapshot_available")
    elif not transactions:
        flags.append("no_recent_statsapi_transactions")
    else:
        flags.append("recent_statsapi_transaction_match")
        if callups:
            flags.append("recent_callup_or_contract_selected")
        if options:
            flags.append("recent_option_or_assignment")
        if injury:
            flags.append("recent_injury_status_transaction")
    return {
        "run_id": run_id,
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "game_date": str(row.get("game_date") or ""),
        "market": str(row.get("market") or ""),
        "line": _float(row.get("line")),
        "tier": str(row.get("tier") or "STANDARD").upper() or "STANDARD",
        "transaction_source_available": source_available,
        "transaction_context_available": bool(transactions),
        "recent_transaction_count": len(transactions),
        "recent_callup_count": len(callups),
        "recent_option_count": len(options),
        "recent_injury_status_count": len(injury),
        "last_transaction_date": str(last.get("date") or last.get("effective_date") or ""),
        "last_transaction_type_code": str(last.get("type_code") or ""),
        "last_transaction_type_desc": str(last.get("type_desc") or ""),
        "last_transaction_description": str(last.get("description") or ""),
        "transaction_volatility_score": _transaction_volatility_score(callups, options, injury),
        "transaction_context_flags": tuple(flags),
    }


def _index_transactions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_person_id: dict[int, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        person_id = _int(row.get("person_id"))
        if person_id:
            by_person_id.setdefault(person_id, []).append(row)
        name_key = _name_key(row.get("player_name"))
        if name_key:
            by_name.setdefault(name_key, []).append(row)
    return {"by_person_id": by_person_id, "by_name": by_name}


def _match_transactions(
    row: dict[str, Any],
    index: dict[str, Any],
    *,
    roster_row: dict[str, Any] | None,
    lookback_days: int,
) -> list[dict[str, Any]]:
    game_date = _parse_date(row.get("game_date"))
    if not game_date:
        return []
    person_id = _int(roster_row.get("statsapi_person_id")) if roster_row else 0
    candidates = list(index["by_person_id"].get(person_id, [])) if person_id else []
    if not candidates:
        candidates = list(index["by_name"].get(_name_key(row.get("player_name")), []))
    start = game_date - timedelta(days=max(0, lookback_days))
    matched: list[dict[str, Any]] = []
    for item in candidates:
        transaction_date = _parse_date(item.get("date") or item.get("effective_date"))
        if transaction_date and start <= transaction_date <= game_date:
            matched.append(item)
    return matched


def _load_staged_jsonl(root: Path, rows_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for path in sorted(root.glob(f"*/{rows_name}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
        rows.extend(_load_jsonl(path))
    return rows


def _load_context_rows(path: Path | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return {}
    return {_matchup_key(row): row for row in rows if isinstance(row, dict)}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _transaction_volatility_score(
    callups: list[dict[str, Any]],
    options: list[dict[str, Any]],
    injury: list[dict[str, Any]],
) -> float:
    score = 0.25 * len(callups) + 0.20 * len(options) + 0.35 * len(injury)
    return round(_clamp(score, 0.0, 1.0), 6)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=TRANSACTION_CONTEXT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in TRANSACTION_CONTEXT_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _matchup_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("source_projection_id") or "").strip(),
        str(row.get("market") or "").strip(),
        _line_key(row.get("line")),
        str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
    )


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _date_key(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _parse_date(value: Any) -> date | None:
    key = _date_key(value)
    if not key:
        return None
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _flag_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for flag in _tuple_flags(value):
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return (value,)
            return _tuple_flags(decoded)
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
