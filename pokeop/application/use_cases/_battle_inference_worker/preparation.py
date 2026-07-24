"""在父 coordinator 中准备不含数据库连接的单配置输入。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.configuration_space import (
    BattleConfiguration,
    GenerateConfigurationSpaceCommand,
)
from pokeop.application.configuration_space.one_on_one.model_base import (
    OneOnOneActionPolicy,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseSnapshot,
    BattleInferenceJobSnapshot,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases._battle_inference_worker.contracts import (
    PreparedBattleInferenceCase,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
    decode_one_on_one_configuration_id,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
    PokemonInferenceSelection,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules


@dataclass(slots=True)
class RepositoryBackedBattleInferenceCasePreparer:
    """复用固定 1v1 配置准备步骤，且只在父进程读取数据库。"""

    inference_use_case: InferOneOnOneBattleUseCase

    def prepare(
        self,
        job: BattleInferenceJobSnapshot,
        case: BattleInferenceCaseSnapshot,
        execution_spec: BattleInferenceExecutionSpec,
    ) -> PreparedBattleInferenceCase:
        """还原 canonical 配置并生成唯一行为配置。"""
        normalized = decode_one_on_one_configuration_id(
            case.definition.configuration_pair_id
        )
        if normalized.attacker.form_id is not None or normalized.defender.form_id is not None:
            raise ValueError("v1 worker does not yet support explicit form_id")
        if (
            normalized.ruleset_id != job.ruleset_id
            or normalized.version_group_id != job.version_group_id
            or normalized.calculation_revision != job.calculation_revision
        ):
            raise ValueError("configuration identity does not match the claimed job")
        rules = BattleInferenceRules(
            ruleset_id=job.ruleset_id,
            version_group_id=job.version_group_id,
            level=normalized.attacker.level,
            max_turns=execution_spec.max_turns,
        )
        command = InferFixedOneOnOneBattleCommand(
            rules=rules,
            attacker=_selection(normalized.attacker, normalized.attacker_move_ids),
            defender=_selection(normalized.defender, normalized.defender_move_ids),
            attacker_policy=battle_action_policy_kind(execution_spec.attacker_policy),
            defender_policy=battle_action_policy_kind(execution_spec.defender_policy),
            observer=BattleSide.ATTACKER,
            graph_limits=StateGraphLimits(
                max_nodes=execution_spec.max_nodes_per_pair,
                max_edges=execution_spec.max_edges_per_pair,
                max_turns=execution_spec.max_turns,
            ),
        )
        return PreparedBattleInferenceCase(
            configuration_pair_id=case.definition.configuration_pair_id,
            attacker_configuration_id=case.definition.attacker_configuration_id,
            defender_configuration_id=case.definition.defender_configuration_id,
            configuration=self._prepare_configuration(command),
            rules=rules,
            attacker_policy=command.attacker_policy,
            defender_policy=command.defender_policy,
            graph_limits=command.graph_limits,
        )

    def _prepare_configuration(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> BattleConfiguration:
        """复用既有固定推演准备步骤，但不在父进程构建状态图。"""
        attacker_loaded = self.inference_use_case._load(  # noqa: SLF001
            command.rules, command.attacker.pokemon_id
        )
        defender_loaded = self.inference_use_case._load(  # noqa: SLF001
            command.rules, command.defender.pokemon_id
        )
        self.inference_use_case._validate_item(  # noqa: SLF001
            command.attacker.item_identifier, attacker_loaded
        )
        self.inference_use_case._validate_item(  # noqa: SLF001
            command.defender.item_identifier, defender_loaded
        )
        generator = self.inference_use_case._configuration_generator()  # noqa: SLF001
        configuration_space = generator.execute(
            self._space_command(command),
            attacker_profile=self.inference_use_case._configuration_profile(  # noqa: SLF001
                attacker_loaded.pokemon, command.rules
            ),
            defender_profile=self.inference_use_case._configuration_profile(  # noqa: SLF001
                defender_loaded.pokemon, command.rules
            ),
        )
        if len(configuration_space.equivalence_classes) != 1:
            raise ValueError("fixed worker configuration must resolve to one behavior class")
        return configuration_space.equivalence_classes[0].representative

    def _space_command(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> GenerateConfigurationSpaceCommand:
        """构造双方各只有一个结果的配置空间命令。"""
        return GenerateConfigurationSpaceCommand(
            attacker=self.inference_use_case._fixed_space_command(  # noqa: SLF001
                command.attacker, command.rules.level
            ),
            defender=self.inference_use_case._fixed_space_command(  # noqa: SLF001
                command.defender, command.rules.level
            ),
            max_raw_configuration_pairs=1,
        )


def _selection(fixed, move_ids: tuple[int, ...]) -> PokemonInferenceSelection:
    """把公开固定配置适配为现有固定推演选择。"""
    return PokemonInferenceSelection(
        pokemon_id=fixed.pokemon_id,
        move_ids=move_ids,
        ability_identifier=fixed.ability_identifier,
        item_identifier=fixed.item_identifier,
        stat_preset_key=fixed.stat_profile_id,
    )


def battle_action_policy_kind(value: str) -> BattleActionPolicyKind:
    """把 #82 公共策略标识转换为状态图执行器枚举。"""
    if value == OneOnOneActionPolicy.FIRST_LEGAL.value:
        return BattleActionPolicyKind.FIRST_LEGAL
    if value == OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION.value:
        return BattleActionPolicyKind.UNIFORM_RANDOM
    raise ValueError(f"unsupported battle action policy: {value!r}")
