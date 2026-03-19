import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> int:
    print(f"\n[RUN] {' '.join(shlex.quote(c) for c in cmd)}")
    p = subprocess.run(cmd, cwd=str(cwd))
    return int(p.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run an Atlas command, then inspect latest scored CSV (role context stats).",
        epilog=(
            "Examples:\n"
            "  py -3.11 tools\\run_and_inspect.py -- py -3.11 -m Atlas.engine.main\n"
            "  py -3.11 tools\\run_and_inspect.py -- py -3.11 run_today.py\n"
            "  py -3.11 tools\\run_and_inspect.py -- py -3.11 -m Atlas.stages.filter.filter_recommendations_live --tag late\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument(
        "--data-root",
        default="data",
        help="Where to search for scored_legs_deduped*.csv after the run (default: data)",
    )
    ap.add_argument(
        "--pattern",
        default="scored_legs_deduped*.csv",
        help="CSV glob to inspect (default: scored_legs_deduped*.csv)",
    )
    ap.add_argument("--cap", type=float, default=1.10, help="Clamp cap (default: 1.10)")
    ap.add_argument("--eps", type=float, default=1e-6, help="Float epsilon (default: 1e-6)")
    ap.add_argument("--raw-threshold", type=float, default=1.10, help="Raw threshold (default: 1.10)")
    ap.add_argument("--top", type=int, default=15, help="How many extreme rows to print (default: 15)")
    ap.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to run after a '--' separator. Example: -- py -3.11 run_today.py",
    )
    args = ap.parse_args()

    if not args.cmd or args.cmd[0] != "--":
        print("[ERROR] You must provide a command after '--'.")
        print("Example: py -3.11 tools\\run_and_inspect.py -- py -3.11 run_today.py")
        return 2

    # strip the "--"
    cmd = args.cmd[1:]
    repo_root = Path(__file__).resolve().parents[1]

    # 1) run atlas command
    rc = run(cmd, cwd=repo_root)
    if rc != 0:
        print(f"[ERROR] Command failed with exit code {rc}. Skipping inspect.")
        return rc

    # 2) run inspector
    inspector = repo_root / "tools" / "inspect_role_ctx.py"
    if not inspector.exists():
        print(f"[ERROR] Missing inspector script: {inspector}")
        print("Create tools/inspect_role_ctx.py first (I already gave you that file).")
        return 2

    py = sys.executable  # the same python running this script
    inspect_cmd = [
        py,
        str(inspector),
        "--data-root",
        str(args.data_root),
        "--pattern",
        str(args.pattern),
        "--cap",
        str(args.cap),
        "--eps",
        str(args.eps),
        "--raw-threshold",
        str(args.raw_threshold),
        "--top",
        str(args.top),
    ]
    return run(inspect_cmd, cwd=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())