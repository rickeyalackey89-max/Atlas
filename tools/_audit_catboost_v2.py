import json, pickle
from pathlib import Path
import pandas as pd

meta = json.loads(Path('data/model/catboost_playoff_ensemble_meta.json').read_text())
print('=== v2 deployed model meta ===')
print(f"  trained_at: {meta.get('trained_at')}")
print(f"  cache_path: {meta.get('cache_path')}")
print(f"  source_col: {meta.get('source_col')}")
print(f"  n_legs:     {meta.get('n_legs_total')}")
brb = meta.get('oof_brier_before')
bra = meta.get('oof_brier_after')
bd = meta.get('oof_brier_delta_mB')
print(f"  OOF Brier:  {brb:.6f} -> {bra:.6f}  ({bd:+.3f} mB)")
print(f"  hyperparams: {meta.get('hyperparams')}")
print()

with open('data/model/_v1_playoff_resim_cache.pkl', 'rb') as f:
    cache = pickle.load(f)
cv = cache['cv']
print('=== resim cache TE check ===')
for c in ('player_te','player_stat_te','player_dir_te'):
    if c in cv.columns:
        s = pd.to_numeric(cv[c], errors='coerce')
        print(f'  {c:18s}: n={int(s.notna().sum()):>6} mean={s.mean():+.4f} std={s.std():.4f} zeros={int((s==0).sum())}/{len(s)}')
    else:
        print(f'  {c}: MISSING')

print()
fi = meta.get('feature_importance', {})
if isinstance(fi, dict) and fi:
    items = sorted(fi.items(), key=lambda kv: -kv[1])[:10]
    print('=== v2 top-10 feature importance ===')
    for f, v in items:
        print(f'  {f:20s} {v:7.3f}')
