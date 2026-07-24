"""编排 version-aware 配置读取、状态图构建和 1v1 精确概率求解。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction

from pokeop.application.configuration_space import (
    AbilityConfigurationCandidate,
    AbilitySpaceCommand,
    BattleConfiguration,
    ConfigurationEquivalenceClass,
    ConfigurationSpace,
    GenerateConfigurationSpaceCommand,
    GenerateConfigurationSpaceUseCase,
    ItemSpaceCommand,
    MechanismSupportStatus as ConfigurationMechanismSupportStatus,
    MoveConfigurationCandidate,
    MoveSpaceCommand,
    PokemonBattleConfiguration,
    PokemonConfigurationGenerator,
    PokemonConfigurationProfile,
    PokemonSpaceCommand,
    StatEnumerationMode,
    StatSpaceCommand,
)
from pokeop.application.repositories.battle_inference import (
    BattleInferenceMoveProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRepository,
    MechanismSupportStatus as RepositoryMechanismSupportStatus,
)
from pokeop.application.solver.graph_solver import (
    BattleGraphSolveResult,
    BattleGraphSolveStatus,
    ExpectedTurnsStatus,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.models import (
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphLimits,
)
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.use_cases.infer_battle import (
    BattleInferenceResult,
    BattleProbability,
    ConfigurationCoverage,
    ConfigurationWeighting,
    ConfigurationWeightSource,
    MechanismCoverage,
    OutcomeCounts,
    PolicyDescriptor,
    RepresentativePathReference,
    TerminationCount,
)
from pokeop.application.use_cases.load_battle_inference_profile import (
    LoadBattleInferenceProfileCommand,
    LoadBattleInferenceProfileResult,
    LoadBattleInferenceProfileUseCase,
)
from pokeop.domain.battle.action_policy import (
    ActionPolicy,
    FirstLegalActionPolicy,
    UniformRandomPolicy,
)
from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects.factories import (
    BattleEffectAbstractFactory,
    PokemonChampionEffectFactory,
)
from pokeop.domain.battle.effects.protocols import (
    BattleEffect,
    EffectCoverageStatus,
)
from pokeop.domain.battle.inference_outcome import (
    BattleSide,
    TerminalOutcome,
    TerminationReason,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.move_execution import StandardMoveTurnResolver
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.transitions import WeightedTransition, merge_equivalent_transitions


class BattleInferenceExecutionError(ValueError):
    """表示顶层推演无法产生完整且可信的结果。"""


class BattleActionPolicyKind(str, Enum):
    """声明一次推演使用的稳定行动策略。"""

    FIRST_LEGAL = "first-legal"
    UNIFORM_RANDOM = "uniform-random"


@dataclass(frozen=True, slots=True)
class PokemonInferenceSelection:
    """声明一侧固定配置所需的候选和能力预设。

    Args:
        pokemon_id: PokeAPI Pokémon 稳定整数 ID。
        move_ids: 本次配置携带的一到四个招式 ID，顺序不承担策略语义。
        ability_identifier: version-aware profile 中必须存在的特性标识。
        item_identifier: 受控道具标识；None 表示明确不携带道具。
        stat_preset_key: application 预设中的能力配置 key。
    """

    pokemon_id: int
    move_ids: tuple[int, ...]
    ability_identifier: str
    item_identifier: str | None = None
    stat_preset_key: str = "max_atk_plus"

    def __post_init__(self) -> None:
        """校验固定配置输入不会隐式扩张为多个候选。

        Raises:
            BattleInferenceExecutionError: ID、招式集合、特性或预设不合法时抛出。
        """
        if isinstance(self.pokemon_id, bool) or self.pokemon_id <= 0:
            raise BattleInferenceExecutionError("pokemon_id must be greater than 0")
        if not 1 <= len(self.move_ids) <= 4:
            raise BattleInferenceExecutionError("move_ids must contain one to four moves")
        if any(isinstance(move_id, bool) or move_id <= 0 for move_id in self.move_ids):
            raise BattleInferenceExecutionError("move ids must be positive integers")
        if len(self.move_ids) != len(set(self.move_ids)):
            raise BattleInferenceExecutionError("move_ids must be unique")
        if not self.ability_identifier.strip():
            raise BattleInferenceExecutionError("ability_identifier must not be blank")
        if not self.stat_preset_key.strip():
            raise BattleInferenceExecutionError("stat_preset_key must not be blank")


@dataclass(frozen=True, slots=True)
class InferFixedOneOnOneBattleCommand:
    """声明一次固定双方配置的完整 1v1 推演。

    Args:
        rules: 规则集、version group、等级和运行保护语义。
        attacker: 稳定攻击方配置选择。
        defender: 稳定防守方配置选择。
        attacker_policy: 攻击方行动选择策略。
        defender_policy: 防守方行动选择策略。
        observer: 胜负概率采用的观察方。
        graph_limits: 状态图节点、边和回合运行保护。
    """

    rules: BattleInferenceRules
    attacker: PokemonInferenceSelection
    defender: PokemonInferenceSelection
    attacker_policy: BattleActionPolicyKind = BattleActionPolicyKind.FIRST_LEGAL
    defender_policy: BattleActionPolicyKind = BattleActionPolicyKind.FIRST_LEGAL
    observer: BattleSide = BattleSide.ATTACKER
    graph_limits: StateGraphLimits = StateGraphLimits(max_nodes=20_000, max_edges=80_000)

    def __post_init__(self) -> None:
        """校验固定推演命令全部使用显式稳定类型。

        Raises:
            BattleInferenceExecutionError: 任一输入类型不满足顶层合同时抛出。
        """
        if not isinstance(self.rules, BattleInferenceRules):
            raise BattleInferenceExecutionError("rules must be BattleInferenceRules")
        if not isinstance(self.attacker, PokemonInferenceSelection):
            raise BattleInferenceExecutionError("attacker must be PokemonInferenceSelection")
        if not isinstance(self.defender, PokemonInferenceSelection):
            raise BattleInferenceExecutionError("defender must be PokemonInferenceSelection")
        if not isinstance(self.attacker_policy, BattleActionPolicyKind):
            raise BattleInferenceExecutionError("attacker_policy must be explicit")
        if not isinstance(self.defender_policy, BattleActionPolicyKind):
            raise BattleInferenceExecutionError("defender_policy must be explicit")
        if not isinstance(self.observer, BattleSide):
            raise BattleInferenceExecutionError("observer must be BattleSide")
        if not isinstance(self.graph_limits, StateGraphLimits):
            raise BattleInferenceExecutionError("graph_limits must be StateGraphLimits")


@dataclass(frozen=True, slots=True)
class InferConfigurationSpaceBattleCommand:
    """声明一次双方受控配置空间的批量推演。

    Args:
        rules: 全部配置共享的规则轴。
        attacker_pokemon_id: 攻击方 Pokémon ID。
        defender_pokemon_id: 防守方 Pokémon ID。
        configuration_space: #32 定义的受控配置空间命令。
        attacker_policy: 所有配置对共享的攻击方行动策略。
        defender_policy: 所有配置对共享的防守方行动策略。
        observer: 聚合胜负概率采用的观察方。
        graph_limits: 每个配置对独立应用的状态图运行保护。
    """

    rules: BattleInferenceRules
    attacker_pokemon_id: int
    defender_pokemon_id: int
    configuration_space: GenerateConfigurationSpaceCommand
    attacker_policy: BattleActionPolicyKind = BattleActionPolicyKind.FIRST_LEGAL
    defender_policy: BattleActionPolicyKind = BattleActionPolicyKind.FIRST_LEGAL
    observer: BattleSide = BattleSide.ATTACKER
    graph_limits: StateGraphLimits = StateGraphLimits(max_nodes=20_000, max_edges=80_000)


@dataclass(frozen=True, slots=True)
class PokemonConfigurationSummary:
    """保存结果解释层需要的一侧完整配置摘要。"""

    pokemon_id: int
    name: str
    level: int
    ability_identifier: str
    item_identifier: str
    move_ids: tuple[int, ...]
    move_names: tuple[str, ...]
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    dimension_labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class BattleConfigurationSummary:
    """保存一组固定双方配置的稳定展示摘要。"""

    attacker: PokemonConfigurationSummary
    defender: PokemonConfigurationSummary


@dataclass(frozen=True, slots=True)
class GraphInferenceSummary:
    """保存状态图规模、循环和截断诊断。"""

    unique_state_count: int
    edge_count: int
    max_turn_number: int
    closed_cycle_count: int
    terminal_reachable_cycle_count: int
    is_complete: bool
    truncation_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepresentativePathStep:
    """保存代表性路径中一个节点的轻量状态快照。"""

    node_id: int
    turn_number: int
    phase: str
    attacker_hp: int
    defender_hp: int
    outcome: str
    events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepresentativeBattlePath:
    """保存胜、负或平局的一条可解释代表性路径。"""

    reference: str
    outcome: TerminalOutcome
    steps: tuple[RepresentativePathStep, ...]


@dataclass(frozen=True, slots=True)
class FixedOneOnOneBattleResult:
    """保存固定配置的概率、图统计、配置和代表路径。"""

    configuration: BattleConfigurationSummary
    inference: BattleInferenceResult
    graph: GraphInferenceSummary
    representative_paths: tuple[RepresentativeBattlePath, ...]
    solver_status: str
    solver_diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfigurationPairInferenceResult:
    """保存配置空间中一个行为等价配置对的求解结果。"""

    index: int
    member_count: int
    coverage_weight: Fraction
    configuration: BattleConfigurationSummary
    result: FixedOneOnOneBattleResult | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationSpaceBattleResult:
    """保存配置空间批量推演的覆盖、聚合概率和极值配置。"""

    raw_configuration_count: int
    unique_configuration_count: int
    completed_count: int
    skipped_count: int
    failed_count: int
    covered_weight: Fraction
    weighted_win_probability: Fraction
    weighted_loss_probability: Fraction
    weighted_draw_probability: Fraction
    best_configuration_index: int | None
    worst_configuration_index: int | None
    observer_guaranteed_win: bool
    pairs: tuple[ConfigurationPairInferenceResult, ...]
    coverage_records: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PolicyDrivenBattleStateExpander:
    """组合双方行动策略与完整回合 resolver，生成状态图后继分布。"""

    turn_resolver: StandardMoveTurnResolver
    attacker_policy: ActionPolicy[BattleAction]
    defender_policy: ActionPolicy[BattleAction]

    def expand(self, state: BattleState) -> tuple[WeightedTransition[BattleState], ...]:
        """展开一个行动选择节点的全部策略和战斗随机分支。

        Args:
            state: 当前不可变战斗状态。

        Returns:
            玩家策略概率与回合内部随机概率相乘后的完整归一化后继集合。
        """
        attacker_actions = self.turn_resolver.legal_actions(state, BattleSide.ATTACKER)
        defender_actions = self.turn_resolver.legal_actions(state, BattleSide.DEFENDER)
        attacker_distribution = self.attacker_policy.distribution_for(attacker_actions)
        defender_distribution = self.defender_policy.distribution_for(defender_actions)
        attacker_distribution.validate_legal_actions(attacker_actions)
        defender_distribution.validate_legal_actions(defender_actions)

        transitions: list[WeightedTransition[BattleState]] = []
        for attacker_selection in attacker_distribution.selections:
            for defender_selection in defender_distribution.selections:
                resolution = self.turn_resolver.resolve(
                    state,
                    attacker_selection.action,
                    defender_selection.action,
                )
                policy_probability = (
                    attacker_selection.probability * defender_selection.probability
                )
                for transition in resolution.transitions:
                    transitions.append(
                        WeightedTransition(
                            probability=policy_probability * transition.probability,
                            state=transition.state,
                            event_summary=transition.event_summary,
                            source_key=transition.source_key or "battle.policy-and-turn",
                        )
                    )
        return merge_equivalent_transitions(transitions)


@dataclass(slots=True)
class InferOneOnOneBattleUseCase:
    """编排 repository、配置生成器、effect factory、状态图和求解器。

    Args:
        repository: version-aware profile 和受控道具候选读取端口。
        effect_factory: 当前规则集的抽象工厂；默认使用 Pokémon Champion 实现。
        solver: 精确状态图求解器；默认使用纯 Python Fraction 版本。
    """

    repository: BattleInferenceRepository
    effect_factory: BattleEffectAbstractFactory = field(
        default_factory=PokemonChampionEffectFactory
    )
    solver: PurePythonBattleGraphSolver = field(default_factory=PurePythonBattleGraphSolver)

    def execute_fixed(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedOneOnOneBattleResult:
        """执行固定双方配置的完整用户旅程。

        Args:
            command: 规则、双方固定候选、策略与图限制。

        Returns:
            包含固定配置、精确概率、状态图统计和代表路径的结果。

        Raises:
            BattleInferenceExecutionError: 配置没有收敛为唯一结果或图无法完整求解时抛出。
        """
        attacker_loaded = self._load(command.rules, command.attacker.pokemon_id)
        defender_loaded = self._load(command.rules, command.defender.pokemon_id)
        self._validate_item(command.attacker.item_identifier, attacker_loaded)
        self._validate_item(command.defender.item_identifier, defender_loaded)
        configuration_space = self._configuration_generator().execute(
            GenerateConfigurationSpaceCommand(
                attacker=self._fixed_space_command(command.attacker, command.rules.level),
                defender=self._fixed_space_command(command.defender, command.rules.level),
                max_raw_configuration_pairs=1,
            ),
            attacker_profile=self._configuration_profile(attacker_loaded.pokemon, command.rules),
            defender_profile=self._configuration_profile(defender_loaded.pokemon, command.rules),
        )
        if len(configuration_space.equivalence_classes) != 1:
            raise BattleInferenceExecutionError(
                "fixed battle command must resolve to one behavior configuration"
            )
        return self._solve_configuration(
            command.rules,
            configuration_space.equivalence_classes[0],
            configuration_space,
            attacker_policy_kind=command.attacker_policy,
            defender_policy_kind=command.defender_policy,
            observer=command.observer,
            graph_limits=command.graph_limits,
            fixed_weighting=True,
        )

    def execute_configuration_space(
        self,
        command: InferConfigurationSpaceBattleCommand,
    ) -> ConfigurationSpaceBattleResult:
        """枚举并逐一求解受控配置空间，然后按覆盖权重聚合结果。

        Args:
            command: 双方 Pokémon、配置空间、行动策略和图限制。

        Returns:
            明确区分完成、跳过、失败、覆盖权重与概率极值的批量结果。
        """
        attacker_loaded = self._load(command.rules, command.attacker_pokemon_id)
        defender_loaded = self._load(command.rules, command.defender_pokemon_id)
        configuration_space = self._configuration_generator().execute(
            command.configuration_space,
            attacker_profile=self._configuration_profile(attacker_loaded.pokemon, command.rules),
            defender_profile=self._configuration_profile(defender_loaded.pokemon, command.rules),
        )

        pair_results: list[ConfigurationPairInferenceResult] = []
        for index, equivalence_class in enumerate(configuration_space.equivalence_classes):
            summary = self._configuration_summary(equivalence_class.representative)
            try:
                solved = self._solve_configuration(
                    command.rules,
                    equivalence_class,
                    configuration_space,
                    attacker_policy_kind=command.attacker_policy,
                    defender_policy_kind=command.defender_policy,
                    observer=command.observer,
                    graph_limits=command.graph_limits,
                    fixed_weighting=False,
                )
            except (BattleInferenceExecutionError, ValueError) as exc:
                pair_results.append(
                    ConfigurationPairInferenceResult(
                        index=index,
                        member_count=equivalence_class.member_count,
                        coverage_weight=equivalence_class.weight.value,
                        configuration=summary,
                        result=None,
                        error=str(exc),
                    )
                )
                continue
            pair_results.append(
                ConfigurationPairInferenceResult(
                    index=index,
                    member_count=equivalence_class.member_count,
                    coverage_weight=equivalence_class.weight.value,
                    configuration=summary,
                    result=solved,
                )
            )

        completed = tuple(pair for pair in pair_results if pair.result is not None)
        covered_weight = sum(
            (pair.coverage_weight for pair in completed), start=Fraction(0)
        )
        weighted_win = sum(
            (
                pair.coverage_weight * pair.result.inference.win_probability.value
                for pair in completed
                if pair.result is not None
            ),
            start=Fraction(0),
        )
        weighted_loss = sum(
            (
                pair.coverage_weight * pair.result.inference.loss_probability.value
                for pair in completed
                if pair.result is not None
            ),
            start=Fraction(0),
        )
        weighted_draw = sum(
            (
                pair.coverage_weight * pair.result.inference.draw_probability.value
                for pair in completed
                if pair.result is not None
            ),
            start=Fraction(0),
        )
        best = max(
            completed,
            key=lambda pair: pair.result.inference.win_probability.value
            if pair.result is not None
            else Fraction(-1),
            default=None,
        )
        worst = min(
            completed,
            key=lambda pair: pair.result.inference.win_probability.value
            if pair.result is not None
            else Fraction(2),
            default=None,
        )
        return ConfigurationSpaceBattleResult(
            raw_configuration_count=configuration_space.statistics.raw_configuration_count,
            unique_configuration_count=(
                configuration_space.statistics.unique_configuration_count
            ),
            completed_count=len(completed),
            skipped_count=0,
            failed_count=len(pair_results) - len(completed),
            covered_weight=covered_weight,
            weighted_win_probability=weighted_win,
            weighted_loss_probability=weighted_loss,
            weighted_draw_probability=weighted_draw,
            best_configuration_index=best.index if best is not None else None,
            worst_configuration_index=worst.index if worst is not None else None,
            observer_guaranteed_win=(
                covered_weight == Fraction(1)
                and bool(completed)
                and all(
                    pair.result is not None
                    and pair.result.inference.win_probability.value == Fraction(1)
                    for pair in completed
                )
            ),
            pairs=tuple(pair_results),
            coverage_records=tuple(
                f"{record.side}:{record.dimension_key}:{record.identifier}:"
                f"{record.support_status.value}:{'included' if record.included else 'excluded'}"
                for record in configuration_space.coverage_records
            ),
        )

    def _load(
        self,
        rules: BattleInferenceRules,
        pokemon_id: int,
    ) -> LoadBattleInferenceProfileResult:
        """通过可替换 repository 加载一侧完整 profile。

        Args:
            rules: 精确 ruleset/version group 轴。
            pokemon_id: 需要加载的 Pokémon ID。

        Returns:
            包含 Pokémon、规则上下文和受控道具边界的读取结果。
        """
        return LoadBattleInferenceProfileUseCase(self.repository).execute(
            LoadBattleInferenceProfileCommand(rules=rules, pokemon_id=pokemon_id)
        )

    def _configuration_generator(self) -> GenerateConfigurationSpaceUseCase:
        """创建复用同一规则集抽象工厂的双方配置生成器。

        Returns:
            不读取数据库、只消费已准备 profile 的配置空间用例。
        """
        generator = PokemonConfigurationGenerator(self.effect_factory)
        return GenerateConfigurationSpaceUseCase(generator, generator)

    @staticmethod
    def _fixed_space_command(
        selection: PokemonInferenceSelection,
        level: int,
    ) -> PokemonSpaceCommand:
        """把一侧固定选择转换为各维度只有一个结果的配置空间命令。

        Args:
            selection: 用户或上层用例提供的固定候选。
            level: 与规则对象一致的战斗等级。

        Returns:
            原始配置数量严格为 1 的单边命令。
        """
        return PokemonSpaceCommand(
            moves=MoveSpaceCommand(
                candidate_move_ids=selection.move_ids,
                slot_counts=(len(selection.move_ids),),
                max_raw_combinations=1,
            ),
            stats=StatSpaceCommand(
                mode=StatEnumerationMode.PRESET,
                preset_keys=(selection.stat_preset_key,),
                max_raw_profiles=1,
            ),
            abilities=AbilitySpaceCommand((selection.ability_identifier,)),
            items=ItemSpaceCommand((selection.item_identifier,)),
            level=level,
            max_raw_configurations=1,
        )

    @staticmethod
    def _configuration_profile(
        profile: BattleInferencePokemonProfile,
        rules: BattleInferenceRules,
    ) -> PokemonConfigurationProfile:
        """把 repository projection 适配成 #32 配置生成器读取模型。

        Args:
            profile: persistence 已还原历史差异的完整 Pokémon profile。
            rules: 本次推演的稳定规则轴。

        Returns:
            不包含 SQLAlchemy 或 raw 表语义的配置生成器 projection。
        """
        return PokemonConfigurationProfile(
            ruleset_id=rules.ruleset_id,
            version_group_id=rules.version_group_id,
            pokemon_id=profile.pokemon_id,
            name=profile.identifier,
            types=tuple(item.domain_type for item in profile.types),
            base_stats=profile.base_stats,
            moves=tuple(
                _configuration_move_candidate(move)
                for move in profile.moves
            ),
            abilities=tuple(
                AbilityConfigurationCandidate(
                    identifier=ability.effect_identifier,
                    support_status=_configuration_support_status(
                        ability.capability.status
                    ),
                    support_reason=ability.capability.reason,
                )
                for ability in profile.abilities
            ),
            can_evolve=profile.can_evolve,
        )

    @staticmethod
    def _validate_item(
        item_identifier: str | None,
        loaded: LoadBattleInferenceProfileResult,
    ) -> None:
        """确认固定配置只使用 repository 明确暴露的受控道具。

        Args:
            item_identifier: 请求中的道具标识；None 表示不携带。
            loaded: 当前规则轴的 profile 与受控道具候选。

        Raises:
            BattleInferenceExecutionError: 请求道具不属于当前受控边界时抛出。
        """
        requested = item_identifier or "none"
        allowed = {candidate.identifier for candidate in loaded.item_candidates}
        if requested not in allowed:
            raise BattleInferenceExecutionError(
                f"item {requested!r} is not available in the controlled item boundary"
            )

    def _solve_configuration(
        self,
        rules: BattleInferenceRules,
        equivalence_class: ConfigurationEquivalenceClass,
        configuration_space: ConfigurationSpace,
        *,
        attacker_policy_kind: BattleActionPolicyKind,
        defender_policy_kind: BattleActionPolicyKind,
        observer: BattleSide,
        graph_limits: StateGraphLimits,
        fixed_weighting: bool,
    ) -> FixedOneOnOneBattleResult:
        """把一个行为等价配置对转换为状态图并精确求解。

        Args:
            rules: 当前规则轴。
            equivalence_class: 待求解配置对及其原始成员权重。
            configuration_space: 提供覆盖统计和原始配置总量。
            attacker_policy_kind: 攻击方行动策略类型。
            defender_policy_kind: 防守方行动策略类型。
            observer: 胜负概率观察方。
            graph_limits: 状态图运行保护。
            fixed_weighting: 是否按固定单配置解释权重来源。

        Returns:
            固定配置的完整可解释结果。

        Raises:
            BattleInferenceExecutionError: 状态图被截断或求解器未返回完整概率时抛出。
        """
        configuration = equivalence_class.representative
        effects = self._effects(configuration)
        attacker_policy = _policy(attacker_policy_kind)
        defender_policy = _policy(defender_policy_kind)
        expander = _PolicyDrivenBattleStateExpander(
            turn_resolver=StandardMoveTurnResolver(effects=effects),
            attacker_policy=attacker_policy,
            defender_policy=defender_policy,
        )
        graph = StateGraphBuilder(expander=expander, limits=graph_limits).build(
            _initial_state(configuration, rules)
        )
        solved = self.solver.solve(graph, observer)
        if solved.status is not BattleGraphSolveStatus.SOLVED:
            diagnostics = "; ".join(solved.diagnostics) or solved.status.value
            raise BattleInferenceExecutionError(
                f"battle graph was not completely solved: {diagnostics}"
            )
        inference = _inference_result(
            rules=rules,
            graph=graph,
            solved=solved,
            effects=effects,
            attacker_policy=attacker_policy,
            defender_policy=defender_policy,
            configuration_space=configuration_space,
            equivalence_class=equivalence_class,
            fixed_weighting=fixed_weighting,
        )
        paths = _representative_paths(graph)
        return FixedOneOnOneBattleResult(
            configuration=self._configuration_summary(configuration),
            inference=inference,
            graph=_graph_summary(graph),
            representative_paths=paths,
            solver_status=solved.status.value,
            solver_diagnostics=solved.diagnostics,
        )

    def _effects(self, configuration: BattleConfiguration) -> tuple[BattleEffect, ...]:
        """为配置中的全部具体招式、特性和道具创建去重 effect 集合。

        Args:
            configuration: 双方已经完成合法性和行为归并的固定配置。

        Returns:
            可直接注入 StandardMoveTurnResolver 的同规则集 effect 元组。
        """
        effects: list[BattleEffect] = []
        for pokemon in (configuration.attacker, configuration.defender):
            for configured_move in pokemon.moves:
                if configured_move.effect_identifier is not None:
                    effects.append(
                        self.effect_factory.create_move_effect(
                            configured_move.effect_identifier
                        )
                    )
            effects.append(
                self.effect_factory.create_ability_effect(pokemon.ability_identifier)
            )
            effects.append(
                self.effect_factory.create_item_effect(
                    None if pokemon.item_identifier == "none" else pokemon.item_identifier
                )
            )
        unique: dict[tuple[str, str], BattleEffect] = {}
        for effect in effects:
            key = (effect.coverage.source_kind.value, effect.coverage.identifier)
            unique.setdefault(key, effect)
        return tuple(unique.values())

    @staticmethod
    def _configuration_summary(
        configuration: BattleConfiguration,
    ) -> BattleConfigurationSummary:
        """把 application 配置转换为稳定且 JSON 友好的解释摘要。

        Args:
            configuration: 待展示的双方固定配置。

        Returns:
            包含能力、特性、道具、招式和维度标签的摘要。
        """
        return BattleConfigurationSummary(
            attacker=_pokemon_summary(configuration.attacker),
            defender=_pokemon_summary(configuration.defender),
        )


def _configuration_move_candidate(
    move: BattleInferenceMoveProfile,
) -> MoveConfigurationCandidate:
    """把合法招式 projection 转换为可执行或仅报告用途的配置候选。

    固定威力攻击招式和变化招式可以安全构造 domain ``MoveSpec``。变化威力攻击招式在
    当前没有动态威力解析器时只保留稳定 ID 与 unsupported 覆盖状态，避免用 ``0`` 或任意
    正数伪造基础威力并破坏 domain 不变量。

    Args:
        move: persistence 已按 version group 还原的合法招式 projection。

    Returns:
        可由 move provider 记录覆盖并在支持时参与配置枚举的候选。

    Raises:
        BattleInferenceExecutionError: 上游错误地把缺少基础威力的攻击招式标记为 supported
            时抛出，防止不完整机制进入战斗执行。
    """
    support_status = _configuration_support_status(move.capability.status)
    move_spec: MoveSpec | None = None
    if move.category is MoveCategory.STATUS or move.power is not None:
        move_spec = MoveSpec(
            move_id=move.move_id,
            move=BattleMove(
                move.display_name,
                move.type.domain_type,
                move.category,
                move.power or 0,
            ),
            max_pp=move.pp,
            priority=move.priority,
            accuracy=move.accuracy,
            effect_identifier=move.effect_identifier,
        )
    elif support_status is ConfigurationMechanismSupportStatus.SUPPORTED:
        raise BattleInferenceExecutionError(
            f"damaging move {move.identifier!r} is marked supported without positive power"
        )

    return MoveConfigurationCandidate(
        move_spec=move_spec,
        effect_identifier=move.effect_identifier,
        support_status=support_status,
        support_reason=move.capability.reason,
        candidate_move_id=move.move_id,
    )


def _configuration_support_status(
    status: RepositoryMechanismSupportStatus,
) -> ConfigurationMechanismSupportStatus:
    """把 repository 覆盖枚举转换为配置空间覆盖枚举。

    Args:
        status: repository 对合法机制的覆盖结论。

    Returns:
        配置生成器支持的 supported、partial 或 unsupported 状态。
    """
    if status in {
        RepositoryMechanismSupportStatus.SUPPORTED,
        RepositoryMechanismSupportStatus.NO_EFFECT,
    }:
        return ConfigurationMechanismSupportStatus.SUPPORTED
    if status is RepositoryMechanismSupportStatus.PARTIAL:
        return ConfigurationMechanismSupportStatus.PARTIAL
    return ConfigurationMechanismSupportStatus.UNSUPPORTED


def _policy(kind: BattleActionPolicyKind) -> ActionPolicy[BattleAction]:
    """根据显式策略枚举创建无状态行动策略。

    Args:
        kind: 固定首项或全部合法行动等概率策略。

    Returns:
        满足 domain ActionPolicy 协议的不可变策略对象。
    """
    if kind is BattleActionPolicyKind.FIRST_LEGAL:
        return FirstLegalActionPolicy[BattleAction]()
    if kind is BattleActionPolicyKind.UNIFORM_RANDOM:
        return UniformRandomPolicy[BattleAction]()
    raise BattleInferenceExecutionError(f"unsupported policy kind: {kind!r}")


def _initial_state(
    configuration: BattleConfiguration,
    rules: BattleInferenceRules,
) -> BattleState:
    """把双方 application 配置转换为满 HP、满 PP 的初始战斗状态。

    Args:
        configuration: 已验证的固定双方配置。
        rules: 状态键必须保留的完整推演规则。

    Returns:
        处于第一回合行动选择阶段的不可变 BattleState。
    """
    return BattleState(
        attacker=_initial_battler(configuration.attacker),
        defender=_initial_battler(configuration.defender),
        rules=rules,
    )


def _initial_battler(configuration: PokemonBattleConfiguration) -> BattlerState:
    """为一侧配置创建满 HP、满 PP 的动态状态。

    Args:
        configuration: 配置生成器输出的一侧代表配置。

    Returns:
        可直接进入 BattleState 的 BattlerState。
    """
    spec = PokemonSpec(
        pokemon_id=configuration.pokemon_id,
        name=configuration.name,
        level=configuration.level,
        types=configuration.types,
        stats=configuration.stats,
        ability=configuration.ability_identifier,
        item=configuration.item_identifier,
        moves=tuple(move.move_spec for move in configuration.moves),
        can_evolve=configuration.can_evolve,
    )
    return BattlerState(
        spec=spec,
        current_hp=spec.stats.hp,
        move_slots=tuple(
            MoveSlotState(
                move_id=move.move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            )
            for move in spec.moves
        ),
    )


def _pokemon_summary(
    configuration: PokemonBattleConfiguration,
) -> PokemonConfigurationSummary:
    """提取一侧配置中不会暴露 domain 内部对象的展示字段。

    Args:
        configuration: 一侧不可变 application 配置。

    Returns:
        可序列化的 Pokémon 配置摘要。
    """
    return PokemonConfigurationSummary(
        pokemon_id=configuration.pokemon_id,
        name=configuration.name,
        level=configuration.level,
        ability_identifier=configuration.ability_identifier,
        item_identifier=configuration.item_identifier,
        move_ids=tuple(move.move_spec.move_id for move in configuration.moves),
        move_names=tuple(move.move_spec.move.name for move in configuration.moves),
        hp=configuration.stats.hp,
        attack=configuration.stats.attack,
        defense=configuration.stats.defense,
        special_attack=configuration.stats.special_attack,
        special_defense=configuration.stats.special_defense,
        speed=configuration.stats.speed,
        dimension_labels=configuration.dimension_labels,
    )


def _inference_result(
    *,
    rules: BattleInferenceRules,
    graph: StateGraphBuildResult,
    solved: BattleGraphSolveResult,
    effects: tuple[BattleEffect, ...],
    attacker_policy: ActionPolicy[BattleAction],
    defender_policy: ActionPolicy[BattleAction],
    configuration_space: ConfigurationSpace,
    equivalence_class: ConfigurationEquivalenceClass,
    fixed_weighting: bool,
) -> BattleInferenceResult:
    """把图求解结果归一化为 issue #20 冻结的稳定结果合同。

    Args:
        rules: 本次推演规则。
        graph: 完整状态图和终局统计。
        solved: 精确概率求解结果。
        effects: 当前配置实际创建的机制产品。
        attacker_policy: 攻击方行动策略。
        defender_policy: 防守方行动策略。
        configuration_space: 配置覆盖统计来源。
        equivalence_class: 当前行为等价配置对。
        fixed_weighting: 是否按单一固定配置解释权重。

    Returns:
        胜负平概率严格守恒的 BattleInferenceResult。
    """
    if (
        solved.win_probability is None
        or solved.loss_probability is None
        or solved.draw_probability is None
    ):
        raise BattleInferenceExecutionError("solved graph is missing probabilities")
    paths = _representative_paths(graph)
    reasons = Counter(
        node.termination_reason
        for node in graph.nodes
        if isinstance(node.termination_reason, TerminationReason)
    )
    included, excluded = _mechanism_coverage(effects)
    expected_turns = (
        solved.expected_turns.value
        if solved.expected_turns.status is ExpectedTurnsStatus.FINITE
        else None
    )
    return BattleInferenceResult(
        rules=rules,
        observer=solved.observer,
        win_probability=BattleProbability(solved.win_probability),
        loss_probability=BattleProbability(solved.loss_probability),
        draw_probability=BattleProbability(solved.draw_probability),
        expected_turns=expected_turns,
        attacker_policy=PolicyDescriptor.from_policy(attacker_policy),
        defender_policy=PolicyDescriptor.from_policy(defender_policy),
        configuration_coverage=ConfigurationCoverage(
            covered_configurations=equivalence_class.member_count,
            total_configurations=(
                1
                if fixed_weighting
                else configuration_space.statistics.raw_configuration_count
            ),
        ),
        configuration_weighting=ConfigurationWeighting(
            source=(
                ConfigurationWeightSource.FIXED_CONFIGURATION
                if fixed_weighting
                else ConfigurationWeightSource.UNIFORM_ENUMERATION
            ),
            description=(
                "固定双方配置的精确战斗概率"
                if fixed_weighting
                else equivalence_class.weight.description
            ),
        ),
        mechanism_coverage=MechanismCoverage(included=included, excluded=excluded),
        representative_paths=tuple(
            RepresentativePathReference(path.outcome, path.reference) for path in paths
        ),
        outcome_counts=OutcomeCounts(
            attacker_wins=graph.statistics.terminal_counts.attacker_wins,
            defender_wins=graph.statistics.terminal_counts.defender_wins,
            draws=graph.statistics.terminal_counts.draws,
        ),
        termination_counts=tuple(
            TerminationCount(reason=reason, count=count)
            for reason, count in sorted(reasons.items(), key=lambda item: item[0].value)
        ),
    )


def _mechanism_coverage(
    effects: tuple[BattleEffect, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """把 effect 及其子能力覆盖记录压缩为 included/excluded 集合。

    Args:
        effects: 当前固定配置实际使用的去重 effect 产品。

    Returns:
        互不重叠、稳定排序的已纳入和未纳入机制标识元组。
    """
    included: set[str] = set()
    excluded: set[str] = set()
    for effect in effects:
        coverage = effect.coverage
        key = f"{coverage.source_kind.value}:{coverage.identifier}"
        if coverage.status is EffectCoverageStatus.UNSUPPORTED:
            excluded.add(key)
        else:
            included.add(key)
        for capability in coverage.capabilities:
            capability_key = f"{key}:{capability.identifier}"
            if capability.status is EffectCoverageStatus.UNSUPPORTED:
                excluded.add(capability_key)
            else:
                included.add(capability_key)
    included -= excluded
    return tuple(sorted(included)), tuple(sorted(excluded))


def _graph_summary(graph: StateGraphBuildResult) -> GraphInferenceSummary:
    """提取状态图规模、循环和截断诊断。

    Args:
        graph: 已完成 SCC 分类的状态图。

    Returns:
        面向 API 和前端的轻量图统计。
    """
    return GraphInferenceSummary(
        unique_state_count=graph.statistics.unique_state_count,
        edge_count=graph.statistics.edge_count,
        max_turn_number=graph.statistics.max_turn_number,
        closed_cycle_count=graph.statistics.closed_cycle_count,
        terminal_reachable_cycle_count=(
            graph.statistics.terminal_reachable_cycle_count
        ),
        is_complete=graph.is_complete,
        truncation_reasons=tuple(reason.value for reason in graph.truncation_reasons),
    )


def _representative_paths(
    graph: StateGraphBuildResult,
) -> tuple[RepresentativeBattlePath, ...]:
    """为每种已出现的终局语义重建第一条代表路径。

    Args:
        graph: 保存首次发现前驱边的完整状态图。

    Returns:
        最多包含攻击方胜、防守方胜和平局三条路径的稳定元组。
    """
    targets = (
        (GraphNodeOutcome.ATTACKER_WIN, TerminalOutcome.ATTACKER_WIN),
        (GraphNodeOutcome.DEFENDER_WIN, TerminalOutcome.DEFENDER_WIN),
        (GraphNodeOutcome.DRAW, TerminalOutcome.DRAW),
    )
    results: list[RepresentativeBattlePath] = []
    edge_by_id = {int(edge.edge_id): edge for edge in graph.edges}
    for graph_outcome, terminal_outcome in targets:
        target = next(
            (node for node in graph.nodes if node.outcome is graph_outcome),
            None,
        )
        if target is None:
            continue
        reference = f"path:{terminal_outcome.value}:node-{int(target.node_id)}"
        steps: list[RepresentativePathStep] = []
        for node_id in graph.representative_path(target.node_id):
            node = graph.node(node_id)
            events: tuple[str, ...] = ()
            if node.predecessor_edge_id is not None:
                edge = edge_by_id[int(node.predecessor_edge_id)]
                first_path = edge.event_summary.paths[0]
                events = tuple(
                    f"{event.event_type.value}:{event.outcome_id}"
                    + (
                        f":{event.numeric_value}"
                        if event.numeric_value is not None
                        else ""
                    )
                    for event in first_path
                )
            steps.append(
                RepresentativePathStep(
                    node_id=int(node.node_id),
                    turn_number=node.state.turn_number,
                    phase=node.state.phase.value,
                    attacker_hp=node.state.attacker.current_hp,
                    defender_hp=node.state.defender.current_hp,
                    outcome=node.outcome.value,
                    events=events,
                )
            )
        results.append(
            RepresentativeBattlePath(
                reference=reference,
                outcome=terminal_outcome,
                steps=tuple(steps),
            )
        )
    return tuple(results)


__all__ = [
    "BattleActionPolicyKind",
    "BattleConfigurationSummary",
    "BattleInferenceExecutionError",
    "ConfigurationPairInferenceResult",
    "ConfigurationSpaceBattleResult",
    "FixedOneOnOneBattleResult",
    "GraphInferenceSummary",
    "InferConfigurationSpaceBattleCommand",
    "InferFixedOneOnOneBattleCommand",
    "InferOneOnOneBattleUseCase",
    "PokemonConfigurationSummary",
    "PokemonInferenceSelection",
    "RepresentativeBattlePath",
    "RepresentativePathStep",
]
