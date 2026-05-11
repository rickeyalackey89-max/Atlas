import pickle, pandas as pd, numpy as np

cache = pickle.load(open('data/model/_v17_resim_cache.pkl','rb'))
cv = cache['cv'].dropna(subset=['p_cal','hit','l20_edge']).copy()
cv['hit'] = cv['hit'].astype(float)

# l20_edge as naive probability
base_hr = cv['hit'].mean()
cv['l20_as_prob'] = (base_hr + cv['l20_edge']).clip(0.05, 0.95)
b_l20 = float(np.mean((cv['l20_as_prob'] - cv['hit'])**2))
b_cal = float(np.mean((cv['p_cal'] - cv['hit'])**2))
print(f"l20_as_prob Brier: {b_l20:.6f}   p_cal Brier: {b_cal:.6f}")
print()

# High confidence tier
hi = cv[cv['p_cal'] >= 0.65].copy()
print(f"High confidence (p_cal>=65%) legs: {len(hi)}")
b_hi = float(np.mean((hi['p_cal'] - hi['hit'])**2))
print(f"  p_cal Brier:      {b_hi:.6f}")
print(f"  p_cal mean:       {hi['p_cal'].mean():.4f}")
print(f"  actual hit rate:  {hi['hit'].mean():.4f}")
gap = (hi['p_cal'].mean() - hi['hit'].mean()) * 100
print(f"  gap (overconf):   {gap:+.1f}pp")
print()

# What is the slip builder actually selecting?
if 'p_cal_marketed' in cv.columns:
    mkt = cv.dropna(subset=['p_cal_marketed']).copy()
    mkt['hit'] = mkt['hit'].astype(float)
    print(f"p_cal_marketed (slip builder picks): N={len(mkt)}")
    print(f"  mean p_cal_marketed: {mkt['p_cal_marketed'].mean():.4f}")
    print(f"  mean actual hit:     {mkt['hit'].mean():.4f}")
    gap2 = (mkt['p_cal_marketed'].mean() - mkt['hit'].mean()) * 100
    print(f"  gap: {gap2:+.1f}pp")
else:
    print("p_cal_marketed not in cache")

# Full probability chain comparison on high-conf tier
print()
print("Probability chain on legs where p_cal >= 0.65:")
for col in ['p','p_role','p_adj','p_for_cal','p_cal']:
    if col in hi.columns:
        b = float(np.mean((hi[col] - hi['hit'])**2))
        m = hi[col].mean()
        print(f"  {col:<15} mean={m:.4f}  Brier={b:.6f}")
