"""验证胜利路径 HTTP 路由、响应合同和查询冲突映射。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from pokeop import main as main_module
from pokeop.api.routers import winning_paths
from pokeop.api.schemas.winning_paths import ListWinningPathGroupsRequest
from tests.application.test_winning_paths import _acyclic_graph
from tests.application.use_cases.battle_exploration_test_helpers import (
    GRAPH_ID,
    REVISION,
    stored_store,
)


def test_winning_path_route_is_registered() -> None:
    """验证动态路由扫描器注册独立的胜利路径 POST 入口。"""
    application = main_module.create_app()
    route = next(
        item
        for item in application.routes
        if item.path == "/v1/winning_paths/graphs/{graph_id}"
    )

    assert "POST" in route.methods


def test_router_returns_configuration_top_k_and_prefix_tree() -> None:
    """验证 HTTP DTO 保留配置、精确概率、代表 cursor 与递归前缀树。"""
    store = stored_store(_acyclic_graph())

    response = asyncio.run(
        winning_paths.list_winning_path_groups(
            GRAPH_ID,
            ListWinningPathGroupsRequest(
                calculation_revision=REVISION,
                winner="attacker",
                limit=2,
            ),
            store,
        )
    )

    assert response.configuration.attacker.move_ids
    assert len(response.path_groups) == 2
    assert response.path_groups[0].probability.numerator == "1"
    assert response.path_groups[0].probability.denominator == "2"
    assert response.path_groups[0].representative_path[0].source_node_id == 0
    assert response.prefix_tree.children
    assert response.next_cursor is not None
    assert response.has_more is True


def test_router_maps_malformed_cursor_to_http_409() -> None:
    """验证无法解码或跨查询复用的分页游标返回稳定冲突错误。"""
    store = stored_store(_acyclic_graph())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            winning_paths.list_winning_path_groups(
                GRAPH_ID,
                ListWinningPathGroupsRequest(
                    calculation_revision=REVISION,
                    winner="attacker",
                    cursor="not-a-valid-cursor",
                ),
                store,
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "winning_path_query_conflict"
