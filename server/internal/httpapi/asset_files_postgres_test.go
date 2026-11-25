package httpapi_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"pokemonbattleinference/server/internal/httpapi"
	"pokemonbattleinference/server/internal/knowledge"
	"pokemonbattleinference/server/internal/postgres"
)

// writeOwnedSpritePNG 生成当前测试拥有的真实PNG；t负责清理，shade令各类别字节可区分。
// filename必须位于t.TempDir，返回完整正文供公开HTTP独立逐字节核对。
func writeOwnedSpritePNG(t *testing.T, filename string, shade color.RGBA) []byte {
	t.Helper()
	bitmap := image.NewRGBA(image.Rect(0, 0, 1, 1))
	bitmap.SetRGBA(0, 0, shade)
	var buffer bytes.Buffer
	if err := png.Encode(&buffer, bitmap); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(filename), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filename, buffer.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

// TestFilesystemAssetsPostgres 用真实PG元数据和本地版本快照证明三种原URL、ETag及损坏处理。
// 只接受目录夹具的空图片表；所有新增资产/批次由本测试清理，不接触其他来源记录。
func TestFilesystemAssetsPostgres(t *testing.T) {
	dsn := os.Getenv("PBI_TEST_CATALOG_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_CATALOG_DSN is required for isolated filesystem asset tests")
	}
	db, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var existing int
	if err = db.QueryRow(`SELECT count(*) FROM poke_raw.sprite_assets`).Scan(&existing); err != nil || existing != 0 {
		t.Fatalf("filesystem asset test requires its owned empty asset fixture: count=%d err=%v", existing, err)
	}
	identity := sha256.Sum256([]byte(fmt.Sprintf("owned-file-assets-%d", time.Now().UnixNano())))
	commit := hex.EncodeToString(identity[:])[:40]
	root := t.TempDir()
	source := filepath.Join(root, commit)
	cases := []struct {
		path  string
		url   string
		shade color.RGBA
		body  []byte
	}{
		{path: "pokemon/149.png", url: "/v1/assets/pokemon/149/sprite", shade: color.RGBA{R: 255, A: 255}},
		{path: "items/life-orb.png", url: "/v1/assets/items/life-orb/sprite", shade: color.RGBA{G: 255, A: 255}},
		{path: "types/generation-ix/scarlet-violet/10.png", url: "/v1/assets/types/fire/sprite", shade: color.RGBA{B: 255, A: 255}},
	}
	for index := range cases {
		cases[index].body = writeOwnedSpritePNG(t, filepath.Join(source, "sprites", cases[index].path), cases[index].shade)
	}
	// 同时存在旧版红色徽标和朱紫蓝色徽标时，公开URL必须选中朱紫的实际蓝色正文。
	writeOwnedSpritePNG(t, filepath.Join(source, "sprites/types/generation-viii/sword-shield/10.png"), color.RGBA{R: 255, A: 255})
	report, err := knowledge.InitializeSpriteFiles(context.Background(), dsn, source, commit)
	if err != nil || report.FilesSeen != 4 || report.Inserted != 4 || report.Storage != "filesystem" {
		t.Fatalf("filesystem metadata import=%+v err=%v", report, err)
	}
	defer func() {
		_, _ = db.Exec(`DELETE FROM poke_raw.sprite_assets WHERE last_seen_batch_id IN (SELECT id FROM poke_raw.sprite_import_batches WHERE source_commit=$1)`, commit)
		_, _ = db.Exec(`DELETE FROM poke_raw.sprite_import_batches WHERE source_commit=$1`, commit)
		_, _ = db.Exec(`REFRESH MATERIALIZED VIEW poke_champion.pokemon_sprite_candidates_mv; REFRESH MATERIALIZED VIEW poke_champion.pokemon_sprite_by_version_group_mv`)
	}()
	var bodies int
	if err = db.QueryRow(`SELECT count(*) FROM poke_raw.sprite_assets WHERE content IS NOT NULL`).Scan(&bodies); err != nil || bodies != 0 {
		t.Fatalf("filesystem bodies entered PostgreSQL: count=%d err=%v", bodies, err)
	}
	handler, err := httpapi.NewServerWithSpriteRoot(db, root)
	if err != nil {
		t.Fatal(err)
	}
	for _, example := range cases {
		got := request(t, handler, "GET", example.url, "", "")
		digest := sha256.Sum256(example.body)
		etag := `"` + hex.EncodeToString(digest[:]) + `"`
		if got.Code != 200 || !bytes.Equal(got.Body.Bytes(), example.body) || got.Header().Get("Content-Type") != "image/png" || got.Header().Get("ETag") != etag {
			t.Fatalf("filesystem response mismatch url=%s status=%d body=%q", example.url, got.Code, got.Body.Bytes())
		}
		r := httptest.NewRequest("GET", example.url, nil)
		r.Header.Set("If-None-Match", "W/"+etag+`, "other"`)
		cached := httptest.NewRecorder()
		handler.ServeHTTP(cached, r)
		if cached.Code != 304 || cached.Body.Len() != 0 || cached.Header().Get("ETag") != etag {
			t.Fatalf("filesystem cache contract mismatch url=%s status=%d", example.url, cached.Code)
		}
		if missing := request(t, httpapi.NewServer(db), "GET", example.url, "", ""); missing.Code != 503 {
			t.Fatalf("missing filesystem configuration returned success: %d", missing.Code)
		}
	}
	// 同长度损坏必须被SHA识别；即使客户端持有原ETag，也不能用304掩盖丢失的正文。
	filename := filepath.Join(source, "sprites", cases[0].path)
	broken := append([]byte(nil), cases[0].body...)
	broken[0] ^= 0xff
	if err = os.WriteFile(filename, broken, 0600); err != nil {
		t.Fatal(err)
	}
	if got := request(t, handler, "GET", cases[0].url, "", ""); got.Code != 503 {
		t.Fatalf("corrupt filesystem body was served: %d", got.Code)
	}
	if err = os.Remove(filename); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("GET", cases[0].url, nil)
	digest := sha256.Sum256(cases[0].body)
	r.Header.Set("If-None-Match", `"`+hex.EncodeToString(digest[:])+`"`)
	missing := httptest.NewRecorder()
	handler.ServeHTTP(missing, r)
	if missing.Code != 503 || missing.Body.Len() == 0 {
		t.Fatalf("missing filesystem body was hidden by cache validation: %d", missing.Code)
	}
}
