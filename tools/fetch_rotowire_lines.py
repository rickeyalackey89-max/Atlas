#!/usr/bin/env python3
"""
Fetch Rotowire NBA lines/spreads and write Atlas-friendly JSON.

HARD REQUIREMENT (your semantics):
- Rotowire is called every LIVE run.

SMOOTH BEHAVIOR:
- If Rotowire returns no rows / no events, do NOT silently proceed with empty spreads.
- Instead:
    1) Try to fall back to a game-date-pinned last-known-good file or same-slate archive copy
    2) If fallback exists and has events, write that into rotowire_lines.json (with a note)
  3) If fallback missing/empty too, write the empty stub and exit non-zero.

ENV:
  ROTOWIRE_GAME_DATE        (optional) YYYY-MM-DD
  ROTOWIRE_BOOK             (optional) default "mgm"  (currently only mgm supported in this script)
  ROTOWIRE_TIMEOUT_S        (optional) default 20
  ROTOWIRE_PHPSESSID        (optional) If provided, use this session id cookie.
  ROTOWIRE_OUT_PATH         (optional) output path override
  ROTOWIRE_LAST_GOOD_PATH   (optional) last-good path override
  ROTOWIRE_ALLOW_EMPTY      (optional) "1" => allow empty without failing (not recommended for LIVE)
  ROTOWIRE_DEBUG_DIR        (optional) where to write debug payloads
  ROTOWIRE_LINES_URL        (optional) full override URL
  ROTOWIRE_HEADERS_JSON     (optional) JSON dict of extra headers
  ROTOWIRE_BOOTSTRAP_URL    (optional) page to visit first to obtain cookies (default: NBA odds page)
  ROTOWIRE_EVENT_TZ         (optional) timezone name for Rotowire eventTime parsing (default America/New_York)

  ODDS_API_KEY              (optional) The Odds API key. If set, used as a fallback source when Rotowire
                            is empty/blocked or yields 0 events.
  ODDS_API_REGIONS          (optional) default "us"
  ODDS_API_MARKETS          (optional) default "spreads" (can be "spreads" or "h2h,spreads,totals" etc.)
  ODDS_API_BOOK_PREF        (optional) comma-separated bookmaker keys preference order (default "draftkings,fanduel")
  ODDS_API_TIMEOUT_S        (optional) default 20
  ODDS_API_TZ               (optional) timezone used to map commence_time to game_date (default America/Chicago)

Notes:
- This tool writes JSON shaped as:
  {"sport":"NBA","source":..., "date":"YYYY-MM-DD","events":[...], "fetched_at":"...Z", "note":"..."}
- Events are:
  {"gameID":..., "eventTime": epoch, "game_date":"YYYY-MM-DD", "homeTeam":"ATL", "awayTeam":"NYK",
   "spread":{"home": -4.5, "away": 4.5}, "ml": {"home": -180, "away": 150}, "ou": 229.5, "source":"mgm"}
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class Event:
    gameID: str
    eventTime: int
    game_date: str
    homeTeam: str
    awayTeam: str
    home_spread: Optional[float]
    away_spread: Optional[float]
    home_ml: Optional[int]
    away_ml: Optional[int]
    ou: Optional[float]
    source: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "gameID": self.gameID,
            "eventTime": self.eventTime,
            "game_date": self.game_date,
            "homeTeam": self.homeTeam,
            "awayTeam": self.awayTeam,
            "spread": {"home": self.home_spread, "away": self.away_spread},
            "ml": {"home": self.home_ml, "away": self.away_ml},
            "ou": self.ou,
            "source": self.source,
        }


# -----------------------------
# Small helpers
# -----------------------------
def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_out_path() -> Path:
    return _repo_root() / "data" / "input" / "rotowire_lines.json"


def _default_last_good_path() -> Path:
    return _repo_root() / "data" / "input" / "rotowire_lines_last_good.json"


def _debug_dir() -> Path:
    p = Path(os.getenv("ROTOWIRE_DEBUG_DIR", str(_repo_root() / "data" / "output" / "debug")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_debug(name: str, content: str) -> None:
    p = _debug_dir() / name
    p.write_text(content, encoding="utf-8")


def _maybe_env(name: str) -> Optional[str]:
    v = os.getenv(name, "").strip()
    return v or None


def _headers_from_env() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.rotowire.com/betting/nba/odds",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    extra_json = _maybe_env("ROTOWIRE_HEADERS_JSON")
    if extra_json:
        try:
            extra = json.loads(extra_json)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    headers[str(k)] = str(v)
        except Exception:
            # ignore bad header json; debugging via debug_dir if desired
            pass
    return headers


def to_float(x: Any) -> Optional[float]:
    """
    Defensive float parser.
    - None -> None
    - "PK"/"PICK" -> 0.0
    - numeric strings -> float
    - int/float -> float
    """
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return None
        if s.upper() in {"PK", "PICK", "PICK'EM", "PICKEM"}:
            return 0.0
        try:
            return float(s)
        except ValueError:
            # try to keep only numeric-ish chars
            cleaned = "".join(ch for ch in s if ch.isdigit() or ch in "+-.")
            if cleaned in {"", "+", "-", ".", "+.", "-."}:
                return None
            try:
                return float(cleaned)
            except Exception:
                return None
    # other types
    try:
        return float(str(x).strip())
    except Exception:
        return None


def _to_nullable_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return int(x)
    if isinstance(x, float):
        # Rotowire sometimes returns floats; treat as int if safe
        try:
            return int(x)
        except Exception:
            return None
    s = str(x).strip()
    if not s or s == "-":
        return None
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in "+-")
    if cleaned in {"", "+", "-"}:
        return None
    try:
        return int(cleaned)
    except Exception:
        return None


def _event_tz():
    # Rotowire table times are effectively US/Eastern for NBA odds pages.
    tz_name = (os.getenv("ROTOWIRE_EVENT_TZ") or "America/New_York").strip()
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/New_York")


def _parse_game_date_epoch(game_date_str: Optional[str], fallback_yyyy_mm_dd: str) -> int:
    """
    Parse Rotowire 'gameDate' into epoch seconds.
    Interpret naive timestamps as ROTOWIRE_EVENT_TZ (default America/New_York).
    """
    tz = _event_tz()

    if game_date_str:
        s = str(game_date_str).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                if tz is not None:
                    dt = dt.replace(tzinfo=tz)
                    return int(dt.timestamp())
                return int(dt.replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                pass

    # fallback: noon local to avoid UTC-midnight boundary surprises
    dt = datetime.strptime(fallback_yyyy_mm_dd, "%Y-%m-%d").replace(hour=12)
    if tz is not None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _normalize_rows_shape(payload: Any) -> List[Dict[str, Any]]:
    """
    Rotowire table responses vary.
    Accept:
      - list[dict]
      - dict with key 'data'/'rows'/'result' containing list[dict]
      - list containing a single list of dicts
    """
    if isinstance(payload, list):
        if len(payload) == 1 and isinstance(payload[0], list):
            payload = payload[0]
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for k in ("data", "rows", "result"):
            v = payload.get(k)
            if isinstance(v, list):
                if len(v) == 1 and isinstance(v[0], list):
                    v = v[0]
                return [x for x in v if isinstance(x, dict)]

    return []


def _pick_book_fields(book: str) -> Tuple[str, str, str]:
    b = (book or "mgm").strip().lower()
    if b == "mgm":
        return ("mgm_spread", "mgm_moneyline", "mgm_ou")
    raise SystemExit(f"[rotowire] Unsupported ROTOWIRE_BOOK={book!r}. Supported: mgm")


def _build_url(game_date: str) -> str:
    return f"https://www.rotowire.com/betting/nba/tables/nba-games-by-market.php?date={game_date}"


def _bootstrap_rotowire_session(sess: requests.Session, timeout_s: float) -> None:
    """Best-effort: visit a normal Rotowire page to obtain a PHPSESSID (and related) cookies."""
    bootstrap_url = (os.getenv("ROTOWIRE_BOOTSTRAP_URL") or "https://www.rotowire.com/betting/nba/odds").strip()
    try:
        sess.get(bootstrap_url, timeout=timeout_s)
    except Exception:
        # best-effort only
        return


# -----------------------------
# Odds API fallback
# -----------------------------
_NBA_TEAM_ABBR: Dict[str, str] = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

_NBA_ABBR_ALIAS: Dict[str, str] = {
    "SA": "SAS",
    "SAS": "SAS",
    "GS": "GSW",
    "GSW": "GSW",
    "NY": "NYK",
    "NYK": "NYK",
    "NO": "NOP",
    "NOP": "NOP",
    "PHO": "PHX",
    "PHX": "PHX",
    "UT": "UTA",
    "UTA": "UTA",
}


def _abbr_from_team_name(name: str) -> Optional[str]:
    if not name:
        return None
    n = str(name).strip()
    abbr = _canonical_abbr(n)
    if abbr:
        return abbr
    if n in _NBA_TEAM_ABBR:
        return _NBA_TEAM_ABBR[n]
    n2 = n.replace("Los Angeles", "LA")
    if n2 in _NBA_TEAM_ABBR:
        return _NBA_TEAM_ABBR[n2]
    return None


def _canonical_abbr(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).upper().strip()
    if not s:
        return None
    if s in _NBA_ABBR_ALIAS:
        return _NBA_ABBR_ALIAS[s]
    valid = set(_NBA_TEAM_ABBR.values())
    if s in valid:
        return s
    return None


def _parse_iso_z(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _oddsapi_tz():
    tz_name = (os.getenv("ODDS_API_TZ") or "America/Chicago").strip()
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Chicago")


def _fetch_oddsapi_events(game_date: str) -> List[Event]:
    api_key = (os.getenv("ODDS_API_KEY") or "").strip()
    if not api_key:
        return []

    regions = (os.getenv("ODDS_API_REGIONS") or "us").strip()
    markets = (os.getenv("ODDS_API_MARKETS") or "spreads").strip()
    timeout_s = float(os.getenv("ODDS_API_TIMEOUT_S", os.getenv("ROTOWIRE_TIMEOUT_S", "20")))
    book_pref = (os.getenv("ODDS_API_BOOK_PREF") or "draftkings,fanduel").strip()
    pref = [x.strip().lower() for x in book_pref.split(",") if x.strip()]

    url = (
        "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        f"?regions={regions}&markets={markets}&oddsFormat=american&apiKey={api_key}"
    )

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    print(f"[oddsapi] GET {url.split('apiKey=')[0]}apiKey=***")
    r = requests.get(url, headers=headers, timeout=timeout_s)
    body = r.content or b""
    print(f"[oddsapi] status={r.status_code} bytes={len(body)}")
    if r.status_code != 200:
        _write_debug(f"oddsapi_http_{r.status_code}_{game_date}.txt", (r.text or "")[:20000])
        return []

    try:
        data = r.json()
    except Exception:
        _write_debug(f"oddsapi_not_json_{game_date}.txt", (r.text or "")[:20000])
        return []

    if not isinstance(data, list):
        _write_debug(f"oddsapi_bad_shape_{game_date}.json", json.dumps(data, ensure_ascii=False)[:200000])
        return []

    tz = _oddsapi_tz()
    out: List[Event] = []

    for ev in data:
        if not isinstance(ev, dict):
            continue

        commence = _parse_iso_z(str(ev.get("commence_time") or ""))
        if commence is None:
            continue

        local_dt = commence.astimezone(tz) if tz is not None else commence
        gd = local_dt.date().isoformat()
        if gd != game_date:
            continue

        home_name = str(ev.get("home_team") or "").strip()
        away_name = str(ev.get("away_team") or "").strip()
        home_abbr = _abbr_from_team_name(home_name)
        away_abbr = _abbr_from_team_name(away_name)
        if not home_abbr or not away_abbr:
            continue

        game_id = str(ev.get("id") or "").strip() or f"oddsapi_{home_abbr}_{away_abbr}_{gd}"

        bms = ev.get("bookmakers")
        if not isinstance(bms, list):
            continue

        chosen: Optional[Dict[str, Any]] = None
        for want in pref:
            for bm in bms:
                if isinstance(bm, dict) and str(bm.get("key") or "").lower() == want:
                    chosen = bm
                    break
            if chosen is not None:
                break

        if chosen is None:
            chosen = bms[0] if (bms and isinstance(bms[0], dict)) else None
        if chosen is None:
            continue

        bm_key = str(chosen.get("key") or "").lower() or "oddsapi"
        mkts = chosen.get("markets")
        if not isinstance(mkts, list):
            continue

        spread_mkt = next((m for m in mkts if isinstance(m, dict) and str(m.get("key") or "") == "spreads"), None)
        if spread_mkt is None:
            continue

        outs = spread_mkt.get("outcomes")
        if not isinstance(outs, list):
            continue

        home_spread: Optional[float] = None
        away_spread: Optional[float] = None

        for o in outs:
            if not isinstance(o, dict):
                continue
            name = str(o.get("name") or "").strip()
            pt_f = to_float(o.get("point"))
            if pt_f is None:
                continue
            if name == home_name:
                home_spread = pt_f
            elif name == away_name:
                away_spread = pt_f

        if home_spread is None or away_spread is None:
            continue

        out.append(
            Event(
                gameID=game_id,
                eventTime=int(commence.timestamp()),
                game_date=gd,
                homeTeam=home_abbr,
                awayTeam=away_abbr,
                home_spread=home_spread,
                away_spread=away_spread,
                home_ml=None,
                away_ml=None,
                ou=None,
                source=f"oddsapi:{bm_key}",
            )
        )

    return out


# -----------------------------
# ESPN game-line fallback
# -----------------------------
def _espn_local_date(dt: datetime) -> str:
    tz = _oddsapi_tz()
    local_dt = dt.astimezone(tz) if tz is not None and dt.tzinfo is not None else dt
    return local_dt.date().isoformat()


def _espn_competitor_abbr(comp: Dict[str, Any], home_away: str) -> Optional[str]:
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return None
    want = home_away.lower().strip()
    for item in competitors:
        if not isinstance(item, dict):
            continue
        if str(item.get("homeAway") or "").lower().strip() != want:
            continue
        team = item.get("team")
        if isinstance(team, dict):
            for key in ("abbreviation", "shortDisplayName", "displayName", "name"):
                abbr = _abbr_from_team_name(str(team.get(key) or ""))
                if abbr:
                    return abbr
        for key in ("abbreviation", "team", "displayName", "name"):
            abbr = _abbr_from_team_name(str(item.get(key) or ""))
            if abbr:
                return abbr
    return None


def _pick_espn_odds_item(items: Any) -> Optional[Dict[str, Any]]:
    if isinstance(items, dict):
        # Site API may expose a single object.
        if "items" in items:
            return _pick_espn_odds_item(items.get("items"))
        return items
    if not isinstance(items, list):
        return None
    odds_items = [x for x in items if isinstance(x, dict)]
    if not odds_items:
        return None

    pref = [
        x.strip().lower()
        for x in (os.getenv("ESPN_ODDS_PROVIDER_PREF") or "draftkings,espn bet,fanduel,caesars").split(",")
        if x.strip()
    ]

    def provider_name(item: Dict[str, Any]) -> str:
        provider = item.get("provider")
        if isinstance(provider, dict):
            return str(provider.get("name") or provider.get("id") or "").lower().strip()
        return str(provider or "").lower().strip()

    for want in pref:
        for item in odds_items:
            if provider_name(item) == want:
                return item
    return odds_items[0]


def _parse_espn_spread(odds: Dict[str, Any], home_abbr: str, away_abbr: str) -> Tuple[Optional[float], Optional[float]]:
    details = str(odds.get("details") or "").upper().strip()
    m = re.search(r"\b([A-Z]{2,4})\b\s*([+-]\d+(?:\.\d+)?)", details)
    if m:
        fav = _canonical_abbr(m.group(1)) or m.group(1)
        spread_val = to_float(m.group(2))
        if spread_val is not None:
            if fav == home_abbr:
                return float(spread_val), float(-spread_val)
            if fav == away_abbr:
                return float(-spread_val), float(spread_val)

    raw_spread = to_float(odds.get("spread"))
    if raw_spread is None:
        return None, None
    spread_abs = abs(float(raw_spread))

    home_odds = odds.get("homeTeamOdds")
    away_odds = odds.get("awayTeamOdds")
    home_fav = isinstance(home_odds, dict) and bool(home_odds.get("favorite"))
    away_fav = isinstance(away_odds, dict) and bool(away_odds.get("favorite"))
    if home_fav and not away_fav:
        return -spread_abs, spread_abs
    if away_fav and not home_fav:
        return spread_abs, -spread_abs

    # ESPN top-level spread is commonly negative for the favorite. If there is
    # no favorite metadata, keep the sign on the home side only when details
    # cannot tell us more. This is less trusted, but still auditable by source.
    return float(raw_spread), float(-raw_spread)


def _parse_espn_moneyline(odds: Dict[str, Any], side: str) -> Optional[int]:
    key = "homeTeamOdds" if side == "home" else "awayTeamOdds"
    obj = odds.get(key)
    if not isinstance(obj, dict):
        return None
    return _to_nullable_int(obj.get("moneyLine"))


def _fetch_espn_core_odds(event_id: str, competition_id: str) -> Optional[Dict[str, Any]]:
    timeout_s = float(os.getenv("ESPN_ODDS_TIMEOUT_S", os.getenv("ROTOWIRE_TIMEOUT_S", "20")))
    url = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
        f"/events/{event_id}/competitions/{competition_id}/odds?lang=en&region=us"
    )
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=timeout_s)
        print(f"[espn-odds] status={r.status_code} bytes={len(r.content or b'')} event={event_id}")
        if r.status_code != 200:
            _write_debug(f"espn_odds_http_{r.status_code}_{event_id}.txt", (r.text or "")[:20000])
            return None
        data = r.json()
    except Exception as exc:
        _write_debug(f"espn_odds_error_{event_id}.txt", repr(exc))
        return None
    if not isinstance(data, dict):
        return None
    return _pick_espn_odds_item(data.get("items"))


def _site_odds_from_comp(comp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for source in (comp.get("odds"), comp.get("competitionOdds")):
        item = _pick_espn_odds_item(source)
        if item:
            return item
    return None


def _fetch_espn_events(game_date: str) -> List[Event]:
    timeout_s = float(os.getenv("ESPN_ODDS_TIMEOUT_S", os.getenv("ROTOWIRE_TIMEOUT_S", "20")))
    yyyymmdd = game_date.replace("-", "")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={yyyymmdd}"
    print(f"[espn-odds] GET {url}")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=timeout_s)
        print(f"[espn-odds] scoreboard status={r.status_code} bytes={len(r.content or b'')}")
        if r.status_code != 200:
            _write_debug(f"espn_scoreboard_http_{r.status_code}_{game_date}.txt", (r.text or "")[:20000])
            return []
        data = r.json()
    except Exception as exc:
        _write_debug(f"espn_scoreboard_error_{game_date}.txt", repr(exc))
        return []

    events_raw = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events_raw, list):
        return []

    out: List[Event] = []
    for ev in events_raw:
        if not isinstance(ev, dict):
            continue
        event_id = str(ev.get("id") or "").strip()
        comps = ev.get("competitions")
        if not event_id or not isinstance(comps, list) or not comps:
            continue
        comp = comps[0] if isinstance(comps[0], dict) else {}
        comp_id = str(comp.get("id") or event_id).strip()
        start = _parse_iso_z(str(comp.get("date") or ev.get("date") or ""))
        if start is None:
            continue
        gd = _espn_local_date(start)
        if gd != game_date:
            continue

        home_abbr = _espn_competitor_abbr(comp, "home")
        away_abbr = _espn_competitor_abbr(comp, "away")
        if not home_abbr or not away_abbr:
            continue

        odds = _site_odds_from_comp(comp) or _fetch_espn_core_odds(event_id, comp_id)
        if not isinstance(odds, dict):
            continue

        home_spread, away_spread = _parse_espn_spread(odds, home_abbr, away_abbr)
        ou = to_float(odds.get("overUnder") or odds.get("total") or odds.get("ou"))
        if home_spread is None and away_spread is None and ou is None:
            continue

        provider = odds.get("provider")
        if isinstance(provider, dict):
            provider_name = str(provider.get("name") or provider.get("id") or "espn")
        else:
            provider_name = str(provider or "espn")

        out.append(
            Event(
                gameID=event_id,
                eventTime=int(start.timestamp()),
                game_date=gd,
                homeTeam=home_abbr,
                awayTeam=away_abbr,
                home_spread=home_spread,
                away_spread=away_spread,
                home_ml=_parse_espn_moneyline(odds, "home"),
                away_ml=_parse_espn_moneyline(odds, "away"),
                ou=ou,
                source=f"espn:{provider_name.lower().replace(' ', '_')}",
            )
        )

    return out


def _write_event_fallback(
    *,
    source: str,
    note: str,
    events: List[Event],
    out_path: Path,
    last_good_path: Path,
) -> None:
    out_obj = {
        "sport": "NBA",
        "source": source,
        "date": events[0].game_date if events else "",
        "events": [e.to_json() for e in events],
        "fetched_at": _now_utc_iso(),
        "note": note,
    }
    _write_json_atomic(out_path, out_obj)
    _maybe_archive_live_rotowire(out_path)
    _write_json_atomic(last_good_path, out_obj)


# -----------------------------
# Last-good fallback
# -----------------------------
def _load_last_good(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict) and isinstance(obj.get("events"), list) and len(obj["events"]) > 0:
            return obj
    except Exception:
        return None
    return None


def _load_date_pinned_fallback(path: Path, game_date: str) -> Optional[Tuple[Dict[str, Any], Path]]:
    candidates: List[Path] = [path]

    for root in (
        _repo_root() / "data" / "archives" / "iael",
        _repo_root() / "archives" / "bundles",
    ):
        if root.exists():
            candidates.extend(root.rglob("rotowire_lines.json"))
            candidates.extend(root.rglob("rotowire_lines_last_good.json"))

    seen: set[Path] = set()
    best: Optional[Tuple[Tuple[int, str, str], Dict[str, Any], Path]] = None
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        obj = _load_last_good(candidate)
        if obj is None:
            continue

        if str(obj.get("date", "")).strip() == game_date:
            resolved = candidate.resolve()
            default_resolved = path.resolve()
            timestamp_matches = re.findall(r"\d{8}_\d{6}Z", str(candidate))
            timestamp = timestamp_matches[-1] if timestamp_matches else ""
            key = (1 if resolved == default_resolved else 0, timestamp, str(candidate))
            if best is None or key > best[0]:
                best = (key, obj, candidate)

    if best is None:
        return None
    return best[1], best[2]


def _write_fallback_output(out_path: Path, last_good_path: Path, obj: Dict[str, Any], note: str) -> None:
    out_obj = dict(obj)
    out_obj["note"] = note
    out_obj["fetched_at"] = _now_utc_iso()
    _write_json_atomic(out_path, out_obj)
    if last_good_path.resolve() != out_path.resolve():
        _write_json_atomic(last_good_path, out_obj)
    _maybe_archive_live_rotowire(out_path)


def _write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _events_have_market_context(events: List[Event]) -> bool:
    for ev in events:
        if ev.home_spread is not None and ev.away_spread is not None:
            return True
        if ev.ou is not None:
            return True
    return False


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def _today_dashed_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _resolve_archive_ids() -> Tuple[Optional[str], str, str]:
    run_id = os.environ.get("ATLAS_RUN_ID") or None
    snapshot_id = os.environ.get("ATLAS_SNAPSHOT_ID") or _utc_compact()
    date_dashed = os.environ.get("ATLAS_ASOF_DATE_DASHED") or _today_dashed_utc()
    return run_id, snapshot_id, date_dashed


def _maybe_archive_live_rotowire(out_path: Path) -> None:
    """
    Additive live-only archive copy for backtest fidelity.

    Rules:
    - archive only when writing the canonical live latest file
    - do nothing for replay/backtest/overridden paths
    - never interfere with the normal live write path
    """
    try:
        if out_path.resolve() != _default_out_path().resolve():
            return

        run_id, snapshot_id, date_dashed = _resolve_archive_ids()
        year = date_dashed[0:4]
        snap_dir = _repo_root() / "data" / "archives" / "iael" / year / date_dashed / snapshot_id
        snap_dir.mkdir(parents=True, exist_ok=True)

        dst = snap_dir / "rotowire_lines.json"
        shutil.copy2(out_path, dst)

        manifest = {
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "date": date_dashed,
            "rotowire_snapshot_dir": str(snap_dir),
            "rotowire_src": str(out_path),
            "rotowire_dst": str(dst),
            "fetched_at": _now_utc_iso(),
        }
        (snap_dir / "rotowire_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[rotowire] archive skipped: {e!r}")


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    timeout_s = float(os.getenv("ROTOWIRE_TIMEOUT_S", "20"))
    book = os.getenv("ROTOWIRE_BOOK", "mgm")
    allow_empty = os.getenv("ROTOWIRE_ALLOW_EMPTY", "0").strip() == "1"

    spread_field, ml_field, ou_field = _pick_book_fields(book)

    game_date = _maybe_env("ROTOWIRE_GAME_DATE")
    url = _maybe_env("ROTOWIRE_LINES_URL")

    if not game_date:
        game_date = datetime.now().strftime("%Y-%m-%d")

    out_path = Path(os.getenv("ROTOWIRE_OUT_PATH", str(_default_out_path())))
    last_good_path = Path(os.getenv("ROTOWIRE_LAST_GOOD_PATH", str(_default_last_good_path())))

    if os.getenv("ROTOWIRE_FORCE_ESPN_FALLBACK", "0").strip() == "1":
        espn_events = _fetch_espn_events(game_date)
        if espn_events and _events_have_market_context(espn_events):
            _write_event_fallback(
                source="espn_scoreboard/core_odds (forced fallback)",
                note="FALLBACK_USED: espn odds (forced repair)",
                events=espn_events,
                out_path=out_path,
                last_good_path=last_good_path,
            )
            print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FORCED FALLBACK")
            return 0
        print("[espn-odds] forced fallback requested but no ESPN game-line context was available")
        if allow_empty:
            return 0
        return 7

    if not url:
        url = _build_url(game_date)

    headers = _headers_from_env()

    # Use a session so cookies persist (Rotowire often gates this endpoint behind PHPSESSID).
    sess = requests.Session()
    sess.headers.update(headers)

    php_sessid = (os.getenv("ROTOWIRE_PHPSESSID") or "").strip()
    if php_sessid:
        sess.cookies.set("PHPSESSID", php_sessid, domain="www.rotowire.com")
    else:
        _bootstrap_rotowire_session(sess, timeout_s)

    print(f"[rotowire] GET {url}")
    r = sess.get(url, timeout=timeout_s)
    body = r.content or b""
    print(f"[rotowire] status={r.status_code} bytes={len(body)}")

    # -----------------------------
    # HTTP non-200
    # -----------------------------
    if r.status_code != 200:
        _write_debug(f"rotowire_http_{r.status_code}_{game_date}.txt", (r.text or "")[:10000])

        espn_events = _fetch_espn_events(game_date)
        if espn_events and _events_have_market_context(espn_events):
            _write_event_fallback(
                source="espn_scoreboard/core_odds (fallback)",
                note=f"FALLBACK_USED: espn odds (rotowire http_{r.status_code})",
                events=espn_events,
                out_path=out_path,
                last_good_path=last_good_path,
            )
            print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FALLBACK")
            return 0

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": f"FALLBACK_USED: oddsapi (rotowire http_{r.status_code})",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        fallback = _load_date_pinned_fallback(last_good_path, game_date)
        if fallback is not None:
            lg, source_path = fallback
            _write_fallback_output(out_path, last_good_path, lg, f"DATE_PINNED_FALLBACK_USED: http_{r.status_code}")
            print(f"[rotowire] wrote {out_path} (events={len(lg['events'])}) using fallback from {source_path}")
            return 0

        return 2

    # -----------------------------
    # Rotowire returned HTML (cookie-gated)
    # -----------------------------
    ct = (r.headers.get("Content-Type") or "").lower()
    if "text/html" in ct:
        _write_debug(f"rotowire_html_{game_date}.html", (r.text or "")[:200000])

        espn_events = _fetch_espn_events(game_date)
        if espn_events and _events_have_market_context(espn_events):
            _write_event_fallback(
                source="espn_scoreboard/core_odds (fallback)",
                note="FALLBACK_USED: espn odds (rotowire got_html)",
                events=espn_events,
                out_path=out_path,
                last_good_path=last_good_path,
            )
            print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FALLBACK")
            return 0

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": "FALLBACK_USED: oddsapi (rotowire got_html)",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        fallback = _load_date_pinned_fallback(last_good_path, game_date)
        if fallback is not None:
            lg, source_path = fallback
            _write_fallback_output(out_path, last_good_path, lg, "DATE_PINNED_FALLBACK_USED: got_html")
            print(f"[rotowire] wrote {out_path} (events={len(lg['events'])}) using fallback from {source_path}")
            return 0

        if allow_empty:
            return 0
        return 3

    # -----------------------------
    # Parse JSON body
    # -----------------------------
    try:
        payload = r.json()
    except Exception as e:
        _write_debug(f"rotowire_not_json_{game_date}.txt", (r.text or "")[:10000])

        espn_events = _fetch_espn_events(game_date)
        if espn_events and _events_have_market_context(espn_events):
            _write_event_fallback(
                source="espn_scoreboard/core_odds (fallback)",
                note=f"FALLBACK_USED: espn odds (rotowire not_json:{type(e).__name__})",
                events=espn_events,
                out_path=out_path,
                last_good_path=last_good_path,
            )
            print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FALLBACK")
            return 0

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [x.to_json() for x in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": f"FALLBACK_USED: oddsapi (rotowire not_json:{type(e).__name__})",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        fallback = _load_date_pinned_fallback(last_good_path, game_date)
        if fallback is not None:
            lg, source_path = fallback
            _write_fallback_output(out_path, last_good_path, lg, f"DATE_PINNED_FALLBACK_USED: not_json:{type(e).__name__}")
            print(f"[rotowire] wrote {out_path} (events={len(lg['events'])}) using fallback from {source_path}")
            return 0

        if allow_empty:
            return 0
        return 4

    rows = _normalize_rows_shape(payload)

    # One-time bootstrap+retry if empty and we didn't explicitly provide PHPSESSID.
    if not rows and not php_sessid:
        _bootstrap_rotowire_session(sess, timeout_s)
        try:
            r2 = sess.get(url, timeout=timeout_s)
            if r2.status_code == 200:
                payload2 = r2.json()
                rows2 = _normalize_rows_shape(payload2)
                if rows2:
                    payload = payload2
                    rows = rows2
        except Exception:
            pass

    # If rotowire literally returned [] (bytes=2), rows will be empty.
    if not rows:
        _write_debug(
            f"rotowire_empty_rows_{game_date}.json",
            json.dumps(payload, ensure_ascii=False)[:200000],
        )

        espn_events = _fetch_espn_events(game_date)
        if espn_events and _events_have_market_context(espn_events):
            _write_event_fallback(
                source="espn_scoreboard/core_odds (fallback)",
                note="FALLBACK_USED: espn odds (rotowire empty_rows)",
                events=espn_events,
                out_path=out_path,
                last_good_path=last_good_path,
            )
            print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FALLBACK")
            return 0

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": "FALLBACK_USED: oddsapi (rotowire empty_rows)",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        fallback = _load_date_pinned_fallback(last_good_path, game_date)
        if fallback is not None:
            lg, source_path = fallback
            _write_fallback_output(out_path, last_good_path, lg, "DATE_PINNED_FALLBACK_USED: empty_rows")
            print(f"[rotowire] wrote {out_path} (events={len(lg['events'])}) using fallback from {source_path}")
            return 0

        out_obj = {
            "sport": "NBA",
            "source": "rotowire.com/betting/nba/tables/nba-games-by-market.php",
            "date": game_date,
            "events": [],
            "fetched_at": _now_utc_iso(),
            "note": "No rows returned from endpoint (schema change, blocked, or empty slate).",
        }
        _write_json_atomic(out_path, out_obj)
        print(f"[rotowire] wrote {out_path} (events=0) at {_now_utc_iso()}")

        if allow_empty:
            return 0
        return 5

    # -----------------------------
    # Build events from Rotowire rows
    # -----------------------------
    games: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        gid = str(row.get("gameID", "")).strip()
        if gid:
            games.setdefault(gid, []).append(row)

    events: List[Event] = []
    for gid, grp in games.items():
        if len(grp) < 2:
            continue

        def ha_tag(x: Dict[str, Any]) -> str:
            return str(x.get("homeAway", "")).strip().lower()

        home = next((x for x in grp if ha_tag(x) == "home"), None)
        away = next((x for x in grp if ha_tag(x) == "away"), None)
        if home is None or away is None:
            home, away = grp[0], grp[1]

        home_team = str(home.get("abbr", "")).strip() or str(home.get("team", "")).strip()
        away_team = str(away.get("abbr", "")).strip() or str(away.get("team", "")).strip()
        if not home_team or not away_team:
            continue

        event_time = _parse_game_date_epoch(str(home.get("gameDate", "") or ""), game_date)

        home_spread = to_float(home.get(spread_field))
        away_spread = to_float(away.get(spread_field))
        home_ml = _to_nullable_int(home.get(ml_field))
        away_ml = _to_nullable_int(away.get(ml_field))

        ou_val = home.get(ou_field) if home.get(ou_field) is not None else away.get(ou_field)
        ou = to_float(ou_val)

        events.append(
            Event(
                gameID=gid,
                eventTime=event_time,
                game_date=game_date,
                homeTeam=home_team,
                awayTeam=away_team,
                home_spread=home_spread,
                away_spread=away_spread,
                home_ml=home_ml,
                away_ml=away_ml,
                ou=ou,
                source=book.lower(),
            )
        )

    out_obj: Dict[str, Any] = {
        "sport": "NBA",
        "source": "rotowire.com/betting/nba/tables/nba-games-by-market.php",
        "date": game_date,
        "events": [e.to_json() for e in events],
        "fetched_at": _now_utc_iso(),
    }

    if events and not _events_have_market_context(events):
        print("[rotowire] events returned but spreads/totals are all empty; trying fallback context")

        espn_events = _fetch_espn_events(game_date)
        if espn_events and _events_have_market_context(espn_events):
            _write_event_fallback(
                source="espn_scoreboard/core_odds (fallback)",
                note="FALLBACK_USED: espn odds (rotowire null market context)",
                events=espn_events,
                out_path=out_path,
                last_good_path=last_good_path,
            )
            print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FALLBACK")
            return 0

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events and _events_have_market_context(oa_events):
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": "FALLBACK_USED: oddsapi (rotowire null market context)",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        fallback = _load_date_pinned_fallback(last_good_path, game_date)
        if fallback is not None:
            lg, source_path = fallback
            fallback_events = []
            try:
                for ev in lg.get("events", []):
                    spread = ev.get("spread", {}) if isinstance(ev, dict) else {}
                    fallback_events.append(
                        Event(
                            gameID=str(ev.get("gameID", "")),
                            eventTime=int(ev.get("eventTime", 0) or 0),
                            game_date=str(ev.get("game_date", game_date)),
                            homeTeam=str(ev.get("homeTeam", "")),
                            awayTeam=str(ev.get("awayTeam", "")),
                            home_spread=to_float(spread.get("home")),
                            away_spread=to_float(spread.get("away")),
                            home_ml=None,
                            away_ml=None,
                            ou=to_float(ev.get("ou")),
                            source=str(ev.get("source", "fallback")),
                        )
                    )
            except Exception:
                fallback_events = []
            if fallback_events and _events_have_market_context(fallback_events):
                _write_fallback_output(out_path, last_good_path, lg, "DATE_PINNED_FALLBACK_USED: rotowire_null_market_context")
                print(f"[rotowire] wrote {out_path} (events={len(lg['events'])}) using fallback from {source_path}")
                return 0

        out_obj["note"] = "Rotowire returned events, but all spread/total fields were empty."

    _write_json_atomic(out_path, out_obj)
    _maybe_archive_live_rotowire(out_path)
    print(f"[rotowire] wrote {out_path} (events={len(events)}) at {_now_utc_iso()}")

    # Update last-good if we actually have events
    if events:
        _write_json_atomic(last_good_path, out_obj)
        print(f"[rotowire] updated last-good: {last_good_path}")
        return 0

    # -----------------------------
    # Parsed rows but produced zero events -> fallback chain
    # -----------------------------
    _write_debug(
        f"rotowire_zero_events_{game_date}.json",
        json.dumps(rows, ensure_ascii=False)[:200000],
    )

    espn_events = _fetch_espn_events(game_date)
    if espn_events and _events_have_market_context(espn_events):
        _write_event_fallback(
            source="espn_scoreboard/core_odds (fallback)",
            note="FALLBACK_USED: espn odds (rotowire parsed_zero_events)",
            events=espn_events,
            out_path=out_path,
            last_good_path=last_good_path,
        )
        print(f"[espn-odds] wrote {out_path} (events={len(espn_events)}) using FALLBACK")
        return 0

    oa_events = _fetch_oddsapi_events(game_date)
    if oa_events:
        out_obj = {
            "sport": "NBA",
            "source": "the-odds-api.com/v4 (fallback)",
            "date": game_date,
            "events": [e.to_json() for e in oa_events],
            "fetched_at": _now_utc_iso(),
            "note": "FALLBACK_USED: oddsapi (rotowire parsed_zero_events)",
        }
        _write_json_atomic(out_path, out_obj)
        _write_json_atomic(last_good_path, out_obj)
        print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
        return 0

    fallback = _load_date_pinned_fallback(last_good_path, game_date)
    if fallback is not None:
        lg, source_path = fallback
        _write_fallback_output(out_path, last_good_path, lg, "DATE_PINNED_FALLBACK_USED: parsed_zero_events")
        print(f"[rotowire] wrote {out_path} (events={len(lg['events'])}) using fallback from {source_path}")
        return 0

    if allow_empty:
        return 0
    return 6


if __name__ == "__main__":
    sys.exit(main())
