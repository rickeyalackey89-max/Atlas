from dataclasses import dataclass
from typing import Dict, Tuple

@dataclass(frozen=True)
class PayoutTable:
    # (hits, legs) -> multiplier
    multipliers: Dict[Tuple[int, int], float]


# Power Play multipliers
POWER_MULT = {
    2: 3.0,
    3: 6.0,
    4: 10.0,
    5: 20.0,
    6: 37.5,
}

# Flex Play payout tables
FLEX_2 = PayoutTable({
    (2, 2): 3.0,
})

FLEX_3 = PayoutTable({
    (3, 3): 3.0,
    (2, 3): 1.0,
})

FLEX_4 = PayoutTable({
    (4, 4): 6.0,
    (3, 4): 1.5,
})

FLEX_5 = PayoutTable({
    (5, 5): 10.0,
    (4, 5): 2.0,
    (3, 5): 0.4,
})

FLEX_6 = PayoutTable({
    (6, 6): 25.0,
    (5, 6): 2.0,
    (4, 6): 0.4,
})
