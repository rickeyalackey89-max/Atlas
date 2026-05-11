import sys
import time
sys.path.insert(0, 'tools')
import kernel_trainer_v1 as kt1
import kernel_trainer_v2_loso as kt2

cv = kt2.load_cache(kt2.DEFAULT_CACHE)
cv = cv[cv["hit"].notna()].reset_index(drop=True)
print(f"cv: {len(cv)} legs, {cv['game_date'].nunique()} dates")

base = kt1._read_current_defaults()
print("base subset:", {k: base[k] for k in ["rate_min_correlation","spread_sd","threshold_margin","star_minute_drop","post_sim_exponent","rate_std_PTS","rate_std_PRA"]})

t0 = time.time()
res = kt1.run_simulation(cv, base, sims=1000, return_per_date=True)
print(f"baseline brier_p={res['brier_p']*1000:.3f} brier_adj={res['brier_adj']*1000:.3f} N={res['n_legs']} ({time.time()-t0:.1f}s)")
for d in sorted(res["per_date"]):
    v = res["per_date"][d]
    print(f"  {d}  N={v['n']:>5}  p={v['brier_p']*1000:.2f}  adj={v['brier_adj']*1000:.2f}")
