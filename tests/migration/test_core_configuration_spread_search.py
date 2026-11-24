"""实际HTTP绑定的WithSpeed反推入口与正式Core搜索的完整独立差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from pokeop.application.use_cases.configuration_speed_goals import ConfigurationSpeedGoalCommand, prepare_configuration_speed_goals
from pokeop.application.use_cases.calculate_catalog_damage import CalculatorMoveProfile
from pokeop.application.use_cases.search_configuration_spreads import SearchPokemonStatSpreadsCommand
from pokeop.application.use_cases.search_configuration_spreads_with_speed import SearchPokemonStatSpreadsWithSpeedCommand, SearchPokemonStatSpreadsWithSpeedUseCase
from pokeop.application.use_cases.solve_configuration_targets import ConfigurationGoalCommand, ConfigurationGoalKind, DamageRollPolicy, SolvePokemonConfigurationCommand
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_version_group
from pokeop.domain.configuration_presets import NATURES, STAT_FIELDS, StatSpread
from tests.application.use_cases.test_calculate_catalog_damage import BULLET_PUNCH_ID, SCIZOR_ID, SYLVEON_ID, FakeCalculatorRepository
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import FakeCalculatorAbilityRepository
from tests.migration.test_core_configuration_goals import GoalInput, GoalResponse, SpeedInput, SpeedResponse, _Contract, _GoalContext, _Oracle, _Prepared
from tests.migration.test_core_configuration_stats import Nature, _Oracle as _StatOracle
from tests.migration.test_core_damage import PokemonSnapshot


class NatureInput(_Contract):
    """唯一知识源的25性格事实；相关轴分组与代表选择必须由Core完成。"""

    identifier: str
    label: str
    modifier: Nature


class SearchInput(_GoalContext):
    """正式搜索命令只含原始知识与目标，不接受预先枚举候选。"""

    kind: Literal["configuration_spread_search"] = "configuration_spread_search"
    subject_base: PokemonSnapshot
    max_candidates: int
    goals: tuple[GoalInput, ...]
    speed_goals: tuple[SpeedInput, ...]
    natures: tuple[NatureInput, ...]


class ValueRange(_Contract):
    """其余五项代表值固定时的原单项闭区间。"""

    minimum: int
    maximum: int


class NatureOption(_Contract):
    """原目标相关倍率等价性格的一项，保留完整有序展示字段。"""

    identifier: str
    label: str


class SearchCandidate(_Contract):
    """实际搜索输出的完整代表、独立区间和双类目标证据。"""

    candidate_id: str
    nature_id: str
    nature_label: str
    nature_options: tuple[NatureOption, ...]
    evs: StatValues
    ivs: StatValues
    ev_ranges: tuple[ValueRange, ...]
    iv_ranges: tuple[ValueRange, ...]
    stats: StatValues
    goals: tuple[GoalResponse, ...]
    speed_goals: tuple[SpeedResponse, ...]


class SearchReply(_Contract):
    """整次原公开搜索的可达结果，不接受遗漏不可达基线证据。"""

    kind: Literal["configuration_spread_search"]
    reachable: bool
    candidates: tuple[SearchCandidate, ...]
    rejected_goals: tuple[GoalResponse, ...]
    rejected_speed_goals: tuple[SpeedResponse, ...]


class _MixedMoveRepository(FakeCalculatorRepository):
    """仅增加一行特殊招式知识，物理/特殊目标仍全部由原完整用例求解。"""

    def get_move_profile(self, *, ruleset_id: str, move_id: int) -> CalculatorMoveProfile | None:
        """按原规则集与ID读取两行知识，不计算伤害或可行性；未知ID为空。"""
        if move_id not in (BULLET_PUNCH_ID, BULLET_PUNCH_ID + 10_000):
            return None
        value = super().get_move_profile(ruleset_id=ruleset_id, move_id=BULLET_PUNCH_ID)
        if value is None or move_id == BULLET_PUNCH_ID:
            return value
        return replace(value, move_id=move_id, identifier="special-fixture", category=MoveCategory.SPECIAL, power=80)

    def pokemon_can_use_move(self, *, ruleset_id: str, pokemon_id: int, move_id: int) -> bool:
        """只投影两行合法learnset知识，不在测试端选择候选或复制搜索规则。"""
        return move_id in (BULLET_PUNCH_ID, BULLET_PUNCH_ID + 10_000) and super().pokemon_can_use_move(
            ruleset_id=ruleset_id, pokemon_id=pokemon_id, move_id=BULLET_PUNCH_ID)


class _SearchOracle:
    """只负责准备边界数据和字段比较，完整枚举/二分/区间均调用原公开execute。"""

    @staticmethod
    def solver() -> SearchPokemonStatSpreadsWithSpeedUseCase:
        """创建实际router使用的原实现，fake仅替代SQL知识读取。"""
        return SearchPokemonStatSpreadsWithSpeedUseCase(FakeCalculatorRepository(), FakeCalculatorAbilityRepository())

    @staticmethod
    def prepare(command: SearchPokemonStatSpreadsWithSpeedCommand, solver: SearchPokemonStatSpreadsWithSpeedUseCase) -> _Prepared:
        """用指定知识端口的原读取/准备链生成事实，不调用搜索或重写原准备规则。"""
        ruleset = solver._require_ruleset(command.ruleset_id)
        subject = solver._require_pokemon(ruleset_id=command.ruleset_id, pokemon_id=command.subject_pokemon_id, role="subject")
        ability = solver._require_ability(ruleset_id=command.ruleset_id, pokemon_id=subject.pokemon_id,
            identifier=command.subject_ability_identifier, role="subject").domain_value
        goals, _ = solver._prepare_goals(ruleset=ruleset, command=SearchPokemonStatSpreadsCommand(
            ruleset_id=command.ruleset_id, subject_pokemon_id=command.subject_pokemon_id,
            subject_ability_identifier=command.subject_ability_identifier, subject_item_identifier=command.subject_item_identifier,
            level=command.level, goals=command.goals, max_candidates=command.max_candidates))
        return _Prepared(subject, ability, solver._item_from_identifier(command.subject_item_identifier), goals, command.level,
            resolve_ruleset_by_version_group(ruleset.version_group_id))

    @staticmethod
    def request(command: SearchPokemonStatSpreadsWithSpeedCommand, prepared: _Prepared) -> SearchInput:
        """由原准备器投影目标/相克/性格；不运行搜索或计算任何可行EV。"""
        base = SolvePokemonConfigurationCommand(subject_pokemon_id=command.subject_pokemon_id,
            subject_ability_identifier=command.subject_ability_identifier, subject_item_identifier=command.subject_item_identifier,
            level=command.level, goals=command.goals, max_candidates=command.max_candidates)
        request = _Oracle.request(base, prepared)
        repository = FakeCalculatorRepository()
        ruleset = repository.get_ruleset_context(command.ruleset_id)
        assert ruleset is not None
        speed = prepare_configuration_speed_goals(repository=repository, ruleset=ruleset, level=command.level, goals=command.speed_goals)
        return SearchInput(generation_id=request.generation_id, policy=request.policy, type_chart=request.type_chart,
            subject_base=request.subject_base, max_candidates=command.max_candidates, goals=request.goals, speed_goals=tuple(SpeedInput(
            goal_id=goal.command.goal_id, target_speed=goal.target_stats.speed) for goal in speed),
            natures=tuple(NatureInput(identifier=nature.identifier, label=nature.label, modifier=_StatOracle.nature(nature.modifier()))
                for nature in reversed(tuple(NATURES.values()))))

    @classmethod
    def check(cls, actual: SearchReply, command: SearchPokemonStatSpreadsWithSpeedCommand, prepared: _Prepared,
              solver: SearchPokemonStatSpreadsWithSpeedUseCase | None = None) -> None:
        """逐字段对照原完整入口，包括所有候选顺序、六区间、等价性格和完整伤害trace。"""
        if solver is None:
            solver = cls.solver()
        expected = solver.execute(command)
        assert actual.reachable == expected.reachable
        assert len(actual.candidates) == len(expected.candidates)
        for value, original in zip(actual.candidates, expected.candidates, strict=True):
            assert value.candidate_id == original.candidate_id
            assert value.nature_id == original.nature_id
            assert value.nature_label == original.nature_label
            assert value.nature_options == tuple(NatureOption(identifier=option.identifier, label=option.label) for option in original.nature_options)
            assert value.evs == original.evs.to_stat_values()
            assert value.ivs == original.ivs.to_stat_values()
            assert value.stats == original.stats
            for ranges, reference in ((value.ev_ranges, original.ev_ranges), (value.iv_ranges, original.iv_ranges)):
                assert ranges == tuple(ValueRange(minimum=reference.value_for(field).minimum, maximum=reference.value_for(field).maximum)
                    for field in STAT_FIELDS)
            for result, reference, goal in zip(value.goals, original.goal_results, prepared.goals, strict=True):
                _Oracle.check_goal(result, reference, prepared, original.stats, goal)
            _Oracle.check_speed(value.speed_goals, original.speed_goal_results)
        assert len(actual.rejected_goals) == len(expected.rejected_goal_results)
        if actual.rejected_goals:
            repository = FakeCalculatorRepository()
            ruleset = repository.get_ruleset_context(command.ruleset_id)
            assert ruleset is not None
            speed = prepare_configuration_speed_goals(repository=repository, ruleset=ruleset, level=command.level, goals=command.speed_goals)
            nature = solver._nature_groups_with_speed(prepared.goals, speed)[0].representative
            stats = solver._calculate_subject_stats(subject=prepared.subject, level=command.level, nature=nature,
                evs=StatSpread.evs(), ivs=StatSpread.perfect_ivs())
            for result, reference, goal in zip(actual.rejected_goals, expected.rejected_goal_results, prepared.goals, strict=True):
                _Oracle.check_goal(result, reference, prepared, stats, goal)
        _Oracle.check_speed(actual.rejected_speed_goals, expected.rejected_speed_goal_results)


@pytest.fixture
def configuration_spread_search_runner() -> Path:
    """获取外部已编译真实Core，缺少时显式skip，不能用Python替代C++运行。"""
    value = os.getenv("PBI_CONFIGURATION_SPREAD_SEARCH_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_SPREAD_SEARCH_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreConfigurationSpreadSearch:
    """真实搜索入口的damage-only/speed-only/混合、不可达与候选成本顺序。"""

    def test_original_public_speed_aware_search(self, configuration_spread_search_runner: Path) -> None:
        """24个固定种子的完整公开搜索，原算法不被oracle复制或预先提供给Core。"""
        rng = random.Random(60211)
        commands: list[SearchPokemonStatSpreadsWithSpeedCommand] = []
        for index in range(24):
            goals: list[ConfigurationGoalCommand] = []
            if index % 3 != 0:
                for axis in range(rng.randint(1, 2)):
                    kind = rng.choice(tuple(ConfigurationGoalKind))
                    target = SYLVEON_ID if kind is ConfigurationGoalKind.ATTACK else SCIZOR_ID
                    goals.append(ConfigurationGoalCommand(goal_id=f"damage-{index}-{axis}", kind=kind,
                        target_pokemon_id=target, move_id=BULLET_PUNCH_ID, required_turns=rng.randint(1, 8),
                        target_ability_identifier="cute-charm" if target == SYLVEON_ID else rng.choice(("swarm", "technician")),
                        target_stat_preset=rng.choice(("no_investment", "max_hp", "max_atk_plus")),
                        target_item_identifier=rng.choice((None, "life-orb")),
                        damage_roll_policy=rng.choice((None, DamageRollPolicy.MIN, DamageRollPolicy.MAX))))
            speed = () if index % 3 == 1 else (ConfigurationSpeedGoalCommand(goal_id=f"speed-{index}",
                target_pokemon_id=rng.choice((SCIZOR_ID, SYLVEON_ID)), target_stat_preset=rng.choice(("no_investment", "max_speed_plus"))),)
            commands.append(SearchPokemonStatSpreadsWithSpeedCommand(subject_pokemon_id=SCIZOR_ID,
                subject_ability_identifier=rng.choice(("swarm", "technician")), subject_item_identifier=rng.choice((None, "life-orb")),
                level=rng.choice((5, 50, 100)), goals=tuple(goals), speed_goals=speed, max_candidates=rng.choice((1, 3, 10))))
        prepared = tuple(_Oracle.prepare(SolvePokemonConfigurationCommand(subject_pokemon_id=command.subject_pokemon_id,
            subject_ability_identifier=command.subject_ability_identifier, subject_item_identifier=command.subject_item_identifier,
            level=command.level, goals=command.goals)) for command in commands)
        requests = tuple(_SearchOracle.request(command, data) for command, data in zip(commands, prepared, strict=True))
        result = subprocess.run([str(configuration_spread_search_runner)], input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        for line, command, data in zip(lines, commands, prepared, strict=True):
            _SearchOracle.check(SearchReply.model_validate_json(line), command, data)

    def test_all_four_damage_axes_and_speed(self, configuration_spread_search_runner: Path) -> None:
        """12套同一配置四轴攻防/速度目标，比较原总EV过滤、真实权衡和所有独立区间。"""
        rng = random.Random(60212)
        solver = SearchPokemonStatSpreadsWithSpeedUseCase(_MixedMoveRepository(), FakeCalculatorAbilityRepository())
        commands: list[SearchPokemonStatSpreadsWithSpeedCommand] = []
        for case in range(12):
            goals = tuple(ConfigurationGoalCommand(goal_id=f"axis-{kind.value}-{category.value}", kind=kind,
                target_pokemon_id=SYLVEON_ID if kind is ConfigurationGoalKind.ATTACK else SCIZOR_ID,
                target_ability_identifier="cute-charm" if kind is ConfigurationGoalKind.ATTACK else "swarm",
                move_id=BULLET_PUNCH_ID + (10_000 if category is MoveCategory.SPECIAL else 0),
                required_turns=rng.randint(2, 7), target_stat_preset=rng.choice(("no_investment", "max_hp", "max_atk_plus")),
                damage_roll_policy=rng.choice((DamageRollPolicy.MIN, DamageRollPolicy.MAX)))
                for kind in ConfigurationGoalKind for category in (MoveCategory.PHYSICAL, MoveCategory.SPECIAL))
            speed = () if case % 2 == 0 else (ConfigurationSpeedGoalCommand(goal_id="speed", target_pokemon_id=SYLVEON_ID,
                target_stat_preset="no_investment"),)
            commands.append(SearchPokemonStatSpreadsWithSpeedCommand(subject_pokemon_id=SCIZOR_ID,
                subject_ability_identifier=rng.choice(("swarm", "technician")), subject_item_identifier=rng.choice((None, "life-orb")),
                level=rng.choice((50, 100)), goals=goals, speed_goals=speed, max_candidates=rng.choice((1, 3, 10))))
        prepared = tuple(_SearchOracle.prepare(command, solver) for command in commands)
        requests = tuple(_SearchOracle.request(command, data) for command, data in zip(commands, prepared, strict=True))
        result = subprocess.run([str(configuration_spread_search_runner)], input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        for line, command, data in zip(lines, commands, prepared, strict=True):
            _SearchOracle.check(SearchReply.model_validate_json(line), command, data, solver)
