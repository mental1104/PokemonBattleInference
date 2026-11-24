package jobs

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"
)

const caseFields = `c.job_id,c.sequence_no,c.configuration_pair_id,c.attacker_configuration_id,c.defender_configuration_id,to_json(c.attacker_move_ids),to_json(c.defender_move_ids),c.status,c.attempt_count,c.lease_owner,c.lease_expires_at,c.heartbeat_at,c.progress_phase,c.observed_node_count,c.observed_edge_count,c.expanded_node_count,c.frontier_count,c.action_pair_completed_count,c.action_pair_total_count,c.updated_at`
const caseSelect = `SELECT ` + caseFields + ` FROM poke_runtime.battle_inference_cases c`

// scanner 是 Row 和 Rows 的共同读取端口，返回值不保留驱动缓冲区。
type scanner interface{ Scan(...any) error }

// scanCase 读取单行并恢复租约及招式 ID；最终概率通过独立结果接口读取。
func scanCase(row scanner) (Case, error) {
	return scanCaseResult(row, false)
}

// scanCaseResult 在一次 Scan 读取状态与可选终态列，防止分页期间混入其他时间点的结果。
// row 借用驱动行；withResult=true 时调用方必须在 caseSelect 后追加 resultColumns。
func scanCaseResult(row scanner, withResult bool) (Case, error) {
	var item Case
	var attacker, defender []byte
	var owner, phase *string
	var expires, heartbeat *time.Time
	destinations := []any{&item.JobID, &item.Sequence, &item.Definition.PairID, &item.Definition.AttackerID, &item.Definition.DefenderID, &attacker, &defender, &item.Status, &item.Attempts, &owner, &expires, &heartbeat, &phase, &item.Progress.ObservedNodes, &item.Progress.ObservedEdges, &item.Progress.ExpandedNodes, &item.Progress.Frontier, &item.Progress.ActionPairsCompleted, &item.Progress.ActionPairsTotal, &item.UpdatedAt}
	var record resultRecord
	if withResult {
		destinations = append(destinations, record.destinations()...)
	}
	err := row.Scan(destinations...)
	if errors.Is(err, sql.ErrNoRows) {
		return item, ErrNotFound
	}
	if err != nil {
		return item, err
	}
	if err = json.Unmarshal(attacker, &item.Definition.AttackerMoves); err != nil {
		return item, err
	}
	if err = json.Unmarshal(defender, &item.Definition.DefenderMoves); err != nil {
		return item, err
	}
	if phase != nil {
		item.Progress.Phase = *phase
	}
	if owner != nil && expires != nil && heartbeat != nil {
		item.Lease = &Lease{*owner, *expires, *heartbeat}
	}
	if withResult {
		if item.Result, err = record.value(item.Status); err != nil {
			return item, err
		}
	}
	return item, nil
}

// ClaimCases 原子领取 pending 或租约已过期用例，恢复不重复增加 running 桶。
// revision 必须匹配冻结值；取消请求后禁止继续领取。limit 范围沿用 1..1000。
func (store *Store) ClaimCases(ctx context.Context, id, owner, revision string, now time.Time, duration time.Duration, limit int) ([]Case, error) {
	expires, err := validateLease(owner, now, duration)
	if err != nil {
		return nil, err
	}
	if limit < 1 || limit > 1000 {
		return nil, errors.New("invalid case claim limit")
	}
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	job, err := loadJob(ctx, tx, id, true)
	if err != nil {
		return nil, err
	}
	if job.Revision != revision {
		return nil, ErrRevision
	}
	if job.Status != Preparing && job.Status != Running {
		return nil, ErrTransition
	}
	rows, err := tx.QueryContext(ctx, caseSelect+` WHERE c.job_id=$1 AND (c.status='pending' OR (c.status='running' AND (c.lease_expires_at IS NULL OR c.lease_expires_at<=$2))) ORDER BY c.sequence_no LIMIT $3 FOR UPDATE OF c SKIP LOCKED`, id, now, limit)
	if err != nil {
		return nil, err
	}
	result := []Case{}
	for rows.Next() {
		item, scanErr := scanCase(rows)
		if scanErr != nil {
			rows.Close()
			return nil, scanErr
		}
		result = append(result, item)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	newlyRunning := 0
	for index := range result {
		item := &result[index]
		recovered := item.Status == Running
		if !recovered {
			newlyRunning++
		}
		_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_cases SET status='running',attempt_count=attempt_count+1,lease_owner=$3,heartbeat_at=$4,lease_expires_at=$5,started_at=COALESCE(started_at,$4),updated_at=$4,last_failure_code=CASE WHEN $6 THEN 'worker_crash' ELSE last_failure_code END,last_failure_diagnostic=CASE WHEN $6 THEN 'worker lease expired before reclaim' ELSE last_failure_diagnostic END WHERE job_id=$1 AND configuration_pair_id=$2`, id, item.Definition.PairID, owner, now, expires, recovered)
		if err != nil {
			return nil, err
		}
		item.Status = Running
		item.Attempts++
		item.Lease = &Lease{owner, expires, now}
		item.UpdatedAt = now
	}
	if len(result) > 0 {
		_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_job_progress SET pending_count=pending_count-$2,running_count=running_count+$2,updated_at=$3 WHERE job_id=$1`, id, newlyRunning, now)
		if err != nil {
			return nil, err
		}
		_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET status='running',started_at=COALESCE(started_at,$2),updated_at=$2 WHERE job_id=$1`, id, now)
		if err != nil {
			return nil, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return result, nil
}

// HeartbeatCases 在同一事务续租 pairs；任一对象丢失或过期都会回滚整批。
func (store *Store) HeartbeatCases(ctx context.Context, id, owner string, pairs []string, now time.Time, duration time.Duration) error {
	expires, err := validateLease(owner, now, duration)
	if err != nil {
		return err
	}
	if len(pairs) == 0 {
		return errors.New("nonempty case identities are required")
	}
	seen := map[string]bool{}
	for _, pair := range pairs {
		if pair == "" || seen[pair] {
			return errors.New("case identities must be unique")
		}
		seen[pair] = true
	}
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = loadJob(ctx, tx, id, true); err != nil {
		return err
	}
	result, err := tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_cases SET heartbeat_at=$4,lease_expires_at=$5,updated_at=$4 WHERE job_id=$1 AND configuration_pair_id=ANY($2::text[]) AND status='running' AND lease_owner=$3 AND lease_expires_at>$4`, id, pairs, owner, now, expires)
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count != int64(len(pairs)) {
		return ErrLeaseConflict
	}
	return tx.Commit()
}

// RecordProgress 保持已观察节点/边/展开计数单调；终态迟到事件返回 false，不改变完成结果。
func (store *Store) RecordProgress(ctx context.Context, id, pair, owner, revision string, now time.Time, progress Progress) (bool, error) {
	if err := progress.Validate(); err != nil {
		return false, err
	}
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return false, err
	}
	defer tx.Rollback()
	job, err := loadJob(ctx, tx, id, true)
	if err != nil {
		return false, err
	}
	if job.Revision != revision {
		return false, ErrRevision
	}
	item, err := scanCase(tx.QueryRowContext(ctx, caseSelect+` WHERE c.job_id=$1 AND c.configuration_pair_id=$2 FOR UPDATE OF c`, id, pair))
	if err != nil {
		return false, err
	}
	if terminalCase(item.Status) {
		return false, tx.Commit()
	}
	if !effectiveCase(item, owner, now) {
		return false, ErrLeaseConflict
	}
	_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_cases SET progress_phase=$3,observed_node_count=GREATEST(observed_node_count,$4),observed_edge_count=GREATEST(observed_edge_count,$5),expanded_node_count=GREATEST(expanded_node_count,$6),frontier_count=$7,action_pair_completed_count=$8,action_pair_total_count=$9,updated_at=$10 WHERE job_id=$1 AND configuration_pair_id=$2`, id, pair, progress.Phase, progress.ObservedNodes, progress.ObservedEdges, progress.ExpandedNodes, progress.Frontier, progress.ActionPairsCompleted, progress.ActionPairsTotal, now)
	if err != nil {
		return false, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET updated_at=$2 WHERE job_id=$1`, id, now); err != nil {
		return false, err
	}
	return true, tx.Commit()
}

// effectiveCase 判断当前 case 的 owner、运行状态及 lease 是否同时有效。
func effectiveCase(item Case, owner string, now time.Time) bool {
	return item.Status == Running && item.Lease != nil && item.Lease.Owner == owner && item.Lease.ExpiresAt.After(now)
}

// fractionParts 返回可绑定 SQL nullable TEXT 的分子分母，不截断大整数。
func fractionParts(value *Fraction) (any, any) {
	if value == nil {
		return nil, nil
	}
	return value.Numerator, value.Denominator
}

// applyResult 只更新一个已锁定 case 的终态及资源，不维护父任务进度桶。
func applyResult(ctx context.Context, tx *sql.Tx, id, pair string, now time.Time, result Result) error {
	an, ad := fractionParts(result.AttackerWin)
	dn, dd := fractionParts(result.DefenderWin)
	tn, td := fractionParts(result.Draw)
	var kind any
	var en, ed any
	if result.ExpectedTurns != nil {
		kind = result.ExpectedTurns.Kind
		en, ed = fractionParts(result.ExpectedTurns.Value)
	}
	_, err := tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_cases SET status=$3,attacker_win_numerator=$4,attacker_win_denominator=$5,defender_win_numerator=$6,defender_win_denominator=$7,draw_numerator=$8,draw_denominator=$9,expected_turns_kind=$10,expected_turns_numerator=$11,expected_turns_denominator=$12,node_count=$13,edge_count=$14,budget_consumed=$15,explanation_json=$16,failure_code=$17,diagnostic=$18,result_fingerprint=$19,completed_at=$20,updated_at=$20,lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL WHERE job_id=$1 AND configuration_pair_id=$2`, id, pair, result.Status, an, ad, dn, dd, tn, td, kind, en, ed, result.Nodes, result.Edges, result.Budget, result.Explanation, result.FailureCode, result.Diagnostic, result.Fingerprint(), now)
	return err
}

// RecordResult 将终态和 progress 守恒计数原子提交；完全相同指纹重放返回 false。
// 终态重放仍要求计算版本匹配；不同结果、旧 owner 或已过期 lease 都明确拒绝。
func (store *Store) RecordResult(ctx context.Context, id, pair, owner, revision string, now time.Time, result Result) (bool, error) {
	normalized, err := result.Normalize()
	if err != nil {
		return false, err
	}
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return false, err
	}
	defer tx.Rollback()
	job, err := loadJob(ctx, tx, id, true)
	if err != nil {
		return false, err
	}
	if job.Revision != revision {
		return false, ErrRevision
	}
	item, err := scanCase(tx.QueryRowContext(ctx, caseSelect+` WHERE c.job_id=$1 AND c.configuration_pair_id=$2 FOR UPDATE OF c`, id, pair))
	if err != nil {
		return false, err
	}
	if terminalCase(item.Status) {
		var prior string
		if err = tx.QueryRowContext(ctx, `SELECT result_fingerprint FROM poke_runtime.battle_inference_cases WHERE job_id=$1 AND configuration_pair_id=$2`, id, pair).Scan(&prior); err != nil {
			return false, err
		}
		if prior != normalized.Fingerprint() {
			return false, ErrConflict
		}
		return false, tx.Commit()
	}
	if !effectiveCase(item, owner, now) {
		return false, ErrLeaseConflict
	}
	if err = applyResult(ctx, tx, id, pair, now, normalized); err != nil {
		return false, err
	}
	_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_job_progress SET running_count=running_count-1,succeeded_count=succeeded_count+CASE WHEN $2='succeeded' THEN 1 ELSE 0 END,failed_count=failed_count+CASE WHEN $2='failed' THEN 1 ELSE 0 END,truncated_count=truncated_count+CASE WHEN $2='truncated' THEN 1 ELSE 0 END,cancelled_count=cancelled_count+CASE WHEN $2='cancelled' THEN 1 ELSE 0 END,cumulative_node_count=cumulative_node_count+$3,cumulative_edge_count=cumulative_edge_count+$4,budget_consumed=budget_consumed+$5,updated_at=$6 WHERE job_id=$1`, id, normalized.Status, normalized.Nodes, normalized.Edges, normalized.Budget, now)
	if err != nil {
		return false, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET updated_at=$2 WHERE job_id=$1`, id, now); err != nil {
		return false, err
	}
	return true, tx.Commit()
}

// CancelUnclaimed 将待领取与已过期运行 case 取消，保留持有有效 lease 的执行者宽限期。
func (store *Store) CancelUnclaimed(ctx context.Context, id string, now time.Time) (int, error) {
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	job, err := loadJob(ctx, tx, id, true)
	if err != nil {
		return 0, err
	}
	if job.Status != CancelRequested {
		return 0, ErrTransition
	}
	rows, err := tx.QueryContext(ctx, caseSelect+` WHERE c.job_id=$1 AND (c.status='pending' OR (c.status='running' AND (c.lease_expires_at IS NULL OR c.lease_expires_at<=$2))) ORDER BY c.sequence_no FOR UPDATE OF c SKIP LOCKED`, id, now)
	if err != nil {
		return 0, err
	}
	items := []Case{}
	for rows.Next() {
		item, scanErr := scanCase(rows)
		if scanErr != nil {
			rows.Close()
			return 0, scanErr
		}
		items = append(items, item)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return 0, err
	}
	code, diagnostic := "cancelled", "job cancellation reached an unclaimed or expired case"
	result := Result{Status: Cancelled, FailureCode: &code, Diagnostic: &diagnostic}
	pending, running := 0, 0
	for _, item := range items {
		if item.Status == Pending {
			pending++
		} else {
			running++
			if _, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_cases SET last_failure_code='worker_crash',last_failure_diagnostic='worker lease expired before cancellation' WHERE job_id=$1 AND configuration_pair_id=$2`, id, item.Definition.PairID); err != nil {
				return 0, err
			}
		}
		if err = applyResult(ctx, tx, id, item.Definition.PairID, now, result); err != nil {
			return 0, err
		}
	}
	_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_job_progress SET pending_count=pending_count-$2,running_count=running_count-$3,cancelled_count=cancelled_count+$2+$3,updated_at=$4 WHERE job_id=$1`, id, pending, running, now)
	if err != nil {
		return 0, err
	}
	if len(items) > 0 {
		if _, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET updated_at=$2 WHERE job_id=$1`, id, now); err != nil {
			return 0, err
		}
	}
	return len(items), tx.Commit()
}

// Cases 返回按 sequence 稳定分页的用例状态，过滤在分页前执行，终态不伪装成成功。
func (store *Store) Cases(ctx context.Context, id string, statuses []Status, offset, limit int) ([]Case, int, error) {
	return store.casePage(ctx, id, CaseFilter{Statuses: statuses, Offset: offset, Limit: limit}, false)
}

// CaseFilter 是原配置查询的可组合条件；空集合/空 ConfigurationID 表示不限制对应轴。
type CaseFilter struct {
	Statuses        []Status
	FailureCodes    []string
	ConfigurationID string
	Offset          int
	Limit           int
}

// Validate 检查 filter 的原状态/错误码及 1..1000 仓库分页边界；HTTP 另保留旧上限 500。
func (filter CaseFilter) Validate() error {
	if filter.Offset < 0 || filter.Limit < 1 || filter.Limit > 1000 {
		return errors.New("invalid case page")
	}
	for _, status := range filter.Statuses {
		if status != Pending && status != Running && !terminalCase(status) {
			return errors.New("unknown case status")
		}
	}
	for _, code := range filter.FailureCodes {
		if !ValidFailureCode(code) {
			return errors.New("unknown inference failure code")
		}
	}
	return nil
}

// FilteredCases 在同一 repeatable-read 快照返回 id 的状态、精确结果及过滤后总数，无 N+1 查询。
// ctx 取消全部 SQL；filter 必须通过 Validate；未创建 Go definition 的旧 Python cases 同样可读取。
func (store *Store) FilteredCases(ctx context.Context, id string, filter CaseFilter) ([]Case, int, error) {
	return store.casePage(ctx, id, filter, true)
}

// casePage 共享旧轻量分页与完整结果分页的事务；withResults 控制是否一次扫描终态列。
// 过滤先于 OFFSET/LIMIT，count/rows 使用同一快照，避免后台结果更新造成页面互相矛盾。
func (store *Store) casePage(ctx context.Context, id string, filter CaseFilter, withResults bool) ([]Case, int, error) {
	if err := filter.Validate(); err != nil {
		return nil, 0, err
	}
	values := make([]string, 0, len(filter.Statuses))
	for _, status := range filter.Statuses {
		values = append(values, string(status))
	}
	codes := filter.FailureCodes
	if codes == nil {
		codes = []string{}
	}
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, 0, err
	}
	defer tx.Rollback()
	// 原 results/issues 只依赖 job/progress/cases；缺 Go definition 或 execution spec 不能隐藏旧结果。
	var exists bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM poke_runtime.battle_inference_jobs j JOIN poke_runtime.battle_inference_job_progress p ON p.job_id=j.job_id WHERE j.job_id=$1)`, id).Scan(&exists); err != nil {
		return nil, 0, err
	}
	if !exists {
		return nil, 0, ErrNotFound
	}
	var total int
	const predicate = ` WHERE c.job_id=$1 AND (cardinality($2::text[])=0 OR c.status=ANY($2::text[])) AND (cardinality($3::text[])=0 OR c.failure_code=ANY($3::text[])) AND ($4='' OR $4=c.configuration_pair_id OR $4=c.attacker_configuration_id OR $4=c.defender_configuration_id)`
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM poke_runtime.battle_inference_cases c`+predicate, id, values, codes, filter.ConfigurationID).Scan(&total); err != nil {
		return nil, 0, err
	}
	fields := caseFields
	if withResults {
		fields += "," + resultColumns
	}
	rows, err := tx.QueryContext(ctx, `SELECT `+fields+` FROM poke_runtime.battle_inference_cases c`+predicate+` ORDER BY c.sequence_no OFFSET $5 LIMIT $6`, id, values, codes, filter.ConfigurationID, filter.Offset, filter.Limit)
	if err != nil {
		return nil, 0, err
	}
	items := []Case{}
	for rows.Next() {
		item, scanErr := scanCaseResult(rows, withResults)
		if scanErr != nil {
			rows.Close()
			return nil, 0, scanErr
		}
		items = append(items, item)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, 0, err
	}
	return items, total, tx.Commit()
}
