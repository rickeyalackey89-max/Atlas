# Atlas Tests

`tests/` is the canonical pytest suite for Atlas and should stay separate from `scripts/`.

## Keep Here

- deterministic unit tests
- regression tests
- contract tests
- runtime behavior tests that should run under pytest

## Do Not Put Here

- one-off diagnostics
- smoke scripts intended to be run manually
- ad-hoc model audits
- exploratory notebooks or sweeps
- generated reports

Those belong under `scripts/diagnostics/`, `scripts/validation/`, `scripts/audits/`, or `scripts/experiments/`.

## Why This Folder Stays Separate

Python tooling, pytest discovery, CI, and Codex code review all expect tests to be easy to find at repo root. Moving tests into `scripts/` would blur the line between automated regression coverage and one-off operational utilities.
