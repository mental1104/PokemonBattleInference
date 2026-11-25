"""原独立五状态门禁、规则策略与随机端口消费的完整差分，不改变默认回合。"""
from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.domain.battle.flow.action_gate import ActionGatePipeline, default_action_gate_pipeline
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.rulesets.status_rules import BurnPolicy, ConfusionPolicy, FreezePolicy, InfatuationPolicy, ParalysisPolicy, PoisonPolicy, StatusRules, TurnBasedSleepPolicy
from pokeop.domain.battle.status.gates import ConfusionGate, FreezeGate, InfatuationGate, ParalysisGate, SleepGate
from pokeop.domain.battle.status.state import BadPoisonStatus, BurnStatus, CombatantStatus, ConfusionStatus, FlinchStatus, FreezeStatus, InfatuationStatus, ParalysisStatus, PoisonStatus, SleepStatus
from tests.domain.battle.helpers import FixedBattleRandom, MoveProfileFactory
from tests.migration.test_core_damage import ExactFraction
from tests.migration.test_core_state import StatusSnapshot, _StateOracle

Gate = Literal["sleep", "freeze", "paralysis", "infatuation", "confusion"]


class _Contract(BaseModel):
    """完整只读诊断边界，未知字段不能被测试忽略。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Rules(_Contract):
    """完整原StatusRules字段，包含门禁以外已迁移的速度/伤害/残余策略值。"""
    sleep_wake_chances: tuple[ExactFraction, ...]
    freeze_thaw_chance: ExactFraction
    allow_thaw_move_override: bool
    paralysis_speed_multiplier: ExactFraction
    full_paralysis_chance: ExactFraction
    burn_physical_multiplier: ExactFraction
    burn_residual_fraction: ExactFraction
    poison_residual_fraction: ExactFraction
    bad_poison_base_fraction: ExactFraction
    confusion_self_hit_chance: ExactFraction
    infatuation_immobilize_chance: ExactFraction

    @classmethod
    def original(cls, rules: StatusRules) -> _Rules:
        """只投影原策略值；sleep原生产profile是明确TurnBasedSleepPolicy。"""
        assert isinstance(rules.sleep_policy, TurnBasedSleepPolicy)
        return cls(sleep_wake_chances=tuple(_StateOracle.fraction(value) for value in rules.sleep_policy.wake_chances),
            freeze_thaw_chance=_StateOracle.fraction(rules.freeze_policy.thaw_chance), allow_thaw_move_override=rules.freeze_policy.allow_thaw_move_override,
            paralysis_speed_multiplier=_StateOracle.fraction(rules.paralysis_policy.speed_multiplier), full_paralysis_chance=_StateOracle.fraction(rules.paralysis_policy.full_paralysis_chance),
            burn_physical_multiplier=_StateOracle.fraction(rules.burn_policy.physical_damage_multiplier), burn_residual_fraction=_StateOracle.fraction(rules.burn_policy.residual_damage_fraction),
            poison_residual_fraction=_StateOracle.fraction(rules.poison_policy.residual_damage_fraction), bad_poison_base_fraction=_StateOracle.fraction(rules.poison_policy.bad_poison_base_fraction),
            confusion_self_hit_chance=_StateOracle.fraction(rules.confusion_policy.self_hit_chance), infatuation_immobilize_chance=_StateOracle.fraction(rules.infatuation_policy.immobilize_chance))


    def domain(self) -> StatusRules:
        """将完整边界事实还原为原策略；所有验证直接由原policy构造器执行。"""
        def fraction(value: ExactFraction) -> Fraction:
            """value为明确分数字符串；返回原精确Fraction，不重写验证。"""
            return Fraction(int(value.numerator), int(value.denominator))
        return StatusRules(TurnBasedSleepPolicy(tuple(fraction(value) for value in self.sleep_wake_chances)),
            FreezePolicy(fraction(self.freeze_thaw_chance), self.allow_thaw_move_override),
            ParalysisPolicy(fraction(self.paralysis_speed_multiplier), fraction(self.full_paralysis_chance)),
            BurnPolicy(fraction(self.burn_physical_multiplier), fraction(self.burn_residual_fraction)),
            PoisonPolicy(fraction(self.poison_residual_fraction), fraction(self.bad_poison_base_fraction)),
            ConfusionPolicy(fraction(self.confusion_self_hit_chance)), InfatuationPolicy(fraction(self.infatuation_immobilize_chance)))


class _Request(_Contract):
    """原完整状态、门禁顺序与固定RNG队列；该测试队列不属于公开生产ABI。"""
    status: StatusSnapshot
    mode: Literal["single", "default", "pipeline"]
    gate: Gate = "sleep"
    gates: tuple[Gate, ...] = ("sleep", "freeze", "paralysis", "infatuation", "confusion")
    thaws_user_when_frozen: bool
    chance_results: tuple[bool, ...]
    generation: int
    rules: _Rules | None = None


class _Reply(_Contract):
    """原完整结果及确切RNG消费，包括后续未消费队列长度。"""
    decision: Literal["allow", "block", "replace_with_self_hit"]
    updated_status: StatusSnapshot
    reason: str | None
    events: tuple[str, ...]
    probabilities: tuple[ExactFraction, ...]
    consumed: int
    remaining: int
    rules: _Rules


@dataclass(frozen=True)
class _Case:
    """所有expected均由原gate/pipeline和原规则直接生成。"""
    status: CombatantStatus
    generation: int
    mode: Literal["single", "default", "pipeline"]
    gate: Gate
    gates: tuple[Gate, ...]
    thaw_move: bool
    outcomes: tuple[bool, ...]
    rules: StatusRules | None = None

    def request(self) -> _Request:
        """返回Core完整事实，未预先决定阻断或替换结果。"""
        return _Request(status=_StateOracle.status(self.status), mode=self.mode, gate=self.gate, gates=self.gates,
            thaws_user_when_frozen=self.thaw_move, chance_results=self.outcomes, generation=self.generation,
            rules=None if self.rules is None else _Rules.original(self.rules))

    def original(self) -> _Reply:
        """执行唯一原五门禁或pipeline，不在oracle复制概率、计数或短路规则。"""
        ruleset = BattleRulesetProfile.from_generation_id(self.generation).build()
        if self.rules is not None:
            ruleset = replace(ruleset, status_rules=self.rules)
        move = MoveProfileFactory.thawing_physical() if self.thaw_move else MoveProfileFactory.physical()
        rng = FixedBattleRandom(list(self.outcomes))
        if self.mode == "default":
            result = default_action_gate_pipeline().check_before_action(status=self.status, move=move, ruleset=ruleset, rng=rng)
        else:
            constructors = {"sleep": SleepGate, "freeze": FreezeGate, "paralysis": ParalysisGate, "infatuation": InfatuationGate, "confusion": ConfusionGate}
            if self.mode == "single":
                result = constructors[self.gate]().check_before_action(status=self.status, move=move, ruleset=ruleset, rng=rng)
            else:
                result = ActionGatePipeline(tuple(constructors[gate]() for gate in self.gates)).check_before_action(status=self.status, move=move, ruleset=ruleset, rng=rng)
        return _Reply(decision=result.decision.value, updated_status=_StateOracle.status(result.updated_status), reason=result.reason, events=result.events,
            probabilities=tuple(_StateOracle.fraction(Fraction(value)) for value in rng.probabilities), consumed=len(self.outcomes) - len(rng.results),
            remaining=len(rng.results), rules=_Rules.original(ruleset.status_rules))


@pytest.fixture
def status_gates_runner() -> Path:
    """真实独立Core诊断程序；缺失时显式skip，不能用Python替代。"""
    configured = os.environ.get("PBI_STATUS_GATES_RUNNER")
    if configured is None:
        pytest.skip("PBI_STATUS_GATES_RUNNER is required")
    runner = Path(configured)
    assert runner.is_file()
    return runner


class TestCoreStatusActionGates:
    """原全部单门禁/默认与自定义顺序、代际profile、精确策略和不变状态。"""

    def test_all_profiles_original_gates_and_exact_random_consumption(self, status_gates_runner: Path) -> None:
        """九代际与1440种输入完整比较；包括无关状态、首阻断短路、醒来事件和末项重复。"""
        generator = random.Random(193705)
        majors = (None, SleepStatus(), SleepStatus(1), SleepStatus(3), SleepStatus(99), FreezeStatus(), ParalysisStatus(), BurnStatus(), PoisonStatus(), BadPoisonStatus(5))
        cases: list[_Case] = []
        gates: tuple[Gate, ...] = ("sleep", "freeze", "paralysis", "infatuation", "confusion")
        for generation in range(1, 10):
            for major in majors:
                for index in range(8):
                    volatile = tuple(value for bit, value in enumerate((ConfusionStatus(3), InfatuationStatus("target"), FlinchStatus())) if index & (1 << bit))
                    for hit in (True, False):
                        mode = "single" if index < 5 else "default" if index == 5 else "pipeline"
                        cases.append(_Case(CombatantStatus(major, frozenset(volatile)), generation, mode, gates[index % 5],
                            gates if index != 7 else tuple(reversed(gates)), bool(generator.getrandbits(1)), (hit,) * 8))
        base = BattleRulesetProfile.GEN9.build().status_rules
        for index in range(80):
            chance = generator.choice((Fraction(0), Fraction(1), Fraction(2, 7), Fraction(10**100 + 1, 10**101 + 3)))
            custom = StatusRules(TurnBasedSleepPolicy((chance, Fraction(1, 11))), FreezePolicy(chance, bool(index % 2)),
                ParalysisPolicy(Fraction(0), chance), BurnPolicy(Fraction(0), chance), PoisonPolicy(chance, chance), ConfusionPolicy(chance), InfatuationPolicy(chance))
            cases.append(_Case(CombatantStatus(majors[index % len(majors)], frozenset((ConfusionStatus(), InfatuationStatus(None)))),
                9, "default", "sleep", gates, bool(index % 2), tuple(bool(generator.getrandbits(1)) for _ in range(8)), custom))
        assert base != cases[-1].rules
        expected = tuple(case.original() for case in cases)
        process = subprocess.run((str(status_gates_runner),), input="".join(case.request().model_dump_json(exclude={"rules"} if case.rules is None else set()) + "\n" for case in cases),
            text=True, capture_output=True, check=True, timeout=120)
        actual = tuple(_Reply.model_validate_json(line) for line in process.stdout.splitlines())
        assert actual == expected, process.stderr


    def test_original_policy_validation_and_empty_pipeline(self, status_gates_runner: Path) -> None:
        """所有原概率/倍率字段和空睡眠表/空管线错误逐条对照原构造器。"""
        baseline = _Rules.original(BattleRulesetProfile.GEN9.build().status_rules)
        negative = ExactFraction(numerator="-1", denominator="10")
        overflow = ExactFraction(numerator="11", denominator="10")
        invalid = [baseline.model_copy(update={"sleep_wake_chances": ()}),
            baseline.model_copy(update={"sleep_wake_chances": (negative,)}),
            baseline.model_copy(update={"sleep_wake_chances": (overflow,)})]
        for field in ("freeze_thaw_chance", "full_paralysis_chance", "burn_residual_fraction", "poison_residual_fraction",
                      "bad_poison_base_fraction", "confusion_self_hit_chance", "infatuation_immobilize_chance"):
            invalid.extend(baseline.model_copy(update={field: value}) for value in (negative, overflow))
        invalid.extend(baseline.model_copy(update={field: negative}) for field in ("paralysis_speed_multiplier", "burn_physical_multiplier"))
        expected: list[str] = []
        requests: list[_Request] = []
        for rules in invalid:
            with pytest.raises(ValueError) as error:
                rules.domain()
            expected.append(str(error.value))
            requests.append(_Request(status=_StateOracle.status(CombatantStatus()), mode="default", thaws_user_when_frozen=False,
                chance_results=(), generation=9, rules=rules))
        with pytest.raises(ValueError) as error:
            ActionGatePipeline(())
        expected.append(str(error.value))
        requests.append(_Request(status=_StateOracle.status(CombatantStatus()), mode="pipeline", gates=(), thaws_user_when_frozen=False,
            chance_results=(), generation=9, rules=baseline))
        process = subprocess.run((str(status_gates_runner),), input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=120)
        class Error(_Contract):
            """单条原策略整体失败，不接受任何部分状态结果。"""
            error: str
        actual = tuple(Error.model_validate_json(line).error for line in process.stdout.splitlines())
        assert actual == tuple(expected), process.stderr
