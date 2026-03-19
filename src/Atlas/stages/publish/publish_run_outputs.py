from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import pandas as pd


def run_publish_stage(
    *,
    LOCAL_TZ,
    OUT_DIR: Path,
    scored: pd.DataFrame,
    scored_for_optimizer: pd.DataFrame,
    sys3: pd.DataFrame,
    sys4: pd.DataFrame,
    sys5: pd.DataFrame,
    wind3: pd.DataFrame,
    wind4: pd.DataFrame,
    wind5: pd.DataFrame,
    sys3_winprob: Optional[pd.DataFrame] = None,
    sys4_winprob: Optional[pd.DataFrame] = None,
    sys5_winprob: Optional[pd.DataFrame] = None,
    wind3_winprob: Optional[pd.DataFrame] = None,
    wind4_winprob: Optional[pd.DataFrame] = None,
    wind5_winprob: Optional[pd.DataFrame] = None,
    write_csv_clean: Optional[Callable[[pd.DataFrame, Path], Path]] = None,
) -> Path:
    """
    Publish Stage (IO only).
    Creates run dirs, writes outputs, prints summary.
    No business logic / transforms.
    """

    if write_csv_clean is None:
        raise ValueError("write_csv_clean must be provided")
    w = write_csv_clean  # local non-optional alias

    ts = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    windfall_dir = run_dir / "Windfall"
    system_dir = run_dir / "System"
    windfall_dir.mkdir(parents=True, exist_ok=True)
    system_dir.mkdir(parents=True, exist_ok=True)

    w(scored, run_dir / "scored_legs.csv")
    w(scored_for_optimizer, run_dir / "scored_legs_deduped.csv")

    # SYSTEM (default / kernel EV)
    w(sys3, system_dir / "recommended_3leg.csv")
    w(sys4, system_dir / "recommended_4leg.csv")
    w(sys5, system_dir / "recommended_5leg.csv")

    # SYSTEM (secondary / no-kernel win-prob)
    if sys3_winprob is not None:
        w(sys3_winprob, system_dir / "recommended_3leg_winprob.csv")
    if sys4_winprob is not None:
        w(sys4_winprob, system_dir / "recommended_4leg_winprob.csv")
    if sys5_winprob is not None:
        w(sys5_winprob, system_dir / "recommended_5leg_winprob.csv")

    # WINDFALL (default / kernel EV)
    w(wind3, windfall_dir / "recommended_3leg.csv")
    w(wind4, windfall_dir / "recommended_4leg.csv")
    w(wind5, windfall_dir / "recommended_5leg.csv")

    # WINDFALL (secondary / no-kernel win-prob)
    if wind3_winprob is not None:
        w(wind3_winprob, windfall_dir / "recommended_3leg_winprob.csv")
    if wind4_winprob is not None:
        w(wind4_winprob, windfall_dir / "recommended_4leg_winprob.csv")
    if wind5_winprob is not None:
        w(wind5_winprob, windfall_dir / "recommended_5leg_winprob.csv")

    # Legacy mirrors SYSTEM (default)
    w(sys3, run_dir / "recommended_3leg.csv")
    w(sys4, run_dir / "recommended_4leg.csv")
    w(sys5, run_dir / "recommended_5leg.csv")

    # Legacy mirrors SYSTEM (secondary / no-kernel win-prob)
    if sys3_winprob is not None:
        w(sys3_winprob, run_dir / "recommended_3leg_winprob.csv")
    if sys4_winprob is not None:
        w(sys4_winprob, run_dir / "recommended_4leg_winprob.csv")
    if sys5_winprob is not None:
        w(sys5_winprob, run_dir / "recommended_5leg_winprob.csv")

    print("Model run complete.")
    print(f"Outputs folder: {OUT_DIR}")
    print(f"Run folder: {run_dir}")
    print("Wrote:")
    print(f" - {run_dir / 'scored_legs.csv'}")
    print(f" - {run_dir / 'scored_legs_deduped.csv'}")
    print(f" - {system_dir / 'recommended_3leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_4leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_5leg.csv'} (SYSTEM)")
    print(f" - {windfall_dir / 'recommended_3leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_4leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_5leg.csv'} (WINDFALL)")

    if sys3_winprob is not None:
        print(f" - {system_dir / 'recommended_3leg_winprob.csv'} (SYSTEM winprob)")
    if sys4_winprob is not None:
        print(f" - {system_dir / 'recommended_4leg_winprob.csv'} (SYSTEM winprob)")
    if sys5_winprob is not None:
        print(f" - {system_dir / 'recommended_5leg_winprob.csv'} (SYSTEM winprob)")

    if wind3_winprob is not None:
        print(f" - {windfall_dir / 'recommended_3leg_winprob.csv'} (WINDFALL winprob)")
    if wind4_winprob is not None:
        print(f" - {windfall_dir / 'recommended_4leg_winprob.csv'} (WINDFALL winprob)")
    if wind5_winprob is not None:
        print(f" - {windfall_dir / 'recommended_5leg_winprob.csv'} (WINDFALL winprob)")

    return run_dir