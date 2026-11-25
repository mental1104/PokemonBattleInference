from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ruleset:
    identifier: str
    generation: int
    version_group: str | None

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("identifier must not be empty")
        if self.generation < 1:
            raise ValueError("generation must be greater than 0")


__all__ = ["Ruleset"]
