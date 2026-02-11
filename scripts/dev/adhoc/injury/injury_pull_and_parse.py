import re
import json
import hashlib
import datetime as dt
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()

from typing import Dict, List, Optional, Tuple

import requests
import pdfplumber

# ---------------------------------------------------------------------
# Source page contains links for the season
# ---------------------------------------------------------------------

SEASON_PAGE = "https://official.nba.com/nba-injury-report-2025-26-season/"
PDF_RE = re.compile(
    r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf"
)

# IAEL hard removal statuses (per your spec)
HARD_INVALID = {"OUT", "DOUBTFUL", "QUESTIONABLE"}
TAG_ONLY = {"PROBABLE"}

ROOT = find_repo_root(Path(__file__))
OUT_DIR = ROOT / "data" / "output"
DASH_DIR = OUT_DIR / "dashboard"
INJ_DIR = OUT_DIR / "injury"
RAW_DIR = INJ_DIR / "raw"
NORM_DIR = INJ_DIR / "normalized"
STATE_DIR = INJ_DIR / "state"

for p in [DASH_DIR, RAW_DIR, NORM_DIR, STATE_DIR]:
    p.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Atlas/IAEL"}


def now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_html(url: str, timeout: int = 30) -> str:
    r = requests.get(url, timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.text


def extract_latest_pdf_url_for_date(html: str, target_date: str) -> Optional[Tuple[str, str]]:
    """
    Returns (pdf_url, report_label) for the latest PDF on target_date.
    report_label is the filename-derived time string like '02:30PM'.
    """
    matches = PDF_RE.findall(html)
    candidates = []
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


def normalize_status(s: str) -> str:
    s = (s or "").strip().upper()
    # Normalize common variants
    s = s.replace("PROBABLE", "PROBABLE")
    s = s.replace("QUESTIONABLE", "QUESTIONABLE")
    s = s.replace("DOUBTFUL", "DOUBTFUL")
    s = s.replace("OUT", "OUT")
    s = s.replace("AVAILABLE", "AVAILABLE")
    return s


DATE_PREFIX_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")


def _parse_line_player_status_reason(tokens: List[str]) -> Optional[Tuple[str, str, str]]:
    """
    Given tokens starting at player (Lastname,Firstname ...), find a status token and split.
    Returns (player, status, reason).
    """
    if not tokens:
        return None

    # first token should contain comma for player
    if "," not in tokens[0]:
        return None

    # locate status token
    status_idx = None
    for i, t in enumerate(tokens):
        tl = t.strip().lower()
        if tl in ("available", "out", "questionable", "doubtful", "probable"):
            status_idx = i
            break

    if status_idx is None:
        return None

    player = " ".join(tokens[:status_idx]).strip()
    status = tokens[status_idx].strip()
    reason = " ".join(tokens[status_idx + 1 :]).strip()
    return player, status, reason


def parse_pdf_rows_text(pdf_path: Path) -> List[Dict]:
    """
    Text-based state-machine parser for modern NBA injury PDFs.
    Handles wrapped rows and continuation lines.

    Emits rows with:
      team, player, status, reason, game_date
    """
    out_rows: List[Dict] = []

    # context across wrapped lines
    ctx = {"game_date": "", "team": ""}

    active: Optional[Dict] = None

    def flush():
        nonlocal active
        if active:
            # squash whitespace
            if active.get("reason"):
                active["reason"] = re.sub(r"\s+", " ", str(active["reason"]).strip())
            out_rows.append(active)
            active = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                # skip obvious header/footer noise
                if line.startswith("Injury Report:"):
                    continue
                if line.startswith("Page") and "of" in line:
                    continue
                if line.startswith("GameDate") and "PlayerName" in line:
                    continue

                tokens = line.split()
                if not tokens:
                    continue

                # FULL ROW begins with a date
                # Example: 02/08/2026 02:00(ET) MIA@WAS MiamiHeat Adebayo,Bam Available Injury/...
                if DATE_PREFIX_RE.match(tokens[0]):
                    # expect: date time matchup team <player...>
                    if len(tokens) >= 5:
                        ctx["game_date"] = tokens[0]
                        ctx["team"] = tokens[3]  # team token is usually here in extracted text
                        rest = tokens[4:]
                        psr = _parse_line_player_status_reason(rest)
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

                # TEAM HEADER ROW (team then player)
                # Example: WashingtonWizards Coulibaly,Bilal Available Injury/...
                if len(tokens) >= 3 and ("," not in tokens[0]) and ("," in tokens[1]):
                    ctx["team"] = tokens[0]
                    psr = _parse_line_player_status_reason(tokens[1:])
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

                # PLAYER CONTINUATION ROW (no date, no team)
                # Example: Herro,Tyler Out Injury/Illness-...
                if "," in tokens[0]:
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

                # REASON SPILLOVER
                if active:
                    active["reason"] = (active.get("reason") or "") + " " + line

    flush()

    # Filter out the garbage header row if it ever sneaks in
    cleaned = []
    for r in out_rows:
        if r.get("player", "").strip() in {"PlayerName", "PLAYERNAME"}:
            continue
        if r.get("status", "").strip() in {"CURRENTSTATUS", "STATUS"}:
            continue
        cleaned.append(r)

    return cleaned


def main():
    target_date = dt.date.today().isoformat()
    pulled_at = now_local_iso()

    # Find latest PDF link for today (prevents 403 for fake timestamps)
    html = fetch_html(SEASON_PAGE)
    latest = extract_latest_pdf_url_for_date(html, target_date)
    if latest is None:
        status = {
            "pulled_at_local": pulled_at,
            "source": "official.nba.com season page",
            "error": f"No PDF links found for date {target_date}",
            "post_iael": False,
            "post_line_recon": False,
        }
        write_json(DASH_DIR / "status_latest.json", status)
        print(status["error"])
        return

    pdf_url, report_label = latest

    # Download
    raw_name = f"{target_date}_{report_label.replace(':','_')}.pdf"
    raw_path = RAW_DIR / raw_name
    pdf_bytes = download_pdf(pdf_url, raw_path)
    pdf_hash = sha1_bytes(pdf_bytes)

    # Parse (TEXT, not tables)
    rows = parse_pdf_rows_text(raw_path)

    normalized = []
    for r in rows:
        status = normalize_status(r.get("status", ""))
        normalized.append({
            "report_date": target_date,
            "report_label": report_label,
            "team": r.get("team", ""),
            "player": r.get("player", ""),
            "status": status,
            "reason": (r.get("reason") or "").strip(),
            "game_date": r.get("game_date", ""),
            "hard_invalid": status in HARD_INVALID,
            "tag_probable": status in TAG_ONLY,
        })

    norm_name = f"{target_date}_{report_label.replace(':','_')}.json"
    norm_path = NORM_DIR / norm_name
    write_json(norm_path, {
        "report_date": target_date,
        "report_label": report_label,
        "source_url": pdf_url,
        "pulled_at_local": pulled_at,
        "pdf_sha1": pdf_hash,
        "rows": normalized,
    })

    # IAEL invalidations
    invalidated_players = sorted(
        {f"{r['team']}|{r['player']}|{r['status']}" for r in normalized if r["hard_invalid"]}
    )
    inv_obj = {
        "report_date": target_date,
        "report_label": report_label,
        "pulled_at_local": pulled_at,
        "invalidated_players_count": len(invalidated_players),
        "invalidated_players": [
            {"team": x.split("|")[0], "player": x.split("|")[1], "status": x.split("|")[2], "reason": ""}
            for x in invalidated_players
        ],
        "policy": "Remove OUT/DOUBTFUL/QUESTIONABLE from eligibility. PROBABLE allowed but tagged.",
    }
    write_json(DASH_DIR / "injury_invalidations_latest.json", inv_obj)

    status_obj = {
        "report_datetime_local": f"{target_date} {report_label}",
        "pulled_at_local": pulled_at,
        "source": "NBA injury report PDF (latest-of-day via season page scrape)",
        "source_url": pdf_url,
        "pdf_sha1": pdf_hash,
        "post_iael": True,
        "post_line_recon": False,
        "notes": "IAEL completed. Injury rows parsed via text (table extraction unreliable).",
    }
    write_json(DASH_DIR / "status_latest.json", status_obj)

    print(f"OK: pulled {pdf_url} -> {norm_path.name} (rows={len(normalized)}) invalid={len(invalidated_players)}")


if __name__ == "__main__":
    main()