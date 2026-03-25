from __future__ import annotations

import argparse
import html as html_lib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if SRC_DIR.exists():
    import sys

    sys.path.insert(0, str(SRC_DIR))

from Atlas.core.share_name_key import share_name_key
from Atlas.runtime.archive_writer import archive_role_metrics_artifacts, resolve_archive_ids


API_URL = "https://craftednba.com/api/player-stats"
DEFAULT_DASHBOARD_DIR = PROJECT_ROOT / "data" / "output" / "dashboard"
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "output" / "role_metrics" / "snapshots"
PARSER_VERSION = "craftednba_api_v1"

DEFAULT_BODY = {
    "positions": ["PG", "SG", "SF", "PF", "C"],
    "ages": [18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36],
    "firstyear": None,
    "orderBy": "FGA",
    "roles": [],
    "statfilters": [],
}

DEFAULT_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": "https://craftednba.com",
    "referer": "https://craftednba.com/player-stats",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}


_FIELD_ALIASES = {
    "age": ("age",),
    "minutes_projection": ("minutes_projection", "minutes", "mp", "2025minutes"),
    "ts_pct": ("ts_pct", "ts%", "ts", "true_shooting_pct"),
    "rts_pct": ("rts_pct", "rts%", "rts", "relative_true_shooting_pct"),
    "sq": ("sq",),
    "three_par": ("three_par", "3par", "threep", "three_point_rate"),
    "r3par": ("r3par", "r3par%", "relative_three_par"),
    "ftr": ("ftr", "free_throw_rate"),
    "orb_pct": ("orb_pct", "orb%", "orb"),
    "rorb_pct": ("rorb_pct", "rorb%", "relative_orb_pct"),
    "raorb": ("raorb",),
    "drb_pct": ("drb_pct", "drb%", "drb"),
    "rdrb_pct": ("rdrb_pct", "rdrb%", "relative_drb_pct"),
    "radrb": ("radrb",),
    "stl_pct": ("stl_pct", "stl%", "stl"),
    "radtov": ("radtov",),
    "blk_pct": ("blk_pct", "blk%", "blk"),
    "tov_pct": ("tov_pct", "tov%", "tov"),
    "usg_pct": ("usg_pct", "usg%", "usg", "usage"),
    "ws": ("ws",),
    "ctov_pct": ("ctov_pct", "ctov%", "catch_and_shoot_tov_pct"),
    "bc": ("bc",),
    "load": ("load",),
    "pr": ("pr",),
    "port": ("port",),
    "plus_minus": ("plus_minus", "plus/minus", "plus minus", "plus-minus", "plusminus", "pm"),
    "role_awareness": ("role_awareness", "role awareness", "roleawareness", "ra"),
    "usage_projection": ("usage_projection", "usage projection", "usageproj"),
    "starter_flag": ("starter_flag", "starter flag", "starter", "is_starter"),
    "rotation_tier": ("rotation_tier", "rotation tier"),
    "depth_role": ("depth_role", "depth role"),
    "obpm": ("obpm",),
    "dbpm": ("dbpm",),
    "bpm": ("bpm",),
    "vorp": ("vorp",),
    "odarko": ("odarko",),
    "ddarko": ("ddarko",),
    "darko": ("darko",),
    "copm": ("copm",),
    "cdpm": ("cdpm",),
    "cpm": ("cpm",),
    "odrip": ("odrip",),
    "ddrip": ("ddrip",),
    "drip_total": ("drip_total", "drip",),
    "drip_offense": ("drip_offense", "drip offense", "drip on offense"),
    "drip_defense": ("drip_defense", "drip defense", "drip on defense"),
}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = html_lib.unescape(text)
    text = text.replace("\u00a0", " ")
    return " ".join(text.split()).strip()


def _normalize_key(value: Any) -> str:
    text = _clean_text(value).lower()
    return "".join(ch for ch in text if ch.isalnum())


def _lookup(record: dict[str, Any], *candidates: str) -> Any:
    normalized = {_normalize_key(key): value for key, value in record.items()}
    for candidate in candidates:
        key = _normalize_key(candidate)
        if key in normalized:
            return normalized[key]
    return None


def _pick(record: dict[str, Any], field_name: str) -> Any:
    candidates = _FIELD_ALIASES.get(field_name, (field_name,))
    return _lookup(record, *candidates)


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _as_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = _clean_text(value).lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("data", "rows", "result", "players", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        return [payload]

    return []


def _render_html(rows: list[dict[str, Any]]) -> str:
    columns = [
        "player",
        "team",
        "position",
        "minutes_projection",
        "usage_projection",
        "plus_minus",
        "vorp",
        "role_awareness",
        "starter_flag",
        "rotation_tier",
        "depth_role",
    ]
    header_html = "".join(f"<th>{html_lib.escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column)
            cells.append(f"<td>{html_lib.escape('' if value is None else str(value))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    table_html = f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>CraftedNBA Player Stats</title>"
        "<style>body{font-family:Arial,sans-serif;padding:24px}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;font-size:12px}th{background:#f4f4f4}"
        "</style></head><body>"
        f"<h1>CraftedNBA Player Stats</h1>{table_html}</body></html>"
    )


def _build_row(record: dict[str, Any], *, game_date: str, source_timestamp: str, source_url: str, source_rank: int) -> dict[str, Any]:
    player = _clean_text(
        _lookup(
            record,
            "player",
            "player_name",
            "name",
            "display_first_last",
            "full_name",
            "playername",
        )
    )
    team = _clean_text(_lookup(record, "team", "abbr", "abbreviation", "tm", "team_abbr", "school"))
    position = _clean_text(_lookup(record, "position", "pos", "dposition", "role", "player_position"))

    row: dict[str, Any] = {
        "player": player,
        "player_key": share_name_key(player),
        "team": team,
        "position": position,
        "game_date": game_date,
        "source_url": source_url,
        "source_timestamp": source_timestamp,
        "source_rank": source_rank,
        "snapshot_id": None,
        "fetched_at": source_timestamp,
        "html_sha256": None,
    }

    for field_name in _FIELD_ALIASES:
        if field_name in {"rotation_tier", "depth_role"}:
            row[field_name] = _pick(record, field_name)
        elif field_name == "starter_flag":
            row[field_name] = _as_bool(_pick(record, field_name))
        else:
            row[field_name] = _as_float(_pick(record, field_name))

    row.update(
        {
            "pos_size": _lookup(record, "pos_size", "pos size"),
            "height": _as_float(_lookup(record, "height")),
            "wingspan": _as_float(_lookup(record, "wingspan")),
            "weight": _as_float(_lookup(record, "weight")),
            "length": _as_float(_lookup(record, "length")),
            "crafted_opm": _as_float(_lookup(record, "craftedopm", "crafted_opm", "opm")),
            "crafted_dpm": _as_float(_lookup(record, "crafteddpm", "crafted_dpm", "dpm")),
            "crafted_warp": _as_float(_lookup(record, "craftedwarp", "crafted_warp", "warp")),
        }
    )

    return row


def _fetch_payload(timeout_s: float) -> tuple[Any, str, str]:
    request = Request(
        API_URL,
        data=json.dumps(DEFAULT_BODY).encode("utf-8"),
        headers=DEFAULT_HEADERS,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            payload_text = response.read().decode("utf-8", errors="replace")
            payload = json.loads(payload_text)
            content_type = response.headers.get("content-type", "")
            return payload, payload_text, content_type
    except HTTPError as exc:
        raise RuntimeError(f"CraftedNBA API request failed with HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"CraftedNBA API request failed: {exc.reason}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch CraftedNBA player stats and write Atlas role-metrics snapshots.")
    parser.add_argument("--game-date", required=True, help="Slate date in YYYY-MM-DD format")
    parser.add_argument("--dashboard-dir", default=str(DEFAULT_DASHBOARD_DIR))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--timeout-s", type=float, default=30.0)
    args = parser.parse_args()

    fetched_at = _now_utc_iso()
    payload, payload_text, content_type = _fetch_payload(timeout_s=args.timeout_s)
    html_sha256 = _hash_text(payload_text)
    records = _extract_records(payload)
    if not records:
        raise RuntimeError("No player records were returned by the CraftedNBA API")

    rows = [
        _build_row(record, game_date=args.game_date, source_timestamp=fetched_at, source_url=API_URL, source_rank=index + 1)
        for index, record in enumerate(records)
    ]

    snapshot_id = f"craftednba_player_stats_{args.game_date.replace('-', '')}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    dashboard_dir = Path(args.dashboard_dir).expanduser()
    snapshot_dir = Path(args.snapshot_dir).expanduser() / args.game_date
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        row["snapshot_id"] = snapshot_id
        row["html_sha256"] = html_sha256

    payload_out = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "game_date": args.game_date,
        "source_url": API_URL,
        "source_content_type": content_type,
        "fetched_at": fetched_at,
        "snapshot_id": snapshot_id,
        "html_sha256": html_sha256,
        "row_count": len(rows),
        "rows": rows,
    }

    latest_json = dashboard_dir / "role_metrics_latest.json"
    latest_html = dashboard_dir / "role_metrics_latest.html"
    manifest_path = dashboard_dir / "role_metrics_snapshot_manifest.json"

    _write_json(latest_json, payload_out)
    latest_html.write_text(_render_html(rows), encoding="utf-8")

    snap_json = snapshot_dir / f"{snapshot_id}.json"
    snap_html = snapshot_dir / f"{snapshot_id}.html"
    _write_json(snap_json, payload_out)
    snap_html.write_text(_render_html(rows), encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "game_date": args.game_date,
        "source_url": API_URL,
        "source_content_type": content_type,
        "fetched_at": fetched_at,
        "snapshot_id": snapshot_id,
        "html_sha256": html_sha256,
        "row_count": len(rows),
        "artifacts": {
            "latest_json": str(latest_json.resolve()),
            "latest_html": str(latest_html.resolve()),
            "snapshot_json": str(snap_json.resolve()),
            "snapshot_html": str(snap_html.resolve()),
        },
    }
    _write_json(manifest_path, manifest)

    try:
        archive_role_metrics_artifacts(
            repo_root=PROJECT_ROOT,
            role_metrics_latest_json=latest_json,
            role_metrics_latest_html=latest_html,
            role_metrics_manifest=manifest_path,
            ids=resolve_archive_ids(),
        )
    except Exception as exc:
        print(f"[CRAFTEDNBA] role-metrics archive skipped: {exc!r}")

    print(f"[CRAFTEDNBA] rows={len(rows)} snapshot_id={snapshot_id}")
    print(f"[CRAFTEDNBA] wrote: {latest_json}")
    print(f"[CRAFTEDNBA] wrote: {latest_html}")
    print(f"[CRAFTEDNBA] wrote: {manifest_path}")
    print(f"[CRAFTEDNBA] wrote: {snap_json}")
    print(f"[CRAFTEDNBA] wrote: {snap_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())