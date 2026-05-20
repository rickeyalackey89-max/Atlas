from mlb.domain.scoring import hitter_fantasy_score, pitcher_fantasy_score


def test_hitter_fantasy_score_uses_prizepicks_weights():
    assert hitter_fantasy_score(
        singles=1,
        doubles=1,
        triples=1,
        home_runs=1,
        runs=1,
        rbis=1,
        walks=1,
        hit_by_pitch=1,
        stolen_bases=1,
    ) == 39


def test_pitcher_fantasy_score_uses_prizepicks_weights():
    assert pitcher_fantasy_score(wins=1, quality_starts=1, earned_runs=2, strikeouts=6, outs=18) == 40
