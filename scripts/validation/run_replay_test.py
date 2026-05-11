#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

# Ensure local src is importable
sys.path.insert(0, os.path.abspath("src"))

import pandas as pd

from Atlas.stages.rebuild.rebuild_today import run_rebuild
from Atlas.model.backtest_v2 import _drop_started_games_for_replay, _parse_replay_cutoff_utc, BacktestMeta

raw_path = Path("data/raw/prizepicks_20260317_152119.json")
print("raw_path:", raw_path.resolve())
payload = json.loads(raw_path.read_text(encoding="utf-8"))

# Rebuild the today board (replay mode)
today_df = run_rebuild(payload=payload, is_replay=True)
print("today rows before gating:", len(today_df))

# Resolved cutoff
cutoff = _parse_replay_cutoff_utc(raw_path, payload)
print("resolved cutoff:", cutoff)

# Inspect payload game starts
start_map = {}
for inc in payload.get("included", []) or []:
    if inc.get("type") == "game":
        gid = str(inc.get("id", "")).strip()
        st = ((inc.get("attributes") or {}).get("start_time"))
        start_map[gid] = st
print("found games in payload:", len(start_map))

if cutoff:
    started_ids = [k for k, v in start_map.items() if v and pd.to_datetime(v, utc=True).to_pydatetime() <= cutoff]
    print("started_ids count by cutoff:", len(started_ids))
    print("started_ids sample:", started_ids[:20])
else:
    print("no cutoff resolved; started_ids unknown")

# Apply the gate
meta = BacktestMeta(
    raw_path=str(raw_path.resolve()),
    raw_stem=raw_path.stem,
    logs_path="",
    config_path="",
    gamelogs_path="",
    injury_dir="",
    run_dir=".",
    created_at_utc="",
    notes=""
)
filtered = _drop_started_games_for_replay(today_df.copy(), payload, raw_path, meta)
print("today rows after gating:", len(filtered))
print("meta.notes:", meta.notes)

print("sample today game_ids (unique, first 20):", today_df["game_id"].drop_duplicates().head(20).tolist())
print("--- done ---")
