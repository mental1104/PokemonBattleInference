package jobs

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

// Store 借用连接池，所有状态改变都使用原任务行锁保证进度桶守恒。
type Store struct{ db *sql.DB }

// New 返回使用 db 的任务仓库，不启动 coordinator 或执行计算。
func New(db *sql.DB) *Store { return &Store{db: db} }

// Migrate 只增加 Go 任务冻结定义表；旧六张运行表须由显式数据库初始化先建立。
// 已存在 Python 任务没有该表中的定义，因此 Go 不会凭空领取不能重建输入的旧任务。
func (store *Store) Migrate(ctx context.Context) error {
	_, err := store.db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS poke_runtime.go_job_definitions(job_id text PRIMARY KEY REFERENCES poke_runtime.battle_inference_jobs(job_id) ON DELETE CASCADE,definition_hash char(64) NOT NULL,definition_json json NOT NULL,created_at timestamptz NOT NULL DEFAULT now())`)
	return err
}

// Create 原子保存 definition、冻结规格、全部有序 case 和初始进度；同 ID 同定义返回 false。
// 不同定义复用 ID 返回 ErrConflict；事务失败不保留部分任务或统计。
func (store *Store) Create(ctx context.Context, definition Definition, now time.Time) (bool, error) {
	if err := definition.Validate(); err != nil {
		return false, err
	}
	if now.IsZero() {
		return false, errors.New("creation timestamp is required")
	}
	data, err := json.Marshal(definition)
	if err != nil {
		return false, err
	}
	sum := sha256.Sum256(data)
	hash := hex.EncodeToString(sum[:])
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return false, err
	}
	defer tx.Rollback()
	result, err := tx.ExecContext(ctx, `INSERT INTO poke_runtime.battle_inference_jobs(job_id,ruleset_id,version_group_id,calculation_revision,status,attempt_count,created_at,updated_at) VALUES($1,$2,$3,$4,'pending',0,$5,$5) ON CONFLICT(job_id) DO NOTHING`, definition.ID, definition.RulesetID, definition.VersionGroupID, definition.Revision, now)
	if err != nil {
		return false, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if count == 0 {
		var prior *string
		err = tx.QueryRowContext(ctx, `SELECT d.definition_hash FROM poke_runtime.battle_inference_jobs j LEFT JOIN poke_runtime.go_job_definitions d ON d.job_id=j.job_id WHERE j.job_id=$1 FOR UPDATE OF j`, definition.ID).Scan(&prior)
		if err != nil {
			return false, err
		}
		if prior == nil || *prior != hash {
			return false, ErrConflict
		}
		return false, tx.Commit()
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO poke_runtime.go_job_definitions(job_id,definition_hash,definition_json,created_at) VALUES($1,$2,$3,$4)`, definition.ID, hash, string(data), now); err != nil {
		return false, err
	}
	spec := definition.Spec
	if _, err = tx.ExecContext(ctx, `INSERT INTO poke_runtime.battle_inference_job_execution_specs(job_id,contract_version,weight_assumption,attacker_policy,defender_policy,mechanism_admission,process_count,queue_depth,max_nodes_per_pair,max_edges_per_pair,max_turns) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, definition.ID, spec.ContractVersion, spec.WeightAssumption, spec.AttackerPolicy, spec.DefenderPolicy, spec.MechanismAdmission, spec.ProcessCount, spec.QueueDepth, spec.MaxNodes, spec.MaxEdges, spec.MaxTurns); err != nil {
		return false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO poke_runtime.battle_inference_job_progress(job_id,total_count,pending_count,running_count,succeeded_count,failed_count,truncated_count,cancelled_count,cumulative_node_count,cumulative_edge_count,budget_consumed,updated_at) VALUES($1,$2,$2,0,0,0,0,0,0,0,0,$3)`, definition.ID, len(definition.Cases), now); err != nil {
		return false, err
	}
	for sequence, item := range definition.Cases {
		_, err = tx.ExecContext(ctx, `INSERT INTO poke_runtime.battle_inference_cases(job_id,sequence_no,configuration_pair_id,attacker_configuration_id,defender_configuration_id,attacker_move_ids,defender_move_ids,status,attempt_count,node_count,edge_count,observed_node_count,observed_edge_count,expanded_node_count,frontier_count,action_pair_completed_count,action_pair_total_count,budget_consumed,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,'pending',0,0,0,0,0,0,0,0,0,0,$8,$8)`, definition.ID, sequence, item.PairID, item.AttackerID, item.DefenderID, item.AttackerMoves, item.DefenderMoves, now)
		if err != nil {
			return false, err
		}
	}
	return true, tx.Commit()
}

// rowQuery 是 DB/Tx 的共同只读端口，使锁和事务边界留在明确调用点。
type rowQuery interface {
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

const jobSelect = `SELECT j.job_id,j.ruleset_id,j.version_group_id,j.calculation_revision,j.status,j.attempt_count,j.lease_owner,j.lease_expires_at,j.heartbeat_at,j.last_failure_code,j.last_failure_diagnostic,j.created_at,j.updated_at,j.started_at,j.completed_at,j.cancel_requested_at,p.total_count,p.pending_count,p.running_count,p.succeeded_count,p.failed_count,p.truncated_count,p.cancelled_count,p.cumulative_node_count,p.cumulative_edge_count,p.budget_consumed,s.contract_version,s.weight_assumption,s.attacker_policy,s.defender_policy,s.mechanism_admission,s.process_count,s.queue_depth,s.max_nodes_per_pair,s.max_edges_per_pair,s.max_turns FROM poke_runtime.battle_inference_jobs j JOIN poke_runtime.battle_inference_job_progress p ON p.job_id=j.job_id JOIN poke_runtime.battle_inference_job_execution_specs s ON s.job_id=j.job_id`

// loadJob 读取 id 的完整快照；lock 时只锁任务父行，所有修改都先取得相同锁序。
func loadJob(ctx context.Context, query rowQuery, id string, lock bool) (Job, error) {
	statement := jobSelect + ` WHERE j.job_id=$1`
	if lock {
		statement += ` FOR UPDATE OF j`
	}
	var job Job
	var owner *string
	var expires, heartbeat *time.Time
	err := query.QueryRowContext(ctx, statement, id).Scan(&job.ID, &job.RulesetID, &job.VersionGroupID, &job.Revision, &job.Status, &job.Attempts, &owner, &expires, &heartbeat, &job.FailureCode, &job.Diagnostic, &job.CreatedAt, &job.UpdatedAt, &job.StartedAt, &job.CompletedAt, &job.CancelRequestedAt, &job.Counts.Total, &job.Counts.Pending, &job.Counts.Running, &job.Counts.Succeeded, &job.Counts.Failed, &job.Counts.Truncated, &job.Counts.Cancelled, &job.Counts.Nodes, &job.Counts.Edges, &job.Counts.Budget, &job.Spec.ContractVersion, &job.Spec.WeightAssumption, &job.Spec.AttackerPolicy, &job.Spec.DefenderPolicy, &job.Spec.MechanismAdmission, &job.Spec.ProcessCount, &job.Spec.QueueDepth, &job.Spec.MaxNodes, &job.Spec.MaxEdges, &job.Spec.MaxTurns)
	if errors.Is(err, sql.ErrNoRows) {
		return job, ErrNotFound
	}
	if err != nil {
		return job, err
	}
	if owner != nil && expires != nil && heartbeat != nil {
		job.Lease = &Lease{*owner, *expires, *heartbeat}
	}
	return job, nil
}

// Get 返回 id 的当前持久化快照，不要求任务属于新 Go coordinator。
func (store *Store) Get(ctx context.Context, id string) (Job, error) {
	return loadJob(ctx, store.db, id, false)
}

// Definition 读取完整冻结输入，不依赖进程内任务注册表。
func (store *Store) Definition(ctx context.Context, id string) (Definition, error) {
	var data []byte
	var definition Definition
	err := store.db.QueryRowContext(ctx, `SELECT definition_json FROM poke_runtime.go_job_definitions WHERE job_id=$1`, id).Scan(&data)
	if errors.Is(err, sql.ErrNoRows) {
		return definition, ErrNotFound
	}
	if err != nil {
		return definition, err
	}
	err = json.Unmarshal(data, &definition)
	return definition, err
}

// ClaimJob 按创建顺序以 SKIP LOCKED 原子领取兼容 revision 的 Go 任务。
// 过期 owner 迁移会保留已完成用例，仅增加尝试次数和恢复诊断。
func (store *Store) ClaimJob(ctx context.Context, owner, revision string, now time.Time, duration time.Duration) (*Job, error) {
	expires, err := validateLease(owner, now, duration)
	if err != nil {
		return nil, err
	}
	if revision == "" {
		return nil, ErrRevision
	}
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	var id string
	err = tx.QueryRowContext(ctx, `SELECT j.job_id FROM poke_runtime.battle_inference_jobs j JOIN poke_runtime.go_job_definitions d ON d.job_id=j.job_id WHERE j.calculation_revision=$1 AND (j.status='pending' OR (j.status IN('preparing','running','cancel_requested') AND (j.lease_expires_at IS NULL OR j.lease_expires_at<=$2))) ORDER BY j.created_at,j.job_id LIMIT 1 FOR UPDATE OF j SKIP LOCKED`, revision, now).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET last_failure_code=CASE WHEN status IN('preparing','running') AND lease_owner IS NOT NULL THEN 'worker_crash' ELSE last_failure_code END,last_failure_diagnostic=CASE WHEN status IN('preparing','running') AND lease_owner IS NOT NULL THEN 'coordinator lease expired before reclaim' ELSE last_failure_diagnostic END,status=CASE WHEN status='pending' THEN 'preparing' ELSE status END,attempt_count=attempt_count+1,lease_owner=$2,lease_expires_at=$4,heartbeat_at=$3,started_at=COALESCE(started_at,$3),updated_at=$3 WHERE job_id=$1`, id, owner, now, expires)
	if err != nil {
		return nil, err
	}
	job, err := loadJob(ctx, tx, id, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &job, nil
}

// HeartbeatJob 只允许当前有效 owner 延长租约，过期 owner 无法复活自己。
func (store *Store) HeartbeatJob(ctx context.Context, id, owner string, now time.Time, duration time.Duration) error {
	expires, err := validateLease(owner, now, duration)
	if err != nil {
		return err
	}
	result, err := store.db.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET lease_expires_at=$4,heartbeat_at=$3,updated_at=$3 WHERE job_id=$1 AND lease_owner=$2 AND lease_expires_at>$3 AND status IN('preparing','running','cancel_requested')`, id, owner, now, expires)
	return affected(result, err)
}

// affected 将条件更新的零行统一映射为租约冲突，不凭行存在性泄露其他信息。
func affected(result sql.Result, err error) error {
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count != 1 {
		return ErrLeaseConflict
	}
	return nil
}

// RequestCancel 幂等记录首次取消时间；任务终态保持原结果不变。
func (store *Store) RequestCancel(ctx context.Context, id string, now time.Time) (Job, error) {
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return Job{}, err
	}
	defer tx.Rollback()
	job, err := loadJob(ctx, tx, id, true)
	if err != nil {
		return job, err
	}
	if !terminalJob(job.Status) && job.Status != CancelRequested {
		_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET status='cancel_requested',cancel_requested_at=$2,updated_at=$2 WHERE job_id=$1`, id, now)
		if err != nil {
			return job, err
		}
		job, err = loadJob(ctx, tx, id, false)
		if err != nil {
			return job, err
		}
	}
	return job, tx.Commit()
}

// Finalize 只在 pending/running 桶均为零时派生最终状态并清空 coordinator lease。
// 已完成任务重放返回原快照，保留首次完成时间。
func (store *Store) Finalize(ctx context.Context, id string, now time.Time) (Job, error) {
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return Job{}, err
	}
	defer tx.Rollback()
	job, err := loadJob(ctx, tx, id, true)
	if err != nil {
		return job, err
	}
	if terminalJob(job.Status) {
		return job, tx.Commit()
	}
	if job.Counts.Pending > 0 || job.Counts.Running > 0 {
		return job, ErrTransition
	}
	status := Succeeded
	if job.Status == CancelRequested || job.Counts.Cancelled > 0 {
		status = Cancelled
	} else if job.Counts.Failed > 0 || job.Counts.Truncated > 0 {
		status = CompletedWithFailures
	}
	_, err = tx.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_jobs SET status=$2,completed_at=$3,updated_at=$3,lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL WHERE job_id=$1`, id, status, now)
	if err != nil {
		return job, err
	}
	job, err = loadJob(ctx, tx, id, false)
	if err != nil {
		return job, err
	}
	return job, tx.Commit()
}

// List 返回按创建时间倒序的原任务列表，jobType 过滤在 LIMIT 前执行，避免跨类型跳页。
func (store *Store) List(ctx context.Context, statuses []Status, activeOnly bool, jobType string, offset, limit int) ([]Job, error) {
	if offset < 0 || limit < 1 || limit > 100 {
		return nil, errors.New("invalid job page")
	}
	if jobType != "" && jobType != "fixed-one-on-one" && jobType != "configuration-space" {
		return nil, errors.New("invalid job type")
	}
	values := make([]string, 0, len(statuses))
	for _, status := range statuses {
		if status != Pending && status != Preparing && status != Running && status != CancelRequested && !terminalJob(status) {
			return nil, errors.New("unknown job status")
		}
		values = append(values, string(status))
	}
	rows, err := store.db.QueryContext(ctx, `SELECT job_id FROM poke_runtime.battle_inference_jobs WHERE (cardinality($1::text[])=0 OR status=ANY($1::text[])) AND (NOT $2 OR status IN('pending','preparing','running','cancel_requested')) AND ($3='' OR ($3='fixed-one-on-one' AND job_id LIKE 'fixed-one-on-one-job-%') OR ($3='configuration-space' AND job_id NOT LIKE 'fixed-one-on-one-job-%')) ORDER BY created_at DESC,job_id DESC OFFSET $4 LIMIT $5`, values, activeOnly, jobType, offset, limit)
	if err != nil {
		return nil, err
	}
	ids := []string{}
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		ids = append(ids, id)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	result := make([]Job, 0, len(ids))
	for _, id := range ids {
		job, err := store.Get(ctx, id)
		if err != nil {
			return nil, fmt.Errorf("read job summary: %w", err)
		}
		result = append(result, job)
	}
	return result, nil
}
