// Package httpapi 把 HTTP 生命周期和原生 JSON 合同接通，不重复实现计算规则。
package httpapi

import (
	"context"
	"errors"
	"io"
	"net/http"
	"pokemonbattleinference/server/internal/corebridge"
)

// Handler 返回首批 Core HTTP 路由；无外部依赖，无启动后台任务。
// 现有 FastAPI 路由尚未迁移，本服务不能替换原 Web 后端。
func Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", health)
	mux.HandleFunc("POST /v1/core/calculate", calculate)
	return mux
}

// health 用静态 JSON 返回就绪状态；writer 接收响应，request 不读取正文。
func health(writer http.ResponseWriter, request *http.Request) {
	writer.Header().Set("Content-Type", "application/json")
	_, _ = io.WriteString(writer, `{"status":"ok"}`)
}

// calculate 读取最多 8 MiB 批次并借用 request.Context 传播断开/超时。
// writer 接收 Core 生成的完整响应；任何原生错误均不伪装为 HTTP 成功。
func calculate(writer http.ResponseWriter, request *http.Request) {
	writer.Header().Set("Content-Type", "application/json")
	body, err := io.ReadAll(http.MaxBytesReader(writer, request.Body, corebridge.MaxRequestBytes))
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			writer.WriteHeader(http.StatusRequestEntityTooLarge)
		} else {
			writer.WriteHeader(http.StatusBadRequest)
		}
		_, _ = io.WriteString(writer, `{"error":{"code":"invalid_body","message":"cannot read request body"}}`)
		return
	}
	response, err := corebridge.Compute(request.Context(), body)
	status := http.StatusOK
	if err != nil {
		var failure *corebridge.Failure
		switch {
		case errors.Is(err, context.Canceled):
			status = http.StatusRequestTimeout
		case errors.Is(err, context.DeadlineExceeded):
			status = http.StatusGatewayTimeout
		case errors.As(err, &failure):
			switch failure.Status {
			case corebridge.InvalidInput:
				status = http.StatusBadRequest
			case corebridge.Unsupported:
				status = http.StatusUnprocessableEntity
			case corebridge.ResourceLimit:
				status = http.StatusRequestEntityTooLarge
			case corebridge.Cancelled:
				status = http.StatusRequestTimeout
			default:
				status = http.StatusInternalServerError
			}
		default:
			status = http.StatusInternalServerError
		}
		if len(response) == 0 {
			response = []byte(`{"error":{"code":"native_error","message":"calculation failed"}}`)
		}
	}
	writer.WriteHeader(status)
	_, _ = writer.Write(response)
}
