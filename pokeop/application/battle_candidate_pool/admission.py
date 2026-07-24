"""在创建精确推演任务前校验固定招式、特性和道具机制。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.battle_candidate_pool.listing import (
    ListBattleCandidatePoolCommand,
    ListBattleCandidatePoolUseCase,
)
from pokeop.application.battle_candidate_pool.models import (
    BattleAbilityCandidate,
    BattleCandidatePool,
    BattleItemCandidate,
    BattleMoveCandidate,
    MechanismAdmissionKey,
)
from pokeop.application.repositories.battle_inference import (
    BattleInferenceRepository,
    MechanismSupportStatus,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
)
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.inference_rules import BattleInferenceRules


@dataclass(frozen=True, slots=True)
class ValidateFixedMechanismSelectionCommand:
    """声明一侧固定配置在任务创建前必须通过的机制选择。

    Args:
        rules: 当前精确推演使用的规则集和 version group。
        pokemon_id: 固定 Pokémon 或 form 的稳定整数 ID。
        move_ids: 固定配置选择的一到四个唯一招式 ID。
        ability_identifier: 固定特性 identifier。
        item_identifier: 固定道具 identifier；None 表示显式不携带道具。
    """

    rules: BattleInferenceRules
    pokemon_id: int
    move_ids: tuple[int, ...]
    ability_identifier: str
    item_identifier: str | None = None

    def __post_init__(self) -> None:
        """校验固定选择可以无歧义地匹配候选池。

        Raises:
            ValueError: 规则、Pokémon、招式集合、特性或道具标识不合法时抛出。
        """
        if not isinstance(self.rules, BattleInferenceRules):
            raise ValueError("rules must be a BattleInferenceRules")
        if (
            isinstance(self.pokemon_id, bool)
            or not isinstance(self.pokemon_id, int)
            or self.pokemon_id <= 0
        ):
            raise ValueError("pokemon_id must be a positive integer")
        normalized_move_ids = tuple(self.move_ids)
        if not 1 <= len(normalized_move_ids) <= 4:
            raise ValueError("move_ids must contain one to four moves")
        if any(
            isinstance(move_id, bool)
            or not isinstance(move_id, int)
            or move_id <= 0
            for move_id in normalized_move_ids
        ):
            raise ValueError("move_ids must contain positive integers")
        if len(normalized_move_ids) != len(set(normalized_move_ids)):
            raise ValueError("move_ids must be unique")
        if (
            not isinstance(self.ability_identifier, str)
            or not self.ability_identifier
            or self.ability_identifier != self.ability_identifier.strip()
        ):
            raise ValueError(
                "ability_identifier must be a normalized non-empty string"
            )
        if self.item_identifier is not None and (
            not isinstance(self.item_identifier, str)
            or not self.item_identifier
            or self.item_identifier != self.item_identifier.strip()
        ):
            raise ValueError(
                "item_identifier must be normalized and non-empty when provided"
            )
        object.__setattr__(self, "move_ids", normalized_move_ids)


@dataclass(frozen=True, slots=True)
class MechanismAdmissionFailure:
    """描述阻止固定配置进入精确推演的一项明确失败。

    Args:
        key: 绑定规则轴、来源、机制标识和计算版本的稳定准入键。
        requested_identifier: 调用方提交的招式 ID 文本、特性或道具 identifier。
        status: 已知候选的 PARTIAL/UNSUPPORTED 状态；非法候选固定为 UNSUPPORTED。
        reason: 可直接返回给 application/API 调用方的拒绝原因。
        missing_mechanism_identifiers: 当前计算版本缺失或无法确认的机制标识。
    """

    key: MechanismAdmissionKey
    requested_identifier: str
    status: MechanismSupportStatus
    reason: str
    missing_mechanism_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        """校验失败记录不会伪装成已支持机制。

        Raises:
            ValueError: 标识、状态、原因或缺失机制集合不满足严格拒绝合同时抛出。
        """
        if not isinstance(self.key, MechanismAdmissionKey):
            raise ValueError("key must be a MechanismAdmissionKey")
        if (
            not isinstance(self.requested_identifier, str)
            or not self.requested_identifier
            or self.requested_identifier != self.requested_identifier.strip()
        ):
            raise ValueError(
                "requested_identifier must be a normalized non-empty string"
            )
        if not isinstance(self.status, MechanismSupportStatus):
            raise ValueError("status must be a MechanismSupportStatus")
        if self.status in {
            MechanismSupportStatus.SUPPORTED,
            MechanismSupportStatus.NO_EFFECT,
        }:
            raise ValueError("admission failure cannot use a selectable status")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not self.missing_mechanism_identifiers:
            raise ValueError("admission failure must report missing mechanisms")
        if any(
            not isinstance(identifier, str)
            or not identifier
            or identifier != identifier.strip()
            for identifier in self.missing_mechanism_identifiers
        ):
            raise ValueError("missing mechanism identifiers must be normalized")
        if len(self.missing_mechanism_identifiers) != len(
            set(self.missing_mechanism_identifiers)
        ):
            raise ValueError("missing mechanism identifiers must be unique")


class StrictMechanismAdmissionRejected(ValueError):
    """表示固定配置包含非法、部分支持或暂不支持的机制选择。"""

    failures: tuple[MechanismAdmissionFailure, ...]

    def __init__(self, failures: tuple[MechanismAdmissionFailure, ...]) -> None:
        """保存全部失败并生成稳定、可诊断的异常文本。

        Args:
            failures: 本次固定选择中的全部准入失败，必须至少包含一项。

        Raises:
            ValueError: failures 为空或包含错误类型时抛出。
        """
        if not failures:
            raise ValueError("strict admission rejection requires failures")
        if any(not isinstance(failure, MechanismAdmissionFailure) for failure in failures):
            raise ValueError(
                "failures must contain only MechanismAdmissionFailure values"
            )
        self.failures = failures
        details = "; ".join(
            f"{failure.key.source_kind.value}:{failure.requested_identifier}:"
            f"{failure.status.value}:"
            f"missing={','.join(failure.missing_mechanism_identifiers)}"
            for failure in failures
        )
        super().__init__(f"strict mechanism admission rejected: {details}")


@dataclass(frozen=True, slots=True)
class ValidatedFixedMechanismSelection:
    """返回任务创建方可直接使用的已验证固定机制候选。

    Args:
        candidate_pool: 本次校验使用的完整可展示候选池。
        moves: 按命令顺序保留的一到四项已支持招式。
        ability: 已支持的固定特性。
        item: 已支持或明确 no-effect 的固定道具/无道具候选。
    """

    candidate_pool: BattleCandidatePool
    moves: tuple[BattleMoveCandidate, ...]
    ability: BattleAbilityCandidate
    item: BattleItemCandidate

    def __post_init__(self) -> None:
        """防止调用方手工构造包含禁用候选的“已验证”结果。

        Raises:
            ValueError: 候选数量越界或任一候选不可选择时抛出。
        """
        if not isinstance(self.candidate_pool, BattleCandidatePool):
            raise ValueError("candidate_pool must be a BattleCandidatePool")
        if any(not isinstance(candidate, BattleMoveCandidate) for candidate in self.moves):
            raise ValueError("moves must contain only BattleMoveCandidate values")
        if not isinstance(self.ability, BattleAbilityCandidate):
            raise ValueError("ability must be a BattleAbilityCandidate")
        if not isinstance(self.item, BattleItemCandidate):
            raise ValueError("item must be a BattleItemCandidate")
        if not 1 <= len(self.moves) <= 4:
            raise ValueError("validated selection must contain one to four moves")
        if any(not candidate.admission.selectable for candidate in self.moves):
            raise ValueError("validated moves must be selectable")
        if not self.ability.admission.selectable:
            raise ValueError("validated ability must be selectable")
        if not self.item.admission.selectable:
            raise ValueError("validated item must be selectable")


class ValidateFixedMechanismSelectionUseCase:
    """在创建 worker/状态图任务前执行固定配置严格准入。

    该用例先获取完整候选池，因此不可选择候选仍可由页面展示；随后一次性校验招式、
    特性和道具，收集全部失败后统一拒绝，避免任务启动后逐配置失败或静默丢失分母。

    Args:
        repository: 返回 version-aware 合法候选和最终 capability 状态的 repository。
        calculation_revision: 当前固定选择必须匹配的精确推演计算语义版本。
    """

    def __init__(
        self,
        repository: BattleInferenceRepository,
        calculation_revision: str = BATTLE_INFERENCE_CALCULATION_REVISION,
    ) -> None:
        """创建复用同一 repository 和 calculation revision 的候选池用例。

        Args:
            repository: application repository 端口，通常为 factory 对账后的装饰器。
            calculation_revision: 用于缓存失效和机制准入追踪的稳定版本。
        """
        self._candidate_pool_use_case = ListBattleCandidatePoolUseCase(
            repository,
            calculation_revision,
        )

    def execute(
        self,
        command: ValidateFixedMechanismSelectionCommand,
    ) -> ValidatedFixedMechanismSelection:
        """校验固定 moves、ability 和 item 均完整支持当前精确推演。

        Args:
            command: 任务提交方提供的一侧固定机制选择。

        Returns:
            包含完整候选池和已收窄候选对象的验证结果。

        Raises:
            StrictMechanismAdmissionRejected: 任一选择非法、PARTIAL 或 UNSUPPORTED 时抛出，
                并在 ``failures`` 中保留缺失机制标识和禁用原因。
        """
        pool = self._candidate_pool_use_case.execute(
            ListBattleCandidatePoolCommand(
                rules=command.rules,
                pokemon_id=command.pokemon_id,
            )
        )
        failures: list[MechanismAdmissionFailure] = []
        selected_moves: list[BattleMoveCandidate] = []

        for move_id in command.move_ids:
            move = pool.move_by_id(move_id)
            if move is None:
                failures.append(
                    self._missing_failure(
                        pool,
                        source_kind=EffectSourceKind.MOVE,
                        requested_identifier=str(move_id),
                        mechanism_identifier=f"move-id-{move_id}",
                        reason=(
                            f"move {move_id} is not legal for Pokemon {pool.pokemon_id} "
                            f"in version group {pool.version_group_id}"
                        ),
                    )
                )
                continue
            if not move.admission.selectable:
                failures.append(
                    self._candidate_failure(
                        requested_identifier=str(move_id),
                        candidate=move,
                    )
                )
                continue
            selected_moves.append(move)

        ability = pool.ability_by_identifier(command.ability_identifier)
        if ability is None:
            failures.append(
                self._missing_failure(
                    pool,
                    source_kind=EffectSourceKind.ABILITY,
                    requested_identifier=command.ability_identifier,
                    mechanism_identifier=command.ability_identifier,
                    reason=(
                        f"ability {command.ability_identifier!r} is not legal for "
                        f"Pokemon {pool.pokemon_id} in version group "
                        f"{pool.version_group_id}"
                    ),
                )
            )
        elif not ability.admission.selectable:
            failures.append(
                self._candidate_failure(
                    requested_identifier=command.ability_identifier,
                    candidate=ability,
                )
            )

        requested_item = command.item_identifier or "none"
        item = pool.item_by_identifier(requested_item)
        if item is None:
            failures.append(
                self._missing_failure(
                    pool,
                    source_kind=EffectSourceKind.ITEM,
                    requested_identifier=requested_item,
                    mechanism_identifier=requested_item,
                    reason=(
                        f"item {requested_item!r} is not available in the controlled "
                        f"boundary for version group {pool.version_group_id}"
                    ),
                )
            )
        elif not item.admission.selectable:
            failures.append(
                self._candidate_failure(
                    requested_identifier=requested_item,
                    candidate=item,
                )
            )

        if failures:
            # 全量收集后统一拒绝，让调用方一次修正全部固定机制，而不是反复提交任务。
            raise StrictMechanismAdmissionRejected(tuple(failures))
        if ability is None or item is None:
            raise AssertionError("validated candidates were not narrowed after admission")

        return ValidatedFixedMechanismSelection(
            candidate_pool=pool,
            moves=tuple(selected_moves),
            ability=ability,
            item=item,
        )

    @staticmethod
    def _candidate_failure(
        *,
        requested_identifier: str,
        candidate: BattleMoveCandidate
        | BattleAbilityCandidate
        | BattleItemCandidate,
    ) -> MechanismAdmissionFailure:
        """把候选自身的 PARTIAL/UNSUPPORTED 结论转换为提交失败。

        Args:
            requested_identifier: 调用方原始选择，用于错误定位。
            candidate: 已存在但当前不可进入精确推演的候选。

        Returns:
            保留候选准入键、禁用原因和缺失机制标识的失败记录。
        """
        admission = candidate.admission
        if admission.selectable:
            raise ValueError("selectable candidate cannot produce an admission failure")
        return MechanismAdmissionFailure(
            key=admission.key,
            requested_identifier=requested_identifier,
            status=admission.status,
            reason=admission.reason,
            missing_mechanism_identifiers=admission.missing_mechanism_identifiers,
        )

    @staticmethod
    def _missing_failure(
        pool: BattleCandidatePool,
        *,
        source_kind: EffectSourceKind,
        requested_identifier: str,
        mechanism_identifier: str,
        reason: str,
    ) -> MechanismAdmissionFailure:
        """为不属于合法候选池的固定选择创建显式 unsupported 失败。

        Args:
            pool: 提供精确规则轴和计算版本的候选池。
            source_kind: 缺失候选属于招式、特性还是道具。
            requested_identifier: 调用方原始选择。
            mechanism_identifier: 用于诊断和缓存键的规范化缺失机制标识。
            reason: 说明该选择为何不合法或不在受控边界。

        Returns:
            绑定同一规则轴且状态为 UNSUPPORTED 的失败记录。
        """
        return MechanismAdmissionFailure(
            key=MechanismAdmissionKey(
                ruleset_id=pool.ruleset_id,
                version_group_id=pool.version_group_id,
                source_kind=source_kind,
                mechanism_identifier=mechanism_identifier,
                calculation_revision=pool.calculation_revision,
            ),
            requested_identifier=requested_identifier,
            status=MechanismSupportStatus.UNSUPPORTED,
            reason=reason,
            missing_mechanism_identifiers=(mechanism_identifier,),
        )


__all__ = [
    "MechanismAdmissionFailure",
    "StrictMechanismAdmissionRejected",
    "ValidateFixedMechanismSelectionCommand",
    "ValidateFixedMechanismSelectionUseCase",
    "ValidatedFixedMechanismSelection",
]
