// Package nativeworker 调度持久化用例与独立原生进程，不实现伤害或概率计算规则。
package nativeworker

import (
	"encoding/json"
	"errors"
	"math"
	"pokemonbattleinference/server/internal/jobs"
	"slices"
	"strings"
)

// calculationInput 只投影正式图/固定战斗的身份；完整状态和知识原样交给 Core，不在 Go 解释规则。
type calculationInput struct {
	Kind        string            `json:"kind"`
	Observer    string            `json:"observer"`
	Nodes       []json.RawMessage `json:"nodes"`
	Edges       []json.RawMessage `json:"edges"`
	Truncations []string          `json:"truncations"`
	State       json.RawMessage   `json:"state"`
}

// graphStatistics 只读取真实构图输出计数，nil 可区别缺少统计与真实零边图。
type graphStatistics struct {
	Nodes int64 `json:"nodes"`
	Edges int64 `json:"edges"`
}

// graphOutput 只投影 Core 已算出的精确摘要，任何未知/不完整状态均不生成默认概率。
// Explanation 保留完整业务归因 JSON；未请求或原生返回 null 时为 nil，版本来源另存独立辅助表。
type graphOutput struct {
	Kind        string           `json:"kind"`
	Status      string           `json:"status"`
	Win         *jobs.Fraction   `json:"win"`
	Loss        *jobs.Fraction   `json:"loss"`
	Draw        *jobs.Fraction   `json:"draw"`
	Observer    string           `json:"observer"`
	Statistics  *graphStatistics `json:"statistics"`
	Truncations []string         `json:"truncations"`
	Diagnostics []string         `json:"diagnostics"`
	Explanation *json.RawMessage `json:"root_action_explanation"`
	Expected    struct {
		Status string         `json:"status"`
		Value  *jobs.Fraction `json:"value"`
	} `json:"expected_turns"`
}

// responseEnvelope 保留实际原生版本；与调度器构建不同的子进程不得写入成功结果。
type responseEnvelope struct {
	Schema  int           `json:"schema_version"`
	Engine  string        `json:"engine_version"`
	Rules   string        `json:"rules_version"`
	Results []graphOutput `json:"results"`
}

var errNativeVersion = errors.New("native engine version mismatch")

// readInput 只接纳一个正式 graph/fixed_battle 请求，其他操作不能假装成持久推演。
// request 为持久化完整批次，返回只读字段投影或错误，调用方仍把原始字节发送给独立 Core。
func readInput(request []byte) (calculationInput, error) {
	var batch struct {
		Schema     int                `json:"schema_version"`
		Operations []calculationInput `json:"operations"`
	}
	if err := json.Unmarshal(request, &batch); err != nil {
		return calculationInput{}, err
	}
	if batch.Schema != 1 || len(batch.Operations) != 1 {
		return calculationInput{}, errors.New("worker requires one version 1 inference operation")
	}
	input := batch.Operations[0]
	if input.Observer != "attacker" && input.Observer != "defender" {
		return calculationInput{}, errors.New("inference observer is required")
	}
	switch input.Kind {
	case "graph":
		if len(input.Nodes) == 0 {
			return calculationInput{}, errors.New("graph nodes are required")
		}
	case "fixed_battle":
		if len(input.State) == 0 {
			return calculationInput{}, errors.New("fixed battle state is required")
		}
	default:
		return calculationInput{}, errors.New("unsupported persistent inference operation")
	}
	return input, nil
}

// decodeResult 将 response 中实际 Core 摘要映射为旧结果合同；engine 是本次明确要求的原生版本。
// 只交换 observer 的胜负视角及验证分数，完整业务归因原样保存；错误不会变成成功或零概率。
func decodeResult(input calculationInput, response []byte, engine string) (jobs.Result, error) {
	var envelope responseEnvelope
	if err := json.Unmarshal(response, &envelope); err != nil {
		return jobs.Result{}, err
	}
	if envelope.Engine != engine {
		return jobs.Result{}, errNativeVersion
	}
	if envelope.Schema != 1 || envelope.Rules == "" || len(envelope.Results) != 1 || envelope.Results[0].Kind != input.Kind {
		return jobs.Result{}, errors.New("invalid native response envelope")
	}
	value := envelope.Results[0]
	nodes, edges := int64(len(input.Nodes)), int64(len(input.Edges))
	reasons := input.Truncations
	if input.Kind == "fixed_battle" {
		if value.Observer != input.Observer || value.Statistics == nil {
			return jobs.Result{}, errors.New("fixed battle response is missing its observer or statistics")
		}
		nodes, edges, reasons = value.Statistics.Nodes, value.Statistics.Edges, value.Truncations
	}
	if nodes < 1 || edges < 0 || edges > math.MaxInt64-nodes {
		return jobs.Result{}, errors.New("invalid native graph resource counts")
	}
	if value.Status != "solved" {
		code := "solver_unresolved"
		status := jobs.Failed
		diagnostics := value.Diagnostics
		if value.Status == "incomplete-graph" {
			status = jobs.Truncated
			// 纯Core使用通用未解诊断；原任务DTO逐项展示构图保护原因和对应solver说明。
			// 这里仅格式化同一事实，不改图、求解状态或概率；失败码按节点→边→回合优先。
			diagnostics = append([]string(nil), reasons...)
			if len(reasons) == 0 {
				diagnostics = append(diagnostics, "graph contains unknown nodes")
			} else {
				for _, reason := range reasons {
					diagnostics = append(diagnostics, "graph truncated: "+reason)
				}
			}
			switch {
			case slices.Contains(reasons, "max-nodes"):
				code = "graph_node_limit"
			case slices.Contains(reasons, "max-edges"):
				code = "graph_edge_limit"
			case slices.Contains(reasons, "max-turns"):
				code = "turn_limit"
			}
		} else if value.Status != "singular-system" {
			return jobs.Result{}, errors.New("unknown native graph status")
		} else if len(diagnostics) == 0 {
			diagnostics = []string{value.Status}
		}
		diagnostic := strings.Join(diagnostics, "; ")
		if diagnostic == "" {
			diagnostic = string(status)
		}
		result := failure(status, code, diagnostic)
		result.Nodes, result.Edges, result.Budget = nodes, edges, nodes+edges
		return result.Normalize()
	}
	var explanation *string
	if value.Explanation != nil {
		// 业务归因由同次 Core 求得，Go 不重建桶、不更换视角，也不拿引擎元数据补空解释。
		encoded := string(*value.Explanation)
		explanation = &encoded
	}
	attacker, defender := value.Win, value.Loss
	if input.Observer == "defender" {
		attacker, defender = defender, attacker
	}
	result := jobs.Result{Status: jobs.Succeeded, AttackerWin: attacker, DefenderWin: defender, Draw: value.Draw,
		ExpectedTurns: &jobs.ExpectedTurns{Kind: value.Expected.Status, Value: value.Expected.Value},
		Nodes:         nodes, Edges: edges, Budget: nodes + edges, Explanation: explanation}
	return result.Normalize()
}

// failure 返回符合旧失败字段互斥合同的终态；code/diagnostic 必须是稳定 ASCII 类别和诊断。
func failure(status jobs.Status, code, diagnostic string) jobs.Result {
	return jobs.Result{Status: status, FailureCode: &code, Diagnostic: &diagnostic}
}
