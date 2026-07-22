from __future__ import annotations

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculateCatalogDamageCommand,
    CalculateCatalogDamageUseCase,
    CalculateCatalogPokemonCommand,
    CalculatorInputError,
    CalculatorMoveProfile,
    CalculatorMoveSearchResult,
    CalculatorPokemonProfile,
    CalculatorPokemonSearchResult,
    CalculatorRulesetContext,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


SCIZOR_ID = 212
SYLVEON_ID = 700
BULLET_PUNCH_ID = 418


class FakeCalculatorRepository:
    """用于 application 测试的内存 repository。

    它模拟 calculator 需要的最小物化视图读取结果，测试重点放在 use case 是否校验
    ruleset/pokemon/move 组合并正确调用 domain 伤害计算。
    """

    def __init__(self, *, allow_move: bool = True) -> None:
        """配置 fake repository 是否允许攻击方使用子弹拳。"""
        self._allow_move = allow_move

    def get_ruleset_context(self, ruleset_id: str) -> CalculatorRulesetContext | None:
        """返回固定的 Pokemon Champion 规则集上下文。"""
        if ruleset_id != "pokemon-champion":
            return None
        return CalculatorRulesetContext(
            ruleset_id="pokemon-champion",
            ruleset_name="Pokemon Champion",
            generation_id=9,
            version_group_id=25,
            version_group_identifier="scarlet-violet",
        )

    def search_pokemon(
        self,
        *,
        ruleset_id: str,
        query: str,
        limit: int,
    ) -> tuple[CalculatorPokemonSearchResult, ...]:
        """返回测试不依赖的空搜索结果。"""
        return ()

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
    ) -> CalculatorPokemonProfile | None:
        """按测试场景返回巨钳螳螂或仙子伊布资料。"""
        if ruleset_id != "pokemon-champion":
            return None
        if pokemon_id == SCIZOR_ID:
            return CalculatorPokemonProfile(
                pokemon_id=SCIZOR_ID,
                identifier="scizor",
                display_name="巨钳螳螂",
                form_identifier="scizor",
                types=(Type.BUG, Type.STEEL),
                type_names=("虫", "钢"),
                base_stats=StatValues(
                    hp=70,
                    attack=130,
                    defense=100,
                    special_attack=55,
                    special_defense=80,
                    speed=65,
                ),
            )
        if pokemon_id == SYLVEON_ID:
            return CalculatorPokemonProfile(
                pokemon_id=SYLVEON_ID,
                identifier="sylveon",
                display_name="仙子伊布",
                form_identifier="sylveon",
                types=(Type.FAIRY,),
                type_names=("妖精",),
                base_stats=StatValues(
                    hp=95,
                    attack=65,
                    defense=65,
                    special_attack=110,
                    special_defense=130,
                    speed=60,
                ),
            )
        return None

    def list_calculable_moves(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        query: str,
        limit: int,
    ) -> tuple[CalculatorMoveSearchResult, ...]:
        """返回测试不依赖的空招式列表。"""
        return ()

    def get_move_profile(
        self,
        *,
        ruleset_id: str,
        move_id: int,
    ) -> CalculatorMoveProfile | None:
        """按测试场景返回子弹拳资料。"""
        if ruleset_id != "pokemon-champion" or move_id != BULLET_PUNCH_ID:
            return None
        return CalculatorMoveProfile(
            move_id=BULLET_PUNCH_ID,
            identifier="bullet-punch",
            display_name="子弹拳",
            type=Type.STEEL,
            type_name="钢",
            category=MoveCategory.PHYSICAL,
            power=40,
        )

    def pokemon_can_use_move(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        move_id: int,
    ) -> bool:
        """返回攻击方是否能在 fake ruleset 下使用子弹拳。"""
        return (
            self._allow_move
            and ruleset_id == "pokemon-champion"
            and pokemon_id == SCIZOR_ID
            and move_id == BULLET_PUNCH_ID
        )


def _command() -> CalculateCatalogDamageCommand:
    """创建固定的巨钳螳螂子弹拳攻击仙子伊布计算命令。"""
    return CalculateCatalogDamageCommand(
        ruleset_id="pokemon-champion",
        attacker=CalculateCatalogPokemonCommand(
            pokemon_id=SCIZOR_ID,
            level=50,
            stat_preset="max_atk_neutral",
        ),
        defender=CalculateCatalogPokemonCommand(
            pokemon_id=SYLVEON_ID,
            level=50,
            stat_preset="max_hp",
        ),
        move_id=BULLET_PUNCH_ID,
    )


def test_catalog_damage_use_case_loads_profiles_and_calculates_real_damage():
    """
    使用 fake repository 模拟物化视图读取，验证 catalog use case 能从 ID 输入一路组装
    domain 快照并得到真实伤害。场景固定为 50 级满攻巨钳螳螂使用子弹拳攻击满 HP
    仙子伊布，预期能力值、99-117 伤害区间、STAB/属性克制/随机修正都与底层 domain
    单元测试保持一致。这个测试保护的是前端不得提交种族值、招式威力和属性等派生资料。
    """
    result = CalculateCatalogDamageUseCase(FakeCalculatorRepository()).execute(_command())

    assert result.attacker.display_name == "巨钳螳螂"
    assert result.attacker.effective_attack == 182
    assert result.defender.display_name == "仙子伊布"
    assert result.defender.effective_hp == 202
    assert result.defender.effective_defense == 85
    assert result.move.display_name == "子弹拳"
    assert (result.damage.min_damage, result.damage.max_damage) == (99, 117)
    assert result.damage.rolls == (
        99,
        100,
        101,
        102,
        104,
        105,
        106,
        107,
        108,
        109,
        111,
        112,
        113,
        114,
        115,
        117,
    )
    assert result.ko_chance.ohko_chance == 0
    assert 0 < result.ko_chance.two_hit_ko_chance < 1
    assert {modifier.key for modifier in result.damage.applied_modifiers} == {
        "stab",
        "type_effectiveness",
        "random",
    }
    assert "动态威力招式" in result.scope.excluded


def test_catalog_damage_use_case_rejects_unavailable_move_for_attacker():
    """
    当 repository 判定招式不属于攻击方当前规则集 learnset 时，use case 必须拒绝计算。
    这个场景防止前端通过伪造 move_id 绕过选择器，把数据库中存在但攻击方不可用的招式
    送进 domain，从而产生对用户有误导性的伤害结果。
    """
    use_case = CalculateCatalogDamageUseCase(FakeCalculatorRepository(allow_move=False))

    try:
        use_case.execute(_command())
    except CalculatorInputError as exc:
        assert "move is not available" in str(exc)
    else:
        raise AssertionError("expected unavailable move to be rejected")
