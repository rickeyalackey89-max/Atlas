from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "scripts" / "dev" / "adhoc" / "injury" / "injury_pull_and_parse.py"


def _load_parser_module():
    spec = importlib.util.spec_from_file_location("injury_pull_and_parse", PARSER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_txt_rows_preserves_san_antonio_team_context(tmp_path):
    parser = _load_parser_module()
    txt_path = tmp_path / "injury.txt"
    txt_path.write_text(
        "\n".join(
            [
                "Game Date    Game Time    Matchup   Team                           Player Name         Current Status   Reason",
                "05/12/2026   08:00 (ET)   MIN@SAS   Minnesota Timberwolves         DiVincenzo, Donte   Out",
                "                                    San Antonio Spurs              Fox, De'Aaron       Questionable     Injury/Illness - Right Ankle; Soreness",
                "                                                                   Harper, Dylan       Questionable     Injury/Illness - Left Knee; Soreness",
            ]
        ),
        encoding="utf-8",
    )

    rows = parser.parse_txt_rows_text(txt_path)

    keyed = {(row["team"], row["player"], row["status"]) for row in rows}
    assert ("MIN", "DiVincenzo, Donte", "OUT") in keyed
    assert ("SAS", "Fox, De'Aaron", "QUESTIONABLE") in keyed
    assert ("SAS", "Harper, Dylan", "QUESTIONABLE") in keyed
