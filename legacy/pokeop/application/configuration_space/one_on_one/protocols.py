"""定义批量执行器与结果持久化之间的 application Protocol。"""

from __future__ import annotations

from typing import Protocol

from pokeop.application.configuration_space.one_on_one.commands import (
    NormalizedOneOnOneConfiguration,
)
from pokeop.application.configuration_space.one_on_one.model_base import (
    OneOnOneActionPolicy,
)
from pokeop.application.configuration_space.one_on_one.results import (
    ConfigurationExecutionResult,
)


class ConfigurationPairExecutor(Protocol):
    """定义流式批处理调用单配置求解器时依赖的 application 端口。"""

    def execute(
        self,
        configuration: NormalizedOneOnOneConfiguration,
        *,
        attacker_policy: OneOnOneActionPolicy,
        defender_policy: OneOnOneActionPolicy,
    ) -> ConfigurationExecutionResult:
        """执行一个规范化配置并返回成功、失败或截断的显式结果。

        Args:
            configuration: 已绑定规则轴、计算修订和规范化技能组的配置。
            attacker_policy: 攻击方行动策略。
            defender_policy: 防守方行动策略。

        Returns:
            不携带完整状态图的单配置执行结果；按需图由独立请求重新构建。
        """
        ...


class ConfigurationResultSink(Protocol):
    """定义批处理执行器持续写入单配置结果时依赖的持久化端口。"""

    def append(self, task_id: str, result: ConfigurationExecutionResult) -> None:
        """把一个终态结果记入任务分母，失败和截断同样必须持久化。

        Args:
            task_id: 后台任务稳定标识。
            result: 成功、失败或截断的类型化结果。
        """
        ...


__all__ = [
    "ConfigurationPairExecutor",
    "ConfigurationResultSink",
]
