"""编排候选技能组合枚举与单个固定配置精确概率摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pokeop.application.battle_candidate_pool.listing import (
    ListBattleCandidatePoolCommand,
    ListBattleCandidatePoolUseCase,
)
from pokeop.application.battle_candidate_pool.models import BattleCandidatePool
from pokeop.application.configuration_space import (
    MAX_TOTAL_CANDIDATE_MOVES,
    ConfigurationEquivalenceClass,
    ConfigurationSpace,
    FixedPokemonConfiguration,
    MoveCandidatePool,
    OneOnOneMovePoolCommand,
    PokemonMovePoolSelection,
)
from pokeop.application.solver.graph_solver import BattleGraphSolveStatus
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.solver.summary_state_graph import (
    SummaryStateGraphBuilder,
    merge_summary_transitions,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
    BattleInferenceCompleteness,
    BattleInferenceExecutionError,
    BattleInferenceSummary,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
)
from pokeop.application.use_cases.infer_one_on_one_battle import _core
from pokeop.domain.battle.action_policy import ActionPolicy
from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.state import BattleState
from pokeop.domain.battle.structured_turn_resolver import (
    BattleEventStandardMoveTurnResolver,
)
from pokeop.domain.battle.transitions import (
    TransitionEventSummary,
    WeightedTransition,
)


@dataclass(frozen=True, slots=True)
class FixedBattleSideSelection:
    """保存技能组合枚举和固定推演共享的一侧完整输入。

    Args:
        pokemon_id: PokeAPI Pokémon 或独立 form 的稳定正整数 ID。
        form_id: 当前首版必须为 None；具体形态应通过对应 ``pokemon_id`` 选择。
        level: 战斗等级，双方在同一次固定推演中必须一致。
        stat_profile_id: 可由 application 配置生成器还原最终能力值的预设 key。
        ability_identifier: 当前 version group 下固定使用的特性 identifier。
        item_identifier: 固定道具 identifier；None 表示明确不携带道具。
    """

    pokemon_id: int
    form_id: int | None
    level: int
    stat_profile_id: str
    ability_identifier: str
    item_identifier: str | None = None

    def __post_init__(self) -> None:
        """校验固定配置字段不会在进入 repository 后产生隐式歧义。"""
        if isinstance(self.pokemon_id, bool) or self.pokemon_id <= 0:
            raise ValueError("pokemon_id must be a positive integer")
        if self.form_id is not None:
            raise ValueError(
                "form_id is not accepted yet; select the form-specific pokemon_id"
            )
        if isinstance(self.level, bool) or not 1 <= self.level <= 100:
            raise ValueError("level must be between 1 and 100")
        for field_name, value in (
            ("stat_profile_id", self.stat_profile_id),
            ("ability_identifier", self.ability_identifier),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be a normalized non-empty string")
        if self.item_identifier is not None and (
            not isinstance(self.item_identifier, str)
            or not self.item_identifier
            or self.item_identifier != self.item_identifier.strip()
        ):
            raise ValueError(
                "item_identifier must be normalized when it is provided"
            )

    def to_configuration(self) -> FixedPokemonConfiguration:
        """转换为现有配置空间合同使用的固定 Pokémon 配置。

        Returns:
            字段语义完全一致的 ``FixedPokemonConfiguration`` 新对象。
        """
        return FixedPokemonConfiguration(
            pokemon_id=self.pokemon_id,
            form_id=self.form_id,
            level=self.level,
            stat_profile_id=self.stat_profile_id,
            ability_identifier=self.ability_identifier,
            item_identifier=self.item_identifier,
        )


@dataclass(frozen=True, slots=True)
class MoveSetOption:
    """表示用户可选择的一组规范化一到四招技能组合。"""

    move_set_id: str
    move_ids: tuple[int, ...]
    move_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MoveSetSideResult:
    """返回一侧候选池及其全部规范化技能组合。"""

    pokemon_id: int
    pokemon_name: str
    candidate_count: int
    move_set_count: int
    move_sets: tuple[MoveSetOption, ...]


@dataclass(frozen=True, slots=True)
class EnumerateMoveSetCombinationsCommand:
    """声明只枚举技能组合、绝不启动 solver 或后台任务的查询。

    Args:
        rules: 候选合法性和历史数据使用的稳定规则轴。
        calculation_revision: 页面候选池绑定的计算语义版本。
        attacker: 攻击方固定配置。
        attacker_candidate_move_ids: 攻击方已选且希望组合的一到十个招式 ID。
        defender: 防守方固定配置。
        defender_candidate_move_ids: 防守方已选且希望组合的一到十个招式 ID。
    """

    rules: BattleInferenceRules
    calculation_revision: str
    attacker: FixedBattleSideSelection
    attacker_candidate_move_ids: tuple[int, ...]
    defender: FixedBattleSideSelection
    defender_candidate_move_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """校验规则、等级和总候选预算满足首版组合合同。"""
        if not isinstance(self.rules, BattleInferenceRules):
            raise ValueError("rules must be a BattleInferenceRules")
        if not self.calculation_revision.strip():
            raise ValueError("calculation_revision must not be blank")
        if not isinstance(self.attacker, FixedBattleSideSelection):
            raise ValueError("attacker must be a FixedBattleSideSelection")
        if not isinstance(self.defender, FixedBattleSideSelection):
            raise ValueError("defender must be a FixedBattleSideSelection")
        if self.attacker.level != self.defender.level:
            raise ValueError("both sides must use the same level in v1")
        if self.rules.level != self.attacker.level:
            raise ValueError("rules.level must match both fixed side levels")
        total = len(self.attacker_candidate_move_ids) + len(
            self.defender_candidate_move_ids
        )
        if total > MAX_TOTAL_CANDIDATE_MOVES:
            raise ValueError("attacker and defender candidates must total at most 20")


@dataclass(frozen=True, slots=True)
class EnumerateMoveSetCombinationsResult:
    """返回双方独立技能组列表和理论配置对数量。"""

    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    attacker: MoveSetSideResult
    defender: MoveSetSideResult
    configuration_pair_count: int


@runtime_checkable
class CandidatePoolReader(Protocol):
    """读取 version-aware 候选池的窄 application 协议。"""

    def execute(self, command: ListBattleCandidatePoolCommand) -> BattleCandidatePool:
        """返回指定 Pokémon 在规则轴下的完整候选池。"""


@dataclass(slots=True)
class EnumerateMoveSetCombinationsUseCase:
    """校验候选机制后，只生成左右技能组列表和理论笛卡尔积数量。

    该用例不会创建 ``configuration job``，也不会遍历配置对执行状态图。最多只物化
    每侧 ``C(10, 4)=210`` 个技能组，适合直接用于交互式页面。

    Args:
        candidate_pool_reader: 读取合法性、展示名称和结构化机制准入的 application 端口。
    """

    candidate_pool_reader: CandidatePoolReader

    def __post_init__(self) -> None:
        """校验候选池读取器实现稳定窄协议。"""
        if not isinstance(self.candidate_pool_reader, CandidatePoolReader):
            raise ValueError("candidate_pool_reader must implement CandidatePoolReader")

    def execute(
        self,
        command: EnumerateMoveSetCombinationsCommand,
    ) -> EnumerateMoveSetCombinationsResult:
        """返回已通过严格机制准入的双方技能组合。

        Args:
            command: 固定双方配置、规则轴和候选招式 ID。

        Returns:
            每侧独立技能组列表及两侧组合数乘积；不返回配置对明细。

        Raises:
            ValueError: 候选非法、不可选择、版本不一致或固定特性/道具不可执行时抛出。
        """
        attacker_pool = self._load_pool(command.rules, command.attacker.pokemon_id)
        defender_pool = self._load_pool(command.rules, command.defender.pokemon_id)
        self._validate_revision(command.calculation_revision, attacker_pool)
        self._validate_revision(command.calculation_revision, defender_pool)
        self._validate_fixed_mechanisms(command.attacker, attacker_pool)
        self._validate_fixed_mechanisms(command.defender, defender_pool)

        attacker_move_ids = self._validated_move_ids(
            command.attacker_candidate_move_ids,
            attacker_pool,
        )
        defender_move_ids = self._validated_move_ids(
            command.defender_candidate_move_ids,
            defender_pool,
        )
        normalized_command = OneOnOneMovePoolCommand(
            ruleset_id=command.rules.ruleset_id,
            version_group_id=command.rules.version_group_id,
            calculation_revision=command.calculation_revision,
            attacker=PokemonMovePoolSelection(
                fixed=command.attacker.to_configuration(),
                candidate_move_ids=attacker_move_ids,
            ),
            defender=PokemonMovePoolSelection(
                fixed=command.defender.to_configuration(),
                candidate_move_ids=defender_move_ids,
            ),
        )
        return EnumerateMoveSetCombinationsResult(
            ruleset_id=command.rules.ruleset_id,
            version_group_id=command.rules.version_group_id,
            calculation_revision=command.calculation_revision,
            attacker=self._side_result(
                normalized_command.attacker,
                attacker_pool,
            ),
            defender=self._side_result(
                normalized_command.defender,
                defender_pool,
            ),
            configuration_pair_count=normalized_command.configuration_pair_count,
        )

    def _load_pool(
        self,
        rules: BattleInferenceRules,
        pokemon_id: int,
    ) -> BattleCandidatePool:
        """读取单侧候选池并保持规则轴由调用命令唯一决定。"""
        return self.candidate_pool_reader.execute(
            ListBattleCandidatePoolCommand(rules=rules, pokemon_id=pokemon_id)
        )

    @staticmethod
    def _validate_revision(
        calculation_revision: str,
        pool: BattleCandidatePool,
    ) -> None:
        """拒绝页面旧候选池和当前服务计算版本混用。"""
        if pool.calculation_revision != calculation_revision:
            raise ValueError(
                "candidate pool calculation_revision does not match the request"
            )

    @staticmethod
    def _validate_fixed_mechanisms(
        side: FixedBattleSideSelection,
        pool: BattleCandidatePool,
    ) -> None:
        """确认固定特性和道具在当前计算版本下可执行。"""
        ability = pool.ability_by_identifier(side.ability_identifier)
        if ability is None or not ability.admission.selectable:
            raise ValueError(
                f"ability {side.ability_identifier!r} is not selectable for "
                f"Pokemon {side.pokemon_id}"
            )
        requested_item = side.item_identifier or "none"
        item = pool.item_by_identifier(requested_item)
        if item is None or not item.admission.selectable:
            raise ValueError(
                f"item {requested_item!r} is not selectable for Pokemon "
                f"{side.pokemon_id}"
            )

    @staticmethod
    def _validated_move_ids(
        move_ids: tuple[int, ...],
        pool: BattleCandidatePool,
    ) -> tuple[int, ...]:
        """规范化候选 ID，并一次性拒绝非法或机制不完整的招式。"""
        normalized = MoveCandidatePool(tuple(move_ids)).candidate_move_ids
        rejected: list[str] = []
        for move_id in normalized:
            candidate = pool.move_by_id(move_id)
            if candidate is None:
                rejected.append(f"{move_id}:not-legal")
            elif not candidate.admission.selectable:
                rejected.append(
                    f"{move_id}:{candidate.admission.status.value}:"
                    f"{candidate.admission.reason}"
                )
        if rejected:
            raise ValueError("move selection rejected: " + "; ".join(rejected))
        return normalized

    @staticmethod
    def _side_result(
        selection: PokemonMovePoolSelection,
        pool: BattleCandidatePool,
    ) -> MoveSetSideResult:
        """把规范化技能组投影为包含展示名称的轻量结果。"""
        names_by_id = {
            candidate.move_id: candidate.move.display_name
            for candidate in pool.moves
        }
        move_sets = tuple(
            MoveSetOption(
                move_set_id="move-set:" + ",".join(str(value) for value in move_ids),
                move_ids=move_ids,
                move_names=tuple(names_by_id[move_id] for move_id in move_ids),
            )
            for move_ids in selection.iter_move_sets()
        )
        return MoveSetSideResult(
            pokemon_id=pool.pokemon_id,
            pokemon_name=pool.pokemon_display_name,
            candidate_count=len(selection.candidate_move_ids),
            move_set_count=len(move_sets),
            move_sets=move_sets,
        )


@dataclass(frozen=True, slots=True)
class FixedBattleSummaryResult:
    """返回固定配置精确摘要，不持有完整可探索图 artifact。"""

    summary: BattleInferenceSummary


@dataclass(frozen=True, slots=True)
class _SummaryPolicyDrivenExpander:
    """组合行动策略与完整回合解析，但只保留后继状态和精确概率。"""

    turn_resolver: BattleEventStandardMoveTurnResolver
    attacker_policy: ActionPolicy[BattleAction]
    defender_policy: ActionPolicy[BattleAction]

    def expand(self, state: BattleState) -> tuple[WeightedTransition[BattleState], ...]:
        """展开联合行动和战斗随机分支，并在当前节点立即丢弃事件路径。"""
        attacker_actions = self.turn_resolver.legal_actions(
            state,
            BattleSide.ATTACKER,
        )
        defender_actions = self.turn_resolver.legal_actions(
            state,
            BattleSide.DEFENDER,
        )
        attacker_distribution = self.attacker_policy.distribution_for(
            attacker_actions
        )
        defender_distribution = self.defender_policy.distribution_for(
            defender_actions
        )
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
                selection_probability = (
                    attacker_selection.probability
                    * defender_selection.probability
                )
                for transition in resolution.transitions:
                    transitions.append(
                        WeightedTransition(
                            probability=(
                                selection_probability * transition.probability
                            ),
                            state=transition.state,
                            event_summary=TransitionEventSummary.empty(),
                            source_key=None,
                        )
                    )
        return merge_summary_transitions(transitions)


@dataclass(slots=True)
class InferFixedBattleSummaryUseCase:
    """复用现有配置准备与精确求解，只省略探索图和代表路径成本。

    Args:
        inference_use_case: 已组合 repository、effect factory 和精确图求解器的既有用例。
    """

    inference_use_case: InferOneOnOneBattleUseCase

    def __post_init__(self) -> None:
        """校验委托对象是正式固定推演 application 用例。"""
        if not isinstance(self.inference_use_case, InferOneOnOneBattleUseCase):
            raise ValueError(
                "inference_use_case must be an InferOneOnOneBattleUseCase"
            )

    def execute(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedBattleSummaryResult:
        """执行一个固定配置对的精确胜负平摘要。

        Args:
            command: 双方一到四招、行动策略、规则和图预算均已冻结的固定推演命令。

        Returns:
            不包含 graph handle、代表路径和事件明细的精确全局摘要。

        Raises:
            BattleInferenceExecutionError: 配置未收敛为唯一行为、图被截断或求解失败时抛出。
        """
        attacker_loaded = self.inference_use_case._load(
            command.rules,
            command.attacker.pokemon_id,
        )
        defender_loaded = self.inference_use_case._load(
            command.rules,
            command.defender.pokemon_id,
        )
        self.inference_use_case._validate_item(
            command.attacker.item_identifier,
            attacker_loaded,
        )
        self.inference_use_case._validate_item(
            command.defender.item_identifier,
            defender_loaded,
        )
        configuration_space = self.inference_use_case._configuration_generator().execute(
            _core.GenerateConfigurationSpaceCommand(
                attacker=self.inference_use_case._fixed_space_command(
                    command.attacker,
                    command.rules.level,
                ),
                defender=self.inference_use_case._fixed_space_command(
                    command.defender,
                    command.rules.level,
                ),
                max_raw_configuration_pairs=1,
            ),
            attacker_profile=self.inference_use_case._configuration_profile(
                attacker_loaded.pokemon,
                command.rules,
            ),
            defender_profile=self.inference_use_case._configuration_profile(
                defender_loaded.pokemon,
                command.rules,
            ),
        )
        if len(configuration_space.equivalence_classes) != 1:
            raise BattleInferenceExecutionError(
                "fixed battle command must resolve to one behavior configuration"
            )
        return self._solve(
            command,
            configuration_space.equivalence_classes[0],
            configuration_space,
        )

    def _solve(
        self,
        command: InferFixedOneOnOneBattleCommand,
        equivalence_class: ConfigurationEquivalenceClass,
        configuration_space: ConfigurationSpace,
    ) -> FixedBattleSummaryResult:
        """构建轻量状态图并复用现有精确 solver 生成全局摘要。"""
        configuration = equivalence_class.representative
        effects = self.inference_use_case._effects(configuration)
        attacker_policy = _core._policy(command.attacker_policy)
        defender_policy = _core._policy(command.defender_policy)
        expander = _SummaryPolicyDrivenExpander(
            turn_resolver=BattleEventStandardMoveTurnResolver(effects=effects),
            attacker_policy=attacker_policy,
            defender_policy=defender_policy,
        )
        graph = SummaryStateGraphBuilder(
            expander=expander,
            limits=command.graph_limits,
        ).build(_core._initial_state(configuration, command.rules))
        solved = self.inference_use_case.solver.solve(graph, command.observer)
        if solved.status is not BattleGraphSolveStatus.SOLVED:
            diagnostics = "; ".join(solved.diagnostics) or solved.status.value
            raise BattleInferenceExecutionError(
                f"battle graph was not completely solved: {diagnostics}"
            )

        inference = _core._inference_result(
            rules=command.rules,
            graph=graph,
            solved=solved,
            effects=effects,
            attacker_policy=attacker_policy,
            defender_policy=defender_policy,
            configuration_space=configuration_space,
            equivalence_class=equivalence_class,
            fixed_weighting=True,
        )
        graph_statistics = _core._graph_summary(graph)
        return FixedBattleSummaryResult(
            summary=BattleInferenceSummary(
                configuration=self.inference_use_case._configuration_summary(
                    configuration
                ),
                inference=inference,
                graph_statistics=graph_statistics,
                representative_paths=(),
                completeness=BattleInferenceCompleteness(
                    graph_complete=graph.is_complete,
                    solver_status=solved.status.value,
                    truncation_reasons=graph_statistics.truncation_reasons,
                    diagnostics=solved.diagnostics,
                ),
            )
        )


def build_fixed_inference_command(
    *,
    rules: BattleInferenceRules,
    attacker: FixedBattleSideSelection,
    attacker_move_ids: tuple[int, ...],
    defender: FixedBattleSideSelection,
    defender_move_ids: tuple[int, ...],
    attacker_policy: _core.BattleActionPolicyKind,
    defender_policy: _core.BattleActionPolicyKind,
    graph_limits: StateGraphLimits,
) -> InferFixedOneOnOneBattleCommand:
    """把组合选择结果转换为现有固定推演命令。

    Args:
        rules: 双方共享的规则轴和等级。
        attacker: 攻击方固定配置。
        attacker_move_ids: 用户从组合列表选择的一到四招。
        defender: 防守方固定配置。
        defender_move_ids: 用户从组合列表选择的一到四招。
        attacker_policy: 攻击方行动策略假设。
        defender_policy: 防守方行动策略假设。
        graph_limits: 单配置状态图运行保护。

    Returns:
        可直接交给 ``InferFixedBattleSummaryUseCase`` 的规范化命令。
    """
    if attacker.level != defender.level or rules.level != attacker.level:
        raise ValueError("fixed battle requires one shared level in v1")
    return InferFixedOneOnOneBattleCommand(
        rules=rules,
        attacker=_core.PokemonInferenceSelection(
            pokemon_id=attacker.pokemon_id,
            move_ids=attacker_move_ids,
            ability_identifier=attacker.ability_identifier,
            item_identifier=attacker.item_identifier,
            stat_preset_key=attacker.stat_profile_id,
        ),
        defender=_core.PokemonInferenceSelection(
            pokemon_id=defender.pokemon_id,
            move_ids=defender_move_ids,
            ability_identifier=defender.ability_identifier,
            item_identifier=defender.item_identifier,
            stat_preset_key=defender.stat_profile_id,
        ),
        attacker_policy=attacker_policy,
        defender_policy=defender_policy,
        graph_limits=graph_limits,
    )


__all__ = [
    "EnumerateMoveSetCombinationsCommand",
    "EnumerateMoveSetCombinationsResult",
    "EnumerateMoveSetCombinationsUseCase",
    "FixedBattleSideSelection",
    "FixedBattleSummaryResult",
    "InferFixedBattleSummaryUseCase",
    "MoveSetOption",
    "MoveSetSideResult",
    "build_fixed_inference_command",
]
