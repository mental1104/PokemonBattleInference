// Package syncapi 通过有界 HTTP JSON 暴露持久化同步，不负责建立用户身份。
package syncapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"pokemonbattleinference/server/internal/syncmodels"
	"pokemonbattleinference/server/internal/syncstore"
	"strconv"
)

// UserResolver 由宿主认证层返回已验证用户标识；不得把不可信任意 header 当成生产认证。
type UserResolver func(*http.Request) (string, error)

// NewHandler 借用 store 和 resolve；返回只处理 GET/POST 的同步 handler，不启动后台任务。
// resolve 必须先认证请求，失败时返回 401，成功后所有 SQL 都使用该用户作用域。
func NewHandler(store *syncstore.Store, resolve UserResolver) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if resolve == nil {
			failure(w, 503, "identity_unavailable")
			return
		}
		user, err := resolve(r)
		if err != nil || user == "" {
			failure(w, 401, "unauthorized")
			return
		}
		switch r.Method {
		case http.MethodGet:
			after := int64(0)
			limit := 100
			if value := r.URL.Query().Get("after"); value != "" {
				after, err = strconv.ParseInt(value, 10, 64)
				if err != nil {
					failure(w, 400, "invalid_cursor")
					return
				}
			}
			if value := r.URL.Query().Get("limit"); value != "" {
				limit, err = strconv.Atoi(value)
				if err != nil {
					failure(w, 400, "invalid_limit")
					return
				}
			}
			if after < 0 || limit < 1 || limit > 200 {
				failure(w, 400, "invalid_page")
				return
			}
			page, readErr := store.Changes(r.Context(), user, after, limit)
			if readErr != nil {
				failure(w, 503, "storage_unavailable")
				return
			}
			_ = json.NewEncoder(w).Encode(page)
		case http.MethodPost:
			decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 2*1024*1024))
			decoder.DisallowUnknownFields()
			var op syncmodels.Operation
			if decoder.Decode(&op) != nil {
				failure(w, 400, "invalid_operation")
				return
			}
			var extra json.RawMessage
			if decoder.Decode(&extra) != io.EOF {
				failure(w, 400, "trailing_json")
				return
			}
			if op.Validate() != nil {
				failure(w, 400, "invalid_operation")
				return
			}
			result, applyErr := store.Apply(r.Context(), user, op)
			if errors.Is(applyErr, syncstore.ErrOperationReuse) {
				failure(w, 409, "operation_reused")
				return
			}
			if applyErr != nil {
				failure(w, 503, "storage_unavailable")
				return
			}
			_ = json.NewEncoder(w).Encode(result)
		default:
			w.Header().Set("Allow", "GET, POST")
			failure(w, 405, "method_not_allowed")
		}
	})
}

// failure 将 status 与稳定 ASCII code 写给 w；隐藏 SQL 和内部异常内容。
func failure(w http.ResponseWriter, status int, code string) {
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(struct {
		Error string `json:"error"`
	}{code})
}
