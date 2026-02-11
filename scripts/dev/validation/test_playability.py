import os
import sys

# Make sure Python can import from /src
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
sys.path.insert(0, SRC_PATH)

from playability import (
    load_board_catalog,
    build_board_map,
    Leg,
    is_playable_leg,
)

# Path to your catalog (relative to project root)
CATALOG_PATH = os.path.join(PROJECT_ROOT, "data", "board", "board_catalog.csv")


def main():
    board_df = load_board_catalog(CATALOG_PATH)
    board_map = build_board_map(board_df)

    tests = [
        Leg("Victor Wembanyama", "AST", 5.5, "UNDER"),  # demon under (should be False)
        Leg("Victor Wembanyama", "AST", 3, "UNDER"),    # standard under (should be True)
        Leg("Victor Wembanyama", "AST", 1.5, "OVER"),   # goblin over (should be True)
    ]

    print("=== Playability Tests ===")
    for leg in tests:
        result = is_playable_leg(leg, board_map)
        print(f"{leg.player} {leg.side} {leg.stat_type} {leg.line} -> {result}")


if __name__ == "__main__":
    main()