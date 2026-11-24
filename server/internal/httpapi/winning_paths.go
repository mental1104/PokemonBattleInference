package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/workerprocess"
	"strings"
	"time"
)

// winningPathsRequest 只保存原查询选择，不让平台计算路径、概率、排序或解码Core拥有的cursor。
type winningPathsRequest struct {
	Revision string  `json:"calculation_revision"`
	Winner   string  `json:"winner"`
	Limit    int     `json:"limit"`
	Cursor   *string `json:"cursor"`
	Sort     string  `json:"sort"`
}

// UnmarshalJSON 应用原省略默认，显式null不代表默认；data仅在解码期间借用。
func (request *winningPathsRequest) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("winning path request must be an object")
	}
	type plain winningPathsRequest
	value := plain{Limit: 10, Sort: "shortest-high-probability"}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, name := range []string{"calculation_revision", "winner", "limit", "sort"} {
		if string(fields[name]) == "null" {
			return errors.New("winning path fields cannot be null")
		}
	}
	*request = winningPathsRequest(value)
	return nil
}

// winningPathsHandler 借用与原graph导航相同的进程store，把完整冻结事实交独立Core按需重建图。
type winningPathsHandler struct {
	store *inferenceGraphStore
	core  calculatorHandler
}

// registerWinningPaths 由唯一graph注册块调用，store随服务器生命周期存在，不另造缓存或后台线程。
func registerWinningPaths(mux *http.ServeMux, store *inferenceGraphStore, core calculatorHandler) {
	mux.Handle("POST /v1/winning_paths/graphs/{graph_id}", winningPathsHandler{store, core})
}

// winningFailure 输出原winning专属envelope；message只来自公开标识或已验证Core协议诊断。
func winningFailure(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"detail": map[string]string{"code": code, "message": message}})
}

// winningFrozenQuery 只描述原winning选择，Core负责cursor解码、配置身份和完整图搜索。
type winningFrozenQuery struct {
	Mode string `json:"mode"`
	ID   string `json:"graph_id"`
	winningPathsRequest
}

// winningCoreOperation 是正式按需重建DTO；原请求已冻结全部知识/策略/预算，不再查PG或传565MiB图JSON。
// Expected字段由首次真实Core返回绑定；Core必须验证版本和完整计数，不接受漂移后同ID图。
type winningCoreOperation struct {
	Kind   string             `json:"kind"`
	Fixed  json.RawMessage    `json:"fixed_request"`
	Engine string             `json:"expected_engine_version"`
	Rules  string             `json:"expected_rules_version"`
	Nodes  int                `json:"expected_nodes"`
	Edges  int                `json:"expected_edges"`
	Query  winningFrozenQuery `json:"query"`
}

// winningCoreQuery 机械转发同一冻结fixed请求，不在Go重建SCC、截事件、恢复概率或枚举路径。
// artifact借用已发布不可变快照；input已完成HTTP格式校验，返回同源只读传输值。
func winningCoreQuery(id string, input winningPathsRequest, artifact *inferenceGraphArtifact) winningCoreOperation {
	return winningCoreOperation{"fixed_graph_query", artifact.fixedRequest, artifact.engineVersion, artifact.rulesVersion, artifact.nodeCount, artifact.edgeCount, winningFrozenQuery{"winning_paths", id, input}}
}

// ServeHTTP 先按原顺序检查store/revision，再通过同源30秒ctx执行唯一Core查询。
// 输出使用显式DTO无损转写数字，当前尚未在graph注册块挂接，须等待正式ABI和原HTTP差分。
func (handler winningPathsHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var input winningPathsRequest
	if !decodeJSON(w, r, &input) {
		return
	}
	if input.Revision == "" || (input.Winner != "attacker" && input.Winner != "defender") || input.Limit < 1 || input.Limit > 100 {
		detail(w, 422, "invalid winning path request")
		return
	}
	id := r.PathValue("graph_id")
	// 原router先构造WinningPathSort枚举，再进入execute的标识/store校验。
	if input.Sort != "shortest-high-probability" {
		winningFailure(w, 409, "winning_path_query_conflict", pythonRepr(input.Sort)+" is not a valid WinningPathSort")
		return
	}
	for _, field := range []struct {
		Name  string
		Value string
	}{{"graph_id", id}, {"calculation_revision", input.Revision}} {
		if field.Value == "" || field.Value != strings.TrimSpace(field.Value) {
			winningFailure(w, 409, "winning_path_query_conflict", field.Name+" must be a non-empty normalized string")
			return
		}
	}
	artifact, err := handler.store.get(id)
	if err != nil {
		var failure *inferenceGraphError
		if errors.As(err, &failure) {
			code, message := "battle_graph_store_error", failure.message
			if failure.status == 404 {
				code = "battle_graph_not_found"
				message = "battle graph " + pythonRepr(id) + " was not found"
			}
			if failure.status == 410 {
				code = "battle_graph_expired"
				message = "battle graph " + pythonRepr(id) + " has expired"
			}
			winningFailure(w, failure.status, code, message)
		} else {
			winningFailure(w, 503, "battle_graph_store_error", "battle graph store is unavailable")
		}
		return
	}
	if input.Revision != artifact.revision {
		winningFailure(w, 409, "winning_path_query_conflict", fmt.Sprintf("battle graph calculation revision mismatch: requested %s, stored %s", pythonRepr(input.Revision), pythonRepr(artifact.revision)))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	result, err := handler.calculate(ctx, winningCoreQuery(id, input, artifact))
	if err != nil {
		var failure *winningQueryFailure
		if errors.As(err, &failure) {
			winningFailure(w, 409, "winning_path_query_conflict", failure.message)
		} else {
			calculatorFailure(w, err)
		}
		return
	}
	// 重建和查询的业务错误由同一Core返回明确envelope；不将版本漂移或失败重建解释为空胜利路径。
	var query struct {
		Kind  string          `json:"kind"`
		Mode  string          `json:"mode"`
		Value json.RawMessage `json:"value"`
		Error *struct {
			Status  int    `json:"http_status"`
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(result, &query) != nil || query.Kind != "fixed_graph_query" || query.Mode != "winning_paths" {
		detail(w, 500, "invalid native winning query result")
		return
	}
	if query.Error != nil {
		if query.Error.Status < 400 || query.Error.Status > 599 || query.Error.Code == "" || query.Error.Message == "" {
			detail(w, 500, "invalid native winning query error")
			return
		}
		winningFailure(w, query.Error.Status, query.Error.Code, query.Error.Message)
		return
	}
	// json.Number同时接受Core十进制字符串和原JSON整数，重编码为数字；精确分数仍是独立string字段。
	var response struct {
		Kind string `json:"kind"`
		winningPathsResponse
	}
	if json.Unmarshal(query.Value, &response) != nil || response.Kind != "winning_paths" || response.ID != id || response.Revision != input.Revision || response.Winner != input.Winner || response.Sort != input.Sort {
		detail(w, 500, "invalid native winning path result")
		return
	}
	writeJSON(w, 200, response.winningPathsResponse)
}

// winningQueryFailure 仅保存已验证ABI invalid_input的安全业务message，不携带worker stderr或文件路径。
type winningQueryFailure struct{ message string }

// Error 返回Core拥有的cursor/图查询诊断；HTTP外层统一编码，避免自由文本解析。
func (failure *winningQueryFailure) Error() string { return failure.message }

// calculate 复用正式Execute隔离边界，额外保留原409所需的ABI业务message。
// ctx负责子进程取消和回收；operation是完整拥有的原生请求，不返回部分结果或解析stderr。
func (handler winningPathsHandler) calculate(ctx context.Context, operation winningCoreOperation) (json.RawMessage, error) {
	if !filepath.IsAbs(handler.core.worker) {
		return nil, errCalculatorWorkerUnavailable
	}
	info, err := os.Stat(handler.core.worker)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		return nil, errCalculatorWorkerUnavailable
	}
	body, err := json.Marshal(struct {
		Version    int   `json:"schema_version"`
		Operations []any `json:"operations"`
	}{1, []any{operation}})
	if err != nil {
		return nil, err
	}
	raw, err := workerprocess.Execute(ctx, handler.core.worker, body)
	if err != nil {
		var failure *workerprocess.Failure
		if errors.As(err, &failure) && failure.Code == "invalid_input" {
			var native struct {
				Error struct {
					Code    string `json:"code"`
					Message string `json:"message"`
				} `json:"error"`
			}
			if json.Unmarshal(raw, &native) == nil && native.Error.Code == failure.Code && native.Error.Message != "" {
				return nil, &winningQueryFailure{native.Error.Message}
			}
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if !errors.As(err, &failure) && !errors.Is(err, workerprocess.ErrOutputLimit) {
			return nil, errCalculatorWorkerUnavailable
		}
		return nil, err
	}
	var response businessCoreBatch
	if json.Unmarshal(raw, &response) != nil || response.Version != 1 || len(response.Results) != 1 {
		return nil, errors.New("invalid native winning path envelope")
	}
	return response.Results[0], nil
}
