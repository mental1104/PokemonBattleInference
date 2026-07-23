"""定义配置空间共享错误、枚举和整数校验辅助函数。"""

from __future__ import annotations

from enum import Enum


def _is_integer(value: object) -> bool:
    """返回 value 是否为排除 bool 的真正整数。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_integer(value: object) -> bool:
    """返回 value 是否为严格大于零且排除 bool 的整数。"""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


class ConfigurationSpaceError(ValueError):
    """表示配置空间输入、候选过滤或组合规模违反了 application 合同。"""


class MechanismSupportStatus(str, Enum):
    """描述 repository 候选机制在进入 domain factory 前的覆盖状态。"""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class StatEnumerationMode(str, Enum):
    """选择使用固定能力预设，或对显式离散 EV/性格集合进行受控枚举。"""

    PRESET = "preset"
    CONTROLLED = "controlled"


class ConfigurationWeightAssumption(str, Enum):
    """声明配置权重只用于覆盖统计时采用的均匀假设。"""

    UNIFORM_RAW_CONFIGURATION = "uniform_raw_configuration"
    UNIFORM_EQUIVALENCE_CLASS = "uniform_equivalence_class"



__all__ = [
    "ConfigurationSpaceError",
    "ConfigurationWeightAssumption",
    "MechanismSupportStatus",
    "StatEnumerationMode",
]
