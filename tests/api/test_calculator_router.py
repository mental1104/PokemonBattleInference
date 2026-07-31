from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from pokeop.api.routers import calculator
from pokeop.api.schemas.calculator_abilities import (
    BattleStatStagesInput,
    CalculateDamageWithAbilitiesRequest,
    CalculatorPokemonWithAbilityInput,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculateCatalogDamageWithAbilitiesUseCase,
)
from pokeop.domain.configuration_presets import (
    PokemonBindingKind,
    StatConfiguration,
    StatConfigurationRole,
    StatConfigurationSource,
    StatSpread,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    BULLET_PUNCH_ID,
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import (
    FakeCalculatorAbilityRepository,
)


def _request() -> CalculateDamageWithAbilitiesRequest:
    """创建包含双方必选特性和默认零级能力变化的 API 请求。

    Returns:
        巨钳螳螂使用子弹拳攻击仙子伊布的 Pydantic 请求模型。
    """
    return CalculateDamageWithAbilitiesRequest(
        ruleset_id="pokemon-champion",
        attacker=CalculatorPokemonWithAbilityInput(
            pokemon_id=SCIZOR_ID,
            level=50,
            stat_preset="max_atk_neutral",
            ability_identifier="swarm",
        ),
        defender=CalculatorPokemonWithAbilityInput(
            pokemon_id=SYLVEON_ID,
            level=50,
            stat_preset="max_hp",
            ability_identifier="cute-charm",
        ),
        move_id=BULLET_PUNCH_ID,
    )


def _use_case(*, allow_move: bool = True) -> CalculateCatalogDamageWithAbilitiesUseCase:
    """创建 API 测试使用的特性感知 calculator use case。

    Args:
        allow_move: fake catalog repository 是否允许巨钳螳螂使用子弹拳。

    Returns:
        注入 catalog 与 ability fake repository 的 use case。
    """
    return CalculateCatalogDamageWithAbilitiesUseCase(
        FakeCalculatorRepository(allow_move=allow_move),
        FakeCalculatorAbilityRepository(),
    )


@pytest.mark.anyio
async def test_calculator_damage_api_returns_frontend_ready_result():
    """
    通过 router 函数执行巨钳螳螂、子弹拳、仙子伊布的基础伤害计算。双方选择数据库合法但尚未实现的
    虫之预感和迷人之躯，因此应按无特性基线返回前端首屏需要的名称、有效能力、伤害区间、KO 字段和
    机制范围说明。该测试同时保护 HTTP 请求必须携带 ability_identifier，且未实现特性不会让合法请求失败。
    """
    response = await calculator.calculate_damage(
        _request(),
        use_case=_use_case(),
    )

    payload = response.model_dump()
    assert payload["ruleset_id"] == "pokemon-champion"
    assert payload["attacker"]["display_name"] == "巨钳螳螂"
    assert payload["attacker"]["effective_attack"] == 182
    assert payload["defender"]["display_name"] == "仙子伊布"
    assert payload["defender"]["effective_hp"] == 202
    assert payload["defender"]["effective_defense"] == 85
    assert payload["move"]["display_name"] == "子弹拳"
    assert payload["move"]["type"] == "steel"
    assert payload["damage"]["min"] == 99
    assert payload["damage"]["max"] == 117
    assert len(payload["damage"]["rolls"]) == 16
    assert "ohko_probability" in payload["ko"]
    assert "动态威力招式" in payload["scope"]["excluded"]
    assert len(payload["warnings"]) == 2


@pytest.mark.anyio
async def test_calculator_damage_api_returns_400_for_illegal_move_combination():
    """
    当 application 层拒绝非法宝可梦和招式组合时，router 必须返回 400 与稳定错误文本，而不是把异常
    泄漏成 500。请求中的双方特性仍然合法且完整，确保失败原因只来自 learnset 校验，防止新增特性链路
    掩盖旧有服务端可信边界，也保证前端能把过期招式选择展示为可恢复的表单错误。
    """
    with pytest.raises(HTTPException) as exc_info:
        await calculator.calculate_damage(
            _request(),
            use_case=_use_case(allow_move=False),
        )

    assert exc_info.value.status_code == 400
    assert "move is not available" in str(exc_info.value.detail)


@pytest.mark.anyio
async def test_calculator_damage_api_uses_stat_configuration_snapshot():
    """
    配置预设提交到计算器时不能只保存 CRUD 数据或显示名称。测试把攻击方配置编码为 snapshot stat_preset，
    同时保留必选且合法的虫之预感，断言 application 展开 adamant nature、252 Attack EV 和 31 IV 后，
    巨钳螳螂实际攻击从满攻中性 182 提升到极限物攻 200，证明特性接入没有破坏原配置快照语义。
    """
    request = _request()
    snapshot = StatConfiguration(
        key="custom-scizor-atk",
        source=StatConfigurationSource.CUSTOM,
        name="Custom Scizor Attack",
        nature_id="adamant",
        evs=StatSpread.evs(attack=252),
        ivs=StatSpread.perfect_ivs(),
        role=StatConfigurationRole.ATTACKER,
        binding_kind=PokemonBindingKind.GLOBAL,
    ).snapshot_profile_id()
    request.attacker.stat_preset = snapshot

    response = await calculator.calculate_damage(
        request,
        use_case=_use_case(),
    )

    assert response.attacker.effective_attack == 200
    assert response.damage.min > 99


@pytest.mark.anyio
async def test_calculator_damage_api_passes_attacker_item_identifier():
    """
    请求同时携带攻击方道具和双方必选特性时，router 必须把各自字段映射到正确 command，不能因为新增
    ability_identifier 而覆盖或遗漏 item_identifier。这里选择未实现特性保持无特性基线，再用生命宝珠验证
    伤害上升且 modifier trace 出现 item:life_orb，从而保护两类效果来源可以独立组合。
    """
    request = _request()
    request.attacker.item_identifier = "life-orb"

    response = await calculator.calculate_damage(
        request,
        use_case=_use_case(),
    )

    assert response.damage.min > 99
    assert any(item.key == "item:life_orb" for item in response.modifiers)


@pytest.mark.anyio
async def test_calculator_damage_api_applies_battle_stat_stages():
    """
    前端在宝可梦摘要红框中选择攻击方攻击加二、防守方防御加一后，HTTP schema 必须保留七项字段并由
    router 转换为显式 StatStages，而不是只把它们作为界面状态。application 应让巨钳螳螂有效攻击从
    一百八十二变成三百六十四，让仙子伊布有效防御从八十五按三比二向下取整为一百二十七；配置基础
    stats 仍维持原值。该测试同时断言伤害高于基线，保护 schema、router、command 和 domain 数值链路
    完整贯通，避免字段名在 special_attack、evasion 等蛇形命名转换中丢失或错位。
    """
    request = _request()
    request.attacker.stat_stages = BattleStatStagesInput(attack=2)
    request.defender.stat_stages = BattleStatStagesInput(defense=1)

    response = await calculator.calculate_damage(
        request,
        use_case=_use_case(),
    )

    assert response.attacker.stats["attack"] == 182
    assert response.attacker.effective_attack == 364
    assert response.defender.stats["defense"] == 85
    assert response.defender.effective_defense == 127
    assert response.damage.min > 99
    assert "攻击/防御/特攻/特防能力等级" in response.scope.included


def test_calculator_stat_stage_schema_rejects_values_outside_six_levels() -> None:
    """
    战斗能力等级只能在负六到正六之间，前端固定枚举不能成为唯一可信边界。测试直接构造攻击加七和回避
    减七的 schema 输入，要求 Pydantic 在进入 router 与 application 之前就拒绝，同时确认布尔值不能借助
    Python 中 bool 继承 int 的规则伪装成一级。该场景保护手工 HTTP 请求、旧客户端和未来批量导入入口，
    防止非法等级到达倍率公式后产生超出游戏规则的结果；合法边界正六与负六仍应正常保留，保证完整枚举
    范围不会因为严格类型校验而被误伤。
    """
    assert BattleStatStagesInput(attack=6, evasion=-6).attack == 6

    with pytest.raises(ValidationError):
        BattleStatStagesInput(attack=7)
    with pytest.raises(ValidationError):
        BattleStatStagesInput(evasion=-7)
    with pytest.raises(ValidationError):
        BattleStatStagesInput(speed=True)


@pytest.mark.anyio
async def test_calculator_items_api_returns_database_mapping_with_sprite_url():
    """
    道具枚举 API 必须继续暴露数据库 ID、PokeAPI identifier、展示名和项目内图标 URL。新增 Pokémon
    特性 endpoint 与新的 damage request 不能改变既有道具响应合同；显式不携带道具仍无 sprite，生命宝珠
    仍映射稳定 effect_identifier 和代理图片路径，避免前端能力选择改造意外破坏道具组件。
    """
    response = await calculator.list_battle_item_options(
        ruleset_id="pokemon-champion",
        repository=FakeCalculatorRepository(),
    )

    assert response[0].identifier == "none"
    assert response[0].sprite_url is None
    assert response[1].item_id == 247
    assert response[1].identifier == "life-orb"
    assert response[1].effect_identifier == "life-orb"
    assert response[1].sprite_url == "/api/v1/assets/items/life-orb/sprite"


@pytest.mark.anyio
async def test_calculator_abilities_api_marks_implementation_status():
    """
    特性枚举 API 必须返回当前 Pokémon 的全部合法候选，而不是只返回 domain 已实现项。巨钳螳螂的虫之预感
    应保留并标记 implemented=false，技术高手应标记 true，同时槽位和隐藏特性信息保持不丢失。该测试保护
    前端能够展示完整真实选择空间，并用禁止样式提示能力缺口，而不是通过过滤列表制造错误的宝可梦数据认知。
    """
    response = await calculator.list_pokemon_ability_options(
        pokemon_id=SCIZOR_ID,
        ruleset_id="pokemon-champion",
        repository=FakeCalculatorAbilityRepository(),
    )

    assert [item.identifier for item in response] == ["swarm", "technician"]
    assert response[0].implemented is False
    assert response[1].implemented is True
    assert response[1].slot == 2
