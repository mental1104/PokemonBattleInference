"""验证 version-aware 战斗推演 repository 的 projection 与 SQL 边界。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from pokeop.application.repositories.battle_inference import MechanismSupportStatus
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type
from pokeop.persistence.battle_inference import repository as repository_module


@dataclass(frozen=True)
class _QueryResult:
    """提供 repository 单元测试需要的 ``first`` 和 ``all`` 查询结果。"""

    first_row: SimpleNamespace | None = None
    all_rows: tuple[SimpleNamespace, ...] = ()

    def first(self) -> SimpleNamespace | None:
        """返回当前查询预置的第一行。

        Returns:
            构造结果时提供的行对象；没有行时返回 None。
        """
        return self.first_row

    def all(self) -> list[SimpleNamespace]:
        """返回当前查询预置的全部行。

        Returns:
            新建列表，避免 repository 或断言意外修改共享测试元组。
        """
        return list(self.all_rows)


class _FakeDatabase:
    """按顺序返回预置结果并记录 SQL 文本与绑定参数的数据库替身。"""

    def __init__(self, responses: tuple[_QueryResult, ...]) -> None:
        """保存每次 ``execute`` 应消费的结果队列。

        Args:
            responses: 按 repository 实际查询顺序排列的结果对象。
        """
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: dict[str, Any]) -> _QueryResult:
        """记录规范化 SQL 和参数，并返回下一项预置结果。

        Args:
            statement: SQLAlchemy ``TextClause`` 或等价可转字符串对象。
            params: repository 传给数据库的绑定参数。

        Returns:
            当前调用对应的预置 ``_QueryResult``。

        Raises:
            AssertionError: repository 执行次数超过测试预置结果数量时抛出。
        """
        self.calls.append((" ".join(str(statement).split()), dict(params)))
        if not self._responses:
            raise AssertionError("unexpected database query")
        return self._responses.pop(0)


def _row(**values: Any) -> SimpleNamespace:
    """构造暴露 SQLAlchemy ``Row._mapping`` 接口的轻量测试行。

    Args:
        values: repository 映射函数需要读取的字段和值。

    Returns:
        ``_mapping`` 指向字段字典的 ``SimpleNamespace``。
    """
    return SimpleNamespace(_mapping=values)


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    database: _FakeDatabase,
) -> None:
    """把 repository 数据库 runtime 替换为当前测试的内存替身。

    Args:
        monkeypatch: pytest 属性替换工具。
        database: 应在事务作用域内返回的 fake database。
    """
    db_kind = SimpleNamespace(POSTGRES="postgres")
    monkeypatch.setattr(
        repository_module,
        "_db_runtime",
        lambda: (db_kind, lambda _kind: nullcontext(database)),
    )


def _pokemon_row(
    *,
    pokemon_id: int,
    identifier: str,
    display_name: str,
    primary_type: tuple[int, str, str],
    secondary_type: tuple[int, str, str] | None,
    stats: tuple[int, int, int, int, int, int],
) -> SimpleNamespace:
    """构造 pokemon_profile_mv 查询所需的完整 Pokémon 行。

    Args:
        pokemon_id: Pokémon 与物种测试 ID。
        identifier: Pokémon 和物种稳定 identifier。
        display_name: 当前语言展示名称。
        primary_type: 第一属性的 ID、identifier 和展示名称。
        secondary_type: 可选第二属性三元组；单属性 Pokémon 使用 None。
        stats: HP、攻击、防御、特攻、特防和速度六项种族值。

    Returns:
        可被完整 profile 映射逻辑消费的测试行。
    """
    secondary = secondary_type or (None, None, None)
    return _row(
        pokemon_id=pokemon_id,
        pokemon_identifier=identifier,
        pokemon_name=display_name,
        species_id=pokemon_id,
        species_identifier=identifier,
        form_identifier=identifier,
        is_default_form=True,
        is_battle_only_form=False,
        is_mega_form=False,
        type_1_id=primary_type[0],
        type_1_identifier=primary_type[1],
        type_1_name=primary_type[2],
        type_2_id=secondary[0],
        type_2_identifier=secondary[1],
        type_2_name=secondary[2],
        hp=stats[0],
        attack=stats[1],
        defense=stats[2],
        special_attack=stats[3],
        special_defense=stats[4],
        speed=stats[5],
        can_evolve=False,
    )


def _ability_row(
    *,
    ability_id: int,
    identifier: str,
    display_name: str,
    slot: int,
    is_hidden: bool,
) -> SimpleNamespace:
    """构造已完成历史特性还原的查询结果行。

    Args:
        ability_id: PokeAPI 特性 ID。
        identifier: 特性稳定 identifier。
        display_name: 当前规则集语言展示名称。
        slot: PokeAPI 特性槽位。
        is_hidden: 是否为隐藏特性。

    Returns:
        可被特性 projection 映射函数消费的测试行。
    """
    return _row(
        ability_id=ability_id,
        ability_identifier=identifier,
        ability_name=display_name,
        slot=slot,
        is_hidden=is_hidden,
    )


def _move_row(
    *,
    move_id: int,
    identifier: str,
    display_name: str,
    move_type: tuple[int, str, str],
    power: int | None,
    pp: int,
    accuracy: int | None,
    priority: int,
    effect_id: int | None,
    effect_chance: int | None,
) -> SimpleNamespace:
    """构造 move_profile_mv 与 learnset 联合查询的完整招式行。

    Args:
        move_id: PokeAPI 招式 ID。
        identifier: 招式稳定 identifier。
        display_name: 当前规则集语言展示名称。
        move_type: 属性 ID、identifier 和展示名称。
        power: 当前 version group 基础威力。
        pp: 当前 version group 基础最大 PP。
        accuracy: 百分制命中率或 None。
        priority: 当前 version group 优先级。
        effect_id: PokeAPI move effect ID。
        effect_chance: 百分制附加效果概率或 None。

    Returns:
        可被完整招式 projection 映射逻辑消费的测试行。
    """
    return _row(
        move_id=move_id,
        move_identifier=identifier,
        move_name=display_name,
        type_id=move_type[0],
        type_identifier=move_type[1],
        type_name=move_type[2],
        power=power,
        pp=pp,
        accuracy=accuracy,
        priority=priority,
        target_id=10,
        target_identifier="selected-pokemon",
        damage_class_identifier="physical",
        effect_id=effect_id,
        effect_chance=effect_chance,
    )


def _repository_for_profile(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pokemon: SimpleNamespace,
    abilities: tuple[SimpleNamespace, ...],
    moves: tuple[SimpleNamespace, ...],
) -> tuple[repository_module.MaterializedViewBattleInferenceRepository, _FakeDatabase]:
    """为一次完整 Pokémon profile 查询安装顺序化数据库结果。

    Args:
        monkeypatch: pytest 属性替换工具。
        pokemon: 第一条 profile 查询返回的单行。
        abilities: 第二条历史特性查询返回的全部行。
        moves: 第三条合法招式查询返回的全部行。

    Returns:
        新 repository 实例和可供检查 SQL/参数的 fake database。
    """
    database = _FakeDatabase(
        (
            _QueryResult(first_row=pokemon),
            _QueryResult(all_rows=abilities),
            _QueryResult(all_rows=moves),
        )
    )
    _install_runtime(monkeypatch, database)
    return repository_module.MaterializedViewBattleInferenceRepository(), database


def test_ruleset_context_requires_exact_ruleset_and_version_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    本场景为 ruleset_context_mv 提供 Pokemon Champion、generation 9 与 version group 25 的单行结果，
    然后调用 repository 的上下文入口。测试断言 projection 完整保留规则集名称、世代、版本组 ID 和稳定
    identifier，并检查 SQL 的 WHERE 条件同时包含 ruleset_id 与 version_group_id，绑定参数也必须与调用值
    完全一致。该场景防止后续实现为了方便只按 ruleset 或 generation 命中一行，从而把不同 learnset、
    machine 或 move changelog 时点的数据错误地组合进同一次 1v1 多回合推演配置。
    """
    database = _FakeDatabase(
        (
            _QueryResult(
                first_row=_row(
                    ruleset_id="pokemon-champion",
                    ruleset_name="Pokemon Champion",
                    generation_id=9,
                    version_group_id=25,
                    version_group_identifier="scarlet-violet",
                )
            ),
        )
    )
    _install_runtime(monkeypatch, database)

    context = (
        repository_module.MaterializedViewBattleInferenceRepository()
        .get_ruleset_context(
            ruleset_id="pokemon-champion",
            version_group_id=25,
        )
    )

    assert context is not None
    assert (
        context.ruleset_id,
        context.generation_id,
        context.version_group_id,
        context.version_group_identifier,
    ) == ("pokemon-champion", 9, 25, "scarlet-violet")
    sql, params = database.calls[0]
    assert "ruleset_id = :ruleset_id" in sql
    assert "version_group_id = :version_group_id" in sql
    assert params == {
        "ruleset_id": "pokemon-champion",
        "version_group_id": 25,
    }


def test_dragonite_profile_keeps_legal_abilities_and_complete_move_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    本场景模拟 Pokemon Champion version group 25 中的快龙读取结果，使用真实龙/飞行属性、六项种族值、
    精神力与多重鳞片，以及冰冻拳和劈瓦的 PokeAPI 战斗字段。测试断言两个合法特性都会进入 projection，
    即使当前并行分支尚未实现其中某个 effect 也只能显式标记覆盖状态，不能静默过滤；同时验证招式 PP、
    命中率、优先级、effect_id、effect_chance 和 target 均完整保留，且所有 SQL 都绑定同一 version group。
    """
    repository, database = _repository_for_profile(
        monkeypatch,
        pokemon=_pokemon_row(
            pokemon_id=149,
            identifier="dragonite",
            display_name="快龙",
            primary_type=(16, "dragon", "龙"),
            secondary_type=(3, "flying", "飞行"),
            stats=(91, 134, 95, 100, 100, 80),
        ),
        abilities=(
            _ability_row(
                ability_id=39,
                identifier="inner-focus",
                display_name="精神力",
                slot=1,
                is_hidden=False,
            ),
            _ability_row(
                ability_id=136,
                identifier="multiscale",
                display_name="多重鳞片",
                slot=3,
                is_hidden=True,
            ),
        ),
        moves=(
            _move_row(
                move_id=8,
                identifier="ice-punch",
                display_name="冰冻拳",
                move_type=(15, "ice", "冰"),
                power=75,
                pp=15,
                accuracy=100,
                priority=0,
                effect_id=6,
                effect_chance=10,
            ),
            _move_row(
                move_id=280,
                identifier="brick-break",
                display_name="劈瓦",
                move_type=(2, "fighting", "格斗"),
                power=75,
                pp=15,
                accuracy=100,
                priority=0,
                effect_id=187,
                effect_chance=None,
            ),
        ),
    )

    profile = repository.get_pokemon_profile(
        ruleset_id="pokemon-champion",
        version_group_id=25,
        pokemon_id=149,
    )

    assert profile is not None
    assert tuple(item.domain_type for item in profile.types) == (
        Type.DRAGON,
        Type.FLYING,
    )
    assert profile.base_stats == StatValues(
        hp=91,
        attack=134,
        defense=95,
        special_attack=100,
        special_defense=100,
        speed=80,
    )
    assert tuple(ability.identifier for ability in profile.abilities) == (
        "inner-focus",
        "multiscale",
    )
    assert all(
        ability.capability.status
        in {MechanismSupportStatus.SUPPORTED, MechanismSupportStatus.UNSUPPORTED}
        for ability in profile.abilities
    )
    moves = {move.identifier: move for move in profile.moves}
    assert (
        moves["ice-punch"].pp,
        moves["ice-punch"].accuracy,
        moves["ice-punch"].priority,
        moves["ice-punch"].effect_id,
        moves["ice-punch"].effect_chance,
        moves["ice-punch"].target_identifier,
    ) == (15, 100, 0, 6, 10, "selected-pokemon")
    assert moves["brick-break"].capability.status is MechanismSupportStatus.PARTIAL
    assert len(database.calls) == 3
    assert all(call[1]["version_group_id"] == 25 for call in database.calls)
    assert "pap.generation_id >= rc.generation_id" in database.calls[1][0]
    assert "mp.version_group_id = learnset.version_group_id" in database.calls[2][0]


def test_weavile_profile_exposes_fake_out_priority_and_all_legal_mechanics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    本场景模拟玛纽拉在相同规则轴下的完整读取，使用真实恶/冰属性、种族值、压迫感与顺手牵羊，
    并提供击掌奇袭、冰冻拳和劈瓦三项合法招式。断言击掌奇袭的 10 PP、100 命中、+3 优先级、
    effect 159 与 100% 效果概率完整存在，另外两个招式也不会因附加机制暂未完全支持而消失。
    该场景保护多回合合法行动生成器所需字段不再退化为 calculator 只读取威力、属性和分类的窄模型。
    """
    repository, _ = _repository_for_profile(
        monkeypatch,
        pokemon=_pokemon_row(
            pokemon_id=461,
            identifier="weavile",
            display_name="玛纽拉",
            primary_type=(17, "dark", "恶"),
            secondary_type=(15, "ice", "冰"),
            stats=(70, 120, 65, 45, 85, 125),
        ),
        abilities=(
            _ability_row(
                ability_id=46,
                identifier="pressure",
                display_name="压迫感",
                slot=1,
                is_hidden=False,
            ),
            _ability_row(
                ability_id=124,
                identifier="pickpocket",
                display_name="顺手牵羊",
                slot=3,
                is_hidden=True,
            ),
        ),
        moves=(
            _move_row(
                move_id=8,
                identifier="ice-punch",
                display_name="冰冻拳",
                move_type=(15, "ice", "冰"),
                power=75,
                pp=15,
                accuracy=100,
                priority=0,
                effect_id=6,
                effect_chance=10,
            ),
            _move_row(
                move_id=252,
                identifier="fake-out",
                display_name="击掌奇袭",
                move_type=(1, "normal", "一般"),
                power=40,
                pp=10,
                accuracy=100,
                priority=3,
                effect_id=159,
                effect_chance=100,
            ),
            _move_row(
                move_id=280,
                identifier="brick-break",
                display_name="劈瓦",
                move_type=(2, "fighting", "格斗"),
                power=75,
                pp=15,
                accuracy=100,
                priority=0,
                effect_id=187,
                effect_chance=None,
            ),
        ),
    )

    profile = repository.get_pokemon_profile(
        ruleset_id="pokemon-champion",
        version_group_id=25,
        pokemon_id=461,
    )

    assert profile is not None
    assert tuple(item.domain_type for item in profile.types) == (Type.DARK, Type.ICE)
    assert tuple(ability.identifier for ability in profile.abilities) == (
        "pressure",
        "pickpocket",
    )
    moves = {move.identifier: move for move in profile.moves}
    assert set(moves) == {"ice-punch", "fake-out", "brick-break"}
    assert (
        moves["fake-out"].pp,
        moves["fake-out"].accuracy,
        moves["fake-out"].priority,
        moves["fake-out"].effect_id,
        moves["fake-out"].effect_chance,
    ) == (10, 100, 3, 159, 100)
    assert moves["fake-out"].capability.status is MechanismSupportStatus.PARTIAL


def test_karate_chop_type_follows_move_changelog_projection_for_each_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    PokeAPI 的 Karate Chop 在 version group 3 发生属性变化，早期读取应得到一般属性，现代读取应得到格斗属性。
    本测试分别让 ``move_profile_mv`` 替身返回 changelog 覆盖后的旧值与当前值，并以 version_group 1 和 25
    调用同一 repository。断言 move_id 保持稳定而 domain Type 随版本变化，同时检查 learnset 与 move profile
    必须通过 ruleset_id、version_group_id 和 move_id 联合连接，防止 repository 只按 generation 或 move_id
    读取当前值，从而使已经在物化视图中还原的历史语义在 application projection 边界再次丢失。
    """
    common_pokemon = _pokemon_row(
        pokemon_id=67,
        identifier="machoke",
        display_name="豪力",
        primary_type=(2, "fighting", "格斗"),
        secondary_type=None,
        stats=(80, 100, 70, 50, 60, 45),
    )
    common_abilities = (
        _ability_row(
            ability_id=62,
            identifier="guts",
            display_name="毅力",
            slot=1,
            is_hidden=False,
        ),
    )
    old_repository, old_database = _repository_for_profile(
        monkeypatch,
        pokemon=common_pokemon,
        abilities=common_abilities,
        moves=(
            _move_row(
                move_id=2,
                identifier="karate-chop",
                display_name="空手劈",
                move_type=(1, "normal", "一般"),
                power=50,
                pp=25,
                accuracy=100,
                priority=0,
                effect_id=44,
                effect_chance=None,
            ),
        ),
    )
    old_profile = old_repository.get_pokemon_profile(
        ruleset_id="legacy-test",
        version_group_id=1,
        pokemon_id=67,
    )

    current_repository, current_database = _repository_for_profile(
        monkeypatch,
        pokemon=common_pokemon,
        abilities=common_abilities,
        moves=(
            _move_row(
                move_id=2,
                identifier="karate-chop",
                display_name="空手劈",
                move_type=(2, "fighting", "格斗"),
                power=50,
                pp=25,
                accuracy=100,
                priority=0,
                effect_id=44,
                effect_chance=None,
            ),
        ),
    )
    current_profile = current_repository.get_pokemon_profile(
        ruleset_id="pokemon-champion",
        version_group_id=25,
        pokemon_id=67,
    )

    assert old_profile is not None
    assert current_profile is not None
    assert old_profile.moves[0].move_id == current_profile.moves[0].move_id == 2
    assert old_profile.moves[0].type.domain_type is Type.NORMAL
    assert current_profile.moves[0].type.domain_type is Type.FIGHTING
    for database, expected_version_group in (
        (old_database, 1),
        (current_database, 25),
    ):
        move_sql, params = database.calls[2]
        assert params["version_group_id"] == expected_version_group
        assert "mp.ruleset_id = learnset.ruleset_id" in move_sql
        assert "mp.version_group_id = learnset.version_group_id" in move_sql
        assert "mp.move_id = learnset.move_id" in move_sql


def test_item_candidates_are_controlled_generation_aware_and_include_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    本场景模拟精确规则轴存在，并返回讲究头带与生命宝珠两个受控道具。repository 必须在结果首位合成显式
    ``none`` 候选，而不是用空值或 UNKNOWN 混淆“不携带道具”；真实道具需要保留稳定 PokeAPI identifier、
    展示名称和可交给 factory 的 effect identifier。测试同时检查 SQL 仅查询 DamageItem 声明的受控集合，
    并通过 ``item_game_indices.generation_id <= ruleset generation`` 排除尚未在目标世代出现的未来道具。
    """
    database = _FakeDatabase(
        (
            _QueryResult(first_row=_row(exists=1)),
            _QueryResult(
                all_rows=(
                    _row(
                        item_id=220,
                        item_identifier="choice-band",
                        item_name="讲究头带",
                    ),
                    _row(
                        item_id=270,
                        item_identifier="life-orb",
                        item_name="生命宝珠",
                    ),
                )
            ),
        )
    )
    _install_runtime(monkeypatch, database)

    items = repository_module.MaterializedViewBattleInferenceRepository().list_item_candidates(
        ruleset_id="pokemon-champion",
        version_group_id=25,
    )

    assert tuple(item.identifier for item in items) == (
        "none",
        "choice-band",
        "life-orb",
    )
    assert items[0].item_id is None
    assert items[0].capability.status is MechanismSupportStatus.NO_EFFECT
    assert items[1].effect_identifier == "choice-band"
    item_sql, params = database.calls[1]
    assert "item_generation.generation_id <= rc.generation_id" in item_sql
    assert set(params["item_identifiers"]) == {
        item.value.replace("_", "-")
        for item in repository_module.DamageItem
        if item is not repository_module.DamageItem.UNKNOWN
    }
