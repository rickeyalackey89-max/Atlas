import pandas as pd
from dataclasses import dataclass
from typing import Dict, Tuple, Optional


# -------------------------
# Data structures
# -------------------------

@dataclass(frozen=True)
class BoardOffer:
    player: str
    stat_type: str
    line: float
    tier: str
    more_allowed: bool
    less_allowed: bool
    game_id: str
    team: str

    def key(self) -> Tuple[str, str, float]:
        return (self.player, self.stat_type, float(self.line))


@dataclass(frozen=True)
class Leg:
    player: str
    stat_type: str
    line: float
    side: str  # "OVER" or "UNDER"

    def key(self) -> Tuple[str, str, float]:
        return (self.player, self.stat_type, float(self.line))


# -------------------------
# Load board catalog
# -------------------------

def load_board_catalog(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    required_cols = {
        "player", "stat_type", "line",
        "tier", "more_allowed", "less_allowed"
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in board_catalog.csv: {missing}")

    df = df.copy()
    df["player"] = df["player"].astype(str).str.strip()
    df["stat_type"] = df["stat_type"].astype(str).str.upper().str.strip()
    df["line"] = df["line"].astype(float)
    df["tier"] = df["tier"].astype(str).str.upper().str.strip()
    df["more_allowed"] = df["more_allowed"].astype(bool)
    df["less_allowed"] = df["less_allowed"].astype(bool)

    if "game_id" not in df.columns:
        df["game_id"] = ""
    if "team" not in df.columns:
        df["team"] = ""

    return df


def build_board_map(df: pd.DataFrame) -> Dict[Tuple[str, str, float], BoardOffer]:
    board = {}
    for r in df.to_dict("records"):
        offer = BoardOffer(
            player=r["player"],
            stat_type=r["stat_type"],
            line=float(r["line"]),
            tier=r["tier"],
            more_allowed=bool(r["more_allowed"]),
            less_allowed=bool(r["less_allowed"]),
            game_id=r.get("game_id", ""),
            team=r.get("team", ""),
        )
        board[offer.key()] = offer
    return board


# -------------------------
# Playability check
# -------------------------

def is_playable_leg(leg: Leg, board_map: Dict[Tuple[str, str, float], BoardOffer]) -> bool:
    key = leg.key()
    offer = board_map.get(key)

    if offer is None:
        return False

    if leg.side == "OVER":
        return offer.more_allowed
    if leg.side == "UNDER":
        return offer.less_allowed

    return False