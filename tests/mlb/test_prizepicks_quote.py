from core.prizepicks_quote import (
    build_game_types_request,
    empirical_payout_estimate,
    normalize_quote_picks,
    parse_game_types_quote,
    quote_cache_key,
    quote_prizepicks_payout,
)


def test_parse_game_types_quote_prefers_power_all_correct_multiplier():
    picks = [
        {"projection_id": "123", "wager_type": "over"},
        {"projection_id": "456", "wager_type": "under"},
    ]
    request_body = build_game_types_request(picks)
    response_data = {
        "data": [
            {"id": "flex", "attributes": {"name": "Flex Play", "payouts": {"2": {"2": 1.5}}}},
            {"id": "power", "attributes": {"name": "Power Play", "payouts": {"2": {"2": 2.75}}}},
        ]
    }

    quote = parse_game_types_quote(response_data, picks, request_body, include_raw=False)

    assert quote["quote_status"] == "quoted"
    assert quote["power"]["all_correct"] == 2.75
    assert quote["flex"]["all_correct"] == 1.5
    assert quote["chosen"]["game_type"] == "power"
    assert quote["chosen"]["all_correct"] == 2.75
    assert quote["chosen"]["payout_is_exact"] is True
    assert "raw" not in quote


def test_replay_quote_uses_flagged_fallback_without_network(monkeypatch):
    monkeypatch.setenv("ATLAS_PP_QUOTE_EMPIRICAL_ENABLED", "0")
    quote = quote_prizepicks_payout(
        [
            {"source_projection_id": "123.0", "side": "over"},
            {"source_projection_id": "456|mlb", "direction": "UNDER"},
        ],
        run_mode="replay_single",
    )

    assert quote is not None
    assert quote["quote_status"] == "fallback_network_disabled_for_replay"
    assert quote["source"] == "atlas_unadjusted_power_table"
    assert quote["chosen"]["all_correct"] == 3.0
    assert quote["chosen"]["payout_is_exact"] is False
    assert quote["picks"] == [
        {"projection_id": "123", "wager_type": "over"},
        {"projection_id": "456", "wager_type": "under"},
    ]


def test_replay_quote_can_use_empirical_fallback_table(tmp_path, monkeypatch):
    table_path = tmp_path / "empirical.json"
    table_path.write_text(
        """
        {
          "schema_version": "atlas_prizepicks_empirical_payout_fallback_v1",
          "tool_version": "test",
          "generated_at_utc": "2026-05-19T00:00:00Z",
          "tables": {
            "family_label": {
              "system|3leg": {"count": 7, "median": 4.0, "mean": 4.03, "min": 3.75, "max": 4.5}
            },
            "family_n_legs": {
              "system|3": {"count": 7, "median": 4.0}
            },
            "n_legs": {
              "3": {"count": 34, "median": 4.25}
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("ATLAS_PP_QUOTE_FALLBACK_PATH", str(table_path))

    quote = quote_prizepicks_payout(
        [
            {"source_projection_id": "123", "side": "over"},
            {"source_projection_id": "456", "side": "over"},
            {"source_projection_id": "789", "side": "over"},
        ],
        run_mode="replay_single",
        family="System",
        label="3leg",
    )

    assert quote is not None
    assert quote["quote_status"] == "fallback_empirical_network_disabled_for_replay"
    assert quote["source"] == "atlas_empirical_prizepicks_quote_table"
    assert quote["chosen"]["all_correct"] == 4.0
    assert quote["chosen"]["payout_is_exact"] is False
    assert quote["empirical_fallback"]["source_key"] == "family_label:system|3leg"


def test_empirical_payout_estimate_falls_back_to_leg_count(tmp_path, monkeypatch):
    table_path = tmp_path / "empirical.json"
    table_path.write_text(
        """
        {
          "schema_version": "atlas_prizepicks_empirical_payout_fallback_v1",
          "tool_version": "test",
          "generated_at_utc": "2026-05-19T00:00:00Z",
          "tables": {
            "family_label": {},
            "family_n_legs": {},
            "n_legs": {"5": {"count": 26, "median": 11.25}}
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("ATLAS_PP_QUOTE_FALLBACK_PATH", str(table_path))

    estimate = empirical_payout_estimate(n_legs=5, family="Unknown", label="5leg")

    assert estimate is not None
    assert estimate["all_correct"] == 11.25
    assert estimate["source_key"] == "n_legs:5"


def test_replay_quote_can_reuse_manifest_cache():
    legs = [
        {"source_projection_id": "123", "side": "over"},
        {"source_projection_id": "456", "side": "under"},
    ]
    picks = normalize_quote_picks(legs)
    cached_quote = {
        "quote_key": quote_cache_key(picks),
        "chosen": {"game_type": "power", "all_correct": 2.5, "payout_is_exact": True},
        "power": {"all_correct": 2.5},
    }

    quote = quote_prizepicks_payout(
        legs,
        run_mode="replay_single",
        cached_manifest={"quotes": [cached_quote]},
    )

    assert quote is not None
    assert quote["quote_status"] == "cached"
    assert quote["source"] == "prizepicks_quote_manifest"
    assert quote["chosen"]["all_correct"] == 2.5
    assert quote["chosen"]["payout_is_exact"] is True


def test_live_quote_retries_transient_request_failure(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"data":[{"id":"power","attributes":{"name":"Power Play","payouts":{"2":{"2":2.75}}}}]}'

    def fake_urlopen(request, timeout):
        calls.append({"request": request, "timeout": timeout})
        if len(calls) == 1:
            raise RuntimeError("HTTP Error 403: Forbidden")
        return FakeResponse()

    monkeypatch.setattr("core.prizepicks_quote.urllib.request.urlopen", fake_urlopen)

    quote = quote_prizepicks_payout(
        [
            {"source_projection_id": "123", "side": "over"},
            {"source_projection_id": "456", "side": "under"},
        ],
        run_mode="live",
        allow_network=True,
        include_raw=False,
        quote_retries=1,
        retry_sleep_seconds=0,
    )

    assert len(calls) == 2
    assert quote is not None
    assert quote["quote_status"] == "quoted"
    assert quote["quote_attempts"] == 2
    assert quote["quote_retries"] == 1
    assert quote["chosen"]["all_correct"] == 2.75
    assert quote["chosen"]["payout_is_exact"] is True
