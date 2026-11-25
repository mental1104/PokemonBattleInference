from __future__ import annotations


def normalize_effect_identifier(identifier: str) -> str:
    """把边界字符串规范化为招式、特性和道具 effect 使用的稳定标识。

    Args:
        identifier: 来自 application、测试或数据映射层的机制名称。

    Returns:
        去除首尾空白、统一小写并把连字符和空格转换为下划线的标识。
    """
    return identifier.strip().lower().replace("-", "_").replace(" ", "_")


__all__ = ["normalize_effect_identifier"]
