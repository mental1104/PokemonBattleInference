"""验证独立推演页面的 HTTP 输入转换与真实 FastAPI 路由注册。"""

from pokeop.api.routers.inference import _command
from pokeop.api.schemas.inference import DragoniteWeavileJourneyRequest
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
)
from pokeop.main import create_app


def test_dragonite_weavile_pressure_plan_maps_to_stable_application_command() -> None:
    """验证页面选择只被转换为稳定 application command。

    HTTP 层不能自行计算伤害、查询 SQL 或解释状态图。测试提交精神力与击掌奇袭施压
    方案，断言双方固定 Pokémon ID、招式 ID、特性 identifier、能力预设及行动策略均被
    准确映射，防止前端展示文案或数组顺序变化时悄悄改写业务语义。
    """
    command = _command(
        DragoniteWeavileJourneyRequest(
            dragonite_ability="inner-focus",
            weavile_plan="fake-out-pressure",
            dragonite_stat_preset="max_atk_neutral",
            weavile_stat_preset="max_atk_plus",
        )
    )

    assert command.attacker.pokemon_id == 149
    assert command.attacker.move_ids == (280,)
    assert command.attacker.ability_identifier == "inner-focus"
    assert command.attacker.stat_preset_key == "max_atk_neutral"
    assert command.defender.pokemon_id == 461
    assert command.defender.move_ids == (8, 252)
    assert command.defender.ability_identifier == "pressure"
    assert command.attacker_policy is BattleActionPolicyKind.FIRST_LEGAL
    assert command.defender_policy is BattleActionPolicyKind.UNIFORM_RANDOM


def test_inference_router_is_registered_by_application_factory() -> None:
    """验证动态路由扫描器实际注册多回合推演 POST 路径。

    `pokeop.main.register_routes` 只识别模块级 `router` 变量。该测试必须从 `create_app()`
    构建完整 FastAPI 应用并检查最终路由表，避免仅导入 endpoint 或测试 command 映射时
    漏掉真实 HTTP 接线问题。
    """
    application = create_app()
    route = next(
        (
            candidate
            for candidate in application.routes
            if candidate.path == "/v1/inference/dragonite-vs-weavile"
        ),
        None,
    )

    assert route is not None
    assert "POST" in route.methods
