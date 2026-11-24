package knowledge

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// TestSpriteMetadataLegacyPaths 锁定原 path_parser 的可空字段、方向/变体与 Unicode 十进制 ID。
// t 为测试上下文；返回失败直接定位原文件路径，不需要数据库或网络。
func TestSpriteMetadataLegacyPaths(t *testing.T) {
	for _, example := range []struct {
		path string
		want spriteMetadata
	}{
		{"pokemon/212.png", spriteMetadata{RelativePath: "pokemon/212.png", Category: "pokemon", PokemonID: spriteValue(int64(212)), Collection: spriteValue("pokemon"), Slot: spriteValue("front_default"), Front: spriteValue(true), Back: spriteValue(false), Female: spriteValue(false), Shiny: spriteValue(false), Animated: spriteValue(false), Status: "parsed"}},
		{"pokemon/versions/generation-v/black-white/animated/back/female/shiny/212.gif", spriteMetadata{RelativePath: "pokemon/versions/generation-v/black-white/animated/back/female/shiny/212.gif", Category: "pokemon", PokemonID: spriteValue(int64(212)), Generation: spriteValue("generation-v"), Version: spriteValue("black-white"), Collection: spriteValue("versions"), RenderStyle: spriteValue("animated"), Slot: spriteValue("back_female_shiny"), Front: spriteValue(false), Back: spriteValue(true), Female: spriteValue(true), Shiny: spriteValue(true), Animated: spriteValue(true), Status: "parsed"}},
		{"items/life-orb.png", spriteMetadata{RelativePath: "items/life-orb.png", Category: "items", Status: "unparsed"}},
		{"pokemon/egg.png", spriteMetadata{RelativePath: "pokemon/egg.png", Category: "pokemon", Collection: spriteValue("pokemon"), Status: "unparsed"}},
		{"pokemon/.hidden", spriteMetadata{RelativePath: "pokemon/.hidden", Category: "pokemon", Status: "unparsed"}},
	} {
		got, err := parseSpritePath(example.path)
		if err != nil || !reflect.DeepEqual(got, example.want) {
			t.Fatalf("metadata mismatch path=%q got=%+v want=%+v err=%v", example.path, got, example.want, err)
		}
	}
	for _, name := range []string{"700", "７００", "٧٠٠", "700-matcha-cream"} {
		got, err := parseSpritePath("pokemon/other/home/" + name + ".PNG")
		if err != nil || got.PokemonID == nil || *got.PokemonID != 700 || got.Collection == nil || *got.Collection != "other" || got.RenderStyle == nil || *got.RenderStyle != "home" {
			t.Fatalf("other/id metadata mismatch name=%q got=%+v err=%v", name, got, err)
		}
	}
	for _, name := range []string{"egg", "212suffix", "-212", "212-a\nb"} {
		got, err := spritePokemonID(name)
		if err != nil || got != nil {
			t.Fatalf("unmapped filename acquired id name=%q got=%v err=%v", name, got, err)
		}
	}
	if _, err := spritePokemonID("999999999999999999999"); err == nil {
		t.Fatal("integer overflow was silently discarded")
	}
	for path, want := range map[string]string{"pokemon/212.png": "image/png", "pokemon/25.GIF": "image/gif", "pokemon/other/dream-world/25.svg": "image/svg+xml", "pokemon/25.webp": "image/webp", "unmapped.unknown-extension": "application/octet-stream", "manifest.txt": "text/plain", "pokemon/25.png.gz": "image/png"} {
		if got := spriteMIME(path); got != want {
			t.Fatalf("MIME mismatch path=%s got=%s want=%s", path, got, want)
		}
	}
}

// writeSpriteTestFile 在 t 独占目录中写入 path/content；失败终止当前测试，不接触外部资源。
func writeSpriteTestFile(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
}

// TestSpriteManifestAndEarlyFailure 对照原 NUL/长度/完整路径排序摘要，并证明取消/源缺失早于连接。
// t 提供独占本地目录；测试不需要 PostgreSQL，即使 dsn 无效也必须先得到来源错误。
func TestSpriteManifestAndEarlyFailure(t *testing.T) {
	root := filepath.Join(t.TempDir(), "sprites")
	writeSpriteTestFile(t, filepath.Join(root, "pokemon", "212.png"), []byte("scizor"))
	writeSpriteTestFile(t, filepath.Join(root, "items", "master-ball.png"), []byte("item"))
	entries, digest, err := spriteManifest(context.Background(), root)
	if err != nil || len(entries) != 2 {
		t.Fatalf("manifest scan entries=%d err=%v", len(entries), err)
	}
	item, scizor := sha256.Sum256([]byte("item")), sha256.Sum256([]byte("scizor"))
	expected := sha256.Sum256([]byte("items/master-ball.png\x00" + hex.EncodeToString(item[:]) + "\x004\npokemon/212.png\x00" + hex.EncodeToString(scizor[:]) + "\x006\n"))
	if digest != hex.EncodeToString(expected[:]) {
		t.Fatalf("legacy manifest mismatch got=%s want=%x", digest, expected)
	}
	if _, err = InitializeSprites(context.Background(), "invalid-dsn", t.TempDir(), ""); err == nil || !strings.Contains(err.Error(), "sprites directory not found") {
		t.Fatalf("missing source was not checked first: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = InitializeSprites(ctx, "invalid-dsn", root, ""); !errors.Is(err, context.Canceled) {
		t.Fatalf("scan ignored cancellation: %v", err)
	}
}

// TestSpriteImportPostgres 用自有独立空库验证原批次/内容/失效合同和真实事务失败恢复。
// t 只借用显式 PBI_TEST_POSTGRES_DSN 的管理连接；emptyDatabase 创建并精确清理唯一测试库。
func TestSpriteImportPostgres(t *testing.T) {
	db, dsn := emptyDatabase(t)
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	if _, err := db.ExecContext(ctx, rawSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, viewSchema); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(t.TempDir(), "sprites")
	firstPath, removedPath := filepath.Join(root, "pokemon", "212.png"), filepath.Join(root, "pokemon", "700.png")
	writeSpriteTestFile(t, firstPath, []byte("old-scizor"))
	writeSpriteTestFile(t, removedPath, []byte("sylveon"))
	first, err := InitializeSprites(ctx, dsn, root, "fixed-sprite-source")
	if err != nil || first.Skipped || first.Inserted != 2 || first.FilesSeen != 2 {
		t.Fatalf("first import=%+v err=%v", first, err)
	}
	var firstID, firstBatch int64
	if err = db.QueryRowContext(ctx, `SELECT id,first_seen_batch_id FROM poke_raw.sprite_assets WHERE relative_path='pokemon/212.png'`).Scan(&firstID, &firstBatch); err != nil {
		t.Fatal(err)
	}
	// 并发重跑串行读取最新完成 manifest，不生成重复资源/批次。
	var wait sync.WaitGroup
	replays := make(chan error, 2)
	for index := 0; index < 2; index++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			replayed, e := InitializeSprites(ctx, dsn, root, "fixed-sprite-source")
			if e != nil {
				replays <- e
				return
			}
			if !replayed.Skipped || replayed.Unchanged != 2 {
				replays <- errors.New("identical sprite manifest did not reuse")
			}
		}()
	}
	wait.Wait()
	close(replays)
	for e := range replays {
		t.Error(e)
	}
	writeSpriteTestFile(t, firstPath, []byte("new-scizor"))
	if err = os.Remove(removedPath); err != nil {
		t.Fatal(err)
	}
	changed, err := InitializeSprites(ctx, dsn, root, "next-source")
	if err != nil || changed.Updated != 1 || changed.Inserted != 0 || changed.FilesSeen != 1 {
		t.Fatalf("changed import=%+v err=%v", changed, err)
	}
	var id, firstSeen int64
	var content []byte
	var active bool
	if err = db.QueryRowContext(ctx, `SELECT id,first_seen_batch_id,content,is_active FROM poke_raw.sprite_assets WHERE relative_path='pokemon/212.png'`).Scan(&id, &firstSeen, &content, &active); err != nil || id != firstID || firstSeen != firstBatch || string(content) != "new-scizor" || !active {
		t.Fatalf("updated content/identity id=%d first=%d content=%q active=%t err=%v", id, firstSeen, content, active, err)
	}
	if err = db.QueryRowContext(ctx, `SELECT is_active FROM poke_raw.sprite_assets WHERE relative_path='pokemon/700.png'`).Scan(&active); err != nil || active {
		t.Fatalf("removed source still active=%t err=%v", active, err)
	}
	// 在已写入第一个新内容后，由真实 PG trigger 拒绝第二个文件；整个批次必须回滚。
	if _, err = db.ExecContext(ctx, `CREATE FUNCTION poke_raw.reject_test_sprite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.relative_path='pokemon/999.png' THEN RAISE EXCEPTION 'injected sprite write failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_test_sprite BEFORE INSERT OR UPDATE ON poke_raw.sprite_assets FOR EACH ROW EXECUTE FUNCTION poke_raw.reject_test_sprite()`); err != nil {
		t.Fatal(err)
	}
	writeSpriteTestFile(t, firstPath, []byte("must-rollback"))
	writeSpriteTestFile(t, filepath.Join(root, "pokemon", "999.png"), []byte("rejected"))
	if _, err = InitializeSprites(ctx, dsn, root, "failed-source"); err == nil {
		t.Fatal("injected mid-import SQL failure was ignored")
	}
	if err = db.QueryRowContext(ctx, `SELECT content,is_active FROM poke_raw.sprite_assets WHERE relative_path='pokemon/212.png'`).Scan(&content, &active); err != nil || string(content) != "new-scizor" || !active {
		t.Fatalf("failed transaction changed old resource content=%q active=%t err=%v", content, active, err)
	}
	var batches, failed int
	if err = db.QueryRowContext(ctx, `SELECT count(*),count(*) FILTER(WHERE status<>'completed') FROM poke_raw.sprite_import_batches`).Scan(&batches, &failed); err != nil || batches != 2 || failed != 0 {
		t.Fatalf("failed import retained batch count=%d failed=%d err=%v", batches, failed, err)
	}
}
