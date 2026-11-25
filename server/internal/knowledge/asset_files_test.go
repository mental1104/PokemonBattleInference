package knowledge

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
)

// TestSpriteFilesRequireSourceIdentity 必须在扫描/连接之前拒绝未固定的外部快照身份。
func TestSpriteFilesRequireSourceIdentity(t *testing.T) {
	for _, source := range []string{"", "unknown", strings.Repeat("A", 40), strings.Repeat("x", 40)} {
		if _, err := InitializeSpriteFiles(context.Background(), "invalid-dsn", "missing-source", source); err == nil {
			t.Fatalf("invalid filesystem source identity accepted: %q", source)
		}
	}
}

// TestSpriteFilesPostgres 在自有库核验真实元数据导入、无正文、稳定身份、幂等和旧入口拒绝。
// 不依赖HTTP或生产素材；外部正文一直由测试目录拥有，表内content必须为SQL NULL。
func TestSpriteFilesPostgres(t *testing.T) {
	db, dsn := emptyDatabase(t)
	ctx := context.Background()
	if _, err := db.ExecContext(ctx, rawSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, viewSchema); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(t.TempDir(), "sprites")
	writeSpriteTestFile(t, filepath.Join(root, "pokemon", "212.png"), []byte("first snapshot bytes"))
	commit := strings.Repeat("a", 40)
	first, err := InitializeSpriteFiles(ctx, dsn, root, commit)
	if err != nil || first.Storage != "filesystem" || first.FilesSeen != 1 || first.Inserted != 1 || first.Skipped {
		t.Fatalf("filesystem import=%+v err=%v", first, err)
	}
	var id, firstSeen, size int64
	var absent bool
	if err = db.QueryRow(`SELECT id,first_seen_batch_id,byte_size,content IS NULL FROM poke_raw.sprite_assets`).Scan(&id, &firstSeen, &size, &absent); err != nil || !absent || size != 20 {
		t.Fatalf("filesystem body entered PostgreSQL: absent=%t size=%d err=%v", absent, size, err)
	}
	replay, err := InitializeSpriteFiles(ctx, dsn, root, commit)
	if err != nil || !replay.Skipped || replay.Unchanged != 1 {
		t.Fatalf("filesystem replay=%+v err=%v", replay, err)
	}
	if _, err = InitializeSprites(ctx, dsn, root, commit); err == nil {
		t.Fatal("legacy importer silently copied filesystem bodies into PostgreSQL")
	}
	writeSpriteTestFile(t, filepath.Join(root, "pokemon", "212.png"), []byte("next snapshot bytes"))
	second, err := InitializeSpriteFiles(ctx, dsn, root, strings.Repeat("b", 40))
	if err != nil || second.Updated != 1 || second.Inserted != 0 {
		t.Fatalf("filesystem update=%+v err=%v", second, err)
	}
	var afterID, afterFirst int64
	if err = db.QueryRow(`SELECT id,first_seen_batch_id,content IS NULL FROM poke_raw.sprite_assets`).Scan(&afterID, &afterFirst, &absent); err != nil || afterID != id || afterFirst != firstSeen || !absent {
		t.Fatalf("filesystem update lost identity or stored content: %v", err)
	}
}

// TestSpriteFilesAdoptsLegacyContent 将原BYTEA显式迁为外部元数据，保留id/first_seen且清除表内正文。
func TestSpriteFilesAdoptsLegacyContent(t *testing.T) {
	db, dsn := emptyDatabase(t)
	ctx := context.Background()
	if _, err := db.ExecContext(ctx, rawSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, viewSchema); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(t.TempDir(), "sprites")
	writeSpriteTestFile(t, filepath.Join(root, "pokemon", "212.png"), []byte("preserved external bytes"))
	commit := strings.Repeat("a", 40)
	if _, err := InitializeSprites(ctx, dsn, root, commit); err != nil {
		t.Fatal(err)
	}
	var id, firstSeen int64
	if err := db.QueryRow(`SELECT id,first_seen_batch_id FROM poke_raw.sprite_assets`).Scan(&id, &firstSeen); err != nil {
		t.Fatal(err)
	}
	adopted, err := InitializeSpriteFiles(ctx, dsn, root, commit)
	if err != nil || adopted.Skipped || adopted.Unchanged != 1 || adopted.Storage != "filesystem" {
		t.Fatalf("legacy body adoption=%+v err=%v", adopted, err)
	}
	var afterID, afterFirst int64
	var absent bool
	if err = db.QueryRow(`SELECT id,first_seen_batch_id,content IS NULL FROM poke_raw.sprite_assets`).Scan(&afterID, &afterFirst, &absent); err != nil || afterID != id || afterFirst != firstSeen || !absent {
		t.Fatalf("legacy identity changed or body remained in PostgreSQL: %v", err)
	}
}

// TestSpriteFilesFailureRollsBackSchema 由真实trigger拒绝后续行，必须一起恢复原NOT NULL及BYTEA。
func TestSpriteFilesFailureRollsBackSchema(t *testing.T) {
	db, dsn := emptyDatabase(t)
	ctx := context.Background()
	if _, err := db.ExecContext(ctx, rawSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, viewSchema); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(t.TempDir(), "sprites")
	filename := filepath.Join(root, "pokemon", "212.png")
	writeSpriteTestFile(t, filename, []byte("original bytes"))
	if _, err := InitializeSprites(ctx, dsn, root, "legacy"); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE FUNCTION poke_raw.reject_file_test_sprite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.relative_path='pokemon/999.png' THEN RAISE EXCEPTION 'injected file metadata failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_file_test_sprite BEFORE INSERT OR UPDATE ON poke_raw.sprite_assets FOR EACH ROW EXECUTE FUNCTION poke_raw.reject_file_test_sprite()`); err != nil {
		t.Fatal(err)
	}
	writeSpriteTestFile(t, filename, []byte("changed bytes"))
	writeSpriteTestFile(t, filepath.Join(root, "pokemon", "999.png"), []byte("rejected bytes"))
	if _, err := InitializeSpriteFiles(ctx, dsn, root, strings.Repeat("b", 40)); err == nil {
		t.Fatal("injected filesystem metadata failure was ignored")
	}
	var content []byte
	if err := db.QueryRow(`SELECT content FROM poke_raw.sprite_assets WHERE relative_path='pokemon/212.png'`).Scan(&content); err != nil || string(content) != "original bytes" {
		t.Fatalf("legacy body changed after failed metadata transaction: %q %v", content, err)
	}
	var required bool
	if err := db.QueryRow(`SELECT attnotnull FROM pg_attribute WHERE attrelid='poke_raw.sprite_assets'::regclass AND attname='content' AND NOT attisdropped`).Scan(&required); err != nil || !required {
		t.Fatalf("failed filesystem migration changed the original schema: required=%t err=%v", required, err)
	}
	var batches int
	if err := db.QueryRow(`SELECT count(*) FROM poke_raw.sprite_import_batches`).Scan(&batches); err != nil || batches != 1 {
		t.Fatalf("failed filesystem migration leaked its batch: %d %v", batches, err)
	}
}
