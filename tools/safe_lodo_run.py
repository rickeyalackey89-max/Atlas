#!/usr/bin/env python3
"""
LODO Run Wrapper with DEMON Calibration Protection

This script wraps LODO runs or trainer executions to automatically protect
the DEMON tier calibration fix from being overwritten.

Usage:
  python tools/safe_lodo_run.py "python tools/gbm_v12_train.py --cache v13"
  python tools/safe_lodo_run.py "python tools/leg_trainer_v5_ev.py"
  python tools/safe_lodo_run.py "python tools/role_ctx_trainer_v1.py"

The script will:
1. Backup current calibration settings
2. Run the specified command
3. Restore DEMON calibration settings if they were changed
4. Report any calibration changes
"""

import subprocess
import sys
import json
from pathlib import Path

# Import protection functions
sys.path.append(str(Path(__file__).parent))
from protect_demon_calibration import (
    backup_calibration_settings, 
    apply_demon_calibration,
    check_calibration_status,
    read_config
)

def get_current_calibration():
    """Get current calibration setting."""
    config = read_config()
    return config.get('telemetry', {}).get('active_calibration')

def run_protected_command(command: str):
    """Run command with calibration protection."""
    print(f"🛡️  Protected LODO Run: {command}")
    print("=" * 60)
    
    # 1. Check initial state
    print("\n📊 Initial calibration status:")
    check_calibration_status()
    initial_calib = get_current_calibration()
    
    # 2. Backup current settings
    print("\n💾 Backing up calibration settings...")
    backup_calibration_settings()
    
    # 3. Run the command
    print(f"\n🚀 Running: {command}")
    print("-" * 40)
    
    try:
        result = subprocess.run(command, shell=True, capture_output=False)
        exit_code = result.returncode
    except Exception as e:
        print(f"❌ Command failed with exception: {e}")
        exit_code = 1
    
    print("-" * 40)
    print(f"Command completed with exit code: {exit_code}")
    
    # 4. Check if calibration was changed
    final_calib = get_current_calibration()
    
    if final_calib != initial_calib:
        print(f"\n⚠️  Calibration changed during run:")
        print(f"   Before: {initial_calib}")
        print(f"   After:  {final_calib}")
        
        if initial_calib == "demon_fix":
            print("🔄 Restoring DEMON calibration fix...")
            apply_demon_calibration()
            restored_calib = get_current_calibration()
            print(f"✅ Restored to: {restored_calib}")
        else:
            print("ℹ️  Original calibration was not demon_fix, leaving as-is")
    else:
        print(f"\n✅ Calibration unchanged: {final_calib}")
    
    # 5. Final status
    print("\n📊 Final calibration status:")
    check_calibration_status()
    
    return exit_code

def main():
    if len(sys.argv) != 2:
        print("Usage: python tools/safe_lodo_run.py \"<command_to_run>\"")
        print("\nExamples:")
        print("  python tools/safe_lodo_run.py \"python tools/gbm_v12_train.py --cache v13\"")
        print("  python tools/safe_lodo_run.py \"python tools/leg_trainer_v5_ev.py\"")
        sys.exit(1)
    
    command = sys.argv[1]
    exit_code = run_protected_command(command)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()