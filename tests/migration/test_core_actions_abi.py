"""正式行动 ABI 与原合法行动生成器、两个精确选招策略差分。"""
from __future__ import annotations

import random
import subprocess
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pokeop.domain.battle.action_policy import FirstLegalActionPolicy, UniformRandomPolicy
from pokeop.domain.battle.actions import BattleAction, StandardLegalActionGenerator, StruggleAction, UseMoveAction
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.state import BattleState
from tests.migration.test_core_damage import ExactFraction, damage_runner
from tests.migration.test_core_state import BattleSnapshot, _StateOracle, _reference


class ActionStrategy(StrEnum):
    """原实现实际提供的两个稳定策略，不能把任意字符串当成已支持策略。"""
    uniform = "uniform-random"
    first = "first-legal-action"


class _Contract(BaseModel):
    """测试传输模型冻结并拒绝未知字段，缺失身份不允许伪通过。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class MoveAction(_Contract):
    """普通招式完整身份，运行时 slot_id 不等于招式序号。"""
    kind: Literal["use-move"] = "use-move"
    side: BattleSide
    move_id: int
    priority: int
    slot_id: int


class SimpleAction(_Contract):
    """没有普通槽位身份的挣扎/濒死占位，不附带虚构招式 ID。"""
    kind: Literal["struggle", "pass"]
    side: BattleSide


Action = Annotated[MoveAction | SimpleAction, Field(discriminator="kind")]


class Selection(_Contract):
    """一个具体行动与精确玩家选择概率。"""
    action: Action
    probability: ExactFraction


class ActionsOperation(_Contract):
    """正式完整状态输入；不复制 C++ 行动生成或筛选规则。"""
    kind: Literal["legal_actions"] = "legal_actions"
    state: BattleSnapshot
    side: BattleSide
    policy: ActionStrategy


class ActionsResult(_Contract):
    """全部合法集合和实际策略分布逐项核对，不能只比较数量。"""
    kind: Literal["legal_actions"] = "legal_actions"
    actions: tuple[Action, ...]
    selections: tuple[Selection, ...]


class ActionsBatch(_Contract):
    """有界正式操作批次，不要求数据库或外部服务。"""
    schema_version: Literal[1] = 1
    operations: tuple[ActionsOperation, ...]


class ActionsEnvelope(_Contract):
    """成功信封必须含准确引擎/规则版本和完整结果。"""
    schema_version: Literal[1]
    engine_version: Literal["0.10.0"]
    rules_version: Literal["calculation-rules.v10"]
    results: tuple[ActionsResult, ...]


class _ActionOracle:
    """只适配旧类型和调用旧算法，不手写 PP/禁用/锁招筛选或概率公式。"""
    @staticmethod
    def action(value: BattleAction) -> MoveAction | SimpleAction:
        """value 为旧类型化行动；返回完整协议身份，保留互斥字段。"""
        if isinstance(value, UseMoveAction):
            return MoveAction(side=value.side, move_id=value.move_id, priority=value.priority, slot_id=value.slot_id)
        return SimpleAction(kind="struggle" if isinstance(value, StruggleAction) else "pass", side=value.side)

    @classmethod
    def expected(cls, state: BattleState, side: BattleSide, strategy: ActionStrategy) -> ActionsResult:
        """state/side 为旧不可变输入，strategy 选择原策略；返回旧公开生成器和策略的精确完整结果。"""
        actions = StandardLegalActionGenerator().generate(state, side)
        distribution = (UniformRandomPolicy[BattleAction]().distribution_for(actions) if strategy is ActionStrategy.uniform
                        else FirstLegalActionPolicy[BattleAction]().distribution_for(actions))
        return ActionsResult(actions=tuple(cls.action(value) for value in actions), selections=tuple(
            Selection(action=cls.action(value.action), probability=_StateOracle.fraction(value.probability)) for value in distribution.selections))


class TestActionsABI:
    """随机真实状态覆盖两侧、两策略及槽位身份/顺序/PP/禁用/锁招/濒死。"""
    def test_actions_and_exact_policies_match_python(self, damage_runner: Path) -> None:
        """damage_runner 为当前构建目录；64 节点×双方×两策略的 256 完整结果全部精确一致。"""
        randomizer = random.Random(9021)
        operations: list[ActionsOperation] = []
        expected: list[ActionsResult] = []
        for _ in range(64):
            state = _reference()
            for side in BattleSide:
                battler = state.battler(side)
                slots = tuple(replace(slot, current_pp=randomizer.choice((0, slot.max_pp)),
                    is_disabled=randomizer.choice((True, False))) for slot in battler.move_slots)
                if randomizer.choice((True, False)):
                    slots = slots[::-1]
                battler = replace(battler, spec=replace(battler.spec, item=DamageItem.CHOICE_BAND),
                    move_slots=slots, current_hp=randomizer.choice((0, battler.current_hp)))
                battler = battler.with_choice_lock(randomizer.choice((None, *(slot.move_id for slot in slots))))
                state = state.with_battler(side, battler)
            for side in BattleSide:
                for strategy in ActionStrategy:
                    operations.append(ActionsOperation(state=_StateOracle.snapshot(state), side=side, policy=strategy))
                    expected.append(_ActionOracle.expected(state, side, strategy))
        batches = tuple(ActionsBatch(operations=tuple(operations[index:index + 64])) for index in range(0, len(operations), 64))
        result = subprocess.run([str(damage_runner.parent / "pbi_abi_vectors")], input="\n".join(value.model_dump_json() for value in batches) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        lines = result.stdout.splitlines()
        assert len(lines) == len(batches)
        actual = [value for line in lines for value in ActionsEnvelope.model_validate_json(line).results]
        assert actual == expected
