package jobs_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"pokemonbattleinference/server/internal/jobs"
	"reflect"
	"strings"
	"testing"
	"time"
)

// executionMetadata 为仓库测试构造调用方提供的实际输入字节摘要；不声称本测试执行了Core或推断真实版本。
// request是不修改的冻结字节；版本标签刻意与Admission不同，证明存储层没有拿提交版本替代调用方来源。
func executionMetadata(request []byte) *jobs.ExecutionMetadata {
	digest := sha256.Sum256(request)
	engine, rules := "child-execution-engine", "child-execution-rules"
	return &jobs.ExecutionMetadata{SchemaVersion: 1, EngineVersion: &engine, RulesVersion: &rules, InputSHA256: hex.EncodeToString(digest[:]), InputSchemaVersion: 1, Operation: "hp", Observer: "attacker"}
}

// TestExecutionMetadataAtomicLeaseReplayPostgres 验证辅助来源与原终态/进度同事务、旧owner无权写、重放不覆盖来源。
// t通过既有database创建独占临时库；全部资料只验证PG状态机，不伪造任何原生计算验收。
func TestExecutionMetadataAtomicLeaseReplayPostgres(t *testing.T) {
	store, db := database(t)
	ctx := context.Background()
	now := time.Now().UTC()
	def := definition("metadata-atomic", 2)
	def.Admission = json.RawMessage(`{"core_response":{"engine_version":"submission-engine","rules_version":"submission-rules"}}`)
	if _, err := store.Create(ctx, def, now); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimJob(ctx, "coordinator", def.Revision, now, time.Minute); err != nil {
		t.Fatal(err)
	}
	cases, err := store.ClaimCases(ctx, def.ID, "worker", def.Revision, now, time.Minute, 2)
	if err != nil || len(cases) != 2 {
		t.Fatalf("claim: cases=%v err=%v", cases, err)
	}
	result := success()
	result.Metadata = executionMetadata(def.Cases[0].CoreRequest)
	if result.Fingerprint() != success().Fingerprint() {
		t.Fatal("auxiliary metadata changed the legacy result fingerprint")
	}
	if _, err = store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "old-worker", def.Revision, now.Add(time.Second), result); !errors.Is(err, jobs.ErrLeaseConflict) {
		t.Fatalf("old owner was not rejected: %v", err)
	}
	if metadata, e := store.ResultMetadata(ctx, def.ID, cases[0].Definition.PairID); e != nil || metadata != nil {
		t.Fatalf("unauthorized metadata persisted: %+v %v", metadata, e)
	}
	// aux INSERT确实失败时，之前的case UPDATE和lease释放必须由同一事务回滚。
	_, err = db.ExecContext(ctx, `CREATE FUNCTION poke_runtime.reject_metadata_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'metadata rollback fixture'; END; $$;
CREATE TRIGGER reject_metadata_fixture BEFORE INSERT ON poke_runtime.go_case_result_metadata FOR EACH ROW EXECUTE FUNCTION poke_runtime.reject_metadata_fixture()`)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "worker", def.Revision, now.Add(time.Second), result); err == nil {
		t.Fatal("metadata write rejection was ignored")
	}
	state, err := store.Get(ctx, def.ID)
	if err != nil || state.Counts.Running != 2 || state.Counts.Succeeded != 0 {
		t.Fatalf("failed transaction changed counters: %+v %v", state.Counts, err)
	}
	remaining, _, err := store.Cases(ctx, def.ID, []jobs.Status{jobs.Running}, 0, 10)
	if err != nil || len(remaining) != 2 || remaining[0].Lease == nil || remaining[0].Lease.Owner != "worker" {
		t.Fatalf("failed transaction changed the lease: %+v %v", remaining, err)
	}
	if metadata, e := store.ResultMetadata(ctx, def.ID, cases[0].Definition.PairID); e != nil || metadata != nil {
		t.Fatalf("failed transaction leaked metadata: %+v %v", metadata, e)
	}
	if _, err = db.ExecContext(ctx, `DROP TRIGGER reject_metadata_fixture ON poke_runtime.go_case_result_metadata`); err != nil {
		t.Fatal(err)
	}
	if applied, e := store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "worker", def.Revision, now.Add(2*time.Second), result); e != nil || !applied {
		t.Fatalf("commit: %v %v", applied, e)
	}
	metadata, err := store.ResultMetadata(ctx, def.ID, cases[0].Definition.PairID)
	if err != nil || !reflect.DeepEqual(metadata, result.Metadata) {
		t.Fatalf("execution source changed: %+v %v", metadata, err)
	}
	// 指纹不包含aux信息；终态相同数学结果的晚到回执也不能覆盖首个实际执行来源。
	changed := success()
	changed.Metadata = executionMetadata([]byte("different callback request"))
	if applied, e := store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "late-worker", def.Revision, now.Add(3*time.Second), changed); e != nil || applied {
		t.Fatalf("terminal replay: %v %v", applied, e)
	}
	preserved, err := store.ResultMetadata(ctx, def.ID, cases[0].Definition.PairID)
	if err != nil || !reflect.DeepEqual(preserved, metadata) {
		t.Fatalf("terminal replay replaced metadata: %+v %v", preserved, err)
	}
	// 原SQL形状的成功结果无需metadata；读取旧结果不推断版本、不改变explanation。
	if applied, e := store.RecordResult(ctx, def.ID, cases[1].Definition.PairID, "worker", def.Revision, now.Add(4*time.Second), success()); e != nil || !applied {
		t.Fatalf("legacy result: %v %v", applied, e)
	}
	if legacy, e := store.ResultMetadata(ctx, def.ID, cases[1].Definition.PairID); e != nil || legacy != nil {
		t.Fatalf("legacy metadata was invented: %+v %v", legacy, e)
	}
	if err = store.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	after, err := store.ResultMetadata(ctx, def.ID, cases[0].Definition.PairID)
	if err != nil || !reflect.DeepEqual(after, metadata) {
		t.Fatalf("migration rewrote metadata: %+v %v", after, err)
	}
}

// TestExecutionMetadataValidationAndOwnership 验证schema/hash格式、未知实际版本和Normalize的独立拥有值。
// t不访问PG或Core；所有版本标签只用于验证存储边界，真实child来源由nativeworker集成测试覆盖。
func TestExecutionMetadataValidationAndOwnership(t *testing.T) {
	result := success()
	result.Metadata = executionMetadata([]byte("final request bytes"))
	normalized, err := result.Normalize()
	if err != nil {
		t.Fatal(err)
	}
	*result.Metadata.EngineVersion = "caller mutation"
	if *normalized.Metadata.EngineVersion != "child-execution-engine" {
		t.Fatal("normalized metadata aliases caller version state")
	}
	for _, bad := range []jobs.ExecutionMetadata{
		{SchemaVersion: 2, InputSchemaVersion: 1, InputSHA256: strings.Repeat("a", 64), Operation: "graph", Observer: "attacker"},
		{SchemaVersion: 1, InputSchemaVersion: 1, InputSHA256: strings.Repeat("G", 64), Operation: "graph", Observer: "attacker"},
		{SchemaVersion: 1, InputSchemaVersion: 1, InputSHA256: strings.Repeat("a", 64), Operation: "", Observer: "attacker"},
	} {
		// 不允许无效来源先改变case终态；RecordResult调用Normalize早于开启写事务。
		candidate := success()
		candidate.Metadata = &bad
		if _, err = candidate.Normalize(); err == nil {
			t.Fatal("invalid execution metadata was accepted")
		}
	}
	unknown := success()
	unknown.Metadata = executionMetadata([]byte("request without a child response"))
	unknown.Metadata.EngineVersion = nil
	unknown.Metadata.RulesVersion = nil
	value, err := unknown.Normalize()
	if err != nil || value.Metadata.EngineVersion != nil || value.Metadata.RulesVersion != nil {
		t.Fatalf("unknown actual versions were invented: %+v %v", value.Metadata, err)
	}
}
