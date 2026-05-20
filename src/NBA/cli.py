"""NBA CLI alias.

The production NBA engine still imports its internal code from ``Atlas.*``.
This module gives operators an unambiguous command:

    py -m NBA.cli live

The legacy ``py -m Atlas.cli ...`` command remains available while scheduled
tasks and docs move over.
"""

from Atlas.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

