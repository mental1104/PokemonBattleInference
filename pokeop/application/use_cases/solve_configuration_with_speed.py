"""在已有配置模板求解中加入严格速度目标。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.use_cases.calculate_catalog_damage import (
    DEFAULT_LEVEL,
    DEFAULT_RULESET_ID,
    CalculatorPokemonProfile,
    CalculatorRulesetContext,
    StatPresetView,
    stat_profile_from_preset,
)
from pokeop.application.use_cases.configuration_speed_goals import (
    ConfigurationSpeedGoalCommand,
    ConfigurationSpeedGoalResult,
    evaluate_configuration_speed_goals,
    prepare_configuration_speed_goals,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationGoalResult,
    ConfigurationGoalKind,
    ConfigurationSolverInputError,
    SolvePokemonConfigurationCommand,
    SolvePokemonConfigurationUseCase,
)
from pokeop.domain.battle.stats import StatValues, calculate_actual_stats


@dataclass(frozen=True, slots=True)
class SolvePokemonConfigurationWithSpeedCommand:
    """同时包含伤害目标与严格速度目标的模板求解命令。

    Args:
        ruleset_id: 当前规则集稳定标识。
        subject_pokemon_id: 需要验证配置的 Pokémon ID。
        subject_ability_identifier: 待配置 Pokémon 固定选择的合法特性。
        subject_item_identifier: 待配置 Pokémon 固定选择的已实现持有道具。
        level: 双方统一使用的等级。
        goals: 攻击与防守伤害目标。
        speed_goals: 要求待配置 Pokémon 严格快于参照配置的速度目标。
        allowed_stat_presets: 允许尝试的已有配置模板或快照。
        max_candidates: 最多返回的可达候选数，范围为 1..10。
    """

    ruleset_id: str = DEFAULT_RULESET_ID
    subject_pokemon_id: int = 0
    subject_ability_identifier: str = ""
    subject_item_identifier: str | None = None
    level: int = DEFAULT_LEVEL
    goals: tuple[ConfigurationGoalCommand, ...] = ()
    speed_goals: tuple[ConfigurationSpeedGoalCommand, ...] = ()
    allowed_stat_presets: tuple[str, ...] = ()
    max_candidates: int = 3


@dataclass(frozen=True, slots=True)
class SolvedConfigurationWithSpeedCandidate:
    """一套同时满足伤害目标和严格速度目标的已有配置候选。"""

    preset: StatPresetView
    stats: StatValues
    goal_results: tuple[ConfigurationGoalResult, ...]
    speed_goal_results: tuple[ConfigurationSpeedGoalResult, ...]


@dataclass(frozen=True, slots=True)
class SolvePokemonConfigurationWithSpeedResult:
    """支持速度目标的已有配置模板求解输出。"""

    ruleset: CalculatorRulesetContext
    subject: CalculatorPokemonProfile
    level: int
    reachable: bool
    candidates: tuple[SolvedConfigurationWithSpeedCandidate, ...]
    rejected_goal_results: tuple[ConfigurationGoalResult, ...]
    rejected_speed_goal_results: tuple[ConfigurationSpeedGoalResult, ...]
    scope: tuple[str, ...]
    warnings: tuple[str, ...]


class SolvePokemonConfigurationWithSpeedUseCase(SolvePokemonConfigurationUseCase):
    """复用原伤害求解器，并把严格速度比较纳入同一候选验收。"""

    def execute(
        self,
        command: SolvePokemonConfigurationWithSpeedCommand,
    ) -> SolvePokemonConfigurationWithSpeedResult:
        """从已有配置中搜索同时满足全部伤害与速度目标的候选。

        Args:
            command: 固定 Pokémon、机制、等级、目标和允许配置的完整命令。

        Returns:
            按允许配置顺序返回的可达候选；无解时返回第一套配置的双类证据。

        Raises:
            ConfigurationSolverInputError: 输入、目标、配置、招式或特性不合法时抛出。
        """
        self._validate_speed_aware_command(command)
        ruleset = self._require_ruleset(command.ruleset_id)
        subject = self._require_pokemon(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=command.subject_pokemon_id,
            role="subject",
        )
        subject_ability = self._require_ability(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=subject.pokemon_id,
            identifier=command.subject_ability_identifier,
            role="subject",
        )
        subject_item = self._item_from_identifier(command.subject_item_identifier)
        goal_abilities = {
            goal.goal_id: self._require_ability(
                ruleset_id=ruleset.ruleset_id,
                pokemon_id=goal.target_pokemon_id,
                identifier=goal.target_ability_identifier,
                role=f"goal {goal.goal_id} target",
            )
            for goal in command.goals
        }
        goal_items = {
            goal.goal_id: self._item_from_identifier(goal.target_item_identifier)
            for goal in command.goals
        }
        prepared_speed_goals = prepare_configuration_speed_goals(
            repository=self._repository,
            ruleset=ruleset,
            level=command.level,
            goals=command.speed_goals,
        )
        preset_keys = self._candidate_preset_keys(command.allowed_stat_presets)
        domain_ruleset = self._domain_ruleset(ruleset)

        candidates: list[SolvedConfigurationWithSpeedCandidate] = []
        first_rejected_goals: tuple[ConfigurationGoalResult, ...] = ()
        first_rejected_speed_goals: tuple[ConfigurationSpeedGoalResult, ...] = ()
        for preset_key in preset_keys:
            subject_stats = calculate_actual_stats(
                stat_profile_from_preset(preset_key, subject.base_stats),
                level=command.level,
            )
            goal_results = tuple(
                self._evaluate_goal(
                    ruleset=ruleset,
                    subject=subject,
                    subject_stats=subject_stats,
                    subject_ability=subject_ability.domain_value,
                    subject_item=subject_item,
                    level=command.level,
                    goal=goal,
                    target_ability=goal_abilities[goal.goal_id].domain_value,
                    target_item=goal_items[goal.goal_id],
                    domain_ruleset=domain_ruleset,
                )
                for goal in command.goals
            )
            speed_goal_results = evaluate_configuration_speed_goals(
                subject_stats=subject_stats,
                goals=prepared_speed_goals,
            )
            if all(item.satisfied for item in (*goal_results, *speed_goal_results)):
                candidates.append(
                    SolvedConfigurationWithSpeedCandidate(
                        preset=self._preset_view_for_speed(preset_key),
                        stats=subject_stats,
                        goal_results=goal_results,
                        speed_goal_results=speed_goal_results,
                    )
                )
                if len(candidates) >= command.max_candidates:
                    break
            elif not first_rejected_goals and not first_rejected_speed_goals:
                first_rejected_goals = goal_results
                first_rejected_speed_goals = speed_goal_results

        base_command = SolvePokemonConfigurationCommand(
            ruleset_id=command.ruleset_id,
            subject_pokemon_id=command.subject_pokemon_id,
            subject_ability_identifier=command.subject_ability_identifier,
            subject_item_identifier=command.subject_item_identifier,
            level=command.level,
            goals=command.goals,
            allowed_stat_presets=command.allowed_stat_presets,
            max_candidates=command.max_candidates,
        )
        return SolvePokemonConfigurationWithSpeedResult(
            ruleset=ruleset,
            subject=subject,
            level=command.level,
            reachable=bool(candidates),
            candidates=tuple(candidates),
            rejected_goal_results=first_rejected_goals if not candidates else (),
            rejected_speed_goal_results=(
                first_rejected_speed_goals if not candidates else ()
            ),
            scope=(
                "同一套配置同时验收全部目标",
                "EV/性格模板",
                "严格速度比较",
                "等级",
                "已实现持有道具",
                "已实现特性",
                "招式固定威力",
                "STAB",
                "属性克制",
                "指定随机伤害档",
            ),
            warnings=(
                *self._ability_warnings(
                    command=base_command,
                    subject_ability=subject_ability,
                    goal_abilities=goal_abilities,
                ),
                "速度目标按实际 Speed 严格大于目标配置判定；同速不满足。",
                "当前速度目标不计入战斗中的速度等级、天气、特性或道具速度修正。",
                "未自动放宽目标；不可达表示当前搜索空间内没有配置满足全部约束。",
            ),
        )

    def _validate_speed_aware_command(
        self,
        command: SolvePokemonConfigurationWithSpeedCommand,
    ) -> None:
        """校验顶层预算、伤害目标和速度目标的统一 ID 空间。"""
        if command.subject_pokemon_id <= 0:
            raise ConfigurationSolverInputError("subject_pokemon_id must be positive")
        if not command.subject_ability_identifier.strip():
            raise ConfigurationSolverInputError("subject_ability_identifier is required")
        if not 1 <= command.level <= 100:
            raise ConfigurationSolverInputError("level must be between 1 and 100")
        if not command.goals and not command.speed_goals:
            raise ConfigurationSolverInputError("at least one goal is required")
        if not 1 <= command.max_candidates <= 10:
            raise ConfigurationSolverInputError("max_candidates must be between 1 and 10")

        goal_ids: set[str] = set()
        for goal in command.goals:
            if not goal.goal_id or goal.goal_id != goal.goal_id.strip():
                raise ConfigurationSolverInputError(
                    "goal_id must be a normalized non-empty string"
                )
            if goal.goal_id in goal_ids:
                raise ConfigurationSolverInputError(f"duplicate goal_id: {goal.goal_id}")
            goal_ids.add(goal.goal_id)
            if goal.target_pokemon_id <= 0:
                raise ConfigurationSolverInputError("target_pokemon_id must be positive")
            if goal.move_id <= 0:
                raise ConfigurationSolverInputError("move_id must be positive")
            if not goal.target_ability_identifier.strip():
                raise ConfigurationSolverInputError(
                    "target_ability_identifier is required"
                )
            if not 1 <= goal.required_turns <= 10:
                raise ConfigurationSolverInputError(
                    "required_turns must be between 1 and 10"
                )
        for goal in command.speed_goals:
            if goal.goal_id in goal_ids:
                raise ConfigurationSolverInputError(f"duplicate goal_id: {goal.goal_id}")
            goal_ids.add(goal.goal_id)

    @staticmethod
    def _domain_ruleset(ruleset: CalculatorRulesetContext):
        """根据 version group 构建当前 domain 战斗规则集。"""
        from pokeop.domain.battle.rulesets.resolver import (
            resolve_ruleset_by_version_group,
        )

        return resolve_ruleset_by_version_group(ruleset.version_group_id)

    @staticmethod
    def _preset_view_for_speed(preset_key: str) -> StatPresetView:
        """复用原模板展示转换，并兼容配置快照。"""
        from pokeop.application.use_cases.solve_configuration_targets import _preset_view

        return _preset_view(preset_key)


__all__ = [
    "SolvePokemonConfigurationWithSpeedCommand",
    "SolvePokemonConfigurationWithSpeedResult",
    "SolvePokemonConfigurationWithSpeedUseCase",
    "SolvedConfigurationWithSpeedCandidate",
]
