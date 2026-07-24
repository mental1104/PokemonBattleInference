"""验证 1v1 application 状态图实际接入结构化 BattleEvent。"""

from __future__ import annotations

from pokeop.application.use_cases.infer_one_on_one_battle import (
    InferFixedOneOnOneBattleCommand,
    PokemonInferenceSelection,
)
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from tests.application.use_cases.test_infer_one_on_one_battle import (
    _RULESET,
    _use_case,
)


def test_fixed_battle_graph_edges_keep_structured_battle_events() -> None:
    """固定冰冻拳旅程的图边应保留选招、PP、命中与伤害业务事件。

    application 必须使用结构化完整回合 resolver，而不是只在 domain 提供一个未接线的
    可选实现。该测试直接读取 exploration 内部图 artifact，确认状态图边继续保存
    ``TransitionEventSummary`` 中的 ``BattleEvent``，供后续 API/presenter 投影战报。
    """
    result = _use_case().execute_fixed(
        InferFixedOneOnOneBattleCommand(
            rules=_RULESET,
            attacker=PokemonInferenceSelection(
                pokemon_id=149,
                move_ids=(280,),
                ability_identifier="multiscale",
            ),
            defender=PokemonInferenceSelection(
                pokemon_id=461,
                move_ids=(8,),
                ability_identifier="pressure",
            ),
        )
    )

    graph = result.exploration.graph_artifact
    assert graph is not None
    events = tuple(
        event
        for edge in graph.edges
        for path in edge.event_summary.paths
        for event in path
        if isinstance(event, BattleEvent)
    )
    kinds = {event.kind for event in events}

    assert BattleEventKind.TURN_STARTED in kinds
    assert BattleEventKind.MOVE_SELECTED in kinds
    assert BattleEventKind.ACTION_ORDERED in kinds
    assert BattleEventKind.MOVE_USED in kinds
    assert BattleEventKind.PP_CHANGED in kinds
    assert BattleEventKind.HIT in kinds
    assert BattleEventKind.DAMAGE in kinds
    assert BattleEventKind.HP_CHANGED in kinds
    assert BattleEventKind.TURN_ENDED in kinds
