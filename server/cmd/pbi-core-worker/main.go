// pbi-core-worker 单次进程只执行一份 Core JSON 请求，隔离原生 abort/段错误。
package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/signal"
	"pokemonbattleinference/server/internal/corebridge"
	"syscall"
)

// main 从 stdin 读取有界请求并向 stdout 写完整 ABI 响应；非零退出码对应稳定错误类别。
// SIGTERM 请求原生取消；SIGKILL、SIGSEGV 或 abort 只能终止本 Worker，不影响 HTTP 进程。
func main() { os.Exit(run()) }

// run 返回进程退出码；所有原生资源在返回前由 corebridge 释放，stderr 不记录请求正文。
func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	body, err := io.ReadAll(io.LimitReader(os.Stdin, corebridge.MaxRequestBytes+1))
	if err != nil || len(body) > corebridge.MaxRequestBytes {
		_, _ = io.WriteString(os.Stdout, `{"error":{"code":"resource_limit","message":"request exceeds worker limit"}}`)
		return 3
	}
	response, err := corebridge.Compute(ctx, body)
	status := 0
	if err != nil {
		status = 5
		var failure *corebridge.Failure
		if errors.As(err, &failure) {
			status = int(failure.Status)
		} else if errors.Is(err, context.Canceled) {
			status = 4
		}
		if len(response) == 0 {
			codes := map[int]string{1: "invalid_input", 2: "unsupported", 3: "resource_limit", 4: "cancelled", 5: "internal_error"}
			// 空缓冲区错误同样输出明确帧，父进程不会把 runtime exit=2 混同于合法拒绝。
			response, _ = json.Marshal(struct {
				Error struct {
					Code string `json:"code"`
				} `json:"error"`
			}{Error: struct {
				Code string `json:"code"`
			}{codes[status]}})
		}
	}
	if len(response) > 0 {
		if _, writeErr := os.Stdout.Write(response); writeErr != nil {
			return 5
		}
	}
	return status
}
