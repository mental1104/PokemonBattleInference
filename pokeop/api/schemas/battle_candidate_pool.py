"""定义 version-group-aware 战斗候选池 HTTP 投影。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pokeop.application.battle_candidate_pool.models import BattleCandidatePool


class _StrictModel(BaseModel):
    """统一拒绝公开合同之外的额外字段。"""

    model_config = ConfigDict(extra="forbid")


class CandidateMechanismAdmissionResponse(_StrictModel):
    """返回候选机制是否可以进入当前精确推演。"""

    status: Literal["supported", "partial", "no_effect", "unsupported"]
    selectable: bool
    reason: str
    disabled_reason: str | None
    missing_mechanism_identifiers: list[str]


class CandidateMoveResponse(_StrictModel):
    """返回一条合法可学习招式及其当前计算版本准入结论。"""

    move_id: int
    identifier: str
    display_name: str
    type_identifier: str
    type_name: str
    damage_class: Literal["physical", "special", "status"]
    power: int | None
    admission: CandidateMechanismAdmissionResponse


class BattleCandidatePoolResponse(_StrictModel):
    """返回配置页消费的一侧真实候选招式池。"""

    pokemon_id: int
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    moves: list[CandidateMoveResponse]


def battle_candidate_pool_response(
    pool: BattleCandidatePool,
) -> BattleCandidatePoolResponse:
    """把 application 候选池转换为稳定且紧凑的 HTTP DTO。"""
    return BattleCandidatePoolResponse(
        pokemon_id=pool.pokemon_id,
        ruleset_id=pool.ruleset_id,
        version_group_id=pool.version_group_id,
        calculation_revision=pool.calculation_revision,
        moves=[
            CandidateMoveResponse(
                move_id=candidate.move.move_id,
                identifier=candidate.move.identifier,
                display_name=candidate.move.display_name,
                type_identifier=candidate.move.type.identifier,
                type_name=candidate.move.type.display_name,
                damage_class=candidate.move.category.value,
                power=candidate.move.power,
                admission=CandidateMechanismAdmissionResponse(
                    status=candidate.admission.status.value,
                    selectable=candidate.admission.selectable,
                    reason=candidate.admission.reason,
                    disabled_reason=candidate.admission.disabled_reason,
                    missing_mechanism_identifiers=list(
                        candidate.admission.missing_mechanism_identifiers
                    ),
                ),
            )
            for candidate in pool.moves
        ],
    )


__all__ = ["BattleCandidatePoolResponse", "battle_candidate_pool_response"]
