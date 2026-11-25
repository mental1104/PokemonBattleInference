from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pokeop.application.use_cases.calculate_catalog_damage import (
    ALL_STAT_PRESETS,
    DEFAULT_LEVEL,
    DEFAULT_RULESET_ID,
    CalculatorCatalogRepository,
    CalculatorInputError,
    CalculatorMoveProfile,
    CalculatorPokemonProfile,
    CalculatorRulesetContext,
    StatPresetView,
    stat_profile_from_preset,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityOption,
    CalculatorAbilityRepository,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattleMove, BattlePokemon, DamageContextBuilder
from pokeop.domain.battle.damage import DamageRollResult, calculate_damage_rolls
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import defensive_stat, offensive_stat
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_version_group
from pokeop.domain.battle.stats import StatValues, calculate_actual_stats
from pokeop.domain.configuration_presets import stat_configuration_from_snapshot


class ConfigurationGoalKind(StrEnum):
    """反向配置求解支持的目标类型。"""

    ATTACK = "attack"
    DEFENSE = "defense"


class DamageRollPolicy(StrEnum):
    """目标验收时采用的随机伤害档口径。"""

    MIN = "min"
    MAX = "max"


@dataclass(frozen=True)
class SolvePokemonConfigurationCommand:
    """反向求解一只 Pokémon 配置的输入命令。

    Args:
        ruleset_id: 当前规则集稳定标识。
        subject_pokemon_id: 用户要配置的 Pokémon ID。
        subject_ability_identifier: 待配置 Pokémon 本次固定使用的合法特性。
        subject_item_identifier: 待配置 Pokémon 本次固定携带的已实现道具。
        level: 本轮配置求解使用的等级。
        goals: 必须由同一套配置同时满足的攻防目标。
        allowed_stat_presets: 允许求解器尝试的配置模板；为空时使用首版内置确定性模板。
        max_candidates: 最多返回多少套可达配置。
    """

    ruleset_id: str = DEFAULT_RULESET_ID
    subject_pokemon_id: int = 0
    subject_ability_identifier: str = ""
    subject_item_identifier: str | None = None
    level: int = DEFAULT_LEVEL
    goals: tuple["ConfigurationGoalCommand", ...] = ()
    allowed_stat_presets: tuple[str, ...] = ()
    max_candidates: int = 3


@dataclass(frozen=True)
class ConfigurationGoalCommand:
    """一条攻击或防守目标。

    Args:
        goal_id: 前端生成的稳定目标 ID，用于响应中逐项回填。
        kind: attack 表示 subject 攻击目标，defense 表示 subject 承受攻击。
        target_pokemon_id: 对手 Pokémon ID；攻击目标中它是防守方，防守目标中它是攻击方。
        move_id: 本条目标使用的招式 ID。
        required_turns: 攻击目标要求几回合内击倒；防守目标要求承受几次攻击后仍存活。
        target_ability_identifier: 该目标 Pokémon 本次固定使用的合法特性。
        target_item_identifier: 该目标 Pokémon 本次固定携带的已实现道具。
        target_stat_preset: 对手使用的配置模板。
        damage_roll_policy: attack 默认用最低伤害档保证击倒，defense 默认用最高伤害档保证存活。
    """

    goal_id: str
    kind: ConfigurationGoalKind
    target_pokemon_id: int
    move_id: int
    required_turns: int
    target_ability_identifier: str
    target_item_identifier: str | None = None
    target_stat_preset: str = "no_investment"
    damage_roll_policy: DamageRollPolicy | None = None


@dataclass(frozen=True)
class SolvedConfigurationCandidate:
    """一套满足全部目标的候选配置。"""

    preset: StatPresetView
    stats: StatValues
    goal_results: tuple["ConfigurationGoalResult", ...]


@dataclass(frozen=True)
class ConfigurationGoalResult:
    """单个目标在某套候选配置下的复核证据。"""

    goal_id: str
    kind: ConfigurationGoalKind
    satisfied: bool
    subject_role: str
    target: CalculatorPokemonProfile
    move: CalculatorMoveProfile
    damage: DamageRollResult
    selected_damage: int
    repetitions: int
    total_damage: int
    hp_threshold: int
    remaining_hp: int
    effective_attack: int | None
    effective_defense: int | None
    roll_policy: DamageRollPolicy


@dataclass(frozen=True)
class SolvePokemonConfigurationResult:
    """反向配置求解输出。"""

    ruleset: CalculatorRulesetContext
    subject: CalculatorPokemonProfile
    level: int
    reachable: bool
    candidates: tuple[SolvedConfigurationCandidate, ...]
    rejected_goal_results: tuple[ConfigurationGoalResult, ...]
    scope: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _ResolvedAbility:
    """保留合法特性选项和实际进入 domain 的降级值。"""

    option: CalculatorAbilityOption
    domain_value: DamageAbility


class ConfigurationSolverInputError(CalculatorInputError):
    """表示反向求解请求非法或超出首版能力边界。"""


class ConfigurationSolverRepository(CalculatorCatalogRepository, Protocol):
    """反向求解器依赖的读取端口，复用 calculator catalog 合同。"""


class SolvePokemonConfigurationUseCase:
    """执行确定性配置反向求解的 application use case。

    搜索空间限定为 application 声明的 EV/性格模板。双方已实现的特性与道具会进入
    统一 domain 伤害计算；合法但未实现的特性按无特性处理并返回警告。
    """

    def __init__(
        self,
        repository: ConfigurationSolverRepository,
        ability_repository: CalculatorAbilityRepository,
    ) -> None:
        """保存 catalog 与 version-aware 特性读取端口。"""
        self._repository = repository
        self._ability_repository = ability_repository

    def execute(
        self,
        command: SolvePokemonConfigurationCommand,
    ) -> SolvePokemonConfigurationResult:
        """搜索满足全部目标的配置模板并返回逐目标证据。"""
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
        preset_keys = self._candidate_preset_keys(command.allowed_stat_presets)
        domain_ruleset = resolve_ruleset_by_version_group(ruleset.version_group_id)

        candidates: list[SolvedConfigurationCandidate] = []
        first_rejected: tuple[ConfigurationGoalResult, ...] = ()
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
            if all(goal_result.satisfied for goal_result in goal_results):
                candidates.append(
                    SolvedConfigurationCandidate(
                        preset=_preset_view(preset_key),
                        stats=subject_stats,
                        goal_results=goal_results,
                    )
                )
                if len(candidates) >= command.max_candidates:
                    break
            elif not first_rejected:
                first_rejected = goal_results

        return SolvePokemonConfigurationResult(
            ruleset=ruleset,
            subject=subject,
            level=command.level,
            reachable=bool(candidates),
            candidates=tuple(candidates),
            rejected_goal_results=first_rejected if not candidates else (),
            scope=(
                "同一套配置同时验收全部目标",
                "EV/性格模板",
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
                "未自动放宽目标；不可达表示当前搜索空间内没有配置满足全部约束。",
            ),
        )

    def _validate_command(self, command: SolvePokemonConfigurationCommand) -> None:
        """校验用户请求的基本边界，避免空目标或无意义预算进入搜索。"""
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
                raise ConfigurationSolverInputError("goal_id must be a normalized non-empty string")
            if goal.goal_id in goal_ids:
                raise ConfigurationSolverInputError(f"duplicate goal_id: {goal.goal_id}")
            goal_ids.add(goal.goal_id)
            if goal.target_pokemon_id <= 0:
                raise ConfigurationSolverInputError("target_pokemon_id must be positive")
            if goal.move_id <= 0:
                raise ConfigurationSolverInputError("move_id must be positive")
            if not goal.target_ability_identifier.strip():
                raise ConfigurationSolverInputError("target_ability_identifier is required")
            if not 1 <= goal.required_turns <= 10:
                raise ConfigurationSolverInputError("required_turns must be between 1 and 10")

    def _candidate_preset_keys(self, allowed_stat_presets: tuple[str, ...]) -> tuple[str, ...]:
        """解析候选配置集合；显式传入时保持用户给定顺序并去重。"""
        default_keys = (
            "max_hp_def_plus",
            "max_hp_spdef_plus",
            "max_hp_def",
            "max_hp_spdef",
            "max_hp",
            "max_spatk_plus",
            "max_atk_plus",
            "max_spatk_neutral",
            "max_atk_neutral",
            "no_investment",
        )
        raw_keys = allowed_stat_presets or default_keys
        unique_keys: list[str] = []
        for key in raw_keys:
            if key not in ALL_STAT_PRESETS:
                try:
                    if stat_configuration_from_snapshot(key) is None:
                        raise ConfigurationSolverInputError(f"unsupported stat preset: {key}")
                except ValueError as exc:
                    raise ConfigurationSolverInputError(str(exc)) from exc
            if key not in unique_keys:
                unique_keys.append(key)
        return tuple(unique_keys)

    def _evaluate_goal(
        self,
        *,
        ruleset: CalculatorRulesetContext,
        subject: CalculatorPokemonProfile,
        subject_stats: StatValues,
        subject_ability: DamageAbility,
        subject_item: DamageItem,
        level: int,
        goal: ConfigurationGoalCommand,
        target_ability: DamageAbility,
        target_item: DamageItem,
        domain_ruleset,
    ) -> ConfigurationGoalResult:
        """用 domain 伤害计算复核一条目标。"""
        target = self._require_pokemon(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=goal.target_pokemon_id,
            role="target",
        )
        move = self._require_move(ruleset_id=ruleset.ruleset_id, move_id=goal.move_id)
        target_stats = calculate_actual_stats(
            stat_profile_from_preset(goal.target_stat_preset, target.base_stats),
            level=level,
        )
        if goal.kind is ConfigurationGoalKind.ATTACK:
            if not self._repository.pokemon_can_use_move(
                ruleset_id=ruleset.ruleset_id,
                pokemon_id=subject.pokemon_id,
                move_id=move.move_id,
            ):
                raise ConfigurationSolverInputError("attack goal move is not available for subject")
            attacker_profile, attacker_stats = subject, subject_stats
            attacker_ability, attacker_item = subject_ability, subject_item
            defender_profile, defender_stats = target, target_stats
            defender_ability, defender_item = target_ability, target_item
            subject_role = "attacker"
            roll_policy = goal.damage_roll_policy or DamageRollPolicy.MIN
        else:
            if not self._repository.pokemon_can_use_move(
                ruleset_id=ruleset.ruleset_id,
                pokemon_id=target.pokemon_id,
                move_id=move.move_id,
            ):
                raise ConfigurationSolverInputError("defense goal move is not available for target")
            attacker_profile, attacker_stats = target, target_stats
            attacker_ability, attacker_item = target_ability, target_item
            defender_profile, defender_stats = subject, subject_stats
            defender_ability, defender_item = subject_ability, subject_item
            subject_role = "defender"
            roll_policy = goal.damage_roll_policy or DamageRollPolicy.MAX

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
            name=move.identifier,
            type=move.type,
            category=move.category,
            power=move.power,
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
            if roll_policy is DamageRollPolicy.MIN
            else damage.max_damage
        )
        total_damage = selected_damage * goal.required_turns
        hp_threshold = defender.stats.hp
        if goal.kind is ConfigurationGoalKind.ATTACK:
            satisfied = total_damage >= hp_threshold
            remaining_hp = max(0, hp_threshold - total_damage)
        else:
            satisfied = total_damage < hp_threshold
            remaining_hp = hp_threshold - total_damage

        return ConfigurationGoalResult(
            goal_id=goal.goal_id,
            kind=goal.kind,
            satisfied=satisfied,
            subject_role=subject_role,
            target=target,
            move=move,
            damage=damage,
            selected_damage=selected_damage,
            repetitions=goal.required_turns,
            total_damage=total_damage,
            hp_threshold=hp_threshold,
            remaining_hp=remaining_hp,
            effective_attack=offensive_stat(attacker, battle_move),
            effective_defense=defensive_stat(defender, battle_move),
            roll_policy=roll_policy,
        )

    def _require_ability(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        identifier: str,
        role: str,
    ) -> _ResolvedAbility:
        """校验特性归属，并把未实现特性解析为 no-op domain 值。"""
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
        """把可选道具 identifier 转成 domain 已实现道具。"""
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
        command: SolvePokemonConfigurationCommand,
        subject_ability: _ResolvedAbility,
        goal_abilities: dict[str, _ResolvedAbility],
    ) -> tuple[str, ...]:
        """为合法但未实现的特性返回显式降级说明。"""
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
            role = "攻目标防守方" if goal.kind is ConfigurationGoalKind.ATTACK else "防目标攻击方"
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
        """读取宝可梦资料，不存在时标明失败角色。"""
        profile = self._repository.get_pokemon_profile(
            ruleset_id=ruleset_id,
            pokemon_id=pokemon_id,
        )
        if profile is None:
            raise ConfigurationSolverInputError(f"unknown {role} pokemon_id: {pokemon_id}")
        return profile

    def _require_move(self, *, ruleset_id: str, move_id: int) -> CalculatorMoveProfile:
        """读取招式资料，只允许当前基础伤害链路支持的固定威力招式。"""
        move = self._repository.get_move_profile(ruleset_id=ruleset_id, move_id=move_id)
        if move is None:
            raise ConfigurationSolverInputError(f"unknown move_id: {move_id}")
        if move.power <= 0:
            raise ConfigurationSolverInputError(
                "moves without fixed positive power are not supported"
            )
        return move


def _preset_view(preset_key: str) -> StatPresetView:
    """返回候选配置展示信息，兼容内置 key 和配置快照。"""
    preset = ALL_STAT_PRESETS.get(preset_key)
    if preset is not None:
        return preset
    payload = stat_configuration_from_snapshot(preset_key)
    if payload is None:
        raise ConfigurationSolverInputError(f"unsupported stat preset: {preset_key}")
    label = str(payload["label"]).strip() or "自定义配置"
    return StatPresetView(
        key=preset_key,
        label=label,
        assumption="来自配置预设快照，包含显式 nature / EV / IV。",
    )


__all__ = [
    "ConfigurationGoalCommand",
    "ConfigurationGoalKind",
    "ConfigurationGoalResult",
    "ConfigurationSolverInputError",
    "DamageRollPolicy",
    "SolvePokemonConfigurationCommand",
    "SolvePokemonConfigurationResult",
    "SolvePokemonConfigurationUseCase",
    "SolvedConfigurationCandidate",
]
