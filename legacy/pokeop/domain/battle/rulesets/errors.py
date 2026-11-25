from __future__ import annotations


class UnknownGenerationError(ValueError):
    """Raised when no domain ruleset profile exists for a generation."""

    def __init__(self, generation_id: int) -> None:
        super().__init__(f"Unknown generation_id: {generation_id}")
        self.generation_id = generation_id


class UnknownVersionGroupError(ValueError):
    """Raised when no domain ruleset profile exists for a version group."""

    def __init__(self, version_group_id: int) -> None:
        super().__init__(f"Unknown version_group_id: {version_group_id}")
        self.version_group_id = version_group_id


__all__ = ["UnknownGenerationError", "UnknownVersionGroupError"]
