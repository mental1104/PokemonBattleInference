package httpapi

import (
	"database/sql"
	"net/http"
	"pokemonbattleinference/server/internal/jobs"
)

// configurationResultMetadata 是独立执行溯源信封，不扩充或改写旧 results/explanation 合同。
// Metadata 为 nil 表示该 case 尚未记录来源；提交准入版本不能替代真实子进程版本。
type configurationResultMetadata struct {
	SchemaVersion int                     `json:"schema_version"`
	Metadata      *jobs.ExecutionMetadata `json:"metadata"`
}

// registerConfigurationJobMetadata 在 mux 注册只读来源接口，db 是借用的同一任务连接池。
// case 不存在返回 404，存在但无辅助记录返回显式 null，读取/校验失败返回 503，不推断旧版本。
func registerConfigurationJobMetadata(mux *http.ServeMux, db *sql.DB) {
	store := jobs.New(db)
	mux.HandleFunc("GET /v1/inference/configuration-jobs/{job_id}/results/{configuration_pair_id}/metadata", func(w http.ResponseWriter, r *http.Request) {
		id, pair := r.PathValue("job_id"), r.PathValue("configuration_pair_id")
		// 使用绑定的完整 canonical ID；不能把旧记录缺 aux 与不存在的 case 混为一谈。
		var exists bool
		if err := db.QueryRowContext(r.Context(), `SELECT EXISTS(SELECT 1 FROM poke_runtime.battle_inference_cases WHERE job_id=$1 AND configuration_pair_id=$2)`, id, pair).Scan(&exists); err != nil {
			detail(w, http.StatusServiceUnavailable, "job storage unavailable")
			return
		}
		if !exists {
			writeJSON(w, http.StatusNotFound, map[string]any{"detail": map[string]string{"code": "battle_inference_case_not_found", "message": "battle inference case was not found"}})
			return
		}
		metadata, err := store.ResultMetadata(r.Context(), id, pair)
		if err != nil {
			detail(w, http.StatusServiceUnavailable, "execution metadata unavailable")
			return
		}
		writeJSON(w, http.StatusOK, configurationResultMetadata{SchemaVersion: 1, Metadata: metadata})
	})
}
