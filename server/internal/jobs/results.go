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

// resultColumns 与 resultRecord 的扫描顺序绑定；共享同一 owning 表别名 c，分页无需 N+1 查询。
const resultColumns = `c.attacker_win_numerator,c.attacker_win_denominator,c.defender_win_numerator,c.defender_win_denominator,c.draw_numerator,c.draw_denominator,c.expected_turns_kind,c.expected_turns_numerator,c.expected_turns_denominator,c.node_count,c.edge_count,c.budget_consumed,c.explanation_json,c.failure_code,c.diagnostic`

// resultRecord 暂存同一行的 nullable 数据；只有解析和 Normalize 成功才发布最终 Result。
type resultRecord struct {
	result                               Result
	an, ad, dn, dd, tn, td, kind, en, ed *string
}

// destinations 返回 record 拥有字段的有序扫描地址；仅在本次同步 Scan 生命周期借用。
func (record *resultRecord) destinations() []any {
	return []any{&record.an, &record.ad, &record.dn, &record.dd, &record.tn, &record.td, &record.kind, &record.en, &record.ed, &record.result.Nodes, &record.result.Edges, &record.result.Budget, &record.result.Explanation, &record.result.FailureCode, &record.result.Diagnostic}
}

// value 将 record 与同一行 status 组合成规范终态；pending/running 返回 nil，不伪造概率。
func (record *resultRecord) value(status Status) (*Result, error) {
	if !terminalCase(status) {
		return nil, nil
	}
	result := record.result
	result.Status = status
	var err error
	if result.AttackerWin, err = nullableFraction(record.an, record.ad); err != nil {
		return nil, err
	}
	if result.DefenderWin, err = nullableFraction(record.dn, record.dd); err != nil {
		return nil, err
	}
	if result.Draw, err = nullableFraction(record.tn, record.td); err != nil {
		return nil, err
	}
	if record.kind != nil {
		value, parseErr := nullableFraction(record.en, record.ed)
		if parseErr != nil {
			return nil, parseErr
		}
		result.ExpectedTurns = &ExpectedTurns{*record.kind, value}
	}
	// 旧 Python 成功记录允许任意非空 explanation 文本；读取保留原文，HTTP presenter 再把非对象 JSON 置空。
	// 新写入仍经严格 Normalize 检查 JSON，不能让兼容历史读取放宽写入契约。
	explanation := result.Explanation
	if status == Succeeded {
		result.Explanation = nil
	}
	normalized, err := result.Normalize()
	if err != nil {
		return nil, err
	}
	normalized.Explanation = explanation
	return &normalized, nil
}

// Result 读取 id/pair 的不可变最终摘要；ctx 取消 SQL，pending/running 返回 nil。
func (store *Store) Result(ctx context.Context, id, pair string) (*Result, error) {
	var record resultRecord
	var status Status
	destinations := append([]any{&status}, record.destinations()...)
	err := store.db.QueryRowContext(ctx, `SELECT c.status,`+resultColumns+` FROM poke_runtime.battle_inference_cases c WHERE c.job_id=$1 AND c.configuration_pair_id=$2`, id, pair).Scan(destinations...)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return record.value(status)
}
