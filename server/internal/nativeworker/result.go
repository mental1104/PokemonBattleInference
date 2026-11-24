// Package nativeworker 调度持久化用例与独立原生进程，不实现伤害或概率计算规则。
package nativeworker

import (
	"encoding/json"
	"errors"
	"pokemonbattleinference/server/internal/jobs"
)

// graphInput 是当前可执行的正式显式图合同，只读取身份和资源数量，完整请求原样交给 Core。
type graphInput struct {
	Kind        string            `json:"kind"`
	Observer    string            `json:"observer"`
	Nodes       []json.RawMessage `json:"nodes"`
	Edges       []json.RawMessage `json:"edges"`
	Truncations []string          `json:"truncations"`
}

// graphOutput 只投影 Core 已算出的精确摘要，任何未知/不完整状态均不生成默认概率。
type graphOutput struct {
	Kind        string         `json:"kind"`
	Status      string         `json:"status"`
	Win         *jobs.Fraction `json:"win"`
	Loss        *jobs.Fraction `json:"loss"`
	Draw        *jobs.Fraction `json:"draw"`
	ClosedCycle *jobs.Fraction `json:"closed_cycle"`
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

// resultMetadata 保存版本和视角；完整图来自冻结输入按需读取，不在每个分页摘要中复制 SCC。
type resultMetadata struct {
	Engine      string         `json:"engine_version"`
	Rules       string         `json:"rules_version"`
	Operation   string         `json:"operation"`
	Observer    string         `json:"observer"`
	ClosedCycle *jobs.Fraction `json:"closed_cycle"`
}

var errNativeVersion = errors.New("native engine version mismatch")

// readGraph 只接纳单个正式 graph 请求；尚未迁移的战斗请求明确拒绝，不使用替代规则伪造推演。
// request 为持久化完整批次，返回只读字段投影或错误，调用方仍把原始字节发送给独立 Core。
func readGraph(request []byte) (graphInput, error) {
	var batch struct {
		Schema     int          `json:"schema_version"`
		Operations []graphInput `json:"operations"`
	}
	if err := json.Unmarshal(request, &batch); err != nil {
		return graphInput{}, err
	}
	if batch.Schema != 1 || len(batch.Operations) != 1 || batch.Operations[0].Kind != "graph" {
		return graphInput{}, errors.New("worker requires one version 1 graph operation")
	}
	input := batch.Operations[0]
	if (input.Observer != "attacker" && input.Observer != "defender") || len(input.Nodes) == 0 {
		return graphInput{}, errors.New("graph observer and nodes are required")
	}
	return input, nil
}

// decodeResult 将 response 中实际 Core 摘要映射为旧结果合同；engine 是本次明确要求的原生版本。
// 只交换 observer 的胜负视角及验证分数，不在 Go 进行求解；错误不会变成成功或零概率。
func decodeResult(input graphInput, response []byte, engine string) (jobs.Result, error) {
	var envelope responseEnvelope
	if err := json.Unmarshal(response, &envelope); err != nil {
		return jobs.Result{}, err
	}
	if envelope.Engine != engine {
		return jobs.Result{}, errNativeVersion
	}
	if envelope.Schema != 1 || envelope.Rules == "" || len(envelope.Results) != 1 || envelope.Results[0].Kind != "graph" {
		return jobs.Result{}, errors.New("invalid native response envelope")
	}
	value := envelope.Results[0]
	nodes, edges := int64(len(input.Nodes)), int64(len(input.Edges))
	if value.Status != "solved" {
		code := "solver_unresolved"
		status := jobs.Failed
		if value.Status == "incomplete-graph" {
			status = jobs.Truncated
			for _, reason := range input.Truncations {
				switch reason {
				case "max-nodes":
					code = "graph_node_limit"
				case "max-edges":
					code = "graph_edge_limit"
				case "max-turns":
					code = "turn_limit"
				}
			}
		} else if value.Status != "singular-system" {
			return jobs.Result{}, errors.New("unknown native graph status")
		}
		result := failure(status, code, "native graph is unresolved")
		result.Nodes, result.Edges, result.Budget = nodes, edges, nodes+edges
		return result.Normalize()
	}
	metadata, err := json.Marshal(resultMetadata{envelope.Engine, envelope.Rules, "graph", input.Observer, value.ClosedCycle})
	if err != nil {
		return jobs.Result{}, err
	}
	explanation := string(metadata)
	attacker, defender := value.Win, value.Loss
	if input.Observer == "defender" {
		attacker, defender = defender, attacker
	}
	result := jobs.Result{Status: jobs.Succeeded, AttackerWin: attacker, DefenderWin: defender, Draw: value.Draw,
		ExpectedTurns: &jobs.ExpectedTurns{Kind: value.Expected.Status, Value: value.Expected.Value},
		Nodes:         nodes, Edges: edges, Budget: nodes + edges, Explanation: &explanation}
	return result.Normalize()
}

// failure 返回符合旧失败字段互斥合同的终态；code/diagnostic 必须是稳定 ASCII 类别和诊断。
func failure(status jobs.Status, code, diagnostic string) jobs.Result {
	return jobs.Result{Status: status, FailureCode: &code, Diagnostic: &diagnostic}
}
