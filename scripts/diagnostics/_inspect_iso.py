import json, pathlib
d = json.loads(pathlib.Path('data/model/telemetry_calibration.playoff_isotonic.json').read_text())
for k, v in d.items():
    if isinstance(v, dict):
        print(k, "=>", list(v.keys())[:15])
        for kk, vv in v.items():
            if isinstance(vv, list):
                print("  ", kk, "len=", len(vv))
            elif isinstance(vv, dict):
                print("  ", kk, "=>", list(vv.keys())[:8])
            else:
                print("  ", kk, "=", repr(vv)[:60])
    else:
        print(k, "=", repr(v)[:60])
