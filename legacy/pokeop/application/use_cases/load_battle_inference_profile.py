"""加载 version-aware Pokémon 推演资料的 application 用例。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.repositories.battle_inference import (
    BattleInferenceItemProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRepository,
    BattleInferenceRulesetContext,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


class BattleInferenceProfileNotFound(LookupError):
    """表示指定规则轴或 Pokémon 没有可供推演使用的完整读取资料。"""


@dataclass(frozen=True, slots=True)
class LoadBattleInferenceProfileCommand:
    """请求 application 加载一只 Pokémon 的完整推演读取资料。

    Args:
        rules: 已通过 domain 校验的 1v1 推演规则，提供 ruleset/version group 主轴。
        pokemon_id: 需要加载的 Pokémon 稳定整数 ID，必须大于 0。
    """

    rules: BattleInferenceRules
    pokemon_id: int

    def __post_init__(self) -> None:
        """校验命令只携带明确规则对象和正整数 Pokémon ID。

        Raises:
            ValueError: rules 类型错误或 pokemon_id 不是正整数时抛出。
        """
        if not isinstance(self.rules, BattleInferenceRules):
            raise ValueError("rules must be a BattleInferenceRules instance")
        if isinstance(self.pokemon_id, bool) or self.pokemon_id <= 0:
            raise ValueError("pokemon_id must be greater than 0")


@dataclass(frozen=True, slots=True)
class LoadBattleInferenceProfileResult:
    """返回配置生成器和 domain factory 后续消费的稳定读取结果。

    Args:
        ruleset: 与命令完全匹配的 ruleset/version group 上下文。
        pokemon: 已还原历史属性、历史特性和合法招式的完整 Pokémon profile。
        item_candidates: 当前规则轴可枚举的受控道具候选，包含不携带道具。
    """

    ruleset: BattleInferenceRulesetContext
    pokemon: BattleInferencePokemonProfile
    item_candidates: tuple[BattleInferenceItemProfile, ...]


class LoadBattleInferenceProfileUseCase:
    """编排一只 Pokémon 的 version-aware 推演资料读取。

    该用例不操作 SQLAlchemy session，也不创建 domain effect。它只验证 repository 返回的
    规则轴与命令一致，并把显式 projection 交给后续配置生成器或 domain factory。
    """

    def __init__(self, repository: BattleInferenceRepository) -> None:
        """保存可由 PostgreSQL 实现或测试 fake 替换的 repository 端口。

        Args:
            repository: 提供规则上下文、完整 Pokémon profile 和受控道具候选的读取端口。
        """
        self._repository = repository

    def execute(
        self,
        command: LoadBattleInferenceProfileCommand,
    ) -> LoadBattleInferenceProfileResult:
        """按命令中的完整规则轴加载并组装推演读取结果。

        Args:
            command: 已校验的规则对象和 Pokémon ID。

        Returns:
            可供配置枚举与 domain factory 继续消费的稳定读取结果。

        Raises:
            BattleInferenceProfileNotFound: 规则轴、Pokémon profile 或受控道具边界不存在时抛出。
        """
        ruleset = self._repository.get_ruleset_context(
            ruleset_id=command.rules.ruleset_id,
            version_group_id=command.rules.version_group_id,
        )
        if ruleset is None:
            # 精确规则轴不存在时不得退化为只按 generation 猜测，以免混入其他版本招式。
            raise BattleInferenceProfileNotFound(
                "battle inference ruleset context was not found"
            )

        pokemon = self._repository.get_pokemon_profile(
            ruleset_id=command.rules.ruleset_id,
            version_group_id=command.rules.version_group_id,
            pokemon_id=command.pokemon_id,
        )
        if pokemon is None:
            raise BattleInferenceProfileNotFound(
                f"pokemon profile {command.pokemon_id} was not found"
            )

        item_candidates = self._repository.list_item_candidates(
            ruleset_id=command.rules.ruleset_id,
            version_group_id=command.rules.version_group_id,
        )
        if not item_candidates:
            # 空集合说明规则轴无法解释，而不是“当前只有无道具”；后者必须返回显式 none 候选。
            raise BattleInferenceProfileNotFound(
                "battle inference item candidate boundary was not found"
            )

        return LoadBattleInferenceProfileResult(
            ruleset=ruleset,
            pokemon=pokemon,
            item_candidates=item_candidates,
        )


__all__ = [
    "BattleInferenceProfileNotFound",
    "LoadBattleInferenceProfileCommand",
    "LoadBattleInferenceProfileResult",
    "LoadBattleInferenceProfileUseCase",
]
