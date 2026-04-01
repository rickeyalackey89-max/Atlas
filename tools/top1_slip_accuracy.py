#!/usr/bin/env python
"""Analyze accuracy of the #1 ranked slip per category across dates."""
from pathlib import Path
import pandas as pd
import yaml
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.slip_builders import build_slips_by_tier_buckets
from Atlas.stages.optimize.build_slips_today import _cfg_for_n_legs

base = Path(r'D:\AtlasTestMarch26\telemetry_replay_runs')
run_dates = ['20260315', '20260316', '20260317', '20260318',
             '20260319', '20260320', '20260321', '20260322']


def build_with_config(legs_df, cfg, n_legs=3, top_n=10, sort_mode='ev'):
    resolved_cfg, _ = _cfg_for_n_legs(cfg, n_legs, top_n, sort_mode)
    mixes = {
        3: {'STANDARD': 2, 'DEMON': 1},
        4: {'STANDARD': 2, 'DEMON': 2},
        5: {'STANDARD': 3, 'DEMON': 2},
    }
    def mix_ok_fn(n, s): return True
    return build_slips_by_tier_buckets(
        legs_df=legs_df, n_legs=n_legs, top_n=top_n,
        payout_power_mult=1.0,
        payout_flex={'3': 2.25, '4': 5.0, '5': 10.0},
        pricing_engine='atlas', cfg=resolved_cfg, seed=42, per_tier=500,
        max_attempts=100000, sort_mode=sort_mode, mixes=mixes,
        required_tiers=['STANDARD', 'DEMON'], mix_ok_fn=mix_ok_fn)


def parse_legs_str(legs_str):
    legs = []
    parts = str(legs_str).split(' | ')
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '[id:' in part:
            part = part[:part.index('[id:')].strip()
        if '(' in part:
            part = part[:part.rindex('(')].strip()
        tokens = part.split()
        if len(tokens) >= 4:
            direction = tokens[-3].lower()
            stat = tokens[-2].upper()
            try:
                line = float(tokens[-1])
            except ValueError:
                continue
            player = ' '.join(tokens[:-3]).strip().lower()
            legs.append((player, line, stat, direction))
    return legs


def evaluate_slip(slip_row, truth):
    """Return (legs_matched, legs_hit, all_hit, leg_details)."""
    legs = parse_legs_str(slip_row.get('legs', ''))
    details = []
    matched = 0
    hit = 0
    for player, line, stat, direction in legs:
        key = (player, line, stat, direction)
        if key in truth:
            matched += 1
            h = truth[key]
            hit += h
            details.append({
                'player': player, 'line': line, 'stat': stat,
                'direction': direction, 'hit': h
            })
        else:
            details.append({
                'player': player, 'line': line, 'stat': stat,
                'direction': direction, 'hit': None
            })
    all_hit = (hit == matched and matched > 0)
    return matched, hit, all_hit, details


def main():
    base_cfg = yaml.safe_load(open('config.yaml'))

    categories = [
        ('3-leg EV',  3, 'ev'),
        ('3-leg HIT', 3, 'hit'),
        ('4-leg EV',  4, 'ev'),
        ('5-leg EV',  5, 'ev'),
    ]

    # collect per-category results
    cat_results = {name: [] for name, _, _ in categories}

    for date in run_dates:
        run_dir = base / f'kernel_v2_perstat_corr015_{date}'
        if not run_dir.exists():
            continue

        eval_files = list(run_dir.rglob('eval_legs.csv'))
        scored_files = list(run_dir.rglob('scored_legs_deduped.csv'))
        if not eval_files or not scored_files:
            continue

        eval_df = pd.read_csv(eval_files[0], low_memory=False)
        scored_df = pd.read_csv(scored_files[0], low_memory=False)

        truth = {}
        for _, row in eval_df.iterrows():
            player = str(row.get('player', '')).strip().lower()
            line_val = row.get('line', 0)
            line = float(line_val if pd.notna(line_val) else 0)
            stat = str(row.get('stat', '')).strip().upper()
            direction = str(row.get('direction', '')).strip().lower()
            hit_val = row.get('hit', 0)
            if pd.isna(hit_val):
                continue
            truth[(player, line, stat, direction)] = int(hit_val)

        for cat_name, n_legs, sort_mode in categories:
            try:
                slips = build_with_config(scored_df, base_cfg, n_legs=n_legs,
                                          top_n=10, sort_mode=sort_mode)
            except Exception:
                continue

            if slips.empty:
                continue

            top_slip = slips.iloc[0]
            matched, hit, all_hit, details = evaluate_slip(top_slip, truth)

            cat_results[cat_name].append({
                'date': date,
                'hit_prob': top_slip.get('hit_prob', 0),
                'n_legs': n_legs,
                'legs_matched': matched,
                'legs_hit': hit,
                'slip_hit': all_hit,
                'details': details,
            })

    # ── Print results ──
    for cat_name, n_legs, sort_mode in categories:
        rows = cat_results[cat_name]
        if not rows:
            continue

        print('=' * 70)
        print(f'  TOP-1 SLIP: {cat_name}  (sort={sort_mode})')
        print('=' * 70)

        wins = sum(1 for r in rows if r['slip_hit'])
        total = len(rows)
        leg_hits = sum(r['legs_hit'] for r in rows)
        leg_total = sum(r['legs_matched'] for r in rows)
        avg_prob = sum(r['hit_prob'] for r in rows) / total

        print(f"Dates tested: {total}")
        print(f"Slip wins (all legs hit): {wins}/{total} = {wins/total*100:.1f}%")
        print(f"Leg hit rate: {leg_hits}/{leg_total} = {leg_hits/leg_total*100:.1f}%")
        print(f"Avg model hit_prob: {avg_prob:.3f}")
        print()

        # Per-date detail
        for r in rows:
            status = 'WIN' if r['slip_hit'] else 'MISS'
            legs_str = f"{r['legs_hit']}/{r['legs_matched']} legs"
            print(f"  {r['date']}  [{status}]  hit_prob={r['hit_prob']:.3f}  {legs_str}")
            for d in r['details']:
                hit_label = {1: 'HIT', 0: 'MISS', None: '???'}[d['hit']]
                print(f"    {d['player']:25s} {d['direction']:5s} {d['stat']:5s} {d['line']:6.1f}  {hit_label}")
            print()

    # ── Summary table ──
    print()
    print('=' * 70)
    print('  SUMMARY: TOP-1 SLIP ACCURACY BY CATEGORY')
    print('=' * 70)
    print(f"{'Category':<15s} {'Dates':>5s} {'Slip Wins':>10s} {'Rate':>8s} {'Leg Rate':>10s} {'Avg Prob':>10s}")
    print('-' * 65)
    for cat_name, _, _ in categories:
        rows = cat_results[cat_name]
        if not rows:
            print(f"{cat_name:<15s}   (no data)")
            continue
        wins = sum(1 for r in rows if r['slip_hit'])
        total = len(rows)
        leg_hits = sum(r['legs_hit'] for r in rows)
        leg_total = sum(r['legs_matched'] for r in rows)
        avg_prob = sum(r['hit_prob'] for r in rows) / total
        print(f"{cat_name:<15s} {total:>5d} {wins:>5d}/{total:<4d} {wins/total*100:>7.1f}% "
              f"{leg_hits}/{leg_total} = {leg_hits/leg_total*100:.1f}% {avg_prob:>9.3f}")


if __name__ == '__main__':
    main()
