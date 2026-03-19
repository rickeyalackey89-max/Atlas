"""Legacy adapter (RETIRED).

This module previously bridged NewEngine to Atlas Legacy.
Legacy has been archived as a relic and retired from the active runtime.

If you need legacy behavior, use the relic zip stored externally.
"""

def score_board(*args, **kwargs):
    raise RuntimeError("Atlas Legacy has been retired. score_board is no longer available in the active runtime.")
