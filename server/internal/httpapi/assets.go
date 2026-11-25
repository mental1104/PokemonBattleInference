package httpapi

import (
	"database/sql"
	"errors"
	"net/http"
	"regexp"
	"strings"
)

var assetIdentifier = regexp.MustCompile(`^[a-z0-9-]+$`)

// registerAssets 保留三条原图片URL；PG存元数据，外部正文由已核验的spriteRoot版本目录提供。
// db/root由进程持有；历史非NULL的BYTEA仍可读取，新文件正文缺失则明确503而非返回空图片。
func registerAssets(mux *http.ServeMux, db *sql.DB, spriteRoot string) {
	mux.HandleFunc("GET /v1/assets/pokemon/{pokemon_id}/sprite", func(w http.ResponseWriter, r *http.Request) {
		id, ok := pokemonID(w, r)
		if !ok {
			return
		}
		slot := r.URL.Query().Get("slot")
		if slot == "" {
			slot = "front_default"
		}
		row := db.QueryRowContext(r.Context(), `SELECT raw.mime_type,raw.sha256,raw.content,raw.relative_path,raw.byte_size,b.source_commit FROM poke_champion.pokemon_sprite_by_version_group_mv selected JOIN poke_raw.sprite_assets raw ON raw.id=selected.asset_id AND raw.is_active IS TRUE LEFT JOIN poke_raw.sprite_import_batches b ON b.id=raw.last_seen_batch_id WHERE selected.ruleset_id=$1 AND selected.pokemon_id=$2 AND selected.sprite_slot=$3 LIMIT 1`, ruleset(r), id, slot)
		assetResponse(w, r, row, spriteRoot, "pokemon sprite not found")
	})
	mux.HandleFunc("GET /v1/assets/types/{type_identifier}/sprite", func(w http.ResponseWriter, r *http.Request) {
		identifier := r.PathValue("type_identifier")
		if len(identifier) > 32 || !assetIdentifier.MatchString(identifier) {
			detail(w, 422, "invalid type identifier")
			return
		}
		// 当前部署优先朱紫徽标；历史库只有剑盾素材时保留原响应，不改变公开URL。
		row := db.QueryRowContext(r.Context(), `SELECT raw.mime_type,raw.sha256,raw.content,raw.relative_path,raw.byte_size,b.source_commit FROM poke_raw.types t JOIN poke_raw.sprite_assets raw ON raw.relative_path IN ('types/generation-ix/scarlet-violet/'||t.id::text||'.png','types/generation-viii/sword-shield/'||t.id::text||'.png') AND raw.asset_category='types' AND raw.is_active IS TRUE LEFT JOIN poke_raw.sprite_import_batches b ON b.id=raw.last_seen_batch_id WHERE t.identifier=$1 ORDER BY CASE WHEN raw.relative_path LIKE 'types/generation-ix/scarlet-violet/%' THEN 0 ELSE 1 END LIMIT 1`, identifier)
		assetResponse(w, r, row, spriteRoot, "type sprite not found")
	})
	mux.HandleFunc("GET /v1/assets/items/{item_identifier}/sprite", func(w http.ResponseWriter, r *http.Request) {
		identifier := r.PathValue("item_identifier")
		if len(identifier) > 64 || !assetIdentifier.MatchString(identifier) {
			detail(w, 422, "invalid item identifier")
			return
		}
		row := db.QueryRowContext(r.Context(), `SELECT raw.mime_type,raw.sha256,raw.content,raw.relative_path,raw.byte_size,b.source_commit FROM poke_raw.items i JOIN poke_raw.sprite_assets raw ON raw.relative_path='items/'||i.identifier||'.png' AND raw.asset_category='items' AND raw.is_active IS TRUE LEFT JOIN poke_raw.sprite_import_batches b ON b.id=raw.last_seen_batch_id WHERE i.identifier=$1 LIMIT 1`, identifier)
		assetResponse(w, r, row, spriteRoot, "item sprite not found")
	})
}

// assetResponse 按row的正文所有权读取真实图片并保留原强/弱ETag；无元数据返回404，存储错误返回503。
// r提供首个If-None-Match标签；root只能读取已登记版本/路径，缺失正文不能因ETag匹配而伪造304。
func assetResponse(w http.ResponseWriter, r *http.Request, row *sql.Row, root, missing string) {
	var mime string
	var source sql.NullString
	var asset spriteFile
	var content []byte
	err := row.Scan(&mime, &asset.Digest, &content, &asset.RelativePath, &asset.ByteSize, &source)
	if errors.Is(err, sql.ErrNoRows) {
		detail(w, 404, missing)
		return
	}
	if err != nil {
		detail(w, 503, "asset storage unavailable")
		return
	}
	if content == nil {
		asset.SourceCommit = source.String
		content, err = readSpriteFile(r.Context(), root, asset)
		if err != nil {
			detail(w, 503, "asset storage unavailable")
			return
		}
	}
	w.Header().Set("ETag", `"`+asset.Digest+`"`)
	w.Header().Set("Cache-Control", "public, max-age=0, must-revalidate")
	candidate := strings.TrimSpace(strings.SplitN(r.Header.Get("If-None-Match"), ",", 2)[0])
	candidate = strings.TrimSpace(strings.TrimPrefix(candidate, "W/"))
	candidate = strings.Trim(candidate, `"`)
	if candidate == asset.Digest {
		w.WriteHeader(304)
		return
	}
	w.Header().Set("Content-Type", mime)
	w.WriteHeader(200)
	_, _ = w.Write(content)
}
