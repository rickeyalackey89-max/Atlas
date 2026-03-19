# Telemetry Calibration Diagnostic

- Runs read: 13
- Settled rows: 40922
- Mean hit: 0.422682
- Mean p_adj: 0.392213
- Mean p_cal: 0.401010
- Brier p_adj: 0.210116
- Brier p_cal: 0.209804
- Logloss p_adj: 0.607310
- Logloss p_cal: 0.606487
- Telemetry applied share: 0.096941

## Most overconfident p_cal buckets

- (0.9,1.0]: rows=63, pred=0.9249, hit=1.0000, gap=-0.0751
- (0.0,0.5]: rows=27450, pred=0.2889, hit=0.3199, gap=-0.0310
- (0.5,0.6]: rows=5950, pred=0.5481, hit=0.5677, gap=-0.0196
- (0.8,0.9]: rows=582, pred=0.8365, hit=0.8196, gap=0.0169
- (0.6,0.7]: rows=4510, pred=0.6468, hit=0.6355, gap=0.0114
- (0.7,0.8]: rows=2367, pred=0.7418, hit=0.7313, gap=0.0105

## Most overconfident stat-direction slices

- FG3M OVER: rows=2730, pred=0.3474, hit=0.3465, gap=0.0009
- AST OVER: rows=3903, pred=0.3676, hit=0.3674, gap=0.0001

## Most underconfident stat-direction slices

- FG3M UNDER: rows=134, pred=0.4863, hit=0.6194, gap=-0.1331
- RA UNDER: rows=567, pred=0.4735, hit=0.5291, gap=-0.0556
- PRA UNDER: rows=938, pred=0.4769, hit=0.5256, gap=-0.0486
- REB UNDER: rows=546, pred=0.4988, hit=0.5458, gap=-0.0470
- PA UNDER: rows=848, pred=0.4806, hit=0.5200, gap=-0.0395
- AST UNDER: rows=343, pred=0.4754, hit=0.5131, gap=-0.0377
- PR UNDER: rows=934, pred=0.4826, hit=0.5193, gap=-0.0367
- PR OVER: rows=4449, pred=0.3889, hit=0.4212, gap=-0.0323
- PRA OVER: rows=5239, pred=0.4083, hit=0.4390, gap=-0.0308
- PTS OVER: rows=6027, pred=0.4142, hit=0.4427, gap=-0.0285
- PA OVER: rows=3754, pred=0.3884, hit=0.4129, gap=-0.0245
- PTS UNDER: rows=921, pred=0.5001, hit=0.5179, gap=-0.0178
- RA OVER: rows=4745, pred=0.3873, hit=0.4027, gap=-0.0154
- REB OVER: rows=4844, pred=0.3779, hit=0.3842, gap=-0.0063

## Interpretation

- This diagnostic pass isolates where calibration error is concentrated.
- It does not recommend or promote a challenger by itself.
- Use the bucket and slice files to design the next targeted experiment.