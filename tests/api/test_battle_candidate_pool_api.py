"""验证真实候选池路由注册与紧凑 HTTP 投影。"""

from __future__ import annotations

from types import SimpleNamespace

from pokeop.api.routers.configuration_jobs import router
from pokeop.api.schemas.battle_candidate_pool import battle_candidate_pool_response


def test_candidate_pool_route_is_registered_under_configuration_router() -> None:
    """候选池入口必须与任务接口共享 `/v1/inference` router。"""
    assert "/candidate-pools/{pokemon_id}" in {route.path for route in router.routes}


def test_candidate_pool_response_keeps_disabled_mechanism_details() -> None:
    """PARTIAL/UNSUPPORTED 候选必须可见并携带结构化禁用原因。"""
    admission = SimpleNamespace(
        status=SimpleNamespace(value="partial"),
        selectable=False,
        reason="secondary effect is not implemented",
        disabled_reason="secondary effect is not implemented",
        missing_mechanism_identifiers=("move-effect:paralysis",),
    )
    move = SimpleNamespace(
        move_id=85,
        identifier="thunderbolt",
        display_name="十万伏特",
        type=SimpleNamespace(identifier="electric", display_name="电"),
        category=SimpleNamespace(value="special"),
        power=90,
    )
    pool = SimpleNamespace(
        pokemon_id=25,
        ruleset_id="pokemon-champion",
        version_group_id=25,
        calculation_revision="battle-inference.summary-exploration.v2",
        moves=(SimpleNamespace(move=move, admission=admission),),
    )

    response = battle_candidate_pool_response(pool)

    assert response.moves[0].move_id == 85
    assert response.moves[0].admission.status == "partial"
    assert response.moves[0].admission.selectable is False
    assert response.moves[0].admission.missing_mechanism_identifiers == [
        "move-effect:paralysis"
    ]
