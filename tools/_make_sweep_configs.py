#!/usr/bin/env python3
from pathlib import Path
import yaml
import copy

orig = Path('config.yaml')
if not orig.exists():
    raise SystemExit('config.yaml not found')
base = yaml.safe_load(orig.read_text())
variants = [
    (100, 50),
    (100, 100),
    (200, 50),
    (200, 200),
    (400, 100),
    (400, 200),
]
out_files = []
for tau, mn in variants:
    cfg = copy.deepcopy(base)
    if cfg.get('telemetry') is None:
        cfg['telemetry'] = {}
    cfg['telemetry']['pooling_tau'] = float(tau)
    cfg['telemetry']['min_count'] = int(mn)
    fname = f'config.telemetry_tau{tau}_min{mn}.yaml'
    Path(fname).write_text(yaml.safe_dump(cfg, sort_keys=False), encoding='utf-8')
    out_files.append(fname)
print('WROTE:' + ','.join(out_files))
