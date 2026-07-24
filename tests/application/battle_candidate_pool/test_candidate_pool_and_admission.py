"""验证 version-group-aware 候选展示合同和固定配置严格机制准入。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pokeop.application.battle_candidate_pool import (
    ListBattleCandidatePoolCommand,
    ListBattleCandidatePoolUseCase,
    StrictMechanismAdmissionRejected,
    ValidateFixedMechanismSelectionCommand,
    ValidateFixedMechanismSelectionUseCase,
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
from pokeop.domain.battle.effects.protocols import (
    EffectCapabilityCoverage,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


@dataclass(frozen=True, slots=True)
class _CoverageOnlyEffect:
    """提供候选准入测试只需要的结构化 coverage 产品。"""

    coverage: EffectCoverage


@dataclass(slots=True)
class _TestEffectFactory:
    """使用显式 descriptor 控制测试机制的完整、部分和不支持状态。"""

    ruleset_id: str
    partial_moves: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unsupported_moves: frozenset[str] = frozenset()
    ability_gaps: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unsupported_items: frozenset[str] = frozenset()

    def create_move_effect(self, identifier: str | None) -> _CoverageOnlyEffect:
        """按招式标识返回完整、部分、不支持或明确 no-effect descriptor。"""
        if identifier is None:
            return self._effect(
                EffectSourceKind.MOVE,
                "none",
                EffectCoverageStatus.NO_EFFECT,
                "纯基础伤害不需要额外 move effect。",
            )
        if identifier in self.partial_moves:
            return self._effect(
                EffectSourceKind.MOVE,
                identifier,
                EffectCoverageStatus.PARTIAL,
                "基础执行可用，但仍有未实现的追加机制。",
                unsupported_aspects=self.partial_moves[identifier],
            )
        if identifier in self.unsupported_moves:
            return self._effect(
                EffectSourceKind.MOVE,
                identifier,
                EffectCoverageStatus.UNSUPPORTED,
                "当前测试 engine 尚未实现该招式。",
            )
        return self._effect(
            EffectSourceKind.MOVE,
            identifier,
            EffectCoverageStatus.SUPPORTED,
            "当前测试 engine 完整支持该招式。",
        )

    def create_ability_effect(self, identifier: str | None) -> _CoverageOnlyEffect:
        """返回可包含真实行为缺口的特性 descriptor。"""
        normalized = identifier or "none"
        capabilities = tuple(
            EffectCapabilityCoverage(
                identifier=gap,
                status=EffectCoverageStatus.UNSUPPORTED,
                reason="该真实特性子能力尚未纳入精确推演。",
            )
            for gap in self.ability_gaps.get(normalized, ())
        )
        return self._effect(
            EffectSourceKind.ABILITY,
            normalized,
            EffectCoverageStatus.SUPPORTED,
            "产品可执行，但 descriptor 可能仍声明真实行为缺口。",
            capabilities=capabilities,
        )

    def create_item_effect(self, identifier: str | None) -> _CoverageOnlyEffect:
        """返回无道具、完整支持或不支持的道具 descriptor。"""
        if identifier is None:
            return self._effect(
                EffectSourceKind.ITEM,
                "none",
                EffectCoverageStatus.NO_EFFECT,
                "显式不携带道具，不需要额外 item effect。",
            )
        if identifier in self.unsupported_items:
            return self._effect(
                EffectSourceKind.ITEM,
                identifier,
                EffectCoverageStatus.UNSUPPORTED,
                "当前测试 engine 尚未实现该道具。",
            )
        return self._effect(
            EffectSourceKind.ITEM,
            identifier,
            EffectCoverageStatus.SUPPORTED,
            "当前测试 engine 完整支持该道具。",
        )

    def create_effect_family(self, **_: object) -> object:
        """满足抽象工厂协议；候选池用例不会调用该批量入口。"""
        raise AssertionError("candidate pool must use typed factory methods")

    def _effect(
        self,
        source_kind: EffectSourceKind,
        identifier: str,
        status: EffectCoverageStatus,
        reason: str,
        *,
        capabilities: tuple[EffectCapabilityCoverage, ...] = (),
        unsupported_aspects: tuple[str, ...] = (),
    ) -> _CoverageOnlyEffect:
        """构造满足 domain coverage 不变量的轻量测试 effect。"""
        return _CoverageOnlyEffect(
            EffectCoverage(
                ruleset_id=self.ruleset_id,
                source_kind=source_kind,
                identifier=identifier,
                status=status,
                reason=reason,
                capabilities=capabilities,
                unsupported_aspects=unsupported_aspects,
            )
        )


def _capability(
    source_kind: EffectSourceKind,
    identifier: str,
    status: MechanismSupportStatus,
) -> MechanismCapability:
    """构造 persistence/application 边界使用的保守 capability。"""
    return MechanismCapability(
        source_kind=source_kind,
        identifier=identifier,
        status=status,
        reason=f"repository marks {identifier} as {status.value}.",
    )


def _type(
    type_id: int,
    identifier: str,
    domain_type: Type,
) -> BattleInferenceTypeProfile:
    """构造同时保留 PokeAPI 标识和 domain Type 的属性 projection。"""
    return BattleInferenceTypeProfile(
        type_id=type_id,
        identifier=identifier,
        display_name=identifier,
        domain_type=domain_type,
    )


def _move(
    move_id: int,
    identifier: str,
    type_profile: BattleInferenceTypeProfile,
    status: MechanismSupportStatus,
    *,
    power: int | None = 50,
    effect_identifier: str | None = None,
    effect_id: int | None = 1,
    effect_chance: int | None = None,
) -> BattleInferenceMoveProfile:
    """构造已由 persistence 完成历史还原的完整招式 projection。"""
    capability_identifier = effect_identifier or "base-damage"
    return BattleInferenceMoveProfile(
        move_id=move_id,
        identifier=identifier,
        display_name=identifier,
        type=type_profile,
        category=MoveCategory.PHYSICAL,
        power=power,
        pp=20,
        accuracy=100,
        priority=0,
        target_id=10,
        target_identifier="selected-pokemon",
        effect_id=effect_id,
        effect_chance=effect_chance,
        effect_identifier=effect_identifier,
        capability=_capability(
            EffectSourceKind.MOVE,
            capability_identifier,
            status,
        ),
    )


def _ability(
    identifier: str = "guts",
    status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED,
) -> BattleInferenceAbilityProfile:
    """构造当前 version group 下合法的特性 projection。"""
    return BattleInferenceAbilityProfile(
        ability_id=62 if identifier == "guts" else 46,
        identifier=identifier,
        display_name=identifier,
        slot=1,
        is_hidden=False,
        effect_identifier=identifier,
        capability=_capability(EffectSourceKind.ABILITY, identifier, status),
    )


def _item(
    identifier: str,
    status: MechanismSupportStatus,
) -> BattleInferenceItemProfile:
    """构造受控道具或显式无道具 projection。"""
    return BattleInferenceItemProfile(
        item_id=None if identifier == "none" else 999,
        identifier=identifier,
        display_name=identifier,
        effect_identifier=None if identifier == "none" else identifier,
        capability=_capability(EffectSourceKind.ITEM, identifier, status),
    )


def _profile(
    moves: tuple[BattleInferenceMoveProfile, ...],
    *,
    abilities: tuple[BattleInferenceAbilityProfile, ...] = (),
) -> BattleInferencePokemonProfile:
    """构造候选池测试使用的腕力完整 profile。"""
    return BattleInferencePokemonProfile(
        pokemon_id=66,
        identifier="machop",
        display_name="腕力",
        species_id=66,
        species_identifier="machop",
        form_identifier="machop",
        is_default_form=True,
        is_battle_only_form=False,
        is_mega_form=False,
        types=(_type(2, "fighting", Type.FIGHTING),),
        base_stats=StatValues(70, 80, 50, 35, 35, 35),
        can_evolve=True,
        abilities=abilities or (_ability(),),
        moves=moves,
    )


@dataclass(slots=True)
class _Repository:
    """按 version group 返回不同 profile 的内存 repository。"""

    profiles: dict[int, BattleInferencePokemonProfile]
    items: tuple[BattleInferenceItemProfile, ...]

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """按精确 version group 返回规则上下文，未知版本不做 generation 近似。"""
        generation = {1: 1, 3: 2, 25: 9}.get(version_group_id)
        if generation is None or version_group_id not in self.profiles:
            return None
        return BattleInferenceRulesetContext(
            ruleset_id=ruleset_id,
            ruleset_name="Test Ruleset",
            generation_id=generation,
            version_group_id=version_group_id,
            version_group_identifier={
                1: "red-blue",
                3: "gold-silver",
                25: "scarlet-violet",
            }[version_group_id],
        )

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleInferencePokemonProfile | None:
        """仅按完整 version group 与 Pokémon ID 返回预置 profile。"""
        del ruleset_id
        return self.profiles.get(version_group_id) if pokemon_id == 66 else None

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """仅在目标 version group 已配置时返回受控道具边界。"""
        del ruleset_id
        return self.items if version_group_id in self.profiles else ()


def _repository(
    profiles: dict[int, BattleInferencePokemonProfile],
    *extra_items: BattleInferenceItemProfile,
) -> _Repository:
    """创建包含显式无道具候选的测试 repository。"""
    return _Repository(
        profiles=profiles,
        items=(
            _item("none", MechanismSupportStatus.NO_EFFECT),
            *extra_items,
        ),
    )


def test_candidate_pool_preserves_historical_values_by_version_group() -> None:
    """
    同一个空手劈 move_id 在红蓝版与金银版分别携带不同的属性、威力和 effect 字段，模拟
    persistence 已根据 move_changelog 还原的历史结果。候选池必须严格使用 command 中的
    version_group_id 获取对应 profile，不得用 generation 或最新 moves 表近似；输出还要把
    ruleset_id、version_group_id、学习合法性和 calculation_revision 绑定到准入键，确保缓存、
    API 与任务提交都无法混用其他版本的候选快照。
    """
    repository = _repository(
        {
            1: _profile(
                (
                    _move(
                        2,
                        "karate-chop",
                        _type(1, "normal", Type.NORMAL),
                        MechanismSupportStatus.SUPPORTED,
                        power=40,
                    ),
                )
            ),
            3: _profile(
                (
                    _move(
                        2,
                        "karate-chop",
                        _type(2, "fighting", Type.FIGHTING),
                        MechanismSupportStatus.PARTIAL,
                        power=60,
                        effect_identifier="karate-chop",
                        effect_id=2,
                        effect_chance=30,
                    ),
                )
            ),
        }
    )
    factory = _TestEffectFactory(
        ruleset_id="test-ruleset",
        partial_moves={"karate-chop": ("historical-secondary-effect",)},
    )
    use_case = ListBattleCandidatePoolUseCase(
        repository,
        factory,
        "candidate-pool.test.v1",
    )

    red_blue = use_case.execute(
        ListBattleCandidatePoolCommand(
            BattleInferenceRules(ruleset_id="test-ruleset", version_group_id=1),
            66,
        )
    )
    gold_silver = use_case.execute(
        ListBattleCandidatePoolCommand(
            BattleInferenceRules(ruleset_id="test-ruleset", version_group_id=3),
            66,
        )
    )

    assert red_blue.moves[0].move.type.identifier == "normal"
    assert red_blue.moves[0].move.power == 40
    assert gold_silver.moves[0].move.type.identifier == "fighting"
    assert gold_silver.moves[0].move.power == 60
    assert gold_silver.moves[0].move.effect_id == 2
    assert gold_silver.moves[0].move.effect_chance == 30
    assert red_blue.moves[0].legality.version_group_id == 1
    assert gold_silver.moves[0].admission.key.version_group_id == 3
    assert red_blue.moves[0].admission.key.calculation_revision == (
        "candidate-pool.test.v1"
    )


def test_partial_and_unsupported_moves_remain_visible_but_disabled() -> None:
    """
    候选池同时包含纯基础伤害、追加效果缺失和变化威力三类合法招式。application 必须按
    move_id 稳定返回全部候选，不能为了让组合枚举成功而静默删除 partial 或 unsupported；
    只有完整支持项可选择，其余项必须暴露禁用原因和由 effect descriptor 给出的缺失机制标识。
    这直接保护“基础伤害可算”不等于“整招可进入精确推演”的严格产品语义。
    """
    fighting = _type(2, "fighting", Type.FIGHTING)
    repository = _repository(
        {
            25: _profile(
                (
                    _move(
                        216,
                        "return",
                        fighting,
                        MechanismSupportStatus.UNSUPPORTED,
                        power=None,
                        effect_identifier="return",
                    ),
                    _move(
                        8,
                        "ice-punch",
                        _type(15, "ice", Type.ICE),
                        MechanismSupportStatus.PARTIAL,
                        effect_identifier="ice-punch",
                        effect_id=2,
                        effect_chance=10,
                    ),
                    _move(
                        2,
                        "karate-chop",
                        fighting,
                        MechanismSupportStatus.SUPPORTED,
                    ),
                )
            )
        }
    )
    pool = ListBattleCandidatePoolUseCase(
        repository,
        _TestEffectFactory(
            ruleset_id="pokemon-champion",
            partial_moves={"ice-punch": ("freeze-secondary-effect",)},
            unsupported_moves=frozenset({"return"}),
        ),
        "candidate-pool.test.v1",
    ).execute(ListBattleCandidatePoolCommand(BattleInferenceRules(), 66))

    assert tuple(candidate.move_id for candidate in pool.moves) == (2, 8, 216)
    assert pool.moves[0].admission.selectable is True
    assert pool.moves[1].admission.status is MechanismSupportStatus.PARTIAL
    assert pool.moves[1].admission.missing_mechanism_identifiers == (
        "freeze-secondary-effect",
    )
    assert pool.moves[2].admission.status is MechanismSupportStatus.UNSUPPORTED
    assert pool.moves[2].admission.missing_mechanism_identifiers == ("return",)
    assert pool.moves[1].admission.disabled_reason is not None


def test_strict_admission_accepts_only_complete_fixed_selection() -> None:
    """
    固定任务选择完整支持的空手劈、毅力和明确 no-effect 的无道具。严格准入必须在构建状态图、
    运行 solver 或创建后台任务之前完成匹配，返回按命令顺序保留的已验证候选，并确保 moves、
    ability、item 的 admission key 共享同一 ruleset、version_group_id 与 calculation_revision。
    该结果可直接成为未来任务创建入口的前置门禁，而不需要在运行阶段再次猜测支持状态。
    """
    repository = _repository(
        {
            25: _profile(
                (
                    _move(
                        2,
                        "karate-chop",
                        _type(2, "fighting", Type.FIGHTING),
                        MechanismSupportStatus.SUPPORTED,
                    ),
                )
            )
        }
    )
    result = ValidateFixedMechanismSelectionUseCase(
        repository,
        _TestEffectFactory(ruleset_id="pokemon-champion"),
        "candidate-pool.test.v1",
    ).execute(
        ValidateFixedMechanismSelectionCommand(
            BattleInferenceRules(),
            66,
            (2,),
            "guts",
        )
    )

    assert tuple(candidate.move_id for candidate in result.moves) == (2,)
    assert result.ability.identifier == "guts"
    assert result.item.identifier == "none"
    assert result.item.admission.status is MechanismSupportStatus.NO_EFFECT
    assert result.moves[0].admission.key.calculation_revision == (
        "candidate-pool.test.v1"
    )


def test_strict_admission_rejects_all_incomplete_mechanisms_together() -> None:
    """
    同一次固定配置提交选择追加效果缺失的冰冻拳、只能中性占位的压迫感和未实现道具。
    特性 factory 即使把占位产品整体标为 SUPPORTED，只要 descriptor 仍包含真实行为子能力缺口，
    严格准入也必须降级为 PARTIAL。用例要一次性返回 move、ability、item 三项失败及各自缺失
    identifier，不能只报第一项错误，更不能让这些配置进入批量运行后再失败并从概率分母消失。
    """
    repository = _repository(
        {
            25: _profile(
                (
                    _move(
                        8,
                        "ice-punch",
                        _type(15, "ice", Type.ICE),
                        MechanismSupportStatus.PARTIAL,
                        effect_identifier="ice-punch",
                        effect_id=2,
                        effect_chance=10,
                    ),
                ),
                abilities=(
                    _ability("pressure", MechanismSupportStatus.UNSUPPORTED),
                ),
            )
        },
        _item("test-item", MechanismSupportStatus.UNSUPPORTED),
    )
    use_case = ValidateFixedMechanismSelectionUseCase(
        repository,
        _TestEffectFactory(
            ruleset_id="pokemon-champion",
            partial_moves={"ice-punch": ("freeze-secondary-effect",)},
            ability_gaps={"pressure": ("real-ability-behavior",)},
            unsupported_items=frozenset({"test-item"}),
        ),
        "candidate-pool.test.v1",
    )

    with pytest.raises(StrictMechanismAdmissionRejected) as error:
        use_case.execute(
            ValidateFixedMechanismSelectionCommand(
                BattleInferenceRules(),
                66,
                (8,),
                "pressure",
                "test-item",
            )
        )

    failures = error.value.failures
    assert tuple(failure.key.source_kind for failure in failures) == (
        EffectSourceKind.MOVE,
        EffectSourceKind.ABILITY,
        EffectSourceKind.ITEM,
    )
    assert tuple(failure.status for failure in failures) == (
        MechanismSupportStatus.PARTIAL,
        MechanismSupportStatus.PARTIAL,
        MechanismSupportStatus.UNSUPPORTED,
    )
    assert tuple(failure.missing_mechanism_identifiers for failure in failures) == (
        ("freeze-secondary-effect",),
        ("real-ability-behavior",),
        ("test-item",),
    )


def test_strict_admission_rejects_move_illegal_in_target_version_group() -> None:
    """
    repository 只声明目标 version group 下腕力可以学习空手劈，但固定任务提交另一个 move_id。
    严格准入必须把它解释为当前 Pokémon 与精确版本轴下不合法的 UNSUPPORTED 选择，生成绑定
    ruleset、version_group、source_kind、calculation_revision 的失败记录；不得回退到其他
    version group 的学习表，也不能把未知招式交给 domain factory 尝试执行。
    """
    repository = _repository(
        {
            25: _profile(
                (
                    _move(
                        2,
                        "karate-chop",
                        _type(2, "fighting", Type.FIGHTING),
                        MechanismSupportStatus.SUPPORTED,
                    ),
                )
            )
        }
    )

    with pytest.raises(StrictMechanismAdmissionRejected) as error:
        ValidateFixedMechanismSelectionUseCase(
            repository,
            _TestEffectFactory(ruleset_id="pokemon-champion"),
            "candidate-pool.test.v1",
        ).execute(
            ValidateFixedMechanismSelectionCommand(
                BattleInferenceRules(),
                66,
                (999,),
                "guts",
            )
        )

    failure = error.value.failures[0]
    assert failure.key.source_kind is EffectSourceKind.MOVE
    assert failure.key.version_group_id == 25
    assert failure.key.calculation_revision == "candidate-pool.test.v1"
    assert failure.status is MechanismSupportStatus.UNSUPPORTED
    assert failure.missing_mechanism_identifiers == ("move-id-999",)
