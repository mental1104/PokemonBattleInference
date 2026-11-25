package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"
)

// inferenceSnapshotInput 同时拥有原fixed选择与用户局部cursor，避免嵌入自定义解码器吞掉cursor。
type inferenceSnapshotInput struct {
	fixed  inferenceFixedRequest
	cursor inferenceGraphCursor
}

// UnmarshalJSON 借用data解码完整固定请求，cursor省略为根而显式null拒绝。
func (input *inferenceSnapshotInput) UnmarshalJSON(data []byte) error {
	if err := json.Unmarshal(data, &input.fixed); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	input.cursor = inferenceGraphCursor{Steps: []inferenceGraphStep{}}
	if raw, exists := fields["cursor"]; exists {
		return json.Unmarshal(raw, &input.cursor)
	}
	return nil
}

// inferenceSnapshotOperation 明确只传当前回合执行需要的事实，不携带或求解全局图预算。
type inferenceSnapshotOperation struct {
	Kind     string                `json:"kind"`
	State    json.RawMessage       `json:"state"`
	Chart    json.RawMessage       `json:"type_chart"`
	Attacker string                `json:"attacker_policy"`
	Defender string                `json:"defender_policy"`
	Limits   json.RawMessage       `json:"turn_limits,omitempty"`
	Cursor   inferenceFrozenCursor `json:"cursor"`
}

// inferenceSnapshotReply 是唯一snapshot结果，业务错误与缺失/畸形Core响应分别处理。
type inferenceSnapshotReply struct {
	Kind  string                        `json:"kind"`
	Value *inferenceExplorationResponse `json:"value"`
	Error *struct {
		Status  int    `json:"http_status"`
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

// registerFixedSnapshotRoute 由现有fixed composition调用；不另开store或后台worker。
func registerFixedSnapshotRoute(mux *http.ServeMux, handler fixedInferenceHandler) {
	mux.HandleFunc("POST /v1/inference/fixed-one-on-one/step", handler.step)
}

// step 复用同一真实PG快照严格准备后，Core按原cursor重放并只展开当前一层。
// ctx取消贯穿PG/准备/独立child；当前状态、局部ID、分组、概率和战报全部由Core产生。
func (handler fixedInferenceHandler) step(w http.ResponseWriter, r *http.Request) {
	var input inferenceSnapshotInput
	if !decodeJSON(w, r, &input) {
		return
	}
	if err := input.fixed.validate(); err != nil {
		inferenceFailure(w, inferenceInvalid(err.Error()))
		return
	}
	steps := make([]inferenceFrozenStep, 0, len(input.cursor.Steps))
	for _, step := range input.cursor.Steps {
		source, sourceOK := normalizeInferenceIdentity(step.Source)
		edge, edgeOK := normalizeInferenceIdentity(step.Edge)
		target, targetOK := normalizeInferenceIdentity(step.Target)
		if !sourceOK || !edgeOK || !targetOK {
			writeJSON(w, 422, map[string]string{"error": "cursor identities must be nonnegative integers"})
			return
		}
		steps = append(steps, inferenceFrozenStep{source.String(), edge.String(), target.String()})
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	prepared, err := handler.prepare(ctx, input.fixed)
	if err != nil {
		inferenceFailure(w, err)
		return
	}
	var operation inferenceSnapshotOperation
	// 源字段已由正式Core模板验证；只选择state/chart/policy/turn_limits，不改其中任何事实。
	if json.Unmarshal(prepared.operation, &operation) != nil || len(operation.State) == 0 || len(operation.Chart) == 0 {
		inferenceFailure(w, errors.New("invalid prepared snapshot request"))
		return
	}
	operation.Kind = "fixed_battle_snapshot"
	operation.Cursor = inferenceFrozenCursor{Steps: steps}
	values, err := handler.core.batch(ctx, []any{operation})
	if err != nil {
		inferenceFailure(w, err)
		return
	}
	var reply inferenceSnapshotReply
	if len(values) != 1 || json.Unmarshal(values[0], &reply) != nil || reply.Kind != "fixed_battle_snapshot" {
		inferenceFailure(w, errors.New("invalid native snapshot response"))
		return
	}
	if reply.Error != nil {
		if reply.Value != nil || reply.Error.Status != 422 || (reply.Error.Code != "fixed_battle_invalid_request" && reply.Error.Code != "fixed_battle_not_completely_solved") {
			inferenceFailure(w, errors.New("invalid native snapshot error response"))
			return
		}
		inferenceFailure(w, &inferenceRequestError{status: reply.Error.Status, code: reply.Error.Code, message: reply.Error.Message})
		return
	}
	if reply.Value == nil || reply.Value.ID != "fixed-one-on-one-snapshot" || reply.Value.Revision != inferenceGraphRevision || reply.Value.Node.ID == "" || reply.Value.Groups == nil || reply.Value.Report.Steps == nil {
		inferenceFailure(w, errors.New("invalid native snapshot exploration response"))
		return
	}
	writeJSON(w, 200, reply.Value)
}
