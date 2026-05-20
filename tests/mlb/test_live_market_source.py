import json

import requests

from mlb.fetchers.http import request_with_retries
from mlb.runtime.pipeline_execution import (
    _ensure_draftkings_pick6_source,
    _ensure_primary_market_source,
    _refresh_context_sources,
)
from mlb.runtime.results import RuntimeCommandResult


def test_live_primary_market_source_uses_same_date_existing_snapshot_when_fresh_fetch_fails(tmp_path, monkeypatch):
    normalized_dir = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "oddsapi"
        / "bettingpros_mlb_props_20990511T120000Z_20990511"
    )
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "oddsapi_props.jsonl").write_text('{"source":"bettingpros_mlb_props"}\n', encoding="utf-8")
    (normalized_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "bettingpros_mlb_props",
                "snapshot_id": "bettingpros_mlb_props_20990511T120000Z",
                "row_count": 123,
                "rejected_count": 4,
            }
        ),
        encoding="utf-8",
    )

    def raise_timeout(**_kwargs):
        raise RuntimeError("504 Server Error: Gateway Timeout")

    monkeypatch.setattr("mlb.runtime.pipeline_execution.fetch_bettingpros_mlb_props", raise_timeout)

    payload = _ensure_primary_market_source(
        enabled=True,
        root=tmp_path,
        game_date="2099-05-11",
        run_mode="live",
    )

    assert payload["status"] == "existing"
    assert payload["fallback_used"] is True
    assert payload["fresh_fetch_status"] == "error"
    assert payload["snapshot_id"] == "bettingpros_mlb_props_20990511T120000Z"
    assert payload["normalized_output_dir"] == str(normalized_dir)
    assert payload["row_count"] == 123
    assert payload["rejected_count"] == 4


def test_replay_primary_market_source_selects_same_date_existing_snapshot_when_refresh_disabled(tmp_path):
    normalized_dir = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "oddsapi"
        / "bettingpros_mlb_props_20990511T120000Z_20990511"
    )
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "oddsapi_props.jsonl").write_text('{"source":"bettingpros_mlb_props"}\n', encoding="utf-8")
    (normalized_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "bettingpros_mlb_props",
                "snapshot_id": "bettingpros_mlb_props_20990511T120000Z",
                "row_count": 123,
                "rejected_count": 4,
            }
        ),
        encoding="utf-8",
    )

    payload = _ensure_primary_market_source(
        enabled=False,
        root=tmp_path,
        game_date="2099-05-11",
        run_mode="replay_single",
    )

    assert payload["status"] == "existing"
    assert payload["refresh_enabled"] is False
    assert payload["selection_mode"] == "date_safe_existing"
    assert payload["normalized_output_dir"] == str(normalized_dir)
    assert payload["row_count"] == 123


def test_live_draftkings_pick6_uses_same_date_existing_snapshot_when_fresh_fetch_fails(tmp_path, monkeypatch):
    normalized_dir = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "draftkings_mlb_pick6"
        / "draftkings_mlb_pick6_20990511T120000Z"
    )
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "oddsapi_props.jsonl").write_text(
        '{"source":"draftkings_mlb_pick6","game_date":"2099-05-11"}\n',
        encoding="utf-8",
    )
    (normalized_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "draftkings_mlb_pick6",
                "snapshot_id": "draftkings_mlb_pick6_20990511T120000Z",
                "row_count": 55,
                "compatible_row_count": 50,
                "rejected_count": 5,
            }
        ),
        encoding="utf-8",
    )

    def raise_timeout(**_kwargs):
        raise RuntimeError("504 Server Error: Gateway Timeout")

    monkeypatch.setattr("mlb.runtime.pipeline_execution.fetch_draftkings_mlb_pick6", raise_timeout)

    payload = _ensure_draftkings_pick6_source(
        enabled=True,
        root=tmp_path,
        game_date="2099-05-11",
        run_mode="live",
    )

    assert payload["status"] == "existing"
    assert payload["fallback_used"] is True
    assert payload["fresh_fetch_status"] == "error"
    assert payload["errors"] == []
    assert payload["normalized_output_dir"] == str(normalized_dir)
    assert payload["row_count"] == 55
    assert payload["compatible_row_count"] == 50


def test_replay_draftkings_pick6_selects_same_date_existing_snapshot_without_fetch(tmp_path, monkeypatch):
    normalized_dir = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "draftkings_mlb_pick6"
        / "draftkings_mlb_pick6_20990511T120000Z"
    )
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "oddsapi_props.jsonl").write_text(
        '{"source":"draftkings_mlb_pick6","game_date":"2099-05-11"}\n',
        encoding="utf-8",
    )
    (normalized_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "draftkings_mlb_pick6",
                "snapshot_id": "draftkings_mlb_pick6_20990511T120000Z",
                "row_count": 55,
                "compatible_row_count": 50,
                "rejected_count": 5,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_draftkings_mlb_pick6",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("replay must not fetch DK Pick6")),
    )

    payload = _ensure_draftkings_pick6_source(
        enabled=True,
        root=tmp_path,
        game_date="2099-05-11",
        run_mode="replay_single",
    )

    assert payload["status"] == "existing"
    assert payload["refresh_enabled"] is False
    assert payload["selection_mode"] == "date_safe_existing"
    assert payload["normalized_output_dir"] == str(normalized_dir)
    assert payload["row_count"] == 55


def test_live_context_refresh_uses_same_date_rotowire_fallback_when_fresh_fetch_fails(tmp_path, monkeypatch):
    normalized_dir = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "rotowire_context"
        / "rotowire_mlb_context_20990511T120000Z"
    )
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "daily_lineups.jsonl").write_text(
        '{"source":"rotowire_mlb_context","game_date":"2099-05-11"}\n',
        encoding="utf-8",
    )
    (normalized_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "rotowire_mlb_context",
                "snapshot_id": "rotowire_mlb_context_20990511T120000Z",
                "game_date": "2099-05-11",
                "row_counts": {"daily_lineups": 1},
                "output_dir": str(normalized_dir),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_rotowire_result",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("504 Server Error: Gateway Timeout")),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_baseball_savant_result",
        lambda **_kwargs: RuntimeCommandResult(
            name="fetch_baseball_savant",
            payload={"source": "baseball_savant_context", "normalized": {"row_counts": {"ballparks": 1}}},
            lines=(),
        ),
    )

    payload = _refresh_context_sources(
        enabled=True,
        root=tmp_path,
        game_date="2099-05-11",
        rotowire_pages=None,
        baseball_savant_pages=None,
        baseball_savant_season=2099,
        include_espn_backfill=False,
        include_live_identity_sources=False,
    )

    assert payload["errors"] == []
    assert payload["rotowire"]["fallback_used"] is True
    assert payload["rotowire"]["normalized"]["fallback_output_dir"] == str(normalized_dir)
    assert payload["fallbacks"][0]["source"] == "rotowire_mlb_context"


def test_request_with_retries_retries_transient_504(monkeypatch):
    calls = []

    class FakeSession:
        def request(self, method, url, timeout, **kwargs):
            calls.append((method, url, timeout, kwargs))
            response = requests.Response()
            response.url = url
            response.status_code = 504 if len(calls) == 1 else 200
            response._content = b'{"ok":true}'
            return response

    monkeypatch.setattr("mlb.fetchers.http.time.sleep", lambda *_args, **_kwargs: None)

    response = request_with_retries(
        FakeSession(),
        "GET",
        "https://example.test/source",
        timeout=3,
        retries=1,
    )

    assert response.status_code == 200
    assert len(calls) == 2
