"""导出 version-group-aware 候选池和严格机制准入 application 合同。"""

from pokeop.application.battle_candidate_pool.admission import (
    MechanismAdmissionFailure,
    StrictMechanismAdmissionRejected,
    ValidateFixedMechanismSelectionCommand,
    ValidateFixedMechanismSelectionUseCase,
    ValidatedFixedMechanismSelection,
)
from pokeop.application.battle_candidate_pool.listing import (
    BattleCandidatePoolNotFound,
    ListBattleCandidatePoolCommand,
    ListBattleCandidatePoolUseCase,
)
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

__all__ = [
    "BattleAbilityCandidate",
    "BattleCandidatePool",
    "BattleCandidatePoolNotFound",
    "BattleItemCandidate",
    "BattleMoveCandidate",
    "CandidateLegalityStatus",
    "ListBattleCandidatePoolCommand",
    "ListBattleCandidatePoolUseCase",
    "MechanismAdmission",
    "MechanismAdmissionFailure",
    "MechanismAdmissionKey",
    "MoveLearningLegality",
    "StrictMechanismAdmissionRejected",
    "ValidateFixedMechanismSelectionCommand",
    "ValidateFixedMechanismSelectionUseCase",
    "ValidatedFixedMechanismSelection",
]
