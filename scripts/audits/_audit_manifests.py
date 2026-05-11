import json, sys
from pathlib import Path

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

o = load(sys.argv[1])  # cat_corpus
c = load(sys.argv[2])  # catboost_v2

print("=== cat_corpus_20260506 ===")
print(f"  config_fingerprint : {o.get('config_fingerprint')}")
print(f"  lookback_games     : {o.get('full_config',{}).get('lookback_games')}")
print(f"  posthoc_enabled    : {o.get('calibration',{}).get('posthoc_enabled')}")
print(f"  active_calibration : {o.get('calibration',{}).get('active_calibration')}")
print(f"  apply_active_cal   : {o.get('calibration',{}).get('apply_active_calibration')}")
print(f"  catboost section   : {o.get('full_config',{}).get('catboost_playoff_calibrator')}")

print()
print("=== catboost_v2_20260506 ===")
print(f"  config_fingerprint : {c.get('config_fingerprint')}")
print(f"  lookback_games     : {c.get('full_config',{}).get('lookback_games')}")
print(f"  posthoc_enabled    : {c.get('calibration',{}).get('posthoc_enabled')}")
print(f"  active_calibration : {c.get('calibration',{}).get('active_calibration')}")
print(f"  apply_active_cal   : {c.get('calibration',{}).get('apply_active_calibration')}")
cc = c.get('full_config',{}).get('catboost_playoff_calibrator', {})
print(f"  catboost.enabled   : {cc.get('enabled') if isinstance(cc, dict) else cc}")

print()
fp_match = o.get('config_fingerprint') == c.get('config_fingerprint')
print(f"Config fingerprints match: {fp_match}")
