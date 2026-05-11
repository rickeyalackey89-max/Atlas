"""Diagnose why build_system_slips exhausts all attempts on corpus data."""
import sys, os, time, copy, yaml
sys.path.insert(0, r'C:\Users\13142\Atlas\Atlas\src')
sys.path.insert(0, r'C:\Users\13142\Atlas\Atlas\tools')
os.environ['ATLAS_DEBUG_BUILDER'] = '1'

from slip_builder_trainer import load_all_dates, _cfg_for_n_legs
from Atlas.core.slip_builders import build_system_slips

data = load_all_dates()
date, scored_df, truth = data[0]
print(f"Date: {date}  Legs: {len(scored_df)}")
if 'tier' in scored_df.columns:
    print(f"Tiers: {scored_df['tier'].value_counts().to_dict()}")
if 'p_cal' in scored_df.columns:
    g = scored_df['tier'] == 'GOBLIN'
    s = scored_df['tier'] == 'STANDARD'
    print(f"GOBLIN p_cal>=0.55: {(scored_df.loc[g, 'p_cal'] >= 0.55).sum()} of {g.sum()}")
    print(f"STANDARD p_cal>=0.55: {(scored_df.loc[s, 'p_cal'] >= 0.55).sum()} of {s.sum()}")

with open(r'C:\Users\13142\Atlas\Atlas\config.yaml') as f:
    base_cfg = yaml.safe_load(f)
base_cfg.get('slip_build', {}).pop('by_legs', None)
base_cfg.get('slip_build', {}).pop('by_sort_mode', None)

overrides = {
    'penalty': {'team_w': 0.15, 'family_w': 0.1, 'frag_w': 0.0},
    'stat_family_mode': 'coarse',
    'beam_window_growth': 2.0,
    'min_leg_prob': 0.55,
}
cfg = copy.deepcopy(base_cfg)
sb2 = cfg.setdefault('slip_build', {})
for k, v in overrides.items():
    if k == 'penalty':
        sb2.setdefault('penalty', {}).update(v)
    else:
        sb2[k] = v

resolved_cfg, _ = _cfg_for_n_legs(cfg, 3, 5, 'ev')
print(f"target_pool_mult={resolved_cfg['slip_build'].get('target_pool_mult')}")
print(f"top_n=5 -> target_pool={5 * resolved_cfg['slip_build'].get('target_pool_mult', 200)}")

t0 = time.time()
result = build_system_slips(scored_df, n_legs=3, top_n=5, seed=42, sort_mode='ev', pricing_engine='atlas', cfg=resolved_cfg)
print(f"Done in {time.time()-t0:.2f}s  rows={len(result)}")
