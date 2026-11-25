"""在常量额外空间内聚合配置覆盖、精确概率和有界排行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from pokeop.application.use_cases.stream_configuration_pairs.models import (
    ConfigurationPairAggregate,
    ConfigurationPairExecutionResult,
    ConfigurationPairExecutionStatus,
    ConfigurationPairProgress,
    ConfigurationPairRankingEntry,
    ConfigurationPairStopReason,
    FractionComplexitySummary,
)


@dataclass(slots=True)
class _FractionComplexityAccumulator:
    """跟踪 Fraction 聚合中间值的分子、分母位数增长。"""

    observed_fraction_count: int = 0
    max_numerator_bits: int = 0
    max_denominator_bits: int = 0

    def observe(self, *values: Fraction) -> None:
        """记录一组中间值的分子和分母位数。

        Args:
            values: 配置权重、战斗概率或累加后的精确 Fraction。
        """
        for value in values:
            self.observed_fraction_count += 1
            self.max_numerator_bits = max(
                self.max_numerator_bits,
                abs(value.numerator).bit_length(),
            )
            self.max_denominator_bits = max(
                self.max_denominator_bits,
                value.denominator.bit_length(),
            )

    def finish(
        self,
        win: Fraction,
        loss: Fraction,
        draw: Fraction,
    ) -> FractionComplexitySummary:
        """冻结最终概率和最大中间复杂度摘要。

        Args:
            win: 最终配置层加权胜率。
            loss: 最终配置层加权负率。
            draw: 最终配置层加权平局率。

        Returns:
            便于评估跨配置 Fraction 增长成本的轻量摘要。
        """
        return FractionComplexitySummary(
            observed_fraction_count=self.observed_fraction_count,
            max_numerator_bits=self.max_numerator_bits,
            max_denominator_bits=self.max_denominator_bits,
            final_win_numerator_bits=abs(win.numerator).bit_length(),
            final_win_denominator_bits=win.denominator.bit_length(),
            final_loss_numerator_bits=abs(loss.numerator).bit_length(),
            final_loss_denominator_bits=loss.denominator.bit_length(),
            final_draw_numerator_bits=abs(draw.numerator).bit_length(),
            final_draw_denominator_bits=draw.denominator.bit_length(),
        )


@dataclass(slots=True)
class _TopKAccumulator:
    """每类只保留 K 个轻量条目，避免缓存全部配置结果。"""

    limit: int
    win_entries: list[ConfigurationPairRankingEntry] = field(default_factory=list)
    expected_turn_entries: list[ConfigurationPairRankingEntry] = field(
        default_factory=list
    )
    node_entries: list[ConfigurationPairRankingEntry] = field(default_factory=list)

    def add(self, result: ConfigurationPairExecutionResult) -> None:
        """把成功配置加入胜率、期望回合和节点规模排行。

        Args:
            result: 已验证概率守恒的成功轻量结果。
        """
        if result.status is not ConfigurationPairExecutionStatus.SUCCEEDED:
            return
        if (
            result.win_probability is None
            or result.loss_probability is None
            or result.draw_probability is None
        ):
            raise AssertionError("successful result probabilities were not narrowed")
        entry = ConfigurationPairRankingEntry(
            pair_id=result.pair_id,
            attacker_configuration_id=result.attacker_configuration_id,
            defender_configuration_id=result.defender_configuration_id,
            attacker_move_ids=result.attacker_move_ids,
            defender_move_ids=result.defender_move_ids,
            win_probability=result.win_probability,
            loss_probability=result.loss_probability,
            draw_probability=result.draw_probability,
            expected_turns=result.expected_turns,
            node_count=result.node_count,
            edge_count=result.edge_count,
        )
        self.win_entries.append(entry)
        self.win_entries.sort(key=lambda item: (-item.win_probability, item.pair_id))
        del self.win_entries[self.limit :]

        if entry.expected_turns is not None:
            self.expected_turn_entries.append(entry)
            self.expected_turn_entries.sort(
                key=lambda item: (
                    -item.expected_turns
                    if item.expected_turns is not None
                    else Fraction(0),
                    item.pair_id,
                )
            )
            del self.expected_turn_entries[self.limit :]

        self.node_entries.append(entry)
        self.node_entries.sort(
            key=lambda item: (-item.node_count, -item.edge_count, item.pair_id)
        )
        del self.node_entries[self.limit :]


@dataclass(slots=True)
class AggregateState:
    """维护常量级计数、精确概率和有界 Top-K 状态。

    Args:
        top_k: 每类排行允许保留的轻量条目数量。
    """

    top_k: int
    processed_pair_count: int = 0
    succeeded_count: int = 0
    truncated_count: int = 0
    failed_count: int = 0
    attempted_weight: Fraction = Fraction(0)
    completed_weight: Fraction = Fraction(0)
    weighted_win_probability: Fraction = Fraction(0)
    weighted_loss_probability: Fraction = Fraction(0)
    weighted_draw_probability: Fraction = Fraction(0)
    cumulative_node_count: int = 0
    cumulative_edge_count: int = 0
    fraction_complexity: _FractionComplexityAccumulator = field(
        default_factory=_FractionComplexityAccumulator
    )
    rankings: _TopKAccumulator = field(init=False)

    def __post_init__(self) -> None:
        """创建与命令一致的有界排行聚合器。"""
        self.rankings = _TopKAccumulator(self.top_k)

    def add(self, result: ConfigurationPairExecutionResult) -> None:
        """把一个轻量结果合入计数、资源、权重、概率和排行。

        Args:
            result: sink 同样可消费且不持有完整图的单配置结果。
        """
        self.processed_pair_count += 1
        self.attempted_weight += result.configuration_weight
        self.cumulative_node_count += result.node_count
        self.cumulative_edge_count += result.edge_count
        self.fraction_complexity.observe(
            result.configuration_weight,
            self.attempted_weight,
        )

        if result.status is ConfigurationPairExecutionStatus.SUCCEEDED:
            self._add_success(result)
            return
        if result.status is ConfigurationPairExecutionStatus.TRUNCATED:
            self.truncated_count += 1
            return
        self.failed_count += 1

    def _add_success(self, result: ConfigurationPairExecutionResult) -> None:
        """聚合一个成功结果的配置权重和战斗随机概率。

        Args:
            result: 胜负平严格和为 1 的成功结果。
        """
        self.succeeded_count += 1
        if (
            result.win_probability is None
            or result.loss_probability is None
            or result.draw_probability is None
        ):
            raise AssertionError("successful result probabilities were not narrowed")
        weighted_win = result.configuration_weight * result.win_probability
        weighted_loss = result.configuration_weight * result.loss_probability
        weighted_draw = result.configuration_weight * result.draw_probability
        self.completed_weight += result.configuration_weight
        self.weighted_win_probability += weighted_win
        self.weighted_loss_probability += weighted_loss
        self.weighted_draw_probability += weighted_draw
        self.fraction_complexity.observe(
            result.win_probability,
            result.loss_probability,
            result.draw_probability,
            weighted_win,
            weighted_loss,
            weighted_draw,
            self.completed_weight,
            self.weighted_win_probability,
            self.weighted_loss_probability,
            self.weighted_draw_probability,
        )
        self.rankings.add(result)

    def progress(self, *, total_pair_count: int) -> ConfigurationPairProgress:
        """冻结当前配置数量和累计资源进度。

        Args:
            total_pair_count: 未受运行预算裁剪的完整配置对数量。

        Returns:
            配置数量与图资源双轴进度快照。
        """
        return ConfigurationPairProgress(
            processed_pair_count=self.processed_pair_count,
            total_pair_count=total_pair_count,
            succeeded_count=self.succeeded_count,
            truncated_count=self.truncated_count,
            failed_count=self.failed_count,
            attempted_weight=self.attempted_weight,
            completed_weight=self.completed_weight,
            cumulative_node_count=self.cumulative_node_count,
            cumulative_edge_count=self.cumulative_edge_count,
        )

    def finish(
        self,
        *,
        stop_reason: ConfigurationPairStopReason,
        total_pair_count: int,
    ) -> ConfigurationPairAggregate:
        """冻结最终聚合，不对未完成配置权重重新归一化。

        Args:
            stop_reason: 执行循环停止领取新配置的原因。
            total_pair_count: 完整候选笛卡尔积数量。

        Returns:
            可持续写入 sink 的完整或部分精确聚合。
        """
        return ConfigurationPairAggregate(
            stop_reason=(
                ConfigurationPairStopReason.COMPLETED
                if self.processed_pair_count == total_pair_count
                else stop_reason
            ),
            total_pair_count=total_pair_count,
            processed_pair_count=self.processed_pair_count,
            unprocessed_pair_count=total_pair_count - self.processed_pair_count,
            succeeded_count=self.succeeded_count,
            truncated_count=self.truncated_count,
            failed_count=self.failed_count,
            attempted_weight=self.attempted_weight,
            completed_weight=self.completed_weight,
            weighted_win_probability=self.weighted_win_probability,
            weighted_loss_probability=self.weighted_loss_probability,
            weighted_draw_probability=self.weighted_draw_probability,
            cumulative_node_count=self.cumulative_node_count,
            cumulative_edge_count=self.cumulative_edge_count,
            top_win_probability=tuple(self.rankings.win_entries),
            top_expected_turns=tuple(self.rankings.expected_turn_entries),
            top_node_count=tuple(self.rankings.node_entries),
            fraction_complexity=self.fraction_complexity.finish(
                self.weighted_win_probability,
                self.weighted_loss_probability,
                self.weighted_draw_probability,
            ),
        )


__all__ = ["AggregateState"]
