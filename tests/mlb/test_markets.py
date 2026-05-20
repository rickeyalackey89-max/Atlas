from mlb.domain.markets import PRIZEPICKS_MARKET_ALIASES, SUPPORTED_MARKETS
from mlb.normalizers.prizepicks import is_supported_market, normalize_market


def test_prizepicks_aliases_cover_board_markets():
    assert normalize_market("Hits+Runs+RBIs") == "hits_runs_rbis"
    assert normalize_market("Pitcher Strikeouts") == "pitcher_strikeouts"
    assert normalize_market("Pitcher Fantasy Score") == "pitcher_fantasy_score"
    assert normalize_market("Earned Runs Allowed") == "earned_runs_allowed"
    assert normalize_market("Triples") == "triples"


def test_supported_market_set_contains_alias_targets():
    assert all(market in SUPPORTED_MARKETS for market in PRIZEPICKS_MARKET_ALIASES.values())
    assert is_supported_market("Total Bases")
    assert is_supported_market("Hitter Strikeouts")
