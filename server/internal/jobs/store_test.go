package jobs_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/postgres"
	"reflect"
	"sync"
	"testing"
	"time"
)

// database 为 t 创建独占数据库，只接受显式测试 DSN，结束只删除创建成功的名字。
func database(t *testing.T) (*jobs.Store, *sql.DB) {
	t.Helper()
	dsn := os.Getenv("PBI_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_POSTGRES_DSN is required for isolated job integration")
	}
	admin, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close() })
	name := fmt.Sprintf("pbi_jobs_test_%d", time.Now().UnixNano())
	if _, err = admin.Exec("CREATE DATABASE " + name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, e := admin.Exec("DROP DATABASE " + name + " WITH(FORCE)"); e != nil {
			t.Error(e)
		}
	})
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	parsed.Path = "/" + name
	db, err := postgres.Open(context.Background(), parsed.String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	if err = postgres.Migrate(context.Background(), db); err != nil {
		t.Fatal(err)
	}
	store := jobs.New(db)
	if err = store.Migrate(context.Background()); err != nil {
		t.Fatal(err)
	}
	return store, db
}

// definition 构造指定 n 个配置的真实持久化输入；仅测试仓库生命周期，不声称执行战斗推演。
func definition(id string, n int) jobs.Definition {
	maxTurns := 100
	result := jobs.Definition{ID: id, RulesetID: "pokemon-champion", VersionGroupID: 25, Revision: "test-revision", Spec: jobs.ExecutionSpec{ContractVersion: "one-on-one-move-pool.v1", WeightAssumption: "uniform_configuration_pair", AttackerPolicy: "first-legal-action", DefenderPolicy: "uniform-random", MechanismAdmission: "supported_only", ProcessCount: 2, QueueDepth: 4, MaxNodes: 20000, MaxEdges: 80000, MaxTurns: &maxTurns}}
	for i := 0; i < n; i++ {
		result.Cases = append(result.Cases, jobs.CaseDefinition{PairID: fmt.Sprintf("pair-%03d", i), AttackerID: fmt.Sprintf("attacker-%d", i), DefenderID: "defender-1", AttackerMoves: []int{1, 2}, DefenderMoves: []int{3}, CoreRequest: json.RawMessage(`{"schema_version":1,"operations":[{"kind":"hp","base":91,"iv":31,"ev":0,"level":50}]}`)})
	}
	return result
}

// success 返回含超过 int64 分母的守恒精确概率，证明存储路径不经过浮点。
func success() jobs.Result {
	return jobs.Result{Status: jobs.Succeeded, AttackerWin: &jobs.Fraction{"1", "100000000000000000000000000003"}, DefenderWin: &jobs.Fraction{"100000000000000000000000000002", "100000000000000000000000000003"}, Draw: &jobs.Fraction{"0", "1"}, ExpectedTurns: &jobs.ExpectedTurns{Kind: "infinite"}, Nodes: 23, Edges: 41, Budget: 64}
}

// TestPersistentLeaseRecoveryAndIdempotentResult 验证领取、过期恢复、旧owner拒绝、精确结果与计数幂等。
func TestPersistentLeaseRecoveryAndIdempotentResult(t *testing.T) {
	store, db := database(t)
	ctx := context.Background()
	now := time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC)
	def := definition("fixed-one-on-one-job-recovery", 2)
	if created, err := store.Create(ctx, def, now); err != nil || !created {
		t.Fatalf("create=%v err=%v", created, err)
	}
	if created, err := store.Create(ctx, def, now.Add(time.Second)); err != nil || created {
		t.Fatalf("retry create=%v err=%v", created, err)
	}
	changed := def
	changed.Revision = "other"
	if _, err := store.Create(ctx, changed, now); !errors.Is(err, jobs.ErrConflict) {
		t.Fatalf("ID reuse err=%v", err)
	}
	// 新仓库实例从 DB 恢复全部冻结数据，不能依靠进程内注册表。
	store = jobs.New(db)
	restored, err := store.Definition(ctx, def.ID)
	if err != nil || !reflect.DeepEqual(restored, def) {
		t.Fatalf("restore differs err=%v got=%+v", err, restored)
	}
	if job, err := store.ClaimJob(ctx, "coordinator-a", "wrong", now, time.Minute); err != nil || job != nil {
		t.Fatalf("revision claim job=%+v err=%v", job, err)
	}
	job, err := store.ClaimJob(ctx, "coordinator-a", def.Revision, now, time.Minute)
	if err != nil || job == nil || job.Status != jobs.Preparing {
		t.Fatalf("claim job=%+v err=%v", job, err)
	}
	cases, err := store.ClaimCases(ctx, def.ID, "worker-a", def.Revision, now, 10*time.Second, 1)
	if err != nil || len(cases) != 1 {
		t.Fatalf("claim cases=%v err=%v", cases, err)
	}
	if err = store.HeartbeatCases(ctx, def.ID, "wrong", []string{cases[0].Definition.PairID}, now.Add(time.Second), time.Minute); !errors.Is(err, jobs.ErrLeaseConflict) {
		t.Fatalf("wrong heartbeat err=%v", err)
	}
	// 续租批次包含缺失对象必须整批回滚，不能仅延长已匹配对象。
	if err = store.HeartbeatCases(ctx, def.ID, "worker-a", []string{cases[0].Definition.PairID, "missing"}, now.Add(time.Second), time.Minute); !errors.Is(err, jobs.ErrLeaseConflict) {
		t.Fatalf("partial heartbeat err=%v", err)
	}
	recovered, err := store.ClaimCases(ctx, def.ID, "worker-b", def.Revision, now.Add(11*time.Second), time.Minute, 1)
	if err != nil || len(recovered) != 1 || recovered[0].Attempts != 2 {
		t.Fatalf("recovery cases=%+v err=%v", recovered, err)
	}
	snapshot, err := store.Get(ctx, def.ID)
	if err != nil || snapshot.Counts.Pending != 1 || snapshot.Counts.Running != 1 {
		t.Fatalf("recovery counted twice: %+v err=%v", snapshot.Counts, err)
	}
	if _, err = store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "worker-a", def.Revision, now.Add(12*time.Second), success()); !errors.Is(err, jobs.ErrLeaseConflict) {
		t.Fatalf("stale owner err=%v", err)
	}
	progress := jobs.Progress{Phase: "building_graph", ObservedNodes: 20, ObservedEdges: 35, ExpandedNodes: 15, Frontier: 5, ActionPairsCompleted: 1, ActionPairsTotal: 3}
	if applied, e := store.RecordProgress(ctx, def.ID, cases[0].Definition.PairID, "worker-b", def.Revision, now.Add(12*time.Second), progress); e != nil || !applied {
		t.Fatalf("progress=%v err=%v", applied, e)
	}
	if applied, e := store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "worker-b", def.Revision, now.Add(13*time.Second), success()); e != nil || !applied {
		t.Fatalf("result=%v err=%v", applied, e)
	}
	if applied, e := store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "worker-b", def.Revision, now.Add(14*time.Second), success()); e != nil || applied {
		t.Fatalf("replay result=%v err=%v", applied, e)
	}
	conflict := success()
	conflict.Nodes++
	if _, err = store.RecordResult(ctx, def.ID, cases[0].Definition.PairID, "worker-b", def.Revision, now.Add(14*time.Second), conflict); !errors.Is(err, jobs.ErrConflict) {
		t.Fatalf("conflicting result err=%v", err)
	}
	result, err := store.Result(ctx, def.ID, cases[0].Definition.PairID)
	expected, _ := success().Normalize()
	if err != nil || result == nil || !reflect.DeepEqual(*result, expected) {
		t.Fatalf("exact result differs result=%+v err=%v", result, err)
	}
	snapshot, err = store.Get(ctx, def.ID)
	if err != nil || snapshot.Counts.Succeeded != 1 || snapshot.Counts.Nodes != 23 || snapshot.Counts.Running != 0 {
		t.Fatalf("result counted twice %+v err=%v", snapshot.Counts, err)
	}
	if _, err = store.Finalize(ctx, def.ID, now); !errors.Is(err, jobs.ErrTransition) {
		t.Fatalf("premature finalization err=%v", err)
	}
}

// TestConcurrentClaimsCancellationAndFinalization 验证多执行者无重复领取、有效lease宽限和取消守恒。
func TestConcurrentClaimsCancellationAndFinalization(t *testing.T) {
	store, _ := database(t)
	ctx := context.Background()
	now := time.Now().UTC()
	def := definition("configuration-space-cancel", 12)
	if _, err := store.Create(ctx, def, now); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimJob(ctx, "coordinator", def.Revision, now, time.Minute); err != nil {
		t.Fatal(err)
	}
	var wait sync.WaitGroup
	var mutex sync.Mutex
	seen := map[string]string{}
	failures := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wait.Add(1)
		go func(worker int) {
			defer wait.Done()
			owner := fmt.Sprintf("worker-%d", worker)
			cases, err := store.ClaimCases(ctx, def.ID, owner, def.Revision, now, 10*time.Second, 2)
			if err != nil {
				failures <- err
				return
			}
			mutex.Lock()
			defer mutex.Unlock()
			for _, item := range cases {
				if prior := seen[item.Definition.PairID]; prior != "" {
					failures <- fmt.Errorf("case %s claimed twice by %s and %s", item.Definition.PairID, prior, owner)
				}
				seen[item.Definition.PairID] = owner
			}
		}(i)
	}
	wait.Wait()
	close(failures)
	for err := range failures {
		t.Error(err)
	}
	if len(seen) != 12 {
		t.Fatalf("claimed %d cases", len(seen))
	}
	if _, err := store.RequestCancel(ctx, def.ID, now.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ClaimCases(ctx, def.ID, "new", def.Revision, now.Add(time.Second), time.Minute, 1); !errors.Is(err, jobs.ErrTransition) {
		t.Fatalf("claim after cancel err=%v", err)
	}
	if count, err := store.CancelUnclaimed(ctx, def.ID, now.Add(2*time.Second)); err != nil || count != 0 {
		t.Fatalf("cancelled active leases count=%d err=%v", count, err)
	}
	if count, err := store.CancelUnclaimed(ctx, def.ID, now.Add(11*time.Second)); err != nil || count != 12 {
		t.Fatalf("cancel expired count=%d err=%v", count, err)
	}
	job, err := store.Finalize(ctx, def.ID, now.Add(12*time.Second))
	if err != nil || job.Status != jobs.Cancelled || job.Lease != nil || job.Counts.Cancelled != 12 || job.Counts.Pending != 0 || job.Counts.Running != 0 {
		t.Fatalf("finalized job=%+v err=%v", job, err)
	}
	replay, err := store.Finalize(ctx, def.ID, now.Add(time.Hour))
	if err != nil || !replay.CompletedAt.Equal(*job.CompletedAt) {
		t.Fatalf("finalize replay changed finish time err=%v", err)
	}
	page, total, err := store.Cases(ctx, def.ID, []jobs.Status{jobs.Cancelled}, 4, 3)
	if err != nil || total != 12 || len(page) != 3 || page[0].Sequence != 4 || page[2].Sequence != 6 {
		t.Fatalf("stable case page len=%d total=%d err=%v", len(page), total, err)
	}
}

// TestCoordinatorReclaimAndFilteredJobPage 验证coordinator过期恢复、终态禁止领取与类型过滤顺序。
func TestCoordinatorReclaimAndFilteredJobPage(t *testing.T) {
	store, _ := database(t)
	ctx := context.Background()
	now := time.Now().UTC()
	for i, id := range []string{"fixed-one-on-one-job-a", "configuration-space-a", "fixed-one-on-one-job-b"} {
		if _, err := store.Create(ctx, definition(id, 1), now.Add(time.Duration(i)*time.Second)); err != nil {
			t.Fatal(err)
		}
	}
	page, err := store.List(ctx, nil, false, "fixed-one-on-one", 0, 2)
	if err != nil || len(page) != 2 || page[0].ID != "fixed-one-on-one-job-b" || page[1].ID != "fixed-one-on-one-job-a" {
		t.Fatalf("filtered page=%+v err=%v", page, err)
	}
	job, err := store.ClaimJob(ctx, "old", "test-revision", now, 10*time.Second)
	if err != nil || job == nil {
		t.Fatalf("claim err=%v", err)
	}
	if err = store.HeartbeatJob(ctx, job.ID, "other", now.Add(time.Second), time.Minute); !errors.Is(err, jobs.ErrLeaseConflict) {
		t.Fatalf("wrong coordinator heartbeat err=%v", err)
	}
	reclaimed, err := store.ClaimJob(ctx, "new", "test-revision", now.Add(11*time.Second), time.Minute)
	if err != nil || reclaimed == nil || reclaimed.ID != job.ID || reclaimed.Attempts != 2 || reclaimed.FailureCode == nil || *reclaimed.FailureCode != "worker_crash" {
		t.Fatalf("coordinator recovery=%+v err=%v", reclaimed, err)
	}
	if err = store.HeartbeatJob(ctx, job.ID, "old", now.Add(12*time.Second), time.Minute); !errors.Is(err, jobs.ErrLeaseConflict) {
		t.Fatalf("old coordinator revived err=%v", err)
	}
}
