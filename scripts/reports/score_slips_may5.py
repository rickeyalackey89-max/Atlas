import pandas as pd, os, re

run = r'data/output/runs/20260505_173532'
eval_df = pd.read_csv(run + '/eval_legs.csv')

def parse_leg_str(leg_str):
    # Format: "Isaiah Joe OVER PTS 5.5 (GOBLIN) [id:11870805]"
    m = re.match(r'^(.+?)\s+(OVER|UNDER)\s+(\w+)\s+([\d.]+)\s+\((\w+)\)', str(leg_str))
    if m:
        return m.group(1).strip(), m.group(2), m.group(3), float(m.group(4))
    return None, None, None, None

def get_result(player, direction, stat, line, eval_df):
    match = eval_df[
        (eval_df['player'].str.lower() == player.lower()) &
        (eval_df['stat'] == stat) &
        (eval_df['line'] == line) &
        (eval_df['direction'] == direction)
    ]
    if len(match) > 0:
        return float(match['hit'].values[0]), match['actual'].values[0]
    return None, None

total_slips = 0
hit_slips = 0

def score_all_slips(df, label, eval_df):
    leg_cols = [c for c in df.columns if re.match(r'^leg_\d+$', c)]
    slips_hit = []
    slips_miss = []
    for i, row in df.iterrows():
        results = []
        for lc in leg_cols:
            leg_str = row[lc]
            if pd.isna(leg_str):
                continue
            player, direction, stat, line = parse_leg_str(leg_str)
            if player is None:
                continue
            h, actual = get_result(player, direction, stat, line, eval_df)
            results.append((player, stat, direction, line, h, actual))
        if not results:
            continue
        n_hit = sum(1 for r in results if r[4] == 1.0)
        n_total = len(results)
        if n_hit == n_total:
            slips_hit.append((i+1, results))
        else:
            slips_miss.append((i+1, n_hit, n_total, results))
    return slips_hit, slips_miss

for family in ['System', 'Windfall']:
    for n_legs in [3, 4, 5]:
        path = f'{run}/{family}/recommended_{n_legs}leg.csv'
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        hits, misses = score_all_slips(df, f'{family} {n_legs}leg', eval_df)
        total_slips += len(hits) + len(misses)
        hit_slips += len(hits)
        print(f'{family} {n_legs}leg: {len(hits)} HIT / {len(hits)+len(misses)} total')
        for rank, results in hits:
            print(f'  [HIT rank #{rank}]', ' | '.join(f"{r[0]} {r[1]} {r[2]} {r[3]}" for r in results))
        if not hits:
            # Show nearest misses (4/5 or 3/4 or 2/3)
            near = [(r, h, t, res) for r, h, t, res in misses if h >= t-1]
            for rank, n_hit, n_total, results in near[:3]:
                miss_legs = [r for r in results if r[4] != 1.0]
                print(f'  [near miss rank #{rank} {n_hit}/{n_total}] missed: ' +
                      ', '.join(f"{r[0]} {r[1]} {r[2]} {r[3]} actual={r[5]}" for r in miss_legs))
        print()

# DemonHunter
dh_path = f'{run}/demonhunter.csv'
if os.path.exists(dh_path):
    dh = pd.read_csv(dh_path)
    if len(dh) > 0:
        hits, misses = score_all_slips(dh, 'DemonHunter', eval_df)
        total_slips += len(hits) + len(misses)
        hit_slips += len(hits)
        print(f'DemonHunter: {len(hits)} HIT / {len(hits)+len(misses)} total')
        for rank, results in hits:
            print(f'  [HIT rank #{rank}]', ' | '.join(f"{r[0]} {r[1]} {r[2]} {r[3]}" for r in results))
        if not hits:
            near = [(r, h, t, res) for r, h, t, res in misses if h >= t-1]
            for rank, n_hit, n_total, results in near[:3]:
                miss_legs = [r for r in results if r[4] != 1.0]
                print(f'  [near miss rank #{rank} {n_hit}/{n_total}] missed: ' +
                      ', '.join(f"{r[0]} {r[1]} {r[2]} {r[3]} actual={r[5]}" for r in miss_legs))
        print()

print(f'=== SUMMARY: {hit_slips}/{total_slips} all slips hit ===')
