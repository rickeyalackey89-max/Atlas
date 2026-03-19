# tools/finalize_now.py
from __future__ import annotations

import json
import os
import subprocess
import sys
import glob
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FETCH = os.path.join(ROOT, "tools", "fetch_apis.py")
REBUILD = os.path.join(ROOT, "tools", "rebuild_today_from_any_raw.py")
FILTER_LIVE = os.path.join(ROOT, "tools", "filter_recommendations_live.py")
POST = os.path.join(ROOT, "tools", "postprocess_outputs.py")

BOARD = os.path.join(ROOT, "data", "board", "today.csv")
RAW_DIR = os.path.join(ROOT, "data", "raw")
LATEST_DIR = os.path.join(ROOT, "data", "output", "latest")

LOCAL_TZ = ZoneInfo("America/Chicago")


def _latest_file(path_glob: str) -> str | None:
    files = glob.glob(path_glob)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


def step(label: str, cmd: list[str], allow_fail: bool = False) -> int:
    print("\n" + "=" * 72)
    print(f"[{label}] {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("CMD:", " ".join(cmd))
    print("=" * 72)

    p = subprocess.run(cmd, cwd=ROOT, check=False)
    if p.returncode != 0 and not allow_fail:
        print(f"[{label}] FAILED (exit code {p.returncode})")
        return p.returncode
    if p.returncode != 0 and allow_fail:
        print(f"[{label}] FAILED (exit code {p.returncode}) — continuing anyway.")
        return p.returncode

    print(f"[{label}] OK")
    return 0


def write_meta(tag: str) -> None:
    tag_dir = os.path.join(LATEST_DIR, tag)
    os.makedirs(tag_dir, exist_ok=True)

    finalize_ts = datetime.now(LOCAL_TZ).isoformat()
    raw_latest = _latest_file(os.path.join(RAW_DIR, "prizepicks_*.json"))
    board_mtime = None
    try:
        board_mtime = datetime.fromtimestamp(os.path.getmtime(BOARD), tz=LOCAL_TZ).isoformat()
    except Exception:
        board_mtime = None

    meta = {
        "tag": tag,
        "finalize_ts_local": finalize_ts,
        "board_csv": BOARD,
        "board_mtime_local": board_mtime,
        "raw_latest_json": raw_latest,
    }
    with open(os.path.join(tag_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def main() -> int:
    tag = "all"
    if len(sys.argv) >= 2:
        tag = str(sys.argv[1]).strip() or "all"

    # This does NOT rerun the model. It only refreshes live feasibility and latest outputs.
    step(f"FETCH (live board before finalize/{tag})", [sys.executable, FETCH], allow_fail=True)
    rc_rebuild = step(f"REBUILD (live board snapshot/{tag})", [sys.executable, REBUILD], allow_fail=False)
    if rc_rebuild != 0:
        return rc_rebuild

    rc_filter = step(f"FILTER (live placeable/{tag})", [sys.executable, FILTER_LIVE, "--tag", tag], allow_fail=False)
    if rc_filter != 0:
        return rc_filter

    rc_post = step(f"POSTPROCESS (latest/{tag})", [sys.executable, POST, tag], allow_fail=False)
    if rc_post != 0:
        return rc_post

    write_meta(tag)
    print("\n✅ FINALIZE DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
