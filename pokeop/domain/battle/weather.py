from __future__ import annotations

from enum import Enum


class Weather(str, Enum):
    """Battle weather states that can affect direct damage calculation."""

    HARSH_SUNLIGHT = "harsh_sunlight"
    RAIN = "rain"
    SANDSTORM = "sandstorm"
    HAIL = "hail"
    SNOW = "snow"


__all__ = ["Weather"]
