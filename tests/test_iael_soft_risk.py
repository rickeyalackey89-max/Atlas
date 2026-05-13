import pandas as pd

from Atlas.core.iael_soft_risk import apply_iael_soft_risk


def test_soft_risk_role_context_questionable_match_is_team_aware():
    scored = pd.DataFrame(
        [
            {
                "player": "Anthony Edwards",
                "team": "MIN",
                "stat": "PTS",
                "role_ctx_outs": '["Harper, Dylan"]',
            },
            {
                "player": "Stephon Castle",
                "team": "SAS",
                "stat": "PTS",
                "role_ctx_outs": '["Harper, Dylan"]',
            },
        ]
    )
    iael = pd.DataFrame(
        [
            {
                "team_norm": "SAS",
                "player": "Harper, Dylan",
                "status": "QUESTIONABLE",
            }
        ]
    )

    out = apply_iael_soft_risk(scored, iael)

    assert int(out.loc[0, "is_questionable"]) == 0
    assert float(out.loc[0, "q_out_frac"]) == 0.0
    assert int(out.loc[1, "is_questionable"]) == 1
    assert float(out.loc[1, "q_out_frac"]) == 0.5
