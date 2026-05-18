from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .slip_composition_policy import (
    composition_drop_reason_for_item,
    infer_slate_game_count,
    leg_parts_from_slip_row,
)


REVIEW_FILE = "builder_openai_review.json"
MANIFEST_FILE = "builder_candidate_manifest.json"


def write_builder_openai_review(run_dir: Path, cfg: Mapping[str, Any] | None) -> dict[str, Path]:
    """Write a report-only builder manifest and optional OpenAI operator review.

    This stage is deliberately downstream of all deterministic builders and quality gates.
    It must never mutate slip outputs or fail a live run.
    """

    section = _section(cfg)
    if not bool(section.get("enabled", False)):
        return {}

    run_dir = Path(run_dir)
    out_dir = run_dir.parent.parent
    dashboard_dir = out_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    candidate_manifest = build_builder_candidate_manifest(run_dir, cfg)
    manifest_path = run_dir / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(candidate_manifest, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    (dashboard_dir / "builder_candidate_latest.json").write_text(
        json.dumps(candidate_manifest, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    review = _build_skipped_review(section, "disabled")
    if bool(section.get("call_openai", True)):
        review = _request_openai_review(candidate_manifest, section, run_dir)

    review_path = run_dir / REVIEW_FILE
    review_path.write_text(json.dumps(review, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
    (dashboard_dir / "builder_openai_review_latest.json").write_text(
        json.dumps(review, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    _print_review_summary(review)
    return {"candidate_manifest": manifest_path, "openai_review": review_path}


def build_builder_candidate_manifest(run_dir: Path, cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    scored = _read_csv(run_dir / "scored_legs_deduped.csv")
    slate_games = infer_slate_game_count(scored)

    public_quality = _read_json(run_dir / "public_slip_quality_manifest.json")
    selected_slips: list[dict[str, Any]] = []
    selected_slips.extend(_load_recommended_family(run_dir / "System", "System", cfg, slate_games))
    selected_slips.extend(_load_recommended_family(run_dir / "Windfall", "Windfall", cfg, slate_games))
    selected_slips.extend(_load_demonhunter(run_dir / "demonhunter.csv", cfg, slate_games))
    selected_slips.extend(_load_marketed(run_dir / "marketed_slips.csv", cfg, slate_games))

    selected_slips.sort(
        key=lambda item: (
            _family_rank(item.get("family")),
            int(_num(item.get("n_legs"), 99)),
            -float(_num(item.get("public_survival_score"), 0.0)),
            -float(_num(item.get("hit_prob"), 0.0)),
        )
    )

    manifest = {
        "generated_at_utc": _utc_now(),
        "report_only": True,
        "run_dir": str(run_dir),
        "slate": _slate_summary(scored, slate_games),
        "selected_slip_count": len(selected_slips),
        "selected_counts": _counts_by_family(selected_slips),
        "selected_slips": selected_slips,
        "public_quality": {
            "enabled": public_quality.get("enabled"),
            "priority": public_quality.get("priority"),
            "kept_counts": public_quality.get("kept_counts", {}),
            "dropped_count": public_quality.get("dropped_count", 0),
            "drops": _trim_public_drops(public_quality.get("drops", [])),
        },
        "notes": [
            "OpenAI review is report-only.",
            "Deterministic probabilities, tiers, quality gates, and slip outputs remain authoritative.",
        ],
    }
    return manifest


def _request_openai_review(candidate_manifest: Mapping[str, Any], section: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    key = _load_openai_key(section, run_dir)
    if not key:
        return _build_skipped_review(section, "missing_api_key")

    model = str(section.get("model") or "gpt-4.1-mini")
    timeout = float(_num(section.get("timeout_seconds"), 20.0))
    max_output_tokens = int(_num(section.get("max_output_tokens"), 1200))
    prompt_payload = _compact_for_prompt(candidate_manifest, int(_num(section.get("max_prompt_slips"), 24)))
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a report-only sports model operations reviewer for Atlas. "
                    "You do not choose bets, do not guarantee outcomes, and do not change probabilities. "
                    "Review the deterministic builder output for composition risk, fragile concentration, "
                    "public-output quality, and whether the operator should publish, thin-publish, or pass. "
                    "Return compact JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Review this Atlas builder manifest. Use only the supplied data. "
                    "Return JSON with keys: publish_recommendation, confidence, strongest_family, "
                    "strongest_slip, pass_or_thin_reason, risk_flags, operator_summary, suggested_audits. "
                    f"\n\n{json.dumps(prompt_payload, default=_json_default)}"
                ),
            },
        ],
        "max_output_tokens": max_output_tokens,
        "temperature": float(_num(section.get("temperature"), 0.1)),
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        return _build_error_review(section, f"http_{exc.code}", detail)
    except Exception as exc:
        return _build_error_review(section, exc.__class__.__name__, str(exc))

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _build_error_review(section, "invalid_openai_json_response", raw[:1000])

    text = _extract_response_text(parsed)
    structured = _parse_json_text(text)
    return {
        "generated_at_utc": _utc_now(),
        "report_only": True,
        "status": "completed",
        "model": section.get("model") or "gpt-4.1-mini",
        "review": structured if structured is not None else {"raw_text": text},
        "openai_response_id": parsed.get("id"),
        "usage": parsed.get("usage", {}),
    }


def _load_openai_key(section: Mapping[str, Any], run_dir: Path) -> str:
    for env_name in ("OPENAI_API_KEY", "ATLAS_OPENAI_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    key_path_env = str(section.get("key_path_env") or "ATLAS_OPENAI_API_KEY_PATH")
    env_path = os.environ.get(key_path_env, "").strip()
    if env_path:
        value = _read_key_file(Path(env_path))
        if value:
            return value

    key_path = str(section.get("key_path") or "").strip()
    if key_path:
        path = Path(key_path)
        if not path.is_absolute():
            path = _repo_root_from_run_dir(run_dir) / path
        value = _read_key_file(path)
        if value:
            return value

    return ""


def _read_key_file(path: Path) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    for line in text.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            return value
    return ""


def _load_recommended_family(
    family_dir: Path,
    family: str,
    cfg: Mapping[str, Any] | None,
    slate_games: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n_legs in (2, 3, 4, 5):
        path = family_dir / f"recommended_{n_legs}leg.csv"
        frame = _read_csv(path)
        if frame.empty:
            continue
        for idx, row in frame.iterrows():
            item = _slip_item_from_row(row, family=family, name=f"{family}_{n_legs}leg", source=path, cfg=cfg, slate_games=slate_games)
            item["row_index"] = int(idx)
            out.append(item)
    return out


def _load_demonhunter(path: Path, cfg: Mapping[str, Any] | None, slate_games: int | None) -> list[dict[str, Any]]:
    frame = _read_csv(path)
    if frame.empty:
        return []
    out: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        n_legs = int(_num(row.get("n_legs"), len(leg_parts_from_slip_row(row)) or 0))
        item = _slip_item_from_row(row, family="DemonHunter", name=f"DemonHunter_{n_legs}leg", source=path, cfg=cfg, slate_games=slate_games)
        item["row_index"] = int(idx)
        out.append(item)
    return out


def _load_marketed(path: Path, cfg: Mapping[str, Any] | None, slate_games: int | None) -> list[dict[str, Any]]:
    frame = _read_csv(path)
    if frame.empty or "slip" not in frame.columns:
        return []
    out: list[dict[str, Any]] = []
    for slip_name, group in frame.groupby("slip", sort=False):
        leg_parts = [
            {
                "player": _clean(row.get("player")),
                "team": _clean(row.get("team")),
                "opp": _clean(row.get("opp")),
                "stat": _clean(row.get("stat")).upper(),
                "direction": _clean(row.get("direction")).upper(),
                "tier": _clean(row.get("tier")).upper(),
                "line": row.get("line"),
                "p_cal": _round(row.get("p_cal"), 4),
            }
            for _, row in group.iterrows()
        ]
        first = group.iloc[0]
        item = _base_slip_item(
            family="Marketed",
            name=f"Marketed_{slip_name}",
            source=path,
            n_legs=len(leg_parts),
            leg_parts=leg_parts,
            hit_prob=first.get("hit_prob"),
            ev_mult=first.get("ev"),
            payout_mult=first.get("payout_mult"),
            public_survival_score=first.get("public_survival_score"),
            public_quality_reasons=first.get("public_quality_reasons"),
            q_leg_count=(
                pd.to_numeric(group["is_questionable"], errors="coerce").fillna(0).sum()
                if "is_questionable" in group.columns
                else None
            ),
            cfg=cfg,
            slate_games=slate_games,
        )
        out.append(item)
    return out


def _slip_item_from_row(
    row: pd.Series,
    *,
    family: str,
    name: str,
    source: Path,
    cfg: Mapping[str, Any] | None,
    slate_games: int | None,
) -> dict[str, Any]:
    leg_parts = leg_parts_from_slip_row(row)
    n_legs = int(_num(row.get("n_legs"), len(leg_parts) or 0))
    return _base_slip_item(
        family=family,
        name=name,
        source=source,
        n_legs=n_legs,
        leg_parts=leg_parts,
        hit_prob=row.get("hit_prob"),
        ev_mult=row.get("ev_mult", row.get("ev")),
        payout_mult=row.get("payout_mult_eff", row.get("payout_mult")),
        public_survival_score=row.get("public_survival_score"),
        public_quality_reasons=row.get("public_quality_reasons"),
        q_leg_count=row.get("q_leg_count"),
        cfg=cfg,
        slate_games=slate_games,
    )


def _base_slip_item(
    *,
    family: str,
    name: str,
    source: Path,
    n_legs: int,
    leg_parts: list[dict[str, Any]],
    hit_prob: Any,
    ev_mult: Any,
    payout_mult: Any,
    public_survival_score: Any,
    public_quality_reasons: Any,
    q_leg_count: Any,
    cfg: Mapping[str, Any] | None,
    slate_games: int | None,
) -> dict[str, Any]:
    item = {
        "family": family,
        "name": name,
        "source": str(source),
        "n_legs": int(n_legs),
        "hit_prob": _round(hit_prob, 4),
        "ev_mult": _round(ev_mult, 4),
        "payout_mult": _round(payout_mult, 4),
        "public_survival_score": _round(public_survival_score, 4),
        "public_quality_reasons": _clean(public_quality_reasons),
        "q_leg_count": int(_num(q_leg_count, 0)),
        "leg_parts": _trim_leg_parts(leg_parts),
    }
    item["composition_drop_reason"] = composition_drop_reason_for_item(item, cfg, slate_games)
    item["risk_flags"] = _risk_flags(item)
    return item


def _slate_summary(scored: pd.DataFrame, slate_games: int | None) -> dict[str, Any]:
    if scored.empty:
        return {"games": slate_games, "scored_leg_count": 0}
    q_col = scored.get("is_questionable", pd.Series(dtype=float))
    q_count = int(pd.to_numeric(q_col, errors="coerce").fillna(0).sum()) if not q_col.empty else 0
    return {
        "games": slate_games,
        "scored_leg_count": int(len(scored)),
        "players": int(scored["player"].nunique()) if "player" in scored.columns else None,
        "teams": sorted([str(x) for x in scored["team"].dropna().unique()]) if "team" in scored.columns else [],
        "direction_counts": _value_counts(scored, "direction", 6),
        "tier_counts": _value_counts(scored, "tier", 6),
        "top_stat_counts": _value_counts(scored, "stat", 10),
        "questionable_leg_count": q_count,
    }


def _risk_flags(item: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    leg_parts = item.get("leg_parts", [])
    if not isinstance(leg_parts, list):
        return flags
    stats = [str(leg.get("stat", "")).upper() for leg in leg_parts if isinstance(leg, Mapping)]
    dirs = [str(leg.get("direction", "")).upper() for leg in leg_parts if isinstance(leg, Mapping)]
    tiers = [str(leg.get("tier", "")).upper() for leg in leg_parts if isinstance(leg, Mapping)]
    if item.get("composition_drop_reason"):
        flags.append(str(item["composition_drop_reason"]))
    if stats.count("PRA") > 0 and int(_num(item.get("n_legs"), 0)) >= 4:
        flags.append("contains_pra_on_4_5")
    if stats.count("FG3M") > 0 and int(_num(item.get("n_legs"), 0)) >= 4:
        flags.append("contains_fg3m_on_4_5")
    if stats and max(stats.count(stat) for stat in set(stats)) > 2:
        flags.append("same_stat_cluster")
    if dirs and (dirs.count("OVER") == len(dirs) or dirs.count("UNDER") == len(dirs)):
        flags.append("single_direction_stack")
    if tiers.count("GOBLIN") >= 2:
        flags.append("goblin_cluster")
    if int(_num(item.get("q_leg_count"), 0)) > 0:
        flags.append("questionable_leg_exposure")
    if float(_num(item.get("public_survival_score"), 1.0)) < 0.58:
        flags.append("thin_public_survival")
    return flags


def _compact_for_prompt(candidate_manifest: Mapping[str, Any], max_slips: int) -> dict[str, Any]:
    slips = list(candidate_manifest.get("selected_slips", []) or [])[:max_slips]
    return {
        "slate": candidate_manifest.get("slate", {}),
        "selected_counts": candidate_manifest.get("selected_counts", {}),
        "selected_slips": slips,
        "public_quality": candidate_manifest.get("public_quality", {}),
    }


def _extract_response_text(parsed: Mapping[str, Any]) -> str:
    output_text = parsed.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    pieces: list[str] = []
    for output in parsed.get("output", []) or []:
        if not isinstance(output, Mapping):
            continue
        for content in output.get("content", []) or []:
            if not isinstance(content, Mapping):
                continue
            text = content.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "\n".join(pieces).strip()


def _parse_json_text(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _build_skipped_review(section: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "generated_at_utc": _utc_now(),
        "report_only": True,
        "status": "skipped",
        "reason": reason,
        "model": section.get("model") or "gpt-4.1-mini",
    }


def _build_error_review(section: Mapping[str, Any], reason: str, detail: str) -> dict[str, Any]:
    return {
        "generated_at_utc": _utc_now(),
        "report_only": True,
        "status": "error",
        "reason": reason,
        "detail": detail[:1000],
        "model": section.get("model") or "gpt-4.1-mini",
    }


def _print_review_summary(review: Mapping[str, Any]) -> None:
    status = review.get("status", "unknown")
    if status == "completed":
        payload = review.get("review", {})
        if isinstance(payload, Mapping):
            rec = payload.get("publish_recommendation", "unknown")
            flags = payload.get("risk_flags", [])
            print(f"[OPENAI_BUILDER_REVIEW] completed -- recommendation={rec} risk_flags={len(flags) if isinstance(flags, list) else 'unknown'}")
        else:
            print("[OPENAI_BUILDER_REVIEW] completed")
    elif status == "skipped":
        print(f"[OPENAI_BUILDER_REVIEW] skipped -- {review.get('reason')}")
    else:
        print(f"[OPENAI_BUILDER_REVIEW] {status} -- {review.get('reason')}")


def _trim_leg_parts(leg_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for leg in leg_parts:
        out.append(
            {
                "player": _clean(leg.get("player")),
                "team": _clean(leg.get("team")),
                "opp": _clean(leg.get("opp")),
                "stat": _clean(leg.get("stat")).upper(),
                "direction": _clean(leg.get("direction")).upper(),
                "tier": _clean(leg.get("tier")).upper(),
                "line": leg.get("line"),
                **({"p_cal": _round(leg.get("p_cal"), 4)} if leg.get("p_cal") is not None else {}),
            }
        )
    return out


def _trim_public_drops(drops: Any) -> list[dict[str, Any]]:
    if not isinstance(drops, list):
        return []
    out: list[dict[str, Any]] = []
    for drop in drops[:30]:
        if not isinstance(drop, Mapping):
            continue
        out.append(
            {
                "family": drop.get("family"),
                "name": drop.get("name"),
                "reason": drop.get("reason"),
                "survival_score": _round(drop.get("survival_score"), 4),
                "prop_keys": drop.get("prop_keys", [])[:8] if isinstance(drop.get("prop_keys"), list) else [],
            }
        )
    return out


def _counts_by_family(slips: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slip in slips:
        family = str(slip.get("family") or "Unknown")
        counts[family] = counts.get(family, 0) + 1
    return counts


def _value_counts(frame: pd.DataFrame, col: str, limit: int) -> dict[str, int]:
    if col not in frame.columns:
        return {}
    counts = frame[col].fillna("").astype(str).str.strip().str.upper()
    counts = counts[counts != ""].value_counts().head(limit)
    return {str(k): int(v) for k, v in counts.items()}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (pd.errors.EmptyDataError, OSError):
        return pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _section(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cfg, Mapping):
        return {}
    section = cfg.get("builder_openai_review", {})
    return dict(section) if isinstance(section, Mapping) else {}


def _repo_root_from_run_dir(run_dir: Path) -> Path:
    # data/output/runs/<run_id> -> repo root
    try:
        return run_dir.parents[3]
    except IndexError:
        return Path.cwd()


def _family_rank(family: Any) -> int:
    order = {"Marketed": 0, "System": 1, "Windfall": 2, "DemonHunter": 3}
    return order.get(str(family), 99)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:
        return default
    return out


def _round(value: Any, digits: int) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return round(out, digits)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return text.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)
