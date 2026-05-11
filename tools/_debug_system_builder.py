"""Patch slip_builders._run_phase to count rejections, then run system builder."""
import pandas as pd, yaml, sys, os, random, warnings
from collections import Counter
warnings.filterwarnings('ignore')
os.environ['ATLAS_DEBUG_BUILDER'] = '0'
sys.path.insert(0, 'C:/Users/13142/Atlas/Atlas/src')

import Atlas.core.slip_builders as sb_mod
import Atlas.core.slip_scoring as ss_mod

# --- Patch _score_slip to trap exceptions ---
_orig_score_slip = ss_mod._score_slip
_score_exceptions = []
def _patched_score_slip(chosen, n_legs, payout_mult, pricing_engine="atlas", cfg=None):
    try:
        return _orig_score_slip(chosen, n_legs, payout_mult, pricing_engine=pricing_engine, cfg=cfg)
    except Exception as e:
        _score_exceptions.append(str(e))
        raise
ss_mod._score_slip = _patched_score_slip
# Also patch the reference in slip_builders
import importlib
importlib.reload(sb_mod)  # reload to pick up patched _score_slip... actually this might not work

# Better: patch in place after reload
import Atlas.core.slip_builders as sb_mod2

# Save original build function
_orig_build = sb_mod2.build_slips_by_tier_buckets

call_counter = Counter()

def _instrumented_build(**kwargs):
    # We'll replace the _run_phase logic with our own counter
    # Actually just call original and count via the outer slips list
    result = _orig_build(**kwargs)
    return result

cfg = yaml.safe_load(open('C:/Users/13142/Atlas/Atlas/config.yaml', encoding='utf-8'))
cfg['slip_build']['min_leg_prob'] = 0.0
cfg['slip_build'].pop('leg_quality_filters', None)

df = pd.read_csv(
    'C:/Users/13142/Atlas/Atlas/data/telemetry/v18_corpus/20260225/scored_legs_deduped.csv',
    low_memory=False
)

# Now manually simulate the ACTUAL mixes used by system:
# mixes = {3: {"GOBLIN": 1, "STANDARD": 2}, ...}
# Let's replicate the exact _run_phase logic with counting

from Atlas.core.slip_scoring import _score_slip, _format_leg
from Atlas.core.slip_builders import _tier_counts_from_legs, _system_mix_ok
from Atlas.core.payout_tables import POWER_MULT, FLEX_3

# First simulate build_slips_by_tier_buckets prep steps
df_c = df.copy().reset_index(drop=True)

# projection_id
pid_series = df_c['projection_id']
df_c['projection_id'] = pid_series.map(lambda x: str(x).strip())

# tier normalization
df_c['tier'] = df_c['tier'].map(lambda x: str(x).upper().strip() if x else 'STANDARD')

# filter to GOBLIN+STANDARD only (system builder)
df_c = df_c[df_c['tier'].isin(['GOBLIN', 'STANDARD'])].reset_index(drop=True)

# p_eff from p_cal
df_c['p_eff'] = df_c['p_cal']

# edge_score
df_c['edge_score'] = df_c['p_eff'] - 0.5

# allocator_score
df_c['allocator_score'] = df_c['edge_score']

# Build buckets: top 650 per tier sorted by allocator_score
n_legs = 3
mix = {'GOBLIN': 1, 'STANDARD': 2}
per_tier = 650
phase1_frac = 0.1

buckets = {}
for t in ['GOBLIN', 'STANDARD']:
    sub = df_c[df_c['tier'] == t].sort_values('allocator_score', ascending=False).head(per_tier).reset_index(drop=True)
    buckets[t] = [sub.iloc[i] for i in range(len(sub))]
    print(f'{t} bucket: {len(buckets[t])} rows, {sub["player"].nunique()} unique players')

# Phase1 buckets (top 10%)
n_p1 = max(int(per_tier * phase1_frac), int(mix.get("GOBLIN", 0) + mix.get("STANDARD", 0)))
phase1_buckets = {t: buckets[t][:n_p1] for t in mix}
print(f'Phase1 bucket size per tier: {n_p1}')

sb = cfg.get('slip_build', {})
max_players_per_team = int(sb.get('max_players_per_team', 2))
max_same_stat = int(sb.get('max_same_stat', 0) or 0)
max_dir = sb.get('max_direction_per_slip')
no_same_game = bool(sb.get('no_same_game_within_slip', False))

rng = random.Random(42)
rejects = Counter()
N_ATTEMPTS = 10000

for attempt in range(N_ATTEMPTS):
    chosen = []
    for t, need in mix.items():
        chosen.extend(rng.sample(phase1_buckets[t], int(need)))

    pids, players, ok = [], [], True
    for r in chosen:
        if 'projection_id' not in r.index:
            ok = False; break
        pid = str(r['projection_id']).strip()
        if not pid or pid.lower() == 'nan':
            ok = False; break
        pids.append(pid)
        player_name = str(r.get('player', '')).strip().lower()
        players.append(player_name)

    if not ok:
        rejects['missing_pid'] += 1; continue
    if len(set(pids)) != len(pids):
        rejects['dup_pid'] += 1; continue
    if len(set(players)) != len(players):
        rejects['dup_player'] += 1; continue

    if max_players_per_team > 0:
        teams = []
        for r in chosen:
            for k in ('team','team_abbrev','player_team'):
                if k in r.index:
                    v = str(r[k]).strip()
                    if v and v.lower() != 'nan':
                        teams.append(v); break
        if teams:
            tc = Counter(teams)
            if max(tc.values()) > max_players_per_team:
                rejects['same_team'] += 1; continue

    if no_same_game:
        games = []
        for r in chosen:
            for k in ('game_id','gameId'):
                if k in r.index:
                    v = str(r[k]).strip()
                    if v and v.lower() != 'nan':
                        games.append(v); break
        if len(set(games)) != len(games):
            rejects['same_game'] += 1; continue

    if max_same_stat > 0:
        stats = [str(r.get('stat','')).strip().upper() for r in chosen]
        sc = Counter(stats)
        if sc and max(sc.values()) > max_same_stat:
            rejects['same_stat'] += 1; continue

    # _score_slip
    try:
        scored = _score_slip(chosen, n_legs, POWER_MULT[n_legs], pricing_engine='atlas', cfg=cfg)
    except Exception as e:
        rejects[f'score_slip_exc:{e}'] += 1; continue

    legs_str = scored.get('legs', '')

    # system mix_ok: n_legs=3 -> GOBLIN=1, STANDARD=2, DEMON=0
    if not _system_mix_ok(n_legs, legs_str):
        tcs = _tier_counts_from_legs(legs_str)
        rejects[f'mix_ok_FAIL tcs={tcs}'] += 1; continue

    rejects['OK'] += 1

total = sum(rejects.values())
print(f'\nAttempts={N_ATTEMPTS}, total={total}')
for k, v in rejects.most_common():
    pct = 100.0 * v / total if total else 0
    print(f'  {k}: {v} ({pct:.1f}%)')

# Print first 3 legs_str to see what they look like
print('\n--- Sample legs_str from 3 attempts ---')
rng2 = random.Random(42)
for _ in range(3):
    chosen = []
    for t, need in mix.items():
        chosen.extend(rng2.sample(phase1_buckets[t], int(need)))
    scored = _score_slip(chosen, n_legs, POWER_MULT[n_legs], pricing_engine='atlas', cfg=cfg)
    legs_str = scored.get('legs','')
    print(f'  legs_str: {legs_str}')
    print(f'  tier_counts: {_tier_counts_from_legs(legs_str)}')
    print(f'  mix_ok: {_system_mix_ok(n_legs, legs_str)}')
    print()
