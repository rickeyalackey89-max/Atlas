from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

from Atlas.core.share_name_key import share_name_key
from Atlas.runtime.archive_writer import archive_role_metrics_artifacts, resolve_archive_ids


DEFAULT_DASHBOARD_DIR = PROJECT_ROOT / "data" / "output" / "dashboard"
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "output" / "role_metrics" / "snapshots"
PARSER_VERSION = "1"

_HEADER_FIELD_MAP = {
    "age": "age",
    "mp": "minutes_projection",
    "ts%": "ts_pct",
    "rts%": "rts_pct",
    "sq": "sq",
    "3par": "three_par",
    "r3par": "r3par",
    "ftr": "ftr",
    "orb%": "orb_pct",
    "rorb%": "rorb_pct",
    "raorb": "raorb",
    "drb%": "drb_pct",
    "rdrb%": "rdrb_pct",
    "radrb": "radrb",
    "stl%": "stl_pct",
    "radtov": "radtov",
    "blk%": "blk_pct",
    "tov%": "tov_pct",
    "usg%": "usg_pct",
    "ws": "ws",
    "ctov%": "ctov_pct",
    "bc": "bc",
    "load": "load",
    "pr": "pr",
    "port": "port",
    "plus/minus": "plus_minus",
    "plus minus": "plus_minus",
    "plus-minus": "plus_minus",
    "plusminus": "plus_minus",
    "role awareness": "role_awareness",
    "role_awareness": "role_awareness",
    "usage projection": "usage_projection",
    "usage_projection": "usage_projection",
    "starter flag": "starter_flag",
    "starter_flag": "starter_flag",
    "rotation tier": "rotation_tier",
    "rotation_tier": "rotation_tier",
    "depth role": "depth_role",
    "depth_role": "depth_role",
    "obpm": "obpm",
    "dbpm": "dbpm",
    "bpm": "bpm",
    "vorp": "vorp",
    "odarko": "odarko",
    "ddarko": "ddarko",
    "darko": "darko",
    "copm": "copm",
    "cdpm": "cdpm",
    "cpm": "cpm",
    "odrip": "odrip",
    "ddrip": "ddrip",
    "drip": "drip_total",
    "drip on offense": "drip_offense",
    "drip offense": "drip_offense",
    "drip on defense": "drip_defense",
    "drip defense": "drip_defense",
}


@dataclass(frozen=True)
class RoleMetricsSnapshot:
    game_date: str
    source_url: str
    fetched_at: str
    snapshot_id: str
    html_sha256: str
    row_count: int
    rows: list[dict[str, Any]]


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = html_lib.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_tags(fragment: str) -> str:
    return _clean_text(fragment)


def _to_float(value: Any) -> Optional[float]:
    text = _strip_tags(value if isinstance(value, str) else str(value))
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _read_html_from_source(html_path: Optional[Path], url: Optional[str]) -> tuple[str, str]:
    if html_path is not None:
        html_text = html_path.read_text(encoding="utf-8", errors="ignore")
        source_url = f"file://{html_path.resolve()}"
        return html_text, source_url

    if url:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text, url

    raise RuntimeError("Provide either --html-path or --url")


def _extract_anchor_text(fragment: str) -> str:
    match = re.search(r"<a[^>]*>(.*?)</a>", fragment, flags=re.I | re.S)
    return _strip_tags(match.group(1)) if match else _strip_tags(fragment)


def _extract_span_text(fragment: str) -> str:
    match = re.search(r"<span[^>]*>(.*?)</span>", fragment, flags=re.I | re.S)
    return _strip_tags(match.group(1)) if match else ""


def _parse_team_position(fragment: str) -> tuple[str, str]:
    text = _extract_span_text(fragment)
    match = re.search(r"([A-Z]{2,3})\s*\|\s*([A-Z0-9/+-]+)", text)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip()


def _normalize_header(header: Any) -> str:
    text = _clean_text(header).lower()
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _map_header(header: Any) -> str | None:
    key = _normalize_header(header)
    if not key:
        return None
    if key in _HEADER_FIELD_MAP:
        return _HEADER_FIELD_MAP[key]
    if "drip" in key and "offense" in key:
        return "drip_offense"
    if "drip" in key and "defense" in key:
        return "drip_defense"
    if key == "drip":
        return "drip_total"
    if key == "3par":
        return "three_par"
    return None


def _parse_rows(html_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tr_pattern = re.compile(r"<tr\b[^>]*>(.*?)</tr>", flags=re.I | re.S)
    td_pattern = re.compile(r"<td\b[^>]*>(.*?)</td>", flags=re.I | re.S)
    th_pattern = re.compile(r"<th\b[^>]*>(.*?)</th>", flags=re.I | re.S)

    current_headers: list[str | None] = []
    fallback_fields = [
        "age",
        "minutes_projection",
        "height",
        "wingspan",
        "weight",
        "length",
        "pos_size",
    ]

    for tr_match in tr_pattern.finditer(html_text):
        tr_html = tr_match.group(0)
        if "headingRow" in tr_html:
            continue

        header_cells = th_pattern.findall(tr_match.group(1))
        if header_cells:
            mapped_headers = [_map_header(cell) for cell in header_cells]
            if any(mapped_headers):
                current_headers = mapped_headers
            continue

        cells = td_pattern.findall(tr_match.group(1))
        if len(cells) < 2:
            continue

        first_cell_text = _strip_tags(cells[0])
        if not first_cell_text or first_cell_text == "#":
            continue

        player_name = _extract_anchor_text(cells[1])
        if not player_name:
            continue

        team, position = _parse_team_position(cells[1])
        record: dict[str, Any] = {
            "source_rank": int(float(first_cell_text)) if first_cell_text.isdigit() else None,
            "player": player_name,
            "player_key": share_name_key(player_name),
            "team": team,
            "position": position,
        }

        header_fields = current_headers[2:] if len(current_headers) >= 2 else []
        if header_fields and len(header_fields) >= len(cells) - 2:
            for idx, field in enumerate(header_fields[: len(cells) - 2], start=2):
                if not field:
                    continue
                raw = cells[idx] if idx < len(cells) else ""
                if field == "pos_size":
                    record[field] = _strip_tags(raw) or None
                elif field in {"starter_flag", "rotation_tier", "depth_role", "role_awareness"}:
                    record[field] = _strip_tags(raw) or None
                else:
                    record[field] = _to_float(raw)
        else:
            for idx, field in enumerate(fallback_fields, start=2):
                raw = cells[idx] if idx < len(cells) else ""
                if field == "pos_size":
                    record[field] = _strip_tags(raw) or None
                else:
                    record[field] = _to_float(raw)

        rows.append(record)

    return rows


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or parse the daily role-metrics HTML snapshot.")
    parser.add_argument("--html-path", type=str, default=None, help="Local HTML/text capture to parse")
    parser.add_argument("--url", type=str, default=None, help="Optional live URL to fetch")
    parser.add_argument("--game-date", required=True, help="Slate date in YYYY-MM-DD format")
    parser.add_argument("--dashboard-dir", type=str, default=str(DEFAULT_DASHBOARD_DIR))
    parser.add_argument("--snapshot-dir", type=str, default=str(DEFAULT_SNAPSHOT_DIR))
    args = parser.parse_args()

    html_path = Path(args.html_path).expanduser() if args.html_path else None
    html_text, source_url = _read_html_from_source(html_path, args.url)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    html_sha256 = _hash_text(html_text)
    snapshot_id = f"role_metrics_{args.game_date.replace('-', '')}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    rows = _parse_rows(html_text)
    if not rows:
        raise RuntimeError("No metric rows were parsed from the HTML source")

    snapshot = RoleMetricsSnapshot(
        game_date=args.game_date,
        source_url=source_url,
        fetched_at=fetched_at,
        snapshot_id=snapshot_id,
        html_sha256=html_sha256,
        row_count=len(rows),
        rows=rows,
    )

    dashboard_dir = Path(args.dashboard_dir).expanduser()
    snapshot_dir = Path(args.snapshot_dir).expanduser() / args.game_date
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    latest_json = dashboard_dir / "role_metrics_latest.json"
    latest_html = dashboard_dir / "role_metrics_latest.html"
    manifest_path = dashboard_dir / "role_metrics_snapshot_manifest.json"

    payload = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "game_date": snapshot.game_date,
        "source_url": snapshot.source_url,
        "fetched_at": snapshot.fetched_at,
        "snapshot_id": snapshot.snapshot_id,
        "html_sha256": snapshot.html_sha256,
        "row_count": snapshot.row_count,
        "rows": snapshot.rows,
    }
    _write_json(latest_json, payload)
    latest_html.write_text(html_text, encoding="utf-8")

    snap_json = snapshot_dir / f"{snapshot.snapshot_id}.json"
    snap_html = snapshot_dir / f"{snapshot.snapshot_id}.html"
    _write_json(snap_json, payload)
    snap_html.write_text(html_text, encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "game_date": snapshot.game_date,
        "source_url": snapshot.source_url,
        "fetched_at": snapshot.fetched_at,
        "snapshot_id": snapshot.snapshot_id,
        "html_sha256": snapshot.html_sha256,
        "row_count": snapshot.row_count,
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
        print(f"[ROLE_METRICS] archive skipped: {exc!r}")

    print(f"[ROLE_METRICS] rows={snapshot.row_count} snapshot_id={snapshot.snapshot_id}")
    print(f"[ROLE_METRICS] wrote: {latest_json}")
    print(f"[ROLE_METRICS] wrote: {latest_html}")
    print(f"[ROLE_METRICS] wrote: {manifest_path}")
    print(f"[ROLE_METRICS] wrote: {snap_json}")
    print(f"[ROLE_METRICS] wrote: {snap_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())