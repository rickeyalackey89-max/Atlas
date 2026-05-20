import json

from core.prizepicks_payout_formula import (
    estimate_payout_formula,
    payout_formula_audit_row,
    write_payout_formula_audit,
)


def test_default_formula_uses_tier_mix():
    legs = [
        {"tier": "GOBLIN"},
        {"tier": "STANDARD"},
        {"tier": "DEMON"},
    ]

    estimate = estimate_payout_formula(legs, family="Windfall", label="3leg", sport="mlb", model={})

    assert estimate["formula_source"] == "default_tier_mix_formula"
    assert estimate["n_legs"] == 3
    assert estimate["tier_counts"] == {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1}
    assert estimate["formula_payout_mult"] > 0


def test_formula_audit_row_compares_exact_quote():
    legs = [{"tier": "GOBLIN"}, {"tier": "STANDARD"}, {"tier": "STANDARD"}]
    quote = {
        "quote_status": "quoted",
        "quote_key": "abc",
        "source": "prizepicks_game_types",
        "chosen": {"all_correct": 4.0, "game_type": "power", "payout_is_exact": True},
    }

    row = payout_formula_audit_row(legs=legs, family="Marketed", label="3-leg", quote=quote, sport="mlb")

    assert row["actual_payout_mult"] == 4.0
    assert row["actual_is_exact"] is True
    assert row["abs_error"] is not None
    assert row["quote_key"] == "abc"


def test_write_formula_audit_artifact(tmp_path):
    row = {
        "formula_payout_mult": 4.2,
        "actual_payout_mult": 4.0,
        "actual_is_exact": True,
        "abs_error": 0.2,
        "pct_error": 0.05,
    }

    payload = write_payout_formula_audit(
        tmp_path / "payout_formula_audit.json",
        rows=[row],
        run_id="live_test",
        run_mode="live",
        sport="mlb",
    )

    saved = json.loads((tmp_path / "payout_formula_audit.json").read_text(encoding="utf-8"))
    assert payload["summary"]["mae"] == 0.2
    assert saved["exact_compare_count"] == 1
