# DEMON Calibration Protection Guide

## 🎯 Problem
During LODO runs and model training, various trainer scripts can overwrite `config.yaml` and lose the custom **DEMON tier calibration fix** that reduces DEMON tier overconfidence by ~10%.

## 🛡️ Solution
Two protection scripts have been created to automatically backup, restore, and protect the DEMON calibration settings:

### 1. Manual Protection Tool
**File:** `tools/protect_demon_calibration.py`

```bash
# Check current calibration status
python tools/protect_demon_calibration.py --status

# Backup current calibration settings
python tools/protect_demon_calibration.py --backup

# Apply DEMON calibration fix
python tools/protect_demon_calibration.py --apply

# Restore from backup
python tools/protect_demon_calibration.py --restore
```

### 2. Automatic Protection Wrapper
**File:** `tools/safe_lodo_run.py`

Automatically protects calibration settings around any command:

```bash
# Protected GBM training
python tools/safe_lodo_run.py "python tools/gbm_v12_train.py --cache v13 --promote"

# Protected leg trainer
python tools/safe_lodo_run.py "python tools/leg_trainer_v5_ev.py"

# Protected role context trainer
python tools/safe_lodo_run.py "python tools/role_ctx_trainer_v1.py"

# Any other command that might affect config
python tools/safe_lodo_run.py "git checkout main -- config.yaml"
```

## 📋 Recommended Workflow

### Before Any Training Session:
```bash
# 1. Check current status
python tools/protect_demon_calibration.py --status

# 2. Backup current settings
python tools/protect_demon_calibration.py --backup

# 3. Run training with protection
python tools/safe_lodo_run.py "python tools/gbm_v12_train.py --cache v13"
```

### After Git Operations:
If you've done any git operations that might have reset config.yaml:
```bash
# Reapply DEMON calibration fix
python tools/protect_demon_calibration.py --apply

# Verify it's active
python tools/protect_demon_calibration.py --status
```

### Emergency Recovery:
If DEMON calibration gets lost and you don't have a backup:
```bash
# Apply fresh DEMON calibration fix
python tools/protect_demon_calibration.py --apply
```

## 🔍 What Gets Protected
- `active_calibration: demon_fix`
- `apply_active_calibration: true`  
- `active_calibration_path: data/model/telemetry_calibration.demon_fix.json`

## 🎯 Key Benefits
- **Automatic detection** when calibration settings change
- **Smart restoration** only applies DEMON fix if it was active before
- **Safe wrapper** for any potentially dangerous commands
- **Backup system** preserves your calibration state
- **Status monitoring** shows current and backed-up states

## ⚠️ Important Notes
1. The protection scripts preserve the **telemetry section** of config.yaml specifically
2. Other trainer changes (role_ctx, external_priors, etc.) are left untouched
3. Always run `--status` first to understand current state
4. The DEMON calibration file must exist: `data/model/telemetry_calibration.demon_fix.json`

## 🔧 Technical Details
The DEMON calibration fix applies a **pre-calibration penalty** of 0.90 (10% reduction) specifically to DEMON tier legs before the isotonic mapping, addressing the systematic 6-14pp overconfidence that was causing DemonHunter slips to dramatically underperform.