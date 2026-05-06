import pickle, pandas as pd, numpy as np

cache = pickle.load(open('data/model/_v17_resim_cache.pkl','rb'))
cv = cache['cv'].dropna(subset=['p_cal','hit']).copy()
cv['hit'] = cv['hit'].astype(float)

bins = [0, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 1.0]
labels = ['<45','45-50','50-55','55-60','60-65','65-70','70-75','75-80','80-85','>85']
cv['bucket'] = pd.cut(cv['p_cal'], bins=bins, labels=labels)
g = cv.groupby('bucket', observed=False).agg(
    n=('hit','count'),
    actual_hit=('hit','mean'),
    model_p=('p_cal','mean')
).reset_index()
g['gap'] = g['actual_hit'] - g['model_p']
g['gap_pct'] = (g['gap'] * 100).round(1)

print("Calibration: model p_cal (displayed as % confidence) vs what actually hit")
print("=" * 65)
print(f"{'Bucket':<10} {'N':>6} {'Model%':>8} {'Actual%':>8} {'Gap pp':>8}")
print("-" * 65)
for _, row in g.iterrows():
    if row['n'] > 0:
        print(f"{str(row['bucket']):<10} {int(row['n']):>6} {row['model_p']*100:>7.1f}% {row['actual_hit']*100:>7.1f}% {row['gap_pct']:>+7.1f}pp")
print("=" * 65)

overall_brier = float(np.mean((cv['p_cal']-cv['hit'])**2))
print(f"\nOverall Brier:   {overall_brier:.6f}")
print(f"Overall hit rate: {cv['hit'].mean():.4f}  | Mean p_cal: {cv['p_cal'].mean():.4f}")

# Direction split
print()
for d in ['OVER','UNDER']:
    sub = cv[cv['direction'].str.upper() == d]
    if len(sub) > 100:
        b = float(np.mean((sub['p_cal']-sub['hit'])**2))
        print(f"{d}: N={len(sub)}  Brier={b:.6f}  hit={sub['hit'].mean():.4f}  p_cal={sub['p_cal'].mean():.4f}")

# p_cal_marketed vs p_cal if it exists
if 'p_cal_marketed' in cv.columns:
    print()
    print("p_cal_marketed (what graphics show) vs actual:")
    cv2 = cv.dropna(subset=['p_cal_marketed'])
    cv2['bucket2'] = pd.cut(cv2['p_cal_marketed'], bins=bins, labels=labels)
    g2 = cv2.groupby('bucket2', observed=False).agg(
        n=('hit','count'),
        actual_hit=('hit','mean'),
        model_p=('p_cal_marketed','mean')
    ).reset_index()
    g2['gap'] = (g2['actual_hit'] - g2['model_p']) * 100
    for _, row in g2.iterrows():
        if row['n'] > 0:
            print(f"  {str(row['bucket2']):<10} N={int(row['n']):>6}  model={row['model_p']*100:.1f}%  actual={row['actual_hit']*100:.1f}%  gap={row['gap']:+.1f}pp")
