"""Minimal worker test: 1 worker, 1 task, 1 date — does it complete?"""
import sys, os, time, multiprocessing as mp
sys.path.insert(0, r'C:\Users\13142\Atlas\Atlas\src')
sys.path.insert(0, r'C:\Users\13142\Atlas\Atlas\tools')

import pickle, tempfile

def worker_init(path):
    global _DATA
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    with open(path, "rb") as f:
        _DATA = pickle.load(f)
    print(f"[W] init done, {len(_DATA)} dates", flush=True)

def worker_task(args):
    n_dates, = args
    from slip_builder_trainer import score_config, SEEDS
    import yaml, copy
    data = _DATA[:n_dates]
    with open(r'C:\Users\13142\Atlas\Atlas\config.yaml') as f:
        base_cfg = yaml.safe_load(f)
    base_cfg.get('slip_build', {}).pop('by_legs', None)
    base_cfg.get('slip_build', {}).pop('by_sort_mode', None)
    overrides = {'penalty': {'team_w': 0.15, 'family_w': 0.1}, 'min_leg_prob': 0.55}
    t0 = time.time()
    print(f"[W] calling score_config for {n_dates} dates...", flush=True)
    r = score_config(overrides, base_cfg, data, 3, 'ev', 'system', seeds=SEEDS[:1], top_k=3)
    print(f"[W] score_config done in {time.time()-t0:.2f}s: {r}", flush=True)
    return r

if __name__ == "__main__":
    mp.freeze_support()
    mp.set_start_method("spawn", force=True)

    from slip_builder_trainer import load_all_dates
    data = load_all_dates()
    print(f"Loaded {len(data)} dates")

    # Write slim pickle
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
    pickle.dump(data, tmp); tmp.close()
    print(f"Pickle: {os.path.getsize(tmp.name)/1e6:.1f} MB")

    for n in [1, 5, 25]:
        print(f"\n--- Testing {n} dates in 1-worker pool ---")
        pool = mp.Pool(1, initializer=worker_init, initargs=(tmp.name,))
        t0 = time.time()
        results = pool.map(worker_task, [(n,)])
        pool.close(); pool.join()
        print(f"Pool done in {time.time()-t0:.2f}s: {results}")

    os.unlink(tmp.name)
    print("DONE")
