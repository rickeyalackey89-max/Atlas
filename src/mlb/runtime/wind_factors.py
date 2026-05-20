"""Runtime artifact writer for MLB stadium wind-factor context."""

from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

WIND_FACTOR_VERSION = "mlb_stadium_wind_factors_v0"

PARK_WIND_FACTOR_COLUMNS = (
    "team",
    "source_team_code",
    "park_name",
    "retractable_roof",
    "hr_added_by_wind",
    "hr_prevented_by_wind",
    "net_hr_wind",
    "wind_hr_susceptibility_score",
    "center_field_direction",
    "home_plate_direction",
    "home_plate_bearing_degrees",
    "center_field_bearing_degrees",
    "orientation_label",
    "orientation_source",
    "wind_out_from_direction",
    "wind_in_from_direction",
    "crosswind_lf_to_rf_from_direction",
    "crosswind_rf_to_lf_from_direction",
    "orientation_model_note",
    "confidence",
    "source",
    "flags",
)

LEAGUE_WIND_EFFECT_COLUMNS = (
    "metric",
    "wind_class",
    "wind_bucket",
    "direction_key",
    "value",
    "baseline",
    "delta",
    "source",
)

_XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

_COMPASS_BEARINGS = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}


def prepare_wind_factors_result(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    manifest = prepare_wind_factor_artifacts(source_path=source_path, root=root, run_id=run_id)
    lines = [
        "Prepared MLB wind factor artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source: {manifest['source_path']}",
        f"  park_profile_count: {manifest['park_profile_count']}",
        f"  league_effect_count: {manifest['league_effect_count']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="prepare_wind_factors", payload=manifest, lines=tuple(lines))


def prepare_wind_factor_artifacts(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    resolved_run_id = run_id or source_path.stem
    normalized = normalize_wind_factor_workbook(source_path)

    output_dir = paths.staged / "wind_factors" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    park_csv_path = output_dir / "park_wind_factors.csv"
    league_csv_path = output_dir / "league_wind_effects.csv"
    json_path = output_dir / "wind_factors.json"
    manifest_path = output_dir / "wind_factors_manifest.json"

    _write_csv(park_csv_path, normalized["park_wind_effects"], columns=PARK_WIND_FACTOR_COLUMNS)
    _write_csv(league_csv_path, normalized["league_wind_effects"], columns=LEAGUE_WIND_EFFECT_COLUMNS)
    payload = {
        "run_id": resolved_run_id,
        "source_path": str(source_path),
        "wind_factor_version": WIND_FACTOR_VERSION,
        **normalized,
        "rows": normalized["park_wind_effects"],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "run_id": resolved_run_id,
        "source_path": str(source_path),
        "wind_factor_version": WIND_FACTOR_VERSION,
        "park_profile_count": len(normalized["park_wind_effects"]),
        "league_effect_count": len(normalized["league_wind_effects"]),
        "league_baselines": normalized["league_baselines"],
        "park_csv_path": str(park_csv_path),
        "league_csv_path": str(league_csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_json_path": str(paths.staged / "wind_factors" / "latest.json"),
        "latest_manifest_path": str(paths.staged / "wind_factors" / "latest_manifest.json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(json_path, paths.staged / "wind_factors" / "latest.json")
    _copy_latest(manifest_path, paths.staged / "wind_factors" / "latest_manifest.json")
    return manifest


def normalize_wind_factor_workbook(source_path: Path) -> dict[str, Any]:
    hr_rows = _parse_league_sheet(
        _read_xlsx_sheet_rows(source_path, "HR per Game"),
        metric="hr_per_game",
    )
    run_rows = _parse_league_sheet(
        _read_xlsx_sheet_rows(source_path, "Runs per Game"),
        metric="runs_per_game",
    )
    league_rows = hr_rows + run_rows
    baselines = {
        "hr_per_game": _mean(row["value"] for row in hr_rows),
        "runs_per_game": _mean(row["value"] for row in run_rows),
    }
    for row in league_rows:
        baseline = baselines.get(str(row["metric"]), 0.0)
        row["baseline"] = baseline
        row["delta"] = round(float(row["value"]) - baseline, 6)

    park_rows = _parse_park_sheet(_read_xlsx_sheet_rows(source_path, "Park HR Wind 2023-24"))
    orientation_rows = _read_optional_xlsx_sheet_rows(source_path, "Ballpark Wind Orientation")
    if orientation_rows:
        park_rows = _merge_orientation_rows(park_rows, _parse_orientation_sheet(orientation_rows))
    return {
        "source": "mlb_wind_effect_data",
        "league_baselines": baselines,
        "league_wind_effects": league_rows,
        "park_wind_effects": park_rows,
    }


def _parse_league_sheet(rows: list[list[Any]], *, metric: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    parsed.extend(
        _parse_league_block(
            rows,
            row_start=2,
            row_end=6,
            col_start=0,
            wind_class="out",
            direction_keys=("to_left", "to_center", "to_right"),
            metric=metric,
        )
    )
    parsed.extend(
        _parse_league_block(
            rows,
            row_start=2,
            row_end=6,
            col_start=5,
            wind_class="in",
            direction_keys=("from_left", "from_center", "from_right"),
            metric=metric,
        )
    )
    parsed.extend(
        _parse_league_block(
            rows,
            row_start=11,
            row_end=15,
            col_start=0,
            wind_class="across",
            direction_keys=("left_to_right", "right_to_left"),
            metric=metric,
        )
    )
    return parsed


def _parse_league_block(
    rows: list[list[Any]],
    *,
    row_start: int,
    row_end: int,
    col_start: int,
    wind_class: str,
    direction_keys: tuple[str, ...],
    metric: str,
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in rows[row_start:row_end]:
        wind_bucket = str(_cell(row, col_start) or "").strip()
        if not wind_bucket:
            continue
        for offset, direction_key in enumerate(direction_keys, start=1):
            value = _float(_cell(row, col_start + offset))
            if value is None:
                continue
            parsed.append(
                {
                    "metric": metric,
                    "wind_class": wind_class,
                    "wind_bucket": wind_bucket,
                    "direction_key": direction_key,
                    "value": value,
                    "baseline": 0.0,
                    "delta": 0.0,
                    "source": "mlb_wind_effect_data",
                }
            )
    return parsed


def _parse_park_sheet(rows: list[list[Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    header_index = _find_header_index(rows, "team/park code")
    header = rows[header_index] if header_index >= 0 else []
    header_lookup = {_normalize_header(value): index for index, value in enumerate(header)}
    for row in rows[2:]:
        source_team = str(_cell(row, 0) or "").strip()
        if not source_team:
            continue
        team = canonical_team_abbr(source_team)
        added = _float(_cell(row, 1)) or 0.0
        prevented = _float(_cell(row, 2)) or 0.0
        net = _float(_cell(row, 3))
        if net is None:
            net = added - prevented
        home_bearing = _float_header(
            row,
            header_lookup,
            "home plate bearing",
            "home plate bearing degrees",
            "home plate orientation",
            "home plate direction degrees",
        )
        center_bearing = _float_header(
            row,
            header_lookup,
            "center field bearing",
            "center field bearing degrees",
            "cf bearing",
            "outfield bearing",
            "out direction degrees",
        )
        orientation_label = _str_header(
            row,
            header_lookup,
            "orientation",
            "orientation label",
            "stadium orientation",
            "field orientation",
            "home plate direction",
            "center field direction",
        )
        orientation_source = _str_header(
            row,
            header_lookup,
            "orientation source",
            "bearing source",
            "direction source",
        )
        flags = ["park_wind_factor_available"]
        if home_bearing is not None or center_bearing is not None or orientation_label:
            flags.append("park_orientation_available")
        parsed.append(
            {
                "team": team,
                "source_team_code": source_team,
                "park_name": "",
                "retractable_roof": False,
                "hr_added_by_wind": added,
                "hr_prevented_by_wind": prevented,
                "net_hr_wind": net,
                "wind_hr_susceptibility_score": round(_clamp(net / 80.0, -1.0, 1.0), 6),
                "center_field_direction": "",
                "home_plate_direction": "",
                "home_plate_bearing_degrees": home_bearing,
                "center_field_bearing_degrees": center_bearing,
                "orientation_label": orientation_label,
                "orientation_source": orientation_source,
                "wind_out_from_direction": "",
                "wind_in_from_direction": "",
                "crosswind_lf_to_rf_from_direction": "",
                "crosswind_rf_to_lf_from_direction": "",
                "orientation_model_note": "",
                "confidence": 0.88,
                "source": "mlb_wind_effect_data",
                "flags": tuple(flags),
            }
        )
    return parsed


def _parse_orientation_sheet(rows: list[list[Any]]) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    header_index = _find_header_index(rows, "Team Abbrev")
    if header_index < 0:
        return parsed
    header = rows[header_index]
    header_lookup = {_normalize_header(value): index for index, value in enumerate(header)}
    for row in rows[header_index + 1 :]:
        source_team = _str_header(row, header_lookup, "team abbrev", "team park code", "team")
        team = canonical_team_abbr(source_team)
        if not team:
            continue
        center_direction = _normalize_compass_direction(
            _str_header(
                row,
                header_lookup,
                "center field direction home cf",
                "center field direction",
                "center field direction home to cf",
            )
        )
        home_direction = _normalize_compass_direction(
            _str_header(
                row,
                header_lookup,
                "home plate direction cf home",
                "home plate direction",
                "home plate direction cf to home",
            )
        )
        out_from = _extract_from_direction(
            _str_header(row, header_lookup, "wind blowing out helps carry weather wind from to")
        )
        in_from = _extract_from_direction(
            _str_header(row, header_lookup, "wind blowing in knocks down weather wind from to")
        )
        lf_to_rf_from = _extract_from_direction(
            _str_header(row, header_lookup, "crosswind lf rf weather wind from to")
        )
        rf_to_lf_from = _extract_from_direction(
            _str_header(row, header_lookup, "crosswind rf lf weather wind from to")
        )
        note = _str_header(row, header_lookup, "modeling note", "note", "notes")
        parsed[team] = {
            "team": team,
            "orientation_source_team_code": source_team,
            "park_name": _str_header(row, header_lookup, "ballpark", "park", "park name"),
            "retractable_roof": _yes(_str_header(row, header_lookup, "retractable roof", "roof")),
            "center_field_direction": center_direction,
            "home_plate_direction": home_direction,
            "center_field_bearing_degrees": _compass_bearing(center_direction),
            "home_plate_bearing_degrees": _compass_bearing(home_direction),
            "orientation_label": f"CF {center_direction}; HP {home_direction}".strip(),
            "orientation_source": "ballpark_wind_orientation_sheet",
            "wind_out_from_direction": out_from,
            "wind_in_from_direction": in_from,
            "crosswind_lf_to_rf_from_direction": lf_to_rf_from,
            "crosswind_rf_to_lf_from_direction": rf_to_lf_from,
            "orientation_model_note": note,
        }
    return parsed


def _merge_orientation_rows(
    park_rows: list[dict[str, Any]],
    orientation_by_team: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in park_rows:
        out = dict(row)
        orientation = orientation_by_team.get(canonical_team_abbr(out.get("team")))
        if orientation:
            for key, value in orientation.items():
                if key == "team" or value in (None, ""):
                    continue
                out[key] = value
            flags = list(out.get("flags") or ())
            if "park_orientation_available" not in flags:
                flags.append("park_orientation_available")
            if out.get("retractable_roof"):
                flags.append("retractable_roof")
            out["flags"] = tuple(flags)
        merged.append(out)
    return merged


def _find_header_index(rows: list[list[Any]], header_name: str) -> int:
    normalized = _normalize_header(header_name)
    for index, row in enumerate(rows):
        if any(_normalize_header(value) == normalized for value in row):
            return index
    return -1


def _float_header(row: list[Any], header_lookup: dict[str, int], *names: str) -> float | None:
    value = _header_value(row, header_lookup, *names)
    return _float(value)


def _str_header(row: list[Any], header_lookup: dict[str, int], *names: str) -> str:
    value = _header_value(row, header_lookup, *names)
    return str(value or "").strip()


def _header_value(row: list[Any], header_lookup: dict[str, int], *names: str) -> Any:
    for name in names:
        index = header_lookup.get(_normalize_header(name))
        if index is not None:
            return _cell(row, index)
    return None


def _normalize_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _read_xlsx_sheet_rows(path: Path, sheet_name: str) -> list[list[Any]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        sheet_path = _sheet_path(archive, sheet_name)
        root = ElementTree.fromstring(archive.read(sheet_path))
    rows: list[list[Any]] = []
    for row in root.findall(".//main:sheetData/main:row", _XML_NS):
        values_by_col: dict[int, Any] = {}
        for cell in row.findall("main:c", _XML_NS):
            col_index = _column_index(cell.attrib.get("r", ""))
            if col_index < 0:
                continue
            values_by_col[col_index] = _cell_value(cell, shared_strings)
        if not values_by_col:
            rows.append([])
            continue
        max_col = max(values_by_col)
        values = [values_by_col.get(index) for index in range(max_col + 1)]
        while values and values[-1] is None:
            values.pop()
        rows.append(values)
    return rows


def _read_optional_xlsx_sheet_rows(path: Path, sheet_name: str) -> list[list[Any]]:
    try:
        return _read_xlsx_sheet_rows(path, sheet_name)
    except ValueError:
        return []


def _sheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.findall("pkgrel:Relationship", _XML_NS)
    }
    for sheet in workbook.findall(".//main:sheets/main:sheet", _XML_NS):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get(f"{{{_XML_NS['rel']}}}id")
        target = rel_targets.get(rel_id, "")
        if not target:
            break
        normalized_target = target.lstrip("/")
        return normalized_target if normalized_target.startswith("xl/") else "xl/" + normalized_target
    raise ValueError(f"Worksheet not found in wind workbook: {sheet_name}")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", _XML_NS):
        values.append("".join(text.text or "" for text in item.findall(".//main:t", _XML_NS)))
    return values


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t", "")
    value_node = cell.find("main:v", _XML_NS)
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//main:t", _XML_NS))
    if value_node is None or value_node.text is None:
        return None
    value = value_node.text
    if cell_type == "s":
        index = int(value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type == "str":
        return value
    number = _float(value)
    return number if number is not None else value


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return -1
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _cell(row: list[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def _extract_from_direction(value: str) -> str:
    match = re.search(r"\bFROM\s+([A-Z]+)", str(value or "").upper())
    return _normalize_compass_direction(match.group(1)) if match else ""


def _normalize_compass_direction(value: Any) -> str:
    text = re.sub(r"[^A-Z]", "", str(value or "").upper())
    return text if text in _COMPASS_BEARINGS else ""


def _compass_bearing(value: str) -> float | None:
    bearing = _COMPASS_BEARINGS.get(_normalize_compass_direction(value))
    return float(bearing) if bearing is not None else None


def _yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _write_csv(path: Path, rows: list[dict[str, Any]], *, columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _mean(values) -> float:
    collected = [float(value) for value in values]
    return round(sum(collected) / len(collected), 6) if collected else 0.0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
