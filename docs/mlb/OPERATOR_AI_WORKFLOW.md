# Atlas MLB Operator AI Workflow

Status: integrated skeleton  
Last updated: 2026-05-11

## Purpose

The operator AI layer reviews Atlas MLB run outputs before dashboard publishing.
It is a publish gate, not a model component.

The AI evaluator may:

- summarize run health
- identify anomalies
- produce operator notes
- recommend next actions
- block publish when risk is high

The AI evaluator must not:

- change model probabilities
- rewrite picks
- modify slip selection
- override deterministic hard-stop checks

## Runtime Flow

```text
PrizePicks data
  -> normalization
  -> feature/share matrix
  -> model scoring
  -> slip families
  -> deterministic anomaly checks
  -> OpenAI operator evaluator
  -> operator report
  -> publish decision
  -> dashboard publish if allowed
```

## Files

Code:

- `src/mlb/evaluation/anomaly_checks.py`
- `src/mlb/evaluation/openai_evaluator.py`
- `src/mlb/evaluation/operator_report.py`
- `src/mlb/evaluation/publish_decision.py`
- `src/mlb/evaluation/schemas.py`
- `src/mlb/evaluation/workflow.py`

Artifacts:

```text
data/mlb/<test_runs|live_runs>/<run_id>/operator/
  ai_evaluation.json
  anomalies.jsonl
  operator_report.md
  publish_decision.json
```

## Setup

Install the optional AI dependency:

```powershell
uv sync --extra ai
```

Set credentials:

```powershell
$env:OPENAI_API_KEY="..."
$env:ATLAS_OPENAI_EVALUATOR_ENABLED="1"
$env:ATLAS_OPENAI_EVALUATOR_MODEL="gpt-5.4-mini"
```

Local helper:

```powershell
.\scripts\setup_openai_evaluator.ps1
```

The helper reads `OpenAI.txt`, sets the environment variables for the current
PowerShell session, and does not print the key.

Secret handling:

- `OpenAI.txt` is ignored by git.
- Do not commit API keys, `.env` files, or `.secrets/` files.
- Rotate the key if it is ever pasted into a tracked file, terminal transcript,
  issue, PR, or chat.

Default behavior without credentials:

- deterministic anomaly checks still run
- OpenAI evaluation is skipped safely
- publish remains gated by local checks

## Commands

Inspect the operator workflow:

```powershell
uv run atlas-mlb operator
uv run atlas-mlb operator --json
```

Run surfaces that include operator evaluation stages:

```powershell
uv run atlas-mlb live
uv run atlas-mlb replay single
uv run atlas-mlb replay bundle
```

## Deterministic Checks

Local checks run before OpenAI:

- empty PrizePicks board
- empty scored output
- low scored-candidate coverage
- unsupported markets
- missing pitcher context
- invalid probabilities
- missing slip output
- explicit hard failures

Hard-stop findings block publish and cannot be overridden by AI.

## OpenAI Evaluation

The OpenAI evaluator receives a compact review packet:

- run id
- run mode
- run summary
- deterministic anomalies
- operator instructions

It returns schema-valid JSON using the publish-decision schema.

Required response fields:

- `publish_allowed`
- `severity`
- `summary`
- `anomalies`
- `operator_notes`
- `recommended_next_actions`

## Publish Rule

Dashboard publish requires:

- deterministic checks do not produce hard stops
- OpenAI/operator decision allows publish when enabled
- dashboard payload validation passes
- publishing guardrails are enabled for the target environment

Replay paths do not publish by default.
