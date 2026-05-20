# Atlas MLB Module Map

`cli.py` is the command surface. Implementation should live in focused packages:

- `contracts/` - typed payload and source contracts
- `domain/` - market taxonomy, scoring helpers, slip family definitions
- `evaluation/` - deterministic checks, operator reports, OpenAI review
- `fetchers/` - external API fetchers
- `matchups/` - lineup, starter, bullpen, environment, and hitter context matrix contracts
- `modeling/` - probability kernels, scoring engine boundary, future trained model layers
- `normalizers/` - source payload to staged contract conversion
- `runtime/` - paths, pipeline stages, preflight, source operations, engine inputs
- `runtime/pipeline_execution.py` - executable internal board pipeline.
- `sources/` - source catalog constants and raw snapshot IO

Keep new code out of the package root unless it is part of the CLI surface.
