"""定义战斗配置空间后台任务的 application 持久化合同。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from math import gcd
from typing import Protocol, runtime_checkable


class BattleInferenceJobStatus(str, Enum):
    """描述一个后台推演任务的稳定生命周期状态。"""

    PENDING = "pending"
    PREPARING = "preparing"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BattleInferenceCaseStatus(str, Enum):
    """描述一个固定配置对的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TRUNCATED = "truncated"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """返回当前状态是否已经形成不可再覆盖的最终结果。

        Returns:
            成功、失败、截断或取消返回 True；待执行和运行中返回 False。
        """
        return self in {
            BattleInferenceCaseStatus.SUCCEEDED,
            BattleInferenceCaseStatus.FAILED,
            BattleInferenceCaseStatus.TRUNCATED,
            BattleInferenceCaseStatus.CANCELLED,
        }


class BattleInferenceFailureCode(str, Enum):
    """列出任务和配置用例可查询的稳定失败或截断代码。"""

    UNSUPPORTED_MECHANISM = "unsupported_mechanism"
    GRAPH_NODE_LIMIT = "graph_node_limit"
    GRAPH_EDGE_LIMIT = "graph_edge_limit"
    TURN_LIMIT = "turn_limit"
    SOLVER_UNRESOLVED = "solver_unresolved"
    WORKER_CRASH = "worker_crash"
    CALCULATION_REVISION_MISMATCH = "calculation_revision_mismatch"
    CANCELLED = "cancelled"
    INVALID_CONFIGURATION = "invalid_configuration"


class BattleInferenceExpectedTurnsKind(str, Enum):
    """描述期望回合数是有限值、无限值还是不可用。"""

    FINITE = "finite"
    INFINITE = "infinite"
    UNAVAILABLE = "unavailable"


class BattleInferenceJobRepositoryError(RuntimeError):
    """表示后台任务 repository 的稳定业务错误。"""


class BattleInferenceJobAlreadyExists(BattleInferenceJobRepositoryError):
    """表示调用方尝试重复创建相同 job ID。"""


class BattleInferenceJobNotFound(BattleInferenceJobRepositoryError):
    """表示指定后台任务不存在。"""


class BattleInferenceCaseNotFound(BattleInferenceJobRepositoryError):
    """表示指定任务中不存在目标配置对。"""


class BattleInferenceLeaseConflict(BattleInferenceJobRepositoryError):
    """表示当前 worker 不再拥有目标任务或配置用例的有效 lease。"""


class BattleInferenceResultConflict(BattleInferenceJobRepositoryError):
    """表示同一配置对已经保存了语义不同的最终结果。"""


class BattleInferenceInvalidTransition(BattleInferenceJobRepositoryError):
    """表示请求的状态迁移违反任务或配置用例生命周期。"""


class BattleInferenceCalculationRevisionMismatch(BattleInferenceJobRepositoryError):
    """表示调用方计算版本与已持久化任务版本不兼容。"""

    def __init__(self, *, expected: str, actual: str) -> None:
        """保存期望版本和任务实际版本，并生成稳定错误文本。

        Args:
            expected: 调用方要求使用的规范化 calculation revision。
            actual: 已持久化任务绑定的 calculation revision。
        """
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"calculation revision mismatch: expected {expected!r}, actual {actual!r}"
        )


@dataclass(frozen=True, slots=True)
class BattleInferenceProbability:
    """保存一个精确概率分数。

    Args:
        numerator: 非负分子。
        denominator: 正分母。
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        """校验概率分数可以稳定持久化和比较。

        Raises:
            ValueError: 分子、分母不是合法整数或概率超过 1 时抛出。
        """
        _validate_non_negative_int(self.numerator, "numerator")
        _validate_positive_int(self.denominator, "denominator")
        if self.numerator > self.denominator:
            raise ValueError("probability numerator must not exceed denominator")
        divisor = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)


@dataclass(frozen=True, slots=True)
class BattleInferenceExpectedTurns:
    """保存固定配置对的期望回合数语义。

    Args:
        kind: 有限、无限或不可用。
        numerator: 有限期望回合数的非负分子；其他类型必须为 None。
        denominator: 有限期望回合数的正分母；其他类型必须为 None。
    """

    kind: BattleInferenceExpectedTurnsKind
    numerator: int | None = None
    denominator: int | None = None

    def __post_init__(self) -> None:
        """校验期望回合数与 kind 保持一致。

        Raises:
            ValueError: kind 与分数字段组合不合法时抛出。
        """
        if not isinstance(self.kind, BattleInferenceExpectedTurnsKind):
            raise ValueError("expected turns kind must be explicit")
        if self.kind is BattleInferenceExpectedTurnsKind.FINITE:
            if self.numerator is None or self.denominator is None:
                raise ValueError("finite expected turns require numerator and denominator")
            _validate_non_negative_int(self.numerator, "expected turns numerator")
            _validate_positive_int(self.denominator, "expected turns denominator")
            divisor = gcd(self.numerator, self.denominator)
            object.__setattr__(self, "numerator", self.numerator // divisor)
            object.__setattr__(self, "denominator", self.denominator // divisor)
            return
        if self.numerator is not None or self.denominator is not None:
            raise ValueError("non-finite expected turns must not contain a fraction")


@dataclass(frozen=True, slots=True)
class BattleInferenceLease:
    """保存 coordinator 或 worker 当前持有的租约。

    Args:
        owner: 规范化 worker 标识。
        heartbeat_at: 最近一次续租的带时区时间。
        expires_at: lease 失效的带时区时间，必须晚于 heartbeat_at。
    """

    owner: str
    heartbeat_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """校验 lease owner 和时间范围。

        Raises:
            ValueError: 标识为空、时间无时区或过期时间不晚于心跳时抛出。
        """
        _validate_identifier(self.owner, "lease owner")
        _validate_aware_datetime(self.heartbeat_at, "heartbeat_at")
        _validate_aware_datetime(self.expires_at, "expires_at")
        if self.expires_at <= self.heartbeat_at:
            raise ValueError("lease expires_at must be later than heartbeat_at")


@dataclass(frozen=True, slots=True)
class BattleInferenceCaseDefinition:
    """描述一个待持久化的固定双方配置对。

    Args:
        configuration_pair_id: 绑定规则、计算版本和双方配置的稳定配置对 ID。
        attacker_configuration_id: 攻击方固定配置的稳定 ID。
        defender_configuration_id: 防守方固定配置的稳定 ID。
        attacker_move_ids: 升序、去重的一到四个攻击方 move ID。
        defender_move_ids: 升序、去重的一到四个防守方 move ID。
    """

    configuration_pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """校验配置 ID 和无序技能组已经规范化。

        Raises:
            ValueError: 标识、技能数量、排序、重复或 move ID 非法时抛出。
        """
        _validate_identifier(self.configuration_pair_id, "configuration_pair_id")
        _validate_identifier(self.attacker_configuration_id, "attacker_configuration_id")
        _validate_identifier(self.defender_configuration_id, "defender_configuration_id")
        _validate_move_ids(self.attacker_move_ids, "attacker_move_ids")
        _validate_move_ids(self.defender_move_ids, "defender_move_ids")


@dataclass(frozen=True, slots=True)
class CreateBattleInferenceJob:
    """保存创建后台任务所需的完整不可变输入。

    Args:
        job_id: 调用方生成的不可猜测稳定任务 ID。
        ruleset_id: 本任务绑定的稳定规则集标识。
        version_group_id: PokeAPI 招式与历史数据使用的主版本轴。
        calculation_revision: 结果复用和兼容性判断使用的计算语义版本。
        cases: 按稳定顺序排列的全部配置对元数据；不得包含完整状态图。
    """

    job_id: str
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    cases: tuple[BattleInferenceCaseDefinition, ...]

    def __post_init__(self) -> None:
        """校验任务主轴和配置对唯一性。

        Raises:
            ValueError: 标识、版本轴、空任务或重复配置对不满足合同时抛出。
        """
        _validate_identifier(self.job_id, "job_id")
        _validate_identifier(self.ruleset_id, "ruleset_id")
        _validate_positive_int(self.version_group_id, "version_group_id")
        _validate_identifier(self.calculation_revision, "calculation_revision")
        if not self.cases:
            raise ValueError("job must contain at least one configuration pair")
        pair_ids = tuple(case.configuration_pair_id for case in self.cases)
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("configuration_pair_id must be unique within a job")


@dataclass(frozen=True, slots=True)
class BattleInferenceJobProgress:
    """保存任务级可原子更新的进度和预算统计。

    Args:
        total_count: 任务总配置对数量。
        pending_count: 尚未领取的配置对数量。
        running_count: 当前拥有 worker lease 的配置对数量。
        succeeded_count: 已成功完成的配置对数量。
        failed_count: 最终失败的配置对数量。
        truncated_count: 因资源或回合限制截断的配置对数量。
        cancelled_count: 因任务取消而终止的配置对数量。
        cumulative_node_count: 已完成用例累计构建的图节点数量。
        cumulative_edge_count: 已完成用例累计构建的图边数量。
        budget_consumed: 已完成用例累计消耗的抽象预算单位。
    """

    total_count: int
    pending_count: int
    running_count: int
    succeeded_count: int
    failed_count: int
    truncated_count: int
    cancelled_count: int
    cumulative_node_count: int
    cumulative_edge_count: int
    budget_consumed: int

    def __post_init__(self) -> None:
        """校验进度计数非负且状态桶之和等于总数。

        Raises:
            ValueError: 任一计数非法或状态桶不守恒时抛出。
        """
        for field_name in (
            "total_count",
            "pending_count",
            "running_count",
            "succeeded_count",
            "failed_count",
            "truncated_count",
            "cancelled_count",
            "cumulative_node_count",
            "cumulative_edge_count",
            "budget_consumed",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        accounted = (
            self.pending_count
            + self.running_count
            + self.succeeded_count
            + self.failed_count
            + self.truncated_count
            + self.cancelled_count
        )
        if accounted != self.total_count:
            raise ValueError("job progress status counts must equal total_count")


@dataclass(frozen=True, slots=True)
class BattleInferenceCaseResult:
    """描述 worker 准备原子写入的单配置最终结果。

    Args:
        status: 必须为成功、失败、截断或取消之一。
        attacker_win: 成功结果中的攻击方获胜精确概率。
        defender_win: 成功结果中的防守方获胜精确概率。
        draw: 成功结果中的平局精确概率。
        expected_turns: 成功结果中的期望回合数语义。
        node_count: 本用例实际构建或观察到的图节点数量。
        edge_count: 本用例实际构建或观察到的图边数量。
        budget_consumed: 本用例消耗的抽象预算单位。
        failure_code: 失败、截断或取消时的稳定代码。
        diagnostic: 可直接展示或记录的规范化诊断文本。
    """

    status: BattleInferenceCaseStatus
    attacker_win: BattleInferenceProbability | None = None
    defender_win: BattleInferenceProbability | None = None
    draw: BattleInferenceProbability | None = None
    expected_turns: BattleInferenceExpectedTurns | None = None
    node_count: int = 0
    edge_count: int = 0
    budget_consumed: int = 0
    failure_code: BattleInferenceFailureCode | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        """校验成功摘要和失败诊断不会混用。

        Raises:
            ValueError: 状态非终态、概率不守恒或错误字段组合非法时抛出。
        """
        if not isinstance(self.status, BattleInferenceCaseStatus) or not self.status.is_terminal:
            raise ValueError("case result status must be terminal")
        _validate_non_negative_int(self.node_count, "node_count")
        _validate_non_negative_int(self.edge_count, "edge_count")
        _validate_non_negative_int(self.budget_consumed, "budget_consumed")
        if self.diagnostic is not None:
            _validate_identifier(self.diagnostic, "diagnostic")

        probabilities = (self.attacker_win, self.defender_win, self.draw)
        if self.status is BattleInferenceCaseStatus.SUCCEEDED:
            if any(probability is None for probability in probabilities):
                raise ValueError("successful case result requires win/draw probabilities")
            if self.expected_turns is None:
                raise ValueError("successful case result requires expected_turns")
            if self.failure_code is not None or self.diagnostic is not None:
                raise ValueError("successful case result must not contain failure diagnostics")
            assert self.attacker_win is not None
            assert self.defender_win is not None
            assert self.draw is not None
            total_numerator = (
                self.attacker_win.numerator
                * self.defender_win.denominator
                * self.draw.denominator
                + self.defender_win.numerator
                * self.attacker_win.denominator
                * self.draw.denominator
                + self.draw.numerator
                * self.attacker_win.denominator
                * self.defender_win.denominator
            )
            total_denominator = (
                self.attacker_win.denominator
                * self.defender_win.denominator
                * self.draw.denominator
            )
            if total_numerator != total_denominator:
                raise ValueError("successful win/draw probabilities must sum to 1")
            return

        if (
            any(probability is not None for probability in probabilities)
            or self.expected_turns is not None
        ):
            raise ValueError("non-success result must not contain probability summary")
        if self.failure_code is None:
            raise ValueError("non-success result requires failure_code")
        if self.diagnostic is None:
            raise ValueError("non-success result requires diagnostic")
        if self.status is BattleInferenceCaseStatus.CANCELLED:
            if self.failure_code is not BattleInferenceFailureCode.CANCELLED:
                raise ValueError("cancelled result must use CANCELLED failure code")
        elif self.failure_code is BattleInferenceFailureCode.CANCELLED:
            raise ValueError("CANCELLED failure code is reserved for cancelled results")

    @property
    def fingerprint(self) -> str:
        """返回用于幂等写入比较的稳定 SHA-256 摘要。

        Returns:
            覆盖全部最终结果字段的十六进制 SHA-256 字符串。
        """
        parts = (
            self.status.value,
            _probability_text(self.attacker_win),
            _probability_text(self.defender_win),
            _probability_text(self.draw),
            _expected_turns_text(self.expected_turns),
            str(self.node_count),
            str(self.edge_count),
            str(self.budget_consumed),
            self.failure_code.value if self.failure_code is not None else "",
            self.diagnostic or "",
        )
        return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BattleInferenceJobSnapshot:
    """表示 application 可读取的任务状态、进度和 lease 元数据。

    Args:
        job_id: 后台任务稳定 ID。
        ruleset_id: 任务绑定的规则集 ID。
        version_group_id: 任务绑定的 PokeAPI version group。
        calculation_revision: 结果兼容性使用的计算版本。
        status: 当前任务生命周期状态。
        attempt_count: coordinator 成功领取任务的累计次数。
        progress: 与 case 表保持守恒的任务进度。
        lease: 当前 coordinator lease；未被领取或已结束时为 None。
        last_failure_code: 最近一次任务级恢复或失败代码。
        last_failure_diagnostic: 最近一次任务级恢复或失败诊断。
        created_at: 任务创建时间。
        updated_at: 任务最后更新时间。
        started_at: 首次领取或执行时间。
        completed_at: 任务进入最终状态的时间。
        cancel_requested_at: 首次收到取消请求的时间。
    """

    job_id: str
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    status: BattleInferenceJobStatus
    attempt_count: int
    progress: BattleInferenceJobProgress
    lease: BattleInferenceLease | None
    last_failure_code: BattleInferenceFailureCode | None
    last_failure_diagnostic: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancel_requested_at: datetime | None


@dataclass(frozen=True, slots=True)
class BattleInferenceCaseSnapshot:
    """表示一个配置对的身份、执行状态、结果摘要和恢复信息。

    Args:
        job_id: 父任务稳定 ID。
        sequence_no: 任务内稳定零基序号，用于确定性分页。
        definition: 配置对身份和双方规范化技能组。
        status: 当前 case 生命周期状态。
        attempt_count: case 被 worker 领取的累计次数。
        lease: 当前 worker lease；未领取或终态时为 None。
        attacker_win: 成功结果中的攻击方获胜概率。
        defender_win: 成功结果中的防守方获胜概率。
        draw: 成功结果中的平局概率。
        expected_turns: 成功结果中的期望回合语义。
        node_count: 本 case 的状态图节点数量。
        edge_count: 本 case 的状态图边数量。
        budget_consumed: 本 case 消耗的抽象预算。
        failure_code: 失败、截断或取消的最终代码。
        diagnostic: 最终结果诊断。
        last_failure_code: 最近一次非最终恢复错误，例如 worker crash。
        last_failure_diagnostic: 最近一次非最终恢复诊断。
        created_at: case 创建时间。
        updated_at: case 最后更新时间。
        started_at: case 首次领取时间。
        completed_at: case 进入终态的时间。
    """

    job_id: str
    sequence_no: int
    definition: BattleInferenceCaseDefinition
    status: BattleInferenceCaseStatus
    attempt_count: int
    lease: BattleInferenceLease | None
    attacker_win: BattleInferenceProbability | None
    defender_win: BattleInferenceProbability | None
    draw: BattleInferenceProbability | None
    expected_turns: BattleInferenceExpectedTurns | None
    node_count: int
    edge_count: int
    budget_consumed: int
    failure_code: BattleInferenceFailureCode | None
    diagnostic: str | None
    last_failure_code: BattleInferenceFailureCode | None
    last_failure_diagnostic: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BattleInferenceCaseFilter:
    """描述配置用例分页查询的可组合过滤条件。

    Args:
        statuses: 允许返回的状态集合；空元组表示不过滤状态。
        failure_codes: 允许返回的最终错误码集合；空元组表示不过滤错误码。
        configuration_id: 精确匹配配置对、攻击方或防守方配置 ID；None 表示不过滤。
        offset: 从稳定 sequence 顺序跳过的非负行数。
        limit: 单页返回数量，范围 1..500。
    """

    statuses: tuple[BattleInferenceCaseStatus, ...] = ()
    failure_codes: tuple[BattleInferenceFailureCode, ...] = ()
    configuration_id: str | None = None
    offset: int = 0
    limit: int = 100

    def __post_init__(self) -> None:
        """校验过滤枚举、配置 ID 和分页范围。

        Raises:
            ValueError: 过滤条件或分页参数非法时抛出。
        """
        if any(not isinstance(status, BattleInferenceCaseStatus) for status in self.statuses):
            raise ValueError("statuses must contain BattleInferenceCaseStatus values")
        if any(
            not isinstance(code, BattleInferenceFailureCode) for code in self.failure_codes
        ):
            raise ValueError("failure_codes must contain BattleInferenceFailureCode values")
        if self.configuration_id is not None:
            _validate_identifier(self.configuration_id, "configuration_id")
        _validate_non_negative_int(self.offset, "offset")
        _validate_positive_int(self.limit, "limit")
        if self.limit > 500:
            raise ValueError("limit must not exceed 500")


@dataclass(frozen=True, slots=True)
class BattleInferenceCasePage:
    """保存稳定 sequence 顺序的一页配置结果。

    Args:
        items: 当前页 case 快照。
        total_count: 应用过滤条件后的总行数。
        offset: 当前页零基偏移。
        limit: 当前页请求上限。
    """

    items: tuple[BattleInferenceCaseSnapshot, ...]
    total_count: int
    offset: int
    limit: int


@runtime_checkable
class BattleInferenceJobRepository(Protocol):
    """定义后台任务、进度、租约和配置结果的 application 持久化端口。"""

    def create_job(
        self,
        command: CreateBattleInferenceJob,
        *,
        created_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """在同一事务中创建任务、进度和全部配置对元数据。

        Args:
            command: 已校验的任务主轴和有序配置对定义。
            created_at: 任务创建的带时区时间。

        Returns:
            状态为 PENDING、全部 case 位于 pending 桶的任务快照。

        Raises:
            BattleInferenceJobAlreadyExists: job ID 已存在时抛出。
        """
        ...

    def get_job(
        self,
        job_id: str,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot:
        """读取任务，并可选拒绝不兼容 calculation revision。

        Args:
            job_id: 目标任务稳定 ID。
            calculation_revision: 可选的精确计算版本要求。

        Returns:
            当前任务状态、进度和 lease 快照。

        Raises:
            BattleInferenceJobNotFound: 任务不存在时抛出。
            BattleInferenceCalculationRevisionMismatch: 版本不兼容时抛出。
        """
        ...

    def claim_next_job(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot | None:
        """使用安全锁领取一个待准备或 coordinator lease 已过期的任务。

        Args:
            lease_owner: coordinator 稳定标识。
            now: 本次领取的带时区时间。
            lease_duration: 新 lease 的正时长。
            calculation_revision: 可选的计算版本过滤条件。

        Returns:
            成功领取时返回任务快照；当前没有候选任务时返回 None。
        """
        ...

    def heartbeat_job(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> BattleInferenceJobSnapshot:
        """仅由当前 owner 原子延长任务 lease。

        Args:
            job_id: 目标任务 ID。
            lease_owner: 当前 coordinator owner。
            now: 心跳时间，必须位于旧 lease 有效期内。
            lease_duration: 从 now 开始计算的新 lease 正时长。

        Returns:
            包含新 lease 的任务快照。

        Raises:
            BattleInferenceLeaseConflict: owner、状态或有效期不匹配时抛出。
        """
        ...

    def claim_cases(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        limit: int,
        calculation_revision: str,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """领取一批待执行或 worker lease 已过期的配置对。

        Args:
            job_id: 父任务 ID。
            lease_owner: 执行本批 case 的 worker 标识。
            now: 本次领取时间。
            lease_duration: 每个 case 的 lease 正时长。
            limit: 单批最大领取数。
            calculation_revision: worker 当前计算版本。

        Returns:
            按稳定序号排列的已领取 case；无候选时返回空元组。
        """
        ...

    def heartbeat_cases(
        self,
        job_id: str,
        configuration_pair_ids: tuple[str, ...],
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """仅由当前 owner 原子延长一批运行中配置对 lease。

        Args:
            job_id: 父任务 ID。
            configuration_pair_ids: 需要续租的非空、无重复配置对 ID。
            lease_owner: 必须拥有全部目标 case 的 worker 标识。
            now: 本次心跳时间。
            lease_duration: 从 now 开始计算的新 lease 正时长。

        Returns:
            按稳定序号排列的续租后 case 快照。
        """
        ...

    def record_case_result(
        self,
        job_id: str,
        configuration_pair_id: str,
        result: BattleInferenceCaseResult,
        *,
        lease_owner: str,
        completed_at: datetime,
        calculation_revision: str,
    ) -> bool:
        """幂等保存单配置最终结果并在同一事务更新进度。

        Args:
            job_id: 父任务 ID。
            configuration_pair_id: 目标配置对稳定 ID。
            result: 成功、失败、截断或取消的最终摘要。
            lease_owner: 提交结果的 worker owner。
            completed_at: 结果完成时间，必须位于有效 lease 内。
            calculation_revision: 产生结果的计算版本。

        Returns:
            首次应用结果返回 True；相同结果重放返回 False。

        Raises:
            BattleInferenceResultConflict: 终态已存在不同结果时抛出。
            BattleInferenceLeaseConflict: worker 不再拥有有效 lease 时抛出。
        """
        ...

    def request_cancel(
        self,
        job_id: str,
        *,
        requested_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """把可取消任务迁移为 CANCEL_REQUESTED，并保留已完成结果。

        Args:
            job_id: 目标任务 ID。
            requested_at: 首次请求取消的带时区时间。

        Returns:
            取消请求后的任务快照；已终态任务保持原状态。
        """
        ...

    def cancel_unclaimed_cases(
        self,
        job_id: str,
        *,
        cancelled_at: datetime,
    ) -> int:
        """取消尚未运行或 lease 已过期的用例。

        Args:
            job_id: 已处于 CANCEL_REQUESTED 的任务 ID。
            cancelled_at: 本次取消清理时间。

        Returns:
            本事务首次迁移为 CANCELLED 的 case 数量。
        """
        ...

    def finalize_job(
        self,
        job_id: str,
        *,
        completed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """在没有 pending/running 用例时根据进度生成最终任务状态。

        Args:
            job_id: 目标任务 ID。
            completed_at: 任务完成时间。

        Returns:
            SUCCEEDED、COMPLETED_WITH_FAILURES 或 CANCELLED 快照。

        Raises:
            BattleInferenceInvalidTransition: 仍有未完成 case 时抛出。
        """
        ...

    def fail_job(
        self,
        job_id: str,
        *,
        failure_code: BattleInferenceFailureCode,
        diagnostic: str,
        failed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """记录任务级致命失败，不删除已经完成的配置结果。

        Args:
            job_id: 目标任务 ID。
            failure_code: 稳定任务级失败代码。
            diagnostic: 非空诊断文本。
            failed_at: 任务失败时间。

        Returns:
            状态为 FAILED 且保留原 progress 的任务快照。
        """
        ...

    def list_cases(
        self,
        job_id: str,
        query: BattleInferenceCaseFilter,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceCasePage:
        """按状态、配置和错误码过滤，并稳定分页读取配置结果。

        Args:
            job_id: 父任务 ID。
            query: 可组合过滤和分页参数。
            calculation_revision: 可选的计算版本兼容要求。

        Returns:
            按 sequence_no 升序排列的一页 case 和过滤总数。
        """
        ...


def validate_lease_request(
    *,
    lease_owner: str,
    now: datetime,
    lease_duration: timedelta,
) -> datetime:
    """校验 lease 请求并计算过期时间。

    Args:
        lease_owner: coordinator 或 worker 的规范化稳定标识。
        now: 本次领取或 heartbeat 的带时区时间。
        lease_duration: 必须大于零的 lease 时长。

    Returns:
        ``now + lease_duration`` 得到的带时区过期时间。

    Raises:
        ValueError: owner、时间或时长不合法时抛出。
    """
    _validate_identifier(lease_owner, "lease_owner")
    _validate_aware_datetime(now, "now")
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")
    return now + lease_duration


def _probability_text(value: BattleInferenceProbability | None) -> str:
    """把可选精确概率转换为稳定指纹片段。

    Args:
        value: 精确概率或 None。

    Returns:
        ``numerator/denominator`` 文本；None 返回空字符串。
    """
    if value is None:
        return ""
    return f"{value.numerator}/{value.denominator}"


def _expected_turns_text(value: BattleInferenceExpectedTurns | None) -> str:
    """把可选期望回合数转换为稳定指纹片段。

    Args:
        value: 期望回合对象或 None。

    Returns:
        可参与 SHA-256 的规范化文本；None 返回空字符串。
    """
    if value is None:
        return ""
    if value.kind is not BattleInferenceExpectedTurnsKind.FINITE:
        return value.kind.value
    return f"{value.kind.value}:{value.numerator}/{value.denominator}"


def _validate_move_ids(move_ids: tuple[int, ...], field_name: str) -> None:
    """校验无序技能组已按稳定 ID 升序规范化。

    Args:
        move_ids: 一到四个 move ID 的元组。
        field_name: 稳定错误文本使用的字段名。

    Raises:
        ValueError: 数量、元素、排序或去重不符合合同时抛出。
    """
    if not 1 <= len(move_ids) <= 4:
        raise ValueError(f"{field_name} must contain between 1 and 4 move ids")
    for move_id in move_ids:
        _validate_positive_int(move_id, field_name)
    if move_ids != tuple(sorted(set(move_ids))):
        raise ValueError(f"{field_name} must be unique and sorted")


def _validate_identifier(value: str, field_name: str) -> None:
    """校验稳定标识是首尾无空白的非空字符串。

    Args:
        value: 待校验标识。
        field_name: 稳定错误文本使用的字段名。

    Raises:
        ValueError: 标识为空、非字符串或首尾有空白时抛出。
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and normalized")


def _validate_non_negative_int(value: int, field_name: str) -> None:
    """校验值为拒绝 bool 的非负整数。

    Args:
        value: 待校验数值。
        field_name: 稳定错误文本使用的字段名。

    Raises:
        ValueError: 值不是非负整数时抛出。
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_positive_int(value: int, field_name: str) -> None:
    """校验值为拒绝 bool 的正整数。

    Args:
        value: 待校验数值。
        field_name: 稳定错误文本使用的字段名。

    Raises:
        ValueError: 值不是正整数时抛出。
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _validate_aware_datetime(value: datetime, field_name: str) -> None:
    """校验时间对象带有可用时区偏移。

    Args:
        value: 待校验时间。
        field_name: 稳定错误文本使用的字段名。

    Raises:
        ValueError: 值不是带时区 datetime 时抛出。
    """
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "BattleInferenceCalculationRevisionMismatch",
    "BattleInferenceCaseDefinition",
    "BattleInferenceCaseFilter",
    "BattleInferenceCaseNotFound",
    "BattleInferenceCasePage",
    "BattleInferenceCaseResult",
    "BattleInferenceCaseSnapshot",
    "BattleInferenceCaseStatus",
    "BattleInferenceExpectedTurns",
    "BattleInferenceExpectedTurnsKind",
    "BattleInferenceFailureCode",
    "BattleInferenceInvalidTransition",
    "BattleInferenceJobAlreadyExists",
    "BattleInferenceJobNotFound",
    "BattleInferenceJobProgress",
    "BattleInferenceJobRepository",
    "BattleInferenceJobRepositoryError",
    "BattleInferenceJobSnapshot",
    "BattleInferenceJobStatus",
    "BattleInferenceLease",
    "BattleInferenceLeaseConflict",
    "BattleInferenceProbability",
    "BattleInferenceResultConflict",
    "CreateBattleInferenceJob",
    "validate_lease_request",
]
