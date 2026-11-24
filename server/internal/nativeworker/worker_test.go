package nativeworker_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"pokemonbattleinference/server/internal/corebridge"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/nativeworker"
	"pokemonbattleinference/server/internal/postgres"
	"syscall"
	"testing"
	"time"
)

// database 为 t 创建真实独占 PG 库；只接受显式测试 DSN/原生二进制，结束仅删除创建成功的名字。
func database(t *testing.T) (*jobs.Store, *sql.DB, nativeworker.Options) {
	t.Helper()
	dsn, executable := os.Getenv("PBI_TEST_POSTGRES_DSN"), os.Getenv("PBI_TEST_CORE_WORKER")
	if dsn == "" || executable == "" {
		t.Skip("PBI_TEST_POSTGRES_DSN and PBI_TEST_CORE_WORKER are required for real native worker acceptance")
	}
	admin, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close() })
	name := fmt.Sprintf("pbi_native_test_%d", time.Now().UnixNano())
	if _, err = admin.Exec("CREATE DATABASE " + name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec("DROP DATABASE " + name + " WITH(FORCE)"); err != nil {
			t.Error(err)
		}
	})
	endpoint, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	endpoint.Path = "/" + name
	db, err := postgres.Open(context.Background(), endpoint.String())
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
	return store, db, nativeworker.Options{Owner: "native-owner-a", Revision: corebridge.EngineVersion(), EngineVersion: corebridge.EngineVersion(),
		Executable: executable, LeaseDuration: 2 * time.Second, HeartbeatInterval: 400 * time.Millisecond,
		PollInterval: 20 * time.Millisecond, DatabaseTimeout: 500 * time.Millisecond}
}

// TestDaemonExecutableConsumesPersistentJob 通过真正 daemon 可执行文件而非测试内调用领取任务，完成后检查空闲轮询及 SIGTERM 回收。
func TestDaemonExecutableConsumesPersistentJob(t *testing.T) {
	store, db, options := database(t)
	executable := os.Getenv("PBI_TEST_WORKER_DAEMON")
	if executable == "" {
		t.Skip("PBI_TEST_WORKER_DAEMON is required for actual daemon integration")
	}
	var databaseName string
	if err := db.QueryRow("SELECT current_database()").Scan(&databaseName); err != nil {
		t.Fatal(err)
	}
	endpoint, err := url.Parse(os.Getenv("PBI_TEST_POSTGRES_DSN"))
	if err != nil {
		t.Fatal(err)
	}
	endpoint.Path = "/" + databaseName
	value := definition("fixed-one-on-one-job-native-daemon", options.Revision, 3)
	create(t, store, value)
	command := exec.Command(executable, "-owner", "daemon-executable-owner", "-revision", options.Revision,
		"-native-executable", options.Executable, "-lease", "2s", "-heartbeat", "400ms", "-poll", "20ms", "-database-timeout", "500ms")
	command.Env = append(os.Environ(), "PBI_POSTGRES_DSN="+endpoint.String())
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- command.Wait() }()
	reaped := false
	// 任一断言失败也必须回收该确切子进程，不留下访问已删除测试库的 daemon。
	defer func() {
		if !reaped {
			_ = command.Process.Kill()
			<-done
		}
	}()
	completed := waitJob(t, store, value.ID, func(job jobs.Job) bool { return job.Status == jobs.Succeeded })
	if completed.Counts.Succeeded != 3 || completed.Attempts != 1 {
		t.Fatalf("daemon result=%+v", completed)
	}
	select {
	case err := <-done:
		reaped = true
		t.Fatalf("daemon exited before shutdown: %v", err)
	default:
	}
	if err := command.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		reaped = true
		if err != nil {
			t.Fatalf("daemon shutdown failed: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("daemon did not stop after SIGTERM")
	}
}

// graphRequest 是会真实交给原生 Core 的三节点显式图，根一步按 1/3、2/3 到攻守胜终局。
func graphRequest(observer string) json.RawMessage {
	return json.RawMessage(fmt.Sprintf(`{"schema_version":1,"operations":[{"kind":"graph","nodes":[{"outcome":"non-terminal","cycle_resolution":"solve-absorption-probability"},{"outcome":"attacker-win","cycle_resolution":"declare-draw"},{"outcome":"defender-win","cycle_resolution":"declare-draw"}],"edges":[{"source":0,"target":1,"probability":{"numerator":"1","denominator":"3"}},{"source":0,"target":2,"probability":{"numerator":"2","denominator":"3"}}],"root":0,"observer":%q,"truncations":[]}]}`, observer))
}

// definition 创建 n 个真实冻结图请求；仅测试现已支持的显式图任务，不冒充完整宝可梦回合器。
func definition(id, revision string, n int) jobs.Definition {
	result := jobs.Definition{ID: id, RulesetID: "pokemon-champion", VersionGroupID: 25, Revision: revision,
		Spec: jobs.ExecutionSpec{ContractVersion: "one-on-one-move-pool.v1", WeightAssumption: "uniform_configuration_pair",
			AttackerPolicy: "first-legal-action", DefenderPolicy: "uniform-random", MechanismAdmission: "supported_only",
			ProcessCount: 1, QueueDepth: 2, MaxNodes: 100, MaxEdges: 200}}
	for index := 0; index < n; index++ {
		observer := "attacker"
		if index%2 == 1 {
			observer = "defender"
		}
		result.Cases = append(result.Cases, jobs.CaseDefinition{PairID: fmt.Sprintf("pair-%03d", index), AttackerID: "attack", DefenderID: "defend",
			AttackerMoves: []int{1}, DefenderMoves: []int{2}, CoreRequest: graphRequest(observer)})
	}
	return result
}

// create 在真实事务中提交冻结定义，并断言相同请求幂等，不通过内存队列塞入工作。
func create(t *testing.T, store *jobs.Store, value jobs.Definition) {
	t.Helper()
	if created, err := store.Create(context.Background(), value, time.Now().UTC()); err != nil || !created {
		t.Fatalf("create=%v err=%v", created, err)
	}
	if created, err := store.Create(context.Background(), value, time.Now().UTC()); err != nil || created {
		t.Fatalf("retry create=%v err=%v", created, err)
	}
}

// workerFor 验证 options 创建实际调度器，构造本身不得修改任务或启动子进程。
func workerFor(t *testing.T, store *jobs.Store, options nativeworker.Options) *nativeworker.Worker {
	t.Helper()
	worker, err := nativeworker.New(store, options)
	if err != nil {
		t.Fatal(err)
	}
	return worker
}

// waitJob 使用真实 PG 轮询 predicate 指定的可观察阶段；timeout 只界定测试，不改变生产时钟或租约。
func waitJob(t *testing.T, store *jobs.Store, id string, predicate func(jobs.Job) bool) jobs.Job {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		item, err := store.Get(context.Background(), id)
		if err != nil {
			t.Fatal(err)
		}
		if predicate(item) {
			return item
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("job did not reach the expected persistent state")
	return jobs.Job{}
}

// TestNativeJobPersistsExactResultAndRestart 实际执行子进程，比较攻守视角、版本档案、进度和新实例重试幂等。
func TestNativeJobPersistsExactResultAndRestart(t *testing.T) {
	store, db, options := database(t)
	value := definition("fixed-one-on-one-job-native-exact", options.Revision, 3)
	value.Spec.ProcessCount = 2
	create(t, store, value)
	worker := workerFor(t, store, options)
	if worked, err := worker.RunOnce(context.Background()); err != nil || !worked {
		t.Fatalf("worked=%v err=%v", worked, err)
	}
	job, err := store.Get(context.Background(), value.ID)
	if err != nil {
		t.Fatal(err)
	}
	if job.Status != jobs.Succeeded || job.Counts.Succeeded != 3 || job.Counts.Pending != 0 || job.Counts.Running != 0 || job.Counts.Nodes != 9 || job.Counts.Edges != 6 || job.Counts.Budget != 15 {
		t.Fatalf("unexpected persisted job: %+v", job)
	}
	for _, item := range value.Cases {
		result, err := jobs.New(db).Result(context.Background(), value.ID, item.PairID)
		if err != nil || result == nil {
			t.Fatalf("result=%v err=%v", result, err)
		}
		if *result.AttackerWin != (jobs.Fraction{Numerator: "1", Denominator: "3"}) || *result.DefenderWin != (jobs.Fraction{Numerator: "2", Denominator: "3"}) || *result.Draw != (jobs.Fraction{Numerator: "0", Denominator: "1"}) || result.ExpectedTurns.Kind != "finite" || *result.ExpectedTurns.Value != (jobs.Fraction{Numerator: "1", Denominator: "1"}) {
			t.Fatalf("native result changed exact probabilities: %+v", result)
		}
		if result.Explanation == nil || !json.Valid([]byte(*result.Explanation)) {
			t.Fatal("native version metadata is missing")
		}
	}
	options.Owner = "native-owner-after-restart"
	if worked, err := workerFor(t, jobs.New(db), options).RunOnce(context.Background()); err != nil || worked {
		t.Fatalf("terminal job was repeated: worked=%v err=%v", worked, err)
	}
	again, err := store.Get(context.Background(), value.ID)
	if err != nil || again.Attempts != 1 || !again.CompletedAt.Equal(*job.CompletedAt) {
		t.Fatalf("terminal state changed: %+v err=%v", again, err)
	}
}

// TestDaemonStopRetainsLeasesAndRecovers 停机取消回收实际子进程但不伪造用户取消；新owner恢复未确认工作并保留已完成项。
func TestDaemonStopRetainsLeasesAndRecovers(t *testing.T) {
	store, _, options := database(t)
	value := definition("fixed-one-on-one-job-native-recovery", options.Revision, 48)
	create(t, store, value)
	ctx, cancel := context.WithCancel(context.Background())
	finished := make(chan error, 1)
	worker := workerFor(t, store, options)
	go func() { _, err := worker.RunOnce(ctx); finished <- err }()
	before := waitJob(t, store, value.ID, func(job jobs.Job) bool { return job.Counts.Succeeded > 0 && job.Counts.Succeeded < job.Counts.Total })
	cancel()
	if err := <-finished; !errors.Is(err, context.Canceled) {
		t.Fatalf("shutdown error=%v", err)
	}
	stopped, err := store.Get(context.Background(), value.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stopped.Counts.Cancelled != 0 || stopped.Counts.Succeeded < before.Counts.Succeeded {
		t.Fatalf("shutdown lost confirmed work or invented cancellation: %+v", stopped)
	}
	waitJob(t, store, value.ID, func(job jobs.Job) bool { return job.Lease != nil && !job.Lease.ExpiresAt.After(time.Now().UTC()) })
	options.Owner = "native-recovery-owner"
	if worked, err := workerFor(t, store, options).RunOnce(context.Background()); err != nil || !worked {
		t.Fatalf("recovery worked=%v err=%v", worked, err)
	}
	recovered, err := store.Get(context.Background(), value.ID)
	if err != nil || recovered.Status != jobs.Succeeded || recovered.Counts.Succeeded != 48 || recovered.Counts.Cancelled != 0 || recovered.Attempts != 2 {
		t.Fatalf("recovery=%+v err=%v", recovered, err)
	}
}

// TestUserCancellationStopsQueuedAndActiveWork 用户取消与停机不同：停止后续领取，杀死/回收活跃子进程并派生稳定取消终态。
func TestUserCancellationStopsQueuedAndActiveWork(t *testing.T) {
	store, _, options := database(t)
	value := definition("fixed-one-on-one-job-native-cancel", options.Revision, 48)
	create(t, store, value)
	finished := make(chan error, 1)
	worker := workerFor(t, store, options)
	go func() { _, err := worker.RunOnce(context.Background()); finished <- err }()
	waitJob(t, store, value.ID, func(job jobs.Job) bool { return job.Counts.Running > 0 })
	if _, err := store.RequestCancel(context.Background(), value.ID, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	if err := <-finished; err != nil {
		t.Fatal(err)
	}
	job, err := store.Get(context.Background(), value.ID)
	if err != nil || job.Status != jobs.Cancelled || job.Counts.Cancelled == 0 || job.Counts.Pending != 0 || job.Counts.Running != 0 || job.Counts.Cancelled+job.Counts.Succeeded != 48 {
		t.Fatalf("cancelled job=%+v err=%v", job, err)
	}
}

// TestNativeRefusalAndIncompleteGraphRemainFailures 真实不支持/截断不得变成成功或零胜率，并拒绝错误原生版本。
func TestNativeRefusalAndIncompleteGraphRemainFailures(t *testing.T) {
	store, _, options := database(t)
	value := definition("fixed-one-on-one-job-native-failures", options.Revision, 2)
	value.Cases[0].CoreRequest = json.RawMessage(`{"schema_version":1,"operations":[{"kind":"hp","base":91,"iv":31,"ev":0,"level":50}]}`)
	value.Cases[1].CoreRequest = json.RawMessage(`{"schema_version":1,"operations":[{"kind":"graph","observer":"attacker","nodes":[{"outcome":"unknown","cycle_resolution":"declare-draw"}],"edges":[],"root":0,"truncations":["max-nodes"]}]}`)
	create(t, store, value)
	if _, err := workerFor(t, store, options).RunOnce(context.Background()); err != nil {
		t.Fatal(err)
	}
	first, err := store.Result(context.Background(), value.ID, value.Cases[0].PairID)
	if err != nil || first == nil || first.Status != jobs.Failed || *first.FailureCode != "invalid_configuration" || first.AttackerWin != nil {
		t.Fatalf("invalid result=%+v err=%v", first, err)
	}
	second, err := store.Result(context.Background(), value.ID, value.Cases[1].PairID)
	if err != nil || second == nil || second.Status != jobs.Truncated || *second.FailureCode != "graph_node_limit" || second.Draw != nil {
		t.Fatalf("truncated result=%+v err=%v", second, err)
	}
	mismatch := definition("fixed-one-on-one-job-native-version", options.Revision, 1)
	create(t, store, mismatch)
	options.EngineVersion = "different-engine"
	if _, err := workerFor(t, store, options).RunOnce(context.Background()); err != nil {
		t.Fatal(err)
	}
	result, err := store.Result(context.Background(), mismatch.ID, mismatch.Cases[0].PairID)
	if err != nil || result == nil || result.Status != jobs.Failed || *result.FailureCode != "calculation_revision_mismatch" {
		t.Fatalf("version result=%+v err=%v", result, err)
	}
}
