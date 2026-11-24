"""正式Core胜利路径完整原用例/HTTP DTO差分，不在测试重写DFS、分组、概率或cursor算法。"""

from __future__ import annotations

import base64
import os
import random
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from pokeop.api.schemas.winning_paths import WinningPathGroupsResponse, winning_path_groups_response
from pokeop.application.solver.models import GraphEdgeId, GraphNodeId, GraphNodeOutcome, GraphTruncationReason, StateGraphBuildResult, StateGraphEdge, StateGraphNode, StateGraphStatistics, StateGraphTerminalCounts
from pokeop.application.solver.strong_components import analyze_strong_components
from pokeop.application.use_cases.winning_paths import ListWinningPathGroupsUseCase, WinningPathGroupsResult, WinningPathQueryError, WinningPathSort, WinningPathWinner, _configuration, _encode_cursor
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventSummary, TransitionEventType
from tests.application.test_winning_paths import _acyclic_graph, _cyclic_graph
from tests.application.use_cases.battle_exploration_test_helpers import GRAPH_ID, REVISION, MemoryStore, stored_store
from tests.migration.test_core_battle_graph import BuildReply, _BuildOracle
from tests.migration.test_core_state import _reference


class _Contract(BaseModel):
    """固定进程边界，模型内部不使用任意JSON字典。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _Request(_Contract):
    """正式完整图与原查询；没有Go预计算配置/动作/胜率/offset字段。"""

    kind: Literal["winning_paths"] = "winning_paths"
    graph_id: str
    calculation_revision: str
    winner: WinningPathWinner
    graph: BuildReply
    limit: int = 10
    cursor: str | None = None
    sort: WinningPathSort = WinningPathSort.SHORTEST_HIGH_PROBABILITY
    max_traversed_walks: int = 100000


class _Reply(WinningPathGroupsResponse):
    """直接复用原HTTP完整DTO验证所有嵌套字段，并额外验证正式Core操作身份。"""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["winning_paths"]


class _Error(_Contract):
    """runner仅捕获异常，不把业务错误当空路径结果。"""

    error: str


class _Vector(_Contract):
    """完整原oracle向量；expected是边界JSON AST，以严格核验整数文本等wire表示。"""

    name: str
    operation: _Request
    expected: dict[str, JsonValue]


class _Vectors(_Contract):
    """版本化冻结golden，不接受省字段或来自Cpp反推的概率。"""

    schema_version: Literal[1]
    oracle: str
    cases: tuple[_Vector, ...]


class _CursorPayload(_Contract):
    """只用于构造恶意边界输入，合法输出仍完全由原_encode_cursor提供。"""

    v: int | bool | float = 1
    graph_id: str = GRAPH_ID
    calculation_revision: str = REVISION
    configuration_key: str
    winner: str = "attacker"
    sort: str = "shortest-high-probability"
    offset: int | str | bool | float | None = 0

    def encode(self) -> str:
        """仅编码明确payload测试输入，不模仿原cursor验证或排序。"""
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")


@dataclass(frozen=True)
class _Case:
    """一个原图/查询，完整交给同一原用例和Cpp codec。"""

    graph: StateGraphBuildResult
    winner: WinningPathWinner = WinningPathWinner.ATTACKER
    limit: int = 10
    cursor: str | None = None
    max_walks: int = 100000
    graph_id: str = GRAPH_ID
    revision: str = REVISION

    def store(self) -> MemoryStore:
        """复用原测试store，允许Unicode/DEL身份以校验原ensure_ascii cursor字节。"""
        store = stored_store(self.graph)
        assert store.stored_graph is not None
        store.stored_graph = replace(store.stored_graph, graph_id=self.graph_id, calculation_revision=self.revision)
        return store

    def original(self) -> WinningPathGroupsResult:
        """实际调用原完整use case，不从Core反推任何expected。"""
        return ListWinningPathGroupsUseCase(self.store(), max_traversed_walks=self.max_walks).execute(
            self.graph_id, self.revision, winner=self.winner, limit=self.limit, cursor=self.cursor)

    def request(self) -> _Request:
        """只投影原完整图records；原reader负责全部图/事件验证。"""
        return _Request(graph_id=self.graph_id, calculation_revision=self.revision, winner=self.winner,
            graph=_BuildOracle.graph(self.graph), limit=self.limit, cursor=self.cursor, max_traversed_walks=self.max_walks)


@pytest.fixture
def winning_runner() -> Path:
    """优先正式环境入口，未提供二进制时明确skip而不是回退Python实现。"""
    configured = os.environ.get("PBI_WINNING_PATHS_RUNNER")
    if not configured:
        pytest.skip("PBI_WINNING_PATHS_RUNNER is required for native differential")
    runner = Path(configured)
    assert runner.is_file()
    return runner


def _compare(runner: Path, cases: tuple[_Case, ...]) -> None:
    """runner为正式Cpp进程、cases为同批原图查询；逐字段比较完整原DTO，失败直接assert。

    整数文本仅由原Pydantic schema机械解析，不转换概率或忽略嵌套字段。
    """
    expected = tuple(winning_path_groups_response(case.original()) for case in cases)
    process = subprocess.run((str(runner),), input="".join(case.request().model_dump_json() + "\n" for case in cases),
        text=True, capture_output=True, check=True, timeout=120)
    lines = process.stdout.splitlines()
    assert len(lines) == len(cases), process.stderr
    for index, (line, original) in enumerate(zip(lines, expected, strict=True)):
        actual = _Reply.model_validate_json(line)
        assert actual.model_dump(exclude={"kind"}) == original.model_dump(), (index, cases[index])


class _GraphFixtures:
    """生成只供原oracle使用的完整类型化图，不实现待迁移的查询算法。"""

    @staticmethod
    def graph(nodes: tuple[StateGraphNode, ...], edges: tuple[StateGraphEdge, ...], *, components: bool = True,
               truncations: tuple[GraphTruncationReason, ...] = ()) -> StateGraphBuildResult:
        """nodes/edges为原输入，components决定是否调用原SCC，truncations为原保护事实。

        返回完整原正式图；不自行实现待迁移的遍历/归并/概率逻辑。
        """
        counts = StateGraphTerminalCounts(
            attacker_wins=sum(node.outcome is GraphNodeOutcome.ATTACKER_WIN for node in nodes),
            defender_wins=sum(node.outcome is GraphNodeOutcome.DEFENDER_WIN for node in nodes),
            draws=sum(node.outcome is GraphNodeOutcome.DRAW for node in nodes),
            non_terminal=sum(node.outcome is GraphNodeOutcome.NON_TERMINAL for node in nodes),
            unknown=sum(node.outcome is GraphNodeOutcome.UNKNOWN for node in nodes))
        statistics = StateGraphStatistics(len(nodes), len(edges), max(node.state.turn_number for node in nodes), counts, 0, 0)
        return StateGraphBuildResult(GraphNodeId(0), nodes, edges, analyze_strong_components(list(nodes), list(edges)) if components else (), statistics, truncations)


    @staticmethod
    def history(turn: int, variant: int, damage: int) -> tuple[TransitionEvent, ...]:
        """turn为实际回合、variant选择事实组合、damage为任意精度原伤害值；返回完整原事件。

        覆盖整体fallback、缺一侧、重复actor首事件和七类关键事件，不执行战斗规则。
        """
        kind = BattleEventKind.MOVE_USED if variant % 3 == 0 else BattleEventKind.MOVE_SELECTED
        events: list[TransitionEvent] = [BattleEvent(kind=kind, turn_number=turn, actor=BattleSide.ATTACKER,
            move_id=1 + variant % 2, source_identifier="policy")]
        if variant % 3 == 1:
            events.append(BattleEvent(kind=BattleEventKind.MOVE_USED, turn_number=turn, actor=BattleSide.DEFENDER, move_id=101, source_identifier="used-only"))
        else:
            events.append(BattleEvent(kind=kind, turn_number=turn, actor=BattleSide.DEFENDER, move_id=101, source_identifier="policy"))
        events.extend((BattleEvent(kind=kind, turn_number=turn, actor=BattleSide.ATTACKER, move_id=4, source_identifier="later-ignored"),
            BattleEvent(kind=BattleEventKind.DAMAGE, turn_number=turn, actor=BattleSide.ATTACKER, target=BattleSide.DEFENDER, move_id=1, value=damage, source_identifier="damage"),
            BattleEvent(kind=(BattleEventKind.MISS, BattleEventKind.ACTION_BLOCKED, BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.ITEM_TRIGGERED,
                BattleEventKind.STATUS_APPLIED, BattleEventKind.STATUS_PREVENTED, BattleEventKind.FAINTED)[variant % 7], turn_number=turn,
                actor=BattleSide.ATTACKER if variant % 2 else None, target=BattleSide.DEFENDER, move_id=1, source_identifier="fact")))
        return tuple(events)


    @classmethod
    def random(cls, seed: int) -> StateGraphBuildResult:
        """seed为可复现随机种子；返回小而完整的原图输入，不在测试重写原路径查询。"""
        randomizer = random.Random(seed)
        root = _reference()
        count = 4 + seed % 7
        nodes: list[StateGraphNode] = []
        for index in range(count):
            outcome = GraphNodeOutcome.NON_TERMINAL
            if index >= count - 2:
                outcome = randomizer.choice((GraphNodeOutcome.ATTACKER_WIN, GraphNodeOutcome.DEFENDER_WIN, GraphNodeOutcome.DRAW))
            state = replace(root, turn_number=1 + index // 2,
                attacker=root.attacker.with_current_hp(root.attacker.current_hp - index),
                defender=root.defender.with_current_hp(0 if outcome is GraphNodeOutcome.ATTACKER_WIN else root.defender.current_hp - index))
            nodes.append(StateGraphNode(GraphNodeId(index), state, state.state_key, outcome,
                TerminationReason.KNOCKOUT if outcome is not GraphNodeOutcome.NON_TERMINAL else None))
        edges: list[StateGraphEdge] = []
        for index, node in enumerate(nodes):
            if node.is_terminal:
                continue
            targets = [randomizer.randrange(index + 1, count) for _ in range(2 + seed % 3)]
            weights = [randomizer.randrange(1, 8) for _ in targets]
            for target, weight in zip(targets, weights, strict=True):
                alternatives = tuple(cls.history(node.state.turn_number, randomizer.randrange(8), 10**30 + len(edges) * 10 + branch)
                    for branch in range(1 + seed % 3))
                summary = TransitionEventSummary(alternatives, tuple(Fraction(branch + 1, sum(range(1, len(alternatives) + 1))) for branch in range(len(alternatives))))
                edges.append(StateGraphEdge(GraphEdgeId(len(edges)), GraphNodeId(index), GraphNodeId(target), Fraction(weight, sum(weights)), summary))
        return cls.graph(tuple(nodes), tuple(edges), components=seed % 2 == 0)


class TestCoreWinningPaths:
    """用原完整入口验证分页/环/动作/精确概率/前缀/巨大整数和所有错误文案。"""

    def test_original_fixtures_pages_cycles_and_random_graphs(self, winning_runner: Path) -> None:
        """原三例和64随机图双侧/预算完整差分，所有expected来自原use case。"""
        cases: list[_Case] = []
        for graph in (_acyclic_graph(), _cyclic_graph(), *(_GraphFixtures.random(seed) for seed in range(64))):
            for winner in WinningPathWinner:
                case = _Case(graph, winner, limit=2)
                cases.extend((case, replace(case, max_walks=1 + len(graph.nodes) // 2)))
                result = case.original()
                while result.next_cursor is not None:
                    case = replace(case, cursor=result.next_cursor)
                    cases.append(case)
                    result = case.original()
        _compare(winning_runner, tuple(cases))

    def test_terminal_unknown_big_history_and_unicode_cursor(self, winning_runner: Path) -> None:
        """2^70原历史组合超过int64，空根walk、unknown截断和UTF8/DEL游标字节全部原样保留。"""
        root = _reference()
        nodes = tuple(StateGraphNode(GraphNodeId(index), replace(root, turn_number=index + 1), replace(root, turn_number=index + 1).state_key,
            GraphNodeOutcome.ATTACKER_WIN if index == 70 else GraphNodeOutcome.NON_TERMINAL,
            TerminationReason.KNOCKOUT if index == 70 else None) for index in range(71))
        edges = tuple(StateGraphEdge(GraphEdgeId(index), GraphNodeId(index), GraphNodeId(index + 1), Fraction(1),
            TransitionEventSummary((_GraphFixtures.history(index + 1, 0, index), _GraphFixtures.history(index + 1, 2, index + 1)))) for index in range(70))
        big = _Case(_GraphFixtures.graph(nodes, edges))
        assert big.original().path_groups[0].raw_history_count_estimate == 2**70
        terminal = _Case(_GraphFixtures.graph((replace(nodes[0], outcome=GraphNodeOutcome.ATTACKER_WIN, termination_reason=TerminationReason.KNOCKOUT),), ()))
        unknown = _Case(_GraphFixtures.graph((replace(nodes[0], outcome=GraphNodeOutcome.UNKNOWN),), (), truncations=(GraphTruncationReason.MAX_NODES,)))
        loop = StateGraphEdge(GraphEdgeId(0), GraphNodeId(0), GraphNodeId(0), Fraction(1), TransitionEventSummary(((),)))
        closed = _Case(_GraphFixtures.graph((nodes[0],), (loop,)))
        missing_closed = _Case(_GraphFixtures.graph((nodes[0],), (loop,), components=False))
        unicode = _Case(_acyclic_graph(), limit=1, graph_id="图-é-😀-\x7f", revision="版本-雪-\x00-😀")
        unicode_next = replace(unicode, cursor=unicode.original().next_cursor)
        huge = _Case(_acyclic_graph(), cursor=_encode_cursor(graph_id=GRAPH_ID, calculation_revision=REVISION,
            configuration_key=_configuration(_acyclic_graph()).configuration_key, winner=WinningPathWinner.ATTACKER,
            sort=WinningPathSort.SHORTEST_HIGH_PROBABILITY, offset=10**500))
        _compare(winning_runner, (big, terminal, replace(terminal, winner=WinningPathWinner.DEFENDER), unknown, closed, missing_closed, unicode, unicode_next, huge))

    def test_configuration_identity_known_abilities_items_and_move_order(self, winning_runner: Path) -> None:
        """全部9能力x6道具完整原配置SHA，展示名称/招式输入顺序不能冒充新配置事实。"""
        base = _acyclic_graph()
        cases: list[_Case] = []
        for ability in DamageAbility:
            for item in DamageItem:
                nodes: list[StateGraphNode] = []
                for node in base.nodes:
                    attacker = replace(node.state.attacker, spec=replace(node.state.attacker.spec,
                        ability=ability, item=item, name="展示-😀", moves=tuple(reversed(node.state.attacker.spec.moves))))
                    state = replace(node.state, attacker=attacker)
                    nodes.append(replace(node, state=state, state_key=state.state_key))
                cases.append(_Case(replace(base, nodes=tuple(nodes)), limit=100))
        assert len({_configuration(case.graph).configuration_key for case in cases}) == len(cases)
        _compare(winning_runner, tuple(cases))

    def test_invalid_cursor_original_messages(self, winning_runner: Path) -> None:
        """原wrong-binding、offset类型、空白、畸形base64/JSON文案均保留，不以空成功结果掩盖。"""
        graph = _acyclic_graph()
        key = _configuration(graph).configuration_key
        cursors: list[str] = ["", " bad ", "!!!", "not-base64", "e30"]
        cursors.extend(payload.encode() for payload in (
            _CursorPayload(configuration_key=key, graph_id="another"),
            _CursorPayload(configuration_key=key, calculation_revision="other"),
            _CursorPayload(configuration_key="cfg-other"),
            _CursorPayload(configuration_key=key, winner="defender"),
            _CursorPayload(configuration_key=key, sort="other"),
            _CursorPayload(configuration_key=key, v=2),
            _CursorPayload(configuration_key=key, offset=-1),
            _CursorPayload(configuration_key=key, offset=True),
            _CursorPayload(configuration_key=key, offset=1.5),
            _CursorPayload(configuration_key=key, offset="1"),
            _CursorPayload(configuration_key=key, offset=None)))
        cases = tuple(_Case(graph, cursor=cursor) for cursor in cursors)
        expected: list[str] = []
        for case in cases:
            with pytest.raises(WinningPathQueryError) as error:
                case.original()
            expected.append(str(error.value))
        process = subprocess.run((str(winning_runner),), input="".join(case.request().model_dump_json() + "\n" for case in cases), text=True,
            capture_output=True, check=True, timeout=120)
        actual = tuple(_Error.model_validate_json(line).error for line in process.stdout.splitlines())
        assert actual == tuple(expected), process.stderr

    def test_frozen_original_vectors_exact_wire(self, winning_runner: Path) -> None:
        """winning_runner为真实codec；严格比较原生成三向量的完整wire，不把文本计数转换后漏验。"""
        fixture = Path(__file__).resolve().parents[1] / "vectors" / "winning-paths.v1.json"
        vectors = _Vectors.model_validate_json(fixture.read_text())
        process = subprocess.run((str(winning_runner),), input="".join(case.operation.model_dump_json() + "\n" for case in vectors.cases),
            text=True, capture_output=True, check=True, timeout=120)
        actual = tuple(TypeAdapter(dict[str, JsonValue]).validate_json(line) for line in process.stdout.splitlines())
        assert actual == tuple(case.expected for case in vectors.cases), process.stderr
