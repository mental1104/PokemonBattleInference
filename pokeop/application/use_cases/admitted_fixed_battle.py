"""在固定配置精确求解前统一执行双方机制准入。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.battle_candidate_pool.admission import (
    ValidateFixedMechanismSelectionCommand,
    ValidateFixedMechanismSelectionUseCase,
)
from pokeop.application.use_cases.fixed_battle_workflow import (
    FixedBattleSummaryResult,
    InferFixedBattleSummaryUseCase,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    InferFixedOneOnOneBattleCommand,
)


@dataclass(slots=True)
class RunAdmittedFixedBattleSummaryUseCase:
    """编排双方严格机制准入与单配置精确摘要。

    API 只负责把 HTTP DTO 转换为固定推演命令。招式、特性和道具是否允许进入当前
    calculation revision 的业务判断由该 application 用例承担，防止其他非 HTTP 调用方
    绕过准入后直接消耗状态图资源。

    Args:
        admission_use_case: 使用当前 repository/effect factory 验证固定机制选择的用例。
        summary_use_case: 构建轻量状态图并执行精确概率求解的固定摘要用例。
    """

    admission_use_case: ValidateFixedMechanismSelectionUseCase
    summary_use_case: InferFixedBattleSummaryUseCase

    def __post_init__(self) -> None:
        """校验两个委托对象使用正式 application 类型。"""
        if not isinstance(
            self.admission_use_case,
            ValidateFixedMechanismSelectionUseCase,
        ):
            raise ValueError(
                "admission_use_case must be ValidateFixedMechanismSelectionUseCase"
            )
        if not isinstance(self.summary_use_case, InferFixedBattleSummaryUseCase):
            raise ValueError(
                "summary_use_case must be InferFixedBattleSummaryUseCase"
            )

    def execute(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedBattleSummaryResult:
        """先验证双方固定机制，再执行唯一配置的精确摘要。

        Args:
            command: 已冻结双方配置、行动策略、规则轴和资源预算的固定推演命令。

        Returns:
            不持有完整探索图的精确胜负平与期望回合摘要。

        Raises:
            StrictMechanismAdmissionRejected: 任一招式、特性或道具不完整支持时抛出。
            BattleInferenceExecutionError: 状态图截断或精确 solver 未完成时由下层抛出。
        """
        for selection in (command.attacker, command.defender):
            self.admission_use_case.execute(
                ValidateFixedMechanismSelectionCommand(
                    rules=command.rules,
                    pokemon_id=selection.pokemon_id,
                    move_ids=selection.move_ids,
                    ability_identifier=selection.ability_identifier,
                    item_identifier=selection.item_identifier,
                )
            )
        return self.summary_use_case.execute(command)


__all__ = ["RunAdmittedFixedBattleSummaryUseCase"]
