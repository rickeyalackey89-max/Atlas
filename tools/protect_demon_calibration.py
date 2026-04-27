#!/usr/bin/env python3
"""
DEMON Calibration Protection Script

This script protects the custom DEMON tier calibration fix from being overwritten
during LODO runs, trainer executions, or config file resets.

Usage:
  python tools/protect_demon_calibration.py --backup     # Save current calibration settings
  python tools/protect_demon_calibration.py --restore    # Restore DEMON calibration settings
  python tools/protect_demon_calibration.py --apply      # Apply DEMON fix to current config
  python tools/protect_demon_calibration.py --status     # Check current calibration status
"""

import json
import yaml
from pathlib import Path
from typing import Dict, Any
import argparse

# Paths
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config.yaml"
DEMON_CALIB_PATH = REPO_ROOT / "data/model/telemetry_calibration.demon_fix.json"
BACKUP_PATH = REPO_ROOT / "data/model/.calibration_backup.json"

# DEMON calibration settings
DEMON_CALIBRATION_CONFIG = {
    "active_calibration": "demon_fix",
    "apply_active_calibration": True,
    "active_calibration_path": "data/model/telemetry_calibration.demon_fix.json"
}

def read_config() -> Dict[str, Any]:
    """Read current config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def write_config(config: Dict[str, Any]) -> None:
    """Write config.yaml preserving formatting."""
    with open(CONFIG_PATH, 'w') as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

def backup_calibration_settings() -> None:
    """Backup current calibration settings."""
    config = read_config()
    
    # Extract telemetry section
    telemetry_section = config.get('telemetry', {})
    
    backup_data = {
        "active_calibration": telemetry_section.get('active_calibration'),
        "apply_active_calibration": telemetry_section.get('apply_active_calibration'),
        "active_calibration_path": telemetry_section.get('active_calibration_path'),
        "backup_timestamp": str(CONFIG_PATH.stat().st_mtime)
    }
    
    with open(BACKUP_PATH, 'w') as f:
        json.dump(backup_data, f, indent=2)
    
    print(f"✅ Calibration settings backed up to {BACKUP_PATH}")
    print(f"   Current: active_calibration = {backup_data['active_calibration']}")

def restore_calibration_settings() -> None:
    """Restore calibration settings from backup."""
    if not BACKUP_PATH.exists():
        print(f"❌ No backup found at {BACKUP_PATH}")
        print("   Use --backup first, or --apply to set DEMON calibration")
        return
    
    with open(BACKUP_PATH) as f:
        backup_data = json.load(f)
    
    config = read_config()
    
    # Ensure telemetry section exists
    if 'telemetry' not in config:
        config['telemetry'] = {}
    
    # Restore calibration settings
    for key in ['active_calibration', 'apply_active_calibration', 'active_calibration_path']:
        if backup_data.get(key) is not None:
            config['telemetry'][key] = backup_data[key]
    
    write_config(config)
    
    print(f"✅ Calibration settings restored from backup")
    print(f"   Restored: active_calibration = {backup_data['active_calibration']}")

def apply_demon_calibration() -> None:
    """Apply DEMON tier calibration fix to config."""
    config = read_config()
    
    # Ensure telemetry section exists
    if 'telemetry' not in config:
        config['telemetry'] = {}
    
    # Apply DEMON calibration settings
    config['telemetry'].update(DEMON_CALIBRATION_CONFIG)
    
    write_config(config)
    
    print("✅ DEMON tier calibration fix applied to config.yaml")
    print("   Settings:")
    for key, value in DEMON_CALIBRATION_CONFIG.items():
        print(f"     {key}: {value}")
    
    # Verify calibration file exists
    if not DEMON_CALIB_PATH.exists():
        print(f"\n⚠️  WARNING: Calibration file not found: {DEMON_CALIB_PATH}")
        print("   The calibration file should have been created earlier.")

def check_calibration_status() -> None:
    """Check current calibration status."""
    config = read_config()
    telemetry = config.get('telemetry', {})
    
    current_calib = telemetry.get('active_calibration')
    calib_enabled = telemetry.get('apply_active_calibration', False)
    calib_path = telemetry.get('active_calibration_path')
    
    print("📊 Current Calibration Status:")
    print(f"   active_calibration: {current_calib}")
    print(f"   apply_active_calibration: {calib_enabled}")
    print(f"   active_calibration_path: {calib_path}")
    
    # Check if DEMON calibration is active
    if current_calib == "demon_fix":
        print("✅ DEMON tier calibration fix is ACTIVE")
        
        # Verify calibration file exists
        if DEMON_CALIB_PATH.exists():
            print(f"✅ Calibration file exists: {DEMON_CALIB_PATH}")
        else:
            print(f"❌ Calibration file missing: {DEMON_CALIB_PATH}")
    else:
        print("❌ DEMON tier calibration fix is NOT active")
        print("   Run with --apply to activate it")
    
    # Check for backup
    if BACKUP_PATH.exists():
        with open(BACKUP_PATH) as f:
            backup_data = json.load(f)
        print(f"\n💾 Backup available: {backup_data['active_calibration']} (from {backup_data.get('backup_timestamp', 'unknown time')})")

def main():
    parser = argparse.ArgumentParser(description="Protect DEMON tier calibration settings")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup", action="store_true", help="Backup current calibration settings")
    group.add_argument("--restore", action="store_true", help="Restore calibration settings from backup")
    group.add_argument("--apply", action="store_true", help="Apply DEMON calibration fix")
    group.add_argument("--status", action="store_true", help="Check calibration status")
    
    args = parser.parse_args()
    
    if args.backup:
        backup_calibration_settings()
    elif args.restore:
        restore_calibration_settings()
    elif args.apply:
        apply_demon_calibration()
    elif args.status:
        check_calibration_status()

if __name__ == "__main__":
    main()