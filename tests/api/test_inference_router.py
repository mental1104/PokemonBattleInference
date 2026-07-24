"""验证独立推演页面的 HTTP 输入只负责转换为 application command。"""

from pokeop.api.routers.inference import _command
from pokeop.api.schemas.inference import DragoniteWeavileJourneyRequest
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
)


def test_dragonite_weavile_pressure_plan_maps_to_stable_application_command() -> None:
    """
    HTTP 层必须只把页面选择转换为稳定 application command，不能在路由中自行计算伤害、查询 SQL 或解释状态图。测试提交精神力与击掌奇袭施压方案，断言快龙和玛纽拉的固定 Pokémon ID、招式 ID、特性 identifier、能力预设以及双方行动策略均被准确映射；尤其要求玛纽拉两招使用 uniform-random，而快龙仍使用 first-legal。这样可以防止前端展示文案或数组顺序变化时悄悄改写业务语义，也证明独立页面与顶层用例之间存在明确边界。
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
