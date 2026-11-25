"""原完整模板求解用例与共享静态目标证据的真实C++差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.use_cases.calculate_catalog_damage import CalculatorPokemonProfile, stat_profile_from_preset
from pokeop.application.use_cases.configuration_speed_goals import ConfigurationSpeedGoalCommand, ConfigurationSpeedGoalResult, prepare_configuration_speed_goals
from pokeop.application.use_cases.search_configuration_spreads import SearchPokemonStatSpreadsCommand, SearchPokemonStatSpreadsUseCase, _PreparedGoal
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand, ConfigurationGoalKind, ConfigurationGoalResult, DamageRollPolicy,
    SolvePokemonConfigurationCommand, SolvePokemonConfigurationUseCase,
    SolvePokemonConfigurationResult,
)
from pokeop.application.use_cases.solve_configuration_with_speed import (
    SolvePokemonConfigurationWithSpeedCommand, SolvePokemonConfigurationWithSpeedResult,
    SolvePokemonConfigurationWithSpeedUseCase, SolvedConfigurationWithSpeedCandidate,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattleMove, BattlePokemon, DamageContext, DamageContextBuilder
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.models import BattleRuleset
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_version_group
from pokeop.domain.battle.stats import StatValues, calculate_actual_stats
from pokeop.domain.configuration_presets import StatConfiguration, StatConfigurationRole, StatConfigurationSource, StatSpread
from pokeop.domain.models.types import TypeHelper
from tests.application.use_cases.test_calculate_catalog_damage import BULLET_PUNCH_ID, SCIZOR_ID, SYLVEON_ID, FakeCalculatorRepository
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import FakeCalculatorAbilityRepository
from tests.migration.test_core_configuration_stats import Nature, Stats, _Oracle as _StatOracle
from tests.migration.test_core_damage import DamageResponse, MoveSnapshot, PokemonSnapshot, TypeEfficacySnapshot, _DamageOracle


class _Contract(BaseModel):
    """冻结完整过程边界，不允许缺少目标证据的响应通过。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GoalInput(_Contract):
    """原准备完成目标，不注入已经计算的满足性或选中伤害。"""

    goal_id: str
    kind: ConfigurationGoalKind
    target: PokemonSnapshot
    move: MoveSnapshot
    required_turns: int
    roll_policy: DamageRollPolicy | None


class Template(_Contract):
    """原模板解析后的投入与完整性格，实际能力仍由Core计算。"""

    preset_key: str
    ivs: Stats
    evs: Stats
    nature: Nature


class SpeedInput(_Contract):
    """原prepare函数给出的实际Speed参照，比较和margin仍由Core完成。"""

    goal_id: str
    target_speed: int


class SpeedResponse(_Contract):
    """原严格速度目标完整证据。"""

    goal_id: str
    satisfied: bool
    subject_speed: int
    target_speed: int
    speed_margin: int


class _GoalContext(_Contract):
    """原静态目标通用上下文，规则/相克只有一个声明事实源。"""

    generation_id: int
    policy: DamagePolicy
    type_chart: tuple[TypeEfficacySnapshot, ...]


class TemplateInput(_GoalContext):
    """完整原模板搜索命令和未预先求解的知识快照。"""

    mode: Literal["templates"] = "templates"
    subject_base: PokemonSnapshot
    templates: tuple[Template, ...]
    allowed_stat_presets: tuple[str, ...]
    max_candidates: int
    goals: tuple[GoalInput, ...]
    speed_goals: tuple[SpeedInput, ...] = ()


class EvaluationInput(_GoalContext):
    """单次共享目标求值，用于验证没有动态HP的真实旧静态上下文。"""

    mode: Literal["evaluate"] = "evaluate"
    subject: PokemonSnapshot
    goal: GoalInput


class GoalResponse(_Contract):
    """全部逐项证据，伤害trace与精确KO也由现有独立oracle核对。"""

    goal_id: str
    kind: ConfigurationGoalKind
    subject_role: Literal["attacker", "defender"]
    satisfied: bool
    damage: DamageResponse
    selected_damage: int
    repetitions: int
    total_damage: str
    hp_threshold: int
    remaining_hp: str
    effective_attack: int
    effective_defense: int
    roll_policy: DamageRollPolicy


class Candidate(_Contract):
    """一套同时满足所有目标的原模板代表。"""

    preset_key: str
    stats: StatValues
    goals: tuple[GoalResponse, ...]
    speed_goals: tuple[SpeedResponse, ...]


class TemplateReply(_Contract):
    """完整可达候选或原首个失败模板的全部证据。"""

    kind: Literal["configuration_templates"]
    reachable: bool
    candidates: tuple[Candidate, ...]
    rejected_goals: tuple[GoalResponse, ...]
    rejected_speed_goals: tuple[SpeedResponse, ...]


class EvaluationReply(_Contract):
    """一条原prepared目标的全部证据，不能省略动态能力相容性事实。"""

    goals: tuple[GoalResponse, ...]


@dataclass(frozen=True)
class _Prepared:
    """只保存原读取与准备函数返回的完整事实，避免在测试中复制求解算法。"""

    subject: CalculatorPokemonProfile
    ability: DamageAbility
    item: DamageItem
    goals: tuple[_PreparedGoal, ...]
    level: int
    ruleset: BattleRuleset


class _Oracle:
    """原公开Solve用例负责求解；本类只准备两端输入和检查完整字段。"""

    @staticmethod
    def solver() -> SolvePokemonConfigurationUseCase:
        """创建原真实业务实现，内存catalog只替代SQL读取端口。"""
        return SolvePokemonConfigurationUseCase(FakeCalculatorRepository(), FakeCalculatorAbilityRepository())

    @classmethod
    def prepare(cls, command: SolvePokemonConfigurationCommand) -> _Prepared:
        """调用原读取、能力解析和prepared-goal路径，未选择模板或计算满足性。"""
        original = cls.solver()
        ruleset = original._require_ruleset(command.ruleset_id)
        subject = original._require_pokemon(ruleset_id=command.ruleset_id, pokemon_id=command.subject_pokemon_id, role="subject")
        ability = original._require_ability(ruleset_id=command.ruleset_id, pokemon_id=subject.pokemon_id,
            identifier=command.subject_ability_identifier, role="subject").domain_value
        search = SearchPokemonStatSpreadsUseCase(FakeCalculatorRepository(), FakeCalculatorAbilityRepository())
        goals, _ = search._prepare_goals(ruleset=ruleset, command=SearchPokemonStatSpreadsCommand(
            ruleset_id=command.ruleset_id, subject_pokemon_id=command.subject_pokemon_id,
            subject_ability_identifier=command.subject_ability_identifier, subject_item_identifier=command.subject_item_identifier,
            level=command.level, goals=command.goals))
        return _Prepared(subject, ability, original._item_from_identifier(command.subject_item_identifier), goals, command.level,
                         resolve_ruleset_by_version_group(ruleset.version_group_id))

    @staticmethod
    def pokemon(profile: CalculatorPokemonProfile, stats: StatValues, level: int, ability: DamageAbility, item: DamageItem) -> BattlePokemon:
        """把只读原profile与已解析字段装配为原静态上下文，不计算任何能力或倍率。"""
        return BattlePokemon(name=profile.identifier, level=level, types=profile.types, stats=stats, ability=ability, item=item)

    @classmethod
    def context(cls, prepared: _Prepared, stats: StatValues, goal: _PreparedGoal) -> DamageContext:
        """仅按原目标方向投影完整数据，实际伤害规则继续调用原责任链。"""
        subject = cls.pokemon(prepared.subject, stats, prepared.level, prepared.ability, prepared.item)
        target = cls.pokemon(goal.target, goal.target_stats, prepared.level, goal.target_ability, goal.target_item)
        attacker, defender = (subject, target) if goal.command.kind is ConfigurationGoalKind.ATTACK else (target, subject)
        return DamageContextBuilder.for_move(attacker=attacker, defender=defender,
            move=BattleMove(goal.move.identifier, goal.move.type, goal.move.category, goal.move.power)).with_ruleset(prepared.ruleset).build()

    @classmethod
    def request(cls, command: SolvePokemonConfigurationCommand, prepared: _Prepared) -> TemplateInput:
        """把原命令/知识投影至Core，模板反序注入以独立验证默认优先级。"""
        keys = cls.solver()._candidate_preset_keys(command.allowed_stat_presets)
        templates: list[Template] = []
        for key in reversed(keys):
            profile = stat_profile_from_preset(key, prepared.subject.base_stats)
            templates.append(Template(preset_key=key, ivs=_StatOracle.values(profile.ivs), evs=_StatOracle.values(profile.evs), nature=_StatOracle.nature(profile.nature_modifier)))
        goals: list[GoalInput] = []
        chart: dict[tuple[int, int], TypeEfficacySnapshot] = {}
        for goal in prepared.goals:
            goals.append(GoalInput(goal_id=goal.command.goal_id, kind=goal.command.kind,
                target=_DamageOracle.pokemon(cls.pokemon(goal.target, goal.target_stats, prepared.level, goal.target_ability, goal.target_item)),
                move=MoveSnapshot(type=goal.move.type, category=goal.move.category, power=goal.move.power),
                required_turns=goal.command.required_turns, roll_policy=goal.command.damage_roll_policy))
            defending = goal.target.types if goal.command.kind is ConfigurationGoalKind.ATTACK else prepared.subject.types
            for target_type in defending:
                chart[(goal.move.type.value, target_type.value)] = TypeEfficacySnapshot(attacking=goal.move.type, defending=target_type,
                    percent=TypeHelper.get_type_efficacy(goal.move.type, target_type))
        return TemplateInput(generation_id=prepared.ruleset.generation_id, policy=prepared.ruleset.damage_policy, type_chart=tuple(chart.values()),
            subject_base=_DamageOracle.pokemon(cls.pokemon(prepared.subject, prepared.subject.base_stats, prepared.level, prepared.ability, prepared.item)),
            templates=tuple(templates), allowed_stat_presets=command.allowed_stat_presets, max_candidates=command.max_candidates, goals=tuple(goals))

    @classmethod
    def check_goal(cls, actual: GoalResponse, expected: ConfigurationGoalResult, prepared: _Prepared, stats: StatValues, goal: _PreparedGoal) -> None:
        """逐字段比原目标证据，再使用既有完整伤害oracle检查所有roll/trace/KO。"""
        assert actual.goal_id == expected.goal_id
        assert actual.kind == expected.kind
        assert actual.subject_role == expected.subject_role
        assert actual.satisfied == expected.satisfied
        assert actual.selected_damage == expected.selected_damage
        assert actual.repetitions == expected.repetitions
        assert int(actual.total_damage) == expected.total_damage
        assert actual.hp_threshold == expected.hp_threshold
        assert int(actual.remaining_hp) == expected.remaining_hp
        assert actual.effective_attack == expected.effective_attack
        assert actual.effective_defense == expected.effective_defense
        assert actual.roll_policy == expected.roll_policy
        _DamageOracle.check(cls.context(prepared, stats, goal), actual.damage)

    @classmethod
    def check(cls, actual: TemplateReply, command: SolvePokemonConfigurationCommand, prepared: _Prepared,
              expected: SolvePokemonConfigurationResult | SolvePokemonConfigurationWithSpeedResult | None = None) -> None:
        """调用原公开execute比较整次求解，不把预期候选先交给Core。"""
        if expected is None:
            expected = cls.solver().execute(command)
        assert actual.reachable == expected.reachable
        assert len(actual.candidates) == len(expected.candidates)
        for candidate, original in zip(actual.candidates, expected.candidates, strict=True):
            assert candidate.preset_key == original.preset.key
            assert candidate.stats == original.stats
            assert len(candidate.goals) == len(original.goal_results)
            for result, reference, goal in zip(candidate.goals, original.goal_results, prepared.goals, strict=True):
                cls.check_goal(result, reference, prepared, original.stats, goal)
            speed = original.speed_goal_results if isinstance(original, SolvedConfigurationWithSpeedCandidate) else ()
            cls.check_speed(candidate.speed_goals, speed)
        assert len(actual.rejected_goals) == len(expected.rejected_goal_results)
        if actual.rejected_goals:
            key = cls.solver()._candidate_preset_keys(command.allowed_stat_presets)[0]
            stats = calculate_actual_stats(stat_profile_from_preset(key, prepared.subject.base_stats), level=prepared.level)
            for result, reference, goal in zip(actual.rejected_goals, expected.rejected_goal_results, prepared.goals, strict=True):
                cls.check_goal(result, reference, prepared, stats, goal)
        speed = expected.rejected_speed_goal_results if isinstance(expected, SolvePokemonConfigurationWithSpeedResult) else ()
        cls.check_speed(actual.rejected_speed_goals, speed)

    @staticmethod
    def check_speed(actual: tuple[SpeedResponse, ...], expected: tuple[ConfigurationSpeedGoalResult, ...]) -> None:
        """比较全部原Speed目标字段，不自行计算严格比较或margin作为oracle。"""
        assert len(actual) == len(expected)
        for result, reference in zip(actual, expected, strict=True):
            assert result.goal_id == reference.goal_id
            assert result.satisfied == reference.satisfied
            assert result.subject_speed == reference.subject_speed
            assert result.target_speed == reference.target_speed
            assert result.speed_margin == reference.speed_margin


@pytest.fixture
def configuration_goals_runner() -> Path:
    """外部独立真实编译入口；未提供时显式skip，不用fake计算替代Core。"""
    value = os.getenv("PBI_CONFIGURATION_GOALS_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_GOALS_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreConfigurationGoals:
    """真实十模板搜索、全部目标同时满足、不可达证据与旧静态能力上下文。"""

    def test_complete_original_template_search(self, configuration_goals_runner: Path) -> None:
        """64个随机原公开Solve加自定义snapshot，覆盖原模板顺序、混合攻防与候选上限。"""
        rng = random.Random(49149)
        commands: list[SolvePokemonConfigurationCommand] = []
        for case in range(64):
            goals: list[ConfigurationGoalCommand] = []
            for index in range(rng.randint(1, 4)):
                kind = rng.choice(tuple(ConfigurationGoalKind))
                target = SYLVEON_ID if kind is ConfigurationGoalKind.ATTACK else SCIZOR_ID
                ability = "cute-charm" if target == SYLVEON_ID else rng.choice(("swarm", "technician"))
                goals.append(ConfigurationGoalCommand(goal_id=f"目标-{case}-{index}", kind=kind, target_pokemon_id=target,
                    move_id=BULLET_PUNCH_ID, required_turns=rng.randint(1, 10), target_ability_identifier=ability,
                    target_item_identifier=rng.choice((None, "life-orb")), target_stat_preset=rng.choice(("no_investment", "max_hp", "max_atk_plus")),
                    damage_roll_policy=rng.choice((None, DamageRollPolicy.MIN, DamageRollPolicy.MAX))))
            commands.append(SolvePokemonConfigurationCommand(subject_pokemon_id=SCIZOR_ID, subject_ability_identifier=rng.choice(("swarm", "technician")),
                subject_item_identifier=rng.choice((None, "life-orb")), level=rng.choice((5, 50, 100)), goals=tuple(goals),
                allowed_stat_presets=rng.choice(((), ("max_atk_plus", "max_atk_plus", "no_investment", "max_hp_def_plus"), ("no_investment", "max_hp"))),
                max_candidates=rng.randint(1, 10)))
        custom = StatConfiguration(key="custom-goal", source=StatConfigurationSource.CUSTOM, name="用户配置",
            nature_id="adamant", evs=StatSpread.evs(hp=252, attack=252), ivs=StatSpread(31, 17, 31, 31, 31, 0),
            role=StatConfigurationRole.BOTH).snapshot_profile_id()
        commands.append(replace(commands[0], allowed_stat_presets=(custom, custom, "no_investment")))
        prepared = tuple(_Oracle.prepare(command) for command in commands)
        requests = tuple(_Oracle.request(command, data) for command, data in zip(commands, prepared, strict=True))
        result = subprocess.run([str(configuration_goals_runner)], input="".join(request.model_dump_json() + "\n" for request in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        for line, command, data in zip(lines, commands, prepared, strict=True):
            _Oracle.check(TemplateReply.model_validate_json(line), command, data)

    def test_reference_static_dynamic_abilities(self, configuration_goals_runner: Path) -> None:
        """32组旧prepared静态目标确认Multiscale/InnerFocus没有动态HP/畏缩伤害钩子。"""
        requests: list[EvaluationInput] = []
        prepared_cases: list[tuple[_Prepared, StatValues, _PreparedGoal]] = []
        for kind in ConfigurationGoalKind:
            for subject_ability in (DamageAbility.MULTISCALE, DamageAbility.INNER_FOCUS):
                for target_ability in (DamageAbility.MULTISCALE, DamageAbility.INNER_FOCUS):
                    for turns in (1, 2, 3, 10):
                        goal = ConfigurationGoalCommand(goal_id="static-context", kind=kind,
                            target_pokemon_id=SYLVEON_ID if kind is ConfigurationGoalKind.ATTACK else SCIZOR_ID,
                            move_id=BULLET_PUNCH_ID, required_turns=turns,
                            target_ability_identifier="cute-charm" if kind is ConfigurationGoalKind.ATTACK else "swarm")
                        command = SolvePokemonConfigurationCommand(subject_pokemon_id=SCIZOR_ID,
                            subject_ability_identifier="swarm", goals=(goal,), allowed_stat_presets=("no_investment",))
                        original = _Oracle.prepare(command)
                        prepared_goal = replace(original.goals[0], target_ability=target_ability)
                        prepared = replace(original, ability=subject_ability, goals=(prepared_goal,))
                        stats = calculate_actual_stats(stat_profile_from_preset("no_investment", prepared.subject.base_stats), level=prepared.level)
                        projected = _Oracle.request(command, prepared)
                        requests.append(EvaluationInput(generation_id=projected.generation_id, policy=projected.policy,
                            type_chart=projected.type_chart, subject=_DamageOracle.pokemon(_Oracle.pokemon(prepared.subject,
                                stats, prepared.level, subject_ability, prepared.item)), goal=projected.goals[0]))
                        prepared_cases.append((prepared, stats, prepared_goal))
        result = subprocess.run([str(configuration_goals_runner)], input="".join(request.model_dump_json() + "\n" for request in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        search = SearchPokemonStatSpreadsUseCase(FakeCalculatorRepository(), FakeCalculatorAbilityRepository())
        for line, (prepared, stats, goal) in zip(lines, prepared_cases, strict=True):
            actual = EvaluationReply.model_validate_json(line)
            assert len(actual.goals) == 1
            expected = search._evaluate_goal(subject=prepared.subject, subject_stats=stats, subject_ability=prepared.ability,
                subject_item=prepared.item, level=prepared.level, goal=goal, domain_ruleset=prepared.ruleset)
            _Oracle.check_goal(actual.goals[0], expected, prepared, stats, goal)

    def test_actual_speed_aware_template_entry(self, configuration_goals_runner: Path) -> None:
        """实际HTTP派生用例的64个damage-only/speed-only/混合案例，包括同速和双类首失败。"""
        rng = random.Random(49212)
        speedy = StatConfiguration(key="custom-speed", source=StatConfigurationSource.CUSTOM, name="速度配置",
            nature_id="jolly", evs=StatSpread.evs(speed=252), ivs=StatSpread.perfect_ivs(), role=StatConfigurationRole.BOTH).snapshot_profile_id()
        originals: list[SolvePokemonConfigurationWithSpeedCommand] = []
        bases: list[SolvePokemonConfigurationCommand] = []
        prepared: list[_Prepared] = []
        requests: list[TemplateInput] = []
        repository = FakeCalculatorRepository()
        ruleset = repository.get_ruleset_context("pokemon-champion")
        assert ruleset is not None
        for index in range(64):
            goals = () if index % 3 == 0 else (ConfigurationGoalCommand(goal_id=f"damage-{index}",
                kind=ConfigurationGoalKind.ATTACK, target_pokemon_id=SYLVEON_ID, move_id=BULLET_PUNCH_ID,
                required_turns=rng.randint(1, 4), target_ability_identifier="cute-charm"),)
            speed = () if index % 3 == 1 else tuple(ConfigurationSpeedGoalCommand(goal_id=f"speed-{index}-{axis}",
                target_pokemon_id=rng.choice((SCIZOR_ID, SYLVEON_ID)), target_stat_preset=rng.choice(("no_investment", "max_speed_plus")))
                for axis in range(rng.randint(1, 3)))
            original = SolvePokemonConfigurationWithSpeedCommand(subject_pokemon_id=SCIZOR_ID,
                subject_ability_identifier=rng.choice(("swarm", "technician")), level=rng.choice((5, 50, 100)),
                goals=goals, speed_goals=speed, allowed_stat_presets=rng.choice(((), (speedy, "no_investment", speedy))), max_candidates=rng.randint(1, 10))
            base = SolvePokemonConfigurationCommand(subject_pokemon_id=original.subject_pokemon_id,
                subject_ability_identifier=original.subject_ability_identifier, level=original.level, goals=original.goals,
                allowed_stat_presets=original.allowed_stat_presets, max_candidates=original.max_candidates)
            data = _Oracle.prepare(base)
            targets = prepare_configuration_speed_goals(repository=repository, ruleset=ruleset, level=original.level, goals=speed)
            requests.append(_Oracle.request(base, data).model_copy(update={"speed_goals": tuple(
                SpeedInput(goal_id=target.command.goal_id, target_speed=target.target_stats.speed) for target in targets)}))
            originals.append(original)
            bases.append(base)
            prepared.append(data)
        result = subprocess.run([str(configuration_goals_runner)], input="".join(request.model_dump_json() + "\n" for request in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        solver = SolvePokemonConfigurationWithSpeedUseCase(repository, FakeCalculatorAbilityRepository())
        for line, original, base, data in zip(lines, originals, bases, prepared, strict=True):
            _Oracle.check(TemplateReply.model_validate_json(line), base, data, solver.execute(original))
