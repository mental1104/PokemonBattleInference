from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SideConditions:
    """Minimal side-condition snapshot for direct damage calculation."""

    reflect: bool = False
    light_screen: bool = False
    aurora_veil: bool = False


__all__ = ["SideConditions"]
