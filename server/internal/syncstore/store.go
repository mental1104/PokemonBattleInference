// Package syncstore 用真实 PostgreSQL 事务保存用户配置、幂等回执与删除增量。
package syncstore

import (
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"pokemonbattleinference/server/internal/syncmodels"
	"strings"
)

//go:embed schema.sql
var schema string

// ErrOperationReuse 表示同一幂等标识被用于不同内容；客户端必须保存原始请求后重试。
var ErrOperationReuse = errors.New("operation_id reused with different content")

// Store 借用调用者管理的连接池；所有修改由 PostgreSQL 用户行锁保护，进程重启不影响回执。
type Store struct{ db *sql.DB }

// New 借用 db 创建仓库；调用者负责关闭连接池，返回值不启动后台任务。
func New(db *sql.DB) *Store { return &Store{db: db} }

// Migrate 在 ctx 生命周期内非破坏性添加专属表；已有数据保留，失败整体回滚。
func (s *Store) Migrate(ctx context.Context) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, schema); err != nil {
		return err
	}
	return tx.Commit()
}

// Apply 按 user 隔离提交 op；ctx 取消会回滚。返回持久化回执，冲突也幂等持久化且不覆盖远端。
func (s *Store) Apply(ctx context.Context, user string, op syncmodels.Operation) (syncmodels.Result, error) {
	var result syncmodels.Result
	if strings.TrimSpace(user) == "" || len(user) > 256 {
		return result, errors.New("invalid user identity")
	}
	if err := op.Validate(); err != nil {
		return result, err
	}
	// JSON 规范化消除请求键顺序差异；不改变完整配置字段的语义。
	var payload json.RawMessage
	if err := json.Unmarshal(op.Configuration, &payload); err != nil {
		return result, err
	}
	var canonical any
	decoder := json.NewDecoder(strings.NewReader(string(payload)))
	decoder.UseNumber()
	if err := decoder.Decode(&canonical); err != nil {
		return result, err
	}
	normalized, err := json.Marshal(canonical)
	if err != nil {
		return result, err
	}
	op.Configuration = normalized
	body, err := json.Marshal(op)
	if err != nil {
		return result, err
	}
	digest := sha256.Sum256(body)
	hash := hex.EncodeToString(digest[:])
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, "INSERT INTO pbi_sync_users(user_id) VALUES ($1) ON CONFLICT DO NOTHING", user); err != nil {
		return result, err
	}
	var cursor int64
	if err = tx.QueryRowContext(ctx, "SELECT cursor FROM pbi_sync_users WHERE user_id=$1 FOR UPDATE", user).Scan(&cursor); err != nil {
		return result, err
	}
	// 锁覆盖幂等查询、revision 比较与写入：同一用户的所有进程看到相同提交次序。
	var priorHash string
	var prior []byte
	err = tx.QueryRowContext(ctx, "SELECT request_hash,result FROM pbi_sync_operations WHERE user_id=$1 AND operation_id=$2", user, op.OperationID).Scan(&priorHash, &prior)
	if err == nil {
		if priorHash != hash {
			return result, ErrOperationReuse
		}
		if err = json.Unmarshal(prior, &result); err != nil {
			return result, err
		}
		return result, tx.Commit()
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return result, err
	}
	var currentData []byte
	err = tx.QueryRowContext(ctx, "SELECT snapshot FROM pbi_sync_entities WHERE user_id=$1 AND entity_id=$2", user, op.EntityID).Scan(&currentData)
	if err == nil {
		var current syncmodels.Snapshot
		if err = json.Unmarshal(currentData, &current); err != nil {
			return result, err
		}
		result.Current = &current
	} else if !errors.Is(err, sql.ErrNoRows) {
		return result, err
	}
	currentRevision := int64(0)
	if result.Current != nil {
		currentRevision = result.Current.Revision
	}
	result.OperationID = op.OperationID
	result.Status = "conflict"
	if currentRevision == op.BaseRevision {
		if cursor == math.MaxInt64 {
			return result, errors.New("sync cursor exhausted")
		}
		cursor++
		result.Status = "accepted"
		result.Current = &syncmodels.Snapshot{EntityID: op.EntityID, Revision: cursor, Deleted: op.Kind == "delete", Configuration: op.Configuration, KnowledgeVersion: op.KnowledgeVersion, EngineVersion: op.EngineVersion}
		snapshot, marshalErr := json.Marshal(result.Current)
		if marshalErr != nil {
			return result, marshalErr
		}
		if _, err = tx.ExecContext(ctx, "INSERT INTO pbi_sync_entities(user_id,entity_id,revision,snapshot) VALUES ($1,$2,$3,$4) ON CONFLICT(user_id,entity_id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot", user, op.EntityID, cursor, string(snapshot)); err != nil {
			return result, err
		}
		if _, err = tx.ExecContext(ctx, "INSERT INTO pbi_sync_changes(user_id,cursor,snapshot) VALUES ($1,$2,$3)", user, cursor, string(snapshot)); err != nil {
			return result, err
		}
		if _, err = tx.ExecContext(ctx, "UPDATE pbi_sync_users SET cursor=$2 WHERE user_id=$1", user, cursor); err != nil {
			return result, err
		}
	}
	encoded, err := json.Marshal(result)
	if err != nil {
		return result, err
	}
	// 首次回执也从持久化结果读取，保证响应确实等于数据库中可重放的回执。
	var storedReceipt []byte
	if err = tx.QueryRowContext(ctx, "INSERT INTO pbi_sync_operations(user_id,operation_id,request_hash,result) VALUES ($1,$2,$3,$4) RETURNING result", user, op.OperationID, hash, string(encoded)).Scan(&storedReceipt); err != nil {
		return result, err
	}
	if err = json.Unmarshal(storedReceipt, &result); err != nil {
		return result, err
	}
	return result, tx.Commit()
}

// Changes 返回 user 在 after 之后最多 limit 条已提交变更；ctx 支持取消，limit 必须为 1…200。
// 空用户库返回空页；不会提升到尚未读取的游标，因此并发提交不会漏项。
func (s *Store) Changes(ctx context.Context, user string, after int64, limit int) (syncmodels.Page, error) {
	page := syncmodels.Page{Changes: []syncmodels.Snapshot{}, NextCursor: after}
	if strings.TrimSpace(user) == "" || len(user) > 256 || after < 0 || limit < 1 || limit > 200 {
		return page, errors.New("invalid sync page parameters")
	}
	rows, err := s.db.QueryContext(ctx, "SELECT snapshot FROM pbi_sync_changes WHERE user_id=$1 AND cursor>$2 ORDER BY cursor LIMIT $3", user, after, limit+1)
	if err != nil {
		return page, err
	}
	defer rows.Close()
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			return page, err
		}
		if len(page.Changes) == limit {
			page.HasMore = true
			break
		}
		var snapshot syncmodels.Snapshot
		if err = json.Unmarshal(raw, &snapshot); err != nil {
			return page, fmt.Errorf("decode sync snapshot: %w", err)
		}
		page.Changes = append(page.Changes, snapshot)
		page.NextCursor = snapshot.Revision
	}
	return page, rows.Err()
}
