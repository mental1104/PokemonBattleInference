// Package syncmodels 定义用户配置同步的版本化协议；不包含战斗计算或知识库内容。
package syncmodels

import (
	"encoding/json"
	"errors"
	"regexp"
	"strings"
)

// Operation 是一次设备编辑的不可变快照；相同 operation_id 的重试必须保持所有字段相同。
type Operation struct {
	SchemaVersion    int             `json:"schema_version"`
	OperationID      string          `json:"operation_id"`
	EntityID         string          `json:"entity_id"`
	BaseRevision     int64           `json:"base_revision"`
	LocalSequence    int64           `json:"local_sequence"`
	Kind             string          `json:"kind"`
	Configuration    json.RawMessage `json:"configuration"`
	KnowledgeVersion string          `json:"knowledge_version"`
	EngineVersion    string          `json:"engine_version"`
}

// Snapshot 是服务端持久化的完整配置或删除标记；Revision 也作为该用户的变更游标。
type Snapshot struct {
	EntityID         string          `json:"entity_id"`
	Revision         int64           `json:"revision"`
	Deleted          bool            `json:"deleted"`
	Configuration    json.RawMessage `json:"configuration"`
	KnowledgeVersion string          `json:"knowledge_version"`
	EngineVersion    string          `json:"engine_version"`
}

// Result 明确区分 accepted 与 conflict；冲突不会改变远端，Current 保留恢复所需的完整远端值。
type Result struct {
	OperationID string    `json:"operation_id"`
	Status      string    `json:"status"`
	Current     *Snapshot `json:"current"`
}

// Page 是严格按提交次序排列的增量页；空页保持请求游标，删除也占用游标。
type Page struct {
	Changes    []Snapshot `json:"changes"`
	NextCursor int64      `json:"next_cursor"`
	HasMore    bool       `json:"has_more"`
}

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// Validate 检查 op 的协议边界，返回可公开的 ASCII 输入错误；不解释战斗规则。
func (op Operation) Validate() error {
	if op.SchemaVersion != 1 || !uuidPattern.MatchString(op.OperationID) || !uuidPattern.MatchString(op.EntityID) || op.BaseRevision < 0 || op.LocalSequence < 1 || (op.Kind != "upsert" && op.Kind != "delete") {
		return errors.New("invalid operation identity, schema or revision")
	}
	if strings.TrimSpace(op.KnowledgeVersion) == "" || strings.TrimSpace(op.EngineVersion) == "" || len(op.KnowledgeVersion) > 256 || len(op.EngineVersion) > 256 {
		return errors.New("invalid version metadata")
	}
	// 配置保持 JSON 原样存储，仅验证稳定 ID 和必要名字；用户库不能依赖当前知识版本存在。
	var value struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if len(op.Configuration) > 1024*1024 || json.Unmarshal(op.Configuration, &value) != nil || strings.ToLower(value.ID) != op.EntityID || strings.TrimSpace(value.Name) == "" {
		return errors.New("invalid configuration payload")
	}
	return nil
}
