"""验证 version-group-aware 候选展示合同和固定配置严格机制准入。"""

from __future__ import annotations

from dataclasses import dataclass

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
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def _capability(
    source_kind: EffectSourceKind,
    identifier: str,
    status: MechanismSupportStatus,
    reason: str | None = None,
) -> MechanismCapability:
    """创建状态、来源和原因均显式的测试 capability。

    Args:
        source_kind: 机制属于招式、特性还是道具。
        identifier: repository 与 effect factory 对账使用的稳定标识。
        status: 当前测试场景需要的完整、部分或不支持状态。
        reason: 可选自定义原因；省略时根据标识和状态生成稳定文本。

    Returns:
        可直接嵌入 application repository projection 的不可变 capability。
    """
    return MechanismCapability(
        source_kind=source_kind,
        identifier=identifier,
        status=status,
        reason=reason or f"{identifier} is {status.value} in this test fixture.",
    )


def _type_profile(
    type_id: int,
    identifier: str,
    display_name: str,
    domain_type: Type,
) -> BattleInferenceTypeProfile:
    """构造同时保存 PokeAPI 和 domain 标识的属性 projection。

    Args:
        type_id: PokeAPI 属性整数 ID。
        identifier: PokeAPI 属性 identifier。
        display_name: 测试展示名称。
        domain_type: domain 计算使用的显式 Type。

    Returns:
        可由招式和 Pokémon profile 复用的属性读取模型。
    """
    return BattleInferenceTypeProfile(
        type_id=type_id,
        identifier=identifier,
        display_name=display_name,
        domain_type=domain_type,
    )


def _move(
    *,
    move_id: int,
    identifier: str,
    display_name: str,
    type_profile: BattleInferenceTypeProfile,
    status: MechanismSupportStatus,
    power: int | None = 50,
    effect_id: int | None = 1,
    effect_identifier: str | None = None,
    effect_chance: int | None = None,
    priority: int = 0,
) -> BattleInferenceMoveProfile:
    """构造已完成历史还原和 capability 判断的招式 projection。

    Args:
        move_id: PokeAPI 招式整数 ID。
        identifier: 招式稳定 identifier。
        display_name: 当前语言展示名称。
        type_profile: 当前 version group 下的有效属性。
        status: 当前计算版本对整体机制的支持状态。
        power: 固定基础威力；变化威力时为 None。
        effect_id: PokeAPI move effect ID。
        effect_identifier: effect factory 使用的标识；纯基础伤害为 None。
        effect_chance: 百分制附加效果概率。
        priority: 当前 version group 下的行动优先级。

    Returns:
        可由 fake repository 返回的完整招式读取模型。
    """
    capability_identifier = effect_identifier or (
        "base-damage"
        if status in {
            MechanismSupportStatus.SUPPORTED,
            MechanismSupportStatus.NO_EFFECT,
        }
        else identifier
    )
    return BattleInferenceMoveProfile(
        move_id=move_id,
        identifier=identifier,
        display_name=display_name,
        type=type_profile,
        category=MoveCategory.PHYSICAL,
        power=power,
        pp=20,
        accuracy=100,
        priority=priority,
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
    *,
    ability_id: int = 62,
    identifier: str = "guts",
    status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED,
) -> BattleInferenceAbilityProfile:
    """构造当前 version group 下合法的特性候选。

    Args:
        ability_id: PokeAPI 特性整数 ID。
        identifier: 特性稳定 identifier。
        status: 当前计算版本对该特性的支持状态。

    Returns:
        可用于候选展示和固定配置准入测试的特性 projection。
    """
    return BattleInferenceAbilityProfile(
        ability_id=ability_id,
        identifier=identifier,
        display_name=identifier,
        slot=1,
        is_hidden=False,
        effect_identifier=identifier,
        capability=_capability(EffectSourceKind.ABILITY, identifier, status),
    )


def _item(
    *,
    item_id: int | None,
    identifier: str,
    status: MechanismSupportStatus,
) -> BattleInferenceItemProfile:
    """构造受控道具或显式无道具候选。

    Args:
        item_id: PokeAPI 道具 ID；无道具为 None。
        identifier: 道具 identifier；无道具为 ``none``。
        status: 当前计算版本对该道具的支持状态。

    Returns:
        可由 fake repository 返回的受控道具 projection。
    """
    return BattleInferenceItemProfile(
        item_id=item_id,
        identifier=identifier,
        display_name=identifier,
        effect_identifier=None if identifier == "none" else identifier,
        capability=_capability(EffectSourceKind.ITEM, identifier, status),
    )


def _profile(
    *,
    moves: tuple[BattleInferenceMoveProfile, ...],
    abilities: tuple[BattleInferenceAbilityProfile, ...] | None = None,
) -> BattleInferencePokemonProfile:
    """构造 Machop 的最小完整 version-aware profile。

    Args:
        moves: 当前 version group 下按 move_id 去重后的合法招式。
        abilities: 当前 version group 下的合法特性；省略时使用 supported 毅力。

    Returns:
        包含真实种族值和格斗属性的 application repository projection。
    """
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
        types=(_type_profile(2, "fighting", "格斗", Type.FIGHTING),),
        base_stats=StatValues(
            hp=70,
            attack=80,
            defense=50,
            special_attack=35,
            special_defense=35,
            speed=35,
        ),
        can_evolve=True,
        abilities=abilities or (_ability(),),
        moves=moves,
    )


@dataclass(slots=True)
class _VersionAwareRepository:
    """按 version group 返回不同上下文和 Pokémon profile 的内存 repository。"""

    profiles: dict[int, BattleInferencePokemonProfile]
    items: tuple[BattleInferenceItemProfile, ...]

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """按精确 version group 返回测试规则集上下文。

        Args:
            ruleset_id: 候选用例请求的稳定规则集标识。
            version_group_id: 招式学习和历史还原使用的主轴。

        Returns:
            已配置版本返回对应世代上下文；未知版本返回 None。
        """
        generation_by_version_group = {1: 1, 3: 2, 25: 9}
        generation_id = generation_by_version_group.get(version_group_id)
        if generation_id is None or version_group_id not in self.profiles:
            return None
        return BattleInferenceRulesetContext(
            ruleset_id=ruleset_id,
            ruleset_name="Test Ruleset",
            generation_id=generation_id,
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
        """返回目标 version group 的预置 profile。

        Args:
            ruleset_id: 候选用例请求的规则集标识，本 fake 不额外过滤。
            version_group_id: 选择历史招式资料的精确版本轴。
            pokemon_id: 需要读取的 Pokémon ID。

        Returns:
            仅当 pokemon_id 为 Machop 且版本已配置时返回 profile。
        """
        if pokemon_id != 66:
            return None
        return self.profiles.get(version_group_id)

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """返回受控道具集合或未知版本的空边界。

        Args:
            ruleset_id: 候选用例请求的稳定规则集标识。
            version_group_id: 当前道具边界适用的 version group。

        Returns:
            已配置版本返回固定道具元组；未知版本返回空元组。
        """
        return self.items if version_group_id in self.profiles else ()


def _repository_for_profiles(
    profiles: dict[int, BattleInferencePokemonProfile],
    *,
    extra_items: tuple[BattleInferenceItemProfile, ...] = (),
) -> _VersionAwareRepository:
    """创建包含显式无道具和可选扩展道具的 fake repository。

    Args:
        profiles: 按 version group 组织的 Pokémon profile。
        extra_items: 需要追加到无道具候选后的测试道具。

    Returns:
        可同时驱动候选展示和严格准入用例的内存 repository。
    """
    return _VersionAwareRepository(
        profiles=profiles,
        items=(
            _item(
                item_id=None,
                identifier="none",
                status=MechanismSupportStatus.NO_EFFECT,
            ),
        )
        + extra_items,
    )


def test_candidate_pool_preserves_version_group_historical_move_values() -> None:
    """
    本场景用同一只腕力和同一个空手劈 move_id 构造红蓝版与金银版两个 repository profile：
    红蓝版保留第一世代的普通属性，金银版恢复后续使用的格斗属性。候选池用例必须严格按照
    command 中的 version_group_id 读取对应 profile，并把属性、威力、优先级、学习合法性、
    ruleset_id、version_group_id 与 calculation_revision 原样绑定到结果和 admission key。
    该测试保护 application 不会用 generation 近似另一个版本，也不会在候选投影时覆盖
    persistence 已根据 move_changelog 还原的历史字段。
    """
    normal = _type_profile(1, "normal", "一般", Type.NORMAL)
    fighting = _type_profile(2, "fighting", "格斗", Type.FIGHTING)
    repository = _repository_for_profiles(
        {
            1: _profile(
                moves=(
                    _move(
                        move_id=2,
                        identifier="karate-chop",
                        display_name="空手劈",
                        type_profile=normal,
                        status=MechanismSupportStatus.SUPPORTED,
                    ),
                )
            ),
            3: _profile(
                moves=(
                    _move(
                        move_id=2,
                        identifier="karate-chop",
                        display_name="空手劈",
                        type_profile=fighting,
                        status=MechanismSupportStatus.SUPPORTED,
                    ),
                )
            ),
        }
    )
    use_case = ListBattleCandidatePoolUseCase(
        repository,
        calculation_revision="candidate-pool.test.v1",
    )

    red_blue = use_case.execute(
        ListBattleCandidatePoolCommand(
            rules=BattleInferenceRules(
                ruleset_id="test-ruleset",
                version_group_id=1,
            ),
            pokemon_id=66,
        )
    )
    gold_silver = use_case.execute(
        ListBattleCandidatePoolCommand(
            rules=BattleInferenceRules(
                ruleset_id="test-ruleset",
                version_group_id=3,
            ),
            pokemon_id=66,
        )
    )

    assert red_blue.moves[0].move.type.identifier == "normal"
    assert gold_silver.moves[0].move.type.identifier == "fighting"
    assert red_blue.moves[0].legality.version_group_id == 1
    assert gold_silver.moves[0].legality.version_group_id == 3
    assert red_blue.moves[0].admission.key.ruleset_id == "test-ruleset"
    assert red_blue.moves[0].admission.key.calculation_revision == (
        "candidate-pool.test.v1"
    )


def test_partial_and_unsupported_moves_remain_visible_but_disabled() -> None:
    """
    本场景让腕力的候选池同时包含一个纯基础伤害招式、一个基础伤害可算但追加效果尚未完整
    实现的招式，以及一个缺少动态威力解析器的招式。候选池必须按 move_id 稳定排序并完整
    返回三项，不能为了让组合生成成功而删除 partial 或 unsupported 候选；但只有 supported
    候选可以选择，其余候选必须返回禁用原因和缺失机制标识。该测试直接保护“可见不等于
    可提交”的产品语义，避免前端误把基础伤害可算当成整体机制已支持。
    """
    fighting = _type_profile(2, "fighting", "格斗", Type.FIGHTING)
    repository = _repository_for_profiles(
        {
            25: _profile(
                moves=(
                    _move(
                        move_id=216,
                        identifier="return",
                        display_name="报恩",
                        type_profile=fighting,
                        status=MechanismSupportStatus.UNSUPPORTED,
                        power=None,
                        effect_identifier="return",
                    ),
                    _move(
                        move_id=8,
                        identifier="ice-punch",
                        display_name="冰冻拳",
                        type_profile=_type_profile(15, "ice", "冰", Type.ICE),
                        status=MechanismSupportStatus.PARTIAL,
                        effect_id=2,
                        effect_identifier="ice-punch",
                        effect_chance=10,
                    ),
                    _move(
                        move_id=2,
                        identifier="karate-chop",
                        display_name="空手劈",
                        type_profile=fighting,
                        status=MechanismSupportStatus.SUPPORTED,
                    ),
                )
            ),
        }
    )

    pool = ListBattleCandidatePoolUseCase(
        repository,
        calculation_revision="candidate-pool.test.v1",
    ).execute(
        ListBattleCandidatePoolCommand(
            rules=BattleInferenceRules(),
            pokemon_id=66,
        )
    )

    assert tuple(candidate.move_id for candidate in pool.moves) == (2, 8, 216)
    assert pool.moves[0].admission.selectable is True
    assert pool.moves[0].admission.disabled_reason is None
    assert pool.moves[1].admission.selectable is False
    assert pool.moves[1].admission.status is MechanismSupportStatus.PARTIAL
    assert pool.moves[1].admission.disabled_reason is not None
    assert pool.moves[1].admission.missing_mechanism_identifiers == ("ice-punch",)
    assert pool.moves[2].admission.status is MechanismSupportStatus.UNSUPPORTED
    assert pool.moves[2].admission.missing_mechanism_identifiers == ("return",)


def test_strict_admission_returns_supported_fixed_selection_before_task_creation() -> None:
    """
    本场景提交一项完整支持的空手劈、完整支持的毅力和明确 no-effect 的无道具固定配置。
    严格准入用例必须在不构建状态图、不运行 solver、也不创建后台任务的情况下完成候选匹配，
    返回按命令顺序保留的已验证对象，并确保三类 admission key 共享同一 ruleset、
    version_group_id 和 calculation_revision。该场景保护任务创建方可以把验证结果作为前置门禁，
    而不需要依赖后续配置枚举或战斗运行阶段再次猜测机制支持情况。
    """
    fighting = _type_profile(2, "fighting", "格斗", Type.FIGHTING)
    repository = _repository_for_profiles(
        {
            25: _profile(
                moves=(
                    _move(
                        move_id=2,
                        identifier="karate-chop",
                        display_name="空手劈",
                        type_profile=fighting,
                        status=MechanismSupportStatus.SUPPORTED,
                    ),
                )
            ),
        }
    )

    result = ValidateFixedMechanismSelectionUseCase(
        repository,
        calculation_revision="candidate-pool.test.v1",
    ).execute(
        ValidateFixedMechanismSelectionCommand(
            rules=BattleInferenceRules(),
            pokemon_id=66,
            move_ids=(2,),
            ability_identifier="guts",
            item_identifier=None,
        )
    )

    assert tuple(candidate.move_id for candidate in result.moves) == (2,)
    assert result.ability.identifier == "guts"
    assert result.item.identifier == "none"
    assert result.item.admission.status is MechanismSupportStatus.NO_EFFECT
    assert result.moves[0].admission.key.calculation_revision == (
        "candidate-pool.test.v1"
    )


def test_strict_admission_rejects_partial_move_unsupported_ability_and_item_together() -> None:
    """
    本场景在同一次固定配置提交中选择追加效果未实现的冰冻拳、当前 engine 不支持的无防守特性，
    以及受控边界中仍未实现的测试道具。严格准入不能只返回第一项错误，更不能让任务进入批量
    配置或状态图阶段后逐个失败；它必须一次性抛出结构化异常，保留 move、ability、item 三个
    来源的 PARTIAL/UNSUPPORTED 状态、禁用原因和缺失机制标识。该场景保护调用方能够一次修正
    全部固定机制，并确保失败配置不会从概率分母中静默消失。
    """
    ice = _type_profile(15, "ice", "冰", Type.ICE)
    repository = _repository_for_profiles(
        {
            25: _profile(
                moves=(
                    _move(
                        move_id=8,
                        identifier="ice-punch",
                        display_name="冰冻拳",
                        type_profile=ice,
                        status=MechanismSupportStatus.PARTIAL,
                        effect_id=2,
                        effect_identifier="ice-punch",
                        effect_chance=10,
                    ),
                ),
                abilities=(
                    _ability(
                        ability_id=99,
                        identifier="no-guard",
                        status=MechanismSupportStatus.UNSUPPORTED,
                    ),
                ),
            ),
        },
        extra_items=(
            _item(
                item_id=999,
                identifier="test-item",
                status=MechanismSupportStatus.UNSUPPORTED,
            ),
        ),
    )
    use_case = ValidateFixedMechanismSelectionUseCase(
        repository,
        calculation_revision="candidate-pool.test.v1",
    )

    with pytest.raises(StrictMechanismAdmissionRejected) as error:
        use_case.execute(
            ValidateFixedMechanismSelectionCommand(
                rules=BattleInferenceRules(),
                pokemon_id=66,
                move_ids=(8,),
                ability_identifier="no-guard",
                item_identifier="test-item",
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
        MechanismSupportStatus.UNSUPPORTED,
        MechanismSupportStatus.UNSUPPORTED,
    )
    assert tuple(
        failure.missing_mechanism_identifiers for failure in failures
    ) == (("ice-punch",), ("no-guard",), ("test-item",))


def test_strict_admission_rejects_move_not_legal_in_target_version_group() -> None:
    """
    本场景的 repository 只声明腕力在目标 version group 下可以学习空手劈，但固定任务提交
    选择了未出现在该候选池中的招式 ID。严格准入必须把它解释为当前 Pokémon 与精确版本轴下
    不合法的 unsupported 选择，生成包含 ruleset、version_group、source_kind、
    calculation_revision 和合成缺失标识的失败记录，而不是回退到其他 version group 的学习表，
    也不能把未知招式交给 domain factory 尝试执行。该测试保护学习合法性与机制支持是两道
    独立且都必须通过的门禁。
    """
    fighting = _type_profile(2, "fighting", "格斗", Type.FIGHTING)
    repository = _repository_for_profiles(
        {
            25: _profile(
                moves=(
                    _move(
                        move_id=2,
                        identifier="karate-chop",
                        display_name="空手劈",
                        type_profile=fighting,
                        status=MechanismSupportStatus.SUPPORTED,
                    ),
                )
            ),
        }
    )

    with pytest.raises(StrictMechanismAdmissionRejected) as error:
        ValidateFixedMechanismSelectionUseCase(
            repository,
            calculation_revision="candidate-pool.test.v1",
        ).execute(
            ValidateFixedMechanismSelectionCommand(
                rules=BattleInferenceRules(),
                pokemon_id=66,
                move_ids=(999,),
                ability_identifier="guts",
            )
        )

    failure = error.value.failures[0]
    assert failure.key.source_kind is EffectSourceKind.MOVE
    assert failure.key.version_group_id == 25
    assert failure.key.calculation_revision == "candidate-pool.test.v1"
    assert failure.status is MechanismSupportStatus.UNSUPPORTED
    assert failure.missing_mechanism_identifiers == ("move-id-999",)
