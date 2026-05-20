import pickle, numpy as np
cv = pickle.load(open(r'C:\Users\13142\Atlas\NBA\data\model\_v1_playoff_resim_cache.pkl','rb'))['cv']
y = cv['hit'].astype(float).to_numpy()

def br(p):
    return float(np.mean((p.astype(float) - y) ** 2))

def br_arr(arr, ys):
    return float(np.mean((arr.astype(float) - ys) ** 2))

print('=== Stratify p_adj->p_for_cal by role_ctx_outs_used ===')
print()
hdr = ['group', 'n', 'p_role', 'p_adj', 'p_for_cal', 'hit', 'd_adj_to_cal_mB']
print('  ' + '  '.join(f'{h:<14}' for h in hdr))
for label, mask in [
    ('use_role(outs>0)', cv['role_ctx_outs_used'] > 0),
    ('no_role(outs=0)',  cv['role_ctx_outs_used'] == 0),
]:
    sub = cv[mask]
    if len(sub) == 0:
        continue
    yd = sub['hit'].astype(float).to_numpy()
    n = len(sub)
    pr = float(sub['p_role'].mean())
    pa = float(sub['p_adj'].mean())
    pf = float(sub['p_for_cal'].mean())
    hr = float(sub['hit'].mean())
    delta = (br_arr(sub['p_for_cal'].values, yd) - br_arr(sub['p_adj'].values, yd)) * 1000.0
    cells = [label, str(n), f'{pr:.4f}', f'{pa:.4f}', f'{pf:.4f}', f'{hr:.4f}', f'{delta:+.2f}']
    print('  ' + '  '.join(f'{c:<14}' for c in cells))

print()
print('=== Per-stage Brier within use_role legs only ===')
sub = cv[cv['role_ctx_outs_used'] > 0]
yd = sub['hit'].astype(float).to_numpy()
print(f'  N={len(sub)}')
for col in ['p', 'p_role', 'p_adj', 'p_for_cal', 'p_cal']:
    print(f'  Brier({col:<10}) = {br_arr(sub[col].values, yd):.6f}')
print(f'  -> Replacing p_role with p_adj for use_role legs: Delta = {(br_arr(sub["p_adj"].values, yd) - br_arr(sub["p_role"].values, yd))*1000:+.2f} mB')

# Aggregate counterfactual
print()
print('=== Aggregate counterfactual (p_for_cal := p_adj for ALL legs) ===')
print(f'  Current Brier(p_for_cal) = {br(cv["p_for_cal"].values):.6f}')
print(f'  Fixed   Brier(p_adj)     = {br(cv["p_adj"].values):.6f}')
print(f'  Aggregate Delta = {(br(cv["p_adj"].values) - br(cv["p_for_cal"].values))*1000:+.2f} mB')

# Per-slate counterfactual
print()
print('=== Per-slate counterfactual (Brier with p_adj vs p_for_cal) ===')
for d, sd in cv.groupby('game_date'):
    yd = sd['hit'].astype(float).to_numpy()
    bcur = br_arr(sd['p_for_cal'].values, yd)
    bfix = br_arr(sd['p_adj'].values, yd)
    use_role_count = int((sd['role_ctx_outs_used'] > 0).sum())
    delta_mB = (bfix - bcur) * 1000
    print(f'  {d}  n={len(sd):>5}  use_role={use_role_count:>4}  cur={bcur:.4f}  fix={bfix:.4f}  Delta={delta_mB:+6.2f}mB')

# Per-tier counterfactual
print()
print('=== Per-tier counterfactual ===')
for t, sd in cv.groupby('tier'):
    yd = sd['hit'].astype(float).to_numpy()
    bcur = br_arr(sd['p_for_cal'].values, yd)
    bfix = br_arr(sd['p_adj'].values, yd)
    print(f'  {t:<10} n={len(sd):>5}  cur={bcur:.4f}  fix={bfix:.4f}  Delta={(bfix-bcur)*1000:+6.2f}mB')

# Per-direction counterfactual
print()
print('=== Per-direction counterfactual ===')
for dr, sd in cv.groupby('direction'):
    yd = sd['hit'].astype(float).to_numpy()
    bcur = br_arr(sd['p_for_cal'].values, yd)
    bfix = br_arr(sd['p_adj'].values, yd)
    print(f'  {dr:<10} n={len(sd):>5}  cur={bcur:.4f}  fix={bfix:.4f}  Delta={(bfix-bcur)*1000:+6.2f}mB')

