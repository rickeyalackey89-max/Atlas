"""Smoke test: playoff rate penalty and minutes boost in MC kernel."""
import sys; sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from Atlas.engine.new_probability import simulate_leg_probability_new

np.random.seed(42)
n = 20
gl = pd.DataFrame({
    'player': ['Test Star'] * n,
    'team': ['DEN'] * n,
    'opp': ['OKC'] * n,
    'game_date': pd.date_range('2026-01-01', periods=n, freq='2D').astype(str),
    'minutes': np.random.normal(34, 2, n).clip(25, 44),
    'pts': np.random.normal(34, 4, n).clip(15, 50),
    'reb': [7.0] * n,
    'ast': [6.0] * n,
    'fg3m': [2.5] * n,
    'fta': [8.0] * n,
    'fga': [15.0] * n,
    'tov': [2.5] * n,
})

row_rs = pd.Series({'player': 'Test Star', 'stat': 'PTS', 'line': 25.5, 'direction': 'OVER',
                    'team': 'DEN', 'opp': 'OKC', 'tier': 'STANDARD', 'spread': -4.0,
                    'game_date': '2026-03-15'})
row_po = row_rs.copy()
row_po['game_date'] = '2026-05-05'

blowout_cfg = {
    'spread_sd': 12.0, 'threshold_margin': 15.5,
    'rate_std_multiplier': 1.0, 'rate_std_under_mult': 1.0,
    'rate_std_multiplier_by_stat': {'PTS': 1.3},
    'thin_window_games': 15, 'thin_window_max_mult': 1.6,
    'recent_form_blend': 0.0, 'opp_defense_strength': 0.0,
    'recency_halflife': 4, 'rate_min_correlation': 0.0,
    'blowout_curve': {'slope': -0.28, 'intercept': 4.0, 'max_gain': 5.0, 'max_drop': 12.0},
    'combo_component_sim': False,
    'playoff_regime': {
        'enabled': True,
        'start_date': '2026-04-30',
        'rate_penalties': {'PTS': 0.89},
        'default_rate_penalty': 0.93,
        'starter_minutes_boost': {
            'elite_floor': 33.0, 'core_floor': 30.0,
            'elite_boost': 6.0, 'core_boost': 3.5, 'boost_cap': 47.0,
        },
    },
}

kwargs = dict(gamelogs=gl, lookback=20, sims=10000, spread_sd=12.0,
              blowout_threshold=15.5, star_minute_drop=8.0, role_minute_drop=0.5,
              blowout_cfg=blowout_cfg, rng=np.random.default_rng(42))

rs = simulate_leg_probability_new(row=row_rs, **kwargs)
po = simulate_leg_probability_new(row=row_po, **kwargs)

print("=== Regular Season (2026-03-15) ===")
p_rs = rs['p']
rate_rs = rs['rate_mean']
min_rs = rs['min_mean']
print(f"  p={p_rs:.4f}  rate_mean={rate_rs:.4f}  min_mean={min_rs:.1f}")
print(f"  is_playoff={rs['is_playoff']}  rate_applied={rs['playoff_rate_applied']}  min_applied={rs['playoff_min_applied']}")
print()
print("=== Playoffs (2026-05-05) ===")
p_po = po['p']
rate_po = po['rate_mean']
min_po = po['min_mean']
print(f"  p={p_po:.4f}  rate_mean={rate_po:.4f}  min_mean={min_po:.1f}")
print(f"  is_playoff={po['is_playoff']}  rate_applied={po['playoff_rate_applied']}  min_applied={po['playoff_min_applied']}")
print()
print(f"Delta p:         {p_po - p_rs:+.4f}  (rate penalty pushes OVER down; minutes boost partially offsets)")
print(f"Delta rate_mean: {rate_po - rate_rs:+.4f}  (x0.89 applied)")
print(f"Delta min_mean:  {min_po - min_rs:+.2f}   (elite +6.0 boost)")
