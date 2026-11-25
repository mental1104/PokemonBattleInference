package httpapi_test

import (
	"context"
	"encoding/json"
	"net/url"
	"pokemonbattleinference/server/internal/httpapi"
	"pokemonbattleinference/server/internal/jobs"
	"strings"
	"testing"
	"time"
)

// TestConfigurationResultMetadataPostgres 以真实 PG 验证独立路由、完整路径身份、旧记录 null 与旧解释保持。
// t 的独占库只构造存储状态；版本为刻意不同的测试标签，不把本测试声称为真实 Core 执行。
func TestConfigurationResultMetadataPostgres(t *testing.T) {
	db := isolatedDatabase(t)
	ctx := context.Background()
	store := jobs.New(db)
	if err := store.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	pair := `one-on-one-configuration:["one-on-one-move-pool.v1","pokemon-champion",25,"metadata-test",[212,null,50,"快龙/a?b#c%","technician",null,[404]],[149,null,50,"max_hp_def_plus","multiscale",null,[337]]]`
	legacyPair := strings.Replace(pair, "快龙/a?b#c%", "legacy", 1)
	unknownPair := strings.Replace(pair, "快龙/a?b#c%", "unknown", 1)
	definition := jobs.Definition{ID: "metadata-http", RulesetID: "pokemon-champion", VersionGroupID: 25, Revision: "metadata-test",
		Spec:      jobs.ExecutionSpec{ContractVersion: "one-on-one-move-pool.v1", WeightAssumption: "uniform_configuration_pair", AttackerPolicy: "first-legal-action", DefenderPolicy: "uniform-random", MechanismAdmission: "supported_only", ProcessCount: 1, QueueDepth: 1, MaxNodes: 100, MaxEdges: 400},
		Admission: json.RawMessage(`{"engine_version":"wrong-admission-version"}`)}
	for _, id := range []string{pair, legacyPair, unknownPair} {
		definition.Cases = append(definition.Cases, jobs.CaseDefinition{PairID: id, AttackerID: "212", DefenderID: "149", AttackerMoves: []int{404}, DefenderMoves: []int{337}, CoreRequest: json.RawMessage(`{"schema_version":1,"operations":[{"kind":"hp","base":91,"iv":31,"ev":0,"level":50}]}`)})
	}
	if _, err := store.Create(ctx, definition, now); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimJob(ctx, "coordinator", definition.Revision, now, time.Minute); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimCases(ctx, definition.ID, "worker", definition.Revision, now, time.Minute, 3); err != nil {
		t.Fatal(err)
	}
	engine, rules := "actual-callback-engine", "actual-callback-rules"
	metadata := &jobs.ExecutionMetadata{SchemaVersion: 1, EngineVersion: &engine, RulesVersion: &rules, InputSHA256: strings.Repeat("a", 64), InputSchemaVersion: 1, Operation: "fixed_battle", Observer: "attacker"}
	explanation := `{"business":"preserved","engine_version":"not-provenance"}`
	for _, id := range []string{pair, legacyPair, unknownPair} {
		result := jobs.Result{Status: jobs.Succeeded, AttackerWin: &jobs.Fraction{Numerator: "1", Denominator: "1"}, DefenderWin: &jobs.Fraction{Numerator: "0", Denominator: "1"}, Draw: &jobs.Fraction{Numerator: "0", Denominator: "1"}, ExpectedTurns: &jobs.ExpectedTurns{Kind: "finite", Value: &jobs.Fraction{Numerator: "1", Denominator: "1"}}, Nodes: 1, Edges: 1, Budget: 100, Explanation: &explanation}
		if id == pair {
			result.Metadata = metadata
		}
		if id == unknownPair {
			copy := *metadata
			copy.EngineVersion = nil
			copy.RulesVersion = nil
			result.Metadata = &copy
		}
		if _, err := store.RecordResult(ctx, definition.ID, id, "worker", definition.Revision, now.Add(time.Second), result); err != nil {
			t.Fatal(err)
		}
	}
	handler := httpapi.NewServer(db)
	base := "/v1/inference/configuration-jobs/" + definition.ID + "/results/"
	response := request(t, handler, "GET", base+url.PathEscape(pair)+"/metadata", "", "")
	var envelope struct {
		Schema   int                     `json:"schema_version"`
		Metadata *jobs.ExecutionMetadata `json:"metadata"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if response.Code != 200 || envelope.Schema != 1 || envelope.Metadata == nil || *envelope.Metadata.EngineVersion != engine || *envelope.Metadata.RulesVersion != rules || envelope.Metadata.InputSHA256 != metadata.InputSHA256 {
		t.Fatalf("actual source changed: status=%d body=%s", response.Code, response.Body)
	}
	response = request(t, handler, "GET", base+url.PathEscape(legacyPair)+"/metadata", "", "")
	if response.Code != 200 || strings.TrimSpace(response.Body.String()) != `{"schema_version":1,"metadata":null}` {
		t.Fatalf("legacy source invented: %d %s", response.Code, response.Body)
	}
	response = request(t, handler, "GET", base+url.PathEscape(unknownPair)+"/metadata", "", "")
	if err := json.Unmarshal(response.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if response.Code != 200 || envelope.Metadata == nil || envelope.Metadata.EngineVersion != nil || envelope.Metadata.RulesVersion != nil {
		t.Fatalf("unknown versions invented: %d %s", response.Code, response.Body)
	}
	for _, path := range []string{base + "missing/metadata", "/v1/inference/configuration-jobs/missing/results/legacy-pair/metadata"} {
		response = request(t, handler, "GET", path, "", "")
		if response.Code != 404 || !strings.Contains(response.Body.String(), "battle_inference_case_not_found") {
			t.Fatalf("missing case masked: %d %s", response.Code, response.Body)
		}
	}
	response = request(t, handler, "GET", strings.TrimSuffix(base, "/"), "", "")
	if response.Code != 200 || !strings.Contains(response.Body.String(), `"engine_version":"not-provenance"`) || strings.Contains(response.Body.String(), `"metadata"`) {
		t.Fatalf("legacy result contract changed: %d %s", response.Code, response.Body)
	}
	// 辅助表损坏必须明确失败；不能返回 admission、explanation 或伪旧记录 null。
	if _, err := db.ExecContext(ctx, `UPDATE poke_runtime.go_case_result_metadata SET metadata_json='{"schema_version":99}' WHERE job_id=$1 AND configuration_pair_id=$2`, definition.ID, pair); err != nil {
		t.Fatal(err)
	}
	response = request(t, handler, "GET", base+url.PathEscape(pair)+"/metadata", "", "")
	if response.Code != 503 {
		t.Fatalf("corrupt source masked: %d %s", response.Code, response.Body)
	}
}
