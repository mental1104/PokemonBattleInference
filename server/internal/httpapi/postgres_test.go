package httpapi_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"pokemonbattleinference/server/internal/configurations"
	"pokemonbattleinference/server/internal/httpapi"
	"pokemonbattleinference/server/internal/postgres"
	"strings"
	"testing"
	"time"
)

// isolatedDatabase 为 t 创建唯一数据库；只使用显式测试 DSN，清理仅针对创建成功的名字。
func isolatedDatabase(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("PBI_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_POSTGRES_DSN is required for PostgreSQL integration")
	}
	admin, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close() })
	name := fmt.Sprintf("pbi_server_test_%d", time.Now().UnixNano())
	if _, err = admin.Exec("CREATE DATABASE " + name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, e := admin.Exec("DROP DATABASE " + name + " WITH (FORCE)"); e != nil {
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
	return db
}

// request 通过 HTTP handler 发送 method/path/body 及可信 tenant，返回完整 recorder。
func request(t *testing.T, handler http.Handler, method, path, body, tenant string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	if tenant != "" {
		r.Header.Set("X-Pokeop-Tenant", tenant)
	}
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)
	return w
}

// TestConfigurationLifecyclePostgres 证明租户隔离、软删除、偏好事务及重建 handler 后持久化。
func TestConfigurationLifecyclePostgres(t *testing.T) {
	db := isolatedDatabase(t)
	handler := httpapi.NewServer(db)
	body := `{"name":"  快龙 & <测试>  ","nature_id":"adamant","evs":{"hp":4,"attack":252,"defense":0,"special_attack":0,"special_defense":0,"speed":252},"role":"both","binding_kind":"pokemon","pokemon_id":149}`
	response := request(t, handler, "POST", "/v1/stat-configurations", body, "alpha")
	if response.Code != 201 {
		t.Fatalf("create status=%d body=%s", response.Code, response.Body)
	}
	var created configurations.View
	if err := json.Unmarshal(response.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.Name != "快龙 & <测试>" || created.IVs.HP != 31 || created.EVs.Attack != 252 || !created.Editable || created.PokemonID == nil || *created.PokemonID != 149 {
		t.Fatalf("create mapping failed: %+v", created)
	}
	snapshot, err := base64.RawURLEncoding.DecodeString(strings.TrimPrefix(created.SnapshotProfileID, "preset-snapshot:"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(snapshot, []byte(`\u003c`)) || !bytes.Contains(snapshot, []byte("快龙 & <测试>")) {
		t.Fatalf("snapshot is not legacy UTF-8 canonical JSON: %s", snapshot)
	}
	// 相同主键不能通过另一个租户更新或软删除。
	path := "/v1/stat-configurations/" + created.Key
	if got := request(t, handler, "PUT", path, body, "beta"); got.Code != 400 {
		t.Fatalf("cross-tenant update status=%d", got.Code)
	}
	if got := request(t, handler, "DELETE", path, "", "beta"); got.Code != 404 {
		t.Fatalf("cross-tenant delete status=%d", got.Code)
	}
	// 幂等迁移和 handler 重建不丢失配置。
	if err = postgres.Migrate(context.Background(), db); err != nil {
		t.Fatal(err)
	}
	handler = httpapi.NewServer(db)
	listPath := "/v1/stat-configurations?role=attacker&pokemon_id=149"
	got := request(t, handler, "GET", listPath, "", "alpha")
	if got.Code != 200 {
		t.Fatal(got.Body.String())
	}
	var list configurations.ListResult
	if err = json.Unmarshal(got.Body.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Items) != 5 || list.Items[4].SnapshotProfileID != created.SnapshotProfileID {
		t.Fatalf("persistent merged list differs: %s", got.Body)
	}
	// 批次第二项无效时，第一项偏好也不能落盘。
	order := `{"role":"attacker","references":[{"source":"custom","key":"` + created.Key + `"},{"source":"custom","key":"missing"}]}`
	if got = request(t, handler, "POST", "/v1/stat-configurations/order", order, "alpha"); got.Code != 400 {
		t.Fatalf("invalid order status=%d body=%s", got.Code, got.Body)
	}
	var count int
	if err = db.QueryRow(`SELECT COUNT(*) FROM poke_runtime.stat_configuration_preferences`).Scan(&count); err != nil || count != 0 {
		t.Fatalf("partial preference write count=%d err=%v", count, err)
	}
	hide := `{"role":"attacker","reference":{"source":"custom","key":"` + created.Key + `"},"hidden":true}`
	if got = request(t, handler, "POST", "/v1/stat-configurations/hidden", hide, "alpha"); got.Code != 204 {
		t.Fatalf("hide status=%d %s", got.Code, got.Body)
	}
	got = request(t, handler, "GET", listPath+"&include_hidden=true", "", "alpha")
	if err = json.Unmarshal(got.Body.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Items) != 5 || len(list.VisibleItems) != 4 || !list.Items[4].Hidden {
		t.Fatalf("hidden projection failed: %s", got.Body)
	}
	if got = request(t, handler, "DELETE", path, "", "alpha"); got.Code != 204 {
		t.Fatalf("delete status=%d", got.Code)
	}
	var deleted bool
	if err = db.QueryRow(`SELECT is_deleted FROM poke_runtime.stat_configurations WHERE id=$1`, created.Key).Scan(&deleted); err != nil || !deleted {
		t.Fatalf("soft deletion failed: %v", err)
	}
	// 旧快照仍可在配置被删除后独立解释。
	var payload struct {
		Name string                `json:"label"`
		EVs  configurations.Spread `json:"evs"`
	}
	if err = json.Unmarshal(snapshot, &payload); err != nil || payload.Name != created.Name || payload.EVs.Attack != 252 {
		t.Fatalf("immutable snapshot failed: %v", err)
	}
}

// TestConfigurationValidation 拒绝缺失能力、总 EV 越界、非法性格及空可信租户。
func TestConfigurationValidation(t *testing.T) {
	db := isolatedDatabase(t)
	handler := httpapi.NewServer(db)
	cases := []string{`{"name":"x","nature_id":"hardy","evs":{"hp":0},"role":"both","binding_kind":"global"}`, `{"name":"x","nature_id":"hardy","evs":{"hp":252,"attack":252,"defense":252,"special_attack":0,"special_defense":0,"speed":0},"role":"both","binding_kind":"global"}`}
	for _, body := range cases {
		got := request(t, handler, "POST", "/v1/stat-configurations", body, "alpha")
		if got.Code < 400 || got.Code >= 500 {
			t.Fatalf("invalid input status=%d body=%s", got.Code, got.Body)
		}
	}
	r := httptest.NewRequest("GET", "/v1/stat-configurations?role=attacker&pokemon_id=149", nil)
	r.Header.Set("X-Pokeop-Tenant", " ")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)
	if w.Code != 400 {
		t.Fatalf("empty tenant status=%d", w.Code)
	}
}

// TestCatalogReferencePostgres 读取真实 CSV 及原物化视图，不创建替代目录数据。
func TestCatalogReferencePostgres(t *testing.T) {
	dsn := os.Getenv("PBI_TEST_CATALOG_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_CATALOG_DSN must point to an isolated initialized legacy catalog")
	}
	db, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	handler := httpapi.NewServer(db)
	var pokemon struct {
		ID    int    `json:"pokemon_id"`
		Name  string `json:"display_name"`
		Stats struct {
			HP     int `json:"hp"`
			Attack int `json:"attack"`
		} `json:"base_stats"`
		Types []string `json:"types"`
	}
	got := request(t, handler, "GET", "/v1/calculator/pokemon/149", "", "")
	if got.Code != 200 {
		t.Fatalf("detail status=%d body=%s", got.Code, got.Body)
	}
	if err = json.Unmarshal(got.Body.Bytes(), &pokemon); err != nil {
		t.Fatal(err)
	}
	if pokemon.ID != 149 || pokemon.Name != "快龙" || pokemon.Stats.HP != 91 || pokemon.Stats.Attack != 134 || strings.Join(pokemon.Types, ",") != "dragon,flying" {
		t.Fatalf("real catalog mapping failed: %s", got.Body)
	}
	for _, path := range []string{"/v1/calculator/pokemon?query=%E5%BF%AB%E9%BE%99", "/v1/calculator/pokemon/149/abilities", "/v1/calculator/items"} {
		got = request(t, handler, "GET", path, "", "")
		if got.Code != 200 || got.Body.String() == "[]" {
			t.Fatalf("catalog path=%s status=%d body=%s", path, got.Code, got.Body)
		}
	}
	movesPath := "/v1/calculator/pokemon/149/moves?limit=2&type=dragon"
	got = request(t, handler, "GET", movesPath, "", "")
	if got.Code != 200 {
		t.Fatalf("moves status=%d body=%s", got.Code, got.Body)
	}
	var page struct {
		Items []struct {
			ID    int    `json:"move_id"`
			Type  string `json:"type"`
			Power int    `json:"power"`
		} `json:"items"`
		Total     int               `json:"total"`
		HasMore   bool              `json:"has_more"`
		Available []json.RawMessage `json:"available_types"`
	}
	if err = json.Unmarshal(got.Body.Bytes(), &page); err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 2 || page.Total <= 2 || !page.HasMore || len(page.Available) != 18 || page.Items[0].ID == page.Items[1].ID || page.Items[0].Type != "dragon" || page.Items[0].Power < page.Items[1].Power {
		t.Fatalf("stable move page failed: %s", got.Body)
	}
	first := got.Body.String()
	got = request(t, handler, "GET", movesPath, "", "")
	if got.Body.String() != first {
		t.Fatal("repeat page differs")
	}
	if got = request(t, handler, "GET", movesPath+"&type=invalid", "", ""); got.Code != 400 {
		t.Fatalf("invalid type status=%d", got.Code)
	}
	if got = request(t, handler, "GET", "/v1/calculator/pokemon/999999", "", ""); got.Code != 404 {
		t.Fatalf("missing pokemon status=%d", got.Code)
	}
}

// TestAssetsPostgres 用真实 PNG BYTEA 和原选择视图证明二进制响应及 ETag，不依赖外部图片服务。
// 测试只向显式目录测试库插入自有批次，结束删除该批次记录并刷新相关视图。
func TestAssetsPostgres(t *testing.T) {
	dsn := os.Getenv("PBI_TEST_CATALOG_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_CATALOG_DSN is required for isolated asset tests")
	}
	db, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	content, err := base64.StdEncoding.DecodeString("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jY6kAAAAASUVORK5CYII=")
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(content)
	digest := hex.EncodeToString(sum[:])
	var batch int
	if err = db.QueryRow(`INSERT INTO poke_raw.sprite_import_batches(manifest_hash,status,files_seen) VALUES($1,'succeeded',3) RETURNING id`, fmt.Sprintf("pbi-go-test-%d", time.Now().UnixNano())).Scan(&batch); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = db.Exec(`DELETE FROM poke_raw.sprite_assets WHERE first_seen_batch_id=$1`, batch)
		_, _ = db.Exec(`DELETE FROM poke_raw.sprite_import_batches WHERE id=$1`, batch)
		_, _ = db.Exec(`REFRESH MATERIALIZED VIEW poke_champion.pokemon_sprite_candidates_mv; REFRESH MATERIALIZED VIEW poke_champion.pokemon_sprite_by_version_group_mv`)
	}()
	_, err = db.Exec(`INSERT INTO poke_raw.sprite_assets(relative_path,asset_category,pokemon_id,collection,sprite_slot,is_front,is_back,parse_status,mime_type,byte_size,sha256,content,first_seen_batch_id,last_seen_batch_id,is_active) VALUES('pokemon/149.png','pokemon',149,'pokemon','front_default',true,false,'parsed','image/png',$1,$2,$3,$4,$4,true),('items/life-orb.png','items',NULL,NULL,NULL,NULL,NULL,'parsed','image/png',$1,$2,$3,$4,$4,true),('types/generation-viii/sword-shield/10.png','types',NULL,NULL,NULL,NULL,NULL,'parsed','image/png',$1,$2,$3,$4,$4,true)`, len(content), digest, content, batch)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec(`REFRESH MATERIALIZED VIEW poke_champion.pokemon_sprite_candidates_mv; REFRESH MATERIALIZED VIEW poke_champion.pokemon_sprite_by_version_group_mv`); err != nil {
		t.Fatal(err)
	}
	handler := httpapi.NewServer(db)
	for _, path := range []string{"/v1/assets/pokemon/149/sprite", "/v1/assets/items/life-orb/sprite", "/v1/assets/types/fire/sprite"} {
		got := request(t, handler, "GET", path, "", "")
		if got.Code != 200 || !bytes.Equal(got.Body.Bytes(), content) || got.Header().Get("ETag") != `"`+digest+`"` || got.Header().Get("Content-Type") != "image/png" {
			t.Fatalf("asset mapping path=%s status=%d body=%s", path, got.Code, got.Body)
		}
		r := httptest.NewRequest("GET", path, nil)
		r.Header.Set("If-None-Match", `W/"`+digest+`", "other"`)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		if w.Code != 304 || w.Body.Len() != 0 || w.Header().Get("ETag") != got.Header().Get("ETag") {
			t.Fatalf("cache contract path=%s status=%d", path, w.Code)
		}
	}
	if got := request(t, handler, "GET", "/v1/assets/items/missing/sprite", "", ""); got.Code != 404 {
		t.Fatalf("missing asset status=%d", got.Code)
	}
}
