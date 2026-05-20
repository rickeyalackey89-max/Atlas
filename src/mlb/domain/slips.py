"""Slip family definitions for MLB dashboard compatibility."""

SLIP_FAMILIES = (
    "System",
    "Windfall",
    "DemonHunter",
    "Marketed",
)


def supported_slip_families() -> tuple[str, ...]:
    return SLIP_FAMILIES
