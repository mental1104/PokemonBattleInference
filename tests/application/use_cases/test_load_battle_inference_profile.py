"""验证 application 推演资料用例只依赖稳定 repository 端口。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pokeop.application.repositories.battle_inference import (
    BattleInferenceAbilityProfile,
    BattleInferenceItemProfile,
    BattleInferenceMoveProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRepository,
    BattleInferenceRulesetContext,
    BattleInferenceTypeProfile,
    MechanismCapability,
    MechanismSupportStatus,
)
from pokeop.application.use_cases.load_battle_inference_profile import (
    BattleInferenceProfileNotFound,
    LoadBattleInferenceProfileCommand,
    LoadBattleInferenceProfileUseCase,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def _supported_capability(
    source_kind: EffectSourceKind,
    identifier: str,
) -> MechanismCapability:
    """构造 application 用例测试需要的最小 supported 覆盖记录。

    Args:
        source_kind: 测试对象对应的招式、特性或道具来源类型。
        identifier: fake projection 使用的稳定机制标识。

    Returns:
        原因固定且状态为 supported 的不可变覆盖记录。
    """
    return MechanismCapability(
        source_kind=source_kind,
        identifier=identifier,
        status=MechanismSupportStatus.SUPPORTED,
        reason="测试 fake 明确提供该机制实现。",
    )


def _ruleset() -> BattleInferenceRulesetContext:
    """创建 Pokemon Champion version group 25 的测试规则集上下文。

    Returns:
        可与默认 ``BattleInferenceRules`` 完整匹配的规则集 projection。
    """
    return BattleInferenceRulesetContext(
        ruleset_id="pokemon-champion",
        ruleset_name="Pokemon Champion",
        generation_id=9,
        version_group_id=25,
        version_group_identifier="scarlet-violet",
    )


def _dragonite_profile() -> BattleInferencePokemonProfile:
    """创建 application 编排测试使用的最小快龙完整 profile。

    Returns:
        包含真实属性、种族值、精神力和冰冻拳字段的不可变读取模型。
    """
    dragon = BattleInferenceTypeProfile(16, "dragon", "龙", Type.DRAGON)
    flying = BattleInferenceTypeProfile(3, "flying", "飞行", Type.FLYING)
    ability = BattleInferenceAbilityProfile(
        ability_id=39,
        identifier="inner-focus",
        display_name="精神力",
        slot=1,
        is_hidden=False,
        effect_identifier="inner-focus",
        capability=_supported_capability(EffectSourceKind.ABILITY, "inner-focus"),
    )
    move = BattleInferenceMoveProfile(
        move_id=8,
        identifier="ice-punch",
        display_name="冰冻拳",
        type=BattleInferenceTypeProfile(15, "ice", "冰", Type.ICE),
        category=MoveCategory.PHYSICAL,
        power=75,
        pp=15,
        accuracy=100,
        priority=0,
        target_id=10,
        target_identifier="selected-pokemon",
        effect_id=6,
        effect_chance=10,
        effect_identifier="ice-punch",
        capability=MechanismCapability(
            source_kind=EffectSourceKind.MOVE,
            identifier="ice-punch",
            status=MechanismSupportStatus.PARTIAL,
            reason="基础伤害可执行，冻结附加效果等待具体实现。",
        ),
    )
    return BattleInferencePokemonProfile(
        pokemon_id=149,
        identifier="dragonite",
        display_name="快龙",
        species_id=149,
        species_identifier="dragonite",
        form_identifier="dragonite",
        is_default_form=True,
        is_battle_only_form=False,
        is_mega_form=False,
        types=(dragon, flying),
        base_stats=StatValues(
            hp=91,
            attack=134,
            defense=95,
            special_attack=100,
            special_defense=100,
            speed=80,
        ),
        can_evolve=False,
        abilities=(ability,),
        moves=(move,),
    )


def _item_candidates() -> tuple[BattleInferenceItemProfile, ...]:
    """创建包含无道具和讲究头带的受控候选集合。

    Returns:
        可用于断言 use case 原样转交 repository projection 的稳定元组。
    """
    return (
        BattleInferenceItemProfile(
            item_id=None,
            identifier="none",
            display_name="不携带道具",
            effect_identifier=None,
            capability=MechanismCapability(
                source_kind=EffectSourceKind.ITEM,
                identifier="none",
                status=MechanismSupportStatus.NO_EFFECT,
                reason="测试显式选择不携带道具。",
            ),
        ),
        BattleInferenceItemProfile(
            item_id=220,
            identifier="choice-band",
            display_name="讲究头带",
            effect_identifier="choice-band",
            capability=_supported_capability(EffectSourceKind.ITEM, "choice-band"),
        ),
    )


@dataclass
class _FakeBattleInferenceRepository:
    """记录 application use case 调用参数的内存 fake repository。"""

    ruleset: BattleInferenceRulesetContext | None
    pokemon: BattleInferencePokemonProfile | None
    items: tuple[BattleInferenceItemProfile, ...]
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """记录规则轴查询并返回预置规则集上下文。

        Args:
            ruleset_id: use case 传入的规则集标识。
            version_group_id: use case 传入的 version group ID。

        Returns:
            构造 fake 时预置的规则集上下文或 None。
        """
        self.calls.append(("ruleset", (ruleset_id, version_group_id)))
        return self.ruleset

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleInferencePokemonProfile | None:
        """记录完整 Pokémon 查询轴并返回预置 profile。

        Args:
            ruleset_id: use case 传入的规则集标识。
            version_group_id: use case 传入的 version group ID。
            pokemon_id: use case 传入的 Pokémon ID。

        Returns:
            构造 fake 时预置的 Pokémon profile 或 None。
        """
        self.calls.append(
            ("pokemon", (ruleset_id, version_group_id, pokemon_id))
        )
        return self.pokemon

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """记录道具候选查询轴并返回预置候选。

        Args:
            ruleset_id: use case 传入的规则集标识。
            version_group_id: use case 传入的 version group ID。

        Returns:
            构造 fake 时预置的受控道具候选元组。
        """
        self.calls.append(("items", (ruleset_id, version_group_id)))
        return self.items


def test_use_case_accepts_fake_repository_and_preserves_version_axis() -> None:
    """
    本场景使用不依赖 PostgreSQL、SQLAlchemy 或 persistence 包的内存 fake repository 替换真实实现，
    然后以默认 Pokemon Champion 规则加载快龙。测试同时断言 ruleset_id、version_group_id 和 pokemon_id
    会按固定顺序传给三个读取入口，返回结果原样保留完整 Pokémon profile 与受控道具候选。该场景保护
    application 只依赖稳定 Protocol 和 projection，不把 session、DAO 或物化视图细节带入用例编排层。
    """
    repository = _FakeBattleInferenceRepository(
        ruleset=_ruleset(),
        pokemon=_dragonite_profile(),
        items=_item_candidates(),
    )
    assert isinstance(repository, BattleInferenceRepository)
    use_case = LoadBattleInferenceProfileUseCase(repository)

    result = use_case.execute(
        LoadBattleInferenceProfileCommand(
            rules=BattleInferenceRules(),
            pokemon_id=149,
        )
    )

    assert result.ruleset.version_group_id == 25
    assert result.pokemon.identifier == "dragonite"
    assert tuple(item.identifier for item in result.item_candidates) == (
        "none",
        "choice-band",
    )
    assert repository.calls == [
        ("ruleset", ("pokemon-champion", 25)),
        ("pokemon", ("pokemon-champion", 25, 149)),
        ("items", ("pokemon-champion", 25)),
    ]


def test_missing_ruleset_stops_before_pokemon_and_item_queries() -> None:
    """
    本场景让 fake repository 对精确 ruleset/version group 组合返回 None，模拟调用方传入尚未注册的版本轴。
    用例必须立即抛出稳定的 ``BattleInferenceProfileNotFound``，并且不能继续读取 Pokémon 或道具候选，
    更不能仅凭 generation 猜测另一个 version group。该断言保护 version group 是招式学习和历史字段的主轴，
    同时确保错误路径不会产生额外数据库查询或返回看似完整但混合了不同版本数据的 projection。
    """
    repository = _FakeBattleInferenceRepository(
        ruleset=None,
        pokemon=_dragonite_profile(),
        items=_item_candidates(),
    )
    use_case = LoadBattleInferenceProfileUseCase(repository)

    with pytest.raises(
        BattleInferenceProfileNotFound,
        match="ruleset context was not found",
    ):
        use_case.execute(
            LoadBattleInferenceProfileCommand(
                rules=BattleInferenceRules(),
                pokemon_id=149,
            )
        )

    assert repository.calls == [("ruleset", ("pokemon-champion", 25))]
