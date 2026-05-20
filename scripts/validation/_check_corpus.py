import pandas as pd, json, pickle
from pathlib import Path

corpus = Path("C:/Users/13142/Atlas/NBA/data/telemetry/v18_corpus")
manifest = json.loads((corpus / "corpus_manifest.json").read_text())
dates = manifest["dates"]
print(f"Manifest dates: {len(dates)}  ({dates[0]} - {dates[-1]})")

for d in [dates[0], dates[len(dates)//2], dates[-1]]:
    f = corpus / d / "scored_legs_deduped.csv"
    df = pd.read_csv(f)
    cal = str(df["telemetry_cal_applied"].all()) if "telemetry_cal_applied" in df.columns else "N/A"
    print(f"  {d}: rows={len(df)}  p_cal={df['p_cal'].mean():.4f}  tel_cal={cal}")

with open("C:/Users/13142/Atlas/NBA/data/model/_v18_resim_cache.pkl", "rb") as f:
    cache = pickle.load(f)
ver = cache.get("version", "unknown")
ndates = len(cache["dates"])
snap_keys = list(cache.get("config_snapshot", {}).keys())[:6]
print(f"Cache version: {ver}  dates: {ndates}")
print(f"Config snapshot keys: {snap_keys}")

