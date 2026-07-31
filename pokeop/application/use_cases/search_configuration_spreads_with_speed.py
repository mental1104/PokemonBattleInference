"""在 EV、IV 与性格反推中加入严格速度目标。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.use_cases.calculate_catalog_damage import (
    DEFAULT_LEVEL,
    DEFAULT_RULESET_ID,
    CalculatorPokemonProfile,
    CalculatorRulesetContext,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityRepository,
)
from pokeop.application.use_cases.configuration_speed_goals import (
    ConfigurationSpeedGoalCommand,
    ConfigurationSpeedGoalResult,
    PreparedConfigurationSpeedGoal,
    configuration_speed_goals_satisfied,
    evaluate_configuration_speed_goals,
    prepare_configuration_speed_goals,
)
from pokeop.application.use_cases.search_configuration_spreads import (
    ConfigurationSpreadSearchRepository,
    SearchPokemonStatSpreadsCommand,
    SearchPokemonStatSpreadsUseCase,
    StatNatureOption,
    StatSpreadRange,
    _NatureGroup,
    _NATURE_PREFERENCE,
    _PreparedGoal,
    _USEFUL_EV_VALUES,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationGoalKind,
    ConfigurationGoalResult,
    ConfigurationSolverInputError,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.configuration_presets import NATURES, NatureDefinition, StatSpread
from pokeop.domain.models.pokemon_fields import StatField


@dataclass(frozen=True, slots=True)
class SearchPokemonStatSpreadsWithSpeedCommand:
    """同时包含伤害目标与严格速度目标的属性反推命令。

    Args:
        ruleset_id: 当前规则集稳定标识。
        subject_pokemon_id: 需要反推配置的 Pokémon ID。
        subject_ability_identifier: 待配置 Pokémon 固定选择的合法特性。
        subject_item_identifier: 待配置 Pokémon 固定选择的已实现持有道具。
        level: 双方目标与候选统一使用的等级。
        goals: 攻击与防守伤害目标。
        speed_goals: 要求候选实际 Speed 严格大于参照配置的目标。
        max_candidates: 最多返回多少条候选，范围为 1..10。
    """

    ruleset_id: str = DEFAULT_RULESET_ID
    subject_pokemon_id: int = 0
    subject_ability_identifier: str = ""
    subject_item_identifier: str | None = None
    level: int = DEFAULT_LEVEL
    goals: tuple[ConfigurationGoalCommand, ...] = ()
    speed_goals: tuple[ConfigurationSpeedGoalCommand, ...] = ()
    max_candidates: int = 10


@dataclass(frozen=True, slots=True)
class SearchedConfigurationWithSpeedCandidate:
    """一套同时满足伤害与严格速度目标的属性反推候选。"""

    candidate_id: str
    nature_id: str
    nature_label: str
    nature_options: tuple[StatNatureOption, ...]
    evs: StatSpread
    ivs: StatSpread
    ev_ranges: StatSpreadRange
    iv_ranges: StatSpreadRange
    stats: StatValues
    goal_results: tuple[ConfigurationGoalResult, ...]
    speed_goal_results: tuple[ConfigurationSpeedGoalResult, ...]


@dataclass(frozen=True, slots=True)
class SearchPokemonStatSpreadsWithSpeedResult:
    """支持严格速度目标的 EV、IV 与性格反推输出。"""

    ruleset: CalculatorRulesetContext
    subject: CalculatorPokemonProfile
    level: int
    reachable: bool
    candidates: tuple[SearchedConfigurationWithSpeedCandidate, ...]
    rejected_goal_results: tuple[ConfigurationGoalResult, ...]
    rejected_speed_goal_results: tuple[ConfigurationSpeedGoalResult, ...]
    scope: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RawCandidateWithSpeed:
    """尚未计算单字段区间的速度感知内部候选。"""

    nature_group: _NatureGroup
    evs: StatSpread
    ivs: StatSpread
    stats: StatValues
    goal_results: tuple[ConfigurationGoalResult, ...]
    speed_goal_results: tuple[ConfigurationSpeedGoalResult, ...]


class SearchPokemonStatSpreadsWithSpeedUseCase(SearchPokemonStatSpreadsUseCase):
    """复用伤害反推算法，并把 Speed 作为第六项单调约束参与搜索。"""

    def __init__(
        self,
        repository: ConfigurationSpreadSearchRepository,
        ability_repository: CalculatorAbilityRepository,
    ) -> None:
        """保存 catalog 与合法特性读取端口。

        Args:
            repository: 提供规则集、Pokémon、招式和道具读取模型的端口。
            ability_repository: 提供 Pokémon 合法特性选项的端口。
        """
        super().__init__(repository, ability_repository)

    def execute(
        self,
        command: SearchPokemonStatSpreadsWithSpeedCommand,
    ) -> SearchPokemonStatSpreadsWithSpeedResult:
        """搜索满足全部伤害与严格速度目标的属性配置。

        Args:
            command: 固定 Pokémon、机制、等级和两类目标的搜索命令。

        Returns:
            最多十条按 EV 成本排序、带独立 EV/IV 安全区间的候选。

        Raises:
            ConfigurationSolverInputError: 输入、目标、招式、配置或特性不合法时抛出。
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
        base_command = SearchPokemonStatSpreadsCommand(
            ruleset_id=command.ruleset_id,
            subject_pokemon_id=command.subject_pokemon_id,
            subject_ability_identifier=command.subject_ability_identifier,
            subject_item_identifier=command.subject_item_identifier,
            level=command.level,
            goals=command.goals,
            max_candidates=command.max_candidates,
        )
        prepared_goals, goal_abilities = self._prepare_goals(
            ruleset=ruleset,
            command=base_command,
        )
        prepared_speed_goals = prepare_configuration_speed_goals(
            repository=self._repository,
            ruleset=ruleset,
            level=command.level,
            goals=command.speed_goals,
        )
        domain_ruleset = self._domain_ruleset(ruleset)

        raw_candidates = self._search_raw_candidates_with_speed(
            subject=subject,
            subject_ability=subject_ability.domain_value,
            subject_item=subject_item,
            level=command.level,
            goals=prepared_goals,
            speed_goals=prepared_speed_goals,
            domain_ruleset=domain_ruleset,
        )
        selected = raw_candidates[: command.max_candidates]
        candidates = tuple(
            self._finalize_candidate_with_speed(
                index=index,
                raw=raw,
                subject=subject,
                subject_ability=subject_ability.domain_value,
                subject_item=subject_item,
                level=command.level,
                goals=prepared_goals,
                speed_goals=prepared_speed_goals,
                domain_ruleset=domain_ruleset,
            )
            for index, raw in enumerate(selected, start=1)
        )

        rejected_goal_results: tuple[ConfigurationGoalResult, ...] = ()
        rejected_speed_goal_results: tuple[ConfigurationSpeedGoalResult, ...] = ()
        if not candidates:
            # 无解时仍返回一套 6V 零努力值基线，帮助用户定位具体失败目标。
            baseline_nature = self._nature_groups_with_speed(
                prepared_goals,
                prepared_speed_goals,
            )[0].representative
            baseline_stats = self._calculate_subject_stats(
                subject=subject,
                level=command.level,
                nature=baseline_nature,
                evs=StatSpread.evs(),
                ivs=StatSpread.perfect_ivs(),
            )
            rejected_goal_results = self._evaluate_goals(
                subject=subject,
                subject_stats=baseline_stats,
                subject_ability=subject_ability.domain_value,
                subject_item=subject_item,
                level=command.level,
                goals=prepared_goals,
                domain_ruleset=domain_ruleset,
            )
            rejected_speed_goal_results = evaluate_configuration_speed_goals(
                subject_stats=baseline_stats,
                goals=prepared_speed_goals,
            )

        warnings: list[str] = [
            *self._ability_warnings(
                command=base_command,
                subject_ability=subject_ability,
                goal_abilities=goal_abilities,
            ),
            "区间表示其余五项保持代表值时，该单项可独立调整的安全范围；"
            "不要把六项区间任意组合后仍视为必然可达。",
        ]
        if prepared_speed_goals:
            warnings.extend(
                (
                    "速度目标按实际 Speed 严格大于目标配置判定；同速不满足。",
                    "当前速度目标不计入战斗中的速度等级、天气、特性或道具速度修正。",
                )
            )
        else:
            warnings.append(
                "当前目标不约束速度；代表解默认 Speed EV 为 0，Speed IV 为 31。"
            )
        warnings.append(
            "未自动放宽目标；不可达表示合法 EV 总量与当前机制范围内没有配置满足全部约束。"
        )

        return SearchPokemonStatSpreadsWithSpeedResult(
            ruleset=ruleset,
            subject=subject,
            level=command.level,
            reachable=bool(candidates),
            candidates=candidates,
            rejected_goal_results=rejected_goal_results,
            rejected_speed_goal_results=rejected_speed_goal_results,
            scope=(
                "同一套配置同时验收全部目标",
                "EV/IV/性格反推",
                "合法 EV 单项与总量约束",
                "单字段独立安全区间",
                "严格速度比较",
                "等级",
                "已实现持有道具",
                "已实现特性",
                "招式固定威力",
                "STAB",
                "属性克制",
                "指定随机伤害档",
            ),
            warnings=tuple(warnings),
        )

    def _search_raw_candidates_with_speed(
        self,
        *,
        subject: CalculatorPokemonProfile,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        speed_goals: tuple[PreparedConfigurationSpeedGoal, ...],
        domain_ruleset,
    ) -> tuple[_RawCandidateWithSpeed, ...]:
        """搜索五项伤害投入与 Speed 投入的合法组合并按成本去重。"""
        physical_attack_goals = self._goal_subset(
            goals,
            kind=ConfigurationGoalKind.ATTACK,
            category=MoveCategory.PHYSICAL,
        )
        special_attack_goals = self._goal_subset(
            goals,
            kind=ConfigurationGoalKind.ATTACK,
            category=MoveCategory.SPECIAL,
        )
        physical_defense_goals = self._goal_subset(
            goals,
            kind=ConfigurationGoalKind.DEFENSE,
            category=MoveCategory.PHYSICAL,
        )
        special_defense_goals = self._goal_subset(
            goals,
            kind=ConfigurationGoalKind.DEFENSE,
            category=MoveCategory.SPECIAL,
        )
        perfect_ivs = StatSpread.perfect_ivs()
        deduplicated: dict[tuple[object, ...], _RawCandidateWithSpeed] = {}

        for nature_group in self._nature_groups_with_speed(goals, speed_goals):
            nature = nature_group.representative
            attack_ev = self._minimum_ev_for_subset(
                subject=subject,
                subject_ability=subject_ability,
                subject_item=subject_item,
                level=level,
                goals=physical_attack_goals,
                domain_ruleset=domain_ruleset,
                nature=nature,
                base_evs=StatSpread.evs(),
                field=StatField.ATTACK,
                ivs=perfect_ivs,
            )
            special_attack_ev = self._minimum_ev_for_subset(
                subject=subject,
                subject_ability=subject_ability,
                subject_item=subject_item,
                level=level,
                goals=special_attack_goals,
                domain_ruleset=domain_ruleset,
                nature=nature,
                base_evs=StatSpread.evs(),
                field=StatField.SPECIAL_ATTACK,
                ivs=perfect_ivs,
            )
            if attack_ev is None or special_attack_ev is None:
                continue

            offensive_evs = StatSpread.evs(
                attack=attack_ev,
                special_attack=special_attack_ev,
            )
            speed_ev = self._minimum_speed_ev(
                subject=subject,
                level=level,
                nature=nature,
                base_evs=offensive_evs,
                ivs=perfect_ivs,
                goals=speed_goals,
            )
            if speed_ev is None:
                continue

            fixed_total = attack_ev + special_attack_ev + speed_ev
            for hp_ev in _USEFUL_EV_VALUES:
                # StatSpread.evs 会立即校验总量，因此必须在构造对象之前过滤超预算组合。
                if fixed_total + hp_ev > 510:
                    break
                base_evs = StatSpread.evs(
                    hp=hp_ev,
                    attack=attack_ev,
                    special_attack=special_attack_ev,
                    speed=speed_ev,
                )
                defense_ev = self._minimum_ev_for_subset(
                    subject=subject,
                    subject_ability=subject_ability,
                    subject_item=subject_item,
                    level=level,
                    goals=physical_defense_goals,
                    domain_ruleset=domain_ruleset,
                    nature=nature,
                    base_evs=base_evs,
                    field=StatField.DEFENSE,
                    ivs=perfect_ivs,
                )
                special_defense_ev = self._minimum_ev_for_subset(
                    subject=subject,
                    subject_ability=subject_ability,
                    subject_item=subject_item,
                    level=level,
                    goals=special_defense_goals,
                    domain_ruleset=domain_ruleset,
                    nature=nature,
                    base_evs=base_evs,
                    field=StatField.SPECIAL_DEFENSE,
                    ivs=perfect_ivs,
                )
                if defense_ev is None or special_defense_ev is None:
                    continue

                candidate_total = (
                    fixed_total + hp_ev + defense_ev + special_defense_ev
                )
                if candidate_total > 510:
                    continue
                evs = StatSpread.evs(
                    hp=hp_ev,
                    attack=attack_ev,
                    defense=defense_ev,
                    special_attack=special_attack_ev,
                    special_defense=special_defense_ev,
                    speed=speed_ev,
                )
                stats = self._calculate_subject_stats(
                    subject=subject,
                    level=level,
                    nature=nature,
                    evs=evs,
                    ivs=perfect_ivs,
                )
                goal_results = self._evaluate_goals(
                    subject=subject,
                    subject_stats=stats,
                    subject_ability=subject_ability,
                    subject_item=subject_item,
                    level=level,
                    goals=goals,
                    domain_ruleset=domain_ruleset,
                )
                speed_goal_results = evaluate_configuration_speed_goals(
                    subject_stats=stats,
                    goals=speed_goals,
                )
                if not all(
                    item.satisfied for item in (*goal_results, *speed_goal_results)
                ):
                    continue

                candidate = _RawCandidateWithSpeed(
                    nature_group=nature_group,
                    evs=evs,
                    ivs=perfect_ivs,
                    stats=stats,
                    goal_results=goal_results,
                    speed_goal_results=speed_goal_results,
                )
                signature = (
                    tuple(option.identifier for option in nature_group.options),
                    stats.hp,
                    stats.attack,
                    stats.defense,
                    stats.special_attack,
                    stats.special_defense,
                    stats.speed,
                )
                existing = deduplicated.get(signature)
                if existing is None or self._candidate_sort_key_with_speed(
                    candidate
                ) < self._candidate_sort_key_with_speed(existing):
                    deduplicated[signature] = candidate

        return tuple(
            sorted(deduplicated.values(), key=self._candidate_sort_key_with_speed)
        )

    def _minimum_speed_ev(
        self,
        *,
        subject: CalculatorPokemonProfile,
        level: int,
        nature: NatureDefinition,
        base_evs: StatSpread,
        ivs: StatSpread,
        goals: tuple[PreparedConfigurationSpeedGoal, ...],
    ) -> int | None:
        """在剩余 EV 预算内二分搜索满足全部严格速度目标的最小 Speed EV。"""
        if not goals:
            return 0
        current_value = base_evs.speed
        available_maximum = min(252, current_value + (510 - base_evs.total()))
        available_values = tuple(
            value for value in _USEFUL_EV_VALUES if value <= available_maximum
        )
        if not available_values:
            return None

        def satisfies(value: int) -> bool:
            evs = self._replace_spread(
                base_evs,
                field=StatField.SPEED,
                value=value,
                ev=True,
            )
            stats = self._calculate_subject_stats(
                subject=subject,
                level=level,
                nature=nature,
                evs=evs,
                ivs=ivs,
            )
            return configuration_speed_goals_satisfied(
                subject_stats=stats,
                goals=goals,
            )

        return self._minimum_grid_value(available_values, satisfies)

    def _finalize_candidate_with_speed(
        self,
        *,
        index: int,
        raw: _RawCandidateWithSpeed,
        subject: CalculatorPokemonProfile,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        speed_goals: tuple[PreparedConfigurationSpeedGoal, ...],
        domain_ruleset,
    ) -> SearchedConfigurationWithSpeedCandidate:
        """为速度感知候选计算六项 EV/IV 的独立安全区间。"""
        nature = raw.nature_group.representative

        def candidate_satisfies(evs: StatSpread, ivs: StatSpread) -> bool:
            stats = self._calculate_subject_stats(
                subject=subject,
                level=level,
                nature=nature,
                evs=evs,
                ivs=ivs,
            )
            return self._goals_satisfied(
                subject=subject,
                subject_stats=stats,
                subject_ability=subject_ability,
                subject_item=subject_item,
                level=level,
                goals=goals,
                domain_ruleset=domain_ruleset,
            ) and configuration_speed_goals_satisfied(
                subject_stats=stats,
                goals=speed_goals,
            )

        ev_ranges = self._build_spread_ranges(
            spread=raw.evs,
            maximum=252,
            total_limit=510,
            predicate=lambda candidate: candidate_satisfies(candidate, raw.ivs),
            ev=True,
        )
        iv_ranges = self._build_spread_ranges(
            spread=raw.ivs,
            maximum=31,
            total_limit=None,
            predicate=lambda candidate: candidate_satisfies(raw.evs, candidate),
            ev=False,
        )
        return SearchedConfigurationWithSpeedCandidate(
            candidate_id=(
                f"spread-{index}-{nature.identifier}-"
                f"{raw.evs.hp}-{raw.evs.attack}-{raw.evs.defense}-"
                f"{raw.evs.special_attack}-{raw.evs.special_defense}-{raw.evs.speed}"
            ),
            nature_id=nature.identifier,
            nature_label=nature.label,
            nature_options=raw.nature_group.options,
            evs=raw.evs,
            ivs=raw.ivs,
            ev_ranges=ev_ranges,
            iv_ranges=iv_ranges,
            stats=raw.stats,
            goal_results=raw.goal_results,
            speed_goal_results=raw.speed_goal_results,
        )

    def _nature_groups_with_speed(
        self,
        goals: tuple[_PreparedGoal, ...],
        speed_goals: tuple[PreparedConfigurationSpeedGoal, ...],
    ) -> tuple[_NatureGroup, ...]:
        """按当前伤害相关能力与 Speed 倍率合并等价性格。"""
        relevant_fields: list[StatField] = []
        for goal in goals:
            if goal.command.kind is ConfigurationGoalKind.ATTACK:
                field = (
                    StatField.ATTACK
                    if goal.move.category is MoveCategory.PHYSICAL
                    else StatField.SPECIAL_ATTACK
                )
            else:
                field = (
                    StatField.DEFENSE
                    if goal.move.category is MoveCategory.PHYSICAL
                    else StatField.SPECIAL_DEFENSE
                )
            if field not in relevant_fields:
                relevant_fields.append(field)
        if speed_goals and StatField.SPEED not in relevant_fields:
            relevant_fields.append(StatField.SPEED)

        grouped: dict[tuple[float, ...], list[NatureDefinition]] = {}
        for nature in NATURES.values():
            modifier = nature.modifier()
            signature = tuple(modifier.value_for(field) for field in relevant_fields)
            grouped.setdefault(signature, []).append(nature)

        preference = {
            identifier: index for index, identifier in enumerate(_NATURE_PREFERENCE)
        }
        nature_groups: list[_NatureGroup] = []
        for definitions in grouped.values():
            ordered = sorted(
                definitions,
                key=lambda item: preference.get(item.identifier, len(preference)),
            )
            nature_groups.append(
                _NatureGroup(
                    representative=ordered[0],
                    options=tuple(
                        StatNatureOption(identifier=item.identifier, label=item.label)
                        for item in ordered
                    ),
                )
            )
        return tuple(
            sorted(
                nature_groups,
                key=lambda group: preference.get(
                    group.representative.identifier,
                    len(preference),
                ),
            )
        )

    def _validate_speed_aware_command(
        self,
        command: SearchPokemonStatSpreadsWithSpeedCommand,
    ) -> None:
        """校验搜索预算以及伤害、速度目标共用的唯一 ID 空间。"""
        if command.subject_pokemon_id <= 0:
            raise ConfigurationSolverInputError("subject_pokemon_id must be positive")
        if not command.subject_ability_identifier.strip():
            raise ConfigurationSolverInputError("subject_ability_identifier is required")
        if not 1 <= command.level <= 100:
            raise ConfigurationSolverInputError("level must be between 1 and 100")
        if not command.goals and not command.speed_goals:
            raise ConfigurationSolverInputError("at least one goal is required")
        if not 1 <= command.max_candidates <= 10:
            raise ConfigurationSolverInputError(
                "max_candidates must be between 1 and 10"
            )

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
            if not goal.goal_id or goal.goal_id != goal.goal_id.strip():
                raise ConfigurationSolverInputError(
                    "speed goal_id must be a normalized non-empty string"
                )
            if goal.goal_id in goal_ids:
                raise ConfigurationSolverInputError(f"duplicate goal_id: {goal.goal_id}")
            goal_ids.add(goal.goal_id)

    @staticmethod
    def _candidate_sort_key_with_speed(
        candidate: _RawCandidateWithSpeed,
    ) -> tuple[object, ...]:
        """优先返回总 EV 更低、投入项更少且分配稳定的候选。"""
        invested_fields = sum(value > 0 for value in candidate.evs.values())
        return (
            candidate.evs.total(),
            invested_fields,
            candidate.nature_group.representative.identifier,
            candidate.evs.values(),
        )

    @staticmethod
    def _domain_ruleset(ruleset: CalculatorRulesetContext):
        """根据 version group 构建当前 domain 战斗规则集。"""
        from pokeop.domain.battle.rulesets.resolver import (
            resolve_ruleset_by_version_group,
        )

        return resolve_ruleset_by_version_group(ruleset.version_group_id)


__all__ = [
    "SearchPokemonStatSpreadsWithSpeedCommand",
    "SearchPokemonStatSpreadsWithSpeedResult",
    "SearchPokemonStatSpreadsWithSpeedUseCase",
    "SearchedConfigurationWithSpeedCandidate",
]
