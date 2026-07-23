"""验证固定 1v1 用例能够串联读取、配置、回合、状态图和概率求解。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.configuration_space import (
    MechanismSupportStatus as ConfigurationMechanismSupportStatus,
    PokemonConfigurationProfile,
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
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
    PokemonInferenceSelection,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


_RULESET = BattleInferenceRules(version_group_id=25, max_turns=20)


def _capability(
    source_kind: EffectSourceKind,
    identifier: str,
    status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED,
) -> MechanismCapability:
    """创建测试 profile 使用的显式机制覆盖记录。"""
    return MechanismCapability(
        source_kind=source_kind,
        identifier=identifier,
        status=status,
        reason=f"{identifier} test capability is {status.value}.",
    )


def _type(type_id: int, identifier: str, value: Type) -> BattleInferenceTypeProfile:
    """创建已映射为 domain Type 的测试属性 projection。"""
    return BattleInferenceTypeProfile(
        type_id=type_id,
        identifier=identifier,
        display_name=identifier,
        domain_type=value,
    )


def _move(
    move_id: int,
    identifier: str,
    move_type: BattleInferenceTypeProfile,
    power: int,
    *,
    priority: int = 0,
    effect_identifier: str | None = None,
) -> BattleInferenceMoveProfile:
    """创建完整回合推进可直接消费的 version-aware 招式 projection。"""
    return BattleInferenceMoveProfile(
        move_id=move_id,
        identifier=identifier,
        display_name=identifier,
        type=move_type,
        category=MoveCategory.PHYSICAL,
        power=power,
        pp=15,
        accuracy=100,
        priority=priority,
        target_id=10,
        target_identifier="selected-pokemon",
        effect_id=None,
        effect_chance=None,
        effect_identifier=effect_identifier,
        capability=_capability(EffectSourceKind.MOVE, effect_identifier or identifier),
    )


def _ability(
    ability_id: int,
    identifier: str,
    *,
    status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED,
) -> BattleInferenceAbilityProfile:
    """创建合法特性及其当前 domain 覆盖 projection。"""
    return BattleInferenceAbilityProfile(
        ability_id=ability_id,
        identifier=identifier,
        display_name=identifier,
        slot=1,
        is_hidden=False,
        effect_identifier=identifier,
        capability=_capability(EffectSourceKind.ABILITY, identifier, status),
    )


def _dragonite() -> BattleInferencePokemonProfile:
    """创建只保留劈瓦和关键特性的快龙读取模型。"""
    return BattleInferencePokemonProfile(
        pokemon_id=149,
        identifier="dragonite",
        display_name="快龙",
        species_id=149,
        species_identifier="dragonite",
        form_identifier=None,
        is_default_form=True,
        is_battle_only_form=False,
        is_mega_form=False,
        types=(
            _type(16, "dragon", Type.DRAGON),
            _type(3, "flying", Type.FLYING),
        ),
        base_stats=StatValues(91, 134, 95, 100, 100, 80),
        can_evolve=False,
        abilities=(
            _ability(39, "inner-focus"),
            _ability(136, "multiscale"),
        ),
        moves=(
            _move(
                280,
                "brick-break",
                _type(2, "fighting", Type.FIGHTING),
                75,
                effect_identifier="brick-break",
            ),
        ),
    )


def _weavile() -> BattleInferencePokemonProfile:
    """创建包含冰冻拳、击掌奇袭和未实现压迫感的玛纽拉读取模型。"""
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
        types=(
            _type(17, "dark", Type.DARK),
            _type(15, "ice", Type.ICE),
        ),
        base_stats=StatValues(70, 120, 65, 45, 85, 125),
        can_evolve=False,
        abilities=(
            _ability(
                46,
                "pressure",
                status=MechanismSupportStatus.UNSUPPORTED,
            ),
        ),
        moves=(
            _move(
                8,
                "ice-punch",
                _type(15, "ice", Type.ICE),
                75,
                effect_identifier="ice-punch",
            ),
            _move(
                252,
                "fake-out",
                _type(1, "normal", Type.NORMAL),
                40,
                priority=3,
                effect_identifier="fake-out",
            ),
        ),
    )


@dataclass(slots=True)
class _Repository:
    """按精确规则轴返回快龙、玛纽拉和无道具候选的 fake repository。"""

    profiles: dict[int, BattleInferencePokemonProfile]

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """只接受测试声明的 Pokémon Champion version group。"""
        if (ruleset_id, version_group_id) != (
            _RULESET.ruleset_id,
            _RULESET.version_group_id,
        ):
            return None
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
        """按 Pokémon ID 返回预构造 profile，并拒绝错误规则轴。"""
        if (ruleset_id, version_group_id) != (
            _RULESET.ruleset_id,
            _RULESET.version_group_id,
        ):
            return None
        return self.profiles.get(pokemon_id)

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """返回显式无道具候选，避免测试绕过 repository 道具边界。"""
        if (ruleset_id, version_group_id) != (
            _RULESET.ruleset_id,
            _RULESET.version_group_id,
        ):
            return ()
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


class _NeutralAbilityUseCase(InferOneOnOneBattleUseCase):
    """在测试中复现页面对压迫感采用的透明中性假设。"""

    @staticmethod
    def _configuration_profile(
        profile: BattleInferencePokemonProfile,
        rules: BattleInferenceRules,
    ) -> PokemonConfigurationProfile:
        """只把压迫感候选放行给透明工厂，其他覆盖状态保持原样。"""
        converted = InferOneOnOneBattleUseCase._configuration_profile(profile, rules)
        return replace(
            converted,
            abilities=tuple(
                replace(
                    ability,
                    support_status=ConfigurationMechanismSupportStatus.SUPPORTED,
                    support_reason="Pressure uses an explicit neutral test assumption.",
                )
                if ability.identifier == "pressure"
                else ability
                for ability in converted.abilities
            ),
        )


def _use_case() -> _NeutralAbilityUseCase:
    """创建使用真实 domain effect 和纯 Python 精确求解器的测试用例。"""
    return _NeutralAbilityUseCase(
        repository=_Repository({149: _dragonite(), 461: _weavile()}),
        effect_factory=TransparentPokemonChampionEffectFactory(),
    )


def test_fixed_ice_punch_journey_returns_complete_probability_result() -> None:
    """
    固定冰冻拳旅程必须从 fake repository 读取双方 version-aware profile，经配置生成器收敛为唯一配置，再用真实多重鳞片、冰冻拳与劈瓦 effect 推进完整回合并构建状态图。测试不锁死某个伤害档概率，而是验证胜负平严格守恒、图未被运行保护截断、双方配置和策略被保留，同时压迫感真实行为作为未覆盖子机制显式出现在结果中，证明 application 没有把未实现机制伪装成完整支持或静默过滤。
    """
    result = _use_case().execute_fixed(
        InferFixedOneOnOneBattleCommand(
            rules=_RULESET,
            attacker=PokemonInferenceSelection(
                pokemon_id=149,
                move_ids=(280,),
                ability_identifier="multiscale",
            ),
            defender=PokemonInferenceSelection(
                pokemon_id=461,
                move_ids=(8,),
                ability_identifier="pressure",
            ),
        )
    )

    total = (
        result.inference.win_probability.value
        + result.inference.loss_probability.value
        + result.inference.draw_probability.value
    )
    assert total == Fraction(1)
    assert result.graph.is_complete
    assert result.configuration.attacker.move_ids == (280,)
    assert result.configuration.defender.move_ids == (8,)
    assert result.inference.attacker_policy.policy_id == "first-legal-action"
    assert "ability:pressure:real_ability_behavior" in (
        result.inference.mechanism_coverage.excluded
    )
    assert result.representative_paths


def test_fake_out_pressure_journey_exposes_terminal_reachable_cycle() -> None:
    """
    当玛纽拉把击掌奇袭和冰冻拳按均匀策略组合时，首次击掌奇袭可以造成伤害和畏缩，后续再次选择该招式会被首次出场规则拒绝，而冰冻拳仍提供离开该状态并到达终局的路径。状态键会忽略绝对回合号，因此重复失败分支应归并为可到达终局的循环，而不是无限创建节点；精确求解器仍必须给出守恒概率和有限或明确不可用的期望回合结果，并在代表路径中保留至少一种终局解释。
    """
    result = _use_case().execute_fixed(
        InferFixedOneOnOneBattleCommand(
            rules=_RULESET,
            attacker=PokemonInferenceSelection(
                pokemon_id=149,
                move_ids=(280,),
                ability_identifier="multiscale",
            ),
            defender=PokemonInferenceSelection(
                pokemon_id=461,
                move_ids=(8, 252),
                ability_identifier="pressure",
            ),
            defender_policy=BattleActionPolicyKind.UNIFORM_RANDOM,
        )
    )

    assert result.inference.defender_policy.policy_id == "uniform-random"
    assert result.graph.terminal_reachable_cycle_count >= 1
    assert result.graph.closed_cycle_count == 0
    assert (
        result.inference.win_probability.value
        + result.inference.loss_probability.value
        + result.inference.draw_probability.value
        == Fraction(1)
    )
    assert result.representative_paths
