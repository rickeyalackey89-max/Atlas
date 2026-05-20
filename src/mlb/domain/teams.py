"""Canonical MLB team identity helpers.

External baseball sources disagree on a few abbreviations. PrizePicks currently
uses AZ while Rotowire and Baseball Savant may use ARI, for example. Runtime
joins should normalize before building keys so valid context is not marked
missing.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_ALIASES = {
    "ANA": "LAA",
    "ANGELS": "LAA",
    "ARIZONA": "AZ",
    "ARIZONADIAMONDBACKS": "AZ",
    "ARI": "AZ",
    "ATH": "ATH",
    "ATHLETICS": "ATH",
    "ATL": "ATL",
    "ATLANTA": "ATL",
    "ATLANTABRAVES": "ATL",
    "AZ": "AZ",
    "BAL": "BAL",
    "BALTIMORE": "BAL",
    "BALTIMOREORIOLES": "BAL",
    "BOS": "BOS",
    "BOSTON": "BOS",
    "BOSTONREDSOX": "BOS",
    "CHC": "CHC",
    "CHICAGOCUBS": "CHC",
    "CHICAGONL": "CHC",
    "CHW": "CWS",
    "CHICAGOAL": "CWS",
    "CHICAGOWHITESOX": "CWS",
    "CIN": "CIN",
    "CINCINNATI": "CIN",
    "CINCINNATIREDS": "CIN",
    "CLE": "CLE",
    "CLEVELAND": "CLE",
    "CLEVELANDGUARDIANS": "CLE",
    "COL": "COL",
    "COLORADO": "COL",
    "COLORADOROCKIES": "COL",
    "CWS": "CWS",
    "DET": "DET",
    "DETROIT": "DET",
    "DETROITTIGERS": "DET",
    "HOU": "HOU",
    "HOUSTON": "HOU",
    "HOUSTONASTROS": "HOU",
    "KC": "KC",
    "KANSASCITY": "KC",
    "KANSASCITYROYALS": "KC",
    "KCR": "KC",
    "LAA": "LAA",
    "LAD": "LAD",
    "LA": "LAD",
    "LOSANGELESANGELS": "LAA",
    "LOSANGELESDODGERS": "LAD",
    "MIA": "MIA",
    "MIAMI": "MIA",
    "MIAMIMARLINS": "MIA",
    "MIL": "MIL",
    "MILWAUKEE": "MIL",
    "MILWAUKEEBREWERS": "MIL",
    "MIN": "MIN",
    "MINNESOTA": "MIN",
    "MINNESOTATWINS": "MIN",
    "NYM": "NYM",
    "NEWYORKMETS": "NYM",
    "NYY": "NYY",
    "NEWYORKYANKEES": "NYY",
    "OAK": "ATH",
    "OAKLAND": "ATH",
    "OAKLANDATHLETICS": "ATH",
    "PHI": "PHI",
    "PHILADELPHIA": "PHI",
    "PHILADELPHIAPHILLIES": "PHI",
    "PIT": "PIT",
    "PITTSBURGH": "PIT",
    "PITTSBURGHPIRATES": "PIT",
    "SD": "SD",
    "SAN DIEGO": "SD",
    "SANDIEGO": "SD",
    "SANDIEGOPADRES": "SD",
    "SDP": "SD",
    "SEA": "SEA",
    "SEATTLE": "SEA",
    "SEATTLEMARINERS": "SEA",
    "SF": "SF",
    "SANFRANCISCO": "SF",
    "SANFRANCISCOGIANTS": "SF",
    "SFG": "SF",
    "STL": "STL",
    "STLOUIS": "STL",
    "STLOUISCARDINALS": "STL",
    "TB": "TB",
    "TAMPA BAY": "TB",
    "TAMPABAY": "TB",
    "TAMPABAYRAYS": "TB",
    "TBR": "TB",
    "TEX": "TEX",
    "TEXAS": "TEX",
    "TEXASRANGERS": "TEX",
    "TOR": "TOR",
    "TORONTO": "TOR",
    "TORONTOBLUEJAYS": "TOR",
    "WAS": "WSH",
    "WASHINGTON": "WSH",
    "WASHINGTONNATIONALS": "WSH",
    "WSH": "WSH",
    "WSN": "WSH",
}


def canonical_team_abbr(value: Any) -> str:
    """Return Atlas' canonical MLB team abbreviation for joins."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in _ALIASES:
        return _ALIASES[upper]
    compact = compact_team_key(raw).upper()
    return _ALIASES.get(compact, upper)


def compact_team_key(value: Any) -> str:
    """Normalize a team string for fuzzy identity lookups."""

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text.lower())
