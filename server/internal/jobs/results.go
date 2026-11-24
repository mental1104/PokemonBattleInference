package jobs

import (
	"context"
	"database/sql"
	"errors"
)

// nullableFraction 验证数据库完整的成对 nullable 字段，拒绝只存在一个分数分量的损坏记录。
func nullableFraction(numerator, denominator *string) (*Fraction, error) {
	if numerator == nil && denominator == nil {
		return nil, nil
	}
	if numerator == nil || denominator == nil {
		return nil, errors.New("incomplete persisted fraction")
	}
	return &Fraction{*numerator, *denominator}, nil
}

// Result 读取 pair 的不可变最终摘要；pending/running 返回 nil，不伪造概率。
func (store *Store) Result(ctx context.Context, id, pair string) (*Result, error) {
	var result Result
	var an, ad, dn, dd, tn, td, kind, en, ed *string
	err := store.db.QueryRowContext(ctx, `SELECT status,attacker_win_numerator,attacker_win_denominator,defender_win_numerator,defender_win_denominator,draw_numerator,draw_denominator,expected_turns_kind,expected_turns_numerator,expected_turns_denominator,node_count,edge_count,budget_consumed,explanation_json,failure_code,diagnostic FROM poke_runtime.battle_inference_cases WHERE job_id=$1 AND configuration_pair_id=$2`, id, pair).Scan(&result.Status, &an, &ad, &dn, &dd, &tn, &td, &kind, &en, &ed, &result.Nodes, &result.Edges, &result.Budget, &result.Explanation, &result.FailureCode, &result.Diagnostic)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if !terminalCase(result.Status) {
		return nil, nil
	}
	if result.AttackerWin, err = nullableFraction(an, ad); err != nil {
		return nil, err
	}
	if result.DefenderWin, err = nullableFraction(dn, dd); err != nil {
		return nil, err
	}
	if result.Draw, err = nullableFraction(tn, td); err != nil {
		return nil, err
	}
	if kind != nil {
		value, parseErr := nullableFraction(en, ed)
		if parseErr != nil {
			return nil, parseErr
		}
		result.ExpectedTurns = &ExpectedTurns{*kind, value}
	}
	normalized, err := result.Normalize()
	if err != nil {
		return nil, err
	}
	return &normalized, nil
}
