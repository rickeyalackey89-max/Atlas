**ATLAS v17 GOLDEN BASELINE**
============================

This directory contains the **IMMUTABLE** v17 model that serves as the canonical baseline for all future development.

**⚠️ DO NOT MODIFY FILES IN THIS DIRECTORY ⚠️**

## Performance Metrics

- **LODO Brier**: 0.200748 (44/44 folds improved over previous baseline)
- **Slip-eligible hit rate**: 62.3% (p_cal ≥ 0.52)
- **GOBLIN tier hit rate**: 64.6% 
- **Training corpus**: 165,792 legs across 44 dates (Feb 9 - Apr 12, 2026)
- **Architecture**: 33 features, 7 seeds, temperature 1.04

## Contents

- `ensemble_meta.json` - v17 GBM ensemble metadata
- `lightgbm_*.txt` - 14 trained LightGBM models (7 OVER × 7 UNDER seeds)
- `_v17_resim_cache.pkl` - Training corpus with features and truth labels
- `model_contract_v17.py` - Contract validation rules
- `config_v17.yaml` - Production configuration

## Restore Commands

If you need to restore v17 from this golden baseline:

```powershell
# Restore ensemble
Copy-Item -Path "data\model\GOLDEN_V17_BASELINE\ensemble_meta.json" -Destination "data\model\ensemble\" -Force
Copy-Item -Path "data\model\GOLDEN_V17_BASELINE\lightgbm_*.txt" -Destination "data\model\ensemble\" -Force

# Restore cache
Copy-Item -Path "data\model\GOLDEN_V17_BASELINE\_v17_resim_cache.pkl" -Destination "data\model\" -Force

# Restore config (optional - review changes first)
Copy-Item -Path "data\model\GOLDEN_V17_BASELINE\config_v17.yaml" -Destination "config.yaml" -Force
```

## Frozen Date
Created: April 30, 2026  
Git commit: [will be updated after commit]

---
**This baseline represents the culmination of the v17 development cycle and should be considered the gold standard for model performance.**