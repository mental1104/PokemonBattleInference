"""定义 version-group-aware 候选池与严格机制准入的稳定 application 合同。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pokeop.application.repositories.battle_inference import (
    BattleInferenceAbilityProfile,
    BattleInferenceItemProfile,
    BattleInferenceMoveProfile,
    MechanismSupportStatus,
)
from pokeop.domain.battle.effects.protocols import EffectSourceKind


def _normalized_text(value: object, field_name: str) -> str:
    """校验并返回不含首尾空白的非空文本。

    Args:
        value: 需要校验的字段值。
        field_name: 错误信息中使用的稳定字段名。

    Returns:
        已确认非空且无需额外 strip 的原字符串。

    Raises:
        ValueError: value 不是规范化非空字符串时抛出。
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a normalized non-empty string")
    return value


def _is_positive_integer(value: object) -> bool:
    """返回输入是否为排除 bool 的正整数。"""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


class CandidateLegalityStatus(str, Enum):
    """描述候选在目标 ruleset/version group 下的学习合法性。"""

    LEGAL = "legal"


@dataclass(frozen=True, slots=True)
class MechanismAdmissionKey:
    """唯一标识某个计算版本下的一项机制准入判断。

    Args:
        ruleset_id: 当前战斗规则集稳定标识。
        version_group_id: PokeAPI 招式学习和历史字段使用的主查询轴。
        source_kind: 机制来自招式、特性还是道具。
        mechanism_identifier: repository 或 factory 使用的稳定机制标识。
        calculation_revision: 当前精确推演计算语义的兼容版本。
    """

    ruleset_id: str
    version_group_id: int
    source_kind: EffectSourceKind
    mechanism_identifier: str
    calculation_revision: str

    def __post_init__(self) -> None:
        """校验准入键可以稳定参与缓存、日志和跨层传递。"""
        _normalized_text(self.ruleset_id, "ruleset_id")
        if not _is_positive_integer(self.version_group_id):
            raise ValueError("version_group_id must be a positive integer")
        if not isinstance(self.source_kind, EffectSourceKind):
            raise ValueError("source_kind must be an EffectSourceKind")
        _normalized_text(self.mechanism_identifier, "mechanism_identifier")
        _normalized_text(self.calculation_revision, "calculation_revision")


@dataclass(frozen=True, slots=True)
class MechanismAdmission:
    """保存合法候选在当前计算版本下能否进入精确推演的完整结论。

    ``PARTIAL`` 和 ``UNSUPPORTED`` 仍保留在候选池中，但不可选择。``NO_EFFECT``
    代表已经明确验证“不需要额外 effect”，因此与 ``SUPPORTED`` 一样可进入推演。

    Args:
        key: 绑定 ruleset、version group、机制标识和计算版本的稳定键。
        status: repository 与当前 effect factory 对账后的机制支持状态。
        reason: 对当前支持状态的可读解释。
        missing_mechanism_identifiers: 阻止精确推演的稳定机制标识集合。
    """

    key: MechanismAdmissionKey
    status: MechanismSupportStatus
    reason: str
    missing_mechanism_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """校验支持状态、禁用原因和缺失机制之间保持保守一致。"""
        if not isinstance(self.key, MechanismAdmissionKey):
            raise ValueError("key must be a MechanismAdmissionKey")
        if not isinstance(self.status, MechanismSupportStatus):
            raise ValueError("status must be a MechanismSupportStatus")
        _normalized_text(self.reason, "reason")
        normalized_missing = tuple(
            _normalized_text(identifier, "missing_mechanism_identifier")
            for identifier in self.missing_mechanism_identifiers
        )
        if len(normalized_missing) != len(set(normalized_missing)):
            raise ValueError("missing mechanism identifiers must be unique")
        if self.selectable and normalized_missing:
            raise ValueError("selectable mechanisms must not report missing identifiers")
        if not self.selectable and not normalized_missing:
            raise ValueError(
                "partial or unsupported mechanisms must report missing identifiers"
            )
        object.__setattr__(self, "missing_mechanism_identifiers", normalized_missing)

    @property
    def selectable(self) -> bool:
        """返回候选是否可直接进入当前计算版本的精确推演。"""
        return self.status in {
            MechanismSupportStatus.SUPPORTED,
            MechanismSupportStatus.NO_EFFECT,
        }

    @property
    def disabled_reason(self) -> str | None:
        """返回不可选择候选的禁用原因；可选择候选返回 None。"""
        return None if self.selectable else self.reason


@dataclass(frozen=True, slots=True)
class MoveLearningLegality:
    """说明一项招式为何属于目标 Pokémon 的合法学习池。

    Args:
        ruleset_id: 当前规则集稳定标识。
        version_group_id: 精确匹配 ``pokemon_moves`` 的 version group。
        pokemon_id: 当前 Pokémon 或 form 的稳定整数 ID。
        move_id: 已经按学习记录归并后的招式稳定整数 ID。
        status: 当前合同仅暴露 repository 已确认合法的候选。
        reason: 对合法性来源的可读说明。
    """

    ruleset_id: str
    version_group_id: int
    pokemon_id: int
    move_id: int
    status: CandidateLegalityStatus
    reason: str

    def __post_init__(self) -> None:
        """校验合法性投影使用完整且精确的查询轴。"""
        _normalized_text(self.ruleset_id, "ruleset_id")
        for field_name, value in (
            ("version_group_id", self.version_group_id),
            ("pokemon_id", self.pokemon_id),
            ("move_id", self.move_id),
        ):
            if not _is_positive_integer(value):
                raise ValueError(f"{field_name} must be a positive integer")
        if not isinstance(self.status, CandidateLegalityStatus):
            raise ValueError("status must be a CandidateLegalityStatus")
        _normalized_text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class BattleMoveCandidate:
    """组合完整招式资料、学习合法性和当前计算版本准入结论。

    Args:
        move: persistence 已完成历史还原的稳定 application 招式 projection。
        legality: 证明该招式属于目标 Pokémon/version group 学习池的记录。
        admission: 当前 calculation revision 下的结构化支持结论。
    """

    move: BattleInferenceMoveProfile
    legality: MoveLearningLegality
    admission: MechanismAdmission

    def __post_init__(self) -> None:
        """校验三个子对象引用同一个招式和机制来源。"""
        if not isinstance(self.move, BattleInferenceMoveProfile):
            raise ValueError("move must be a BattleInferenceMoveProfile")
        if not isinstance(self.legality, MoveLearningLegality):
            raise ValueError("legality must be a MoveLearningLegality")
        if self.legality.move_id != self.move.move_id:
            raise ValueError("legality move_id must match move profile")
        if not isinstance(self.admission, MechanismAdmission):
            raise ValueError("admission must be a MechanismAdmission")
        if self.admission.key.source_kind is not EffectSourceKind.MOVE:
            raise ValueError("move admission source_kind must be MOVE")

    @property
    def move_id(self) -> int:
        """返回候选查找和稳定排序使用的 PokeAPI move ID。"""
        return self.move.move_id

    @property
    def identifier(self) -> str:
        """返回跨语言稳定招式 identifier。"""
        return self.move.identifier


@dataclass(frozen=True, slots=True)
class BattleAbilityCandidate:
    """组合 version-aware 合法特性资料和当前计算版本准入结论。"""

    ability: BattleInferenceAbilityProfile
    admission: MechanismAdmission

    def __post_init__(self) -> None:
        """校验特性 profile 和准入来源类型。"""
        if not isinstance(self.ability, BattleInferenceAbilityProfile):
            raise ValueError("ability must be a BattleInferenceAbilityProfile")
        if not isinstance(self.admission, MechanismAdmission):
            raise ValueError("admission must be a MechanismAdmission")
        if self.admission.key.source_kind is not EffectSourceKind.ABILITY:
            raise ValueError("ability admission source_kind must be ABILITY")

    @property
    def identifier(self) -> str:
        """返回固定配置匹配使用的特性 identifier。"""
        return self.ability.identifier


@dataclass(frozen=True, slots=True)
class BattleItemCandidate:
    """组合受控道具资料和当前计算版本准入结论。"""

    item: BattleInferenceItemProfile
    admission: MechanismAdmission

    def __post_init__(self) -> None:
        """校验道具 profile 和准入来源类型。"""
        if not isinstance(self.item, BattleInferenceItemProfile):
            raise ValueError("item must be a BattleInferenceItemProfile")
        if not isinstance(self.admission, MechanismAdmission):
            raise ValueError("admission must be a MechanismAdmission")
        if self.admission.key.source_kind is not EffectSourceKind.ITEM:
            raise ValueError("item admission source_kind must be ITEM")

    @property
    def identifier(self) -> str:
        """返回固定配置匹配使用的道具 identifier。"""
        return self.item.identifier


@dataclass(frozen=True, slots=True)
class BattleCandidatePool:
    """返回给 application/API 的完整 version-aware 候选池。

    Args:
        ruleset_id: 当前稳定规则集标识。
        generation_id: 用于解释当前历史数据所属世代。
        version_group_id: 招式学习和历史字段还原使用的精确 version group。
        version_group_identifier: PokeAPI version group 稳定 identifier。
        calculation_revision: 当前候选准入对应的精确推演计算语义版本。
        pokemon_id: 当前 Pokémon 或 form 的稳定整数 ID。
        pokemon_identifier: Pokémon 或 form 的稳定 identifier。
        pokemon_display_name: 当前规则集语言下的展示名称。
        form_identifier: 默认或具体形态 identifier；无法识别时为 None。
        moves: 全部合法且按 move_id 去重排序的招式候选，包括禁用项。
        abilities: 当前 version group 下全部合法特性候选，包括禁用项。
        items: 当前受控道具边界，包括显式无道具和禁用项。
    """

    ruleset_id: str
    generation_id: int
    version_group_id: int
    version_group_identifier: str
    calculation_revision: str
    pokemon_id: int
    pokemon_identifier: str
    pokemon_display_name: str
    form_identifier: str | None
    moves: tuple[BattleMoveCandidate, ...]
    abilities: tuple[BattleAbilityCandidate, ...]
    items: tuple[BattleItemCandidate, ...]

    def __post_init__(self) -> None:
        """校验候选唯一性和全部准入记录共享同一计算轴。"""
        _normalized_text(self.ruleset_id, "ruleset_id")
        for field_name, value in (
            ("generation_id", self.generation_id),
            ("version_group_id", self.version_group_id),
            ("pokemon_id", self.pokemon_id),
        ):
            if not _is_positive_integer(value):
                raise ValueError(f"{field_name} must be a positive integer")
        _normalized_text(self.version_group_identifier, "version_group_identifier")
        _normalized_text(self.calculation_revision, "calculation_revision")
        _normalized_text(self.pokemon_identifier, "pokemon_identifier")
        _normalized_text(self.pokemon_display_name, "pokemon_display_name")
        if self.form_identifier is not None:
            _normalized_text(self.form_identifier, "form_identifier")
        if not self.moves:
            raise ValueError("candidate pool must contain at least one legal move")
        move_ids = tuple(candidate.move_id for candidate in self.moves)
        ability_ids = tuple(candidate.ability.ability_id for candidate in self.abilities)
        item_identifiers = tuple(candidate.identifier for candidate in self.items)
        if len(move_ids) != len(set(move_ids)):
            raise ValueError("move candidates must be unique by move_id")
        if len(ability_ids) != len(set(ability_ids)):
            raise ValueError("ability candidates must be unique by ability_id")
        if len(item_identifiers) != len(set(item_identifiers)):
            raise ValueError("item candidates must be unique by identifier")
        for admission in self._admissions():
            key = admission.key
            if (
                key.ruleset_id != self.ruleset_id
                or key.version_group_id != self.version_group_id
                or key.calculation_revision != self.calculation_revision
            ):
                raise ValueError("candidate admission key does not match pool context")

    def _admissions(self) -> tuple[MechanismAdmission, ...]:
        """返回招式、特性和道具候选的全部准入记录。"""
        return (
            tuple(candidate.admission for candidate in self.moves)
            + tuple(candidate.admission for candidate in self.abilities)
            + tuple(candidate.admission for candidate in self.items)
        )

    def move_by_id(self, move_id: int) -> BattleMoveCandidate | None:
        """按稳定 ID 查找一项合法招式候选。"""
        return next(
            (candidate for candidate in self.moves if candidate.move_id == move_id),
            None,
        )

    def ability_by_identifier(
        self,
        identifier: str,
    ) -> BattleAbilityCandidate | None:
        """按稳定 identifier 查找一项合法特性候选。"""
        return next(
            (candidate for candidate in self.abilities if candidate.identifier == identifier),
            None,
        )

    def item_by_identifier(self, identifier: str) -> BattleItemCandidate | None:
        """按稳定 identifier 查找一项受控道具候选。"""
        return next(
            (candidate for candidate in self.items if candidate.identifier == identifier),
            None,
        )


__all__ = [
    "BattleAbilityCandidate",
    "BattleCandidatePool",
    "BattleItemCandidate",
    "BattleMoveCandidate",
    "CandidateLegalityStatus",
    "MechanismAdmission",
    "MechanismAdmissionKey",
    "MoveLearningLegality",
]
