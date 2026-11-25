package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"strings"
	"time"
)

// inferenceGraphHandler 共享固定准备/独立Core，进程store仅保存冻结事实、计数与TTL。
type inferenceGraphHandler struct {
	fixed fixedInferenceHandler
	store *inferenceGraphStore
}

// registerFixedGraphRoutes 在同一服务器实例挂接原图创建和四条导航路由，不启动后台任务。
// mux由调用方拥有；fixed共享唯一catalog入口和正式worker配置，图store随该服务器实例释放。
func registerFixedGraphRoutes(mux *http.ServeMux, fixed fixedInferenceHandler) *inferenceGraphStore {
	handler := inferenceGraphHandler{fixed, newInferenceGraphStore()}
	mux.HandleFunc("POST /v1/inference/fixed-one-on-one/graph", handler.create)
	mux.HandleFunc("POST /v1/inference/graphs/{graph_id}/explore", handler.explore)
	mux.HandleFunc("POST /v1/inference/graphs/{graph_id}/groups/{group_id}/outcomes", handler.outcomes)
	mux.HandleFunc("POST /v1/inference/graphs/{graph_id}/advance", handler.advance)
	mux.HandleFunc("POST /v1/inference/graphs/{graph_id}/backtrack", handler.backtrack)
	registerWinningPaths(mux, handler.store, fixed.core)
	registerDragoniteJourney(mux, handler)
	return handler.store
}

// inferenceGraphFailure 仅映射原store/导航异常；准备、取消和worker隔离失败仍走既有适配器。
func inferenceGraphFailure(w http.ResponseWriter, err error) {
	var failure *inferenceGraphError
	if errors.As(err, &failure) {
		writeJSON(w, failure.status, map[string]any{"detail": map[string]string{"code": failure.code, "message": failure.message}})
		return
	}
	inferenceFailure(w, err)
}

// inferenceGraphConflict 把完整路径身份冲突格式化为原公开409，message只含公开图/步骤诊断。
func inferenceGraphConflict(message string) error {
	return &inferenceGraphError{409, "battle_exploration_conflict", message}
}

// create 使用同一PG快照严格准备并只求解一次；代表路径与计数来自该次Core结果。
// 请求ctx取消覆盖准备/child/store之前全部阶段，只有完整发布之后才返回可浏览句柄。
func (handler inferenceGraphHandler) create(w http.ResponseWriter, r *http.Request) {
	var input inferenceFixedRequest
	if !decodeJSON(w, r, &input) {
		return
	}
	if err := input.validate(); err != nil {
		inferenceFailure(w, inferenceInvalid(err.Error()))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	prepared, err := handler.fixed.prepare(ctx, input)
	if err != nil {
		inferenceGraphFailure(w, err)
		return
	}
	value, err := handler.createPrepared(ctx, input, prepared)
	if err != nil {
		inferenceGraphFailure(w, err)
		return
	}
	writeJSON(w, 200, value)
}

// createPrepared 消费同一快照准备结果，求解一次并冻结原请求/真实版本/计数及唯一store句柄。
// ctx由入口拥有；input仅提供原summary规则/策略标签，prepared保持Core完整事实，不输出全图JSON。
// 返回完整原stored journey；任何失败不会发布部分图或修改已有句柄。
func (handler inferenceGraphHandler) createPrepared(ctx context.Context, input inferenceFixedRequest, prepared inferencePrepared) (inferenceStoredJourney, error) {
	var operation map[string]json.RawMessage
	if json.Unmarshal(prepared.operation, &operation) != nil {
		return inferenceStoredJourney{}, errors.New("invalid prepared fixed request")
	}
	// 这两项只是正式Core输出选择，不改变冻结状态、知识、策略或预算。
	operation["include_graph"] = json.RawMessage(`false`)
	operation["include_representative_paths"] = json.RawMessage(`true`)
	// 旧请求无graph_mode时正式Core默认Full；新job摘要模板需要在图入口明确选回Full。
	if _, explicit := operation["graph_mode"]; explicit {
		operation["graph_mode"] = json.RawMessage(`"full"`)
	}
	updated, err := json.Marshal(operation)
	prepared.operation = updated
	if err != nil {
		return inferenceStoredJourney{}, err
	}
	result, err := handler.fixed.calculate(ctx, input, prepared)
	if err != nil {
		return inferenceStoredJourney{}, err
	}
	if result.native.Paths == nil {
		return inferenceStoredJourney{}, errors.New("native fixed request omitted representative paths")
	}
	for _, path := range result.native.Paths {
		raw, encodeErr := json.Marshal(path)
		if encodeErr != nil {
			return inferenceStoredJourney{}, encodeErr
		}
		result.summary.Paths = append(result.summary.Paths, raw)
	}
	artifact := &inferenceGraphArtifact{fixedRequest: prepared.operation, engineVersion: result.engineVersion, rulesVersion: result.rulesVersion,
		nodeCount: result.native.Statistics.Nodes, edgeCount: result.native.Statistics.Edges, revision: inferenceGraphRevision}
	if err = ctx.Err(); err != nil {
		return inferenceStoredJourney{}, err
	}
	stored, err := handler.store.put(artifact)
	if err != nil {
		return inferenceStoredJourney{}, err
	}
	return inferenceStoredJourney{Summary: result.summary, Exploration: inferenceGraphEntry{ID: stored.id, Root: 0, Revision: stored.revision,
		Expires: stored.expires.Format(time.RFC3339Nano), Cursor: inferenceGraphCursor{Steps: []inferenceGraphStep{}}, Expandable: true}}, nil
}

// UnmarshalJSON 区分原cursor的省略默认与显式null；data只借用到返回，成功后拥有完整步骤。
func (cursor *inferenceGraphCursor) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("cursor must be an object")
	}
	type plain inferenceGraphCursor
	value := plain{Steps: []inferenceGraphStep{}}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	if steps, exists := fields["steps"]; exists && string(steps) == "null" {
		return errors.New("cursor steps must be an array")
	}
	*cursor = inferenceGraphCursor(value)
	return nil
}

// normalizeInferenceIdentity 只做非负整数身份的词法验证/规范化；不计算战斗、图或概率。
// value来自原HTTP整数字段；返回false代表schema拒绝，不把非法ID当成未找到的图边。
func normalizeInferenceIdentity(value json.Number) (json.Number, bool) {
	number, ok := new(big.Int).SetString(value.String(), 10)
	if !ok || number.Sign() < 0 {
		return "", false
	}
	return json.Number(number.String()), true
}

// inferenceExploreRequest 保留原三个导航请求的公开字段；额外字段只由各自处理器解释。
// json.Number的身份没有float64中转，cursor为空步骤时仍表示服务端真实根节点0。
type inferenceExploreRequest struct {
	Revision string               `json:"calculation_revision"`
	Cursor   inferenceGraphCursor `json:"cursor"`
	Edge     *json.Number         `json:"edge_id,omitempty"`
	Depth    *json.Number         `json:"depth,omitempty"`
}

// readInferenceExplore 校验原导航公共schema；不执行Core、图搜索或概率运算。
// w只在格式失败写一次422；返回true时cursor.steps已规范为空数组而非null。
func readInferenceExplore(w http.ResponseWriter, r *http.Request) (inferenceExploreRequest, bool) {
	input := inferenceExploreRequest{Cursor: inferenceGraphCursor{[]inferenceGraphStep{}}}
	if !decodeJSON(w, r, &input) {
		return input, false
	}
	if input.Revision == "" {
		writeJSON(w, 422, map[string]string{"error": "calculation_revision is required"})
		return input, false
	}
	if input.Cursor.Steps == nil {
		input.Cursor.Steps = []inferenceGraphStep{}
	}
	for index, step := range input.Cursor.Steps {
		source, sourceOK := normalizeInferenceIdentity(step.Source)
		edge, edgeOK := normalizeInferenceIdentity(step.Edge)
		target, targetOK := normalizeInferenceIdentity(step.Target)
		if !sourceOK || !edgeOK || !targetOK {
			writeJSON(w, 422, map[string]string{"error": "cursor identities must be nonnegative integers"})
			return input, false
		}
		input.Cursor.Steps[index] = inferenceGraphStep{source, edge, target}
	}
	if input.Edge != nil {
		edge, ok := normalizeInferenceIdentity(*input.Edge)
		if !ok {
			writeJSON(w, 422, map[string]string{"error": "edge_id must be a nonnegative integer"})
			return input, false
		}
		input.Edge = &edge
	}
	if input.Depth != nil {
		depth, ok := normalizeInferenceIdentity(*input.Depth)
		if !ok {
			writeJSON(w, 422, map[string]string{"error": "depth must be nonnegative"})
			return input, false
		}
		input.Depth = &depth
	}
	return input, true
}

// load 先读取TTL句柄再验证语义revision，错误顺序与原load_context一致。
func (handler inferenceGraphHandler) load(id, revision string) (*inferenceGraphArtifact, error) {
	if id == "" || strings.TrimSpace(id) != id {
		return nil, inferenceGraphConflict("graph_id must be non-empty and normalized")
	}
	if revision == "" || strings.TrimSpace(revision) != revision {
		return nil, inferenceGraphConflict("calculation_revision must be non-empty and normalized")
	}
	artifact, err := handler.store.get(id)
	if err != nil {
		return nil, err
	}
	if artifact.revision != revision {
		return nil, inferenceGraphConflict(fmt.Sprintf("battle graph calculation revision mismatch: requested '%s', stored '%s'", revision, artifact.revision))
	}
	return artifact, nil
}

// inferenceFrozenStep 只把公开整数身份编码成Core任意精度十进制文本，不计算图关系。
type inferenceFrozenStep struct {
	Source string `json:"source_node_id"`
	Edge   string `json:"edge_id"`
	Target string `json:"target_node_id"`
}

// inferenceFrozenCursor 保持原用户步骤顺序，所有路径合法性与累计概率交Core验证。
type inferenceFrozenCursor struct {
	Steps []inferenceFrozenStep `json:"steps"`
}

// inferenceFrozenQuery 是一次按需重建的导航选择，不含完整图JSON或Go计算的投影。
type inferenceFrozenQuery struct {
	Mode     string                `json:"mode"`
	ID       string                `json:"graph_id"`
	Revision string                `json:"calculation_revision"`
	Cursor   inferenceFrozenCursor `json:"cursor"`
	Group    string                `json:"group_id,omitempty"`
	Edge     *string               `json:"edge_id,omitempty"`
	Depth    *string               `json:"depth,omitempty"`
}

// inferenceFrozenOperation 绑定首次计算的真实版本与图计数，禁止漂移后继续复用旧句柄。
type inferenceFrozenOperation struct {
	Kind   string               `json:"kind"`
	Fixed  json.RawMessage      `json:"fixed_request"`
	Engine string               `json:"expected_engine_version"`
	Rules  string               `json:"expected_rules_version"`
	Nodes  int                  `json:"expected_nodes"`
	Edges  int                  `json:"expected_edges"`
	Query  inferenceFrozenQuery `json:"query"`
}

// inferenceFrozenReply 将原HTTP业务拒绝与Core进程/协议失败分开，缺value不能当空成功。
type inferenceFrozenReply struct {
	Kind  string          `json:"kind"`
	Mode  string          `json:"mode"`
	Value json.RawMessage `json:"value"`
	Error *struct {
		Status  int    `json:"http_status"`
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

// frozenOperation 只复制请求的传输身份与已冻结事实；不搜索图、归并行动或计算概率。
func frozenOperation(artifact *inferenceGraphArtifact, input inferenceExploreRequest, mode, group string) inferenceFrozenOperation {
	steps := make([]inferenceFrozenStep, 0, len(input.Cursor.Steps))
	for _, step := range input.Cursor.Steps {
		steps = append(steps, inferenceFrozenStep{step.Source.String(), step.Edge.String(), step.Target.String()})
	}
	query := inferenceFrozenQuery{Mode: mode, ID: artifact.id, Revision: artifact.revision, Cursor: inferenceFrozenCursor{steps}, Group: group}
	if input.Edge != nil {
		edge := input.Edge.String()
		query.Edge = &edge
	}
	if input.Depth != nil {
		depth := input.Depth.String()
		query.Depth = &depth
	}
	return inferenceFrozenOperation{"fixed_graph_query", artifact.fixedRequest, artifact.engineVersion, artifact.rulesVersion, artifact.nodeCount, artifact.edgeCount, query}
}

// view 每个请求只启动一次独立Core，以冻结知识重建完整typed图并返回原页面DTO。
// mode由唯一已注册路由决定；ctx取消回收child，store锁不会覆盖构图或响应编码。
func (handler inferenceGraphHandler) view(w http.ResponseWriter, r *http.Request, mode string) {
	input, ok := readInferenceExplore(w, r)
	if !ok {
		return
	}
	if mode == "advance" && input.Edge == nil {
		writeJSON(w, 422, map[string]string{"error": "edge_id is required"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	artifact, err := handler.load(r.PathValue("graph_id"), input.Revision)
	if err != nil {
		inferenceGraphFailure(w, err)
		return
	}
	if mode == "outcomes" && (r.PathValue("group_id") == "" || strings.TrimSpace(r.PathValue("group_id")) != r.PathValue("group_id")) {
		inferenceGraphFailure(w, inferenceGraphConflict("group_id must be non-empty and normalized"))
		return
	}
	operation := frozenOperation(artifact, input, mode, r.PathValue("group_id"))
	values, err := handler.fixed.core.batch(ctx, []any{operation})
	if err != nil {
		inferenceGraphFailure(w, err)
		return
	}
	var reply inferenceFrozenReply
	if len(values) != 1 || json.Unmarshal(values[0], &reply) != nil || reply.Kind != "fixed_graph_query" || reply.Mode != mode {
		inferenceGraphFailure(w, errors.New("invalid native frozen graph query response"))
		return
	}
	if reply.Error != nil {
		if len(reply.Value) != 0 || reply.Error.Status < 400 || reply.Error.Status > 599 || reply.Error.Code == "" {
			inferenceGraphFailure(w, errors.New("invalid native frozen graph error response"))
			return
		}
		inferenceGraphFailure(w, &inferenceGraphError{reply.Error.Status, reply.Error.Code, reply.Error.Message})
		return
	}
	// 显式DTO把Core十进制身份无损转回原HTTP整数；所有业务投影均保持Core给定字段。
	if mode == "outcomes" {
		var value inferenceOutcomesResponse
		if json.Unmarshal(reply.Value, &value) != nil || value.ID != artifact.id || value.Revision != artifact.revision || value.Current == "" || value.Group.ID == "" {
			inferenceGraphFailure(w, errors.New("invalid native graph outcomes response"))
			return
		}
		writeJSON(w, 200, value)
		return
	}
	var value inferenceExplorationResponse
	if json.Unmarshal(reply.Value, &value) != nil || value.ID != artifact.id || value.Revision != artifact.revision || value.Node.ID == "" || value.Groups == nil || value.Report.Steps == nil {
		inferenceGraphFailure(w, errors.New("invalid native graph exploration response"))
		return
	}
	writeJSON(w, 200, value)
}

// explore 返回原当前节点与折叠分组；图身份和概率由同一Core计算。
func (handler inferenceGraphHandler) explore(w http.ResponseWriter, r *http.Request) {
	handler.view(w, r, "explore")
}

// outcomes 展开原当前节点的一个group，不在Go扫描或重组事件。
func (handler inferenceGraphHandler) outcomes(w http.ResponseWriter, r *http.Request) {
	handler.view(w, r, "outcomes")
}

// advance 由Core验证选中正式边、更新cursor并生成完整前缀战报。
func (handler inferenceGraphHandler) advance(w http.ResponseWriter, r *http.Request) {
	handler.view(w, r, "advance")
}

// backtrack 由Core验证原cursor后截断，保持原根回退与越界深度错误。
func (handler inferenceGraphHandler) backtrack(w http.ResponseWriter, r *http.Request) {
	handler.view(w, r, "backtrack")
}
