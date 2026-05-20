from mlb.runtime.wind_factors import _merge_orientation_rows, _parse_league_sheet, _parse_orientation_sheet, _parse_park_sheet


def test_wind_factor_league_sheet_parser_flattens_direction_buckets():
    rows = [
        ["title", None, None, None, None, "title"],
        ["Wind", "To Left", "To Center", "To Right", None, "Wind", "From Left", "From Center", "From Right"],
        ["0 to 5 mph", 1.0, 1.1, 1.2, None, "0 to 5 mph", 0.9, 0.8, 0.7],
        ["6 to 10 mph", 1.0, 1.1, 1.2, None, "6 to 10 mph", 0.9, 0.8, 0.7],
        ["11 to 15 mph", 1.0, 1.1, 1.2, None, "11 to 15 mph", 0.9, 0.8, 0.7],
        ["16+ mph", 1.0, 1.1, 1.2, None, "16+ mph", 0.9, 0.8, 0.7],
        [],
        [],
        [],
        ["across"],
        ["Wind", "Left to Right", "Right to Left"],
        ["0 to 5 mph", 1.3, 1.4],
        ["6 to 10 mph", 1.3, 1.4],
        ["11 to 15 mph", 1.3, 1.4],
        ["16+ mph", 1.3, 1.4],
    ]

    parsed = _parse_league_sheet(rows, metric="hr_per_game")

    assert len(parsed) == 32
    assert parsed[1]["wind_class"] == "out"
    assert parsed[1]["direction_key"] == "to_center"
    assert parsed[-1]["wind_class"] == "across"
    assert parsed[-1]["direction_key"] == "right_to_left"


def test_wind_factor_park_sheet_parser_canonicalizes_team_codes():
    rows = [
        ["title"],
        ["Team/Park Code", "HR Added by Wind", "HR Prevented by Wind", "Net Gain/Loss"],
        ["KCR", 2, 67, -65],
        ["SDP", 12, 5, 7],
    ]

    parsed = _parse_park_sheet(rows)

    assert parsed[0]["team"] == "KC"
    assert parsed[0]["net_hr_wind"] == -65
    assert parsed[1]["team"] == "SD"
    assert parsed[1]["wind_hr_susceptibility_score"] > 0


def test_wind_factor_park_sheet_parser_keeps_optional_orientation_columns():
    rows = [
        ["title"],
        [
            "Team/Park Code",
            "HR Added by Wind",
            "HR Prevented by Wind",
            "Net Gain/Loss",
            "Center Field Bearing",
            "Orientation Source",
        ],
        ["BOS", 19, 13, 6, 45, "manual_orientation_sheet"],
    ]

    parsed = _parse_park_sheet(rows)

    assert parsed[0]["team"] == "BOS"
    assert parsed[0]["center_field_bearing_degrees"] == 45
    assert parsed[0]["orientation_source"] == "manual_orientation_sheet"
    assert "park_orientation_available" in parsed[0]["flags"]


def test_wind_factor_orientation_sheet_merges_ballpark_compass_inputs():
    park_rows = _parse_park_sheet(
        [
            ["title"],
            ["Team/Park Code", "HR Added by Wind", "HR Prevented by Wind", "Net Gain/Loss"],
            ["CLE", 12, 5, 7],
        ]
    )
    orientation = _parse_orientation_sheet(
        [
            ["title"],
            ["note"],
            [],
            [
                "League",
                "Team Abbrev",
                "Team",
                "Ballpark",
                "Retractable Roof?",
                "Center Field Direction (Home -> CF)",
                "Home Plate Direction (CF -> Home)",
                "Wind Blowing OUT Helps Carry (Weather Wind FROM -> TO)",
                "Wind Blowing IN Knocks Down (Weather Wind FROM -> TO)",
                "Crosswind LF -> RF (Weather Wind FROM -> TO)",
                "Crosswind RF -> LF (Weather Wind FROM -> TO)",
                "Modeling Note",
            ],
            [
                "AL",
                "CLE",
                "Cleveland Guardians",
                "Progressive Field",
                "No",
                "N",
                "S",
                "FROM S -> TO N",
                "FROM N -> TO S",
                "FROM NW -> TO NE",
                "FROM NE -> TO NW",
                "fixture note",
            ],
        ]
    )

    merged = _merge_orientation_rows(park_rows, orientation)

    assert merged[0]["park_name"] == "Progressive Field"
    assert merged[0]["center_field_direction"] == "N"
    assert merged[0]["center_field_bearing_degrees"] == 0.0
    assert merged[0]["wind_out_from_direction"] == "S"
    assert merged[0]["wind_in_from_direction"] == "N"
    assert merged[0]["crosswind_lf_to_rf_from_direction"] == "NW"
    assert "park_orientation_available" in merged[0]["flags"]
