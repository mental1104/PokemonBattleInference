package nativeworker_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"pokemonbattleinference/server/internal/jobs"
	"testing"
)

// fixedOperation 仅在测试传输边界投影正式 fixture，状态/属性知识完整原样保留，不复制战斗规则。
type fixedOperation struct {
	Kind             string          `json:"kind"`
	State            json.RawMessage `json:"state"`
	Chart            json.RawMessage `json:"type_chart"`
	AttackerPolicy   string          `json:"attacker_policy"`
	DefenderPolicy   string          `json:"defender_policy"`
	Observer         string          `json:"observer"`
	IncludeGraph     bool            `json:"include_graph"`
	GraphMode        string          `json:"graph_mode"`
	Explanation      bool            `json:"include_root_action_explanation"`
	ProgressInterval int             `json:"progress_interval"`
	Limits           struct {
		Nodes int `json:"max_nodes"`
		Edges int `json:"max_edges"`
		Turns int `json:"max_turns"`
	} `json:"graph_limits"`
}

// fixedRequest 为 t 读取正式共享的真实固定战斗，observer 选择视角，nodes 是本次明确构图预算。
// 只改变执行参数以覆盖 PG 结果/进度/截断，预期一回合攻击方击倒来自冻结共享结果。
func fixedRequest(t *testing.T, observer string, nodes int) json.RawMessage {
	t.Helper()
	directory := os.Getenv("PBI_CONTRACT_FIXTURES")
	if directory == "" {
		directory = filepath.Join("..", "..", "..", "tests", "vectors")
	}
	data, err := os.ReadFile(filepath.Join(directory, "abi-calculations.v1.request.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Operations []json.RawMessage `json:"operations"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	for _, encoded := range fixture.Operations {
		var operation fixedOperation
		if err := json.Unmarshal(encoded, &operation); err != nil {
			t.Fatal(err)
		}
		if operation.Kind != "fixed_battle" {
			continue
		}
		operation.Observer, operation.ProgressInterval, operation.IncludeGraph = observer, 1, false
		operation.GraphMode, operation.Explanation = "configuration_summary", true
		operation.Limits.Nodes, operation.Limits.Edges, operation.Limits.Turns = nodes, 200, 10
		request, err := json.Marshal(struct {
			Schema     int              `json:"schema_version"`
			Operations []fixedOperation `json:"operations"`
		}{Schema: 1, Operations: []fixedOperation{operation}})
		if err != nil {
			t.Fatal(err)
		}
		return request
	}
	t.Fatal("the shared fixed_battle fixture is missing")
	return nil
}

// TestFixedBattlePersistsRealProgressAndExactSummary 经真实摘要构图/NDJSON/PG保存精确结果和完整业务归因。
// t 拥有独占数据库；额外独立执行同一冻结输入，核对业务说明原样落库与实际版本来源分离。
func TestFixedBattlePersistsRealProgressAndExactSummary(t *testing.T) {
	store, _, options := database(t)
	value := definition("fixed-one-on-one-job-actual-battle", options.Revision, 2)
	value.Spec.ProcessCount = 2
	value.Cases[0].CoreRequest = fixedRequest(t, "attacker", 100)
	value.Cases[1].CoreRequest = fixedRequest(t, "defender", 100)
	create(t, store, value)
	// case列表只保存公开身份；实际执行输入来自落库后重新读取的冻结Definition。
	frozen, err := store.Definition(context.Background(), value.ID)
	if err != nil || frozen.CoreTemplate != nil {
		t.Fatalf("expected independently frozen complete requests: %+v err=%v", frozen.CoreTemplate, err)
	}
	if worked, err := workerFor(t, store, options).RunOnce(context.Background()); err != nil || !worked {
		t.Fatalf("worked=%v err=%v", worked, err)
	}
	cases, total, err := store.Cases(context.Background(), value.ID, nil, 0, 10)
	if err != nil || total != 2 {
		t.Fatalf("total=%d err=%v", total, err)
	}
	for _, item := range cases {
		result, err := store.Result(context.Background(), value.ID, item.Definition.PairID)
		if err != nil || result == nil {
			t.Fatalf("result=%+v err=%v", result, err)
		}
		if result.Status != jobs.Succeeded || *result.AttackerWin != (jobs.Fraction{Numerator: "1", Denominator: "1"}) ||
			*result.DefenderWin != (jobs.Fraction{Numerator: "0", Denominator: "1"}) || result.ExpectedTurns.Kind != "finite" ||
			*result.ExpectedTurns.Value != (jobs.Fraction{Numerator: "1", Denominator: "1"}) {
			t.Fatalf("unexpected actual fixed battle result: %+v", result)
		}
		if result.Nodes != 2 || result.Edges != 1 || result.Budget != 3 {
			t.Fatalf("statistics not taken from Core: %+v", result)
		}
		if item.Progress.Phase != "graph_built" || item.Progress.ObservedNodes != 2 || item.Progress.ObservedEdges != 1 ||
			item.Progress.ExpandedNodes != 1 || item.Progress.Frontier != 0 {
			t.Fatalf("real final progress was not persisted: %+v", item.Progress)
		}
		if result.Explanation == nil {
			t.Fatal("root action attribution is absent")
		}
		// 独立辅助表保存实际child版本与最终请求SHA；不从提交Definition或旧explanation回填。
		provenance, err := store.ResultMetadata(context.Background(), value.ID, item.Definition.PairID)
		if err != nil || provenance == nil || provenance.EngineVersion == nil || provenance.RulesVersion == nil {
			t.Fatalf("actual execution metadata is absent: %+v err=%v", provenance, err)
		}
		var actualRequest json.RawMessage
		for _, candidate := range frozen.Cases {
			if candidate.PairID == item.Definition.PairID {
				actualRequest = candidate.CoreRequest
				break
			}
		}
		if len(actualRequest) == 0 {
			t.Fatal("the frozen case request is absent")
		}
		// 使用独立真实 child 读取完整对象，而不是在 Go 测试里重做归因或只核对版本标签。
		command := exec.Command(options.Executable)
		command.Stdin = bytes.NewReader(actualRequest)
		response, err := command.Output()
		if err != nil {
			t.Fatal(err)
		}
		var native struct {
			Rules   string `json:"rules_version"`
			Results []struct {
				Explanation json.RawMessage `json:"root_action_explanation"`
			} `json:"results"`
		}
		if err := json.Unmarshal(response, &native); err != nil || len(native.Results) != 1 {
			t.Fatalf("invalid independent native result: %s err=%v", response, err)
		}
		var expectedExplanation, storedExplanation bytes.Buffer
		if err := json.Compact(&expectedExplanation, native.Results[0].Explanation); err != nil {
			t.Fatal(err)
		}
		if err := json.Compact(&storedExplanation, []byte(*result.Explanation)); err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(expectedExplanation.Bytes(), storedExplanation.Bytes()) ||
			!bytes.Contains(storedExplanation.Bytes(), []byte(`"version":"battle-inference.explanation.v1"`)) ||
			bytes.Contains(storedExplanation.Bytes(), []byte(`"engine_version"`)) {
			t.Fatalf("stored business explanation differs from Core: %s", storedExplanation.String())
		}
		digest := sha256.Sum256(actualRequest)
		if provenance.InputSHA256 != hex.EncodeToString(digest[:]) || provenance.InputSchemaVersion != 1 ||
			provenance.Operation != "fixed_battle" || *provenance.EngineVersion != options.EngineVersion || *provenance.RulesVersion != native.Rules {
			t.Fatalf("execution metadata does not describe the real request/response: %+v", provenance)
		}
	}
}

// TestFixedBattleBudgetDoesNotInventDraw 真实节点预算截断保留 unknown 与资源，绝不把未解图持久化为平局。
func TestFixedBattleBudgetDoesNotInventDraw(t *testing.T) {
	store, _, options := database(t)
	value := definition("fixed-one-on-one-job-actual-budget", options.Revision, 1)
	value.Spec.MaxNodes = 1
	value.Cases[0].CoreRequest = fixedRequest(t, "attacker", 1)
	create(t, store, value)
	if _, err := workerFor(t, store, options).RunOnce(context.Background()); err != nil {
		t.Fatal(err)
	}
	result, err := store.Result(context.Background(), value.ID, value.Cases[0].PairID)
	if err != nil || result == nil || result.Status != jobs.Truncated || *result.FailureCode != "graph_node_limit" ||
		result.AttackerWin != nil || result.DefenderWin != nil || result.Draw != nil || result.ExpectedTurns != nil {
		t.Fatalf("truncated graph fabricated a result: %+v err=%v", result, err)
	}
	if result.Nodes != 1 || result.Edges != 0 || result.Budget != 1 {
		t.Fatalf("truncated resource counters lost: %+v", result)
	}
}
