import pandas as pd, re, os

def parse_leg_str(leg_str):
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

def score_top_slip(path, eval_df, label):
    if not os.path.exists(path):
        return
    df = pd.read_csv(path)
    top = df.iloc[0]
    leg_cols = [c for c in df.columns if re.match(r'^leg_\d+$', c)]
    results = []
    for lc in leg_cols:
        ls = top[lc]
        if pd.isna(ls):
            continue
        p, d, s, l = parse_leg_str(ls)
        if p is None:
            continue
        h, actual = get_result(p, d, s, l, eval_df)
        results.append((p, s, d, l, h, actual))
    n_hit = sum(1 for r in results if r[4] == 1.0)
    status = 'HIT' if n_hit == len(results) else 'MISS %d/%d' % (n_hit, len(results))
    print('  %s: %s' % (label, status))
    for r in results:
        mark = 'v' if r[4] == 1.0 else 'x'
        print('    [%s] %s %s %s %s -> actual=%s' % (mark, r[0], r[1], r[2], r[3], r[5]))

runs = [
    ('data/output/runs/20260505_080510', '8:05 AM'),
    ('data/output/runs/20260505_091019', '9:10 AM'),
    ('data/output/runs/20260505_110554', '11:05 AM'),
    ('data/output/runs/20260505_124901', '12:49 PM'),
    ('data/output/runs/20260505_130359', '1:03 PM'),
    ('data/output/runs/20260505_140937', '2:09 PM'),
    ('data/output/runs/20260505_143511', '2:35 PM'),
    ('data/output/runs/20260505_151943', '3:19 PM'),
    ('data/output/runs/20260505_171724', '5:17 PM'),
    ('data/output/runs/20260505_173532', '5:35 PM'),
]

for run_path, label in runs:
    if not os.path.exists(run_path):
        continue
    eval_df = pd.read_csv(run_path + '/eval_legs.csv')
    print('=== RUN %s (%s) ===' % (label, run_path.split('/')[-1]))

    # Root-level recommended (these may be the "market slips")
    for n in [3, 4, 5]:
        score_top_slip('%s/recommended_%dleg.csv' % (run_path, n), eval_df, 'root-%dleg' % n)

    # marketed_slips.csv
    mkt_path = run_path + '/marketed_slips.csv'
    if os.path.exists(mkt_path):
        mkt = pd.read_csv(mkt_path)
        for slip_type in mkt['slip'].unique():
            sub = mkt[mkt['slip'] == slip_type]
            results = []
            for _, row in sub.iterrows():
                match = eval_df[
                    (eval_df['player'] == row['player']) &
                    (eval_df['stat'] == row['stat']) &
                    (eval_df['line'] == row['line']) &
                    (eval_df['direction'] == row['direction'])
                ]
                h = float(match['hit'].values[0]) if len(match) > 0 else None
                actual = match['actual'].values[0] if len(match) > 0 else None
                results.append((row['player'], row['stat'], row['direction'], row['line'], h, actual))
            n_hit = sum(1 for r in results if r[4] == 1.0)
            status = 'HIT' if n_hit == len(results) else 'MISS %d/%d' % (n_hit, len(results))
            print('  marketed-%s: %s' % (slip_type, status))
            for r in results:
                mark = 'v' if r[4] == 1.0 else 'x'
                print('    [%s] %s %s %s %s -> actual=%s' % (mark, r[0], r[1], r[2], r[3], r[5]))
    print()