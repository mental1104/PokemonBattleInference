// Package workerprocess 通过子进程执行复杂原生请求，将崩溃边界放在 HTTP 进程之外。
package workerprocess

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"pokemonbattleinference/server/internal/corebridge"
)

// ErrOutputLimit 表示子进程违反响应大小合同。
var ErrOutputLimit = errors.New("worker output limit exceeded")

// Failure 保留可持久化的错误种类和退出码，不携带潜在敏感 stderr。
type Failure struct {
	Code     string
	ExitCode int
}

// Error 返回简短 ASCII 诊断，调用方可用 Code 决定重试或失败。
func (failure *Failure) Error() string {
	return fmt.Sprintf("worker failed: code=%s exit=%d", failure.Code, failure.ExitCode)
}

// limitedBuffer 为子进程输出设定硬内存上限；超限立即停止接收且不扩大容量。
type limitedBuffer struct {
	buffer   bytes.Buffer
	max      int
	overflow bool
}

// Write 只接受尚未超限的 data，返回 ErrOutputLimit 后 exec 会关闭对应管道。
func (buffer *limitedBuffer) Write(data []byte) (int, error) {
	if buffer.overflow {
		return 0, ErrOutputLimit
	}
	remaining := buffer.max - buffer.buffer.Len()
	if len(data) > remaining {
		_, _ = buffer.buffer.Write(data[:remaining])
		buffer.overflow = true
		return remaining, ErrOutputLimit
	}
	return buffer.buffer.Write(data)
}

// Execute 用绝对 executable 执行一份 request；ctx 取消会杀死并回收子进程。
// 返回 stdout 的独立副本及稳定 Failure；没有 shell、任意附加参数或 Python fallback。
// 原生状态 1..5 保留 ABI 分类，其他退出或信号记为 worker_crash。
func Execute(ctx context.Context, executable string, request []byte) ([]byte, error) {
	if !filepath.IsAbs(executable) {
		return nil, errors.New("worker executable must be absolute")
	}
	if len(request) > corebridge.MaxRequestBytes {
		return nil, &Failure{Code: "resource_limit", ExitCode: 3}
	}
	output := limitedBuffer{max: 32 << 20}
	diagnostic := limitedBuffer{max: 4 << 10}
	command := exec.CommandContext(ctx, executable)
	command.Stdin = bytes.NewReader(request)
	command.Stdout = &output
	command.Stderr = &diagnostic
	err := command.Run()
	result := append([]byte(nil), output.buffer.Bytes()...)
	if ctx.Err() != nil {
		return result, ctx.Err()
	}
	if output.overflow {
		return nil, ErrOutputLimit
	}
	if err == nil {
		return result, nil
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		code := exit.ExitCode()
		kinds := map[int]string{1: "invalid_input", 2: "unsupported", 3: "resource_limit", 4: "cancelled", 5: "internal_error"}
		kind, exists := kinds[code]
		if !exists {
			kind = "worker_crash"
		}
		return result, &Failure{Code: kind, ExitCode: code}
	}
	if errors.Is(err, io.ErrShortWrite) {
		return result, ErrOutputLimit
	}
	return nil, err
}
