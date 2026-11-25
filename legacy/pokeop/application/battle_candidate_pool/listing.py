"""把 version-aware repository projection 转换为可展示候选池。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.battle_candidate_pool.models import (
    BattleAbilityCandidate,
    BattleCandidatePool,
    BattleItemCandidate,
    BattleMoveCandidate,
    CandidateLegalityStatus,
    MechanismAdmission,
    MechanismAdmissionKey,
    MoveLearningLegality,
)
from pokeop.application.repositories.battle_inference import (
    BattleInferenceAbilityProfile,
    BattleInferenceItemProfile,
    BattleInferenceMoveProfile,
    BattleInferenceRepository,
    MechanismCapability,
    MechanismSupportStatus,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
)
from pokeop.application.use_cases.load_battle_inference_profile import (
    BattleInferenceProfileNotFound,
    LoadBattleInferenceProfileCommand,
    LoadBattleInferenceProfileUseCase,
)
from pokeop.domain.battle.effects.factories import BattleEffectAbstractFactory
from pokeop.domain.battle.effects.protocols import (
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


class BattleCandidatePoolNotFound(LookupError):
    """表示目标规则轴或 Pokémon 没有可供展示和准入判断的完整候选池。"""


@dataclass(frozen=True, slots=True)
class ListBattleCandidatePoolCommand:
    """请求 application 构建一只 Pokémon 的完整候选池。

    Args:
        rules: 已校验的规则集和 version group 主轴。
        pokemon_id: 需要列出候选的 Pokémon 或 form 稳定整数 ID。
    """

    rules: BattleInferenceRules
    pokemon_id: int

    def __post_init__(self) -> None:
        """校验候选池请求只携带显式规则对象和正整数 Pokémon ID。

        Raises:
            ValueError: rules 类型错误或 pokemon_id 不是正整数时抛出。
        """
        if not isinstance(self.rules, BattleInferenceRules):
            raise ValueError("rules must be a BattleInferenceRules")
        if (
            isinstance(self.pokemon_id, bool)
            or not isinstance(self.pokemon_id, int)
            or self.pokemon_id <= 0
        ):
            raise ValueError("pokemon_id must be a positive integer")


class ListBattleCandidatePoolUseCase:
    """编排 version-aware 资料读取并生成全量可展示候选池。

    persistence repository 负责返回目标 version group 下的合法候选和历史字段；当前具体
    effect factory 的 ``EffectCoverage`` descriptor 负责声明真实机制覆盖。用例会把二者
    组合成严格准入结果，即使 factory 为了兼容旧旅程返回可执行的中性占位，只要 descriptor
    仍含 unsupported 子能力，该候选也会降级为 ``PARTIAL`` 并禁止进入精确推演。

    Args:
        repository: 返回 version-aware 合法候选的 application repository 端口。
        effect_factory: 当前 calculation revision 实际使用的显式 effect registry/factory。
        calculation_revision: 当前候选准入绑定的精确推演计算语义版本。
    """

    def __init__(
        self,
        repository: BattleInferenceRepository,
        effect_factory: BattleEffectAbstractFactory,
        calculation_revision: str = BATTLE_INFERENCE_CALCULATION_REVISION,
    ) -> None:
        """保存读取端口、显式机制 descriptor 来源和稳定计算版本。

        Args:
            repository: 可由 PostgreSQL 实现、composition 装饰器或测试 fake 提供的读取端口。
            effect_factory: 提供招式、特性和道具结构化 ``EffectCoverage`` 的当前工厂。
            calculation_revision: 非空且不含首尾空白的计算兼容版本。

        Raises:
            ValueError: calculation_revision 为空或未规范化时抛出。
        """
        if (
            not isinstance(calculation_revision, str)
            or not calculation_revision
            or calculation_revision != calculation_revision.strip()
        ):
            raise ValueError(
                "calculation_revision must be a normalized non-empty string"
            )
        self._repository = repository
        self._effect_factory = effect_factory
        self._calculation_revision = calculation_revision

    def execute(self, command: ListBattleCandidatePoolCommand) -> BattleCandidatePool:
        """加载并投影一只 Pokémon 的全量合法候选。

        ``PARTIAL`` 和 ``UNSUPPORTED`` 候选不会被删除，而是通过 ``admission`` 明确
        标记为不可选择。相同 move_id 已由 repository profile 不变量去重，本层仍按
        move_id 排序，确保 API、缓存和测试得到稳定顺序。

        Args:
            command: 目标规则轴和 Pokémon ID。

        Returns:
            同时包含招式、特性和受控道具候选的稳定 application 投影。

        Raises:
            BattleCandidatePoolNotFound: 规则轴、Pokémon 或受控道具边界不存在时抛出。
            ValueError: repository/factory 返回与请求不一致的规则轴或来源类型时抛出。
        """
        if self._effect_factory.ruleset_id != command.rules.ruleset_id:
            raise ValueError("effect factory ruleset does not match candidate command")
        try:
            loaded = LoadBattleInferenceProfileUseCase(self._repository).execute(
                LoadBattleInferenceProfileCommand(
                    rules=command.rules,
                    pokemon_id=command.pokemon_id,
                )
            )
        except BattleInferenceProfileNotFound as exc:
            raise BattleCandidatePoolNotFound(str(exc)) from exc

        if (
            loaded.ruleset.ruleset_id != command.rules.ruleset_id
            or loaded.ruleset.version_group_id != command.rules.version_group_id
        ):
            # fake 或错误 repository 不能通过返回其他版本数据绕过精确 version group 主轴。
            raise ValueError("repository ruleset context does not match candidate command")
        if loaded.pokemon.pokemon_id != command.pokemon_id:
            raise ValueError("repository pokemon profile does not match candidate command")

        pokemon = loaded.pokemon
        return BattleCandidatePool(
            ruleset_id=loaded.ruleset.ruleset_id,
            generation_id=loaded.ruleset.generation_id,
            version_group_id=loaded.ruleset.version_group_id,
            version_group_identifier=loaded.ruleset.version_group_identifier,
            calculation_revision=self._calculation_revision,
            pokemon_id=pokemon.pokemon_id,
            pokemon_identifier=pokemon.identifier,
            pokemon_display_name=pokemon.display_name,
            form_identifier=pokemon.form_identifier,
            moves=tuple(
                self._move_candidate(
                    move,
                    ruleset_id=loaded.ruleset.ruleset_id,
                    version_group_id=loaded.ruleset.version_group_id,
                    pokemon_id=pokemon.pokemon_id,
                )
                for move in sorted(pokemon.moves, key=lambda candidate: candidate.move_id)
            ),
            abilities=tuple(
                self._ability_candidate(
                    ability,
                    ruleset_id=loaded.ruleset.ruleset_id,
                    version_group_id=loaded.ruleset.version_group_id,
                )
                for ability in sorted(
                    pokemon.abilities,
                    key=lambda candidate: (candidate.slot, candidate.ability_id),
                )
            ),
            items=tuple(
                self._item_candidate(
                    item,
                    ruleset_id=loaded.ruleset.ruleset_id,
                    version_group_id=loaded.ruleset.version_group_id,
                )
                for item in loaded.item_candidates
            ),
        )

    def _admission(
        self,
        capability: MechanismCapability,
        coverage: EffectCoverage,
        *,
        ruleset_id: str,
        version_group_id: int,
        expected_source_kind: EffectSourceKind,
        base_executable: bool,
        allow_no_effect: bool,
    ) -> MechanismAdmission:
        """组合 persistence 合法性判断与当前 factory 的显式机制 descriptor。

        Args:
            capability: repository 对候选基础字段和整体机制的保守判断。
            coverage: 当前实际 effect 产品返回的结构化覆盖记录。
            ruleset_id: 当前候选池规则集标识。
            version_group_id: 当前候选池 version group。
            expected_source_kind: 调用方候选类型要求的机制来源。
            base_executable: 不依赖附加 effect 的基础字段是否足以执行。
            allow_no_effect: 当前候选是否明确允许 ``NO_EFFECT`` 作为完整语义。

        Returns:
            可直接用于页面禁用和任务提交校验的结构化准入记录。

        Raises:
            ValueError: capability/coverage 的规则集或来源类型与候选不一致时抛出。
        """
        if capability.source_kind is not expected_source_kind:
            raise ValueError(
                "capability source_kind does not match candidate projection"
            )
        if coverage.ruleset_id != ruleset_id:
            raise ValueError("effect coverage belongs to a different ruleset")
        if coverage.source_kind is not expected_source_kind:
            raise ValueError("effect coverage source_kind does not match candidate")

        missing_identifiers = self._coverage_missing_identifiers(coverage)
        status: MechanismSupportStatus
        if not base_executable:
            status = MechanismSupportStatus.UNSUPPORTED
        elif missing_identifiers:
            # overall SUPPORTED 但仍暴露 unsupported 子能力的中性占位也不能进入精确推演。
            status = MechanismSupportStatus.PARTIAL
        elif coverage.status is EffectCoverageStatus.SUPPORTED:
            status = MechanismSupportStatus.SUPPORTED
        elif coverage.status is EffectCoverageStatus.NO_EFFECT and allow_no_effect:
            status = MechanismSupportStatus.NO_EFFECT
        elif coverage.status is EffectCoverageStatus.PARTIAL:
            status = MechanismSupportStatus.PARTIAL
        else:
            status = MechanismSupportStatus.UNSUPPORTED

        if status in {
            MechanismSupportStatus.SUPPORTED,
            MechanismSupportStatus.NO_EFFECT,
        }:
            missing_identifiers = ()
        elif not missing_identifiers:
            fallback_identifier = (
                coverage.identifier
                if coverage.identifier != "none"
                else capability.identifier
            )
            missing_identifiers = (fallback_identifier,)

        return MechanismAdmission(
            key=MechanismAdmissionKey(
                ruleset_id=ruleset_id,
                version_group_id=version_group_id,
                source_kind=capability.source_kind,
                mechanism_identifier=capability.identifier,
                calculation_revision=self._calculation_revision,
            ),
            status=status,
            reason=(
                f"{capability.reason} Current factory coverage: {coverage.reason}"
            ),
            missing_mechanism_identifiers=missing_identifiers,
        )

    @staticmethod
    def _coverage_missing_identifiers(
        coverage: EffectCoverage,
    ) -> tuple[str, ...]:
        """归并 factory descriptor 中未支持的 aspect 与子能力标识。

        Args:
            coverage: 当前具体 effect 产品返回的结构化覆盖记录。

        Returns:
            保持 descriptor 顺序并去重的缺失机制标识元组。
        """
        ordered = coverage.unsupported_aspects + tuple(
            capability.identifier for capability in coverage.unsupported_capabilities
        )
        return tuple(dict.fromkeys(ordered))

    def _move_candidate(
        self,
        move: BattleInferenceMoveProfile,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleMoveCandidate:
        """把完整招式 profile 转换为可展示且可严格准入的候选。

        Args:
            move: persistence 已完成历史还原的招式 application projection。
            ruleset_id: 当前规则集稳定标识。
            version_group_id: 学习合法性与历史字段使用的 version group。
            pokemon_id: 当前 Pokémon 或 form ID。

        Returns:
            保留全部战斗字段、合法性和禁用原因的稳定招式候选。
        """
        coverage = self._effect_factory.create_move_effect(
            move.effect_identifier
        ).coverage
        is_damaging = move.category.value != "status"
        return BattleMoveCandidate(
            move=move,
            legality=MoveLearningLegality(
                ruleset_id=ruleset_id,
                version_group_id=version_group_id,
                pokemon_id=pokemon_id,
                move_id=move.move_id,
                status=CandidateLegalityStatus.LEGAL,
                reason=(
                    "repository 已在该 Pokémon 和精确 version group 下解析到至少一条 "
                    "pokemon_moves 学习记录，并按 move_id 归并重复学习方式。"
                ),
            ),
            admission=self._admission(
                move.capability,
                coverage,
                ruleset_id=ruleset_id,
                version_group_id=version_group_id,
                expected_source_kind=EffectSourceKind.MOVE,
                base_executable=not is_damaging or move.power is not None,
                allow_no_effect=is_damaging and move.effect_identifier is None,
            ),
        )

    def _ability_candidate(
        self,
        ability: BattleInferenceAbilityProfile,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleAbilityCandidate:
        """把 version-aware 合法特性转换为可展示准入候选。"""
        coverage = self._effect_factory.create_ability_effect(
            ability.effect_identifier
        ).coverage
        return BattleAbilityCandidate(
            ability=ability,
            admission=self._admission(
                ability.capability,
                coverage,
                ruleset_id=ruleset_id,
                version_group_id=version_group_id,
                expected_source_kind=EffectSourceKind.ABILITY,
                base_executable=True,
                allow_no_effect=False,
            ),
        )

    def _item_candidate(
        self,
        item: BattleInferenceItemProfile,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleItemCandidate:
        """把受控道具或显式无道具 projection 转换为准入候选。"""
        coverage = self._effect_factory.create_item_effect(
            item.effect_identifier
        ).coverage
        return BattleItemCandidate(
            item=item,
            admission=self._admission(
                item.capability,
                coverage,
                ruleset_id=ruleset_id,
                version_group_id=version_group_id,
                expected_source_kind=EffectSourceKind.ITEM,
                base_executable=True,
                allow_no_effect=item.effect_identifier is None,
            ),
        )


__all__ = [
    "BattleCandidatePoolNotFound",
    "ListBattleCandidatePoolCommand",
    "ListBattleCandidatePoolUseCase",
]
