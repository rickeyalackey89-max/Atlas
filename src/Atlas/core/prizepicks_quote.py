"""PrizePicks payout quote client with replay-manifest support.

The live API quote is the source of truth for adjusted PrizePicks payouts.
Fallback payouts are intentionally marked as unadjusted so website/model
consumers do not mistake them for exact board quotes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.request

QUOTE_MANIFEST_SCHEMA_VERSION = "atlas_prizepicks_quote_manifest_v1"
QUOTE_TOOL_VERSION = "prizepicks_quote_v2"
POWER_FALLBACK_MULTIPLIERS = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
FLEX_FALLBACK_ALL_CORRECT = {2: 3.0, 3: 3.0, 4: 6.0, 5: 10.0, 6: 25.0}


def clean_projection_id(value: Any) -> str:
    projection_id = str(value or "").strip()
    if "|" in projection_id:
        projection_id = projection_id.split("|", 1)[0]
    if projection_id.endswith(".0"):
        projection_id = projection_id[:-2]
    return projection_id


def quote_prizepicks_payout(
    legs: list[dict[str, Any]],
    amount_bet_cents: int = 2500,
    timeout_seconds: int = 10,
    *,
    run_mode: str = "live",
    allow_network: bool | None = None,
    cached_manifest: dict[str, Any] | str | Path | None = None,
    write_manifest_path: str | Path | None = None,
    include_raw: bool = True,
) -> dict[str, Any] | None:
    """Quote PrizePicks adjusted payouts for a final slip.

    For replay/corpus runs this function never calls the live API unless
    ``allow_network=True`` is passed explicitly. It first checks a cached quote
    manifest, then returns a clearly flagged fallback quote when no cache exists.
    """

    picks = normalize_quote_picks(legs)
    if len(picks) < 2:
        quote = _invalid_quote(picks=picks, amount_bet_cents=amount_bet_cents, run_mode=run_mode)
        _write_single_quote_manifest(write_manifest_path, quote)
        return None

    quote_key = quote_cache_key(picks)
    cached_quote = find_cached_quote(cached_manifest, quote_key)
    if cached_quote:
        quote = copy.deepcopy(cached_quote)
        quote["quote_status"] = "cached"
        quote["source"] = "prizepicks_quote_manifest"
        quote["quote_key"] = quote_key
        _write_single_quote_manifest(write_manifest_path, quote)
        return quote

    request_body = build_game_types_request(picks, amount_bet_cents=amount_bet_cents)
    if allow_network is None:
        allow_network = _network_allowed_for_mode(run_mode)

    if not allow_network:
        quote = fallback_quote(
            picks=picks,
            request_body=request_body,
            run_mode=run_mode,
            reason="network_disabled_for_replay",
        )
        _write_single_quote_manifest(write_manifest_path, quote)
        return quote

    request = urllib.request.Request(
        "https://api.prizepicks.com/game_types",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        quote = fallback_quote(
            picks=picks,
            request_body=request_body,
            run_mode=run_mode,
            reason="quote_request_failed",
            error=str(exc),
        )
        _write_single_quote_manifest(write_manifest_path, quote)
        return quote

    quote = parse_game_types_quote(response_data, picks, request_body, include_raw=include_raw)
    _write_single_quote_manifest(write_manifest_path, quote)
    return quote


def normalize_quote_picks(legs: list[dict[str, Any]]) -> list[dict[str, str]]:
    picks: list[dict[str, str]] = []
    for leg in legs:
        projection_id = (
            leg.get("source_projection_id")
            or leg.get("projection_id")
            or leg.get("id")
        )
        projection_id_s = clean_projection_id(projection_id)
        wager_type = str(
            leg.get("direction")
            or leg.get("side")
            or leg.get("dir")
            or leg.get("wager_type")
            or ""
        ).lower().strip()
        if not projection_id_s or wager_type not in {"over", "under"}:
            return []
        picks.append({"projection_id": projection_id_s, "wager_type": wager_type})
    return picks


def build_game_types_request(picks: list[dict[str, str]], amount_bet_cents: int = 2500) -> dict[str, Any]:
    try:
        lat = float(os.environ.get("ATLAS_PP_LAT", "38.5777"))
        lng = float(os.environ.get("ATLAS_PP_LNG", "-90.25122"))
    except Exception:
        lat, lng = 38.5777, -90.25122
    return {
        "game_mode": os.environ.get("ATLAS_PP_GAME_MODE", "prizepools"),
        "lat": lat,
        "lng": lng,
        "new_wager": {
            "amount_bet_cents": int(amount_bet_cents),
            "pick_protection": False,
            "picks": picks,
        },
    }


def parse_game_types_quote(
    response_data: dict[str, Any],
    picks: list[dict[str, str]],
    request_body: dict[str, Any],
    *,
    include_raw: bool = True,
) -> dict[str, Any]:
    quote = _base_quote(
        picks=picks,
        request_body=request_body,
        source="prizepicks_game_types",
        quote_status="quoted",
    )
    quote["response_sha256"] = _sha256_json(response_data)
    if include_raw:
        quote["raw"] = response_data

    for item in response_data.get("data", []):
        attrs = item.get("attributes") if isinstance(item, dict) else {}
        attrs = attrs if isinstance(attrs, dict) else {}
        parsed = _parse_game_type_item(attrs, len(picks))
        game_type = _classify_game_type(attrs, item)
        if game_type == "power":
            quote["power"] = parsed
        elif game_type == "flex":
            quote["flex"] = parsed
        else:
            quote.setdefault("other_game_types", []).append({"game_type": game_type, **parsed})

    _choose_quote_multiplier(quote)
    if quote["chosen"]["all_correct"] is None:
        fallback = fallback_quote(
            picks=picks,
            request_body=request_body,
            run_mode=str(request_body.get("run_mode") or "live"),
            reason="quote_response_missing_multiplier",
        )
        fallback["raw_quote"] = quote
        return fallback
    return quote


def fallback_quote(
    *,
    picks: list[dict[str, str]],
    request_body: dict[str, Any],
    run_mode: str,
    reason: str,
    error: str = "",
) -> dict[str, Any]:
    n_legs = len(picks)
    quote = _base_quote(
        picks=picks,
        request_body=request_body,
        source="atlas_unadjusted_power_table",
        quote_status=f"fallback_{reason}",
    )
    quote["payout_is_exact"] = False
    quote["fallback_reason"] = reason
    if error:
        quote["error"] = error
    quote["power"] = {
        "all_correct": POWER_FALLBACK_MULTIPLIERS.get(n_legs),
        "is_adjusted": False,
        "payouts": {},
        "payout_source": "atlas_unadjusted_power_table",
    }
    quote["flex"] = {
        "all_correct": FLEX_FALLBACK_ALL_CORRECT.get(n_legs),
        "is_adjusted": False,
        "payouts": {},
        "payout_source": "atlas_unadjusted_flex_table",
    }
    quote["replay_fidelity"] = {
        "run_mode": run_mode,
        "network_allowed": False,
        "requires_manifest_for_exact_replay": True,
    }
    _choose_quote_multiplier(quote)
    quote["chosen"]["payout_is_exact"] = False
    return quote


def quote_power_multiplier(legs: list[dict[str, Any]], amount_bet_cents: int = 2500) -> float | None:
    quote = quote_prizepicks_payout(legs, amount_bet_cents=amount_bet_cents)
    if not quote:
        return None
    chosen = (quote.get("chosen") or {}).get("all_correct")
    return float(chosen) if chosen is not None else None


def quote_cache_key(picks: list[dict[str, str]]) -> str:
    return _sha256_json({"picks": picks})


def find_cached_quote(cached_manifest: dict[str, Any] | str | Path | None, quote_key: str) -> dict[str, Any] | None:
    manifest = load_quote_manifest(cached_manifest)
    if not manifest:
        return None
    if manifest.get("quote_key") == quote_key:
        return manifest
    for quote in manifest.get("quotes", []):
        if isinstance(quote, dict) and quote.get("quote_key") == quote_key:
            return quote
    return None


def load_quote_manifest(value: dict[str, Any] | str | Path | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    path = Path(value)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_quote_manifest(
    path: str | Path,
    *,
    run_id: str = "",
    run_mode: str = "",
    quotes: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest = {
        "schema_version": QUOTE_MANIFEST_SCHEMA_VERSION,
        "tool_version": QUOTE_TOOL_VERSION,
        "generated_at_utc": _utc_now(),
        "run_id": run_id,
        "run_mode": run_mode,
        "quote_count": len(quotes),
        "exact_quote_count": sum(1 for quote in quotes if bool((quote.get("chosen") or {}).get("payout_is_exact"))),
        "fallback_quote_count": sum(1 for quote in quotes if not bool((quote.get("chosen") or {}).get("payout_is_exact"))),
        "quotes": quotes,
    }
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return manifest


def fallback_power_multiplier(n_legs: int) -> float:
    return float(POWER_FALLBACK_MULTIPLIERS.get(int(n_legs), 0.0) or 0.0)


def _parse_game_type_item(attrs: dict[str, Any], n_legs: int) -> dict[str, Any]:
    payouts = attrs.get("payouts") if isinstance(attrs.get("payouts"), dict) else {}
    all_correct = _nested_multiplier(payouts, n_legs, n_legs)
    if all_correct is None:
        all_correct = _first_numeric(
            attrs.get("payout_multiplier"),
            attrs.get("max_payout_multiplier"),
            attrs.get("max_payout"),
            attrs.get("multiplier"),
        )
    return {
        "all_correct": all_correct,
        "payouts": payouts,
        "is_adjusted": bool(payouts.get("is_adjusted", attrs.get("is_adjusted", False))),
        "name": attrs.get("name"),
    }


def _classify_game_type(attrs: dict[str, Any], item: Any) -> str:
    text = " ".join(
        str(value or "").lower()
        for value in (
            attrs.get("name"),
            attrs.get("display_name"),
            attrs.get("type"),
            attrs.get("game_type"),
            item.get("id") if isinstance(item, dict) else "",
            item.get("type") if isinstance(item, dict) else "",
        )
    )
    if "power" in text:
        return "power"
    if "flex" in text or "protected" in text:
        return "flex"
    return text.strip() or "unknown"


def _choose_quote_multiplier(quote: dict[str, Any]) -> None:
    power_mult = ((quote.get("power") or {}).get("all_correct"))
    flex_mult = ((quote.get("flex") or {}).get("all_correct"))
    chosen_game_type = "power" if power_mult is not None else "flex" if flex_mult is not None else ""
    chosen_mult = power_mult if power_mult is not None else flex_mult
    exact = bool(quote.get("payout_is_exact", True)) and quote.get("quote_status") == "quoted"
    quote["chosen"] = {
        "game_type": chosen_game_type,
        "all_correct": float(chosen_mult) if chosen_mult is not None else None,
        "payout_is_exact": exact and chosen_mult is not None,
    }


def _base_quote(
    *,
    picks: list[dict[str, str]],
    request_body: dict[str, Any],
    source: str,
    quote_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": QUOTE_MANIFEST_SCHEMA_VERSION,
        "tool_version": QUOTE_TOOL_VERSION,
        "generated_at_utc": _utc_now(),
        "source": source,
        "quote_status": quote_status,
        "payout_is_exact": quote_status == "quoted",
        "game_mode": request_body.get("game_mode"),
        "amount_bet_cents": int((request_body.get("new_wager") or {}).get("amount_bet_cents") or 0),
        "n_legs": len(picks),
        "picks": picks,
        "quote_key": quote_cache_key(picks),
        "request_sha256": _sha256_json(request_body),
        "request": request_body,
    }


def _invalid_quote(*, picks: list[dict[str, str]], amount_bet_cents: int, run_mode: str) -> dict[str, Any]:
    request_body = build_game_types_request(picks, amount_bet_cents=amount_bet_cents)
    return fallback_quote(
        picks=picks,
        request_body=request_body,
        run_mode=run_mode,
        reason="invalid_or_too_few_picks",
    )


def _write_single_quote_manifest(path: str | Path | None, quote: dict[str, Any]) -> None:
    if path is None:
        return
    write_quote_manifest(path, run_id="", run_mode="", quotes=[quote])


def _network_allowed_for_mode(run_mode: str) -> bool:
    override = os.environ.get("ATLAS_PP_QUOTE_ENABLED")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return str(run_mode or "").strip().lower() == "live"


def _nested_multiplier(payouts: dict[str, Any], hits: int, legs: int) -> float | None:
    for first in (str(hits), hits):
        value = payouts.get(first)
        if not isinstance(value, dict):
            continue
        for second in (str(legs), legs, "all_correct", "max"):
            parsed = _optional_float(value.get(second))
            if parsed is not None:
                return parsed
    return None


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
