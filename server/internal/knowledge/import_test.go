package knowledge

import (
	"context"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/postgres"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// TestCSVLegacyTypeConversion 对照原 DAO 的空整数字段、空布尔及文本语义，并验证 header 映射。
func TestCSVLegacyTypeConversion(t *testing.T) {
	path := filepath.Join(t.TempDir(), "typed.csv")
	if err := os.WriteFile(path, []byte("text,flag,count\n\"中文,逗号\",yes,42\n,,\nvalue,0,-3\n \"unquoted quote\",yes,7\n"), 0600); err != nil {
		t.Fatal(err)
	}
	table := Table{Name: "test", Columns: []Column{{"count", Integer}, {"flag", Boolean}, {"text", Text}, {"missing", Integer}}}
	source, err := openRows(path, table)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	want := [][]any{{int64(42), true, "中文,逗号", int64(0)}, {int64(0), false, "", int64(0)}, {int64(-3), false, "value", int64(0)}, {int64(7), true, " \"unquoted quote\"", int64(0)}}
	for index, expected := range want {
		if !source.Next() {
			t.Fatalf("row %d unavailable: %v", index, source.Err())
		}
		actual, err := source.Values()
		if err != nil || !reflect.DeepEqual(actual, expected) {
			t.Fatalf("row %d got=%v want=%v err=%v", index, actual, expected, err)
		}
	}
	if source.Next() || source.Err() != nil || source.rows != 4 {
		t.Fatalf("EOF/count differs rows=%d err=%v", source.rows, source.Err())
	}
}

// TestManifestAndEarlyIntegrityFailure 确认固定来源/许可摘要，以及源文件缺失先于数据库连接拒绝。
func TestManifestAndEarlyIntegrityFailure(t *testing.T) {
	manifest, version, err := Contract()
	if err != nil {
		t.Fatal(err)
	}
	if manifest.SourceCommit != "1567d53073a069b6c96e1c393c5c490f602e3ab5" || len(manifest.Tables) != 177 || manifest.RawTableCount != 179 || !strings.HasPrefix(version, "pg-pokeapi-1567d53073a0-") {
		t.Fatalf("fixed manifest differs: %+v", manifest)
	}
	if _, err = Initialize(context.Background(), "invalid-dsn", t.TempDir(), false); err == nil || !strings.Contains(err.Error(), "CSV source unavailable") {
		t.Fatalf("source integrity was not checked first: %v", err)
	}
	if len(licenseText) < 1000 || !strings.Contains(string(licenseText), "PokéAPI") {
		t.Fatal("complete source license is missing")
	}
}

// TestFullFixedCSVPostgres 导入或复用本次维护脚本自有 PG，全量真实资料通过原八个 MV 查询。
// 不删除外部 schema；PBI_TEST_KNOWLEDGE_DSN 只能指向可丢弃的测试库。
func TestFullFixedCSVPostgres(t *testing.T) {
	dsn, root := os.Getenv("PBI_TEST_KNOWLEDGE_DSN"), os.Getenv("PBI_KNOWLEDGE_CSV_ROOT")
	if dsn == "" || root == "" {
		t.Skip("PBI_TEST_KNOWLEDGE_DSN and PBI_KNOWLEDGE_CSV_ROOT are required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	report, err := Initialize(ctx, dsn, root, false)
	if err != nil {
		t.Fatal(err)
	}
	if report.RawTables != 179 || report.CSVTables != 177 || report.MaterializedViews != 8 || report.SourceRows < 1000000 || report.InsertedRows < 1000000 || len(report.Tables) != 177 {
		t.Fatalf("incomplete import report: %+v", report)
	}
	db, err := postgres.Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for table, want := range map[string]int{"pokemon": 1350, "moves": 937, "natures": 25, "abilities": 367} {
		var got int
		if err = db.QueryRow(`SELECT count(*) FROM poke_raw.` + table).Scan(&got); err != nil || got != want {
			t.Fatalf("full raw table=%s count=%d want=%d err=%v", table, got, want, err)
		}
	}
	var hp, attack int
	if err = db.QueryRow(`SELECT hp,attack FROM poke_champion.pokemon_profile_mv WHERE pokemon_id=149`).Scan(&hp, &attack); err != nil || hp != 91 || attack != 134 {
		t.Fatalf("original view result differs hp=%d attack=%d err=%v", hp, attack, err)
	}
	var nullPower, zeroPower int
	if err = db.QueryRow(`SELECT count(*) FILTER(WHERE power IS NULL),count(*) FILTER(WHERE power=0) FROM poke_raw.moves`).Scan(&nullPower, &zeroPower); err != nil || nullPower != 0 || zeroPower == 0 {
		t.Fatalf("legacy empty integer conversion differs null=%d zero=%d err=%v", nullPower, zeroPower, err)
	}
	// 两个独立 PG 连接并行重跑，同版本只校验复用，不重复导入或覆盖行。
	var wait sync.WaitGroup
	results := make(chan error, 2)
	for i := 0; i < 2; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			replayed, e := Initialize(ctx, dsn, root, false)
			if e != nil {
				results <- e
				return
			}
			if !replayed.Reused || replayed.InsertedRows != report.InsertedRows {
				results <- errors.New("idempotent knowledge reuse differs")
			}
		}()
	}
	wait.Wait()
	close(results)
	for err := range results {
		t.Error(err)
	}
}

// emptyDatabase 创建唯一空测试库并登记精确清理，绝不删除调用方提供的数据库。
func emptyDatabase(t *testing.T) (*sql.DB, string) {
	t.Helper()
	dsn := os.Getenv("PBI_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_POSTGRES_DSN is required for knowledge transaction guards")
	}
	admin, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close() })
	name := fmt.Sprintf("pbi_knowledge_guard_%d", time.Now().UnixNano())
	if _, err = admin.Exec(`CREATE DATABASE ` + name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, e := admin.Exec(`DROP DATABASE ` + name + ` WITH(FORCE)`); e != nil {
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
	return db, parsed.String()
}

// TestRejectUnversionedDataWithoutMutation 证明未知非空库不会被清空、覆盖或登记为新知识版本。
func TestRejectUnversionedDataWithoutMutation(t *testing.T) {
	root := os.Getenv("PBI_KNOWLEDGE_CSV_ROOT")
	if root == "" {
		t.Skip("PBI_KNOWLEDGE_CSV_ROOT is required")
	}
	db, dsn := emptyDatabase(t)
	if _, err := db.Exec(rawSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO poke_raw.abilities(id,identifier,generation_id,is_main_series) VALUES(999999,'owned-guard-row',1,true)`); err != nil {
		t.Fatal(err)
	}
	if _, err := Initialize(context.Background(), dsn, root, false); !errors.Is(err, ErrNonempty) {
		t.Fatalf("unversioned target was accepted: %v", err)
	}
	var name string
	if err := db.QueryRow(`SELECT identifier FROM poke_raw.abilities WHERE id=999999`).Scan(&name); err != nil || name != "owned-guard-row" {
		t.Fatalf("existing row changed: %q err=%v", name, err)
	}
	var marker *string
	if err := db.QueryRow(`SELECT to_regclass('poke_raw._go_knowledge_version')::text`).Scan(&marker); err != nil || marker != nil {
		t.Fatalf("failed transaction retained version table marker=%v err=%v", marker, err)
	}
}

// TestAllCSVLegacyDigests 对全部固定源记录做 Go/Python 逐字段解析与类型转换差分，不以行数替代值一致。
func TestAllCSVLegacyDigests(t *testing.T) {
	root := os.Getenv("PBI_KNOWLEDGE_CSV_ROOT")
	if root == "" {
		t.Skip("PBI_KNOWLEDGE_CSV_ROOT is required for full CSV semantic differential")
	}
	manifest, _, err := Contract()
	if err != nil {
		t.Fatal(err)
	}
	var count int64
	for _, table := range manifest.Tables {
		source, err := openRows(filepath.Join(root, filepath.FromSlash(table.RelativePath)), table)
		if err != nil {
			t.Fatal(err)
		}
		for source.Next() {
		}
		parseErr := source.Err()
		closeErr := source.Close()
		if parseErr != nil || closeErr != nil {
			t.Fatalf("source %s parse=%v close=%v", table.Name, parseErr, closeErr)
		}
		got := hex.EncodeToString(source.semanticHash.Sum(nil))
		if got != table.ParsedSHA256 {
			t.Fatalf("legacy semantic mismatch %s rows=%d got=%s want=%s", table.RelativePath, source.rows, got, table.ParsedSHA256)
		}
		count += source.rows
	}
	t.Logf("matched Python parsing/types for %d CSV files and %d source rows", len(manifest.Tables), count)
}

// TestLegacyCSVQuoteAndNewlineRules 锁定真实源中的宽松闭引号、变长行和引用字段 CRLF。
func TestLegacyCSVQuoteAndNewlineRules(t *testing.T) {
	reader := newLegacyCSVReader(strings.NewReader("\r\n158,6,\"Route 210 \"(Westen, Richtung Elyses)\"\r\n1,9,\"inside\r\nquoted\"\n2,9, \"after space\"\n"))
	for index, want := range [][]string{{"158", "6", "Route 210 (Westen", " Richtung Elyses)\""}, {"1", "9", "inside\r\nquoted"}, {"2", "9", " \"after space\""}} {
		got, err := reader.Read()
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Fatalf("legacy row %d got=%q want=%q err=%v", index, got, want, err)
		}
	}
}
