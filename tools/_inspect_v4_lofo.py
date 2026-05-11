import json
v4 = json.load(open('data/model/catboost_playoff_v4_lofo.json'))
v5b = json.load(open('data/model/catboost_playoff_v5b_lodo.json'))
print(f"v5b features ({len(v5b['v5b_features'])}):")
for f in v5b['v5b_features']:
    print(f'  {f}')
print()

# v4 LOFO results
key = 'lofo_results'
print(f'v4 keys: {list(v4.keys())}')
print()
if key:
    rows = v4[key]
    print(f'v4 {key} count: {len(rows)}')
    if rows and isinstance(rows, list):
        sample = rows[0]
        print('sample keys:', list(sample.keys()) if isinstance(sample, dict) else 'not dict')
        for row in rows:
            if isinstance(row, dict):
                f = row.get('feature', '?')
                da = row.get('d_agg_mB', row.get('d_agg', 0))
                dw = row.get('d_worst_mB', row.get('d_worst', 0))
                cl = row.get('class', '?')
                print(f'  {f:<22} d_agg={da:+6.2f}  d_worst={dw:+6.2f}  class={cl}')
