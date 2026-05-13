from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence
from zoneinfo import ZoneInfo

import requests

from Atlas.engine.new_probability import _team_to_abbr
from Atlas.runtime.archive_writer import archive_json_pair, resolve_archive_ids
from Atlas.runtime.paths import find_repo_root
import subprocess

# ---------------------------------------------------------------------
# Source page contains links for the season
# ---------------------------------------------------------------------

SEASON_PAGE = "https://official.nba.com/nba-injury-report-2025-26-season/"
PDF_RE = re.compile(
    r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{1,2})_(\d{2})(AM|PM)\.pdf"
)

UA = {"User-Agent": "Atlas/IAEL"}

# IAEL hard removal statuses (per your spec)
HARD_INVALID = {"OUT", "DOUBTFUL"}
TAG_ONLY = {"PROBABLE"}

def status_to_out_frac(status: str) -> float:
    """
    Deterministic 'removed budget' proxy for role context.
    Keep conservative so it doesn't swing the model wildly.
    """
    s = (status or "").strip().upper()
    if s == "OUT":
        return 0.12
    if s == "DOUBTFUL":
        return 0.08
    # PROBABLE/AVAILABLE/etc. contribute 0 removed budget
    return 0.0

VALID_TEAM_ABBRS = {
  "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
  "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
  "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
}
# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

ROOT = find_repo_root(Path(__file__))

OUT_DIR = ROOT / "data" / "output"
DASH_DIR = OUT_DIR / "dashboard"

INJ_DIR = OUT_DIR / "injury"
RAW_DIR = INJ_DIR / "raw"
NORM_DIR = INJ_DIR / "normalized"
STATE_DIR = INJ_DIR / "state"

for p in (DASH_DIR, RAW_DIR, NORM_DIR, STATE_DIR):
    p.mkdir(parents=True, exist_ok=True)

# State pointer is NOT the same as dashboard status.
STATE_LATEST = STATE_DIR / "latest.json"

# Dashboard artifacts legacy uses
STATUS_LATEST = DASH_DIR / "status_latest.json"
INVALIDATIONS_LATEST = DASH_DIR / "injury_invalidations_latest.json"


# ---------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------

def now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# HTTP and link discovery
# ---------------------------------------------------------------------

def fetch_html(url: str, timeout: int = 30) -> str:
    r = requests.get(url, timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.text


def extract_latest_pdf_url_for_date(html: str, target_date: str) -> Optional[Tuple[str, str]]:
    """
    Returns (pdf_url, report_label) for the latest PDF on target_date.
    report_label is filename-derived time string like '02:30PM'.
    """
    matches = PDF_RE.findall(html)
    candidates: List[Tuple[int, str, str]] = []

    for d, hh, mm, ap in matches:
        if d != target_date:
            continue

        h = int(hh)
        m = int(mm)
        if ap == "AM":
            h24 = 0 if h == 12 else h
        else:
            h24 = 12 if h == 12 else h + 12

        key = h24 * 60 + m
        url = f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{hh}_{mm}{ap}.pdf"
        label = f"{hh}:{mm}{ap}"
        candidates.append((key, url, label))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    _, url, label = candidates[-1]
    return url, label


def download_pdf(url: str, out_path: Path, timeout: int = 60) -> bytes:
    r = requests.get(url, timeout=timeout, headers=UA)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return r.content


def pdf_to_txt(pdf_path: Path, txt_path: Path) -> None:
    """
    Convert PDF to text using pdftotext with -layout option.
    Only runs if txt_path doesn't already exist.
    """
    if txt_path.exists():
        return
    
    subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
        check=True,
    )


# ---------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------

def normalize_status(s: str) -> str:
    s2 = (s or "").strip().upper()
    if s2 in {"PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT", "AVAILABLE"}:
        return s2
    return s2


DATE_PREFIX_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")
TIME_RE = re.compile(r"^\d{2}:\d{2}\b")


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _parse_line_player_status_reason(tokens: Sequence[str]) -> Optional[Tuple[str, str, str]]:
    """
    Given tokens starting at player (Lastname,Firstname ...), find a status token and split.
    Returns (player, status, reason).
    """
    if not tokens:
        return None

    # Find the first token that looks like a status
    status_idx = None
    for i in range(0, min(len(tokens), 10)):
        t = (tokens[i] or "").strip().upper()
        if t in {"PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT", "AVAILABLE"}:
            status_idx = i
            break

    if status_idx is None:
        return None

    player = " ".join(tokens[:status_idx]).strip()
    
    # Require comma somewhere in the player string, not necessarily token 0
    if "," not in player:
        return None
    
    status = tokens[status_idx].strip()
    reason = " ".join(tokens[status_idx + 1 :]).strip()
    return player, status, reason


def _is_matchup(tok: str) -> bool:
    """Check if token is a matchup like XXX@YYY"""
    t = (tok or "").strip()
    return ("@" in t) and (len(t) >= 5) and (len(t) <= 9)


def _find_matchup_index(tokens: List[str]) -> Optional[int]:
    """Find the index of the first matchup token in the token list."""
    for i, tok in enumerate(tokens):
        if _is_matchup(tok):
            return i
    return None


def _team_abbr_from_tokens(tokens: List[str]) -> str:
    """Convert team name tokens to abbreviation."""
    s = " ".join(tokens).strip()
    if not s:
        return ""
    u = s.upper()
    if len(u) == 3 and u.isalpha() and u in VALID_TEAM_ABBRS:
        return u
    abbr = (_team_to_abbr(s) or "").upper()
    return abbr if abbr in VALID_TEAM_ABBRS else ""


TEAM_NAME_FIRST_TOKENS = {
    "ATLANTA",
    "BOSTON",
    "BROOKLYN",
    "CHARLOTTE",
    "CHICAGO",
    "CLEVELAND",
    "DALLAS",
    "DENVER",
    "DETROIT",
    "GOLDEN",
    "HOUSTON",
    "INDIANA",
    "LA",
    "LOS",
    "MEMPHIS",
    "MIAMI",
    "MILWAUKEE",
    "MINNESOTA",
    "NEW",
    "OKLAHOMA",
    "ORLANDO",
    "PHILADELPHIA",
    "PHOENIX",
    "PORTLAND",
    "SACRAMENTO",
    "SAN",
    "TORONTO",
    "UTAH",
    "WASHINGTON",
}


def parse_txt_rows_text(txt_path: Path) -> List[Dict[str, str]]:
    out_rows: List[Dict[str, str]] = []
    ctx: Dict[str, str] = {"game_date": "", "game_time": "", "matchup": "", "team": ""}
    active: Optional[Dict[str, str]] = None
    pending_player: Optional[str] = None  # player name whose status arrives on the next line
    _STATUS_WORDS = {"PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT", "AVAILABLE"}

    def flush() -> None:
        nonlocal active
        if not active:
            return
        active["reason"] = _clean_ws(active.get("reason", ""))
        if active.get("team") and active.get("player") and active.get("status"):
            out_rows.append(active)
        active = None

    lines = txt_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Skip header/footer noise
        if line.startswith("Injury Report:"):
            continue
        if line.startswith("Page") and "of" in line:
            continue
        if line.startswith("Game Date") or line.startswith("GameDate"):
            continue

        tokens = line.split()
        if not tokens:
            continue
        
        # pdftotext sometimes emits a bogus 3-letter fragment (e.g. "LIV") before player tokens.
        # Comma may be a few tokens later (e.g. "LIV Naji Marshall, ..."), so scan ahead.
        if (
            len(tokens) >= 3
            and len(tokens[0]) == 3
            and tokens[0].isalpha()
            and tokens[0].upper() not in VALID_TEAM_ABBRS
            and tokens[0].upper() not in TEAM_NAME_FIRST_TOKENS
            and any("," in t for t in tokens[1:5])
        ):
            tokens = tokens[1:]
        # PENDING PLAYER: status/reason line arrives after a split player-line (pdftotext layout wrap)
        if pending_player is not None and tokens and tokens[0].upper() in _STATUS_WORDS:
            flush()
            active = {
                "team": ctx["team"],
                "player": pending_player,
                "status": normalize_status(tokens[0]),
                "reason": " ".join(tokens[1:]).strip(),
                "game_date": ctx["game_date"],
            }
            pending_player = None
            continue

        # Check for NOT YET SUBMITTED on otherwise valid game header line
        if "NOT YET SUBMITTED" in line.upper():
            # If line contains matchup, treat as game header but don't set team
            mi = _find_matchup_index(tokens)
            if mi is not None:
                flush()
                ctx["team"] = ""
            continue

        # Check for game header: any line with a matchup token
        mi = _find_matchup_index(tokens)
        if mi is not None:
            flush()
            pending_player = None  # stale pending state is invalid once a new game starts
            
            # Variant 1: Date + time + matchup
            if DATE_PREFIX_RE.match(tokens[0]):
                ctx["game_date"] = tokens[0]
                # Look for time token (HH:MM format)
                ti = None
                for i in range(1, mi):
                    if TIME_RE.match(tokens[i]):
                        ti = i
                        break
                ctx["game_time"] = tokens[ti] if ti is not None else ""
                ctx["matchup"] = tokens[mi]
                ctx["team"] = ""
                # Check if team + player follow on the same line (inline format)
                tail = tokens[mi + 1:]
                if tail:
                    for n in (4, 3, 2, 1):
                        if len(tail) <= n:
                            continue
                        team_u = _team_abbr_from_tokens(tail[:n])
                        if team_u and ("," in " ".join(tail[n:])):
                            ctx["team"] = team_u
                            psr = _parse_line_player_status_reason(tail[n:])
                            if psr:
                                player, status, reason = psr
                                flush()
                                active = {
                                    "team": ctx["team"],
                                    "player": player,
                                    "status": normalize_status(status),
                                    "reason": reason,
                                    "game_date": ctx["game_date"],
                                }
                            else:
                                # Status on the next line — store player name
                                leftover = " ".join(tail[n:]).strip()
                                if "," in leftover:
                                    pending_player = leftover
                            break
                continue
            
            # Variant 2: Time + matchup (no date) or Variant 3: Matchup only
            # Check if first token is time
            if TIME_RE.match(tokens[0]):
                ctx["game_time"] = tokens[0]
                ctx["matchup"] = tokens[mi]
            else:
                # Matchup-only: keep prior date/time, just update matchup
                ctx["matchup"] = tokens[mi]
            
            ctx["team"] = ""
            # Check if team + player follow on the same line (inline format)
            tail = tokens[mi + 1:]
            if tail:
                for n in (4, 3, 2, 1):
                    if len(tail) <= n:
                        continue
                    team_u = _team_abbr_from_tokens(tail[:n])
                    if team_u and ("," in " ".join(tail[n:])):
                        ctx["team"] = team_u
                        psr = _parse_line_player_status_reason(tail[n:])
                        if psr:
                            player, status, reason = psr
                            flush()
                            active = {
                                "team": ctx["team"],
                                "player": player,
                                "status": normalize_status(status),
                                "reason": reason,
                                "game_date": ctx["game_date"],
                            }
                        else:
                            # Status on the next line — store player name
                            leftover = " ".join(tail[n:]).strip()
                            if "," in leftover:
                                pending_player = leftover
                        break
            continue

        # REASON continuation: no matchup, no comma-leader, and we have active
        if active and (not any(_is_matchup(t) for t in tokens)) and ("," not in line):
            active["reason"] = (active.get("reason", "") + " " + line).strip()
            continue

        # TEAM HEADER row: team name tokens followed by player
        # Attempt prefixes up to 4 tokens for team name
        found_header = False
        for n in (4, 3, 2, 1):
            if len(tokens) <= n:
                continue
            team_u = _team_abbr_from_tokens(tokens[:n])
            if team_u and ("," in " ".join(tokens[n:])):
                ctx["team"] = team_u
                psr = _parse_line_player_status_reason(tokens[n:])
                if psr:
                    player, status, reason = psr
                    flush()
                    active = {
                        "team": ctx["team"],
                        "player": player,
                        "status": normalize_status(status),
                        "reason": reason,
                        "game_date": ctx["game_date"],
                    }
                found_header = True
                break
        if found_header:
            continue

        # PLAYER row: begins with Last,First (continuation under current team)
        if "," in tokens[0]:
            if not ctx["team"]:
                continue
            psr = _parse_line_player_status_reason(tokens)
            if psr:
                player, status, reason = psr
                flush()
                active = {
                    "team": ctx["team"],
                    "player": player,
                    "status": normalize_status(status),
                    "reason": reason,
                    "game_date": ctx["game_date"],
                }
            continue

        # Otherwise ignore
        continue

    flush()

    cleaned: List[Dict[str, str]] = []
    for r in out_rows:
        if r.get("player", "").strip() in {"PlayerName", "PLAYERNAME"}:
            continue
        if r.get("status", "").strip() in {"CURRENTSTATUS", "STATUS"}:
            continue
        cleaned.append(r)

    if not cleaned:
        print(f"[INJURY] No injury rows parsed from TXT: {txt_path}")
        raise RuntimeError(f"No injury rows parsed from TXT: {txt_path}")

    return cleaned

# ---------------------------------------------------------------------
# WRITE INVALIDATIONS_LATEST and STATUS_LATEST, then archive a matched pair for the dashboard to consume.
# ---------------------------------------------------------------------

def _write_invalidations_from_rows(
    *,
    report_date: str,
    report_label: str,
    pulled_at_local: str,
    rows: List[Dict[str, Any]],
) -> None:
    """
    Writes the invalidations-latest JSON ONLY.
    Archiving must happen after STATUS_LATEST is finalized for the same run path.
    """
    invalidated_players = sorted(
        {f"{r['team']}|{r['player']}|{r['status']}" for r in rows if r.get("hard_invalid")}
    )

    inv_obj = {
        "report_date": report_date,
        "report_label": report_label,
        "pulled_at_local": pulled_at_local,
        "invalidated_players_count": len(invalidated_players),
        "invalidated_players": [
            {"team": x.split("|")[0], "player": x.split("|")[1], "status": x.split("|")[2], "reason": ""}
            for x in invalidated_players
        ],
        "policy": "Remove OUT/DOUBTFUL from eligibility. PROBABLE allowed but tagged.",
    }

    write_json(INVALIDATIONS_LATEST, inv_obj)

def _archive_latest_dashboard_pair(*, run_id: Optional[str] = None, snapshot_id: Optional[str] = None) -> None:
    """
    Archive AFTER STATUS_LATEST is finalized for the current control path.
    This guarantees we snapshot a matched pair:
      - injury_invalidations_latest.json
      - status_latest.json
    """
    if run_id:
        os.environ["ATLAS_RUN_ID"] = str(run_id)
    if snapshot_id:
        os.environ["ATLAS_SNAPSHOT_ID"] = str(snapshot_id)

    ids = resolve_archive_ids()

    archive_json_pair(
        repo_root=ROOT,
        iael_invalidations_latest=INVALIDATIONS_LATEST,
        iael_status_latest=STATUS_LATEST,
        ids=ids,
    )


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    TZ_CT = ZoneInfo("America/Chicago")
    now_ct = dt.datetime.now(tz=TZ_CT)
    target_date = now_ct.date().isoformat()
    pulled_at = now_ct.isoformat(timespec="seconds")

    print(f"[INJURY] target_date={target_date}")

    html = fetch_html(SEASON_PAGE)
    latest = extract_latest_pdf_url_for_date(html, target_date)

    # DEAD PERIOD: no PDF for today -- emit empty invalidations and status, archive, and exit with error
    if latest is None:
        print(f"[INJURY] No PDF links found for date {target_date}")

        status = {
            "pulled_at_local": pulled_at,
            "source": "official.nba.com season page",
            "error": f"No PDF links found for date {target_date}. No IAEL will be produced.",
            "dead_period": True,
            "post_iael": False,
            "post_line_recon": False,
        }
        write_json(STATUS_LATEST, status)

        # ✅ Archive AFTER final status write (hard error path)
        _archive_latest_dashboard_pair()
        raise RuntimeError(status["error"])

    # Normal path: we have a PDF for today
    pdf_url, report_label = latest

    raw_name = f"{target_date}_{report_label.replace(':', '_')}.pdf"
    raw_path = RAW_DIR / raw_name

    pdf_bytes = download_pdf(pdf_url, raw_path)
    pdf_hash = sha1_bytes(pdf_bytes)
    
    txt_name = f"{pdf_hash}.txt"
    txt_path = RAW_DIR / txt_name
    pdf_to_txt(raw_path, txt_path)
    rows = parse_txt_rows_text(txt_path)

    normalized: List[Dict[str, Any]] = []
    for r in rows:
        st = normalize_status(r.get("status", ""))
        normalized.append(
            {
                "report_date": target_date,
                "report_label": report_label,
                "team": r.get("team", ""),
                "player": r.get("player", ""),
                "status": st,
                "reason": (r.get("reason") or "").strip(),
                "game_date": r.get("game_date", ""),
                "hard_invalid": st in HARD_INVALID,
                "tag_probable": st in TAG_ONLY,
                "out_frac": status_to_out_frac(st),
            }
        )

    norm_name = f"{target_date}_{report_label.replace(':', '_')}.json"
    norm_path = NORM_DIR / norm_name

    write_json(
        norm_path,
        {
            "report_date": target_date,
            "report_label": report_label,
            "source_url": pdf_url,
            "pulled_at_local": pulled_at,
            "pdf_sha1": pdf_hash,
            "rows": normalized,
        },
    )

    # Emit invalidations dashboard artifact
    _write_invalidations_from_rows(
        report_date=target_date,
        report_label=report_label,
        pulled_at_local=pulled_at,
        rows=normalized,
    )

    status_obj = {
        "report_datetime_local": f"{target_date} {report_label}",
        "pulled_at_local": pulled_at,
        "source": "NBA injury report PDF (latest-of-day via season page scrape)",
        "source_url": pdf_url,
        "pdf_sha1": pdf_hash,
        "post_iael": True,
        "post_line_recon": False,
        "dead_period": False,
        "notes": "IAEL completed. Injury rows parsed via text (table extraction unreliable).",
    }
    write_json(STATUS_LATEST, status_obj)

    # ✅ Archive AFTER final status write (success terminal path)
    _archive_latest_dashboard_pair()

    invalid_count = int(read_json(INVALIDATIONS_LATEST).get("invalidated_players_count", 0))
    print(f"OK: pulled {pdf_url} -> {norm_path.name} (rows={len(normalized)}) invalid={invalid_count}")


if __name__ == "__main__":
    main()
