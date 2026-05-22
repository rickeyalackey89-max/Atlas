"""MLB slip family builder registry."""

from __future__ import annotations

from .contracts import FamilyBuilderPolicy, policy_to_manifest
from .demonhunter import POLICY as DEMONHUNTER_POLICY
from .marketed import POLICY as MARKETED_POLICY
from .system import POLICY as SYSTEM_POLICY
from .windfall import POLICY as WINDFALL_POLICY

FAMILY_BUILDER_POLICIES: dict[str, FamilyBuilderPolicy] = {
    "Marketed": MARKETED_POLICY,
    "System": SYSTEM_POLICY,
    "Windfall": WINDFALL_POLICY,
    "DemonHunter": DEMONHUNTER_POLICY,
}


def family_policy(family: str) -> FamilyBuilderPolicy:
    return FAMILY_BUILDER_POLICIES.get(family, MARKETED_POLICY)


def family_policy_manifest() -> dict[str, dict[str, object]]:
    return {family: policy_to_manifest(policy) for family, policy in FAMILY_BUILDER_POLICIES.items()}


__all__ = [
    "FamilyBuilderPolicy",
    "FAMILY_BUILDER_POLICIES",
    "family_policy",
    "family_policy_manifest",
    "policy_to_manifest",
]
