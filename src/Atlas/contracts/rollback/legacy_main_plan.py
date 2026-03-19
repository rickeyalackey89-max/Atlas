"""Legacy rollback plan (RETIRED).

The legacy rollback entrypoint has been removed from the active runtime.
"""

def build_legacy_main_plan(*args, **kwargs):
    raise RuntimeError("Atlas Legacy has been retired. No legacy rollback plan exists in the active runtime.")
