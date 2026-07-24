"""验证 application composition 只校正覆盖结论，不改写 version-aware 合法候选。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.repositories.battle_inference import (
    BattleInferenceAbilityProfile,
    BattleInferenceItemProfile,
    BattleInferenceMoveProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRulesetContext,
    BattleInferenceTypeProfile,
    MechanismCapability,
    MechanismSupportStatus,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def _capability(
    source_kind: EffectSourceKind,
    identifier: str,
    status: MechanismSupportStatus,
) -> MechanismCapability:
    """创建明确来源和保守状态的测试机制记录。"""
    return MechanismCapability(
        source_kind=source_kind,
        identifier=identifier,
        status=status,
        reason=f"repository marks {identifier} as {status.value}.",
    )


def _type() -> BattleInferenceTypeProfile:
    """创建测试招式与 Pokémon 共用的冰属性 projection。"""
    return BattleInferenceTypeProfile(
        type_id=15,
        identifier="ice",
        display_name="冰",
        domain_type=Type.ICE,
    )


def _profile() -> BattleInferencePokemonProfile:
    """创建同时包含已实现 partial 招式和透明中性特性的 profile。"""
    return BattleInferencePokemonProfile(
        pokemon_id=461,
        identifier="weavile",
        display_name="玛纽拉",
        species_id=461,
        species_identifier="weavile",
        form_identifier=None,
        is_default_form=True,
        is_battle_only_form=False,
        is_mega_form=False,
        types=(_type(),),
        base_stats=StatValues(70, 120, 65, 45, 85, 125),
        can_evolve=False,
        abilities=(
            BattleInferenceAbilityProfile(
                ability_id=46,
                identifier="pressure",
                display_name="压迫感",
                slot=1,
                is_hidden=False,
                effect_identifier="pressure",
                capability=_capability(
                    EffectSourceKind.ABILITY,
                    "pressure",
                    MechanismSupportStatus.UNSUPPORTED,
                ),
            ),
        ),
        moves=(
            BattleInferenceMoveProfile(
                move_id=8,
                identifier="ice-punch",
                display_name="冰冻拳",
                type=_type(),
                category=MoveCategory.PHYSICAL,
                power=75,
                pp=15,
                accuracy=100,
                priority=0,
                target_id=10,
                target_identifier="selected-pokemon",
                effect_id=2,
                effect_chance=10,
                effect_identifier="ice-punch",
                capability=_capability(
                    EffectSourceKind.MOVE,
                    "ice-punch",
                    MechanismSupportStatus.PARTIAL,
                ),
            ),
            BattleInferenceMoveProfile(
                move_id=216,
                identifier="return",
                display_name="报恩",
                type=_type(),
                category=MoveCategory.PHYSICAL,
                power=None,
                pp=20,
                accuracy=100,
                priority=0,
                target_id=10,
                target_identifier="selected-pokemon",
                effect_id=1,
                effect_chance=None,
                effect_identifier=None,
                capability=_capability(
                    EffectSourceKind.MOVE,
                    "return",
                    MechanismSupportStatus.UNSUPPORTED,
                ),
            ),
        ),
    )


@dataclass(slots=True)
class _Repository:
    """返回固定 profile 和无道具候选的底层 repository。"""

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """返回与输入一致的测试规则轴。"""
        return BattleInferenceRulesetContext(
            ruleset_id=ruleset_id,
            ruleset_name="Pokémon Champion",
            generation_id=8,
            version_group_id=version_group_id,
            version_group_identifier="sword-shield",
        )

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleInferencePokemonProfile | None:
        """忽略读取参数并返回固定玛纽拉 profile。"""
        return _profile()

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """返回 repository 已明确标记为 no-effect 的无道具候选。"""
        return (
            BattleInferenceItemProfile(
                item_id=None,
                identifier="none",
                display_name="不携带道具",
                effect_identifier=None,
                capability=_capability(
                    EffectSourceKind.ITEM,
                    "none",
                    MechanismSupportStatus.NO_EFFECT,
                ),
            ),
        )


def test_reconciliation_promotes_executable_candidates_without_changing_legality() -> None:
    """
    persistence 对 PokeAPI 附加效果只能给出保守 partial 判断，也会把尚未进入 domain enum 的压迫感标记为 unsupported；但页面组合使用的具体 factory 已实现冰冻拳，并为压迫感提供了带明确子能力缺口的中性占位。测试要求装饰器把这两个合法候选的整体状态提升为 supported，使配置生成器能够继续执行，同时 Pokémon ID、招式 ID、特性槽位、历史属性和候选数量全部保持不变。这样可证明对账层没有越权修改合法性或数据库读取结果，只修正当前 composition 实际可执行的覆盖结论。
    """
    repository = FactoryReconciledBattleInferenceRepository(
        repository=_Repository(),
        effect_factory=TransparentPokemonChampionEffectFactory(),
    )

    profile = repository.get_pokemon_profile(
        ruleset_id="pokemon-champion",
        version_group_id=25,
        pokemon_id=461,
    )

    assert profile is not None
    assert profile.pokemon_id == 461
    assert len(profile.moves) == 2
    assert profile.moves[0].move_id == 8
    assert profile.moves[0].capability.status is MechanismSupportStatus.SUPPORTED
    assert profile.moves[1].move_id == 216
    assert profile.moves[1].power is None
    assert profile.moves[1].capability.status is MechanismSupportStatus.UNSUPPORTED
    assert len(profile.abilities) == 1
    assert profile.abilities[0].slot == 1
    assert profile.abilities[0].capability.status is MechanismSupportStatus.SUPPORTED
    assert "Factory reconciliation" in profile.moves[0].capability.reason
    assert "Factory reconciliation" in profile.abilities[0].capability.reason
