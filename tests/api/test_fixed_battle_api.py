"""验证组合预览和固定配置精确推演的 HTTP 合同。"""

from __future__ import annotations

from pokeop.api.routers.fixed_battle import router
from pokeop.api.schemas.fixed_battle import (
    FixedBattleSideRequest,
    move_set_combinations_response,
)
from pokeop.application.use_cases.fixed_battle_workflow import (
    EnumerateMoveSetCombinationsResult,
    MoveSetOption,
    MoveSetSideResult,
)


def test_fixed_battle_routes_share_the_inference_resource_prefix() -> None:
    """路由模块必须同时暴露组合预览、异步任务和兼容同步入口。

    固定配置页面的默认产品链路已经从同步 HTTP 求解切换为后台任务，因此 router
    需要保留旧 summary/graph 入口作为兼容能力，同时新增不会执行 solver 的任务创建
    入口。该测试只检查模块自身路径，避免依赖真实数据库或 worker。
    """
    paths = {route.path for route in router.routes}

    assert "/move-set-combinations" in paths
    assert "/fixed-one-on-one-jobs" in paths
    assert "/fixed-one-on-one" in paths
    assert "/fixed-one-on-one/graph" in paths


def test_combination_response_keeps_side_lists_separate() -> None:
    """响应只返回左右技能组和理论乘积，不物化配置对执行记录。"""
    attacker = MoveSetSideResult(
        pokemon_id=149,
        pokemon_name="dragonite",
        candidate_count=5,
        move_set_count=2,
        move_sets=(
            MoveSetOption(
                "move-set:1,2,3,4",
                (1, 2, 3, 4),
                ("a", "b", "c", "d"),
            ),
            MoveSetOption(
                "move-set:1,2,3,5",
                (1, 2, 3, 5),
                ("a", "b", "c", "e"),
            ),
        ),
    )
    defender = MoveSetSideResult(
        pokemon_id=461,
        pokemon_name="weavile",
        candidate_count=4,
        move_set_count=1,
        move_sets=(
            MoveSetOption(
                "move-set:11,12,13,14",
                (11, 12, 13, 14),
                ("w", "x", "y", "z"),
            ),
        ),
    )

    response = move_set_combinations_response(
        EnumerateMoveSetCombinationsResult(
            ruleset_id="pokemon-champion",
            version_group_id=25,
            calculation_revision="battle-inference.summary-exploration.v2",
            attacker=attacker,
            defender=defender,
            configuration_pair_count=2,
        )
    )

    assert response.configuration_pair_count == 2
    assert len(response.attacker.move_sets) == 2
    assert len(response.defender.move_sets) == 1
    assert not hasattr(response, "job_id")


def test_http_side_conversion_rejects_form_id_that_solver_cannot_preserve() -> None:
    """API 不得接受随后会在固定推演命令中被静默丢弃的 form_id。"""
    request = FixedBattleSideRequest(
        pokemon_id=149,
        form_id=10001,
        level=50,
        stat_profile_id="max_atk_plus",
        ability_identifier="multiscale",
    )

    try:
        request.to_application()
    except ValueError as error:
        assert "form-specific pokemon_id" in str(error)
    else:  # pragma: no cover - 明确保护静默丢字段回归。
        raise AssertionError("form_id should have been rejected")
