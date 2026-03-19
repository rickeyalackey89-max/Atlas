import argparse
import json
import math
from pathlib import Path

import pandas as pd


JOIN_KEY_PRIORITY = ['projection_id', 'prop_key', 'source_projection_id']
MERGE_FIELDS = [
    'hit',
    'p_adj',
    'p_cal',
    'p_for_cal',
    'p_cal_src',
    'direction',
    'role_ctx_outs_used',
    'telemetry_cal_key',
    'telemetry_mult',
]


def brier(p, y):
    p = pd.to_numeric(p, errors="coerce").clip(0.0, 1.0)
    y = pd.to_numeric(y, errors="coerce")
    mask = p.notna() & y.notna()
    if not mask.any():
        return float("nan")
    return float(((p[mask] - y[mask]) ** 2).mean())


def parse_args():
    parser = argparse.ArgumentParser(description='Compute per-key direction_under Brier deltas for the latest telemetry audit.')
    parser.add_argument('--audit-dir', type=Path, help='Optional telemetry_corpus audit directory to use.')
    parser.add_argument('--base-dir', type=Path, help='Optional corpus directory containing eval_legs.csv or scored_legs_deduped.csv files.')
    parser.add_argument('--candidate', help='Optional candidate name from candidate_scores.json to force.')
    parser.add_argument('--top', type=int, default=50, help='How many keys to print.')
    return parser.parse_args()


def _find_latest_audit(explicit_dir: Path | None) -> Path | None:
    if explicit_dir is not None:
        return explicit_dir

    audit_bases = [
        Path('.atlas_audit/diagnostics/telemetry_corpus'),
        Path('outputtelem/diagnostics/telemetry_corpus'),
    ]
    audits = []
    for audit_base in audit_bases:
        if audit_base.exists():
            audits.extend(sorted(path for path in audit_base.glob('*') if path.is_dir()))
    return max(audits, key=lambda path: path.name) if audits else None


def _select_candidate(candidates, preferred_name: str | None):
    def name_of(candidate):
        return candidate.get('candidate', '') or candidate.get('name', '')

    def with_mult_map(items):
        return [item for item in items if item.get('meta', {}).get('mult_map')]

    items = with_mult_map(candidates or [])
    if preferred_name:
        for item in items:
            if name_of(item) == preferred_name:
                return item

    for item in items:
        name = name_of(item).lower()
        if 'role_off' in name or 'role-off' in name or ('role' in name and 'off' in name):
            return item

    return items[0] if items else None


def _candidate_base_dirs(candidate_scores) -> list[Path]:
    seen = set()
    base_dirs = []
    labels = [item.get('label') for item in candidate_scores.get('variant_rankings', []) if item.get('label')]

    for label in labels:
        for variant in (f'outputtelem/{label}_extracted', f'outputtelem/{label}'):
            path = Path(variant)
            if path not in seen:
                seen.add(path)
                base_dirs.append(path)

    fallback_dirs = [
        Path('outputtelem/role_off_full_20260318_extracted'),
        Path('outputtelem/role_off_full_20260318'),
    ]
    for path in fallback_dirs:
        if path not in seen:
            seen.add(path)
            base_dirs.append(path)

    return base_dirs


def _looks_like_corpus_dir(path: Path) -> bool:
    return any(path.rglob('eval_legs.csv')) or any(path.rglob('scored_legs_deduped.csv'))


def _pick_base_dir(explicit_dir: Path | None, candidate_scores) -> Path | None:
    if explicit_dir is not None:
        return explicit_dir

    for base_dir in _candidate_base_dirs(candidate_scores):
        if base_dir.exists() and _looks_like_corpus_dir(base_dir):
            return base_dir
    return None


def _pick_join_key(scored_df: pd.DataFrame, eval_df: pd.DataFrame) -> str | None:
    best_key = None
    best_score = (-1, -1)
    for priority, key in enumerate(JOIN_KEY_PRIORITY):
        if key not in scored_df.columns or key not in eval_df.columns:
            continue
        left = scored_df[key].dropna().astype(str).str.strip()
        right = eval_df[key].dropna().astype(str).str.strip()
        overlap = len(set(left.unique()) & set(right.unique()))
        score = (overlap, -priority)
        if score > best_score:
            best_key = key
            best_score = score
    return best_key


def _merge_scored_with_eval(scored_df: pd.DataFrame, eval_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    join_key = _pick_join_key(scored_df, eval_df)
    if join_key is None:
        return scored_df.copy(), None

    eval_cols = [join_key] + [field for field in MERGE_FIELDS if field in eval_df.columns]
    eval_subset = eval_df[eval_cols].drop_duplicates(subset=[join_key])
    merged = scored_df.merge(eval_subset, on=join_key, how='left', suffixes=('', '_eval'))

    for field in MERGE_FIELDS:
        eval_field = f'{field}_eval'
        if eval_field not in merged.columns:
            continue
        if field in merged.columns:
            merged[field] = merged[field].combine_first(merged[eval_field])
            merged.drop(columns=[eval_field], inplace=True)
        else:
            merged.rename(columns={eval_field: field}, inplace=True)

    return merged, join_key


def _load_dataframe(base_dir: Path) -> tuple[pd.DataFrame, str, list[str]]:
    eval_files = sorted(base_dir.rglob('eval_legs.csv'))
    if eval_files:
        dfs = [pd.read_csv(file_path) for file_path in eval_files]
        return pd.concat(dfs, ignore_index=True), 'eval_legs.csv', []

    scored_files = sorted(base_dir.rglob('scored_legs_deduped.csv'))
    if not scored_files:
        raise FileNotFoundError(f'No eval_legs.csv or scored_legs_deduped.csv files found under {base_dir}')

    merged_frames = []
    join_keys_used = []
    for scored_file in scored_files:
        scored_df = pd.read_csv(scored_file)
        eval_file = scored_file.with_name('eval_legs.csv')
        if eval_file.exists():
            eval_df = pd.read_csv(eval_file)
            scored_df, join_key = _merge_scored_with_eval(scored_df, eval_df)
            if join_key:
                join_keys_used.append(join_key)
        merged_frames.append(scored_df)

    return pd.concat(merged_frames, ignore_index=True), 'scored_legs_deduped.csv+eval_legs.csv', sorted(set(join_keys_used))


def _lookup_mult(mult_map, key: str) -> float:
    if key in mult_map:
        return float(mult_map[key])
    if '|UNDER' in key and key.replace('|UNDER', '|OVER') in mult_map:
        return float(mult_map[key.replace('|UNDER', '|OVER')])
    if '|OVER' in key and key.replace('|OVER', '|UNDER') in mult_map:
        return float(mult_map[key.replace('|OVER', '|UNDER')])
    stat = key.split('|')[0]
    if stat in mult_map:
        return float(mult_map[stat])
    return 1.0


def _candidate_mask(df: pd.DataFrame, candidate_name: str) -> pd.Series:
    role_outs = pd.to_numeric(df.get('role_ctx_outs_used', pd.Series(0, index=df.index)), errors='coerce').fillna(0)
    role_off = role_outs <= 0
    lowered = candidate_name.lower()
    if 'role_off' in lowered or 'role-off' in lowered or ('role' in lowered and 'off' in lowered):
        return role_off
    if 'role_on' in lowered or 'role-on' in lowered or ('role' in lowered and 'on' in lowered):
        return ~role_off
    return pd.Series(True, index=df.index)


def main():
    args = parse_args()
    latest = _find_latest_audit(args.audit_dir)
    if latest is None:
        print('No audits found under .atlas_audit or outputtelem/diagnostics/telemetry_corpus')
        return

    cand_file = latest / 'candidate_scores.json'
    if not cand_file.exists():
        print('candidate_scores.json not found in', latest)
        return
    cand = json.loads(cand_file.read_text(encoding='utf-8'))

    candidate = _select_candidate(cand.get('calibration_candidates', []), args.candidate)
    if candidate is None:
        print('No mult_map found in', cand_file)
        return
    mult_map = candidate.get('meta', {}).get('mult_map', {})
    cand_name_used = candidate.get('candidate', '') or candidate.get('name', '')

    base_dir = _pick_base_dir(args.base_dir, cand)
    if base_dir is None:
        print('Could not infer a corpus directory from audit labels; pass --base-dir explicitly.')
        return

    try:
        df, data_source, join_keys_used = _load_dataframe(base_dir)
    except FileNotFoundError as exc:
        print(str(exc))
        return

    df = df.copy()
    df['telemetry_cal_key'] = df.get('telemetry_cal_key', df.get('prop_key', pd.Series('', index=df.index))).astype(str)
    df['telemetry_mult'] = pd.to_numeric(df.get('telemetry_mult', pd.Series(1.0, index=df.index)), errors='coerce').fillna(1.0)
    df['p_cal'] = pd.to_numeric(df.get('p_cal', pd.Series(index=df.index, dtype=float)), errors='coerce')
    df['p_adj'] = pd.to_numeric(df.get('p_adj', pd.Series(index=df.index, dtype=float)), errors='coerce')
    df['p_for_cal'] = pd.to_numeric(df.get('p_for_cal', pd.Series(index=df.index, dtype=float)), errors='coerce')
    df['hit'] = pd.to_numeric(df.get('hit', pd.Series(index=df.index)), errors='coerce')
    df['candidate_mask'] = _candidate_mask(df, cand_name_used)
    df['direction_u'] = df.get('direction', pd.Series('', index=df.index)).astype(str).str.upper().str.strip() == 'UNDER'

    slice_df = df[df['direction_u']].copy()
    total_rows = len(slice_df)
    if total_rows == 0:
        print('No rows in direction_under slice')
        return

    rows = []
    for key, sub in slice_df.groupby('telemetry_cal_key'):
        new_mult = _lookup_mult(mult_map, key)
        existing_mult = sub['telemetry_mult'].replace(0.0, 1.0).fillna(1.0)

        p_base = sub['p_cal'].fillna(sub['p_adj']).fillna(sub['p_for_cal'])
        p_cand = p_base.copy()
        p_candidate_raw = sub['p_for_cal'].fillna(sub['p_adj'])
        fallback_ratio = p_base * (float(new_mult) / existing_mult)
        p_cand.loc[sub['candidate_mask']] = p_candidate_raw.loc[sub['candidate_mask']].fillna(fallback_ratio.loc[sub['candidate_mask']])
        p_cand = p_cand.clip(0.0, 1.0)

        base_brier = brier(p_base, sub['hit'])
        cand_brier = brier(p_cand, sub['hit'])
        delta = base_brier - cand_brier
        rows.append((key, int(len(sub)), delta, base_brier, cand_brier))

    out = sorted(rows, key=lambda x: x[2])  # most negative first (harmful)
    print(f'Audit: {latest}')
    print(f'Data root: {base_dir}')
    print(f'Data source: {data_source}')
    if join_keys_used:
        print(f'Join keys used: {", ".join(join_keys_used)}')
    print('direction_under per-key delta (harmful first):')
    print('key,count,delta_brier,base_brier,cand_brier')
    print(f'Using candidate: {cand_name_used}')
    for key, cnt, delta, b0, b1 in out[:args.top]:
        def fmt(x):
            return f'{x:.6e}' if (x is not None and not (isinstance(x, float) and math.isnan(x))) else 'nan'
        print(f'{key},{cnt},{fmt(delta)},{fmt(b0)},{fmt(b1)}')


if __name__ == '__main__':
    main()
