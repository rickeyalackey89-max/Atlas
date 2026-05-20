import json
from pathlib import Path

import mlb.runtime.slips as slips_runtime
from mlb.runtime.slips import build_slip_families_from_scored_run

_GOBLIN_MARKETS = ("hitter_fantasy_score", "hits_runs_rbis", "hits")
_STANDARD_MARKETS = ("hitter_fantasy_score", "hits_runs_rbis", "total_bases")
_DEMON_MARKETS = ("singles", "total_bases", "hits_runs_rbis")


def test_slip_outputs_enforce_atlas_tier_mix_contracts(tmp_path):
    run_dir = _write_scored_run(
        tmp_path,
        [
            _leg(1, tier="GOBLIN", side="under", probability=0.99, market="hitter_fantasy_score"),
            _leg(2, tier="DEMON", side="over", probability=0.98, market="home_runs"),
            *[
                _leg(index, tier="GOBLIN", side="over", probability=0.95 - index * 0.001, market=_cycle_market(index, _GOBLIN_MARKETS))
                for index in range(10, 40)
            ],
            *[
                _leg(index, tier="STANDARD", side="over", probability=0.90 - index * 0.001, market=_cycle_market(index, _STANDARD_MARKETS))
                for index in range(100, 130)
            ],
            *[_leg(index, tier="DEMON", side="over", probability=0.85 - index * 0.001, market=_cycle_market(index, _DEMON_MARKETS)) for index in range(200, 260)],
        ],
    )

    manifest = build_slip_families_from_scored_run(run_dir)

    assert manifest["builder"] == "atlas_mlb_slip_writer_v4"
    assert manifest["run_mode"] == "replay_single"
    assert manifest["single_game_slate"] is False
    assert manifest["portfolio_policy"]["max_exact_leg_repeats_across_public"] == 1
    assert manifest["portfolio_policy"]["max_exposure_repeats_across_public"] == 1
    assert manifest["portfolio_policy"]["repeat_violations"] == []
    assert manifest["portfolio_policy"]["exposure_repeat_violations"] == []
    assert manifest["family_builder_policies"]["Marketed"]["purpose"] == "premium_public_picks"
    assert manifest["family_builder_policies"]["System"]["purpose"] == "atlas_value_ev"
    assert manifest["family_builder_policies"]["Windfall"]["purpose"] == "flex_upside_best_of_both_worlds"
    assert manifest["family_builder_policies"]["DemonHunter"]["purpose"] == "high_variance_demon_over_payout"
    quote_manifest = json.loads((run_dir / "slips" / "payout_quote_manifest.json").read_text(encoding="utf-8"))
    assert manifest["payout_quote_manifest"]["quote_count"] == manifest["slip_count"]
    assert quote_manifest["quote_count"] == manifest["slip_count"]
    assert quote_manifest["exact_quote_count"] == 0
    assert quote_manifest["fallback_quote_count"] == manifest["slip_count"]
    assert not (run_dir / "slips" / "system_2leg.json").exists()
    assert not (run_dir / "System" / "recommended_2leg.csv").exists()
    assert not (run_dir / "slips" / "windfall_2leg.json").exists()
    assert not (run_dir / "Windfall" / "recommended_2leg.csv").exists()
    _assert_counts(_json_legs(run_dir, "system_3leg.json"), {"GOBLIN": 1, "STANDARD": 2})
    _assert_counts(_json_legs(run_dir, "system_4leg.json"), {"GOBLIN": 2, "STANDARD": 2})
    _assert_counts(_json_legs(run_dir, "system_5leg.json"), {"GOBLIN": 3, "STANDARD": 2})
    _assert_counts(_json_legs(run_dir, "windfall_3leg.json"), {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1})
    _assert_counts(_json_legs(run_dir, "windfall_4leg.json"), {"GOBLIN": 1, "STANDARD": 2, "DEMON": 1})
    _assert_counts(_json_legs(run_dir, "windfall_5leg.json"), {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1})

    demonhunter = json.loads((run_dir / "slips" / "demonhunter.json").read_text(encoding="utf-8"))
    assert [len(slip["legs"]) for slip in demonhunter["slips"]] == [3, 4, 5]
    for slip in demonhunter["slips"]:
        _assert_counts(slip["legs"], {"DEMON": len(slip["legs"])})

    marketed = json.loads((run_dir / "marketed_slips.json").read_text(encoding="utf-8"))
    assert [slip["label"] for slip in marketed["slips"]] == ["3-leg", "4-leg", "5-leg"]
    _assert_counts(marketed["slips"][0]["legs"], {"GOBLIN": 1, "STANDARD": 2})
    _assert_counts(marketed["slips"][1]["legs"], {"GOBLIN": 2, "STANDARD": 2})
    _assert_counts(marketed["slips"][2]["legs"], {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1})
    for slip in marketed["slips"]:
        _assert_no_invalid_tier_direction(slip["legs"])
    _assert_unique_public_exact_legs(run_dir)
    _assert_unique_public_exposure_legs(run_dir)
    _assert_public_slip_composition(run_dir)


def test_live_slip_runs_call_prizepicks_quote_tool(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_quote(legs, **kwargs):
        calls.append({"legs": legs, **kwargs})
        multiplier = {2: 2.5, 3: 5.0, 4: 9.0, 5: 18.0}.get(len(legs), 0.0)
        return {
            "quote_status": "quoted",
            "source": "prizepicks_game_types",
            "quote_key": f"quote-{len(calls)}",
            "chosen": {"game_type": "power", "all_correct": multiplier, "payout_is_exact": True},
            "power": {"all_correct": multiplier},
            "flex": {"all_correct": multiplier / 2 if multiplier else None},
        }

    monkeypatch.setattr(slips_runtime, "quote_prizepicks_payout", fake_quote)
    run_dir = tmp_path / "data" / "mlb" / "live_runs" / "live_quote_test"
    rows = [
        *[_leg(index, tier="GOBLIN", side="over", probability=0.95 - index * 0.001, market=_cycle_market(index, _GOBLIN_MARKETS)) for index in range(10, 35)],
        *[_leg(index, tier="STANDARD", side="over", probability=0.90 - index * 0.001, market=_cycle_market(index, _STANDARD_MARKETS)) for index in range(100, 125)],
        *[_leg(index, tier="DEMON", side="over", probability=0.85 - index * 0.001, market=_cycle_market(index, _DEMON_MARKETS)) for index in range(200, 225)],
    ]
    _write_scored_run_at(run_dir, rows)

    manifest = build_slip_families_from_scored_run(run_dir)

    assert calls
    assert manifest["run_mode"] == "live"
    assert all(call["run_mode"] == "live" for call in calls)
    assert all(call["allow_network"] is True for call in calls)
    quote_manifest = json.loads((run_dir / "slips" / "payout_quote_manifest.json").read_text(encoding="utf-8"))
    assert quote_manifest["exact_quote_count"] == quote_manifest["quote_count"]
    assert not (run_dir / "slips" / "system_2leg.json").exists()
    system_3leg = json.loads((run_dir / "slips" / "system_3leg.json").read_text(encoding="utf-8"))
    assert system_3leg["payout_mult"] == 5.0
    assert system_3leg["payout_is_exact"] is True


def test_live_payout_quote_context_reuses_duplicate_quote_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_PP_QUOTE_THROTTLE_S", "0")
    calls: list[dict] = []

    def fake_quote(legs, **kwargs):
        calls.append({"legs": legs, **kwargs})
        picks = slips_runtime.normalize_quote_picks(legs)
        return {
            "quote_status": "quoted",
            "source": "prizepicks_game_types",
            "quote_key": slips_runtime.quote_cache_key(picks),
            "chosen": {"game_type": "power", "all_correct": 4.0, "payout_is_exact": True},
            "power": {"all_correct": 4.0},
            "flex": {"all_correct": 2.0},
        }

    monkeypatch.setattr(slips_runtime, "quote_prizepicks_payout", fake_quote)
    context = slips_runtime._PayoutQuoteContext(run_dir=tmp_path, run_id="live_quote_cache", run_mode="live")
    legs = [
        {"source_projection_id": "123", "side": "over"},
        {"source_projection_id": "456", "side": "under"},
    ]

    first = context.quote(legs, family="Marketed", label="3-leg")
    second = context.quote(legs, family="System", label="3leg")
    manifest = context.write_manifest(tmp_path / "slips" / "payout_quote_manifest.json")

    assert len(calls) == 1
    assert first["quote_status"] == "quoted"
    assert second["quote_status"] == "cached_in_run"
    assert second["cache_source"] == "live_run_quote_cache"
    assert second["family"] == "System"
    assert second["chosen"]["payout_is_exact"] is True
    assert manifest["quote_count"] == 2
    assert manifest["exact_quote_count"] == 2


def test_single_game_slip_outputs_use_atlas_single_game_templates(tmp_path):
    run_dir = _write_scored_run(
        tmp_path,
        [
            *[
                    _leg(
                        index,
                        tier="GOBLIN",
                        side="over",
                        probability=0.95 - index * 0.001,
                        event_id="single_game",
                        market=_cycle_market(index, _GOBLIN_MARKETS),
                    )
                for index in range(10, 35)
            ],
            *[
                    _leg(
                        index,
                        tier="STANDARD",
                        side="over",
                        probability=0.90 - index * 0.001,
                        event_id="single_game",
                        market=_cycle_market(index, _STANDARD_MARKETS),
                    )
                for index in range(100, 120)
            ],
            *[
                        _leg(index, tier="DEMON", side="over", probability=0.85 - index * 0.001, event_id="single_game", market=_cycle_market(index, _DEMON_MARKETS))
                for index in range(200, 220)
            ],
        ],
    )

    manifest = build_slip_families_from_scored_run(run_dir)

    assert manifest["single_game_slate"] is True
    _assert_counts(_json_legs(run_dir, "windfall_2leg.json"), {"GOBLIN": 2})
    _assert_counts(_json_legs(run_dir, "windfall_3leg.json"), {"GOBLIN": 2, "STANDARD": 1})
    _assert_counts(_json_legs(run_dir, "windfall_4leg.json"), {"GOBLIN": 3, "STANDARD": 1})
    assert _json_legs(run_dir, "windfall_5leg.json") == []

    marketed = json.loads((run_dir / "marketed_slips.json").read_text(encoding="utf-8"))
    assert [slip["label"] for slip in marketed["slips"]] == ["2-leg", "3-leg"]
    _assert_counts(marketed["slips"][0]["legs"], {"GOBLIN": 2})
    _assert_counts(marketed["slips"][1]["legs"], {"GOBLIN": 2, "STANDARD": 1})
    _assert_unique_public_exact_legs(run_dir)
    _assert_unique_public_exposure_legs(run_dir)


def test_public_portfolio_blocks_line_alternate_exposure_across_families(tmp_path):
    run_dir = _write_scored_run(
        tmp_path,
        [
            _leg(1, tier="GOBLIN", side="over", probability=0.99, event_id="same_game", market="hits", line=0.5, player_id="same_player"),
            _leg(2, tier="GOBLIN", side="over", probability=0.98, event_id="same_game", market="hits", line=1.5, player_id="same_player"),
            *[
                _leg(index, tier="GOBLIN", side="over", probability=0.95 - index * 0.001, market=_cycle_market(index, _GOBLIN_MARKETS))
                for index in range(10, 40)
            ],
            *[
                _leg(index, tier="STANDARD", side="over", probability=0.90 - index * 0.001, market=_cycle_market(index, _STANDARD_MARKETS))
                for index in range(100, 130)
            ],
            *[_leg(index, tier="DEMON", side="over", probability=0.85 - index * 0.001, market=_cycle_market(index, _DEMON_MARKETS)) for index in range(200, 260)],
        ],
    )

    build_slip_families_from_scored_run(run_dir)

    exposure_keys = [_exposure_key(leg) for leg in _all_public_legs(run_dir)]
    exposure_keys = [key for key in exposure_keys if key]
    assert exposure_keys.count("same_player|same_game|hits|over") <= 1


def test_family_builder_policies_rank_marketed_away_from_volatile_pitch_count():
    rows = [
        _leg(1, tier="GOBLIN", side="over", probability=0.90, market="pitches_thrown"),
        _leg(2, tier="GOBLIN", side="over", probability=0.89, market="hitter_fantasy_score"),
        _leg(3, tier="GOBLIN", side="over", probability=0.88, market="total_bases"),
    ]

    marketed = slips_runtime._ranked_legs(rows, family="Marketed")

    assert marketed[0]["market"] == "hitter_fantasy_score"


def _write_scored_run(tmp_path: Path, rows: list[dict]) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_scored_run_at(run_dir, rows)
    return run_dir


def _write_scored_run_at(run_dir: Path, rows: list[dict]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scored_legs.json").write_text(
        json.dumps({"run_id": "tier_contract_run", "scored_legs": rows}),
        encoding="utf-8",
    )
    return run_dir


def _cycle_market(index: int, markets: tuple[str, ...]) -> str:
    return markets[index % len(markets)]


def _leg(
    index: int,
    *,
    tier: str,
    side: str,
    probability: float,
    event_id: str | None = None,
    market: str | None = None,
    line: float = 1.5,
    player_id: str | None = None,
) -> dict:
    resolved_market = market or f"market_{index}"
    return {
        "source_projection_id": f"proj_{index}",
        "event_id": event_id or f"game_{index % 3}",
        "game_date": "2026-05-11",
        "start_time_utc": "2026-05-11T23:10:00Z",
        "player_id": player_id or f"player_{index}",
        "player_name": f"Player {index}",
        "player_team": f"T{index % 5}",
        "opponent": f"O{index % 5}",
        "market": resolved_market,
        "source_market": resolved_market.replace("_", " ").title(),
        "line": line,
        "side": side,
        "tier": tier,
        "model_probability": probability,
        "stability_score": 0.80,
        "fragility_score": 0.10,
    }


def _json_legs(run_dir: Path, filename: str) -> list[dict]:
    path = run_dir / "slips" / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["legs"]


def _assert_counts(legs: list[dict], expected: dict[str, int]) -> None:
    actual = {tier: sum(1 for leg in legs if str(leg.get("tier", "")).upper() == tier) for tier in ("GOBLIN", "STANDARD", "DEMON")}
    for tier, count in expected.items():
        assert actual[tier] == count
    assert sum(actual.values()) == sum(expected.values())
    _assert_no_invalid_tier_direction(legs)


def _assert_no_invalid_tier_direction(legs: list[dict]) -> None:
    for leg in legs:
        tier = str(leg.get("tier", "")).upper()
        side = str(leg.get("side") or leg.get("direction") or "").upper()
        if tier == "GOBLIN":
            assert side == "OVER"
        if tier == "DEMON":
            assert side == "OVER"


def _assert_unique_public_exact_legs(run_dir: Path) -> None:
    keys = [_exact_key(leg) for leg in _all_public_legs(run_dir)]
    keys = [key for key in keys if key]
    assert len(keys) == len(set(keys))


def _assert_unique_public_exposure_legs(run_dir: Path) -> None:
    keys = [_exposure_key(leg) for leg in _all_public_legs(run_dir)]
    keys = [key for key in keys if key]
    assert len(keys) == len(set(keys))


def _assert_public_slip_composition(run_dir: Path) -> None:
    workload_markets = {
        "earned_runs_allowed",
        "hits_allowed",
        "pitcher_fantasy_score",
        "pitcher_strikeouts",
        "pitches_thrown",
        "pitching_outs",
        "walks_allowed",
    }
    for legs in _public_slips(run_dir):
        market_counts = {}
        workload_count = 0
        for leg in legs:
            market = str(leg.get("market") or leg.get("stat_raw") or leg.get("source_market") or leg.get("stat") or "").strip().lower()
            market_counts[market] = market_counts.get(market, 0) + 1
            if market in workload_markets:
                workload_count += 1
        assert all(count <= 2 for count in market_counts.values())
        assert workload_count <= 1


def _public_slips(run_dir: Path) -> list[list[dict]]:
    slips: list[list[dict]] = []
    for prefix in ("system", "windfall"):
        for size in (2, 3, 4, 5):
            legs = _json_legs(run_dir, f"{prefix}_{size}leg.json")
            if legs:
                slips.append(legs)

    demonhunter = json.loads((run_dir / "slips" / "demonhunter.json").read_text(encoding="utf-8"))
    for slip in demonhunter.get("slips", []):
        slips.append(slip.get("legs", []))

    marketed = json.loads((run_dir / "marketed_slips.json").read_text(encoding="utf-8"))
    for slip in marketed.get("slips", []):
        slips.append(slip.get("legs", []))
    return slips


def _all_public_legs(run_dir: Path) -> list[dict]:
    legs: list[dict] = []
    for prefix in ("system", "windfall"):
        for size in (2, 3, 4, 5):
            legs.extend(_json_legs(run_dir, f"{prefix}_{size}leg.json"))

    demonhunter = json.loads((run_dir / "slips" / "demonhunter.json").read_text(encoding="utf-8"))
    for slip in demonhunter.get("slips", []):
        legs.extend(slip.get("legs", []))

    marketed = json.loads((run_dir / "marketed_slips.json").read_text(encoding="utf-8"))
    for slip in marketed.get("slips", []):
        legs.extend(slip.get("legs", []))
    return legs


def _exact_key(leg: dict) -> str:
    player = str(leg.get("player_id") or leg.get("player_name") or leg.get("player") or "").strip().lower()
    event = str(leg.get("event_id") or leg.get("game_id") or "").strip().lower()
    market = str(leg.get("market") or leg.get("stat_raw") or leg.get("source_market") or leg.get("stat") or "").strip().lower()
    line = str(float(leg.get("line") or 0.0))
    side = str(leg.get("side") or leg.get("direction") or "").strip().lower()
    return "|".join((player, event, market, line, side))


def _exposure_key(leg: dict) -> str:
    player = str(leg.get("player_id") or leg.get("player_name") or leg.get("player") or "").strip().lower()
    event = str(leg.get("event_id") or leg.get("game_id") or "").strip().lower()
    market = str(leg.get("market") or leg.get("stat_raw") or leg.get("source_market") or leg.get("stat") or "").strip().lower()
    side = str(leg.get("side") or leg.get("direction") or "").strip().lower()
    return "|".join((player, event, market, side))
