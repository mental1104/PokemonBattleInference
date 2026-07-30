"""定义通用后台推演任务列表与详情 HTTP DTO。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class InferenceJobCountsResponse(BaseModel):
    """返回任务内部配置对状态桶计数。"""

    total: int
    pending: int
    running: int
    succeeded: int
    failed: int
    truncated: int
    cancelled: int
    completed: int


class InferenceJobResourceResponse(BaseModel):
    """返回可靠的资源预算使用量，不表达求解完成百分比。"""

    used: int
    limit: int


class InferenceJobRunningCaseResponse(BaseModel):
    """返回当前运行中配置对的最新观测进度。"""

    configuration_id: str
    phase: str
    percent: float
    observed_nodes: int
    observed_edges: int
    node_limit: int
    edge_limit: int
    expanded_nodes: int
    frontier_nodes: int
    action_pairs_completed: int
    action_pairs_total: int
    updated_at: str


class InferenceJobProgressResponse(BaseModel):
    """返回任务面板可展示的最新可靠进度。"""

    phase: str
    counts: InferenceJobCountsResponse
    state_nodes: InferenceJobResourceResponse
    state_edges: InferenceJobResourceResponse
    running_case: InferenceJobRunningCaseResponse | None
    elapsed_seconds: float | None


class InferenceJobLinksResponse(BaseModel):
    """返回任务详情与取消操作链接。"""

    self: str
    cancel: str


class InferenceJobSummaryResponse(BaseModel):
    """返回任务列表和详情共用的轻量任务快照。"""

    job_id: str
    job_type: Literal["fixed-one-on-one", "configuration-space"]
    status: str
    phase: str
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    created_at: str
    started_at: str | None
    updated_at: str
    finished_at: str | None
    cancel_requested_at: str | None
    can_cancel: bool
    progress: InferenceJobProgressResponse
    error_code: str | None
    error_message: str | None
    links: InferenceJobLinksResponse


class InferenceJobListResponse(BaseModel):
    """返回稳定分页的一页任务。"""

    items: list[InferenceJobSummaryResponse]
    next_cursor: str | None


class CancelInferenceJobResponse(BaseModel):
    """返回取消请求后的最新任务状态。"""

    job: InferenceJobSummaryResponse


__all__ = [
    "CancelInferenceJobResponse",
    "InferenceJobListResponse",
    "InferenceJobRunningCaseResponse",
    "InferenceJobSummaryResponse",
]
