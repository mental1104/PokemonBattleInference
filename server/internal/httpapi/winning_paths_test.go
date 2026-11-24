package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestWinningLookupBoundaries 仅验证原HTTP错误顺序和同一store的生命周期；不把它当作Core搜索验收。
// t由Go测试框架拥有；元数据夹具没有成功战斗输出，所有路径都在调用Core之前返回。
func TestWinningLookupBoundaries(t *testing.T) {
	store := newInferenceGraphStore()
	instant := time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC)
	// 时钟与只读元数据只用于生命周期边界，不构造战斗概率或冒充计算出的状态图。
	store.now = func() time.Time { return instant }
	store.entries["expired"] = &inferenceGraphArtifact{id: "expired", revision: "current", expires: instant.Add(-time.Second)}
	store.entries["held"] = &inferenceGraphArtifact{id: "held", revision: "current", expires: instant.Add(time.Minute)}
	mux := http.NewServeMux()
	registerWinningPaths(mux, store, calculatorHandler{})
	for _, scenario := range []struct {
		name, id, body string
		status         int
		code, message  string
	}{
		{"missing", "a'b", `{"calculation_revision":"current","winner":"attacker"}`, 404, "battle_graph_not_found", `battle graph "a'b" was not found`},
		{"sort-before-normalization", "missing", `{"calculation_revision":" old ","winner":"attacker","sort":"unknown"}`, 409, "winning_path_query_conflict", `'unknown' is not a valid WinningPathSort`},
		{"expired", "expired", `{"calculation_revision":"current","winner":"attacker"}`, 410, "battle_graph_expired", `battle graph 'expired' has expired`},
		{"expired-removed", "expired", `{"calculation_revision":"current","winner":"attacker"}`, 404, "battle_graph_not_found", `battle graph 'expired' was not found`},
		{"revision", "held", `{"calculation_revision":"old","winner":"attacker"}`, 409, "winning_path_query_conflict", `battle graph calculation revision mismatch: requested 'old', stored 'current'`},
	} {
		// 每次请求使用同一实际store，过期首次410之后再次查为404，不重新补回图。
		t.Run(scenario.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			incoming := httptest.NewRequest("POST", "/v1/winning_paths/graphs/"+scenario.id, strings.NewReader(scenario.body))
			mux.ServeHTTP(response, incoming)
			var body struct {
				Detail struct {
					Code    string `json:"code"`
					Message string `json:"message"`
				} `json:"detail"`
			}
			if response.Code != scenario.status || json.Unmarshal(response.Body.Bytes(), &body) != nil || body.Detail.Code != scenario.code || body.Detail.Message != scenario.message {
				t.Fatalf("unexpected query response: status=%d body=%s", response.Code, response.Body.String())
			}
		})
	}
}

// TestWinningIntegerProjection 保证Core十进制整数文本在旧HTTP仍为完整JSON整数，概率分数保持字符串。
// t由框架拥有；该测试只验证传输边界，不为任何战斗构造预期胜率。
func TestWinningIntegerProjection(t *testing.T) {
	const integer = "184467440737095516170000000000000001"
	var group winningPathGroup
	if err := json.Unmarshal([]byte(`{"raw_history_count_estimate":"`+integer+`","representative_path":[{"source_node_id":"9007199254740993","edge_id":"1","target_node_id":"2"}],"probability":{"numerator":"1","denominator":"`+integer+`","decimal":0,"percent":0}}`), &group); err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(group)
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		Histories json.RawMessage `json:"raw_history_count_estimate"`
		Path      []struct {
			Source json.RawMessage `json:"source_node_id"`
		} `json:"representative_path"`
		Probability struct {
			Denominator json.RawMessage `json:"denominator"`
		} `json:"probability"`
	}
	if json.Unmarshal(encoded, &result) != nil || string(result.Histories) != integer || len(result.Path) != 1 || string(result.Path[0].Source) != "9007199254740993" || string(result.Probability.Denominator) != `"`+integer+`"` {
		t.Fatalf("integer or probability representation changed: %s", encoded)
	}
}
