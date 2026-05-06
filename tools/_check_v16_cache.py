import pickle
cache = pickle.load(open('data/model/_v16_resim_cache.pkl','rb'))
dates = sorted(cache.get('dates',[]))
cv = cache['cv']
print(f"v16 cache: {len(dates)} dates, {len(cv)} legs")
print(f"Range: {dates[0]} to {dates[-1]}")
print()
print("All dates:")
for d in dates:
    print(f"  {d}")
