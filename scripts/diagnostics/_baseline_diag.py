"""Diagnostic: reproduce the exact baseline loop from main() with full config."""
import sys, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
import yaml
from tools.leg_trainer_v5_windfall import load_all_dates, score_config, SEEDS, TOP_K

with open('config.yaml') as f:
    base_cfg = yaml.safe_load(f)

cats = [
    ('3-leg WINDFALL', 3, 'hit'),
    ('4-leg WINDFALL', 4, 'hit'),
    ('5-leg WINDFALL', 5, 'hit'),
]

data = load_all_dates()
print(f'Loaded {len(data)} dates')
print('--- Baseline ---')
for cat_name, n_legs, sort_mode in cats:
    print(f'  Running {cat_name}...')
    try:
        result = score_config({}, base_cfg, data, n_legs, sort_mode, sweep_seeds=SEEDS, sweep_top_k=TOP_K)
        if result:
            w = result['weighted']
            sw = result['slip_wins']
            lh = result['legs_hit']
            lm = result['legs_matched']
            lr = result['leg_rate']
            print(f'  {cat_name}: weighted={w} slips={sw} legs={lh}/{lm} ({lr:.0%})')
    except Exception as e:
        traceback.print_exc()
print('Baseline done.')
