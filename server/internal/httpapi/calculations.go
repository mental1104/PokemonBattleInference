// Package httpapi 只适配 HTTP/数据生命周期，所有 Core 计算统一在独立子进程执行。
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/corebridge"
	"pokemonbattleinference/server/internal/workerprocess"
	"time"
)

// Handler 返回无数据库依赖的 Core HTTP 路由；每个计算请求均使用真实 Worker。
func Handler() http.Handler { return baseMux() }

// configuredWorker 优先读取显式绝对路径，否则仅查 server 可执行文件同目录的固定名字。
// 无法定位时返回空路径，计算接口明确 503；不搜索 PATH，也不回退到 in-process CGO。
func configuredWorker() string {
	if value := os.Getenv("PBI_CORE_WORKER_PATH"); value != "" {
		return value
	}
	executable, err := os.Executable()
	if err != nil {
		return ""
	}
	return filepath.Join(filepath.Dir(executable), "pbi-core-worker")
}

// baseMux 建立共享健康和计算路由；Worker 路径在 handler 创建时冻结，不随请求变化。
func baseMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", health)
	mux.Handle("POST /v1/core/calculate", coreHandler{worker: configuredWorker(), timeout: 30 * time.Second})
	return mux
}

// health 用静态 JSON 返回进程存活状态，不逐次调用数据库或 Worker。
func health(writer http.ResponseWriter, request *http.Request) {
	writer.Header().Set("Content-Type", "application/json")
	_, _ = io.WriteString(writer, `{"status":"ok"}`)
}

// coreHandler 借用绝对可执行路径，每个请求都有独立进程和 stdout/ctx 生命周期。
type coreHandler struct {
	worker  string
	timeout time.Duration
}

// ServeHTTP 读取有界 JSON 并转发 Worker；完整保留原生成功/拒绝正文和原 HTTP 状态映射。
// request.Context 取消会终止并回收子进程；缺失 Worker 或崩溃不会进入 HTTP 进程中的 CGO。
func (handler coreHandler) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	writer.Header().Set("Content-Type", "application/json")
	ctx, cancel := context.WithTimeout(request.Context(), handler.timeout)
	defer cancel()
	body, err := io.ReadAll(http.MaxBytesReader(writer, request.Body, corebridge.MaxRequestBytes))
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			writer.WriteHeader(413)
		} else {
			writer.WriteHeader(400)
		}
		_, _ = io.WriteString(writer, `{"error":{"code":"invalid_body","message":"cannot read request body"}}`)
		return
	}
	if !filepath.IsAbs(handler.worker) {
		workerError(writer, 503, "worker_unavailable", "isolated calculation worker is unavailable")
		return
	}
	info, err := os.Stat(handler.worker)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		workerError(writer, 503, "worker_unavailable", "isolated calculation worker is unavailable")
		return
	}
	response, err := workerprocess.Execute(ctx, handler.worker, body)
	status := 200
	if err != nil {
		var failure *workerprocess.Failure
		switch {
		case errors.Is(err, context.Canceled):
			workerError(writer, 408, "cancelled", "calculation request was cancelled")
			return
		case errors.Is(err, context.DeadlineExceeded):
			workerError(writer, 504, "cancelled", "calculation request exceeded its deadline")
			return
		case errors.Is(err, workerprocess.ErrOutputLimit):
			workerError(writer, 413, "resource_limit", "worker response limit exceeded")
			return
		case errors.As(err, &failure):
			switch failure.Code {
			case "invalid_input":
				status = 400
			case "unsupported":
				status = 422
			case "resource_limit":
				status = 413
			case "cancelled":
				status = 408
			case "internal_error":
				status = 500
			default:
				workerError(writer, 500, "worker_crash", "isolated calculation worker failed")
				return
			}
		default:
			workerError(writer, 503, "worker_unavailable", "isolated calculation worker is unavailable")
			return
		}
	}
	if !json.Valid(response) {
		workerError(writer, 500, "invalid_worker_response", "isolated calculation worker returned an invalid response")
		return
	}
	writer.WriteHeader(status)
	_, _ = writer.Write(response)
}

// workerError 返回稳定基础错误帧，不输出路径、stderr、请求内容或不完整结果。
func workerError(writer http.ResponseWriter, status int, code, message string) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(struct {
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}{Error: struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	}{code, message}})
}
