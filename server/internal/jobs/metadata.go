package jobs

import (
	"context"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

// ExecutionMetadata 独立保存实际子进程版本与最终请求摘要，不占用原explanation或改变原结果指纹。
// EngineVersion/RulesVersion成对nil表示未取得真实child响应；不得用提交版本或Worker配置代填。
type ExecutionMetadata struct {
	SchemaVersion      int     `json:"schema_version"`
	EngineVersion      *string `json:"engine_version"`
	RulesVersion       *string `json:"rules_version"`
	InputSHA256        string  `json:"input_sha256"`
	InputSchemaVersion int     `json:"input_schema_version"`
	Operation          string  `json:"operation"`
	Observer           string  `json:"observer"`
}

// normalized 校验实际来源字段并复制可空字符串，返回独立拥有值；不推断版本或重新计算输入SHA。
func (metadata ExecutionMetadata) normalized() (*ExecutionMetadata, error) {
	if metadata.SchemaVersion != 1 || metadata.InputSchemaVersion != 1 {
		return nil, errors.New("unsupported execution metadata schema")
	}
	digest, err := hex.DecodeString(metadata.InputSHA256)
	if err != nil || len(digest) != 32 || metadata.InputSHA256 != strings.ToLower(metadata.InputSHA256) {
		return nil, errors.New("execution metadata requires a lowercase SHA256 input digest")
	}
	if metadata.Operation == "" || strings.TrimSpace(metadata.Operation) != metadata.Operation || (metadata.Observer != "attacker" && metadata.Observer != "defender") {
		return nil, errors.New("execution metadata requires an operation and observer")
	}
	if (metadata.EngineVersion == nil) != (metadata.RulesVersion == nil) {
		return nil, errors.New("actual execution versions must both be known or unknown")
	}
	for _, version := range []**string{&metadata.EngineVersion, &metadata.RulesVersion} {
		if *version == nil {
			continue
		}
		value := **version
		if value == "" || value != strings.TrimSpace(value) {
			return nil, errors.New("actual execution version must be normalized and nonempty")
		}
		*version = &value
	}
	return &metadata, nil
}

// migrateExecutionMetadata 仅增量创建私有辅助表；ctx取消回滚单条DDL，不修改原六表或历史行。
func (store *Store) migrateExecutionMetadata(ctx context.Context) error {
	_, err := store.db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS poke_runtime.go_case_result_metadata (
 job_id text NOT NULL,
 configuration_pair_id text NOT NULL,
 metadata_json json NOT NULL,
 result_fingerprint char(64) NOT NULL,
 created_at timestamptz NOT NULL,
 PRIMARY KEY(job_id,configuration_pair_id),
 FOREIGN KEY(job_id,configuration_pair_id) REFERENCES poke_runtime.battle_inference_cases(job_id,configuration_pair_id) ON DELETE CASCADE
)`)
	return err
}

// persistExecutionMetadata 只由持有有效case租约且正在提交终态的同一事务调用。
// metadata为Normalize后的独立值；nil保留旧Python/未执行准备失败的无元数据状态。
// id/pair绑定真实case，fingerprint是原终态指纹；首次插入之外不覆盖现存溯源，冲突令整个结果事务失败。
func persistExecutionMetadata(ctx context.Context, tx *sql.Tx, id, pair string, now time.Time, result Result) error {
	if result.Metadata == nil {
		return nil
	}
	data, err := json.Marshal(result.Metadata)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO poke_runtime.go_case_result_metadata(job_id,configuration_pair_id,metadata_json,result_fingerprint,created_at) VALUES($1,$2,$3,$4,$5)`, id, pair, string(data), result.Fingerprint(), now)
	return err
}

// ResultMetadata 读取id/pair的实际执行溯源；没有辅助行（包括旧Python结果）返回(nil,nil)。
// ctx取消终止查询；返回值独立拥有，非法历史元数据或数据库错误明确返回error，不从Definition补造。
func (store *Store) ResultMetadata(ctx context.Context, id, pair string) (*ExecutionMetadata, error) {
	var data []byte
	err := store.db.QueryRowContext(ctx, `SELECT metadata_json FROM poke_runtime.go_case_result_metadata WHERE job_id=$1 AND configuration_pair_id=$2`, id, pair).Scan(&data)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var metadata ExecutionMetadata
	if err = json.Unmarshal(data, &metadata); err != nil {
		return nil, err
	}
	return metadata.normalized()
}
