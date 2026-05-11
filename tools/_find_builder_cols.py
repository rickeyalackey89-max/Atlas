"""Find all DataFrame column names accessed in slip_builders.py and slip_scoring.py."""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = [
    root / "src/Atlas/core/slip_builders.py",
    root / "src/Atlas/core/slip_scoring.py",
]

cols = set()
for fpath in files:
    src = fpath.read_text(encoding="utf-8")
    # df["col"] and df['col']
    cols |= set(re.findall(r'df\["([a-zA-Z_][a-zA-Z0-9_]*)"\]', src))
    cols |= set(re.findall(r"df\['([a-zA-Z_][a-zA-Z0-9_]*)'\]", src))
    # _to_float_series(df, "col") and similar helper calls
    cols |= set(re.findall(r'_to_float_series\(df,\s*"([a-zA-Z_][a-zA-Z0-9_]*)"', src))
    cols |= set(re.findall(r"_to_float_series\(df,\s*'([a-zA-Z_][a-zA-Z0-9_]*)'", src))
    # pd.to_numeric(df["col"]) etc
    cols |= set(re.findall(r'pd\.to_numeric\(df\["([a-zA-Z_][a-zA-Z0-9_]*)"\]', src))
    # df.get("col") style — not a real pandas op but check anyway
    cols |= set(re.findall(r'df\.get\("([a-zA-Z_][a-zA-Z0-9_]*)"\)', src))

print(f"Found {len(cols)} columns:")
for c in sorted(cols):
    print(f"  {c}")
