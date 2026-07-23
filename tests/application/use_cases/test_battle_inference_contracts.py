from __future__ import annotations

from fractions import Fraction

from pokeop.application.use_cases.infer_battle import (
    BattleInferenceCommand,
    BattleInferenceResult,
    BattleProbability,
    ConfigurationCoverage,
    ConfigurationWeighting,
    ConfigurationWeightSource,
    InvalidBattleInferenceContract,
    MechanismCoverage,
    OutcomeCounts,
    PolicyDescriptor,
    RepresentativePathReference,
    TerminationCount,
)
from pokeop.domain.battle.action_policy import (
    ActionDistribution,
    FirstLegalActionPolicy,
    UniformRandomPolicy,
)
from pokeop.domain.battle.inference_outcome import (
    BattleSide,
    TerminalOutcome,
    TerminationReason,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


def _result() -> BattleInferenceResult:
    """创建同时覆盖胜、负、平和解释字段的最小合法结果。"""
    attacker_policy = UniformRandomPolicy[str]()
    defender_policy = FirstLegalActionPolicy[str]()
    return BattleInferenceResult(
        rules=BattleInferenceRules(),
        observer=BattleSide.ATTACKER,
        win_probability=BattleProbability(Fraction(1, 2)),
        loss_probability=BattleProbability(Fraction(1, 4)),
        draw_probability=BattleProbability(Fraction(1, 4)),
        expected_turns=Fraction(7, 2),
        attacker_policy=PolicyDescriptor.from_policy(attacker_policy),
        defender_policy=PolicyDescriptor.from_policy(defender_policy),
        configuration_coverage=ConfigurationCoverage(
            covered_configurations=6,
            total_configurations=8,
        ),
        configuration_weighting=ConfigurationWeighting(
            source=ConfigurationWeightSource.UNIFORM_ENUMERATION,
            description="候选配置等权枚举，不代表真实环境使用率",
        ),
        mechanism_coverage=MechanismCoverage(
            included=("HP", "PP", "命中"),
            excluded=("交换", "太晶化"),
        ),
        representative_paths=(
            RepresentativePathReference(TerminalOutcome.ATTACKER_WIN, "path:win:1"),
            RepresentativePathReference(TerminalOutcome.DEFENDER_WIN, "path:loss:1"),
            RepresentativePathReference(TerminalOutcome.DRAW, "path:draw:1"),
        ),
        outcome_counts=OutcomeCounts(attacker_wins=2, defender_wins=1, draws=1),
        termination_counts=(
            TerminationCount(TerminationReason.KNOCKOUT, 3),
            TerminationCount(TerminationReason.CYCLE_GUARD, 1),
        ),
    )


def test_inference_command_accepts_structural_fake_policy_without_state_model_dependency():
    """命令可先使用任意显式配置类型，后续 #21 接入 PokemonSpec 时无需改策略协议。"""

    class FakePolicy:
        @property
        def policy_id(self) -> str:
            return "fake"

        @property
        def description(self) -> str:
            return "测试策略"

        def distribution_for(
            self,
            legal_actions: tuple[str, ...],
        ) -> ActionDistribution[str]:
            return ActionDistribution.deterministic(legal_actions[0])

    command = BattleInferenceCommand(
        rules=BattleInferenceRules(),
        attacker_configuration="dragonite-config-a",
        defender_configuration="weavile-config-b",
        attacker_policy=FakePolicy(),
        defender_policy=UniformRandomPolicy[str](),
    )

    assert command.attacker_configuration == "dragonite-config-a"
    assert command.attacker_policy.policy_id == "fake"
    assert command.observer is BattleSide.ATTACKER


def test_inference_result_exposes_normalized_probabilities_and_full_explanation_contract():
    """固定配置战斗概率、配置覆盖和真实使用率声明必须通过不同字段表达。"""
    result = _result()

    assert result.probability_total == Fraction(1, 1)
    assert result.expected_turns == Fraction(7, 2)
    assert result.configuration_coverage.coverage_ratio == Fraction(3, 4)
    assert result.configuration_weighting.represents_external_usage is False
    assert result.outcome_counts is not None
    assert result.outcome_counts.total == 4
    assert {item.outcome for item in result.representative_paths} == {
        TerminalOutcome.ATTACKER_WIN,
        TerminalOutcome.DEFENDER_WIN,
        TerminalOutcome.DRAW,
    }
    assert result.mechanism_coverage.excluded == ("交换", "太晶化")


def test_external_usage_weight_requires_explicit_source():
    """只有外部使用率来源可以被调用方解释为真实环境配置权重。"""
    uniform = ConfigurationWeighting(
        source=ConfigurationWeightSource.UNIFORM_ENUMERATION,
        description="所有候选配置等权",
    )
    external = ConfigurationWeighting(
        source=ConfigurationWeightSource.EXTERNAL_USAGE_DATA,
        description="来自已注明版本和时间范围的外部使用率数据",
    )

    assert uniform.represents_external_usage is False
    assert external.represents_external_usage is True


def test_inference_result_rejects_non_normalized_win_loss_draw_probability():
    """胜、负、平概率必须精确等于 1，不能依靠展示层四舍五入掩盖缺失分支。"""
    base = _result()

    try:
        BattleInferenceResult(
            rules=base.rules,
            observer=base.observer,
            win_probability=BattleProbability(Fraction(1, 2)),
            loss_probability=BattleProbability(Fraction(1, 3)),
            draw_probability=BattleProbability(Fraction(1, 10)),
            expected_turns=None,
            attacker_policy=base.attacker_policy,
            defender_policy=base.defender_policy,
            configuration_coverage=base.configuration_coverage,
            configuration_weighting=base.configuration_weighting,
            mechanism_coverage=base.mechanism_coverage,
        )
    except InvalidBattleInferenceContract as exc:
        assert "sum exactly to 1" in str(exc)
    else:
        raise AssertionError("expected non-normalized outcome probabilities to fail")


def test_configuration_coverage_is_not_a_battle_probability_type():
    """覆盖率拥有配置计数语义，不能被当作固定配置战斗胜率对象传递。"""
    coverage = ConfigurationCoverage(covered_configurations=1, total_configurations=2)

    assert coverage.coverage_ratio == Fraction(1, 2)
    assert not isinstance(coverage, BattleProbability)
