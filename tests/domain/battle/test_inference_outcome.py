from __future__ import annotations

from pokeop.domain.battle.inference_outcome import (
    TerminalBattleOutcome,
    TerminalOutcome,
    TerminationReason,
)


def test_terminal_outcome_keeps_winner_and_termination_reason_separate():
    """同一个 KO 原因可对应任一方获胜，胜负语义不编码在自由字符串中。"""
    result = TerminalBattleOutcome(
        outcome=TerminalOutcome.ATTACKER_WIN,
        reason=TerminationReason.KNOCKOUT,
        turns=3,
    )

    assert result.outcome is TerminalOutcome.ATTACKER_WIN
    assert result.reason is TerminationReason.KNOCKOUT
    assert result.turns == 3


def test_cycle_and_repetition_termination_must_be_draws():
    """首版循环保护和重复状态停止不能被误报为任一方战胜。"""
    for reason in (TerminationReason.REPETITION, TerminationReason.CYCLE_GUARD):
        try:
            TerminalBattleOutcome(
                outcome=TerminalOutcome.DEFENDER_WIN,
                reason=reason,
                turns=100,
            )
        except ValueError as exc:
            assert "must produce a draw" in str(exc)
        else:
            raise AssertionError("expected cycle-like termination to require draw")
