"""兼容导出标准配置维度 provider 与通用扩展协议。"""

from pokeop.application.configuration_space.effect_providers import (
    AbilityDimensionProvider,
    ItemDimensionProvider,
)
from pokeop.application.configuration_space.move_provider import MoveSetDimensionProvider
from pokeop.application.configuration_space.provider_core import (
    ConfigurationDimensionProvider,
    ConfigurationDimensionValue,
    ConfigurationGenerationContext,
    DimensionExpansion,
    OpaqueDimensionValue,
    PokemonConfigurationDraft,
)
from pokeop.application.configuration_space.stat_provider import StatDimensionProvider

DEFAULT_DIMENSION_PROVIDERS: tuple[ConfigurationDimensionProvider, ...] = (
    MoveSetDimensionProvider(),
    StatDimensionProvider(),
    AbilityDimensionProvider(),
    ItemDimensionProvider(),
)

__all__ = [
    "AbilityDimensionProvider",
    "ConfigurationDimensionProvider",
    "ConfigurationDimensionValue",
    "ConfigurationGenerationContext",
    "DEFAULT_DIMENSION_PROVIDERS",
    "DimensionExpansion",
    "ItemDimensionProvider",
    "MoveSetDimensionProvider",
    "OpaqueDimensionValue",
    "PokemonConfigurationDraft",
    "StatDimensionProvider",
]
