"""Canonical MLB market names for the development skeleton."""

BATTER_MARKETS = (
    "hits",
    "singles",
    "doubles",
    "triples",
    "total_bases",
    "hits_runs_rbis",
    "runs",
    "rbis",
    "home_runs",
    "plate_appearances",
    "walks",
    "stolen_bases",
    "hitter_strikeouts",
    "hitter_fantasy_score",
)

PITCHER_MARKETS = (
    "pitcher_strikeouts",
    "pitching_outs",
    "hits_allowed",
    "earned_runs_allowed",
    "walks_allowed",
    "pitches_thrown",
    "pitcher_fantasy_score",
)

GAME_MARKETS = (
    "first_inning_runs_allowed",
    "first_inning_walks_allowed",
)

COMBO_MARKETS = (
    "pitcher_strikeouts_combo",
    "pitcher_strikeouts_plus_total_bases",
)

MARKET_GROUPS = {
    "batter": BATTER_MARKETS,
    "pitcher": PITCHER_MARKETS,
    "game": GAME_MARKETS,
    "combo": COMBO_MARKETS,
}

SUPPORTED_MARKETS = BATTER_MARKETS + PITCHER_MARKETS + GAME_MARKETS + COMBO_MARKETS

PRIZEPICKS_MARKET_ALIASES = {
    "Hits": "hits",
    "Singles": "singles",
    "Doubles": "doubles",
    "Triples": "triples",
    "Total Bases": "total_bases",
    "Hits+Runs+RBIs": "hits_runs_rbis",
    "Hits + Runs + RBIs": "hits_runs_rbis",
    "Runs": "runs",
    "RBIs": "rbis",
    "RBI": "rbis",
    "Home Runs": "home_runs",
    "Plate Appearances": "plate_appearances",
    "Walks": "walks",
    "Stolen Bases": "stolen_bases",
    "Hitter Strikeouts": "hitter_strikeouts",
    "Hitter Fantasy Score": "hitter_fantasy_score",
    "Pitcher Strikeouts": "pitcher_strikeouts",
    "Pitching Outs": "pitching_outs",
    "Hits Allowed": "hits_allowed",
    "Earned Runs Allowed": "earned_runs_allowed",
    "Walks Allowed": "walks_allowed",
    "Pitches Thrown": "pitches_thrown",
    "Pitcher Fantasy Score": "pitcher_fantasy_score",
    "Pitcher Strikeouts (Combo)": "pitcher_strikeouts_combo",
    "Pitcher Strikeouts + Total Bases": "pitcher_strikeouts_plus_total_bases",
    "1st Inning Runs Allowed": "first_inning_runs_allowed",
    "1st Inning Walks Allowed": "first_inning_walks_allowed",
}

HITTER_FANTASY_WEIGHTS = {
    "single": 3,
    "double": 5,
    "triple": 8,
    "home_run": 10,
    "run": 2,
    "rbi": 2,
    "walk": 2,
    "hit_by_pitch": 2,
    "stolen_base": 5,
}

PITCHER_FANTASY_WEIGHTS = {
    "win": 6,
    "quality_start": 4,
    "earned_run": -3,
    "strikeout": 3,
    "out": 1,
}
