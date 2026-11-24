package httpapi

import (
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"pokemonbattleinference/server/internal/configurations"
	"pokemonbattleinference/server/internal/syncapi"
	"pokemonbattleinference/server/internal/syncstore"
	"strconv"
	"strings"
)

// NewServer 组合原配置、知识读取和用户同步 API；db 的生命周期由进程拥有。
// 未传数据库时保留原 Core-only Handler；不会退化到进程内假仓库。
func NewServer(db *sql.DB) http.Handler {
	mux := baseMux()
	if db == nil {
		return mux
	}
	store := configurations.New(db)
	mux.HandleFunc("GET /v1/stat-configurations/natures", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, configurations.Natures()) })
	mux.HandleFunc("GET /v1/stat-configurations", func(w http.ResponseWriter, r *http.Request) {
		tenant, ok := tenantScope(w, r)
		if !ok {
			return
		}
		role := r.URL.Query().Get("role")
		pokemon, err := strconv.Atoi(r.URL.Query().Get("pokemon_id"))
		if err != nil || pokemon <= 0 || (role != "attacker" && role != "defender") {
			detail(w, 422, "valid role and positive pokemon_id are required")
			return
		}
		include := false
		if raw := r.URL.Query().Get("include_hidden"); raw != "" {
			include, err = strconv.ParseBool(raw)
			if err != nil {
				detail(w, 422, "invalid include_hidden")
				return
			}
		}
		result, err := store.List(r.Context(), tenant, role, pokemon, include)
		if err != nil {
			detail(w, 503, "configuration storage unavailable")
			return
		}
		writeJSON(w, 200, result)
	})
	// 保存命令同时用于 POST 和 PUT，避免二者的校验路径发生漂移。
	save := func(w http.ResponseWriter, r *http.Request) {
		tenant, ok := tenantScope(w, r)
		if !ok {
			return
		}
		var command configurations.Command
		if !decodeJSON(w, r, &command) {
			return
		}
		if err := command.Validate(); err != nil {
			detail(w, 400, err.Error())
			return
		}
		view, err := store.Save(r.Context(), tenant, r.PathValue("config_id"), command)
		if errors.Is(err, configurations.ErrNotFound) {
			detail(w, 400, err.Error())
			return
		}
		if err != nil {
			detail(w, 503, "configuration storage unavailable")
			return
		}
		status := 200
		if r.Method == "POST" {
			status = 201
		}
		writeJSON(w, status, view)
	}
	mux.HandleFunc("POST /v1/stat-configurations", save)
	mux.HandleFunc("PUT /v1/stat-configurations/{config_id}", save)
	mux.HandleFunc("DELETE /v1/stat-configurations/{config_id}", func(w http.ResponseWriter, r *http.Request) {
		tenant, ok := tenantScope(w, r)
		if !ok {
			return
		}
		err := store.Delete(r.Context(), tenant, r.PathValue("config_id"))
		if errors.Is(err, configurations.ErrNotFound) {
			detail(w, 404, err.Error())
			return
		}
		if err != nil {
			detail(w, 503, "configuration storage unavailable")
			return
		}
		w.WriteHeader(204)
	})
	mux.HandleFunc("POST /v1/stat-configurations/hidden", func(w http.ResponseWriter, r *http.Request) {
		tenant, ok := tenantScope(w, r)
		if !ok {
			return
		}
		var body struct {
			Role      string                   `json:"role"`
			Reference configurations.Reference `json:"reference"`
			Hidden    *bool                    `json:"hidden"`
		}
		if !decodeJSON(w, r, &body) {
			return
		}
		if body.Hidden == nil {
			detail(w, 422, "hidden is required")
			return
		}
		if err := store.Preferences(r.Context(), tenant, body.Role, []configurations.Reference{body.Reference}, body.Hidden); err != nil {
			preferenceError(w, err)
			return
		}
		w.WriteHeader(204)
	})
	mux.HandleFunc("POST /v1/stat-configurations/order", func(w http.ResponseWriter, r *http.Request) {
		tenant, ok := tenantScope(w, r)
		if !ok {
			return
		}
		var body struct {
			Role       string                     `json:"role"`
			References []configurations.Reference `json:"references"`
		}
		if !decodeJSON(w, r, &body) {
			return
		}
		if body.References == nil {
			detail(w, 422, "references are required")
			return
		}
		if err := store.Preferences(r.Context(), tenant, body.Role, body.References, nil); err != nil {
			preferenceError(w, err)
			return
		}
		w.WriteHeader(204)
	})
	registerCatalog(mux, db)
	registerCalculator(mux, db)
	registerAssets(mux, db)
	registerJobs(mux, db)
	registerConfigurationJobs(mux, db)
	registerJobSubmission(mux, db)
	registerConfigurationSolver(mux, db)
	registerLegacyDamage(mux, db)
	registerFixedInference(mux, db)
	sync := syncapi.NewHandler(syncstore.New(db), func(r *http.Request) (string, error) {
		user := strings.TrimSpace(r.Header.Get("X-Pokeop-User"))
		if user == "" {
			return "", errors.New("trusted user identity is required")
		}
		return user, nil
	})
	mux.Handle("/v1/sync", sync)
	return mux
}

// preferenceError 只公开业务拒绝；数据库驱动错误统一映射到可重试的 503。
func preferenceError(w http.ResponseWriter, err error) {
	if errors.Is(err, configurations.ErrInvalidPreference) || errors.Is(err, configurations.ErrNotFound) {
		detail(w, 400, err.Error())
		return
	}
	detail(w, 503, "configuration storage unavailable")
}

// tenantScope 沿用原可信网关注入 header 与开发默认值；不构成身份认证。
func tenantScope(w http.ResponseWriter, r *http.Request) (string, bool) {
	value, exists := r.Header["X-Pokeop-Tenant"]
	if !exists {
		return "default-tenant", true
	}
	tenant := ""
	if len(value) > 0 {
		tenant = strings.TrimSpace(value[0])
	}
	if tenant == "" {
		detail(w, 400, "tenant scope is empty")
		return "", false
	}
	return tenant, true
}

// decodeJSON 限制正文为 8 MiB 且必须只有一个 JSON 值，拒绝尾随请求和无效字段类型。
func decodeJSON(w http.ResponseWriter, r *http.Request, target any) bool {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	if err := decoder.Decode(target); err != nil {
		detail(w, 422, "invalid JSON request body")
		return false
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		detail(w, 422, "request must contain one JSON value")
		return false
	}
	return true
}

// writeJSON 输出 value 的协议模型；错误发生在写出前时返回稳定内部错误。
func writeJSON(w http.ResponseWriter, status int, value any) {
	data, err := json.Marshal(value)
	if err != nil {
		detail(w, 500, "response encoding failed")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(data)
}

// detail 沿用 FastAPI 的 detail 错误 envelope，不附带数据库和连接细节。
func detail(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(struct {
		Detail string `json:"detail"`
	}{message})
}
