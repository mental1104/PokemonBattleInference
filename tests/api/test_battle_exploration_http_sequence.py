"""通过真实 FastAPI ASGI 请求验证状态图可跨多个 HTTP 调用渐进探索。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI

from pokeop.api.routers import inference
from tests.api.test_battle_exploration_router import (
    _fixed_result,
    _journey_request,
    _test_app,
)
from tests.application.use_cases.battle_exploration_test_helpers import (
    REVISION,
    Executor,
)


@dataclass(frozen=True, slots=True)
class AsgiJsonResponse:
    """保存一次测试 ASGI 请求返回的状态码和 JSON body。"""

    status_code: int
    body: dict[str, Any]


async def _post_json(
    application: FastAPI,
    path: str,
    payload: dict[str, Any],
) -> AsgiJsonResponse:
    """不依赖外部 HTTP 客户端地向 FastAPI 发送一条 POST JSON 请求。

    Args:
        application: 已进入 lifespan 的 FastAPI 应用。
        path: 包含完整 `/v1` 前缀的目标路由路径。
        payload: 需要 UTF-8 JSON 编码的请求对象。

    Returns:
        汇总 ASGI response start/body 消息后的状态码和 JSON 对象。
    """
    request_body = json.dumps(payload).encode("utf-8")
    request_sent = False
    response_messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        """向应用提供一次完整 request body，随后报告客户端断开。"""
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        """记录 FastAPI 发出的 response start/body 消息。"""
        response_messages.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(request_body)).encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }
    await application(scope, receive, send)

    status_message = next(
        message
        for message in response_messages
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in response_messages
        if message["type"] == "http.response.body"
    )
    return AsgiJsonResponse(
        status_code=status_message["status"],
        body=json.loads(response_body.decode("utf-8")),
    )


def test_http_sequence_reads_same_graph_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 POST 推演、探索、展开、前进和回退共享同一 lifespan graph store。"""
    application = _test_app(monkeypatch)
    executor = Executor(_fixed_result())

    def inference_executor_override() -> Executor:
        """向真实 FastAPI dependency graph 注入固定图执行器。"""
        return executor

    application.dependency_overrides[inference._inference_executor] = (
        inference_executor_override
    )

    async def scenario() -> None:
        """按 Issue #64 验收顺序发送五类真实 ASGI POST 请求。"""
        async with application.router.lifespan_context(application):
            initial = await _post_json(
                application,
                "/v1/inference/dragonite-vs-weavile",
                _journey_request().model_dump(),
            )
            assert initial.status_code == 200
            graph_id = initial.body["exploration"]["graph_id"]
            assert graph_id
            assert initial.body["exploration"]["cursor"] == {"steps": []}
            assert initial.body["summary"]["win_probability"]["numerator"] == "3"

            root_request = {
                "calculation_revision": REVISION,
                "cursor": {"steps": []},
            }
            root = await _post_json(
                application,
                f"/v1/inference/graphs/{graph_id}/explore",
                root_request,
            )
            assert root.status_code == 200
            assert root.body["node"]["node_id"] == 0
            assert root.body["transition_groups"][0]["expanded"] is False
            assert root.body["transition_groups"][0]["outcomes"] == []

            group_id = root.body["transition_groups"][0]["group_id"]
            outcomes = await _post_json(
                application,
                f"/v1/inference/graphs/{graph_id}/groups/{group_id}/outcomes",
                root_request,
            )
            assert outcomes.status_code == 200
            assert outcomes.body["transition_group"]["expanded"] is True
            assert [
                item["edge_id"]
                for item in outcomes.body["transition_group"]["outcomes"]
            ] == [0, 1]

            advanced = await _post_json(
                application,
                f"/v1/inference/graphs/{graph_id}/advance",
                {
                    **root_request,
                    "edge_id": 0,
                },
            )
            assert advanced.status_code == 200
            assert advanced.body["node"]["node_id"] == 1
            assert advanced.body["cumulative_probability"] == {
                "numerator": "1",
                "denominator": "3",
                "decimal": pytest.approx(1 / 3),
                "percent": pytest.approx(100 / 3),
            }

            backtracked = await _post_json(
                application,
                f"/v1/inference/graphs/{graph_id}/backtrack",
                {
                    "calculation_revision": REVISION,
                    "cursor": advanced.body["cursor"],
                },
            )
            assert backtracked.status_code == 200
            assert backtracked.body["node"]["node_id"] == 0
            assert backtracked.body["cursor"] == {"steps": []}
            assert backtracked.body["battle_report"]["steps"] == []

    asyncio.run(scenario())
