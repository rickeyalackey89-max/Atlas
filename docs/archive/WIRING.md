# Atlas wiring report (auto-generated)

Generated: 2026-02-13 15:26:24
RepoRoot: C:\Users\rick\projects\Atlas

## Python entrypoints (__main__)

- run_today.py (argparse=True, typer=False, click=False)
- scripts\dev\adhoc\build_external_slips_from_picks.py (argparse=True, typer=False, click=False)
- scripts\dev\adhoc\build_roster_and_slate.py (argparse=False, typer=False, click=False)
- scripts\dev\adhoc\fetch_rotowire_priors.py (argparse=True, typer=False, click=False)
- scripts\dev\adhoc\finalize_now.py (argparse=False, typer=False, click=False)
- scripts\dev\adhoc\gamescript_best_combos.py (argparse=False, typer=False, click=False)
- scripts\dev\adhoc\injury\injury_pull_and_parse.py (argparse=False, typer=False, click=False)
- scripts\dev\adhoc\parse_bettingpros_paste.py (argparse=False, typer=False, click=False)
- scripts\dev\adhoc\postprocess_outputs.py (argparse=False, typer=False, click=False)
- scripts\dev\adhoc\write_definitions_readme.py (argparse=False, typer=False, click=False)
- scripts\dev\analysis\backtest\backtest_role_layer.py (argparse=True, typer=False, click=False)
- scripts\dev\analysis\graph_and_testbet_730.py (argparse=False, typer=False, click=False)
- scripts\dev\analysis\top3_parlays_from_compare.py (argparse=False, typer=False, click=False)
- scripts\dev\boards\build_audit_last5_board.py (argparse=False, typer=False, click=False)
- scripts\dev\boards\compare_snapshots.py (argparse=True, typer=False, click=False)
- scripts\dev\boards\snapshot_prizepicks_board.py (argparse=True, typer=False, click=False)
- scripts\dev\boards\update_board_from_prizepicks.py (argparse=False, typer=False, click=False)
- scripts\dev\diagnostics\diag_fetch_only.py (argparse=False, typer=False, click=False)
- scripts\dev\export\export_cloudflare_payload.py (argparse=False, typer=False, click=False)
- scripts\dev\export\export_invalidations_to_dashboard.py (argparse=False, typer=False, click=False)
- scripts\dev\export\export_recommended_to_dashboard.py (argparse=False, typer=False, click=False)
- scripts\dev\export\export_status_to_dashboard.py (argparse=False, typer=False, click=False)
- scripts\dev\gamelogs\refresh_nba_gamelogs.py (argparse=True, typer=False, click=False)
- scripts\dev\gamelogs\update_all_gamelogs.py (argparse=False, typer=False, click=False)
- scripts\dev\gamelogs\update_gamelogs.py (argparse=False, typer=False, click=False)
- scripts\dev\validation\enforce_playability_on_today.py (argparse=False, typer=False, click=False)
- scripts\dev\validation\test_playability.py (argparse=False, typer=False, click=False)
- scripts\dev\validation\validate_recs_vs_today.py (argparse=False, typer=False, click=False)
- src\Atlas\build_cheatsheet_html.py (argparse=True, typer=False, click=False)
- src\Atlas\legacy\main.py (argparse=False, typer=False, click=False)
- src\Atlas\rebuild_today_from_any_raw.py (argparse=False, typer=False, click=False)
- src\Atlas\rebuild_today_from_latest_raw.py (argparse=False, typer=False, click=False)
- tools\analyze_slip_probs_and_exposure.py (argparse=False, typer=False, click=False)
- tools\backtest_role_layer.py (argparse=True, typer=False, click=False)
- tools\backtest_snapshots_accuracy.py (argparse=False, typer=False, click=False)
- tools\build_share_matrix.py (argparse=False, typer=False, click=False)
- tools\dev_team_role_dump.py (argparse=False, typer=False, click=False)
- tools\fetch_prizepicks_today.py (argparse=False, typer=False, click=False)
- tools\filter_recommendations_live.py (argparse=True, typer=False, click=False)
- tools\rebuild_today_from_any_raw.py (argparse=False, typer=False, click=False)
- tools\refresh_nba_gamelogs.py (argparse=True, typer=False, click=False)
- tools\simulate_bankroll_from_slips.py (argparse=False, typer=False, click=False)

## PowerShell/batch invoking python

- run_publish.cmd:30  py -3 run_today.py >>"%LOG%" 2>&1
- scripts\run_iael_11am.cmd:13  python scripts\injury\injury_pull_and_parse.py >> %LOG% 2>&1
- scripts\run_iael_11am.cmd:20  python run_today.py >> %LOG% 2>&1
- scripts\run_iael_11am.cmd:36  python scripts\alerts\slack_notify.py >> %LOG% 2>&1
- scripts\run_iael_230pm.cmd:15  python scripts\injury\injury_pull_and_parse.py >> %LOG% 2>&1
- scripts\run_iael_230pm.cmd:22  python run_today.py >> %LOG% 2>&1
- scripts\run_iael_230pm.cmd:38  python scripts\alerts\slack_notify.py >> %LOG% 2>&1
- scripts\run_iael_morning.cmd:13  python scripts\injury\injury_pull_and_parse.py >> %LOG% 2>&1
- scripts\run_iael_morning.cmd:20  python run_today.py >> %LOG% 2>&1
- scripts\run_iael_morning.cmd:36  python scripts\alerts\slack_notify.py >> %LOG% 2>&1
- src\Atlas\Public\Invoke-AtlasRunAllAndPublish.ps1:37  & $py (Join-Path $AtlasRoot 'tools\refresh_nba_gamelogs.py')
- src\Atlas\Public\Invoke-AtlasRunAllAndPublish.ps1:63  & $py (Join-Path $AtlasRoot 'tools\build_audit_last5_board.py')
- src\Atlas\Public\Invoke-AtlasRunAllAndPublish.ps1:73  & $py (Join-Path $AtlasRoot 'tools\export_cloudflare_payload.py')
- tools\Wiring-Audit.ps1:22  # Hard-gate (requires -IncludeToolsInventory): fail if any tools/*.py exist but are not wired by run_today.py
- tools\Wiring-Audit.ps1:252  # --- 4) Optional inventory of tools/*.py not referenced by run_today.py ---

## Core static analysis (src/Atlas)

- Source root: src/Atlas
- Import edges captured: 137
- Call edges captured: 2151

## Top call targets (by frequency)

- float — 109
- astype — 88
- str — 79
- print — 65
- len — 64
- pd.to_numeric — 60
- strip — 54
- str.strip — 54
- fillna — 53
- int — 43
- str.upper — 37
- pd.DataFrame — 33
- clip — 33
- upper — 29
- _clean_str — 26
- r.get — 26
- apply — 26
- isinstance — 25
- copy — 22
- max — 20
- attr.get — 20
- reset_index — 18
- out.get — 18
- df.get — 17
- attrs.get — 16
- set — 16
- map — 15
- rules.get — 14
- list — 13
- sum — 12
- Path — 12
- pd.Series — 12
- join — 12
- pd.read_csv — 11
- replace — 11
- write_csv_clean — 11
- bool — 11
- lower — 11
- range — 10
- isin — 10
- pd.to_datetime — 9
- ValueError — 9
- p.get — 9
- str.lower — 8
- np.clip — 8
- head — 8
- dropna — 7
- FileNotFoundError — 7
- pri_cfg.get — 7
- abs — 7

## Mermaid: imports + calls (trimmed)

```mermaid
flowchart TD
  N1["src/Atlas/build_cheatsheet_html.py"]
  N2["__future__.annotations"]
  N1 --> N2
  N3["argparse"]
  N1 --> N3
  N4["html"]
  N1 --> N4
  N5["os"]
  N1 --> N5
  N6["re"]
  N1 --> N6
  N7["pathlib.Path"]
  N1 --> N7
  N8["datetime.datetime"]
  N1 --> N8
  N9["pandas"]
  N1 --> N9
  N10["Atlas.runtime.paths.find_repo_root"]
  N1 --> N10
  N11["src/Atlas/rebuild_today_from_any_raw.py"]
  N11 --> N2
  N12["json"]
  N11 --> N12
  N11 --> N6
  N11 --> N8
  N13["datetime.timezone"]
  N11 --> N13
  N11 --> N7
  N14["typing.Any"]
  N11 --> N14
  N11 --> N9
  N15["src/Atlas/rebuild_today_from_latest_raw.py"]
  N15 --> N5
  N15 --> N12
  N15 --> N8
  N15 --> N13
  N15 --> N14
  N16["typing.Dict"]
  N15 --> N16
  N17["typing.List"]
  N15 --> N17
  N18["typing.Optional"]
  N15 --> N18
  N19["typing.Tuple"]
  N15 --> N19
  N15 --> N9
  N20["src/Atlas/legacy/blowout.py"]
  N20 --> N2
  N21["math"]
  N20 --> N21
  N22["dataclasses.dataclass"]
  N20 --> N22
  N23["src/Atlas/legacy/external_priors.py"]
  N23 --> N2
  N23 --> N7
  N23 --> N10
  N23 --> N14
  N23 --> N16
  N23 --> N18
  N24["numpy"]
  N23 --> N24
  N23 --> N9
  N25["yaml"]
  N23 --> N25
  N26["src/Atlas/legacy/features.py"]
  N26 --> N2
  N26 --> N16
  N27["typing.Iterable"]
  N26 --> N27
  N26 --> N18
  N26 --> N19
  N28["unicodedata"]
  N26 --> N28
  N26 --> N24
  N26 --> N9
  N29["src/Atlas/legacy/main.py"]
  N29 --> N2
  N30["ast"]
  N29 --> N30
  N29 --> N12
  N31["random"]
  N29 --> N31
  N29 --> N6
  N29 --> N8
  N29 --> N7
  N29 --> N14
  N29 --> N24
  N29 --> N9
  N29 --> N25
  N32["zoneinfo.ZoneInfo"]
  N29 --> N32
  N33["external_priors.apply_external_priors"]
  N29 --> N33
  N34["matchup_enricher.enrich_with_matchups"]
  N29 --> N34
  N35["minutes.minutes_sensitivity"]
  N29 --> N35
  N36["optimize._score_slip"]
  N29 --> N36
  N37["payout_tables.FLEX_3"]
  N29 --> N37
  N38["payout_tables.FLEX_4"]
  N29 --> N38
  N39["payout_tables.FLEX_5"]
  N29 --> N39
  N40["payout_tables.POWER_MULT"]
  N29 --> N40
  N41["probability.simulate_leg_probability"]
  N29 --> N41
  N42["runtime.telemetry_calibration.apply_calibration"]
  N29 --> N42
  N43["runtime.telemetry_calibration.load_calibration"]
  N29 --> N43
  N44["src/Atlas/legacy/matchup_enricher.py"]
  N44 --> N6
  N44 --> N8
  N44 --> N9
  N45["src/Atlas/legacy/minutes.py"]
  N45 --> N2
  N46["src/Atlas/legacy/optimize.py"]
  N46 --> N2
  N46 --> N31
  N46 --> N6
  N46 --> N14
  N46 --> N27
  N46 --> N9
  N47["pp_pricing.load_kernel"]
  N46 --> N47
  N48["pp_pricing.power_multiplier"]
  N46 --> N48
  N49["src/Atlas/legacy/payouts.py"]
  N49 --> N17
  N50["payout_tables.PayoutTable"]
  N49 --> N50
  N51["src/Atlas/legacy/payout_tables.py"]
  N51 --> N22
  N51 --> N16
  N51 --> N19
  N52["src/Atlas/legacy/playability.py"]
  N52 --> N9
  N52 --> N22
  N52 --> N16
  N52 --> N19
  N52 --> N18
  N53["src/Atlas/legacy/pp_pricing.py"]
  N53 --> N2
  N53 --> N22
  N53 --> N21
  N53 --> N14
  N53 --> N16
  N54["src/Atlas/legacy/probability.py"]
  N54 --> N24
  N54 --> N9
  N54 --> N7
  N55["features.summarize_stat"]
  N54 --> N55
  N56["features.get_player_window"]
  N54 --> N56
  N57["features.blowout_probability"]
  N54 --> N57
  N58["model.team_share_reallocator.compute_role_multiplier"]
  N54 --> N58
  N59["src/Atlas/legacy/slip_scoring.py"]
  N59 --> N2
  N60["collections.Counter"]
  N59 --> N60
  N61["src/Atlas/model/team_share_reallocator.py"]
  N61 --> N2
  N61 --> N22
  N61 --> N16
  N61 --> N18
  N61 --> N19
  N61 --> N17
  N61 --> N24
  N61 --> N9
  N62["src/Atlas/runtime/orchestrator.py"]
  N62 --> N2
  N62 --> N5
  N63["subprocess"]
  N62 --> N63
  N64["sys"]
  N62 --> N64
  N65["time"]
  N62 --> N65
  N62 --> N22
  N62 --> N8
  N62 --> N7
  N62 --> N17
  N62 --> N18
  N62 --> N10
  N66["src/Atlas/runtime/paths.py"]
  N66 --> N2
  N66 --> N7
  N67["src/Atlas/runtime/telemetry_calibration.py"]
  N67 --> N2
  N67 --> N12
  N67 --> N22
  N67 --> N8
  N67 --> N7
  N67 --> N14
  N67 --> N16
  N67 --> N18
  N67 --> N19
  N67 --> N9
  N68["src/Atlas/build_cheatsheet_html.py:_canon_player"]
  N69["lower"]
  N68 --> N69
  N70["re.sub"]
  N68 --> N70
  N71["strip"]
  N68 --> N71
  N72["str"]
  N68 --> N72
  N73["src/Atlas/build_cheatsheet_html.py:_canon_market"]
  N74["upper"]
  N73 --> N74
  N73 --> N70
  N73 --> N71
  N73 --> N72
  N75["src/Atlas/build_cheatsheet_html.py:_canon_dir"]
  N75 --> N74
  N75 --> N71
  N75 --> N72
  N76["src/Atlas/build_cheatsheet_html.py:_project_root"]
  N77["find_repo_root"]
  N76 --> N77
  N78["Path"]
  N76 --> N78
  N79["src/Atlas/build_cheatsheet_html.py:_auto_find_scored"]
  N80["list"]
  N79 --> N80
  N81["rglob"]
  N79 --> N81
  N79 --> N80
  N79 --> N81
  N82["cand.sort"]
  N79 --> N82
  N83["p.stat"]
  N79 --> N83
  N84["src/Atlas/build_cheatsheet_html.py:_prepare"]
  N85["pd.read_csv"]
  N84 --> N85
  N84 --> N85
  N86["scored_path.exists"]
  N84 --> N86
  N84 --> N85
  N87["bp.copy"]
  N84 --> N87
  N88["bp2.get"]
  N84 --> N88
  N89["map"]
  N84 --> N89
  N90["src/Atlas/build_cheatsheet_html.py:_bp_market_to_pp"]
  N91["_canon_market"]
  N90 --> N91
  N84 --> N89
  N92["astype"]
  N84 --> N92
  N84 --> N89
  N84 --> N88
  N93["pd.to_numeric"]
  N84 --> N93
  N84 --> N88
  N94["board.copy"]
  N84 --> N94
  N84 --> N89
  N84 --> N89
  N95["b2.get"]
  N84 --> N95
  N84 --> N89
  N84 --> N95
  N84 --> N93
  N84 --> N95
  N96["scored.copy"]
  N84 --> N96
  N84 --> N89
  N84 --> N89
  N97["s2.get"]
  N84 --> N97
  N84 --> N89
  N84 --> N97
  N84 --> N93
  N84 --> N97
  N98["b2.drop"]
  N84 --> N98
  N99["bp2.merge"]
  N84 --> N99
  N100["s2.drop"]
  N84 --> N100
  N101["m.merge"]
  N84 --> N101
  N102["isna"]
  N84 --> N102
  N103["m.get"]
  N84 --> N103
  N84 --> N102
  N84 --> N103
  N104["src/Atlas/build_cheatsheet_html.py:_reason"]
  N105["bool"]
  N104 --> N105
  N106["row.get"]
  N104 --> N106
  N104 --> N72
  N104 --> N106
  N107["m.apply"]
  N84 --> N107
  N108["m.rename"]
  N84 --> N108
```

