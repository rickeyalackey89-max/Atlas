"""Compatibility wrapper for MLB slip family builders.

New code should import from `mlb.runtime.slip_builders`. This module keeps older
imports stable while the slip writer is being split into family modules.
"""

from __future__ import annotations

from mlb.runtime.slip_builders import (
    FAMILY_BUILDER_POLICIES,
    FamilyBuilderPolicy,
    family_policy,
    family_policy_manifest,
    policy_to_manifest,
)

__all__ = [
    "FAMILY_BUILDER_POLICIES",
    "FamilyBuilderPolicy",
    "family_policy",
    "family_policy_manifest",
    "policy_to_manifest",
]
