"""把 #83 固定机制准入适配为完整候选技能池准入。"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

from pokeop.application.battle_candidate_pool.admission import (
    StrictMechanismAdmissionRejected,
    ValidateFixedMechanismSelectionCommand,
    ValidateFixedMechanismSelectionUseCase,
)
from pokeop.application.configuration_space.one_on_one import OneOnOneMovePoolCommand
from pokeop.application.use_cases._battle_inference_jobs.contracts import (
    BattleInferenceAdmissionValidator,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


@dataclass(slots=True)
class StrictBattleInferenceAdmissionValidator(BattleInferenceAdmissionValidator):
    """复用 #83 固定选择准入用例验证最多十招的候选池。"""

    use_case: ValidateFixedMechanismSelectionUseCase

    def validate(self, command: OneOnOneMovePoolCommand) -> None:
        """分块验证双方候选池，任一机制不完整时拒绝整个任务。"""
        failures = []
        rules = BattleInferenceRules(
            ruleset_id=command.ruleset_id,
            version_group_id=command.version_group_id,
            level=command.attacker.fixed.level,
        )
        for selection in (command.attacker, command.defender):
            move_ids = iter(selection.candidate_move_ids)
            while chunk := tuple(islice(move_ids, 4)):
                try:
                    self.use_case.execute(
                        ValidateFixedMechanismSelectionCommand(
                            rules=rules,
                            pokemon_id=selection.fixed.pokemon_id,
                            move_ids=chunk,
                            ability_identifier=selection.fixed.ability_identifier,
                            item_identifier=selection.fixed.item_identifier,
                        )
                    )
                except StrictMechanismAdmissionRejected as error:
                    failures.extend(error.failures)
        if failures:
            raise StrictMechanismAdmissionRejected(tuple(dict.fromkeys(failures)))
