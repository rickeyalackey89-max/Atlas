import pandas as pd
import os, glob

ev = pd.read_csv('data/output/runs/20260505_173532/eval_legs.csv')

def hit(player, stat, line, direction):
    row = ev[(ev['player']==player) & (ev['stat']==stat) & (ev['line']==line) & (ev['direction']==direction)]
    if row.empty: return None
    return bool(row.iloc[0]['hit'] == 1.0)

def check_slip_csv(fpath, label):
    if not os.path.exists(fpath):
        return
    df = pd.read_csv(fpath)
    if df.empty:
        return
    row1 = df.iloc[0]
    leg_cols = sorted([c for c in df.columns if c.startswith('leg_') and c[4:].isdigit()])
    legs = [str(row1[c]) for c in leg_cols if str(row1[c]) not in ('nan','')]
    hits = []
    leg_details = []
    for leg in legs:
        parts = leg.split()
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
    print(f"{label}: {status}")
    if all_win:
        for l in leg_details:
            print(f"  {l}")

# Check DemonHunter from all May 5 runs
print("=== DemonHunter ===")
for run in sorted(glob.glob('data/output/runs/20260505_*/')):
    ts = run.rstrip('/\\').split('\\')[-1]
    hour = int(ts[9:11]); minute = ts[11:13]
    lbl = f"{hour%12 or 12}:{minute}{'am' if hour<12 else 'pm'}"
    fpath = os.path.join(run, 'demonhunter.csv')
    if os.path.exists(fpath):
        check_slip_csv(fpath, f"DH {lbl}")

# Check Windfall top slips from ALL May 5 runs (not just 5:35pm)
print()
print("=== Windfall (all runs) ===")
for run in sorted(glob.glob('data/output/runs/20260505_*/')):
    ts = run.rstrip('/\\').split('\\')[-1]
    hour = int(ts[9:11]); minute = ts[11:13]
    lbl = f"{hour%12 or 12}:{minute}{'am' if hour<12 else 'pm'}"
    for sz in ['3leg','4leg','5leg']:
        fpath = os.path.join(run, 'Windfall', f'recommended_{sz}.csv')
        check_slip_csv(fpath, f"WF {lbl} {sz}")
