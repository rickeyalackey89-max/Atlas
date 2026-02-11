import os
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "data", "output", "latest", "all")
OUT_PATH = os.path.join(OUT_DIR, "README_metrics.csv")

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    rows = [
        {"field": "p_adj", "meaning": "Simulated hit probability after blowout/minutes adjustment", "used_for": "Risk-adjusted probability signal"},
        {"field": "p_eff", "meaning": "Optimizer 'effective' probability used for ranking/edges (post-feature adjustments)", "used_for": "Ranking + EV/edge calculations"},
        {"field": "p_combo", "meaning": "Combined score from p_adj + p_eff, penalized when they disagree", "used_for": "One-number summary using both signals"},
        {"field": "agreement_gap", "meaning": "Absolute difference between p_eff and p_adj", "used_for": "Detect disagreement / uncertainty"},
        {"field": "agreement_tier", "meaning": "STRONG/GOOD/MIXED/DISAGREE/NO_EFF based on value + agreement", "used_for": "Quick confidence label"},
        {"field": "tier", "meaning": "Same as agreement_tier (shown in parlay report)", "used_for": "Quick confidence label"},
    ]

    pd.DataFrame(rows).to_csv(OUT_PATH, index=False)
    print(f"Wrote: {OUT_PATH}")

if __name__ == "__main__":
    main()