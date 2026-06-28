from __future__ import annotations

from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import CombatantStatus


def clear_status_on_switch_out(status: CombatantStatus) -> CombatantStatus:
    """Clear switch-out volatile statuses while preserving major statuses."""
    return status.clear_volatile_status(
        VolatileStatusKind.CONFUSION
    ).clear_volatile_status(VolatileStatusKind.INFATUATION)


__all__ = ["clear_status_on_switch_out"]
