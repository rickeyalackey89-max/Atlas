#!/usr/bin/env python3
"""
scripts/validation/validate_artifacts.py

Phase 8 - Artifact Validator (dead-period / guardrail aware)

Matches orchestrator.py semantics:
- no_slate => expected clean stop, may emit no artifact_fingerprint, should PASS (skip)
- guardrail => expected clean stop, may emit no artifact_fingerprint, should PASS (skip)
- smoke_test-only runs may emit only {"event":"smoke_test"} and nothing else => should PASS (skip)

This validator:
1) Loads events JSONL for run_id
2) Determines "run mode" from events:
   - run_end.status if present
   - else presence of known expected-stop events (no_slate_detected / guardrail_stop_detected / smoke_test)
3) If expected stop => PASS (skip artifact enforcement) exit 0
4) If normal run => enforce contract against artifact_fingerprint events

Fingerprint schema (from orchestrator.py):
  event_type/event == "artifact_fingerprint"
  label: str           (artifact identifier; contract keys must match label)
  path: str
  exists: bool
  sha256: str|None
  csv_rows: int|None
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ----------------------------
# YAML loading (PyYAML required)
# ----------------------------
def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Missing dependency: PyYAML. Install with `pip install pyyaml`.\n"
            f"Original error: {e}"
        )
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {path}")
    return data


def try_import_pandas():
    try:
        import pandas as pd  # type: ignore
        return pd
    except Exception:
        return None


@dataclass
class Violation:
    artifact: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.artifact}] {self.code}: {self.message}"


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def get_event_name(evt: Dict[str, Any]) -> Optional[str]:
    """
    Your logs sometimes use "event" (e.g. smoke_test),
    and orchestrator uses emit_event(ctx, "artifact_fingerprint", ...) which may serialize to:
      - event_type
      - event
      - type
      - name
    """
    for k in ("event_type", "event", "type", "name"):
        v = evt.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# ----------------------------
# Paths
# ----------------------------
def locate_events_files(run_id: str, explicit: Optional[str]) -> List[Path]:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"--events path not found: {p}")
        return [p]

    audit_dir = Path(".atlas_audit")
    if not (audit_dir.exists() and audit_dir.is_dir()):
        raise FileNotFoundError("Missing .atlas_audit directory. Provide --events explicitly.")

    preferred = [
        audit_dir / f"events_{run_id}.jsonl",
        audit_dir / f"events_py_{run_id}.jsonl",
        audit_dir / f"events_orchestrator_{run_id}.jsonl",
        audit_dir / f"events_{run_id}_orchestrator.jsonl",
        audit_dir / f"events_{run_id}_runtime.jsonl",
        audit_dir / f"events_ps_{run_id}.jsonl",
    ]

    found = [p.resolve() for p in preferred if p.exists()]
    if not found:
        found = [p.resolve() for p in sorted(audit_dir.glob(f"*{run_id}*.jsonl"))]

    if not found:
        raise FileNotFoundError(
            f"Could not locate any events JSONL for run_id={run_id} in .atlas_audit. "
            "Provide --events explicitly."
        )

    # de-dup preserving order
    seen = set()
    uniq: List[Path] = []
    for p in found:
        sp = str(p)
        if sp not in seen:
            uniq.append(p)
            seen.add(sp)
    return uniq


def locate_contract(explicit: Optional[str]) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"--contract path not found: {p}")
        return p
    p = Path("src/Atlas/contracts/artifact_contract.yaml").resolve()
    if not p.exists():
        raise FileNotFoundError(f"Default contract not found at {p}. Provide --contract explicitly.")
    return p


# ----------------------------
# Contract helpers
# ----------------------------
def normalize_dtype(dt: Optional[str]) -> Optional[str]:
    if dt is None:
        return None
    s = str(dt).strip().lower()
    if s in ("int64", "int32", "int16", "int8", "int", "integer"):
        return "int64"
    if s in ("float64", "float32", "float16", "float", "double"):
        return "float64"
    if s in ("bool", "boolean"):
        return "bool"
    if s in ("object", "str", "string", "unicode"):
        return "string"
    if s in ("datetime64[ns]", "datetime", "timestamp"):
        return "datetime64[ns]"
    if s.startswith("int"):
        return "int64"
    if s.startswith("float"):
        return "float64"
    return s


# ----------------------------
# Run classification
# ----------------------------
EXPECTED_STOP_EVENTS = {
    "no_slate_detected",
    "guardrail_stop_detected",
    "smoke_test",
}

EXPECTED_STOP_STATUSES = {"no_slate", "guardrail"}


def extract_run_signals(events_files: List[Path], run_id: str) -> Dict[str, Any]:
    """
    Returns a dict with:
      - run_end_status (str|None)
      - saw_expected_stop_event (bool)
      - expected_stop_event_names (list[str])
      - total_events (int)
    """
    status: Optional[str] = None
    expected_seen: List[str] = []
    total = 0

    for f in events_files:
        for evt in read_jsonl(f):
            evt_run = evt.get("run_id")
            if evt_run is not None and str(evt_run) != str(run_id):
                continue
            total += 1
            name = get_event_name(evt)

            if name == "run_end":
                st = evt.get("status")
                if isinstance(st, str) and st.strip():
                    status = st.strip()

            if name in EXPECTED_STOP_EVENTS:
                expected_seen.append(name)

    return {
        "run_end_status": status,
        "saw_expected_stop_event": len(expected_seen) > 0,
        "expected_stop_event_names": sorted(list(set(expected_seen))),
        "total_events": total,
    }


# ----------------------------
# Fingerprint extraction (matches orchestrator.py)
# ----------------------------
def extract_artifact_fingerprints(events_files: List[Path], run_id: str) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    latest_by_label: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []

    total = 0
    for f in events_files:
        for evt in read_jsonl(f):
            evt_run = evt.get("run_id")
            if evt_run is not None and str(evt_run) != str(run_id):
                continue

            if get_event_name(evt) != "artifact_fingerprint":
                continue

            label = evt.get("label")
            if not isinstance(label, str) or not label.strip():
                continue

            latest_by_label[label.strip()] = evt
            total += 1

    notes.append(f"artifact_fingerprint events found: {total} (unique_labels={len(latest_by_label)})")

    # Fallback: replay/sandbox runs may write scored legs under data/output/runs/<engine_run_id>/...
    # The calibration_applied event records the true file paths in patched[].
    patched = extract_calibration_patched_paths(events_files, run_id)
    if patched:
        # only override if current fingerprints indicate missing
        for label, idx in [("scored_legs.csv", 0), ("scored_legs_deduped.csv", 1)]:
            fp = latest_by_label.get(label)
            if fp is None:
                continue
            if fp.get("exists") is True:
                continue
            if idx >= len(patched):
                continue
            p = patched[idx]
            try:
                exists = Path(p).exists()
            except Exception:
                exists = False
            fp2 = dict(fp)
            fp2["path"] = p
            fp2["exists"] = True if exists else False
            # clear stale hash/rows if they exist; validator will re-read from fp2["path"] if schema checks require it
            fp2.pop("sha256", None)
            fp2.pop("csv_rows", None)
            latest_by_label[label] = fp2
        notes.append(f"calibration_applied patched[] fallback applied for scored legs (n={len(patched)})")

    return latest_by_label, notes




def extract_calibration_patched_paths(events_files: List[Path], run_id: str) -> List[str]:
    """
    Returns patched[] paths from the single calibration_applied event for this run_id, if present.
    Used as a fallback for locating scored_legs artifacts in replay/sandbox runs where root paths may not exist.
    """
    for f in events_files:
        for evt in read_jsonl(f):
            evt_run = evt.get("run_id")
            if evt_run is not None and str(evt_run) != str(run_id):
                continue
            if get_event_name(evt) != "calibration_applied":
                continue
            patched = evt.get("patched")
            if isinstance(patched, list) and all(isinstance(x, str) for x in patched):
                return [x for x in patched if x.strip()]
    return []


# ----------------------------
# Schema reading (best-effort, only if contract specifies schema)
# ----------------------------
def read_dataframe_best_effort(path: Path, pd):
    if pd is None:
        return None
    if not path.exists() or not path.is_file():
        return None

    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            return pd.read_csv(path)
        if ext == ".tsv":
            return pd.read_csv(path, sep="\t")
        if ext in (".parquet", ".pq"):
            return pd.read_parquet(path)
        if ext == ".jsonl":
            return pd.read_json(path, lines=True)
        if ext == ".json":
            return pd.read_json(path)
    except Exception:
        return None
    return None


def dtype_from_series(series) -> str:
    dt = str(series.dtype)
    return normalize_dtype(dt) or dt


# ----------------------------
# Validation core
# ----------------------------
def validate_run(contract: Dict[str, Any], fingerprints: Dict[str, Dict[str, Any]], pd) -> List[Violation]:
    vios: List[Violation] = []

    global_cfg = contract.get("global", {}) if isinstance(contract.get("global"), dict) else {}
    enforce_hash_global = bool(global_cfg.get("enforce_hash", False))
    allow_extra_columns = bool(global_cfg.get("allow_extra_columns", False))
    require_schema_match = bool(global_cfg.get("require_schema_match", True))

    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, dict):
        return [Violation("_contract", "contract_structure", "Missing/invalid 'artifacts' section")]

    for artifact_key, spec in artifacts.items():
        if not isinstance(artifact_key, str) or not isinstance(spec, dict):
            continue

        required = bool(spec.get("required", False))
        min_rows = spec.get("min_rows", None)
        max_rows = spec.get("max_rows", None)
        schema = spec.get("schema", None)
        hash_enforced = bool(spec.get("hash_enforced", False))
        expected_hash = spec.get("expected_hash", None)

        fp = fingerprints.get(artifact_key)

        if fp is None:
            if required:
                vios.append(Violation(artifact_key, "missing_artifact", "Required artifact missing fingerprint event (label)"))
            continue

        exists = fp.get("exists")
        if exists is not True:
            vios.append(Violation(artifact_key, "missing_file", "Fingerprint indicates artifact does not exist"))
            continue

        rows = fp.get("csv_rows")
        rows_int: Optional[int]
        try:
            rows_int = int(rows) if rows is not None else None
        except Exception:
            rows_int = None

        if min_rows is not None and rows_int is not None:
            try:
                if rows_int < int(min_rows):
                    vios.append(Violation(artifact_key, "min_rows", f"csv_rows={rows_int} < min_rows={min_rows}"))
            except Exception:
                pass

        if max_rows is not None and rows_int is not None:
            try:
                if rows_int > int(max_rows):
                    vios.append(Violation(artifact_key, "max_rows", f"csv_rows={rows_int} > max_rows={max_rows}"))
            except Exception:
                pass

        enforce_hash = enforce_hash_global or hash_enforced
        if enforce_hash:
            fp_hash = fp.get("sha256")
            if expected_hash is None:
                vios.append(Violation(artifact_key, "hash_enforcement_config", "Hash enforcement enabled but contract missing expected_hash"))
            else:
                if not fp_hash:
                    vios.append(Violation(artifact_key, "hash_missing", "Fingerprint missing sha256"))
                elif str(fp_hash) != str(expected_hash):
                    vios.append(Violation(artifact_key, "hash_mismatch", f"sha256={fp_hash} != expected_hash={expected_hash}"))

        if isinstance(schema, dict) and schema:
            artifact_path = fp.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                vios.append(Violation(artifact_key, "schema_no_path", "Contract requires schema validation but fingerprint missing path"))
                continue

            df = read_dataframe_best_effort(Path(artifact_path), pd)
            if df is None:
                vios.append(Violation(artifact_key, "schema_unreadable", "Contract requires schema validation but artifact could not be read (need pandas + supported format)"))
                continue

            df_cols = [str(c) for c in list(df.columns)]
            contract_cols = list(schema.keys())

            if require_schema_match:
                missing = [c for c in contract_cols if c not in df_cols]
                if missing:
                    vios.append(Violation(artifact_key, "missing_columns", f"Missing columns: {missing}"))

                if not allow_extra_columns:
                    extra = [c for c in df_cols if c not in contract_cols]
                    if extra:
                        vios.append(Violation(artifact_key, "extra_columns", f"Extra columns present: {extra}"))

            for col, colspec in schema.items():
                if not isinstance(col, str) or not isinstance(colspec, dict):
                    continue
                if col not in df.columns:
                    continue

                expected_dtype = normalize_dtype(colspec.get("dtype"))
                if expected_dtype:
                    actual_dtype = dtype_from_series(df[col])
                    if normalize_dtype(actual_dtype) != expected_dtype:
                        vios.append(Violation(artifact_key, "dtype_mismatch", f"Column '{col}' dtype={actual_dtype} != expected={expected_dtype}"))

                nullable = bool(colspec.get("nullable", True))
                if not nullable:
                    nulls = int(df[col].isna().sum())
                    if nulls > 0:
                        vios.append(Violation(artifact_key, "nullability", f"Column '{col}' is non-nullable but has null_count={nulls}"))

    return vios


# ----------------------------
# CLI
# ----------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate_artifacts.py",
        description="Validate run artifacts against artifact_contract.yaml using orchestrator events (dead-period aware).",
    )
    p.add_argument("--run-id", required=True, help="Run identifier matching events_<runid>.jsonl")
    p.add_argument("--events", default=None, help="Explicit path to events JSONL (optional).")
    p.add_argument("--contract", default=None, help="Path to artifact_contract.yaml (optional).")
    p.add_argument("--json", action="store_true", help="Emit JSON output in addition to human output.")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    run_id = str(args.run_id)
    events_files = locate_events_files(run_id, args.events)
    contract_path = locate_contract(args.contract)

    contract = load_yaml(contract_path)
    pd = try_import_pandas()

    signals = extract_run_signals(events_files, run_id)
    status = signals.get("run_end_status")
    saw_expected_event = bool(signals.get("saw_expected_stop_event"))
    expected_events = signals.get("expected_stop_event_names") or []
    total_events = int(signals.get("total_events") or 0)

    # Expected clean stops: PASS, skip artifact enforcement
    if (isinstance(status, str) and status in EXPECTED_STOP_STATUSES) or saw_expected_event:
        print("PASS")
        print(f"run_id={run_id}")
        print(f"events={';'.join(str(p) for p in events_files)}")
        print(f"contract={contract_path}")

        if isinstance(status, str) and status in EXPECTED_STOP_STATUSES:
            print(f"NOTE: run_end.status={status} => expected stop; artifact validation skipped.")
        else:
            # smoke_test-only or explicit expected-stop event without run_end
            print(
                "NOTE: expected-stop event(s) present "
                f"{expected_events} with no enforceable artifacts (dead period/downmode); validation skipped."
            )
        if total_events <= 2:
            print(f"NOTE: total_events={total_events} (minimal event stream)")

        if args.json:
            payload = {
                "result": "PASS",
                "run_id": run_id,
                "events": [str(p) for p in events_files],
                "contract": str(contract_path),
                "run_end_status": status,
                "expected_stop_events": expected_events,
                "total_events": total_events,
                "violations": [],
            }
            print(json.dumps(payload, indent=2))
        return 0

    # Normal run: enforce artifacts
    fingerprints, fp_notes = extract_artifact_fingerprints(events_files, run_id)
    vios = validate_run(contract, fingerprints, pd)

    # If run_end explicitly fail, mark failure regardless of contract
    if status == "fail":
        vios.append(Violation("_run", "run_failed", "run_end.status=fail"))

    ok = len(vios) == 0
    events_joined = ";".join(str(p) for p in events_files)

    if ok:
        print("PASS")
        print(f"run_id={run_id}")
        print(f"events={events_joined}")
        print(f"contract={contract_path}")
        if status:
            print(f"NOTE: run_end.status={status}")
        for n in fp_notes:
            print(f"NOTE: {n}")
    else:
        print("FAIL")
        print(f"run_id={run_id}")
        print(f"events={events_joined}")
        print(f"contract={contract_path}")
        if status:
            print(f"NOTE: run_end.status={status}")
        for n in fp_notes:
            print(f"NOTE: {n}")
        print("Violations:")
        for v in vios:
            print(f" - {v}")

    if args.json:
        payload = {
            "result": "PASS" if ok else "FAIL",
            "run_id": run_id,
            "events": [str(p) for p in events_files],
            "contract": str(contract_path),
            "run_end_status": status,
            "expected_stop_events": expected_events,
            "total_events": total_events,
            "fingerprint_labels": sorted(list(fingerprints.keys())),
            "violations": [{"artifact": v.artifact, "code": v.code, "message": v.message} for v in vios],
        }
        print(json.dumps(payload, indent=2))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())