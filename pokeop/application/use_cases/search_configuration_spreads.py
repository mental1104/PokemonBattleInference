"""根据攻防目标搜索 Pokémon 的 EV、IV 与性格配置。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

from pokeop.application.use_cases.calculate_catalog_damage import (
    DEFAULT_LEVEL,
    DEFAULT_RULESET_ID,
    CalculatorCatalogRepository,
    CalculatorMoveProfile,
    CalculatorPokemonProfile,
    CalculatorRulesetContext,
    stat_profile_from_preset,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityOption,
    CalculatorAbilityRepository,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationGoalKind,
    ConfigurationGoalResult,
    ConfigurationSolverInputError,
    DamageRollPolicy,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import (
    BattleMove,
    BattlePokemon,
    DamageContextBuilder,
    MoveCategory,
)
from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import defensive_stat, offensive_stat
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_version_group
from pokeop.domain.battle.stats import StatProfile, StatValues, calculate_actual_stats
from pokeop.domain.configuration_presets import NATURES, NatureDefinition, StatSpread
from pokeop.domain.models.pokemon_fields import StatField


_USEFUL_EV_VALUES: tuple[int, ...] = tuple(range(0, 253, 4))
"""现代能力公式中会改变实际能力值的 EV 代表值。"""

_STAT_FIELDS: tuple[StatField, ...] = (
    StatField.HP,
    StatField.ATTACK,
    StatField.DEFENSE,
    StatField.SPECIAL_ATTACK,
    StatField.SPECIAL_DEFENSE,
    StatField.SPEED,
)
"""生成区间结果时使用的固定能力顺序。"""

_NATURE_PREFERENCE: tuple[str, ...] = (
    "adamant",
    "modest",
    "bold",
    "calm",
    "impish",
    "careful",
    "jolly",
    "timid",
    "brave",
    "quiet",
    "relaxed",
    "sassy",
    "hardy",
    "docile",
    "serious",
    "bashful",
    "quirky",
    "lonely",
    "naughty",
    "lax",
    "hasty",
    "naive",
    "mild",
    "rash",
    "gentle",
)
"""同等可行性格的展示优先级，优先选择常见对战性格。"""


@dataclass(frozen=True, slots=True)
class StatValueRange:
    """表示一项 EV 或 IV 在当前候选中的独立安全区间。

    Args:
        minimum: 其余五项保持候选代表值时仍满足全部目标的最小值。
        maximum: 受单项上限与 EV 总量约束限制的最大安全值。
    """

    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class StatSpreadRange:
    """保存六项 EV 或 IV 的独立安全区间。"""

    hp: StatValueRange
    attack: StatValueRange
    defense: StatValueRange
    special_attack: StatValueRange
    special_defense: StatValueRange
    speed: StatValueRange

    def value_for(self, field: StatField) -> StatValueRange:
        """按能力字段读取对应区间。

        Args:
            field: 需要读取的六项能力字段。

        Returns:
            与字段对应的独立安全区间。
        """
        return getattr(self, field.value)


@dataclass(frozen=True, slots=True)
class StatNatureOption:
    """一项对当前目标等价可选的性格。"""

    identifier: str
    label: str


@dataclass(frozen=True, slots=True)
class SearchedConfigurationCandidate:
    """一套满足全部攻防目标的反推配置候选。

    Args:
        candidate_id: 前后端用于区分候选的稳定标识。
        nature_id: 计算代表值所使用的性格 identifier。
        nature_label: 代表性格展示名称。
        nature_options: 对当前目标产生相同相关能力倍率的可选性格。
        evs: 候选代表努力值分配。
        ivs: 候选代表个体值分配，当前搜索从六项 31 开始。
        ev_ranges: 其余字段固定时，各 EV 字段可独立调整的安全区间。
        iv_ranges: 其余字段固定时，各 IV 字段可独立调整的安全区间。
        stats: 代表配置在目标等级下的实际六项能力值。
        goal_results: 代表配置对全部目标的逐项复核证据。
    """

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


@dataclass(frozen=True, slots=True)
class SearchPokemonStatSpreadsCommand:
    """反推一只 Pokémon 的 EV、IV 与性格输入命令。

    Args:
        ruleset_id: 当前规则集稳定标识。
        subject_pokemon_id: 需要被反推配置的 Pokémon ID。
        subject_ability_identifier: 待配置 Pokémon 固定选择的合法特性。
        subject_item_identifier: 待配置 Pokémon 固定选择的持有道具。
        level: 本轮目标与候选统一使用的等级。
        goals: 必须由同一套配置同时满足的攻防目标。
        max_candidates: 最多返回多少套按 EV 总量排序的候选，范围为 1..10。
    """

    ruleset_id: str = DEFAULT_RULESET_ID
    subject_pokemon_id: int = 0
    subject_ability_identifier: str = ""
    subject_item_identifier: str | None = None
    level: int = DEFAULT_LEVEL
    goals: tuple[ConfigurationGoalCommand, ...] = ()
    max_candidates: int = 10


@dataclass(frozen=True, slots=True)
class SearchPokemonStatSpreadsResult:
    """EV、IV 与性格反推结果。"""

    ruleset: CalculatorRulesetContext
    subject: CalculatorPokemonProfile
    level: int
    reachable: bool
    candidates: tuple[SearchedConfigurationCandidate, ...]
    rejected_goal_results: tuple[ConfigurationGoalResult, ...]
    scope: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedAbility:
    """保留合法特性选项以及实际进入 domain 的降级值。"""

    option: CalculatorAbilityOption
    domain_value: DamageAbility


@dataclass(frozen=True, slots=True)
class _PreparedGoal:
    """缓存一条目标在搜索期间不会变化的资料，避免重复访问 repository。"""

    command: ConfigurationGoalCommand
    target: CalculatorPokemonProfile
    target_stats: StatValues
    target_ability: DamageAbility
    target_item: DamageItem
    move: CalculatorMoveProfile
    roll_policy: DamageRollPolicy


@dataclass(frozen=True, slots=True)
class _NatureGroup:
    """对当前目标相关能力具有相同倍率的一组性格。"""

    representative: NatureDefinition
    options: tuple[StatNatureOption, ...]


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    """尚未计算单字段区间的内部候选。"""

    nature_group: _NatureGroup
    evs: StatSpread
    ivs: StatSpread
    stats: StatValues
    goal_results: tuple[ConfigurationGoalResult, ...]


class ConfigurationSpreadSearchRepository(CalculatorCatalogRepository, Protocol):
    """配置反推依赖的读取端口，复用 calculator catalog 合同。"""


class SearchPokemonStatSpreadsUseCase:
    """根据多目标约束反推合法 EV、IV 与性格配置。

    当前伤害链中，待配置 Pokémon 的攻击类目标只单调依赖 Attack 或 Sp. Atk，
    防守类目标只单调依赖 HP 与 Defense/Sp. Def。搜索器利用该单调性对每项 EV
    执行二分搜索，并枚举 HP 与防御投入之间的合法权衡；Speed 不参与当前伤害目标。
    """

    def __init__(
        self,
        repository: ConfigurationSpreadSearchRepository,
        ability_repository: CalculatorAbilityRepository,
    ) -> None:
        """保存 catalog 与合法特性读取端口。

        Args:
            repository: 读取规则集、Pokémon、招式、招式归属和道具资料的端口。
            ability_repository: 读取 Pokémon 在规则集下合法特性的端口。
        """
        self._repository = repository
        self._ability_repository = ability_repository

    def execute(
        self,
        command: SearchPokemonStatSpreadsCommand,
    ) -> SearchPokemonStatSpreadsResult:
        """搜索满足全部目标的配置，并为前十条候选计算独立安全区间。

        Args:
            command: 固定 Pokémon、道具、特性、等级和多目标约束的搜索命令。

        Returns:
            包含按有效 EV 总量排序的候选、逐目标证据、范围说明和降级警告。

        Raises:
            ConfigurationSolverInputError: 输入、Pokémon、招式、特性或目标配置不合法时抛出。
        """
        self._validate_command(command)
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
        prepared_goals, goal_abilities = self._prepare_goals(
            ruleset=ruleset,
            command=command,
        )
        domain_ruleset = resolve_ruleset_by_version_group(ruleset.version_group_id)

        raw_candidates = self._search_raw_candidates(
            subject=subject,
            subject_ability=subject_ability.domain_value,
            subject_item=subject_item,
            level=command.level,
            goals=prepared_goals,
            domain_ruleset=domain_ruleset,
        )
        selected = raw_candidates[: command.max_candidates]
        candidates = tuple(
            self._finalize_candidate(
                index=index,
                raw=raw,
                subject=subject,
                subject_ability=subject_ability.domain_value,
                subject_item=subject_item,
                level=command.level,
                goals=prepared_goals,
                domain_ruleset=domain_ruleset,
            )
            for index, raw in enumerate(selected, start=1)
        )

        rejected_goal_results: tuple[ConfigurationGoalResult, ...] = ()
        if not candidates:
            # 无解时用最保守的 6V 零努力值配置返回可解释证据，而不是静默空响应。
            baseline_nature = self._nature_groups(prepared_goals)[0].representative
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

        return SearchPokemonStatSpreadsResult(
            ruleset=ruleset,
            subject=subject,
            level=command.level,
            reachable=bool(candidates),
            candidates=candidates,
            rejected_goal_results=rejected_goal_results,
            scope=(
                "同一套配置同时验收全部目标",
                "EV/IV/性格反推",
                "合法 EV 单项与总量约束",
                "单字段独立安全区间",
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
                    command=command,
                    subject_ability=subject_ability,
                    goal_abilities=goal_abilities,
                ),
                "区间表示其余五项保持代表值时，该单项可独立调整的安全范围；"
                "不要把六项区间任意组合后仍视为必然可达。",
                "当前目标不约束速度；代表解默认 Speed EV 为 0，Speed IV 为 31。",
                "未自动放宽目标；不可达表示合法 EV 总量与当前机制范围内没有配置满足全部约束。",
            ),
        )

    def _validate_command(self, command: SearchPokemonStatSpreadsCommand) -> None:
        """校验搜索预算、目标标识和输入字段的基本边界。"""
        if command.subject_pokemon_id <= 0:
            raise ConfigurationSolverInputError("subject_pokemon_id must be positive")
        if not command.subject_ability_identifier.strip():
            raise ConfigurationSolverInputError("subject_ability_identifier is required")
        if not 1 <= command.level <= 100:
            raise ConfigurationSolverInputError("level must be between 1 and 100")
        if not command.goals:
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

    def _prepare_goals(
        self,
        *,
        ruleset: CalculatorRulesetContext,
        command: SearchPokemonStatSpreadsCommand,
    ) -> tuple[tuple[_PreparedGoal, ...], dict[str, _ResolvedAbility]]:
        """一次性读取目标资料、配置、招式和特性，供整个搜索过程复用。"""
        prepared: list[_PreparedGoal] = []
        abilities: dict[str, _ResolvedAbility] = {}
        for goal in command.goals:
            target = self._require_pokemon(
                ruleset_id=ruleset.ruleset_id,
                pokemon_id=goal.target_pokemon_id,
                role=f"goal {goal.goal_id} target",
            )
            move = self._require_move(
                ruleset_id=ruleset.ruleset_id,
                move_id=goal.move_id,
            )
            target_ability = self._require_ability(
                ruleset_id=ruleset.ruleset_id,
                pokemon_id=target.pokemon_id,
                identifier=goal.target_ability_identifier,
                role=f"goal {goal.goal_id} target",
            )
            target_item = self._item_from_identifier(goal.target_item_identifier)
            target_stats = calculate_actual_stats(
                stat_profile_from_preset(goal.target_stat_preset, target.base_stats),
                level=command.level,
            )
            if goal.kind is ConfigurationGoalKind.ATTACK:
                can_use_move = self._repository.pokemon_can_use_move(
                    ruleset_id=ruleset.ruleset_id,
                    pokemon_id=command.subject_pokemon_id,
                    move_id=move.move_id,
                )
                if not can_use_move:
                    raise ConfigurationSolverInputError(
                        "attack goal move is not available for subject"
                    )
                roll_policy = goal.damage_roll_policy or DamageRollPolicy.MIN
            else:
                can_use_move = self._repository.pokemon_can_use_move(
                    ruleset_id=ruleset.ruleset_id,
                    pokemon_id=target.pokemon_id,
                    move_id=move.move_id,
                )
                if not can_use_move:
                    raise ConfigurationSolverInputError(
                        "defense goal move is not available for target"
                    )
                roll_policy = goal.damage_roll_policy or DamageRollPolicy.MAX

            abilities[goal.goal_id] = target_ability
            prepared.append(
                _PreparedGoal(
                    command=goal,
                    target=target,
                    target_stats=target_stats,
                    target_ability=target_ability.domain_value,
                    target_item=target_item,
                    move=move,
                    roll_policy=roll_policy,
                )
            )
        return tuple(prepared), abilities

    def _search_raw_candidates(
        self,
        *,
        subject: CalculatorPokemonProfile,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        domain_ruleset,
    ) -> tuple[_RawCandidate, ...]:
        """利用能力单调性搜索合法代表分配，并按 EV 成本去重排序。"""
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
        deduplicated: dict[tuple[object, ...], _RawCandidate] = {}

        for nature_group in self._nature_groups(goals):
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

            for hp_ev in _USEFUL_EV_VALUES:
                base_evs = StatSpread.evs(
                    hp=hp_ev,
                    attack=attack_ev,
                    special_attack=special_attack_ev,
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

                evs = StatSpread.evs(
                    hp=hp_ev,
                    attack=attack_ev,
                    defense=defense_ev,
                    special_attack=special_attack_ev,
                    special_defense=special_defense_ev,
                    speed=0,
                )
                if evs.total() > 510:
                    continue
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
                if not all(result.satisfied for result in goal_results):
                    continue

                candidate = _RawCandidate(
                    nature_group=nature_group,
                    evs=evs,
                    ivs=perfect_ivs,
                    stats=stats,
                    goal_results=goal_results,
                )
                signature = (
                    tuple(option.identifier for option in nature_group.options),
                    stats.hp,
                    stats.attack,
                    stats.defense,
                    stats.special_attack,
                    stats.special_defense,
                )
                existing = deduplicated.get(signature)
                if (
                    existing is None
                    or self._candidate_sort_key(candidate)
                    < self._candidate_sort_key(existing)
                ):
                    deduplicated[signature] = candidate

        return tuple(sorted(deduplicated.values(), key=self._candidate_sort_key))

    def _minimum_ev_for_subset(
        self,
        *,
        subject: CalculatorPokemonProfile,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        domain_ruleset,
        nature: NatureDefinition,
        base_evs: StatSpread,
        field: StatField,
        ivs: StatSpread,
    ) -> int | None:
        """通过二分搜索找到满足指定同类目标的最小有效 EV 代表值。"""
        if not goals:
            return 0

        current_value = getattr(base_evs, field.value)
        available_maximum = min(252, current_value + (510 - base_evs.total()))
        available_values = tuple(
            value for value in _USEFUL_EV_VALUES if value <= available_maximum
        )

        def satisfies(value: int) -> bool:
            evs = self._replace_spread(base_evs, field=field, value=value, ev=True)
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
            )

        return self._minimum_grid_value(available_values, satisfies)

    def _finalize_candidate(
        self,
        *,
        index: int,
        raw: _RawCandidate,
        subject: CalculatorPokemonProfile,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        domain_ruleset,
    ) -> SearchedConfigurationCandidate:
        """为已选代表候选补充六项 EV/IV 独立安全区间。"""
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
        return SearchedConfigurationCandidate(
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
        )

    def _build_spread_ranges(
        self,
        *,
        spread: StatSpread,
        maximum: int,
        total_limit: int | None,
        predicate: Callable[[StatSpread], bool],
        ev: bool,
    ) -> StatSpreadRange:
        """计算六项在其他字段固定时的最小可行值和合法最大值。"""
        ranges: dict[str, StatValueRange] = {}
        for field in _STAT_FIELDS:
            current = getattr(spread, field.value)

            def satisfies(value: int) -> bool:
                candidate = self._replace_spread(
                    spread,
                    field=field,
                    value=value,
                    ev=ev,
                )
                return predicate(candidate)

            minimum = self._minimum_integer_value(current, satisfies)
            if total_limit is None:
                safe_maximum = maximum
            else:
                remaining = total_limit - spread.total()
                safe_maximum = min(maximum, current + remaining)
            ranges[field.value] = StatValueRange(
                minimum=minimum,
                maximum=safe_maximum,
            )
        return StatSpreadRange(**ranges)

    def _evaluate_goals(
        self,
        *,
        subject: CalculatorPokemonProfile,
        subject_stats: StatValues,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        domain_ruleset,
    ) -> tuple[ConfigurationGoalResult, ...]:
        """使用同一套待配置能力值复核全部准备完成的目标。"""
        return tuple(
            self._evaluate_goal(
                subject=subject,
                subject_stats=subject_stats,
                subject_ability=subject_ability,
                subject_item=subject_item,
                level=level,
                goal=goal,
                domain_ruleset=domain_ruleset,
            )
            for goal in goals
        )

    def _goals_satisfied(
        self,
        *,
        subject: CalculatorPokemonProfile,
        subject_stats: StatValues,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goals: tuple[_PreparedGoal, ...],
        domain_ruleset,
    ) -> bool:
        """在搜索短路路径中判断指定目标集合是否全部满足。"""
        for goal in goals:
            result = self._evaluate_goal(
                subject=subject,
                subject_stats=subject_stats,
                subject_ability=subject_ability,
                subject_item=subject_item,
                level=level,
                goal=goal,
                domain_ruleset=domain_ruleset,
            )
            if not result.satisfied:
                return False
        return True

    def _evaluate_goal(
        self,
        *,
        subject: CalculatorPokemonProfile,
        subject_stats: StatValues,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goal: _PreparedGoal,
        domain_ruleset,
    ) -> ConfigurationGoalResult:
        """用 domain 伤害计算复核一条已经缓存资料的目标。"""
        if goal.command.kind is ConfigurationGoalKind.ATTACK:
            attacker_profile, attacker_stats = subject, subject_stats
            attacker_ability, attacker_item = subject_ability, subject_item
            defender_profile, defender_stats = goal.target, goal.target_stats
            defender_ability, defender_item = goal.target_ability, goal.target_item
            subject_role = "attacker"
        else:
            attacker_profile, attacker_stats = goal.target, goal.target_stats
            attacker_ability, attacker_item = goal.target_ability, goal.target_item
            defender_profile, defender_stats = subject, subject_stats
            defender_ability, defender_item = subject_ability, subject_item
            subject_role = "defender"

        attacker = BattlePokemon(
            name=attacker_profile.identifier,
            level=level,
            types=attacker_profile.types,
            stats=attacker_stats,
            ability=attacker_ability,
            item=attacker_item,
        )
        defender = BattlePokemon(
            name=defender_profile.identifier,
            level=level,
            types=defender_profile.types,
            stats=defender_stats,
            ability=defender_ability,
            item=defender_item,
        )
        battle_move = BattleMove(
            name=goal.move.identifier,
            type=goal.move.type,
            category=goal.move.category,
            power=goal.move.power,
        )
        damage = calculate_damage_rolls(
            DamageContextBuilder.for_move(
                attacker=attacker,
                defender=defender,
                move=battle_move,
            )
            .with_ruleset(domain_ruleset)
            .build()
        )
        selected_damage = (
            damage.min_damage
            if goal.roll_policy is DamageRollPolicy.MIN
            else damage.max_damage
        )
        total_damage = selected_damage * goal.command.required_turns
        hp_threshold = defender.stats.hp
        if goal.command.kind is ConfigurationGoalKind.ATTACK:
            satisfied = total_damage >= hp_threshold
            remaining_hp = max(0, hp_threshold - total_damage)
        else:
            satisfied = total_damage < hp_threshold
            remaining_hp = hp_threshold - total_damage

        return ConfigurationGoalResult(
            goal_id=goal.command.goal_id,
            kind=goal.command.kind,
            satisfied=satisfied,
            subject_role=subject_role,
            target=goal.target,
            move=goal.move,
            damage=damage,
            selected_damage=selected_damage,
            repetitions=goal.command.required_turns,
            total_damage=total_damage,
            hp_threshold=hp_threshold,
            remaining_hp=remaining_hp,
            effective_attack=offensive_stat(attacker, battle_move),
            effective_defense=defensive_stat(defender, battle_move),
            roll_policy=goal.roll_policy,
        )

    @staticmethod
    def _calculate_subject_stats(
        *,
        subject: CalculatorPokemonProfile,
        level: int,
        nature: NatureDefinition,
        evs: StatSpread,
        ivs: StatSpread,
    ) -> StatValues:
        """把反推配置应用到待配置 Pokémon 的种族值并计算实际能力。"""
        profile = StatProfile(
            base_stats=subject.base_stats,
            evs=evs.to_stat_values(),
            ivs=ivs.to_stat_values(),
            nature_modifier=nature.modifier(),
        )
        return calculate_actual_stats(profile, level=level)

    @staticmethod
    def _goal_subset(
        goals: tuple[_PreparedGoal, ...],
        *,
        kind: ConfigurationGoalKind,
        category: MoveCategory,
    ) -> tuple[_PreparedGoal, ...]:
        """按目标方向与招式分类筛出只依赖同一项能力的目标集合。"""
        return tuple(
            goal
            for goal in goals
            if goal.command.kind is kind and goal.move.category is category
        )

    def _nature_groups(
        self,
        goals: tuple[_PreparedGoal, ...],
    ) -> tuple[_NatureGroup, ...]:
        """把对当前相关能力提供相同倍率的性格合并为一个搜索分支。"""
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

        grouped: dict[tuple[float, ...], list[NatureDefinition]] = {}
        for nature in NATURES.values():
            modifier = nature.modifier()
            signature = tuple(modifier.value_for(field) for field in relevant_fields)
            grouped.setdefault(signature, []).append(nature)

        preference = {identifier: index for index, identifier in enumerate(_NATURE_PREFERENCE)}
        nature_groups: list[_NatureGroup] = []
        for definitions in grouped.values():
            ordered = sorted(
                definitions,
                key=lambda item: preference.get(item.identifier, len(preference)),
            )
            representative = ordered[0]
            nature_groups.append(
                _NatureGroup(
                    representative=representative,
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

    @staticmethod
    def _minimum_grid_value(
        values: tuple[int, ...],
        predicate: Callable[[int], bool],
    ) -> int | None:
        """在单调整数网格中二分查找第一个满足条件的值。"""
        if not predicate(values[-1]):
            return None
        low = 0
        high = len(values) - 1
        while low < high:
            middle = (low + high) // 2
            if predicate(values[middle]):
                high = middle
            else:
                low = middle + 1
        return values[low]

    @staticmethod
    def _minimum_integer_value(
        current: int,
        predicate: Callable[[int], bool],
    ) -> int:
        """在 0..current 单调区间中找到最小安全整数。"""
        low = 0
        high = current
        while low < high:
            middle = (low + high) // 2
            if predicate(middle):
                high = middle
            else:
                low = middle + 1
        return low

    @staticmethod
    def _replace_spread(
        spread: StatSpread,
        *,
        field: StatField,
        value: int,
        ev: bool,
    ) -> StatSpread:
        """返回只替换一项的 EV 或 IV 分布，并执行对应合法性校验。"""
        candidate = replace(spread, **{field.value: value})
        if ev:
            if value < 0 or value > 252:
                raise ValueError("each EV value must be between 0 and 252")
        else:
            candidate.validate_ivs()
        return candidate

    @staticmethod
    def _candidate_sort_key(candidate: _RawCandidate) -> tuple[object, ...]:
        """优先返回总 EV 更低、投入项更少且分配稳定的候选。"""
        invested_fields = sum(value > 0 for value in candidate.evs.values())
        return (
            candidate.evs.total(),
            invested_fields,
            candidate.nature_group.representative.identifier,
            candidate.evs.values(),
        )

    def _require_ability(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        identifier: str,
        role: str,
    ) -> _ResolvedAbility:
        """校验特性归属，并把未实现特性转换成显式 no-op domain 值。"""
        normalized = identifier.strip()
        options = self._ability_repository.list_pokemon_ability_options(
            ruleset_id=ruleset_id,
            pokemon_id=pokemon_id,
        )
        option = next(
            (candidate for candidate in options if candidate.identifier == normalized),
            None,
        )
        if option is None:
            raise ConfigurationSolverInputError(
                f"ability is not available for {role} in this ruleset: {normalized}"
            )
        return _ResolvedAbility(
            option=option,
            domain_value=DamageAbility.from_identifier(option.effect_identifier),
        )

    @staticmethod
    def _item_from_identifier(identifier: str | None) -> DamageItem:
        """把可选道具 identifier 转换为当前 domain 已实现道具。"""
        normalized = "" if identifier is None else identifier.strip()
        if not normalized or normalized == "none":
            return DamageItem.UNKNOWN
        item = DamageItem.from_identifier(normalized)
        if item is DamageItem.UNKNOWN:
            raise ConfigurationSolverInputError(
                f"unsupported item_identifier: {normalized}"
            )
        return item

    @staticmethod
    def _ability_warnings(
        *,
        command: SearchPokemonStatSpreadsCommand,
        subject_ability: _ResolvedAbility,
        goal_abilities: dict[str, _ResolvedAbility],
    ) -> tuple[str, ...]:
        """为合法但未实现的双方特性生成显式降级说明。"""
        warnings: list[str] = []
        if not subject_ability.option.implemented:
            warnings.append(
                f"待配置 Pokémon 特性“{subject_ability.option.display_name}”尚未实现，"
                "本次按无特性处理。"
            )
        for goal in command.goals:
            resolved = goal_abilities[goal.goal_id]
            if resolved.option.implemented:
                continue
            role = (
                "攻目标防守方"
                if goal.kind is ConfigurationGoalKind.ATTACK
                else "防目标攻击方"
            )
            warnings.append(
                f"{role}特性“{resolved.option.display_name}”尚未实现，本次按无特性处理。"
            )
        return tuple(warnings)

    def _require_ruleset(self, ruleset_id: str) -> CalculatorRulesetContext:
        """读取规则集，不存在时抛出稳定输入错误。"""
        ruleset = self._repository.get_ruleset_context(ruleset_id)
        if ruleset is None:
            raise ConfigurationSolverInputError(f"unknown ruleset_id: {ruleset_id}")
        return ruleset

    def _require_pokemon(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        role: str,
    ) -> CalculatorPokemonProfile:
        """读取 Pokémon 战斗资料，不存在时标明失败角色。"""
        profile = self._repository.get_pokemon_profile(
            ruleset_id=ruleset_id,
            pokemon_id=pokemon_id,
        )
        if profile is None:
            raise ConfigurationSolverInputError(
                f"unknown {role} pokemon_id: {pokemon_id}"
            )
        return profile

    def _require_move(
        self,
        *,
        ruleset_id: str,
        move_id: int,
    ) -> CalculatorMoveProfile:
        """读取固定正威力物理或特殊招式，并拒绝当前搜索无法建模的招式。"""
        move = self._repository.get_move_profile(
            ruleset_id=ruleset_id,
            move_id=move_id,
        )
        if move is None:
            raise ConfigurationSolverInputError(f"unknown move_id: {move_id}")
        if move.category not in (MoveCategory.PHYSICAL, MoveCategory.SPECIAL):
            raise ConfigurationSolverInputError(
                "status moves are not supported in configuration spread search"
            )
        if move.power <= 0:
            raise ConfigurationSolverInputError(
                "moves without fixed positive power are not supported"
            )
        return move


__all__ = [
    "SearchPokemonStatSpreadsCommand",
    "SearchPokemonStatSpreadsResult",
    "SearchPokemonStatSpreadsUseCase",
    "SearchedConfigurationCandidate",
    "StatNatureOption",
    "StatSpreadRange",
    "StatValueRange",
]
