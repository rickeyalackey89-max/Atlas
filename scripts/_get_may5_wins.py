import pandas as pd, glob, os, sys
sys.path.insert(0, 'src')

ev = pd.read_csv('data/output/runs/20260505_173532/eval_legs.csv')

def hit(player, stat, line, direction):
    row = ev[(ev['player']==player) & (ev['stat']==stat) & (ev['line']==line) & (ev['direction']==direction)]
    if row.empty: return None
    return bool(row.iloc[0]['hit'] == 1.0)

# Scan all May 5 runs for winning slips
runs = sorted(glob.glob('data/output/runs/20260505_*/'))
winners = []
for r in runs:
    ts = r.rstrip('/\\').split('\\')[-1]
    hour = ts[9:11]
    minute = ts[11:13]
    label = f"{int(hour)%12 or 12}:{minute}{'am' if int(hour)<12 else 'pm'}"
    mp = os.path.join(r, 'marketed_slips.csv')
    if not os.path.exists(mp):
        continue
    m = pd.read_csv(mp)
    for slip_type in m['slip'].unique():
        legs = m[m['slip']==slip_type]
        hits = [hit(row['player'], row['stat'], row['line'], row['direction']) for _, row in legs.iterrows()]
        if all(h is True for h in hits):
            leg_details = []
            for _, row in legs.iterrows():
                leg_details.append(f"{row['player']} {row['direction']} {row['stat']} {row['line']}")
            winners.append({'label': label, 'slip': slip_type, 'legs': leg_details, 'ts': ts})
            print(f"WIN: {label} {slip_type}")
            for l in leg_details:
                print(f"  {l}")
        else:
            miss_str = '/'.join(['H' if h else ('M' if h is False else '?') for h in hits])
            print(f"    {label} {slip_type}: [{miss_str}]")

print()
print(f"Total wins: {len(winners)}")
