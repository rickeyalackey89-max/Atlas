"""Source definitions for MLB development fetchers."""

PRIZEPICKS_PROJECTIONS_URL = "https://api.prizepicks.com/projections"
PRIZEPICKS_MLB_LEAGUE_ID = 2
PRIZEPICKS_BOARD_URL = (
    f"{PRIZEPICKS_PROJECTIONS_URL}?league_id={PRIZEPICKS_MLB_LEAGUE_ID}"
    "&per_page=250"
    "&single_stat=false"
    "&in_game=false"
    "&state_code=MO"
    "&game_mode=prizepools"
)
ESPN_MLB_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"
ESPN_MLB_INJURIES_PAGE_URL = "https://www.espn.com/mlb/injuries"
ESPN_MLB_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
ESPN_MLB_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"
ESPN_MLB_ATHLETE_GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/baseball/mlb/athletes/{athlete_id}/gamelog"
MLB_STATSAPI_BASE_URL = "https://statsapi.mlb.com/api/v1"
ODDSAPI_BASE_URL = "https://api.the-odds-api.com/v4"
ODDSAPI_MLB_SPORT_KEY = "baseball_mlb"
PARLAYAPI_BASE_URL = "https://parlay-api.com/v1"
BETTINGPROS_BASE_URL = "https://api.bettingpros.com/v3"
ODDSAPI_MLB_BOOKMAKERS = (
    "prizepicks",
    "draftkings",
    "fanduel",
)
ROTOWIRE_BASE_URL = "https://www.rotowire.com"
ROTOWIRE_MLB_DAILY_LINEUPS_URL = f"{ROTOWIRE_BASE_URL}/baseball/daily-lineups.php"
ROTOWIRE_MLB_BATTING_ORDERS_URL = f"{ROTOWIRE_BASE_URL}/baseball/batting-orders.php"
ROTOWIRE_MLB_PROJECTED_STARTERS_URL = f"{ROTOWIRE_BASE_URL}/baseball/projected-starters.php"
ROTOWIRE_MLB_BULLPEN_USAGE_URL = f"{ROTOWIRE_BASE_URL}/baseball/bullpen-usage.php"
ROTOWIRE_MLB_BULLPEN_USAGE_TABLE_URL = f"{ROTOWIRE_BASE_URL}/baseball/tables/bullpen-usage.php"
ROTOWIRE_MLB_RELIEVER_USAGE_URL = f"{ROTOWIRE_BASE_URL}/baseball/reliever-usage.php"
ROTOWIRE_MLB_RELIEVER_USAGE_TABLE_URL = f"{ROTOWIRE_BASE_URL}/baseball/tables/reliever-usage.php"
ROTOWIRE_MLB_LINEUP_CARD_URL = f"{ROTOWIRE_BASE_URL}/baseball/lineup-card.php"
ROTOWIRE_MLB_WEATHER_URL = f"{ROTOWIRE_BASE_URL}/baseball/weather.php"
ROTOWIRE_MLB_UMPIRES_URL = f"{ROTOWIRE_BASE_URL}/baseball/umpire-stats-daily.php"
ROTOWIRE_MLB_ODDS_URL = f"{ROTOWIRE_BASE_URL}/betting/mlb/odds"
COVERS_MLB_WEATHER_URL = "https://www.covers.com/sport/mlb/weather"
WUNDERGROUND_BASE_URL = "https://www.wunderground.com"
WEATHER_COM_HISTORICAL_OBSERVATIONS_URL = "https://api.weather.com/v1/location/{location}/observations/historical.json"
BASEBALL_SAVANT_BASE_URL = "https://baseballsavant.mlb.com"
BASEBALL_SAVANT_CUSTOM_LEADERBOARD_URL = f"{BASEBALL_SAVANT_BASE_URL}/leaderboard/custom"
BASEBALL_SAVANT_EXPECTED_STATS_URL = f"{BASEBALL_SAVANT_BASE_URL}/leaderboard/expected_statistics"
BASEBALL_SAVANT_PARK_FACTORS_URL = f"{BASEBALL_SAVANT_BASE_URL}/leaderboard/statcast-park-factors"
BASEBALL_SAVANT_SCHEDULE_URL = f"{BASEBALL_SAVANT_BASE_URL}/schedule"
BASEBALL_SAVANT_STATCAST_SEARCH_CSV_URL = f"{BASEBALL_SAVANT_BASE_URL}/statcast_search/csv"
BASEBALL_SAVANT_TRENDING_PLAYERS_URL = f"{BASEBALL_SAVANT_BASE_URL}/savant/api/v1/trending-players"
BASEBALL_REFERENCE_BASE_URL = "https://www.baseball-reference.com"
UMPSCORECARDS_BASE_URL = "https://umpscorecards.com"
UMPSCORECARDS_GAMES_URL = f"{UMPSCORECARDS_BASE_URL}/api/games"
DRAFTKINGS_SPORTS_CONTENT_VIEWS_BFF = "https://sportsbook-nash.draftkings.com/api/sportscontent/views/dkusnj"
DRAFTKINGS_PICK6_API_BASE_URL = "https://api.draftkings.com"
DRAFTKINGS_PICK6_MLB_SPORT_LEAGUE_KEY = "2-2"

MLB_STATSAPI_MAJOR_SPORT_ID = 1
MLB_STATSAPI_MINOR_SPORT_IDS = (11, 12, 13, 14, 16)
MLB_STATSAPI_DEFAULT_SPORT_IDS = (MLB_STATSAPI_MAJOR_SPORT_ID,) + MLB_STATSAPI_MINOR_SPORT_IDS

MLB_STATSAPI_SPORT_LABELS = {
    1: "MLB",
    11: "Triple-A",
    12: "Double-A",
    13: "High-A",
    14: "Single-A",
    16: "Rookie",
}

ODDSAPI_MLB_CORE_MARKETS = (
    "batter_hits",
    "batter_total_bases",
    "batter_rbis",
    "batter_runs_scored",
    "batter_hits_runs_rbis",
    "batter_singles",
    "batter_doubles",
    "batter_walks",
    "batter_strikeouts",
    "batter_stolen_bases",
    "batter_home_runs",
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
)
ODDSAPI_MLB_ALL_MARKETS = (
    *ODDSAPI_MLB_CORE_MARKETS,
    "batter_triples",
    "batter_fantasy_score",
)
ODDSAPI_MLB_MARKETS = ODDSAPI_MLB_CORE_MARKETS

SOURCE_NAMES = {
    "prizepicks": "PrizePicks",
    "prizepicks_all_sports": "PrizePicks All Sports",
    "legacy_prizepicks_nba": "Legacy Atlas NBA PrizePicks Raw",
    "cbs_mlb_injuries": "CBS MLB Injury Reports",
    "espn_injuries": "ESPN MLB Injuries",
    "espn_game_context": "ESPN MLB Game Context",
    "espn_player_gamelog": "ESPN MLB Player Game Log",
    "espn_player_gamelogs_bulk": "ESPN MLB Bulk Player Game Logs",
    "oddsapi_mlb_live": "The Odds API MLB Live Props",
    "oddsapi_mlb_historical": "The Odds API MLB Historical Props",
    "parlayapi_mlb_historical_closing_props": "ParlayAPI MLB Historical Closing Props",
    "bettingpros_mlb_props": "BettingPros MLB Player Props",
    "draftkings_mlb_live": "DraftKings Sportsbook MLB Live",
    "draftkings_mlb_sportsbook": "DraftKings Sportsbook MLB Player Props",
    "draftkings_mlb_pick6": "DraftKings Pick6 MLB Props",
    "statsapi_teams": "MLB StatsAPI Teams",
    "statsapi_rosters": "MLB StatsAPI Rosters",
    "statsapi_rosters_bulk": "MLB StatsAPI Bulk Rosters",
    "statsapi_schedule": "MLB StatsAPI Schedule",
    "statsapi_boxscore": "MLB StatsAPI Box Scores",
    "statsapi_boxscores_bulk": "MLB StatsAPI Bulk Box Scores",
    "statsapi_player_gamelog": "MLB StatsAPI Player Game Logs",
    "statsapi_player_gamelogs_bulk": "MLB StatsAPI Bulk Player Game Logs",
    "statsapi_transactions": "MLB StatsAPI Transactions",
    "rotowire_mlb_context": "Rotowire MLB Context",
    "covers_mlb_weather": "Covers MLB Weather",
    "wunderground_history_weather": "Weather Underground Historical Weather",
    "baseball_reference_boxscore_context": "Baseball Reference Boxscore Context",
    "mlb_wind_effect_data": "MLB Stadium Wind Effect Data",
    "baseball_savant_context": "Baseball Savant Context",
    "umpscorecards_games": "UmpScorecards Game Scorecards",
}

SOURCE_DESCRIPTIONS = {
    "prizepicks": "PrizePicks MLB projections board and included player/game metadata.",
    "prizepicks_all_sports": "Full PrizePicks projections board across all available sports for audit and recovery.",
    "legacy_prizepicks_nba": (
        "Imported Atlas NBA PrizePicks raw boards kept as format fixtures; not used as MLB source snapshots."
    ),
    "cbs_mlb_injuries": (
        "Manually captured CBS daily MLB injury reports parsed into date-safe replay injury snapshots."
    ),
    "espn_injuries": "ESPN MLB injury report API used for broad availability context.",
    "espn_game_context": (
        "ESPN MLB scoreboard, summaries, boxscore lineups, probable starters, venue, and umpire context."
    ),
    "espn_player_gamelog": "ESPN MLB athlete season game log for postgame/player-result backfills.",
    "espn_player_gamelogs_bulk": "Atomic ESPN athlete season game-log snapshot across selected players.",
    "oddsapi_mlb_live": "Live MLB player prop odds from The Odds API, preserved as raw event JSON.",
    "oddsapi_mlb_historical": "Historical MLB player prop odds snapshots from The Odds API paid endpoints.",
    "parlayapi_mlb_historical_closing_props": (
        "ParlayAPI historical MLB closing player-prop rows normalized into Atlas market-context artifacts."
    ),
    "bettingpros_mlb_props": (
        "BettingPros MLB player prop consensus and optional sportsbook offer table. Normalized into the "
        "OddsAPI-compatible market-context artifact for live and replay fidelity."
    ),
    "draftkings_mlb_live": (
        "DraftKings Sportsbook sports-content BFF live MLB odds probe. Preserved as raw JSON until prop-market "
        "coverage and route stability are validated."
    ),
    "draftkings_mlb_sportsbook": (
        "DraftKings Sportsbook MLB player-prop subcategory market rows normalized as one-sided milestone odds. "
        "Used only as supplemental market context behind BettingPros consensus."
    ),
    "draftkings_mlb_pick6": (
        "DraftKings Pick6 MLB pick groups and category pickcards. Useful as DFS-equivalent line coverage; not "
        "treated as sportsbook probability unless a true price source is added."
    ),
    "statsapi_teams": "MLB StatsAPI major/minor team identity and parent-org mapping.",
    "statsapi_rosters": "MLB StatsAPI team rosters hydrated with player identity.",
    "statsapi_rosters_bulk": "Atomic StatsAPI roster snapshot across selected MLB or MiLB teams.",
    "statsapi_schedule": "MLB StatsAPI major/minor schedules and game IDs.",
    "statsapi_boxscore": "MLB StatsAPI game box scores for player game stats and settlement.",
    "statsapi_boxscores_bulk": "Atomic StatsAPI boxscore snapshot across selected game IDs.",
    "statsapi_player_gamelog": "MLB StatsAPI player hitting/pitching/fielding game logs.",
    "statsapi_player_gamelogs_bulk": "Atomic StatsAPI game-log snapshot across selected players.",
    "statsapi_transactions": "MLB StatsAPI roster transactions for call-ups, options, IL, and assignments.",
    "rotowire_mlb_context": (
        "Rotowire MLB lineup, projected starter, bullpen, reliever, weather, umpire, and market context pages."
    ),
    "covers_mlb_weather": "Captured Covers MLB weather page used for park weather, wind, temperature, and rain context.",
    "wunderground_history_weather": (
        "Weather Underground/Weather.com historical station observations for replay weather, wind, temperature, "
        "humidity, and precipitation context."
    ),
    "baseball_reference_boxscore_context": (
        "Baseball Reference boxscore starting-lineup table used for historical pregame lineup backfill diagnostics."
    ),
    "mlb_wind_effect_data": "Stadium wind-factor workbook for wind direction, speed, HR, and run environment effects.",
    "baseball_savant_context": (
        "Baseball Savant advanced hitter/pitcher Statcast leaderboards, park factors, schedule, and trend context."
    ),
    "umpscorecards_games": (
        "UmpScorecards game-level plate umpire accuracy, consistency, favor, and batter/pitcher impact."
    ),
}
