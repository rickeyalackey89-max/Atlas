"""Quick diagnostic — build one windfall slip and verify projection_id fix."""
import sys, yaml, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path("C:/Users/13142/Atlas/NBA/src")))

from Atlas.core.slip_builders import build_windfall_slips

cfg = yaml.safe_load(open("C:/Users/13142/Atlas/NBA/config.yaml", encoding="utf-8"))

scored = pd.read_csv(
    "C:/Users/13142/Atlas/NBA/data/telemetry/v18_corpus/20260322/scored_legs_deduped.csv",
    low_memory=False
)
eval_df = pd.read_csv(
    "C:/Users/13142/Atlas/NBA/data/telemetry/v18_corpus/20260322/eval_legs.csv",
    low_memory=False
)

print(f"scored_df rows: {len(scored)}  columns (first 10): {list(scored.columns[:10])}")
print(f"eval_df rows: {len(eval_df)}  columns: {list(eval_df.columns)}")
print(f"eval hit col exists: {'hit' in eval_df.columns}  sample hits: {eval_df['hit'].value_counts().to_dict() if 'hit' in eval_df.columns else 'N/A'}")
print()

# Build truth dict like the trainer does
truth = {}
for _, row in eval_df.iterrows():
    player = str(row.get("player", "")).strip().lower()
    line = float(row.get("line", 0))
    stat = str(row.get("stat", "")).strip().upper()
    direction = str(row.get("direction", "")).strip().lower()
    hit_val = row.get("hit")
    if pd.isna(hit_val):
        continue
    truth[(player, line, stat, direction)] = int(hit_val)
print(f"Truth dict: {len(truth)} entries")
print(f"Sample truth keys: {list(truth.keys())[:3]}")
print()

# Build slips
slips = build_windfall_slips(scored, n_legs=3, top_n=5, seed=42, sort_mode="hit",
                              pricing_engine="atlas", cfg=cfg)

if slips is None or slips.empty:
    print("ERROR: build_windfall_slips returned empty/None!")
else:
    print(f"Slips built: {len(slips)}")
    print(f"Slip columns: {list(slips.columns)}")
    print()
    row = slips.iloc[0]
    print(f"--- Slip 0 legs column ---")
    print(repr(row.get("legs", "<no legs col>")))
    print()
    # Try parsing
    legs_str = str(row.get("legs", ""))
    parts = legs_str.split(" | ")
    print(f"Split into {len(parts)} parts:")
    for i, part in enumerate(parts):
        print(f"  part[{i}]: {repr(part)}")
        part2 = part.strip()
        if "[id:" in part2:
            part2 = part2[:part2.index("[id:")].strip()
        if "(" in part2:
            part2 = part2[:part2.rindex("(")].strip()
        tokens = part2.split()
        print(f"    tokens: {tokens}")
        if len(tokens) >= 4:
            direction = tokens[-3].lower()
            stat = tokens[-2].upper()
            try:
                line = float(tokens[-1])
            except ValueError:
                line = None
            player = " ".join(tokens[:-3]).strip().lower()
            key = (player, line, stat, direction)
            print(f"    parsed key: {key}")
            print(f"    in truth: {key in truth}")
        else:
            print(f"    SKIP: <4 tokens")

