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
	progressMode := len(os.Args) == 2 && os.Args[1] == "--progress"
	if len(os.Args) != 1 && !progressMode {
		_, _ = io.WriteString(os.Stderr, "unsupported worker arguments\n")
		return 64
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	body, err := io.ReadAll(io.LimitReader(os.Stdin, corebridge.MaxRequestBytes+1))
	if err != nil || len(body) > corebridge.MaxRequestBytes {
		_ = writeResult([]byte(`{"error":{"code":"resource_limit","message":"request exceeds worker limit"}}`), progressMode)
		return 3
	}
	var response []byte
	if progressMode {
		encoder := json.NewEncoder(os.Stdout)
		emitted := 0
		var previous corebridge.Progress
		hasPrevious := false
		response, err = corebridge.ComputeWithProgress(ctx, body, func(progress corebridge.Progress) {
			// 只在实际节点/边/展开量有足够增量时发送中间帧；不改变 Core 回调或任何业务事件。
			if progress.Phase != corebridge.ProgressBuilt && hasPrevious && progress.OperationIndex == previous.OperationIndex &&
				progress.Nodes >= previous.Nodes && progress.Edges >= previous.Edges && progress.Expanded >= previous.Expanded &&
				progress.Nodes-previous.Nodes < 256 && progress.Edges-previous.Edges < 1024 && progress.Expanded-previous.Expanded < 256 {
				return
			}
			// 末 built 必发；额外总限只合并观察帧，永不丢弃事件或唯一最终结果。
			if emitted >= 32768 && progress.Phase != corebridge.ProgressBuilt {
				return
			}
			previous, hasPrevious = progress, true
			emitted++
			if encodeErr := encoder.Encode(struct {
				Kind     string              `json:"kind"`
				Progress corebridge.Progress `json:"progress"`
			}{Kind: "progress", Progress: progress}); encodeErr != nil {
				// bridge 会截获观察者 panic，取消 Core，随后按稳定失败处理；不跨 C 栈抛出。
				panic(encodeErr)
			}
		})
	} else {
		response, err = corebridge.Compute(ctx, body)
	}
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
		if writeErr := writeResult(response, progressMode); writeErr != nil {
			return 5
		}
	}
	return status
}

// writeResult 原样保留完整 ABI response 字节；progressMode 只增加固定 NDJSON 外壳，不重编结果 JSON。
// response 只读且必须合法 JSON；返回实际输出错误，末帧失败不能被父进程当成成功。
func writeResult(response []byte, progressMode bool) error {
	if !progressMode {
		_, err := os.Stdout.Write(response)
		return err
	}
	if _, err := io.WriteString(os.Stdout, `{"kind":"result","response":`); err != nil {
		return err
	}
	if _, err := os.Stdout.Write(response); err != nil {
		return err
	}
	_, err := io.WriteString(os.Stdout, "}\n")
	return err
}
