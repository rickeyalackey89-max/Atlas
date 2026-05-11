import pandas as pd
import os

ev = pd.read_csv('data/output/runs/20260505_173532/eval_legs.csv')

def hit(player, stat, line, direction):
    row = ev[(ev['player']==player) & (ev['stat']==stat) & (ev['line']==line) & (ev['direction']==direction)]
    if row.empty: return None
    return bool(row.iloc[0]['hit'] == 1.0)

run_dir = 'data/output/runs/20260505_173532'

for slip_size in ['3leg', '4leg', '5leg']:
    fpath = os.path.join(run_dir, 'Windfall', f'recommended_{slip_size}.csv')
    if not os.path.exists(fpath):
        print(f"Missing: {fpath}")
        continue
    df = pd.read_csv(fpath)
    # Check top slip (rank 1)
    row1 = df.iloc[0]
    legs_str = str(row1['legs'])
    # Parse legs from the leg_1, leg_2, leg_3... columns
    leg_cols = [c for c in df.columns if c.startswith('leg_') and c[4:].isdigit()]
    legs = [str(row1[c]) for c in leg_cols if str(row1[c]) not in ('nan','')]
    # Check hits
    hits = []
    leg_details = []
    for leg in legs:
        # Format: "Player Name DIR STAT LINE (TIER) [id:xxx]"
        parts = leg.split()
        # find OVER or UNDER
        try:
            dir_idx = next(i for i, p in enumerate(parts) if p in ('OVER','UNDER'))
        except StopIteration:
            continue
        player = ' '.join(parts[:dir_idx])
        direction = parts[dir_idx]
        stat = parts[dir_idx+1]
        line = float(parts[dir_idx+2])
        leg_details.append(f"{player} {direction} {stat} {line}")
        hits.append(hit(player, stat, line, direction))

    all_win = all(h is True for h in hits)
    hit_str = '/'.join(['H' if h else ('M' if h is False else '?') for h in hits])
    status = 'WIN' if all_win else f'MISS [{hit_str}]'
    print(f"Windfall {slip_size}: {status}")
    for l in leg_details:
        print(f"  {l}")