"""PrizePicks payout quote client.

This module quotes slip-level payout multipliers. It does not submit entries.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


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
) -> dict[str, Any] | None:
    """Quote real PrizePicks adjusted payouts for a final slip via game_types."""
    picks = []
    for leg in legs:
        projection_id = (
            leg.get("source_projection_id")
            or leg.get("projection_id")
            or leg.get("id")
        )
        projection_id_s = clean_projection_id(projection_id)
        if not projection_id_s:
            return None

        wager_type = str(
            leg.get("direction")
            or leg.get("dir")
            or leg.get("wager_type")
            or ""
        ).lower().strip()
        if wager_type not in {"over", "under"}:
            return None
        picks.append({"projection_id": projection_id_s, "wager_type": wager_type})

    if len(picks) < 2:
        return None

    try:
        lat = float(os.environ.get("ATLAS_PP_LAT", "38.5777"))
        lng = float(os.environ.get("ATLAS_PP_LNG", "-90.25122"))
    except Exception:
        lat, lng = 38.5777, -90.25122

    body = {
        "game_mode": os.environ.get("ATLAS_PP_GAME_MODE", "prizepools"),
        "lat": lat,
        "lng": lng,
        "new_wager": {
            "amount_bet_cents": int(amount_bet_cents),
            "pick_protection": False,
            "picks": picks,
        },
    }
    request = urllib.request.Request(
        "https://api.prizepicks.com/game_types",
        data=json.dumps(body).encode("utf-8"),
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
    except Exception:
        return None

    return parse_game_types_quote(response_data, picks, body)


def parse_game_types_quote(
    response_data: dict[str, Any],
    picks: list[dict[str, str]],
    request_body: dict[str, Any],
) -> dict[str, Any]:
    n = str(len(picks))
    quote: dict[str, Any] = {
        "source": "prizepicks_game_types",
        "game_mode": request_body.get("game_mode"),
        "amount_bet_cents": int((request_body.get("new_wager") or {}).get("amount_bet_cents") or 0),
        "n_legs": len(picks),
        "picks": picks,
        "raw": response_data,
    }
    for item in response_data.get("data", []):
        attrs = item.get("attributes") or {}
        name = str(attrs.get("name") or "").lower()
        payouts = attrs.get("payouts") or {}
        all_correct = None
        try:
            all_correct = float((payouts.get(n) or {}).get(n))
        except Exception:
            all_correct = None
        parsed = {
            "all_correct": all_correct,
            "payouts": payouts,
            "is_adjusted": bool(payouts.get("is_adjusted", False)),
        }
        if "power" in name:
            quote["power"] = parsed
        elif "flex" in name:
            quote["flex"] = parsed
    return quote


def quote_power_multiplier(legs: list[dict[str, Any]], amount_bet_cents: int = 2500) -> float | None:
    quote = quote_prizepicks_payout(legs, amount_bet_cents=amount_bet_cents)
    if not quote:
        return None
    power_mult = (quote.get("power") or {}).get("all_correct")
    flex_mult = (quote.get("flex") or {}).get("all_correct")
    chosen = power_mult if power_mult is not None else flex_mult
    return float(chosen) if chosen is not None else None
