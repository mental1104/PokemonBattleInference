"""定义通用 1v1 技能池后台任务的 HTTP 请求与响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pokeop.application.configuration_space.one_on_one import (
    ConfigurationDimensionMode,
    FixedPokemonConfiguration,
    MechanismAdmissionPolicy,
    OneOnOneActionPolicy,
    OneOnOneConfigurationWeightAssumption,
    OneOnOneDimensionModes,
    OneOnOneMovePoolCommand,
    PokemonMovePoolSelection,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
)


class _StrictModel(BaseModel):
    """统一拒绝未进入公开合同的额外 HTTP 字段。"""

    model_config = ConfigDict(extra="forbid")


class OneOnOneDimensionModesRequest(_StrictModel):
    """接收 #82 冻结的各配置维度模式。"""

    pokemon: Literal["fixed"]
    form: Literal["fixed"]
    level: Literal["fixed"]
    stats: Literal["fixed"]
    ability: Literal["fixed"]
    item: Literal["fixed"]
    moves: Literal["candidate_pool"]
    special_mechanics: Literal["disabled"]

    def to_application(self) -> OneOnOneDimensionModes:
        """转换为 application 显式枚举对象。"""
        return OneOnOneDimensionModes(
            pokemon=ConfigurationDimensionMode(self.pokemon),
            form=ConfigurationDimensionMode(self.form),
            level=ConfigurationDimensionMode(self.level),
            stats=ConfigurationDimensionMode(self.stats),
            ability=ConfigurationDimensionMode(self.ability),
            item=ConfigurationDimensionMode(self.item),
            moves=ConfigurationDimensionMode(self.moves),
            special_mechanics=ConfigurationDimensionMode(self.special_mechanics),
        )


class FixedPokemonConfigurationRequest(_StrictModel):
    """接收一侧不会参与 v1 枚举的固定配置。"""

    pokemon_id: int = Field(gt=0)
    form_id: int | None = Field(default=None, gt=0)
    level: int = Field(ge=1, le=100)
    stat_profile_id: str = Field(min_length=1)
    ability_identifier: str = Field(min_length=1)
    item_identifier: str | None = Field(default=None, min_length=1)

    def to_application(self) -> FixedPokemonConfiguration:
        """转换为参与 canonical 配置身份的 application 对象。"""
        return FixedPokemonConfiguration(
            pokemon_id=self.pokemon_id,
            form_id=self.form_id,
            level=self.level,
            stat_profile_id=self.stat_profile_id,
            ability_identifier=self.ability_identifier,
            item_identifier=self.item_identifier,
        )


class PokemonMovePoolSelectionRequest(_StrictModel):
    """接收一侧固定配置和 version-aware 候选招式 ID。"""

    fixed: FixedPokemonConfigurationRequest
    candidate_move_ids: list[int] = Field(min_length=1, max_length=10)

    def to_application(self) -> PokemonMovePoolSelection:
        """转换并由 application 合同完成排序、去重和预算校验。"""
        return PokemonMovePoolSelection(
            fixed=self.fixed.to_application(),
            candidate_move_ids=tuple(self.candidate_move_ids),
        )


class BattleInferenceExecutionBudgetRequest(_StrictModel):
    """允许调用方在服务端安全上限内冻结单任务执行预算。"""

    process_count: int = Field(default=2, ge=1, le=8)
    queue_depth: int = Field(default=4, ge=1, le=32)
    max_nodes_per_pair: int = Field(default=20_000, ge=1, le=2_000_000)
    max_edges_per_pair: int = Field(default=80_000, ge=1, le=8_000_000)
    max_turns: int | None = Field(default=100, ge=1, le=10_000)


class CreateBattleInferenceJobRequest(_StrictModel):
    """接收 #82 技能池命令，并可附带 #87 有界 worker 预算。"""

    contract_version: Literal["one-on-one-move-pool.v1"]
    ruleset_id: str = Field(min_length=1)
    version_group_id: int = Field(gt=0)
    calculation_revision: str = Field(min_length=1)
    dimensions: OneOnOneDimensionModesRequest
    weight_assumption: Literal["uniform_configuration_pair"]
    attacker_policy: Literal["first-legal-action", "uniform-random"]
    defender_policy: Literal["first-legal-action", "uniform-random"]
    mechanism_admission: Literal["supported_only"]
    attacker: PokemonMovePoolSelectionRequest
    defender: PokemonMovePoolSelectionRequest
    execution: BattleInferenceExecutionBudgetRequest = Field(
        default_factory=BattleInferenceExecutionBudgetRequest
    )

    def to_application(
        self,
    ) -> tuple[OneOnOneMovePoolCommand, BattleInferenceExecutionSpec]:
        """转换为公开技能池命令和与其策略一致的冻结执行规格。"""
        command = OneOnOneMovePoolCommand(
            contract_version=self.contract_version,
            ruleset_id=self.ruleset_id,
            version_group_id=self.version_group_id,
            calculation_revision=self.calculation_revision,
            dimensions=self.dimensions.to_application(),
            weight_assumption=OneOnOneConfigurationWeightAssumption(
                self.weight_assumption
            ),
            attacker_policy=OneOnOneActionPolicy(self.attacker_policy),
            defender_policy=OneOnOneActionPolicy(self.defender_policy),
            mechanism_admission=MechanismAdmissionPolicy(self.mechanism_admission),
            attacker=self.attacker.to_application(),
            defender=self.defender.to_application(),
        )
        budget = self.execution
        return command, BattleInferenceExecutionSpec.from_command(
            command,
            process_count=budget.process_count,
            queue_depth=budget.queue_depth,
            max_nodes_per_pair=budget.max_nodes_per_pair,
            max_edges_per_pair=budget.max_edges_per_pair,
            max_turns=budget.max_turns,
        )


class CreateBattleInferenceJobResponse(_StrictModel):
    """返回 HTTP 202 异步任务确认。"""

    job_id: str
    status: Literal["pending"] = "pending"
    submitted_configuration_pairs: int
    created_at: str


class BattleInferenceJobCountsResponse(_StrictModel):
    """返回与数据库进度桶一一对应的任务计数。"""

    total: int
    completed: int
    succeeded: int
    failed: int
    truncated: int
    running: int
    pending: int
    cancelled: int


class BattleInferenceResourceProgressResponse(_StrictModel):
    """返回累计资源消耗与创建时冻结的理论上限。"""

    used: int
    limit: int


class BattleInferenceJobStatusResponse(_StrictModel):
    """返回轮询所需生命周期、进度、预算和诊断。"""

    job_id: str
    status: Literal["queued", "running", "completed", "partial", "cancelled", "failed"]
    cancellation_requested: bool
    counts: BattleInferenceJobCountsResponse
    state_nodes: BattleInferenceResourceProgressResponse
    state_edges: BattleInferenceResourceProgressResponse
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    weight_assumption: str
    attacker_policy: str
    defender_policy: str
    last_failure_code: str | None
    last_failure_diagnostic: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class ExactProbabilityResponse(_StrictModel):
    """同时返回精确分数和前端展示小数。"""

    numerator: str
    denominator: str
    decimal: float


class BattleInferenceCaseResponse(_StrictModel):
    """返回一个不含完整状态图的配置执行摘要。"""

    configuration_id: str
    sequence_no: int
    status: str
    attacker_pokemon_id: int
    defender_pokemon_id: int
    attacker_move_ids: list[int]
    defender_move_ids: list[int]
    attacker_win_probability: ExactProbabilityResponse | None
    defender_win_probability: ExactProbabilityResponse | None
    draw_probability: ExactProbabilityResponse | None
    expected_turns_kind: str | None
    expected_turns: str | None
    node_count: int
    edge_count: int
    explanation: dict[str, object] | None = None
    failure_code: str | None
    diagnostic: str | None
    attempt_count: int


class BattleInferenceCasePageResponse(_StrictModel):
    """返回稳定 sequence 分页结果。"""

    job_id: str
    offset: int
    limit: int
    total: int
    next_cursor: str | None
    items: list[BattleInferenceCaseResponse]


class CancelBattleInferenceJobResponse(_StrictModel):
    """确认取消请求已经持久化。"""

    job_id: str
    cancellation_requested: bool
    status: str


__all__ = [
    "BattleInferenceCasePageResponse",
    "BattleInferenceCaseResponse",
    "BattleInferenceJobStatusResponse",
    "CancelBattleInferenceJobResponse",
    "CreateBattleInferenceJobRequest",
    "CreateBattleInferenceJobResponse",
    "ExactProbabilityResponse",
]
