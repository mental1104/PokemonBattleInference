package httpapi

import (
	"database/sql"
	"errors"
	"net/http"
	"regexp"
	"strings"
)

var assetIdentifier = regexp.MustCompile(`^[a-z0-9-]+$`)

// registerAssets 保留三条原 BYTEA 图片接口，路径仅由白名单类别与数据库标识组成。
func registerAssets(mux *http.ServeMux, db *sql.DB) {
	mux.HandleFunc("GET /v1/assets/pokemon/{pokemon_id}/sprite", func(w http.ResponseWriter, r *http.Request) {
		id, ok := pokemonID(w, r)
		if !ok {
			return
		}
		slot := r.URL.Query().Get("slot")
		if slot == "" {
			slot = "front_default"
		}
		row := db.QueryRowContext(r.Context(), `SELECT raw.mime_type,raw.sha256,raw.content FROM poke_champion.pokemon_sprite_by_version_group_mv selected JOIN poke_raw.sprite_assets raw ON raw.id=selected.asset_id AND raw.is_active IS TRUE WHERE selected.ruleset_id=$1 AND selected.pokemon_id=$2 AND selected.sprite_slot=$3 LIMIT 1`, ruleset(r), id, slot)
		assetResponse(w, r, row, "pokemon sprite not found")
	})
	mux.HandleFunc("GET /v1/assets/types/{type_identifier}/sprite", func(w http.ResponseWriter, r *http.Request) {
		identifier := r.PathValue("type_identifier")
		if len(identifier) > 32 || !assetIdentifier.MatchString(identifier) {
			detail(w, 422, "invalid type identifier")
			return
		}
		row := db.QueryRowContext(r.Context(), `SELECT raw.mime_type,raw.sha256,raw.content FROM poke_raw.types t JOIN poke_raw.sprite_assets raw ON raw.relative_path='types/generation-viii/sword-shield/'||t.id::text||'.png' AND raw.asset_category='types' AND raw.is_active IS TRUE WHERE t.identifier=$1 LIMIT 1`, identifier)
		assetResponse(w, r, row, "type sprite not found")
	})
	mux.HandleFunc("GET /v1/assets/items/{item_identifier}/sprite", func(w http.ResponseWriter, r *http.Request) {
		identifier := r.PathValue("item_identifier")
		if len(identifier) > 64 || !assetIdentifier.MatchString(identifier) {
			detail(w, 422, "invalid item identifier")
			return
		}
		row := db.QueryRowContext(r.Context(), `SELECT raw.mime_type,raw.sha256,raw.content FROM poke_raw.items i JOIN poke_raw.sprite_assets raw ON raw.relative_path='items/'||i.identifier||'.png' AND raw.asset_category='items' AND raw.is_active IS TRUE WHERE i.identifier=$1 LIMIT 1`, identifier)
		assetResponse(w, r, row, "item sprite not found")
	})
}

// assetResponse 读取 row 中的图片字节并处理原强/弱 ETag 协商；缺失资产为 404。
// r 提供 If-None-Match，仅比较首个标签，与原 API 保持一致；不读取任意文件。
func assetResponse(w http.ResponseWriter, r *http.Request, row *sql.Row, missing string) {
	var mime, digest string
	var content []byte
	err := row.Scan(&mime, &digest, &content)
	if errors.Is(err, sql.ErrNoRows) {
		detail(w, 404, missing)
		return
	}
	if err != nil {
		detail(w, 503, "asset storage unavailable")
		return
	}
	w.Header().Set("ETag", `"`+digest+`"`)
	w.Header().Set("Cache-Control", "public, max-age=0, must-revalidate")
	candidate := strings.TrimSpace(strings.SplitN(r.Header.Get("If-None-Match"), ",", 2)[0])
	candidate = strings.TrimSpace(strings.TrimPrefix(candidate, "W/"))
	candidate = strings.Trim(candidate, `"`)
	if candidate == digest {
		w.WriteHeader(304)
		return
	}
	w.Header().Set("Content-Type", mime)
	w.WriteHeader(200)
	_, _ = w.Write(content)
}
