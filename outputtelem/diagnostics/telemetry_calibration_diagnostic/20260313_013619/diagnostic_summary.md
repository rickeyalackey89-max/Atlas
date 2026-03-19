# Telemetry Calibration Diagnostic

- Runs read: 13
- Settled rows: 40922
- Mean hit: 0.422682
- Mean p_adj: 0.392213
- Mean p_cal: 0.400608
- Brier p_adj: 0.210116
- Brier p_cal: 0.209833
- Logloss p_adj: 0.607310
- Logloss p_cal: 0.606537
- Telemetry applied share: 0.000000

## Most overconfident p_cal buckets

- (0.9,1.0]: rows=63, pred=0.9247, hit=1.0000, gap=-0.0753
- (0.0,0.5]: rows=27502, pred=0.2890, hit=0.3207, gap=-0.0317
- (0.5,0.6]: rows=5922, pred=0.5481, hit=0.5664, gap=-0.0183
- (0.8,0.9]: rows=574, pred=0.8365, hit=0.8223, gap=0.0142
- (0.6,0.7]: rows=4513, pred=0.6469, hit=0.6348, gap=0.0120
- (0.7,0.8]: rows=2348, pred=0.7419, hit=0.7338, gap=0.0081

## Most overconfident stat-direction slices

- FG3M OVER: rows=2730, pred=0.3474, hit=0.3465, gap=0.0009
- AST OVER: rows=3903, pred=0.3676, hit=0.3674, gap=0.0001

## Most underconfident stat-direction slices

- FG3M UNDER: rows=134, pred=0.4749, hit=0.6194, gap=-0.1445
- RA UNDER: rows=567, pred=0.4688, hit=0.5291, gap=-0.0603
- PRA UNDER: rows=938, pred=0.4722, hit=0.5256, gap=-0.0534
- REB UNDER: rows=546, pred=0.4938, hit=0.5458, gap=-0.0519
- PA UNDER: rows=848, pred=0.4777, hit=0.5200, gap=-0.0423
- PR UNDER: rows=934, pred=0.4797, hit=0.5193, gap=-0.0396
- AST UNDER: rows=343, pred=0.4754, hit=0.5131, gap=-0.0377
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