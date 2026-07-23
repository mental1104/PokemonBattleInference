from __future__ import annotations

from fractions import Fraction

from pokeop.domain.battle.action_policy import (
    ActionDistribution,
    ActionPolicy,
    ActionSelection,
    FirstLegalActionPolicy,
    IllegalActionSelectionError,
    InvalidActionDistributionError,
    NoLegalActionsError,
    UniformRandomPolicy,
)


def test_uniform_random_policy_assigns_exact_equal_action_probabilities():
    """行动选择使用 Fraction 精确归一化，并保持调用方给出的稳定行动顺序。"""
    policy = UniformRandomPolicy[str]()

    distribution = policy.distribution_for(("ice-punch", "fake-out", "brick-break"))

    assert tuple(item.action for item in distribution.selections) == (
        "ice-punch",
        "fake-out",
        "brick-break",
    )
    assert tuple(item.probability for item in distribution.selections) == (
        Fraction(1, 3),
        Fraction(1, 3),
        Fraction(1, 3),
    )
    assert distribution.total_probability == Fraction(1, 1)


def test_first_legal_action_policy_is_deterministic_and_extensible():
    """确定性策略和 Protocol 使用同一分布合同，不要求求解器增加策略分支。"""
    policy = FirstLegalActionPolicy[str]()

    assert isinstance(policy, ActionPolicy)
    assert policy.distribution_for(("fake-out", "ice-punch")) == (
        ActionDistribution.deterministic("fake-out")
    )


def test_action_policy_rejects_empty_legal_action_set():
    """无合法行动由回合/终局规则处理，策略不能返回隐式空分布。"""
    for policy in (UniformRandomPolicy[str](), FirstLegalActionPolicy[str]()):
        try:
            policy.distribution_for(())
        except NoLegalActionsError:
            continue
        raise AssertionError("expected empty legal action set to be rejected")


def test_action_distribution_rejects_unnormalized_weights():
    """自定义策略也必须通过公共分布值对象提供精确且归一化的权重。"""
    try:
        ActionDistribution(
            (
                ActionSelection("ice-punch", Fraction(1, 4)),
                ActionSelection("brick-break", Fraction(1, 4)),
            )
        )
    except InvalidActionDistributionError as exc:
        assert "sum exactly to 1" in str(exc)
    else:
        raise AssertionError("expected unnormalized policy weights to be rejected")


def test_action_distribution_rejects_action_outside_legal_set():
    """策略只选择合法行动，不能制造或直接执行新的战斗动作。"""
    distribution = ActionDistribution.deterministic("unknown-move")

    try:
        distribution.validate_legal_actions(("ice-punch", "brick-break"))
    except IllegalActionSelectionError:
        pass
    else:
        raise AssertionError("expected illegal policy action to be rejected")


def test_fake_policy_can_extend_protocol_without_modifying_existing_policy_types():
    """新增脚本策略只需实现协议并返回公共分布，不依赖求解器或内置策略注册表。"""

    class FakeScriptedPolicy:
        @property
        def policy_id(self) -> str:
            return "fake-scripted"

        @property
        def description(self) -> str:
            return "优先使用击掌奇袭，否则使用第一个合法行动"

        def distribution_for(
            self,
            legal_actions: tuple[str, ...],
        ) -> ActionDistribution[str]:
            selected = "fake-out" if "fake-out" in legal_actions else legal_actions[0]
            distribution = ActionDistribution.deterministic(selected)
            distribution.validate_legal_actions(legal_actions)
            return distribution

    policy = FakeScriptedPolicy()

    assert isinstance(policy, ActionPolicy)
    assert policy.distribution_for(("ice-punch", "fake-out")) == (
        ActionDistribution.deterministic("fake-out")
    )
