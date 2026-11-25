package knowledge

import (
	"context"
	"database/sql"
	"errors"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

// TestLegacyExpectedSchemaUsesFixedModel 确保每张固定CSV表都有独立临时DDL，未知表明确拒绝。
func TestLegacyExpectedSchemaUsesFixedModel(t *testing.T) {
	manifest, _, err := Contract()
	if err != nil {
		t.Fatal(err)
	}
	for _, table := range manifest.Tables {
		ddl, err := expectedLegacyDDL(table)
		if err != nil || !strings.HasPrefix(ddl, "CREATE TEMP TABLE pbi_knowledge_expected (") || !strings.HasSuffix(ddl, "ON COMMIT DROP") {
			t.Fatalf("fixed temporary model unavailable for %s: %v", table.Name, err)
		}
	}
	if _, err := expectedLegacyDDL(Table{Name: "not_a_fixed_table"}); err == nil {
		t.Fatal("unknown table was accepted")
	}
}

// TestLegacyAdoptionIsExactAndNonDestructive 用真实完整CSV/PG验证默认拒绝、同数量异值拒绝、
// schema差异拒绝和全部字段匹配后的显式接管；用户记录、raw身份及历史序列必须保持不变。
func TestLegacyAdoptionIsExactAndNonDestructive(t *testing.T) {
	root := os.Getenv("PBI_KNOWLEDGE_CSV_ROOT")
	if root == "" {
		t.Skip("PBI_KNOWLEDGE_CSV_ROOT is required")
	}
	db, dsn := emptyDatabase(t)
	ctx := context.Background()
	baseline, err := Initialize(ctx, dsn, root, false)
	if err != nil {
		t.Fatal(err)
	}
	// 去掉本测试库的Go标记来构造历史状态；这里不是向用户建议删除生产标记。
	if _, err := db.Exec(`DROP TABLE poke_raw._go_knowledge_version; CREATE TABLE public.adoption_user_record(id text PRIMARY KEY,payload text NOT NULL); INSERT INTO public.adoption_user_record VALUES('stable-id','preserve user configuration')`); err != nil {
		t.Fatal(err)
	}
	var sequence, original, identity string
	if err := db.QueryRow(`SELECT last_value::text || ':' || is_called::text FROM poke_raw.abilities_id_seq`).Scan(&sequence); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`SELECT identifier FROM poke_raw.abilities WHERE id=1`).Scan(&original); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`SELECT xmin::text || ':' || ctid::text FROM poke_raw.abilities WHERE id=2`).Scan(&identity); err != nil {
		t.Fatal(err)
	}
	if _, err := Initialize(ctx, dsn, root, false); !errors.Is(err, ErrNonempty) {
		t.Fatalf("default initialization must still reject legacy data: %v", err)
	}
	verifyAdoptionCancellation(t, db, dsn, root)
	if _, err := db.Exec(`UPDATE poke_raw.abilities SET identifier='owned-mismatch' WHERE id=1`); err != nil {
		t.Fatal(err)
	}
	if _, err := AdoptLegacy(ctx, dsn, root, false); !errors.Is(err, ErrLegacyMismatch) {
		t.Fatalf("same-count changed data was accepted: %v", err)
	}
	var changed string
	if err := db.QueryRow(`SELECT identifier FROM poke_raw.abilities WHERE id=1`).Scan(&changed); err != nil || changed != "owned-mismatch" {
		t.Fatalf("rejected target was rewritten: %q err=%v", changed, err)
	}
	var marker *string
	if err := db.QueryRow(`SELECT to_regclass('poke_raw._go_knowledge_version')::text`).Scan(&marker); err != nil || marker != nil {
		t.Fatalf("failed adoption retained a marker: %v err=%v", marker, err)
	}
	if _, err := db.Exec(`UPDATE poke_raw.abilities SET identifier=$1 WHERE id=1`, original); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`ALTER TABLE poke_raw.abilities ADD COLUMN owned_extra text`); err != nil {
		t.Fatal(err)
	}
	if _, err := AdoptLegacy(ctx, dsn, root, false); !errors.Is(err, ErrLegacyMismatch) {
		t.Fatalf("changed schema was accepted: %v", err)
	}
	if _, err := db.Exec(`ALTER TABLE poke_raw.abilities DROP COLUMN owned_extra`); err != nil {
		t.Fatal(err)
	}
	adopted, err := AdoptLegacy(ctx, dsn, root, false)
	if err != nil {
		t.Fatal(err)
	}
	if !adopted.LegacyAdopted || adopted.Reused || adopted.SourceRows != baseline.SourceRows || adopted.InsertedRows != baseline.InsertedRows || len(adopted.Tables) != 177 {
		t.Fatalf("incomplete full adoption: %+v", adopted)
	}
	var afterIdentity, afterSequence, payload string
	if err := db.QueryRow(`SELECT xmin::text || ':' || ctid::text FROM poke_raw.abilities WHERE id=2`).Scan(&afterIdentity); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`SELECT last_value::text || ':' || is_called::text FROM poke_raw.abilities_id_seq`).Scan(&afterSequence); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`SELECT payload FROM public.adoption_user_record WHERE id='stable-id'`).Scan(&payload); err != nil || payload != "preserve user configuration" || identity != afterIdentity || sequence != afterSequence {
		t.Fatalf("historical state changed identity=%q/%q sequence=%q/%q payload=%q err=%v", identity, afterIdentity, sequence, afterSequence, payload, err)
	}
	replayed, err := Initialize(ctx, dsn, root, false)
	if err != nil || !replayed.Reused || !replayed.LegacyAdopted || replayed.InsertedRows != baseline.InsertedRows {
		t.Fatalf("normal initialization cannot reuse adopted knowledge: %+v err=%v", replayed, err)
	}
}

// verifyAdoptionCancellation 用本测试库的晚序表锁，确认接管已实际进入逐表核验后再取消。
// t报告失败；db/dsn是自有数据库，root是固定CSV源。返回前释放锁，取消后版本表不得残留。
func verifyAdoptionCancellation(t *testing.T, db *sql.DB, dsn, root string) {
	t.Helper()
	blocker, err := db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	defer blocker.Rollback()
	if _, err := blocker.Exec(`LOCK TABLE poke_raw.types IN SHARE ROW EXCLUSIVE MODE`); err != nil {
		t.Fatal(err)
	}
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	query := parsed.Query()
	query.Set("application_name", "pbi-legacy-adoption-cancel")
	parsed.RawQuery = query.Encode()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	// 独立连接执行接管，观察连接只读取pg_stat_activity，不注入实现内部回调。
	go func() {
		_, err := AdoptLegacy(ctx, parsed.String(), root, false)
		done <- err
	}()
	blocked := false
	deadline := time.Now().Add(45 * time.Second)
	for time.Now().Before(deadline) {
		if err := db.QueryRow(`SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='pbi-legacy-adoption-cancel' AND wait_event_type='Lock' AND query LIKE 'LOCK TABLE "poke_raw"."types" IN SHARE MODE;%')`).Scan(&blocked); err != nil {
			t.Fatal(err)
		}
		if blocked {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !blocked {
		t.Fatal("adoption did not reach the observed late-table lock")
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("running adoption was not cancelled: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("cancelled adoption did not release its transaction")
	}
	var marker *string
	if err := db.QueryRow(`SELECT to_regclass('poke_raw._go_knowledge_version')::text`).Scan(&marker); err != nil || marker != nil {
		t.Fatalf("interrupted adoption retained a version table: %v err=%v", marker, err)
	}
}
