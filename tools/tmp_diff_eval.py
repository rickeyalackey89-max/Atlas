import pandas as pd

a = pd.read_csv(r"C:\Users\rick\projects\Atlas\tools\reports\baseline_20260227.csv")
b = pd.read_csv(r"C:\Users\rick\projects\Atlas\tools\reports\roleoff_20260227.csv")

# keep only evaluated, non-push rows
a = a[a["hit"].notna()].copy()
b = b[b["hit"].notna()].copy()
if "push" in a.columns:
    a = a[a["push"] != 1].copy()
if "push" in b.columns:
    b = b[b["push"] != 1].copy()

keys = ["projection_id", "source_projection_id", "game_id", "player_key", "stat", "line", "direction"]
cols = ["p_base", "p_role_role", "p_adj_role", "role_ctx_mult_role", "role_ctx_mult_raw_role", "role_ctx_sigma_mult_role", "role_ctx_reason_role"]

for k in keys:
    a[k] = a[k].fillna("__NA__").astype(str)
    b[k] = b[k].fillna("__NA__").astype(str)

a2 = a[keys + cols].copy()
b2 = b[keys + cols].copy()

a2["_occ"] = a2.groupby(keys).cumcount()
b2["_occ"] = b2.groupby(keys).cumcount()

m = a2.merge(b2, on=keys + ["_occ"], suffixes=("_basecfg", "_roleoff"), how="inner")

m["dp_base"] = m["p_base_basecfg"] - m["p_base_roleoff"]
m["dp_role"] = m["p_role_role_basecfg"] - m["p_role_role_roleoff"]
m["dp_adj"] = m["p_adj_role_basecfg"] - m["p_adj_role_roleoff"]

keep = m[(m["dp_base"] != 0) | (m["dp_role"] != 0) | (m["dp_adj"] != 0)].copy()

print("rows_compared =", len(m))
print("changed_rows =", len(keep))
print(
    keep[
        [
            "player_key",
            "stat",
            "line",
            "direction",
            "dp_base",
            "dp_role",
            "dp_adj",
            "role_ctx_mult_role_basecfg",
            "role_ctx_mult_role_roleoff",
            "role_ctx_reason_role_basecfg",
            "role_ctx_reason_role_roleoff",
        ]
    ]
    .head(80)
    .to_string(index=False)
)