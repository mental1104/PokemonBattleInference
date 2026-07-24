"""验证固定 1v1 用例能够串联读取、配置、回合、状态图和概率求解。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

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
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
    BattleActionPolicyKind,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
    PokemonInferenceSelection,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.inference_outcome import TerminalOutcome
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
    power: int | None,
    *,
    priority: int = 0,
    effect_identifier: str | None = None,
    support_status: MechanismSupportStatus = MechanismSupportStatus.PARTIAL,
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
        capability=_capability(
            EffectSourceKind.MOVE,
            effect_identifier or identifier,
            support_status,
        ),
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
            _ability(39, "inner-focus", status=MechanismSupportStatus.UNSUPPORTED),
            _ability(136, "multiscale", status=MechanismSupportStatus.UNSUPPORTED),
        ),
        moves=(
            _move(
                280,
                "brick-break",
                _type(2, "fighting", Type.FIGHTING),
                75,
                effect_identifier="brick-break",
            ),
            _move(
                216,
                "return",
                _type(1, "normal", Type.NORMAL),
                None,
                support_status=MechanismSupportStatus.UNSUPPORTED,
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


def _use_case() -> InferOneOnOneBattleUseCase:
    """创建真实 effect、覆盖对账 repository 与精确求解器组成的测试用例。"""
    effect_factory = TransparentPokemonChampionEffectFactory()
    repository = FactoryReconciledBattleInferenceRepository(
        repository=_Repository({149: _dragonite(), 461: _weavile()}),
        effect_factory=effect_factory,
    )
    return InferOneOnOneBattleUseCase(
        repository=repository,
        effect_factory=effect_factory,
    )


def test_fixed_ice_punch_journey_returns_complete_probability_result() -> None:
    """
    固定冰冻拳旅程必须从 fake repository 读取双方 version-aware profile，经覆盖对账与配置生成器收敛为唯一配置，再用真实多重鳞片、冰冻拳与劈瓦 effect 推进完整回合并构建状态图。测试不锁死某个伤害档概率，而是验证胜负平严格守恒、图未被运行保护截断、双方配置和策略被保留，同时压迫感真实行为作为未覆盖子机制显式出现在结果中，证明 application 没有把未实现机制伪装成完整支持或静默过滤。
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
        result.summary.inference.win_probability.value
        + result.summary.inference.loss_probability.value
        + result.summary.inference.draw_probability.value
    )
    assert total == Fraction(1)
    assert result.summary.graph_statistics.is_complete
    assert result.summary.configuration.attacker.move_ids == (280,)
    assert result.summary.configuration.defender.move_ids == (8,)
    assert result.summary.inference.attacker_policy.policy_id == "first-legal-action"
    assert "ability:pressure:real_ability_behavior" in (
        result.summary.inference.mechanism_coverage.excluded
    )
    assert result.summary.representative_paths
    graph_artifact = result.exploration.graph_artifact
    assert graph_artifact is not None
    assert result.exploration.root_node_id == int(graph_artifact.root_node_id) == 0
    assert result.exploration.graph_handle is None
    assert result.exploration.expandable
    assert (
        result.exploration.calculation_revision
        == BATTLE_INFERENCE_CALCULATION_REVISION
    )
    assert graph_artifact.statistics.unique_state_count == (
        result.summary.graph_statistics.unique_state_count
    )


def test_fake_out_pressure_journey_keeps_both_terminal_branches_without_cycles() -> None:
    """
    当玛纽拉在击掌奇袭与冰冻拳间等概率选择时，击掌奇袭成功分支会先造成伤害并让快龙畏缩；下一回合再次选择击掌奇袭会在执行前失败，但快龙仍能立即使用劈瓦结束战斗，因此这个分支不会形成状态循环。选择冰冻拳则可在多重鳞片已失效后结束另一条终局路径。测试要求状态图在两回合内完整收敛、没有封闭或可退出循环，同时快龙胜和玛纽拉胜都具有正概率且总概率严格守恒，从而按真实 TurnResolver 语义验收而不是强行制造不存在的 SCC。
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

    assert result.summary.inference.defender_policy.policy_id == "uniform-random"
    assert result.summary.graph_statistics.is_complete
    assert result.summary.graph_statistics.max_turn_number == 2
    assert result.summary.graph_statistics.closed_cycle_count == 0
    assert result.summary.graph_statistics.terminal_reachable_cycle_count == 0
    assert result.summary.inference.win_probability.value > 0
    assert result.summary.inference.loss_probability.value > 0
    assert result.summary.inference.draw_probability.value == 0
    assert result.summary.inference.probability_total == Fraction(1)
    assert {path.outcome for path in result.summary.representative_paths} == {
        TerminalOutcome.ATTACKER_WIN,
        TerminalOutcome.DEFENDER_WIN,
    }
