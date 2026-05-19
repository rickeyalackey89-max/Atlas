from __future__ import annotations

import re
from typing import Any


# Atlas canonical NBA team codes match the live PrizePicks/NBA.com surfaces.
_TEAM_ALIAS_TO_CANONICAL = {
    "ATL": "ATL",
    "BOS": "BOS",
    "BKN": "BKN",
    "BRK": "BKN",
    "CHA": "CHA",
    "CHO": "CHA",
    "CHH": "CHA",
    "CHI": "CHI",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GS": "GSW",
    "GSW": "GSW",
    "GOL": "GSW",
    "HOU": "HOU",
    "IND": "IND",
    "LAC": "LAC",
    "LAL": "LAL",
    "MEM": "MEM",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NO": "NOP",
    "NOP": "NOP",
    "NOR": "NOP",
    "NY": "NYK",
    "NYK": "NYK",
    "OKC": "OKC",
    "ORL": "ORL",
    "PHI": "PHI",
    "PHO": "PHX",
    "PHX": "PHX",
    "PNX": "PHX",
    "POR": "POR",
    "SAC": "SAC",
    "SA": "SAS",
    "SAS": "SAS",
    "TOR": "TOR",
    "UTA": "UTA",
    "UTAH": "UTA",
    "WAS": "WAS",
    "WSH": "WAS",
}

_TEAM_NAME_TO_CANONICAL = {
    "ATLANTAHAWKS": "ATL",
    "BOSTONCELTICS": "BOS",
    "BROOKLYNNETS": "BKN",
    "CHARLOTTEHORNETS": "CHA",
    "CHICAGOBULLS": "CHI",
    "CLEVELANDCAVALIERS": "CLE",
    "DALLASMAVERICKS": "DAL",
    "DENVERNUGGETS": "DEN",
    "DETROITPISTONS": "DET",
    "GOLDENSTATEWARRIORS": "GSW",
    "HOUSTONROCKETS": "HOU",
    "INDIANAPACERS": "IND",
    "LACLIPPERS": "LAC",
    "LOSANGELESCLIPPERS": "LAC",
    "LALAKERS": "LAL",
    "LOSANGELESLAKERS": "LAL",
    "MEMPHISGRIZZLIES": "MEM",
    "MIAMIHEAT": "MIA",
    "MILWAUKEEBUCKS": "MIL",
    "MINNESOTATIMBERWOLVES": "MIN",
    "NEWORLEANSPELICANS": "NOP",
    "NEWYORKKNICKS": "NYK",
    "OKLAHOMACITYTHUNDER": "OKC",
    "ORLANDOMAGIC": "ORL",
    "PHILADELPHIA76ERS": "PHI",
    "PHOENIXSUNS": "PHX",
    "PORTLANDTRAILBLAZERS": "POR",
    "SACRAMENTOKINGS": "SAC",
    "SANANTONIOSPURS": "SAS",
    "SANANTONIOSPURRS": "SAS",
    "TORONTORAPTORS": "TOR",
    "UTAHJAZZ": "UTA",
    "WASHINGTONWIZARDS": "WAS",
}


def normalize_team_abbr(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    key = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if not key:
        return ""

    if key in _TEAM_ALIAS_TO_CANONICAL:
        return _TEAM_ALIAS_TO_CANONICAL[key]
    if key in _TEAM_NAME_TO_CANONICAL:
        return _TEAM_NAME_TO_CANONICAL[key]

    return key


def normalize_team_series(series):
    return series.map(normalize_team_abbr)


CANONICAL_NBA_TEAMS = frozenset(_TEAM_ALIAS_TO_CANONICAL.values())
