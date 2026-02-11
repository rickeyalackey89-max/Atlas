import re
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
TODAY = PROJECT_ROOT / "data" / "board" / "today.csv"
REC4 = PROJECT_ROOT / "data" / "output" / "latest" / "all" / "recommended_4leg.csv"
REC5 = PROJECT_ROOT / "data" / "output" / "latest" / "all" / "recommended_5leg.csv"

ID_RE = re.compile(r"\[id:(\d+)\]")

# Try to capture "... STAT <line> (TIER) [id:####]"
# We'll just pull a number that appears before "(...)[id:####]" in that leg segment.
LINE_NEAR_ID_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*\([A-Z]+\)\s*\[id:(\d+)\]")


def extract_ids(legs: str) -> list[str]:
    if not isinstance(legs, str):
        return []
    return ID_RE.findall(legs)


def load_today() -> pd.DataFrame:
    df = pd.read_csv(TODAY)
    df["projection_id"] = df["projection_id"].astype(str)
    df["player"] = df["player"].astype(str)
    df["stat"] = df["stat"].astype(str).str.upper().str.strip()
    df["direction"] = df["direction"].astype(str).str.upper().str.strip()
    df["tier"] = df.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    df["line"] = pd.to_numeric(df["line"], errors="coerce")

    df["more_allowed"] = pd.to_numeric(df.get("more_allowed", 1), errors="coerce").fillna(0).astype(int)
    df["less_allowed"] = pd.to_numeric(df.get("less_allowed", 1), errors="coerce").fillna(0).astype(int)
    return df


def _line_variants(x: float) -> set[str]:
    """
    Accept common textual renderings of the same numeric line:
      15.0 -> {"15", "15.0"}
      1.5  -> {"1.5"}
      10.25 -> {"10.25"}
    """
    if x is None:
        return set()
    try:
        v = float(x)
    except Exception:
        return set()

    out = {str(v)}
    # integer-ish -> accept "15"
    if abs(v - round(v)) < 1e-9:
        out.add(str(int(round(v))))
    # also accept one-decimal representation (common for half lines)
    out.add(f"{v:.1f}".rstrip("0").rstrip("."))
    return out


def _extract_line_by_id(legs: str) -> dict[str, float]:
    """
    Best-effort: extract numeric line printed near each [id:####] token.
    Returns {pid: line_from_text}
    """
    mp: dict[str, float] = {}
    if not isinstance(legs, str) or not legs:
        return mp
    for m in LINE_NEAR_ID_RE.finditer(legs):
        line_s, pid = m.group(1), m.group(2)
        try:
            mp[str(pid)] = float(line_s)
        except Exception:
            continue
    return mp


def check_file(path: Path, today: pd.DataFrame) -> None:
    if not path.exists():
        print(f"[WARN] Missing: {path}")
        return

    rec = pd.read_csv(path)
    if "legs" not in rec.columns:
        print(f"[WARN] No 'legs' column in {path.name}")
        return

    missing = 0
    wrong_dir = 0
    wrong_line = 0

    print(f"\n=== {path.name} ===")

    for i, row in rec.iterrows():
        legs = str(row.get("legs", ""))
        ids = extract_ids(legs)

        if not ids:
            print(f"[ROW {i}] NO IDS FOUND -> cannot validate\n  {legs}\n")
            continue

        line_from_text = _extract_line_by_id(legs)
        problems = []

        for pid in ids:
            m = today[today["projection_id"] == str(pid)]
            if m.empty:
                missing += 1
                problems.append(f"id:{pid} MISSING_FROM_TODAY")
                continue

            rr = m.iloc[0]

            # Validate playability flags against direction
            if rr["direction"] == "UNDER" and rr["less_allowed"] != 1:
                wrong_dir += 1
                problems.append(f"id:{pid} UNDER_NOT_ALLOWED")
            if rr["direction"] == "OVER" and rr["more_allowed"] != 1:
                wrong_dir += 1
                problems.append(f"id:{pid} OVER_NOT_ALLOWED")

            # Validate line numerically, NOT via naive string containment.
            # If we can extract a line from the leg text for this id, compare numerically.
            today_line = rr["line"]
            if pd.notna(today_line):
                if pid in line_from_text:
                    if abs(float(today_line) - float(line_from_text[pid])) > 1e-6:
                        wrong_line += 1
                        problems.append(f"id:{pid} LINE_MISMATCH(today={today_line}, text={line_from_text[pid]})")
                else:
                    # fallback: accept any common textual variant existing somewhere in legs
                    variants = _line_variants(float(today_line))
                    if not any(v in legs for v in variants):
                        wrong_line += 1
                        problems.append(f"id:{pid} LINE_NOT_FOUND(today={today_line})")

        if problems:
            print(f"[ROW {i}] PROBLEMS:")
            for p in problems:
                print(" -", p)
            print("  legs:", legs)
            print()

    print(f"SUMMARY: missing_ids={missing} wrong_dir_flags={wrong_dir} line_mismatches={wrong_line}")


def main():
    print("TODAY:", TODAY)
    today = load_today()

    print("today rows:", len(today))
    print("today tier counts:\n", today["tier"].value_counts().to_string())
    print("today direction counts:\n", today["direction"].value_counts().to_string())

    check_file(REC4, today)
    check_file(REC5, today)


if __name__ == "__main__":
    main()
