package jobs_test

import (
	"context"
	"pokemonbattleinference/server/internal/jobs"
	"testing"
	"time"
)

// TestFilteredCaseResultsKeepLegacyRows 在独占 PG 验证先过滤后分页、同快照结果及无 Go definition/spec 的历史读取。
// t 管理数据库与断言；本测试只创建结果资料夹具，不冒称 Core 战斗已执行。
func TestFilteredCaseResultsKeepLegacyRows(t *testing.T) {
	store, db := database(t)
	ctx := context.Background()
	now := time.Date(2026, 11, 24, 1, 2, 3, 0, time.UTC)
	value := definition("legacy-filtered-cases", 4)
	if _, err := store.Create(ctx, value, now); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimJob(ctx, "coordinator", value.Revision, now, time.Minute); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimCases(ctx, value.ID, "worker", value.Revision, now, time.Minute, 3); err != nil {
		t.Fatal(err)
	}
	crash, limit, diagnostic := "worker_crash", "graph_node_limit", "archived result fixture"
	outcomes := []jobs.Result{success(), {Status: jobs.Failed, FailureCode: &crash, Diagnostic: &diagnostic, Nodes: 7, Edges: 9}, {Status: jobs.Truncated, FailureCode: &limit, Diagnostic: &diagnostic, Nodes: 17, Edges: 29}}
	for index, outcome := range outcomes {
		if _, err := store.RecordResult(ctx, value.ID, value.Cases[index].PairID, "worker", value.Revision, now, outcome); err != nil {
			t.Fatal(err)
		}
	}
	items, total, err := store.FilteredCases(ctx, value.ID, jobs.CaseFilter{Statuses: []jobs.Status{jobs.Failed, jobs.Truncated}, FailureCodes: []string{"worker_crash"}, Limit: 1})
	if err != nil || total != 1 || len(items) != 1 || items[0].Sequence != 1 || items[0].Result == nil || items[0].Result.Nodes != 7 || *items[0].Result.FailureCode != "worker_crash" {
		t.Fatalf("filtered page total=%d items=%+v err=%v", total, items, err)
	}
	items, total, err = store.FilteredCases(ctx, value.ID, jobs.CaseFilter{ConfigurationID: "defender-1", Offset: 1, Limit: 1})
	if err != nil || total != 4 || len(items) != 1 || items[0].Sequence != 1 {
		t.Fatalf("identity filter total=%d items=%+v err=%v", total, items, err)
	}
	items, total, err = store.FilteredCases(ctx, value.ID, jobs.CaseFilter{ConfigurationID: "attacker-2", Limit: 1})
	if err != nil || total != 1 || len(items) != 1 || items[0].Sequence != 2 || items[0].Result.Status != jobs.Truncated {
		t.Fatalf("side identity filter total=%d items=%+v err=%v", total, items, err)
	}
	// 旧 Python 成功说明允许非 JSON；读取仍保留该文本，新写入继续拒绝，不扩宽契约。
	if _, err = db.ExecContext(ctx, `UPDATE poke_runtime.battle_inference_cases SET explanation_json='legacy opaque text' WHERE job_id=$1 AND sequence_no=0`, value.ID); err != nil {
		t.Fatal(err)
	}
	read, err := store.Result(ctx, value.ID, value.Cases[0].PairID)
	if err != nil || read == nil || read.Explanation == nil || *read.Explanation != "legacy opaque text" {
		t.Fatalf("legacy explanation result=%+v err=%v", read, err)
	}
	opaque := "new invalid JSON"
	invalid := success()
	invalid.Explanation = &opaque
	if _, err = invalid.Normalize(); err == nil {
		t.Fatal("legacy read compatibility weakened new write validation")
	}
	if _, err = db.ExecContext(ctx, `DELETE FROM poke_runtime.go_job_definitions WHERE job_id=$1`, value.ID); err != nil {
		t.Fatal(err)
	}
	if _, err = db.ExecContext(ctx, `DELETE FROM poke_runtime.battle_inference_job_execution_specs WHERE job_id=$1`, value.ID); err != nil {
		t.Fatal(err)
	}
	items, total, err = store.FilteredCases(ctx, value.ID, jobs.CaseFilter{Limit: 10})
	if err != nil || total != 4 || len(items) != 4 || items[0].Result == nil || items[3].Result != nil {
		t.Fatalf("legacy-only rows total=%d items=%+v err=%v", total, items, err)
	}
	for _, filter := range []jobs.CaseFilter{{FailureCodes: []string{"unknown"}, Limit: 1}, {Statuses: []jobs.Status{jobs.Preparing}, Limit: 1}, {Offset: -1, Limit: 1}} {
		if _, _, err = store.FilteredCases(ctx, value.ID, filter); err == nil {
			t.Fatalf("invalid filter accepted: %+v", filter)
		}
	}
}
