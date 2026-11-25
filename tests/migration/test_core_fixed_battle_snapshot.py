"""原snapshot实际重放/展开与Core纯域完整差分，不传全局图或复刻局部ID公式。"""
from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict
from fastapi import HTTPException
from pokeop.api.schemas.battle_exploration import BattleGraphExplorationResponse, battle_graph_exploration_response
from pokeop.api.routers.fixed_battle import _raise_http_error
from pokeop.api.routers.inference import _use_case
from pokeop.application import state_graph_projection as projection
from pokeop.application.solver.models import GraphNodeId, GraphEdgeId
from pokeop.application.state_graph_exploration import ExplorationCursor, ExplorationPathStep
from pokeop.application.state_graph_projection import BattleNodeProjection, ProbabilityProjection
from pokeop.application.use_cases import fixed_battle_snapshot as snapshot
from pokeop.application.use_cases.battle_exploration._support import expand_group, list_group_summaries
from pokeop.application.use_cases.battle_exploration.models import BattleReportStep, BattleReport, BattleExplorationPosition, BattleTransitionGroupsResult
from pokeop.application.use_cases.infer_one_on_one_battle import BATTLE_INFERENCE_CALCULATION_REVISION
from pokeop.application.use_cases.infer_one_on_one_battle._core import _PolicyDrivenBattleStateExpander
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.state import BattleState
from pokeop.domain.models.types import Type
from tests.migration.test_core_state import _reference, BattleSnapshot
from tests.migration.test_core_damage import TypeEfficacySnapshot
from tests.migration.test_core_actions_abi import ActionStrategy
from tests.migration.test_core_turn import Mode, _TurnCase, _TurnOracle, TurnLimits
from tests.migration.test_core_turn_abi import TurnOperation, PolicySelection, _ABIOracle


class _Contract(BaseModel):
    """精确进程边界；未知字段与缺字段全部失败。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Step(_Contract):
    """任意精度身份仅用十进制文本，不经过float64。"""
    source_node_id: str
    edge_id: str
    target_node_id: str


class _Input(_Contract):
    """真实策略回合与原cursor，不传预计算概率。"""
    turn: TurnOperation
    cursor: tuple[_Step, ...]


class _Reply(_Contract):
    """当前全部展开组及每个选择步骤完整替代事件历史。"""
    projection: BattleNodeProjection
    report_steps: tuple[BattleReportStep, ...]


class _Oracle:
    """调用原snapshot owning函数；状态输入不依赖PG或候选准备替身。"""
    @staticmethod
    def immune_state() -> BattleState:
        """真实Normal打Ghost且PP1000，让第六层ID超过uint64。"""
        state = _reference()
        for side in BattleSide:
            battler = state.battler(side)
            move = replace(battler.spec.moves[0], move=replace(battler.spec.moves[0].move,type=Type.NORMAL),max_pp=1000,priority=0)
            spec = replace(battler.spec,types=(Type.GHOST,),moves=(move,),item=DamageItem.UNKNOWN)
            state = state.with_battler(side,replace(battler,spec=spec,move_slots=(MoveSlotState(move.move_id,1000,1000),)))
        return replace(state,rules=replace(state.rules,max_turns=1,damage_policy=replace(state.rules.damage_policy,random_damage_multipliers=(1.0,))))

    @staticmethod
    def observe(state: BattleState, cursor: ExplorationCursor) -> tuple[_Reply, tuple[ExplorationPathStep, ...]]:
        """返回原完整投影/战报及真实下一层边，不复制ID、概率、事件算法。"""
        owner = snapshot.ExpandFixedBattleSnapshotUseCase(_use_case())
        case = _TurnCase(state,Mode.EXPAND)
        expander = _PolicyDrivenBattleStateExpander(_TurnOracle.resolver(state),_TurnOracle.policy(case.attacker_policy),_TurnOracle.policy(case.defender_policy))
        current,cumulative,report = owner._replay(state,expander,cursor)
        node = snapshot._node(node_id=cursor.current_node_id,state=current)
        edges = owner._expand_current(node,expander)
        groups = tuple(expand_group(graph_id=snapshot.SNAPSHOT_GRAPH_ID,node=node,edges=edges,cumulative_probability=cumulative,group_id=group.group_id)
            for group in list_group_summaries(node,edges))
        expected = _Reply(projection=BattleNodeProjection(node=projection._node_detail(node,has_outgoing_edges=bool(edges)),
            cumulative_probability=ProbabilityProjection.from_fraction(cumulative),transition_groups=groups),report_steps=tuple(report))
        return expected,tuple(ExplorationPathStep(edge.source_node_id,edge.edge_id,edge.target_node_id) for edge in edges)


@pytest.fixture
def snapshot_runner() -> Path:
    """缺显式Core入口单列SKIP，不计作迁移通过。"""
    value = os.environ.get("PBI_FIXED_BATTLE_SNAPSHOT_RUNNER")
    if value is None:
        pytest.skip("PBI_FIXED_BATTLE_SNAPSHOT_RUNNER is required")
    path = Path(value)
    assert path.is_file()
    return path


class TestFixedBattleSnapshot:
    """完整状态与事件差分，并验证全局max_turns不截断即时快照。"""
    @pytest.mark.parametrize("scenario",("normal","faint","immune"))
    def test_actual_snapshot_replay(self,snapshot_runner:Path,scenario:str) -> None:
        """根和真实后继完整组/概率/战报相等，不以PP断言替代结果比较。"""
        state = _Oracle.immune_state() if scenario == "immune" else _reference()
        if scenario == "faint":
            state = state.with_battler(BattleSide.DEFENDER,replace(state.defender,current_hp=1))
        turn = _ABIOracle.request(_TurnCase(state,Mode.EXPAND)).operations[0]
        assert isinstance(turn,TurnOperation)
        cursor = ExplorationCursor(snapshot.SNAPSHOT_GRAPH_ID,GraphNodeId(0))
        inputs:list[_Input] = []
        expected:list[_Reply] = []
        for _ in range(7 if scenario == "immune" else 3):
            observed,edges = _Oracle.observe(state,cursor)
            expected.append(observed)
            inputs.append(_Input(turn=turn,cursor=tuple(_Step(source_node_id=str(step.source_node_id),edge_id=str(step.edge_id),target_node_id=str(step.target_node_id)) for step in cursor.steps)))
            if not edges:
                break
            cursor = replace(cursor,steps=(*cursor.steps,edges[0]))
        result = subprocess.run([str(snapshot_runner)],input="".join(value.model_dump_json()+"\n" for value in inputs),text=True,capture_output=True,check=True,timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines)==len(expected)
        for line,reference in zip(lines,expected,strict=True):
            actual = _Reply.model_validate_json(line)
            assert actual.model_dump(mode="json")==reference.model_dump(mode="json")
        if scenario == "immune":
            assert int(expected[-1].projection.node.node_id)>2**64
            assert expected[-1].projection.node.turn_number==7


class _WireCursor(_Contract):
    """原cursor对象，只有步骤序列，不把完整图或累计概率当输入。"""
    steps: tuple[_Step,...]


class _WireInput(_Contract):
    """正式snapshot操作完整边界；字段类型沿用唯一正式策略回合模型。"""
    kind: Literal["fixed_battle_snapshot"] = "fixed_battle_snapshot"
    state: BattleSnapshot
    type_chart: tuple[TypeEfficacySnapshot,...]
    attacker_policy: ActionStrategy
    defender_policy: ActionStrategy
    turn_limits: TurnLimits
    cursor: _WireCursor

    @classmethod
    def from_turn(cls,turn:TurnOperation,cursor:tuple[_Step,...]) -> _WireInput:
        """turn只接受策略选择，cursor是同一公开路径；返回机械编码输入，不执行领域逻辑。"""
        assert isinstance(turn.selection,PolicySelection)
        return cls(state=turn.state,type_chart=turn.type_chart,attacker_policy=turn.selection.attacker,
            defender_policy=turn.selection.defender,turn_limits=turn.turn_limits,cursor=_WireCursor(steps=cursor))


class _WireError(_Contract):
    """原固定入口稳定业务拒绝，不以字符串推断错误类型。"""
    http_status: int
    code: str
    message: str


class _WireReply(_Contract):
    """正式snapshot完整HTTP值与互斥业务错误。"""
    kind: Literal["fixed_battle_snapshot"]
    value: BattleGraphExplorationResponse | None = None
    error: _WireError | None = None


@pytest.fixture
def snapshot_contract_runner() -> Path:
    """单列正式codec入口，缺环境SKIP不冒称协议通过。"""
    value=os.environ.get("PBI_FIXED_BATTLE_SNAPSHOT_CONTRACT_RUNNER")
    if value is None:
        pytest.skip("PBI_FIXED_BATTLE_SNAPSHOT_CONTRACT_RUNNER is required")
    path=Path(value)
    assert path.is_file()
    return path


class TestFixedBattleSnapshotContract:
    """真正公开DTO使用原schema presenter编码，错误也由原owning映射产生。"""
    @staticmethod
    def query(runner:Path,input:_WireInput) -> _WireReply:
        """runner是实际codec；input完整拥有，返回缺行/协议错误均失败。"""
        result=subprocess.run([str(runner)],input=input.model_dump_json()+"\n",text=True,capture_output=True,check=True,timeout=30)
        return _WireReply.model_validate_json(result.stdout)

    @pytest.mark.parametrize("depth",(0,1,6))
    def test_full_original_http_projection(self,snapshot_contract_runner:Path,depth:int) -> None:
        """实际原snapshot重放后交原HTTP presenter，全部空值/事件/概率/整数逐字段一致。"""
        state=_Oracle.immune_state() if depth==6 else _reference()
        turn=_ABIOracle.request(_TurnCase(state,Mode.EXPAND)).operations[0]
        assert isinstance(turn,TurnOperation)
        cursor=ExplorationCursor(snapshot.SNAPSHOT_GRAPH_ID,GraphNodeId(0))
        for _ in range(depth):
            _,edges=_Oracle.observe(state,cursor)
            cursor=replace(cursor,steps=(*cursor.steps,edges[0]))
        observed,_=_Oracle.observe(state,cursor)
        position=BattleExplorationPosition(snapshot.SNAPSHOT_GRAPH_ID,BATTLE_INFERENCE_CALCULATION_REVISION,cursor,
            observed.projection.node,observed.projection.cumulative_probability)
        groups=BattleTransitionGroupsResult(position,observed.projection.transition_groups)
        report=BattleReport(snapshot.SNAPSHOT_GRAPH_ID,BATTLE_INFERENCE_CALCULATION_REVISION,0,int(cursor.current_node_id),cursor.depth,
            observed.projection.cumulative_probability,observed.report_steps)
        expected=battle_graph_exploration_response(groups,report)
        steps=tuple(_Step(source_node_id=str(step.source_node_id),edge_id=str(step.edge_id),target_node_id=str(step.target_node_id)) for step in cursor.steps)
        actual=self.query(snapshot_contract_runner,_WireInput.from_turn(turn,steps))
        assert actual.error is None and actual.value is not None
        assert actual.value.model_dump(mode="json")==expected.model_dump(mode="json")

    @pytest.mark.parametrize("step",(_Step(source_node_id="1",edge_id="0",target_node_id="10000"),
        _Step(source_node_id="0",edge_id="999999",target_node_id="10000"),
        _Step(source_node_id="0",edge_id="0",target_node_id="10001")))
    def test_original_replay_error_categories(self,snapshot_contract_runner:Path,step:_Step) -> None:
        """原cursor构造与实际重放具有不同错误类别，完整HTTP码与原文案必须保真。"""
        state=_reference()
        turn=_ABIOracle.request(_TurnCase(state,Mode.EXPAND)).operations[0]
        assert isinstance(turn,TurnOperation)
        try:
            cursor=ExplorationCursor(snapshot.SNAPSHOT_GRAPH_ID,GraphNodeId(0),(ExplorationPathStep(GraphNodeId(int(step.source_node_id)),
                GraphEdgeId(int(step.edge_id)),GraphNodeId(int(step.target_node_id))),))
            _Oracle.observe(state,cursor)
        except ValueError as error:
            with pytest.raises(HTTPException) as expected:
                _raise_http_error(error)
        else:
            pytest.fail("original accepted invalid snapshot cursor")
        actual=self.query(snapshot_contract_runner,_WireInput.from_turn(turn,(step,)))
        assert actual.value is None and actual.error is not None
        assert actual.error.http_status==expected.value.status_code
        assert {"code":actual.error.code,"message":actual.error.message}==expected.value.detail
