"""验证组合枚举不会启动批量求解且保持严格机制准入。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from pokeop.application.use_cases.fixed_battle_workflow import (
    EnumerateMoveSetCombinationsCommand,
    EnumerateMoveSetCombinationsUseCase,
    FixedBattleSideSelection,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


@dataclass(frozen=True, slots=True)
class _FakeAdmission:
    """提供测试所需的最小候选准入字段。"""

    selectable: bool
    status: SimpleNamespace
    reason: str


@dataclass(frozen=True, slots=True)
class _FakeMove:
    """提供组合展示和准入所需的最小招式候选。"""

    move_id: int
    display_name: str
    admission: _FakeAdmission

    @property
    def move(self) -> SimpleNamespace:
        """返回与真实候选 profile 同形状的展示对象。"""
        return SimpleNamespace(display_name=self.display_name)


@dataclass(frozen=True, slots=True)
class _FakeMechanism:
    """提供特性或道具的最小准入字段。"""

    admission: _FakeAdmission


class _FakePool:
    """模拟 version-aware 候选池，不访问数据库。"""

    def __init__(
        self,
        pokemon_id: int,
        move_ids: tuple[int, ...],
        *,
        rejected_move_id: int | None = None,
    ) -> None:
        """创建指定候选集合，并可把其中一个招式标记为不可选择。"""
        self.calculation_revision = "battle-inference.summary-exploration.v2"
        self.pokemon_id = pokemon_id
        self.pokemon_display_name = f"pokemon-{pokemon_id}"
        self.moves = tuple(
            _FakeMove(
                move_id=move_id,
                display_name=f"move-{move_id}",
                admission=_FakeAdmission(
                    selectable=move_id != rejected_move_id,
                    status=SimpleNamespace(
                        value=(
                            "unsupported"
                            if move_id == rejected_move_id
                            else "supported"
                        )
                    ),
                    reason=(
                        "missing effect"
                        if move_id == rejected_move_id
                        else "supported"
                    ),
                ),
            )
            for move_id in move_ids
        )
        self._ability = _FakeMechanism(
            _FakeAdmission(True, SimpleNamespace(value="supported"), "supported")
        )
        self._item = _FakeMechanism(
            _FakeAdmission(True, SimpleNamespace(value="no_effect"), "no effect")
        )

    def move_by_id(self, move_id: int) -> _FakeMove | None:
        """按 ID 返回候选；未声明的招式视为当前 version group 不合法。"""
        return next((item for item in self.moves if item.move_id == move_id), None)

    def ability_by_identifier(self, identifier: str) -> _FakeMechanism | None:
        """仅接受测试固定特性。"""
        return self._ability if identifier == "test-ability" else None

    def item_by_identifier(self, identifier: str) -> _FakeMechanism | None:
        """仅接受显式无道具候选。"""
        return self._item if identifier == "none" else None


class _FakeCandidatePoolReader:
    """根据 Pokémon ID 返回预先构造的候选池。"""

    def __init__(self, pools: dict[int, _FakePool]) -> None:
        """保存每个 Pokémon 对应的测试候选池。"""
        self._pools = pools

    def execute(self, command):
        """返回命令中 Pokémon ID 对应的候选池。"""
        return self._pools[command.pokemon_id]


def _side(pokemon_id: int) -> FixedBattleSideSelection:
    """创建双方测试共享的合法固定配置。"""
    return FixedBattleSideSelection(
        pokemon_id=pokemon_id,
        form_id=None,
        level=50,
        stat_profile_id="max_atk_plus",
        ability_identifier="test-ability",
        item_identifier=None,
    )


def test_enumerates_side_move_sets_without_materializing_configuration_pairs() -> None:
    """5 招和 4 招应返回 5 个左右组合，但不生成五条配置执行记录。"""
    use_case = EnumerateMoveSetCombinationsUseCase(
        _FakeCandidatePoolReader(
            {
                1: _FakePool(1, (1, 2, 3, 4, 5)),
                2: _FakePool(2, (11, 12, 13, 14)),
            }
        )
    )

    result = use_case.execute(
        EnumerateMoveSetCombinationsCommand(
            rules=BattleInferenceRules(level=50),
            calculation_revision="battle-inference.summary-exploration.v2",
            attacker=_side(1),
            attacker_candidate_move_ids=(5, 4, 3, 2, 1),
            defender=_side(2),
            defender_candidate_move_ids=(14, 13, 12, 11),
        )
    )

    assert result.attacker.move_set_count == 5
    assert result.defender.move_set_count == 1
    assert result.configuration_pair_count == 5
    assert result.attacker.move_sets[0].move_ids == (1, 2, 3, 4)
    assert result.attacker.move_sets[-1].move_ids == (2, 3, 4, 5)
    assert result.attacker.move_sets[0].move_names == (
        "move-1",
        "move-2",
        "move-3",
        "move-4",
    )


def test_rejects_unsupported_candidate_before_returning_combinations() -> None:
    """候选池中存在不可执行招式时应一次性拒绝，不把它带入固定推演。"""
    use_case = EnumerateMoveSetCombinationsUseCase(
        _FakeCandidatePoolReader(
            {
                1: _FakePool(1, (1, 2, 3, 4, 5), rejected_move_id=5),
                2: _FakePool(2, (11, 12, 13, 14)),
            }
        )
    )

    with pytest.raises(ValueError, match="5:unsupported:missing effect"):
        use_case.execute(
            EnumerateMoveSetCombinationsCommand(
                rules=BattleInferenceRules(level=50),
                calculation_revision="battle-inference.summary-exploration.v2",
                attacker=_side(1),
                attacker_candidate_move_ids=(1, 2, 3, 4, 5),
                defender=_side(2),
                defender_candidate_move_ids=(11, 12, 13, 14),
            )
        )


def test_fixed_side_rejects_ambiguous_form_id() -> None:
    """首版不应接收随后会被固定推演静默丢弃的独立 form_id。"""
    with pytest.raises(ValueError, match="form-specific pokemon_id"):
        FixedBattleSideSelection(
            pokemon_id=1,
            form_id=99,
            level=50,
            stat_profile_id="max_atk_plus",
            ability_identifier="test-ability",
        )
