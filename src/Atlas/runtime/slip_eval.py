from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


LEG_ID_RE = re.compile(r"\[id:(?P<id>[^\]]+)\]")
LEG_RE = re.compile(
    r"^(?P<player>.*?)\s+"
    r"(?P<direction>OVER|UNDER)\s+"
    r"(?P<stat>[A-Z0-9+]+)\s+"
    r"(?P<line>-?\d+(?:\.\d+)?)\s+"
    r"\((?P<tier>[^)]+)\)"
    r"(?:\s+\[id:(?P<id>[^\]]+)\])?",
    re.IGNORECASE,
)


def write_eval_slips_for_run(run_dir: Path) -> tuple[Path, Path]:
    """Grade slip files in a run directory against eval_legs.csv.

    Writes:
    - eval_slips.csv: one row per slip
    - eval_slips.json: summary plus leg-level details
    """

    run_dir = Path(run_dir)
    eval_path = run_dir / "eval_legs.csv"
    if not eval_path.is_file():
        raise FileNotFoundError(f"Missing eval_legs.csv: {eval_path}")

    eval_df = pd.read_csv(eval_path, low_memory=False)
    truth = _TruthIndex(eval_df)

    slips: list[dict[str, Any]] = []
    slips.extend(_score_recommended_family(run_dir, "System", run_dir / "System", truth))
    slips.extend(_score_recommended_family(run_dir, "Windfall", run_dir / "Windfall", truth))
    slips.extend(_score_recommended_family(run_dir, "DemonHunter", run_dir / "DemonHunter", truth))

    if not (run_dir / "System").is_dir():
        slips.extend(_score_recommended_family(run_dir, "System", run_dir, truth))

    demonhunter_path = run_dir / "demonhunter.csv"
    if demonhunter_path.is_file():
        slips.extend(_score_slip_rows(demonhunter_path, "DemonHunter", truth, source_root=run_dir))

    marketed_path = run_dir / "marketed_slips.csv"
    if marketed_path.is_file():
        slips.extend(_score_marketed_slips(marketed_path, truth, source_root=run_dir))

    summary = _summary(slips, run_dir)
    payload = {
        "run_dir": str(run_dir.resolve()),
        "summary": summary,
        "winners": [slip for slip in slips if slip["status"] == "win"],
        "slips": slips,
    }

    json_path = run_dir / "eval_slips.json"
    csv_path = run_dir / "eval_slips.csv"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([_csv_row(slip) for slip in slips]).to_csv(csv_path, index=False)
    return csv_path.resolve(), json_path.resolve()


class _TruthIndex:
    def __init__(self, eval_df: pd.DataFrame) -> None:
        self.by_id: dict[str, list[dict[str, Any]]] = {}
        self.by_prop: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        for _, row in eval_df.iterrows():
            record = row.to_dict()
            for col in ("source_projection_id", "projection_id"):
                key = _norm_id(record.get(col))
                if key:
                    self.by_id.setdefault(key, []).append(record)

            prop_key = _prop_key(
                record.get("player"),
                record.get("stat"),
                record.get("direction"),
                record.get("line"),
            )
            if prop_key not in self.by_prop:
                self.by_prop[prop_key] = record

    def lookup_leg(self, leg: dict[str, Any]) -> dict[str, Any] | None:
        key = _norm_id(leg.get("projection_id"))
        if key:
            matches = self.by_id.get(key, [])
            if len(matches) == 1:
                return matches[0]
            if matches:
                leg_key = _prop_key(leg.get("player"), leg.get("stat"), leg.get("direction"), leg.get("line"))
                for match in matches:
                    if _prop_key(match.get("player"), match.get("stat"), match.get("direction"), match.get("line")) == leg_key:
                        return match
        return self.by_prop.get(_prop_key(leg.get("player"), leg.get("stat"), leg.get("direction"), leg.get("line")))

    def lookup_prop(self, row: pd.Series) -> dict[str, Any] | None:
        return self.by_prop.get(_prop_key(row.get("player"), row.get("stat"), row.get("direction"), row.get("line")))


def _score_recommended_family(
    run_dir: Path,
    family: str,
    folder: Path,
    truth: _TruthIndex,
) -> list[dict[str, Any]]:
    if not folder.is_dir():
        return []
    slips: list[dict[str, Any]] = []
    for path in sorted(folder.glob("recommended_*leg.csv")):
        if path.stat().st_size <= 20:
            continue
        slips.extend(_score_slip_rows(path, family, truth, source_root=run_dir))
    return slips


def _score_slip_rows(
    path: Path,
    family: str,
    truth: _TruthIndex,
    *,
    source_root: Path,
) -> list[dict[str, Any]]:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return []
    if df.empty:
        return []

    out: list[dict[str, Any]] = []
    for slip_index, row in df.reset_index(drop=True).iterrows():
        legs = _legs_from_recommended_row(row)
        if not legs:
            continue
        n_legs = _int(row.get("n_legs"), default=len(legs))
        out.append(
            _score_slip(
                family=family,
                slip_label=f"{n_legs}-leg",
                n_legs=n_legs,
                source_file=_rel(path, source_root),
                slip_index=slip_index + 1,
                row=row,
                legs=legs,
                truth=truth,
            )
        )
    return out


def _score_marketed_slips(path: Path, truth: _TruthIndex, *, source_root: Path) -> list[dict[str, Any]]:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return []
    if df.empty or "slip" not in df.columns:
        return []

    slips: list[dict[str, Any]] = []
    for slip_index, (slip_label, group) in enumerate(df.groupby("slip", sort=False), start=1):
        first = group.iloc[0]
        legs = [_leg_from_marketed_row(row) for _, row in group.iterrows()]
        n_legs = _n_legs_from_label(str(slip_label), default=len(legs))
        slips.append(
            _score_slip(
                family="Marketed",
                slip_label=str(slip_label),
                n_legs=n_legs,
                source_file=_rel(path, source_root),
                slip_index=slip_index,
                row=first,
                legs=legs,
                truth=truth,
            )
        )
    return slips


def _score_slip(
    *,
    family: str,
    slip_label: str,
    n_legs: int,
    source_file: str,
    slip_index: int,
    row: pd.Series,
    legs: list[dict[str, Any]],
    truth: _TruthIndex,
) -> dict[str, Any]:
    scored_legs = []
    hit_count = 0
    truth_count = 0
    void_count = 0

    for leg in legs:
        match = truth.lookup_leg(leg)
        scored = dict(leg)
        if match is None:
            scored.update({"hit": None, "actual": None, "truth_status": "missing"})
            void_count += 1
        else:
            hit = _hit_value(match.get("hit"))
            scored.update(
                {
                    "hit": hit,
                    "actual": _float_or_none(match.get("actual")),
                    "truth_status": "graded" if hit is not None else "void",
                    "projection_id": _norm_id(match.get("source_projection_id")) or _norm_id(match.get("projection_id")),
                }
            )
            if hit is None:
                void_count += 1
            else:
                truth_count += 1
                hit_count += int(hit)
        scored_legs.append(scored)

    if void_count > 0 or truth_count != len(legs):
        status = "void"
    elif hit_count == len(legs):
        status = "win"
    else:
        status = "loss"

    return {
        "family": family,
        "slip_label": slip_label,
        "n_legs": int(n_legs),
        "status": status,
        "all_hit": status == "win",
        "hit_count": int(hit_count),
        "truth_legs": int(truth_count),
        "void_count": int(void_count),
        "source_file": source_file,
        "slip_index": int(slip_index),
        "hit_prob": _float_or_none(row.get("hit_prob")),
        "payout_mult": _float_or_none(row.get("payout_mult")),
        "ev_mult": _float_or_none(row.get("ev_mult", row.get("ev"))),
        "public_survival_score": _float_or_none(row.get("public_survival_score")),
        "public_quality_pass": _bool_or_none(row.get("public_quality_pass")),
        "public_quality_reasons": str(row.get("public_quality_reasons", "") or ""),
        "slip_consensus_legs": _int(row.get("slip_consensus_legs"), default=0),
        "slip_consensus_share": _float_or_none(row.get("slip_consensus_share")),
        "public_portfolio_status": str(row.get("public_portfolio_status", "") or ""),
        "public_portfolio_reason": str(row.get("public_portfolio_reason", "") or ""),
        "legs": scored_legs,
    }


def _legs_from_recommended_row(row: pd.Series) -> list[dict[str, Any]]:
    leg_cols = sorted(
        [str(col) for col in row.index if re.fullmatch(r"leg_\d+", str(col))],
        key=lambda col: int(col.split("_", 1)[1]),
    )
    raw_legs: list[str] = []
    for col in leg_cols:
        value = str(row.get(col, "") or "").strip()
        if value and value.lower() != "nan":
            raw_legs.append(value)

    if not raw_legs:
        text = str(row.get("legs", "") or "")
        raw_legs = [part.strip() for part in text.split("|") if part.strip()]

    return [_parse_leg_text(text) for text in raw_legs if _parse_leg_text(text)]


def _parse_leg_text(text: str) -> dict[str, Any]:
    match = LEG_RE.match(text.strip())
    if match:
        payload = match.groupdict()
        return {
            "player": payload.get("player", "").strip(),
            "direction": str(payload.get("direction", "")).upper(),
            "stat": str(payload.get("stat", "")).upper(),
            "line": _float_or_none(payload.get("line")),
            "tier": str(payload.get("tier", "")).upper(),
            "projection_id": _norm_id(payload.get("id")),
            "label": text,
        }
    ids = LEG_ID_RE.findall(text)
    return {"projection_id": _norm_id(ids[0]) if ids else "", "label": text}


def _leg_from_marketed_row(row: pd.Series) -> dict[str, Any]:
    return {
        "player": str(row.get("player", "") or "").strip(),
        "team": str(row.get("team", "") or "").strip(),
        "opp": str(row.get("opp", "") or "").strip(),
        "stat": str(row.get("stat", "") or "").upper(),
        "direction": str(row.get("direction", "") or "").upper(),
        "tier": str(row.get("tier", "") or "").upper(),
        "line": _float_or_none(row.get("line")),
        "projection_id": "",
        "label": _format_leg_label(row),
    }


def _format_leg_label(row: pd.Series) -> str:
    player = str(row.get("player", "") or "").strip()
    direction = str(row.get("direction", "") or "").upper()
    stat = str(row.get("stat", "") or "").upper()
    line = _format_line(row.get("line"))
    tier = str(row.get("tier", "") or "").upper()
    return f"{player} {direction} {stat} {line} ({tier})".strip()


def _summary(slips: list[dict[str, Any]], run_dir: Path) -> dict[str, Any]:
    wins = [slip for slip in slips if slip["status"] == "win"]
    losses = [slip for slip in slips if slip["status"] == "loss"]
    voids = [slip for slip in slips if slip["status"] == "void"]
    graded = len(wins) + len(losses)
    by_family: dict[str, dict[str, int]] = {}
    for slip in slips:
        fam = slip["family"]
        bucket = by_family.setdefault(fam, {"total": 0, "wins": 0, "losses": 0, "voids": 0})
        bucket["total"] += 1
        if slip["status"] == "win":
            bucket["wins"] += 1
        elif slip["status"] == "loss":
            bucket["losses"] += 1
        else:
            bucket["voids"] += 1
    return {
        "run_id": run_dir.name,
        "total_slips": len(slips),
        "graded_slips": graded,
        "wins": len(wins),
        "losses": len(losses),
        "voids": len(voids),
        "win_rate": (len(wins) / graded) if graded else None,
        "by_family": by_family,
    }


def _csv_row(slip: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": slip["family"],
        "slip_label": slip["slip_label"],
        "n_legs": slip["n_legs"],
        "status": slip["status"],
        "all_hit": slip["all_hit"],
        "hit_count": slip["hit_count"],
        "truth_legs": slip["truth_legs"],
        "void_count": slip["void_count"],
        "hit_prob": slip["hit_prob"],
        "payout_mult": slip["payout_mult"],
        "ev_mult": slip["ev_mult"],
        "public_survival_score": slip.get("public_survival_score"),
        "public_quality_pass": slip.get("public_quality_pass"),
        "public_quality_reasons": slip.get("public_quality_reasons"),
        "slip_consensus_legs": slip.get("slip_consensus_legs"),
        "slip_consensus_share": slip.get("slip_consensus_share"),
        "public_portfolio_status": slip.get("public_portfolio_status"),
        "public_portfolio_reason": slip.get("public_portfolio_reason"),
        "source_file": slip["source_file"],
        "slip_index": slip["slip_index"],
        "legs": " | ".join(str(leg.get("label", "")) for leg in slip["legs"]),
        "legs_json": json.dumps(slip["legs"], sort_keys=True),
    }


def _prop_key(player: Any, stat: Any, direction: Any, line: Any) -> tuple[str, str, str, str]:
    return (_norm_text(player), str(stat or "").strip().upper(), str(direction or "").strip().upper(), _format_line(line))


def _norm_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"\s+", " ", text)


def _norm_id(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def _format_line(value: Any) -> str:
    num = _float_or_none(value)
    return "" if num is None else f"{num:g}"


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hit_value(value: Any) -> int | None:
    num = _float_or_none(value)
    if num is None:
        return None
    if num >= 1:
        return 1
    if num <= 0:
        return 0
    return None


def _bool_or_none(value: Any) -> bool | None:
    try:
        if value is None or pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
    except TypeError:
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _n_legs_from_label(label: str, *, default: int) -> int:
    match = re.search(r"(\d+)-?leg", label, re.IGNORECASE)
    return int(match.group(1)) if match else default


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
