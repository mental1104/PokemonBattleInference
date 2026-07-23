from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.move_execution_policy import MoveExecutionPolicy


class BattleFormat(str, Enum):
    """首版战斗推演支持的对战形式。"""

    ONE_ON_ONE_SINGLES = "one-on-one-singles"


class SwitchingPolicy(str, Enum):
    """战斗中是否允许主动交换宝可梦。"""

    DISABLED = "disabled"


class RepetitionResolution(str, Enum):
    """检测到重复状态时的处理语义。"""

    DECLARE_DRAW = "declare-draw"
    CONTINUE = "continue"


class CycleResolution(str, Enum):
    """状态图确认形成封闭循环时的处理语义。"""

    DECLARE_DRAW = "declare-draw"
    SOLVE_ABSORPTION_PROBABILITY = "solve-absorption-probability"


class InvalidBattleInferenceRules(ValueError):
    """表示规则值越界或不属于首版 1v1 能力范围。"""


@dataclass(frozen=True, slots=True)
class BattleInferenceRules:
    """冻结一次 1v1 多回合推演使用的规则语义。

    ``max_turns`` 只是产品运行保护；重复状态与封闭循环仍由各自策略处理，后续求解器
    不得把回合上限冒充为循环证明。首版明确禁止交换与三种形态变换，避免调用方通过
    默认值差异隐式扩大规则范围。伤害公式与通用招式执行规则分别由显式 policy 承担，
    从而让状态键完整包含会影响后续结果的规则配置。
    """

    ruleset_id: str = "pokemon-champion"
    version_group_id: int = 25
    level: int = 50
    battle_format: BattleFormat = BattleFormat.ONE_ON_ONE_SINGLES
    switching_policy: SwitchingPolicy = SwitchingPolicy.DISABLED
    allow_terastallization: bool = False
    allow_mega_evolution: bool = False
    allow_dynamax: bool = False
    max_turns: int | None = 100
    repetition_resolution: RepetitionResolution = RepetitionResolution.DECLARE_DRAW
    cycle_resolution: CycleResolution = CycleResolution.DECLARE_DRAW
    damage_policy: DamagePolicy = field(default_factory=DamagePolicy)
    move_execution_policy: MoveExecutionPolicy = field(
        default_factory=MoveExecutionPolicy
    )

    def __post_init__(self) -> None:
        """校验规则标识、首版能力边界以及组合 policy 类型。

        Raises:
            InvalidBattleInferenceRules: 任一规则字段不满足首版推演合同时抛出。
        """
        if not self.ruleset_id or self.ruleset_id != self.ruleset_id.strip():
            raise InvalidBattleInferenceRules(
                "ruleset_id must be a non-empty normalized identifier"
            )
        if isinstance(self.version_group_id, bool) or self.version_group_id <= 0:
            raise InvalidBattleInferenceRules("version_group_id must be greater than 0")
        if isinstance(self.level, bool) or not 1 <= self.level <= 100:
            raise InvalidBattleInferenceRules("level must be between 1 and 100")
        if self.battle_format is not BattleFormat.ONE_ON_ONE_SINGLES:
            raise InvalidBattleInferenceRules(
                "the first battle inference contract only supports 1v1 singles"
            )
        if self.switching_policy is not SwitchingPolicy.DISABLED:
            raise InvalidBattleInferenceRules(
                "the first battle inference contract does not allow switching"
            )
        enabled_transformations = tuple(
            name
            for name, enabled in (
                ("terastallization", self.allow_terastallization),
                ("mega evolution", self.allow_mega_evolution),
                ("dynamax", self.allow_dynamax),
            )
            if enabled
        )
        if enabled_transformations:
            raise InvalidBattleInferenceRules(
                "unsupported transformations enabled: "
                + ", ".join(enabled_transformations)
            )
        if self.max_turns is not None and (
            isinstance(self.max_turns, bool) or self.max_turns <= 0
        ):
            raise InvalidBattleInferenceRules(
                "max_turns must be greater than 0 when configured"
            )
        if not isinstance(self.repetition_resolution, RepetitionResolution):
            raise InvalidBattleInferenceRules(
                "repetition_resolution must be a RepetitionResolution"
            )
        if not isinstance(self.cycle_resolution, CycleResolution):
            raise InvalidBattleInferenceRules(
                "cycle_resolution must be a CycleResolution"
            )
        if not isinstance(self.damage_policy, DamagePolicy):
            raise InvalidBattleInferenceRules("damage_policy must be a DamagePolicy")
        if not isinstance(self.move_execution_policy, MoveExecutionPolicy):
            raise InvalidBattleInferenceRules(
                "move_execution_policy must be a MoveExecutionPolicy"
            )
