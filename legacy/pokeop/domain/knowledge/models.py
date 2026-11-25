from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class BaseStats:
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value < 0:
                raise ValueError(f"{field.name} must not be negative")


@dataclass(frozen=True)
class PokemonKnowledge:
    identifier: str
    display_name: str | None
    types: tuple[str, ...]
    base_stats: BaseStats

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("identifier must not be empty")
        if not self.types:
            raise ValueError("types must not be empty")


@dataclass(frozen=True)
class MoveKnowledge:
    identifier: str
    display_name: str | None
    type: str
    damage_class: str
    power: int | None
    accuracy: int | None
    priority: int

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("identifier must not be empty")
        if not self.type:
            raise ValueError("type must not be empty")
        if not self.damage_class:
            raise ValueError("damage_class must not be empty")
        if self.power is not None and self.power < 0:
            raise ValueError("power must not be negative")
        if self.accuracy is not None and self.accuracy < 0:
            raise ValueError("accuracy must not be negative")


__all__ = ["BaseStats", "MoveKnowledge", "PokemonKnowledge"]
