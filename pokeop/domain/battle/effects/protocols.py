from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from pokeop.domain.battle.context import DamageContext
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.modifier_keys import ModifierKeyLike
from pokeop.domain.battle.state import BattleState
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import VolatileStatus
from pokeop.domain.battle.transitions import WeightedTransition

ActionT = TypeVar("ActionT")
TransitionSet = tuple[WeightedTransition[BattleState], ...]


class EffectSourceKind(str, Enum):
    """标识一个 battle effect 来自招式、特性还是携带道具。"""

    MOVE = "move"
    ABILITY = "ability"
    ITEM = "item"


class EffectCoverageStatus(str, Enum):
    """描述一个机制标识在当前规则集中的支持状态。"""

    SUPPORTED = "supported"
    NO_EFFECT = "no_effect"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class EffectCapabilityCoverage:
    """记录一个 effect 内部子机制的结构化覆盖状态。

    Attributes:
        identifier: 子机制的稳定标识，例如 ``freeze_secondary_effect``。
        status: 当前规则集对该子机制的支持状态。
        reason: 面向诊断和结果 DTO 的简短解释，不参与行为分发。
    """

    identifier: str
    status: EffectCoverageStatus
    reason: str

    def __post_init__(self) -> None:
        """拒绝空标识、非法状态和空解释，保证覆盖结果可被稳定消费。"""
        if not self.identifier.strip():
            raise ValueError("capability identifier must not be blank")
        if not isinstance(self.status, EffectCoverageStatus):
            raise ValueError("capability status must be an EffectCoverageStatus")
        if not self.reason.strip():
            raise ValueError("capability reason must not be blank")


@dataclass(frozen=True, slots=True)
class EffectCoverage:
    """记录工厂创建出的 effect 对当前机制的覆盖结论。

    Attributes:
        ruleset_id: 创建该 effect 的规则集标识。
        source_kind: 机制来自招式、特性还是道具。
        identifier: 规范化后的机制标识；未配置时使用 ``none``。
        status: 当前规则集对该机制整体的支持状态。
        reason: 面向诊断和结果 DTO 的简短解释，不参与状态判等。
        capabilities: 该 effect 内部可独立声明的子机制覆盖结果。
    """

    ruleset_id: str
    source_kind: EffectSourceKind
    identifier: str
    status: EffectCoverageStatus
    reason: str
    capabilities: tuple[EffectCapabilityCoverage, ...] = ()

    def __post_init__(self) -> None:
        """校验覆盖记录必须包含可追踪的规则集、机制标识和子能力。"""
        if not self.ruleset_id.strip():
            raise ValueError("ruleset_id must not be blank")
        if not self.identifier.strip():
            raise ValueError("identifier must not be blank")
        if not isinstance(self.source_kind, EffectSourceKind):
            raise ValueError("source_kind must be an EffectSourceKind")
        if not isinstance(self.status, EffectCoverageStatus):
            raise ValueError("status must be an EffectCoverageStatus")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        capabilities = tuple(self.capabilities)
        if any(
            not isinstance(capability, EffectCapabilityCoverage)
            for capability in capabilities
        ):
            raise ValueError(
                "capabilities must contain EffectCapabilityCoverage values"
            )
        identifiers = tuple(capability.identifier for capability in capabilities)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("capability identifiers must be unique")
        object.__setattr__(self, "capabilities", capabilities)

    @property
    def unsupported_capabilities(self) -> tuple[EffectCapabilityCoverage, ...]:
        """返回当前 effect 明确声明为尚未支持的子机制。"""
        return tuple(
            capability
            for capability in self.capabilities
            if capability.status is EffectCoverageStatus.UNSUPPORTED
        )


@dataclass(frozen=True, slots=True)
class ActionEffectContext(Generic[ActionT]):
    """向行动校验和选招后 effect 提供不可变输入。

    Attributes:
        state: #21 定义的当前不可变 ``BattleState`` 节点。
        actor: 本次行动所属的一方。
        action: 已由合法行动生成器产生或正在校验的类型化行动。
    """

    state: BattleState
    actor: BattleSide
    action: ActionT


@dataclass(frozen=True, slots=True)
class ActionOrder:
    """表示一个行动在排序阶段可被 effect 调整的显式排序键。

    Attributes:
        priority: 招式或行动的优先级，数值越大越先执行。
        speed: 当前规则计算后的有效速度，数值越大越先执行。
        tie_break: 同优先级同速度时由外部概率分支写入的稳定顺序键。
    """

    priority: int
    speed: int
    tie_break: int = 0


@dataclass(frozen=True, slots=True)
class ActionOrderEffectContext(Generic[ActionT]):
    """向行动顺序 effect 提供当前战斗节点、行动方和类型化行动。"""

    state: BattleState
    actor: BattleSide
    action: ActionT


@dataclass(frozen=True, slots=True)
class MoveEffectContext(Generic[ActionT]):
    """向招式执行前后阶段提供当前战斗节点和行动信息。"""

    state: BattleState
    actor: BattleSide
    action: ActionT


@dataclass(frozen=True, slots=True)
class TurnEndEffectContext:
    """向回合结束 effect 提供唯一可信的当前 ``BattleState``。

    回合号直接读取 ``state.turn_number``，不再在上下文中复制一份可能与状态节点
    不一致的数值。
    """

    state: BattleState


@dataclass(frozen=True, slots=True)
class VolatileStatusEffectContext:
    """向临时状态阻止 effect 提供来源、目标和状态标识。

    Attributes:
        state: 当前不可变 ``BattleState`` 节点。
        source: 尝试施加状态的一方。
        target: 即将接收状态的一方。
        status_identifier: 已在 domain 边界规范化的临时状态标识。
    """

    state: BattleState
    source: BattleSide
    target: BattleSide
    status_identifier: str

    def __post_init__(self) -> None:
        """拒绝空状态标识，避免 effect 把未知输入误判为已支持机制。"""
        if not self.status_identifier.strip():
            raise ValueError("status_identifier must not be blank")


@dataclass(frozen=True, slots=True)
class VolatileStatusAttempt:
    """表示招式在伤害后发出的一次类型化临时状态施加请求。

    Attributes:
        source: 发出状态请求的稳定战斗侧。
        target: 接收状态请求的另一稳定战斗侧。
        status: 已构造完成的不可变临时状态值对象。
        source_identifier: 发出请求的 effect 标识，用于诊断和测试追踪。
    """

    source: BattleSide
    target: BattleSide
    status: VolatileStatus
    source_identifier: str

    def __post_init__(self) -> None:
        """校验状态请求必须指向对手且携带可追踪的临时状态。"""
        if not isinstance(self.source, BattleSide):
            raise ValueError("status attempt source must be a BattleSide")
        if not isinstance(self.target, BattleSide):
            raise ValueError("status attempt target must be a BattleSide")
        if self.source is self.target:
            raise ValueError("status attempt target must differ from source")
        if not isinstance(self.status.kind, VolatileStatusKind):
            raise ValueError("status attempt must carry a volatile status")
        if not self.source_identifier.strip():
            raise ValueError("status attempt source_identifier must not be blank")


@dataclass(frozen=True, slots=True)
class ActionValidationResult:
    """表示一个校验 effect 对当前行动的独立裁决。"""

    allowed: bool
    source_identifier: str
    reason: str = ""

    def __post_init__(self) -> None:
        """校验裁决必须指出提供结论的 effect 标识。"""
        if not self.source_identifier.strip():
            raise ValueError("source_identifier must not be blank")


@dataclass(frozen=True, slots=True)
class ActionValidationReport:
    """聚合所有行动校验 effect 的不可变结果。"""

    decisions: tuple[ActionValidationResult, ...]

    @property
    def allowed(self) -> bool:
        """仅当所有已参与校验的 effect 都允许时返回 True。"""
        return all(decision.allowed for decision in self.decisions)


@dataclass(frozen=True, slots=True)
class StatusPreventionResult:
    """表示一个 effect 是否阻止指定临时状态。"""

    prevented: bool
    source_identifier: str
    reason: str = ""

    def __post_init__(self) -> None:
        """校验阻止结论必须指出提供结果的 effect 标识。"""
        if not self.source_identifier.strip():
            raise ValueError("source_identifier must not be blank")


@dataclass(frozen=True, slots=True)
class StatusPreventionReport:
    """聚合所有临时状态阻止 effect 的结果。"""

    decisions: tuple[StatusPreventionResult, ...]

    @property
    def prevented(self) -> bool:
        """任一 effect 明确阻止状态时返回 True。"""
        return any(decision.prevented for decision in self.decisions)


class DamageEffectStage(str, Enum):
    """标识旧伤害 effect 适配到统一协议时的调用阶段。"""

    BASE_POWER = "base_power"
    ATTACK_STAT = "attack_stat"
    DEFENSE_STAT = "defense_stat"
    STAB = "stab"
    CRITICAL_HIT = "critical_hit"
    FINAL_DAMAGE = "final_damage"


@dataclass(frozen=True, slots=True)
class DamageEffectContext:
    """向 ``ModifyDamageEffect`` 提供现有伤害链可理解的阶段输入。

    Attributes:
        damage_context: 已规范化的单次伤害计算上下文。
        stage: 当前需要执行的伤害修正阶段。
        type_effectiveness: final damage effect 需要读取的属性克制倍率。
        base_multiplier: critical effect 需要读取的规则集基础会心倍率。
    """

    damage_context: DamageContext
    stage: DamageEffectStage
    type_effectiveness: float = 1.0
    base_multiplier: float = 1.0

    def __post_init__(self) -> None:
        """校验倍率输入不能为负，零仍允许表达属性免疫。"""
        if self.type_effectiveness < 0:
            raise ValueError("type_effectiveness must not be negative")
        if self.base_multiplier < 0:
            raise ValueError("base_multiplier must not be negative")


@dataclass(frozen=True, slots=True)
class DamageEffectApplication:
    """统一表示 ability/item damage adapter 产生的一次倍率修正。"""

    key: ModifierKeyLike
    multiplier: float
    reason: str

    def __post_init__(self) -> None:
        """拒绝负倍率和空解释，保证伤害 trace 可稳定展示。"""
        if self.multiplier < 0:
            raise ValueError("damage effect multiplier must not be negative")
        if not self.reason.strip():
            raise ValueError("damage effect reason must not be blank")


@dataclass(frozen=True, slots=True)
class DamageEffectResult:
    """表示一个 ``ModifyDamageEffect`` 在当前阶段是否生效。"""

    application: DamageEffectApplication | None = None

    @property
    def active(self) -> bool:
        """存在实际倍率修正时返回 True。"""
        return self.application is not None

    @classmethod
    def inactive(cls) -> "DamageEffectResult":
        """返回当前阶段未生效的显式结果，避免调用方传播 None。"""
        return cls()


class BattleEffect(Protocol):
    """所有 battle effect 共享的最小覆盖信息协议。"""

    @property
    def coverage(self) -> EffectCoverage:
        """返回该 effect 在当前规则集中的机制覆盖状态。"""
        ...


class MoveEffect(BattleEffect, Protocol):
    """标记由抽象工厂创建的招式 effect 产品。"""


class AbilityEffect(BattleEffect, Protocol):
    """标记由抽象工厂创建的特性 effect 产品。"""


class ItemEffect(BattleEffect, Protocol):
    """标记由抽象工厂创建的道具 effect 产品。"""


@runtime_checkable
class ValidateActionEffect(Protocol[ActionT]):
    """只负责判断一个类型化行动当前是否允许执行。"""

    def validate_action(
        self,
        context: ActionEffectContext[ActionT],
    ) -> ActionValidationResult:
        """返回独立校验结论，不执行行动也不修改状态。"""
        ...


@runtime_checkable
class ModifyActionOrderEffect(Protocol[ActionT]):
    """只负责调整单个行动的显式排序键。"""

    def modify_action_order(
        self,
        context: ActionOrderEffectContext[ActionT],
        current: ActionOrder,
    ) -> ActionOrder:
        """基于当前排序键返回新排序键，不重排完整行动列表。"""
        ...


@runtime_checkable
class BeforeMoveEffect(Protocol[ActionT]):
    """只在招式执行前转换精确带权 ``BattleState`` 后继分支。"""

    def before_move(
        self,
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """返回新的带权转移集合，不原地修改输入状态或共享集合。"""
        ...


@runtime_checkable
class ModifyDamageEffect(Protocol):
    """只参与显式伤害阶段，兼容现有 ability/item damage effect。"""

    def modify_damage(self, context: DamageEffectContext) -> DamageEffectResult:
        """返回当前阶段的倍率修正；未生效时返回显式 inactive 结果。"""
        ...


@runtime_checkable
class PreventVolatileStatusEffect(Protocol):
    """只判断指定临时状态是否应被阻止。"""

    def prevent_volatile_status(
        self,
        context: VolatileStatusEffectContext,
    ) -> StatusPreventionResult:
        """返回状态阻止结论，不直接清理或写入状态字段。"""
        ...


@runtime_checkable
class AfterMoveSelectedEffect(Protocol[ActionT]):
    """只在行动选定后、执行前转换精确带权后继状态转移。"""

    def after_move_selected(
        self,
        context: ActionEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """返回新的带权转移集合，用于锁招等选招后机制。"""
        ...


@runtime_checkable
class AfterDamageEffect(Protocol[ActionT]):
    """只在伤害结算后转换精确带权后继状态转移。"""

    def after_damage(
        self,
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """返回新的带权转移集合，用于反伤、吸血或消耗品等后续扩展。"""
        ...


@runtime_checkable
class AfterDamageVolatileStatusEffect(Protocol[ActionT]):
    """只在伤害完成后发出类型化临时状态请求，不直接写入目标状态。"""

    def after_damage_volatile_status_attempts(
        self,
        context: MoveEffectContext[ActionT],
    ) -> tuple[VolatileStatusAttempt, ...]:
        """返回需要经过目标特性等阻止 effect 裁决的状态请求。"""
        ...


@runtime_checkable
class TurnEndEffect(Protocol):
    """只在回合结束阶段转换精确带权后继状态转移。"""

    def on_turn_end(
        self,
        context: TurnEndEffectContext,
        transitions: TransitionSet,
    ) -> TransitionSet:
        """返回新的带权转移集合，用于回合结束伤害、回复和清理。"""
        ...


__all__ = [
    "AbilityEffect",
    "ActionEffectContext",
    "ActionOrder",
    "ActionOrderEffectContext",
    "ActionValidationReport",
    "ActionValidationResult",
    "AfterDamageEffect",
    "AfterDamageVolatileStatusEffect",
    "AfterMoveSelectedEffect",
    "BattleEffect",
    "BattleSide",
    "BeforeMoveEffect",
    "DamageEffectApplication",
    "DamageEffectContext",
    "DamageEffectResult",
    "DamageEffectStage",
    "EffectCapabilityCoverage",
    "EffectSourceKind",
    "ItemEffect",
    "EffectCoverage",
    "EffectCoverageStatus",
    "ModifyActionOrderEffect",
    "ModifyDamageEffect",
    "MoveEffect",
    "MoveEffectContext",
    "PreventVolatileStatusEffect",
    "StatusPreventionReport",
    "StatusPreventionResult",
    "TransitionSet",
    "TurnEndEffect",
    "TurnEndEffectContext",
    "ValidateActionEffect",
    "VolatileStatusAttempt",
    "VolatileStatusEffectContext",
]
