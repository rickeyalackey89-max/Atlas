#!/usr/bin/env python
"""
Deep calibration audit: where is the model accurate, where is it lying?
Breaks down hit rate by stat, direction, tier, prob bucket, and rank position.
"""
from pathlib import Path
import pandas as pd
import yaml
import sys
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.slip_builders import build_slips_by_tier_buckets

base = Path(__file__).resolve().parents[1] / "data" / "telemetry" / "replay_runs"
_TAG_FILE = base / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"
run_dates = ['20260315', '20260316', '20260317', '20260318',
             '20260319', '20260320', '20260321', '20260322']


def build_with_config(legs_df, cfg, n_legs=3, top_n=10, sort_mode='ev'):
    mixes = {3: {'STANDARD': 2, 'DEMON': 1}, 4: {'STANDARD': 2, 'DEMON': 2}, 5: {'STANDARD': 3, 'DEMON': 2}}
    def mix_ok_fn(n, s): return True
    return build_slips_by_tier_buckets(
        legs_df=legs_df, n_legs=n_legs, top_n=top_n,
        payout_power_mult=1.0, payout_flex={'3': 2.25, '4': 5.0, '5': 10.0},
        pricing_engine='atlas', cfg=cfg, seed=42, per_tier=500,
        max_attempts=100000, sort_mode=sort_mode, mixes=mixes,
        required_tiers=['STANDARD', 'DEMON'], mix_ok_fn=mix_ok_fn)


def parse_legs_str(legs_str):
    legs = []
    parts = str(legs_str).split(' | ')
    for part in parts:
        part = part.strip()
        if not part: continue
        tier = 'UNKNOWN'
        if '(DEMON)' in part: tier = 'DEMON'
        elif '(STANDARD)' in part: tier = 'STANDARD'
        elif '(GOBLIN)' in part: tier = 'GOBLIN'
        if '[id:' in part: part = part[:part.index('[id:')].strip()
        if '(' in part: part = part[:part.rindex('(')].strip()
        tokens = part.split()
        if len(tokens) >= 4:
            direction = tokens[-3].lower()
            stat = tokens[-2].upper()
            try: line = float(tokens[-1])
            except: continue
            player = ' '.join(tokens[:-3]).strip().lower()
            legs.append({'player': player, 'line': line, 'stat': stat, 'direction': direction, 'tier': tier})
    return legs


def main():
    base_cfg = yaml.safe_load(open('config.yaml'))

    # ── SECTION 1: Raw leg-level calibration from scored_legs ──
    print('=' * 70)
    print('  SECTION 1: RAW LEG CALIBRATION (all scored legs vs truth)')
    print('=' * 70)

    all_legs = []  # (prob, hit, stat, direction, tier)

    for date in run_dates:
        run_dir = base / f'{_CORPUS_TAG}_{date}'
        if not run_dir.exists(): continue
        eval_files = list(run_dir.rglob('eval_legs.csv'))
        scored_files = list(run_dir.rglob('scored_legs_deduped.csv'))
        if not eval_files or not scored_files: continue

        eval_df = pd.read_csv(eval_files[0], low_memory=False)
        scored_df = pd.read_csv(scored_files[0], low_memory=False)

        truth = {}
        for _, row in eval_df.iterrows():
            player = str(row.get('player', '')).strip().lower()
            line = float(row.get('line', 0) if pd.notna(row.get('line')) else 0)
            stat = str(row.get('stat', '')).strip().upper()
            direction = str(row.get('direction', '')).strip().lower()
            hit_val = row.get('hit', 0)
            if pd.isna(hit_val): continue
            truth[(player, line, stat, direction)] = int(hit_val)

        for _, row in scored_df.iterrows():
            player = str(row.get('player', '')).strip().lower()
            line = float(row.get('line', 0) if pd.notna(row.get('line')) else 0)
            stat = str(row.get('stat', '')).strip().upper()
            direction = str(row.get('direction', '')).strip().lower()
            # Use p_cal (calibrated), fallback to p_adj, then p
            prob = row.get('p_cal', row.get('p_adj', row.get('p', 0)))
            if pd.isna(prob): continue
            tier = str(row.get('tier', 'UNKNOWN')).strip().upper()
            key = (player, line, stat, direction)
            if key in truth:
                all_legs.append({
                    'prob': float(prob), 'hit': truth[key],
                    'stat': stat, 'direction': direction, 'tier': tier
                })

    legs_df = pd.DataFrame(all_legs)
    print(f"\nTotal legs matched to truth: {len(legs_df)}")
    print(f"Overall hit rate: {legs_df['hit'].mean()*100:.1f}%")
    print(f"Overall avg prob: {legs_df['prob'].mean()*100:.1f}%")

    # By prob bucket
    print("\n--- By probability bucket ---")
    legs_df['prob_bucket'] = pd.cut(legs_df['prob'], bins=[0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 1.0])
    bucket_stats = legs_df.groupby('prob_bucket', observed=True).agg(
        count=('hit', 'count'), hit_rate=('hit', 'mean'), avg_prob=('prob', 'mean')
    )
    for bucket, row in bucket_stats.iterrows():
        cal_error = row['hit_rate'] - row['avg_prob']
        marker = ' ***OVERCONFIDENT***' if cal_error < -0.10 else (' ***UNDERCONFIDENT***' if cal_error > 0.10 else '')
        print(f"  {str(bucket):20s}  n={int(row['count']):5d}  hit={row['hit_rate']*100:5.1f}%  model={row['avg_prob']*100:5.1f}%  error={cal_error*100:+5.1f}%{marker}")

    # By stat
    print("\n--- By stat type ---")
    stat_stats = legs_df.groupby('stat').agg(
        count=('hit', 'count'), hit_rate=('hit', 'mean'), avg_prob=('prob', 'mean')
    ).sort_values('count', ascending=False)
    for stat, row in stat_stats.iterrows():
        cal_error = row['hit_rate'] - row['avg_prob']
        marker = '  ***' if abs(cal_error) > 0.08 else ''
        print(f"  {stat:8s}  n={int(row['count']):5d}  hit={row['hit_rate']*100:5.1f}%  model={row['avg_prob']*100:5.1f}%  error={cal_error*100:+5.1f}%{marker}")

    # By direction
    print("\n--- By direction ---")
    dir_stats = legs_df.groupby('direction').agg(
        count=('hit', 'count'), hit_rate=('hit', 'mean'), avg_prob=('prob', 'mean')
    )
    for d, row in dir_stats.iterrows():
        cal_error = row['hit_rate'] - row['avg_prob']
        print(f"  {d:8s}  n={int(row['count']):5d}  hit={row['hit_rate']*100:5.1f}%  model={row['avg_prob']*100:5.1f}%  error={cal_error*100:+5.1f}%")

    # By stat+direction
    print("\n--- By stat + direction (top combos) ---")
    combo_stats = legs_df.groupby(['stat', 'direction']).agg(
        count=('hit', 'count'), hit_rate=('hit', 'mean'), avg_prob=('prob', 'mean')
    ).sort_values('count', ascending=False)
    for idx, row in combo_stats.head(20).iterrows():
        stat, d = idx  # type: ignore[misc]
        cal_error = row['hit_rate'] - row['avg_prob']
        marker = '  ***GOOD***' if cal_error > 0.05 and row['count'] >= 50 else ('  ***BAD***' if cal_error < -0.05 and row['count'] >= 50 else '')
        print(f"  {stat:6s} {d:6s}  n={int(row['count']):5d}  hit={row['hit_rate']*100:5.1f}%  model={row['avg_prob']*100:5.1f}%  error={cal_error*100:+5.1f}%{marker}")

    # By tier
    print("\n--- By tier ---")
    tier_stats = legs_df.groupby('tier').agg(
        count=('hit', 'count'), hit_rate=('hit', 'mean'), avg_prob=('prob', 'mean')
    )
    for t, row in tier_stats.iterrows():
        cal_error = row['hit_rate'] - row['avg_prob']
        print(f"  {t:12s}  n={int(row['count']):5d}  hit={row['hit_rate']*100:5.1f}%  model={row['avg_prob']*100:5.1f}%  error={cal_error*100:+5.1f}%")

    # ── SECTION 2: Which slip RANK hits most? ──
    print()
    print('=' * 70)
    print('  SECTION 2: WHICH SLIP RANK HITS MOST? (is #1 even the best pick?)')
    print('=' * 70)

    rank_hits = defaultdict(lambda: {'wins': 0, 'total': 0, 'leg_hits': 0, 'leg_total': 0})

    for date in run_dates:
        run_dir = base / f'{_CORPUS_TAG}_{date}'
        if not run_dir.exists(): continue
        eval_files = list(run_dir.rglob('eval_legs.csv'))
        scored_files = list(run_dir.rglob('scored_legs_deduped.csv'))
        if not eval_files or not scored_files: continue

        eval_df = pd.read_csv(eval_files[0], low_memory=False)
        scored_df = pd.read_csv(scored_files[0], low_memory=False)

        truth = {}
        for _, row in eval_df.iterrows():
            player = str(row.get('player', '')).strip().lower()
            line = float(row.get('line', 0) if pd.notna(row.get('line')) else 0)
            stat = str(row.get('stat', '')).strip().upper()
            direction = str(row.get('direction', '')).strip().lower()
            hit_val = row.get('hit', 0)
            if pd.isna(hit_val): continue
            truth[(player, line, stat, direction)] = int(hit_val)

        slips = build_with_config(scored_df, base_cfg, n_legs=3, top_n=10, sort_mode='ev')
        for rank, (_, slip) in enumerate(slips.head(10).iterrows(), 1):
            legs = parse_legs_str(slip.get('legs', ''))
            leg_hits = sum(1 for lg in legs if truth.get((lg['player'], lg['line'], lg['stat'], lg['direction']), -1) == 1)
            leg_total = sum(1 for lg in legs if (lg['player'], lg['line'], lg['stat'], lg['direction']) in truth)
            if leg_total == 0: continue
            rank_hits[rank]['total'] += 1
            rank_hits[rank]['leg_hits'] += leg_hits
            rank_hits[rank]['leg_total'] += leg_total
            if leg_hits == leg_total:
                rank_hits[rank]['wins'] += 1

    print("\n3-leg EV slips: win rate by rank position")
    print(f"{'Rank':>4s} {'Wins':>6s} {'Total':>6s} {'Slip%':>8s} {'LegHit':>8s} {'Leg%':>8s}")
    print('-' * 45)
    for rank in sorted(rank_hits.keys()):
        r = rank_hits[rank]
        slip_pct = r['wins'] / r['total'] * 100 if r['total'] else 0
        leg_pct = r['leg_hits'] / r['leg_total'] * 100 if r['leg_total'] else 0
        marker = '  <-- BEST' if slip_pct == max(rank_hits[k]['wins'] / rank_hits[k]['total'] * 100 for k in rank_hits if rank_hits[k]['total'] > 0) else ''
        print(f"  #{rank:<3d} {r['wins']:>4d}   {r['total']:>4d}   {slip_pct:>6.1f}%  {r['leg_hits']}/{r['leg_total']:>3d}  {leg_pct:>6.1f}%{marker}")

    # ── SECTION 3: High-confidence legs only ──
    print()
    print('=' * 70)
    print('  SECTION 3: HIGH-CONFIDENCE LEG ACCURACY')
    print('=' * 70)

    for threshold in [0.55, 0.58, 0.60, 0.62, 0.65]:
        high_conf = legs_df[legs_df['prob'] >= threshold]
        if len(high_conf) == 0:
            print(f"\n  prob >= {threshold:.2f}: NO LEGS")
            continue
        hit_rate = high_conf['hit'].mean()
        print(f"\n  prob >= {threshold:.2f}: n={len(high_conf)}, hit_rate={hit_rate*100:.1f}%, model_avg={high_conf['prob'].mean()*100:.1f}%")
        # By stat
        for stat in high_conf['stat'].value_counts().head(5).index:
            sub = high_conf[high_conf['stat'] == stat]
            print(f"    {stat:8s} n={len(sub):4d}  hit={sub['hit'].mean()*100:.1f}%")


if __name__ == '__main__':
    main()
