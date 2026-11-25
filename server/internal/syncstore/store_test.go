package syncstore_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	_ "github.com/jackc/pgx/v5/stdlib"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"pokemonbattleinference/server/internal/syncapi"
	"pokemonbattleinference/server/internal/syncmodels"
	"pokemonbattleinference/server/internal/syncstore"
	"sync"
	"testing"
	"time"
)

// database 为 t 创建真实 PostgreSQL 独立 schema；只使用显式测试 DSN，缺少时不访问任何数据库。
// 返回仓库与连接池；t.Cleanup 仅删除本次生成的 schema，绝不清理外部表。
func database(t *testing.T) (*syncstore.Store, *sql.DB) {
	t.Helper()
	dsn := os.Getenv("PBI_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_POSTGRES_DSN is required for isolated PostgreSQL tests")
	}
	base, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { base.Close() })
	schema := fmt.Sprintf("pbi_sync_test_%d", time.Now().UnixNano())
	if _, err = base.Exec("CREATE SCHEMA " + schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, e := base.Exec("DROP SCHEMA " + schema + " CASCADE"); e != nil {
			t.Error(e)
		}
	})
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	query := parsed.Query()
	query.Set("search_path", schema)
	parsed.RawQuery = query.Encode()
	db, err := sql.Open("pgx", parsed.String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	store := syncstore.New(db)
	if err = store.Migrate(context.Background()); err != nil {
		t.Fatal(err)
	}
	return store, db
}

// operation 以 n 生成稳定测试 UUID，并指定 entity/revision/name；返回完整不可变用户快照。
func operation(n int, entity string, revision int64, name string) syncmodels.Operation {
	configuration, _ := json.Marshal(struct {
		ID    string `json:"id"`
		Name  string `json:"name"`
		Large int64  `json:"large"`
	}{entity, name, 9007199254740993})
	return syncmodels.Operation{SchemaVersion: 1, OperationID: fmt.Sprintf("00000000-0000-4000-8000-%012d", n), EntityID: entity, BaseRevision: revision, LocalSequence: int64(n), Kind: "upsert", Configuration: configuration, KnowledgeVersion: "knowledge-1", EngineVersion: "0.4.0"}
}

// TestPersistentRetryConflictDeletionAndTenantIsolation 用两个设备序列验证持久化幂等、删除传播和用户隔离。
func TestPersistentRetryConflictDeletionAndTenantIsolation(t *testing.T) {
	store, db := database(t)
	ctx := context.Background()
	entity := "11111111-1111-4111-8111-111111111111"
	first := operation(1, entity, 0, "device A initial \x00 preserved")
	accepted, err := store.Apply(ctx, "alice", first)
	if err != nil {
		t.Fatal(err)
	}
	if accepted.Status != "accepted" || accepted.Current.Revision != 1 {
		t.Fatalf("unexpected initial result: %+v", accepted)
	}
	// 重新构造仓库模拟进程重启；丢失响应后的同请求重试必须返回原回执，不多生成变更。
	restarted := syncstore.New(db)
	retry, err := restarted.Apply(ctx, "alice", first)
	if err != nil {
		t.Fatal(err)
	}
	a, _ := json.Marshal(accepted)
	b, _ := json.Marshal(retry)
	if !bytes.Equal(a, b) {
		t.Fatalf("retry changed receipt: %s %s", a, b)
	}
	changed := first
	changed.LocalSequence++
	if _, err = restarted.Apply(ctx, "alice", changed); !errors.Is(err, syncstore.ErrOperationReuse) {
		t.Fatalf("operation reuse was accepted: %v", err)
	}
	// 双设备从同 revision 离线修改：先提交者获胜，后提交者保留完整远端作为冲突，不静默覆盖。
	editA := operation(2, entity, 1, "device A offline edit")
	editB := operation(3, entity, 1, "device B offline edit")
	aResult, err := store.Apply(ctx, "alice", editA)
	if err != nil {
		t.Fatal(err)
	}
	bResult, err := store.Apply(ctx, "alice", editB)
	if err != nil {
		t.Fatal(err)
	}
	if aResult.Status != "accepted" || bResult.Status != "conflict" || bResult.Current.Revision != 2 {
		t.Fatalf("missing conflict: %+v %+v", aResult, bResult)
	}
	// 人工选择 B 内容后用新 operationId 和远端 revision 恢复，两个设备拉取同一完整结果。
	resolved := operation(4, entity, bResult.Current.Revision, "device B offline edit")
	if _, err = store.Apply(ctx, "alice", resolved); err != nil {
		t.Fatal(err)
	}
	deletion := operation(5, entity, 3, "device B offline edit")
	deletion.Kind = "delete"
	if _, err = store.Apply(ctx, "alice", deletion); err != nil {
		t.Fatal(err)
	}
	page, err := store.Changes(ctx, "alice", 0, 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Changes) != 2 || !page.HasMore || page.NextCursor != 2 {
		t.Fatalf("invalid first page: %+v", page)
	}
	last, err := store.Changes(ctx, "alice", page.NextCursor, 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(last.Changes) != 2 || last.HasMore || last.NextCursor != 4 || !last.Changes[1].Deleted {
		t.Fatalf("deletion missing: %+v", last)
	}
	if !bytes.Contains(last.Changes[1].Configuration, []byte("9007199254740993")) {
		t.Fatal("integer precision was lost during canonicalization")
	}
	other, err := store.Changes(ctx, "bob", 0, 100)
	if err != nil || len(other.Changes) != 0 {
		t.Fatalf("tenant data leaked: %+v %v", other, err)
	}
	if result, e := store.Apply(ctx, "bob", first); e != nil || result.Current.Revision != 1 {
		t.Fatalf("user operation namespace leaked: %+v %v", result, e)
	}
	// 旧冲突请求重试仍返回当时的 revision 2，不受后续人工恢复和删除改变。
	conflictRetry, err := restarted.Apply(ctx, "alice", editB)
	if err != nil || conflictRetry.Current.Revision != 2 {
		t.Fatalf("conflict receipt not stable: %+v %v", conflictRetry, err)
	}
}

// TestConcurrentCommitCursorsNoLoss 用独立连接并发提交不同实体，验证游标按提交锁顺序分配且增量无洞。
func TestConcurrentCommitCursorsNoLoss(t *testing.T) {
	store, _ := database(t)
	const count = 24
	var group sync.WaitGroup
	failures := make(chan error, count)
	for i := 1; i <= count; i++ {
		group.Add(1)
		go func(n int) {
			defer group.Done()
			entity := fmt.Sprintf("22222222-2222-4222-8222-%012d", n)
			_, err := store.Apply(context.Background(), "concurrent", operation(n, entity, 0, "parallel"))
			failures <- err
		}(i)
	}
	group.Wait()
	close(failures)
	for err := range failures {
		if err != nil {
			t.Fatal(err)
		}
	}
	cursor := int64(0)
	total := 0
	for {
		page, err := store.Changes(context.Background(), "concurrent", cursor, 3)
		if err != nil {
			t.Fatal(err)
		}
		for _, entry := range page.Changes {
			cursor++
			if entry.Revision != cursor {
				t.Fatalf("cursor gap: got %d want %d", entry.Revision, cursor)
			}
			total++
		}
		if !page.HasMore {
			break
		}
	}
	if total != count {
		t.Fatalf("lost committed changes: %d", total)
	}
}

// TestHTTPIdentityAndProtocol 使用真实 PG handler 检验未认证拒绝、HTTP 幂等和有界分页。
func TestHTTPIdentityAndProtocol(t *testing.T) {
	store, _ := database(t)
	server := httptest.NewServer(syncapi.NewHandler(store, func(r *http.Request) (string, error) {
		user := r.Header.Get("X-Pokeop-User")
		if user == "" {
			return "", errors.New("missing identity")
		}
		return user, nil
	}))
	defer server.Close()
	response, err := http.Get(server.URL + "?after=0")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 401 {
		t.Fatal("missing identity accepted")
	}
	op := operation(1, "33333333-3333-4333-8333-333333333333", 0, "HTTP real PG")
	body, _ := json.Marshal(op)
	for i := 0; i < 2; i++ {
		request, _ := http.NewRequest("POST", server.URL, bytes.NewReader(body))
		request.Header.Set("X-Pokeop-User", "http-user")
		response, err = http.DefaultClient.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		var result syncmodels.Result
		err = json.NewDecoder(response.Body).Decode(&result)
		response.Body.Close()
		if err != nil || response.StatusCode != 200 || result.Current.Revision != 1 {
			t.Fatalf("HTTP submit failed: %+v %v", result, err)
		}
	}
	request, _ := http.NewRequest("GET", server.URL+"?after=0&limit=201", nil)
	request.Header.Set("X-Pokeop-User", "http-user")
	response, err = http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 400 {
		t.Fatal("invalid page limit accepted")
	}
}

// TestServeSwiftIntegration 仅在显式指定监听地址时运行真实 PG 同步服务器，供两个 Swift SQLite 客户端验收。
// t 持有独立 schema 生命周期；测试结束或 180 秒超时都会关闭 HTTP 和清理测试表。
func TestServeSwiftIntegration(t *testing.T) {
	address := os.Getenv("PBI_SYNC_TEST_SERVE_ADDR")
	if address == "" {
		t.Skip("PBI_SYNC_TEST_SERVE_ADDR is required for Swift integration server")
	}
	store, _ := database(t)
	done := make(chan struct{})
	var once sync.Once
	mux := http.NewServeMux()
	mux.Handle("/v1/sync", syncapi.NewHandler(store, func(r *http.Request) (string, error) { return r.Header.Get("X-Pokeop-User"), nil }))
	mux.HandleFunc("POST /__test_shutdown", func(w http.ResponseWriter, r *http.Request) { once.Do(func() { close(done) }); w.WriteHeader(204) })
	server := &http.Server{Addr: address, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	defer server.Close()
	failure := make(chan error, 1)
	go func() { failure <- server.ListenAndServe() }()
	select {
	case err := <-failure:
		t.Fatal(err)
	case <-done:
	case <-time.After(180 * time.Second):
		t.Fatal("Swift integration server timed out")
	}
}
