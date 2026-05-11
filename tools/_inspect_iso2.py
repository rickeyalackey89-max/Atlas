import json, pathlib

d = json.loads(pathlib.Path('data/model/telemetry_calibration.playoff_isotonic.json').read_text())
meta = d['meta']
print("meta.source_col:", meta.get('source_col'))
print("meta.x_thresholds:", meta['x_thresholds'][:5], "...", meta['x_thresholds'][-5:])
print("meta.y_thresholds:", meta['y_thresholds'][:5], "...", meta['y_thresholds'][-5:])
print()
pc = meta.get('protected_calibration', {})
print("protected_calibration.mode:", pc.get('mode'))
pc_meta = pc.get('meta', {})
print("protected_calibration.meta keys:", list(pc_meta.keys())[:10])
print("protected_calibration.meta.source_col:", pc_meta.get('source_col'))
xlen = len(pc_meta.get('x_thresholds', []))
print("protected_calibration.meta.x_thresholds len:", xlen)

print()
print("protected_stat_directions (first 3):")
for item in meta.get('protected_stat_directions', [])[:3]:
    print(" ", item)
