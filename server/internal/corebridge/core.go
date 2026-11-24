// Package corebridge 只适配版本化 C ABI，不实现任何宝可梦计算规则。
package corebridge

/*
#cgo CFLAGS: -I${SRCDIR}/../../../contracts/c
#cgo linux LDFLAGS: -lpbi_abi -lpbi_core -lstdc++ -lm
#cgo darwin LDFLAGS: -lpbi_abi -lpbi_core -lc++
#include "pbi_core.h"
#include "progress.h"
#include <stdlib.h>
*/
import "C"

import (
	"context"
	"fmt"
	"runtime/cgo"
	"unsafe"
)

// Status 表示原生层的稳定 v1 错误分类，与 contracts/c/pbi_core.h 对齐。
type Status int

// MaxRequestBytes 来自同一 C 头文件，避免 Go 在 C.CBytes 前复制超限输入。
const MaxRequestBytes = C.PBI_V1_MAX_REQUEST_BYTES

// MaxResultBytes 来自同一 C 合同，进程协议和 Go 复制均遵循同一结果上限。
const MaxResultBytes = C.PBI_V1_MAX_RESULT_BYTES

// MaxOperations/MaxGraphNodes/MaxGraphEdges 用于进程协议计数校验，来自唯一 C 资源合同。
const MaxOperations = C.PBI_V1_MAX_OPERATIONS
const MaxGraphNodes = C.PBI_V1_MAX_GRAPH_NODES
const MaxGraphEdges = C.PBI_V1_MAX_GRAPH_EDGES

// MaxGeneratedNodes/MaxGeneratedEdges 是在线生成图预算，独立于显式拓扑的 JSON 输入预算。
const MaxGeneratedNodes = C.PBI_V1_MAX_GENERATED_NODES
const MaxGeneratedEdges = C.PBI_V1_MAX_GENERATED_EDGES

const (
	InvalidInput  Status = 1
	Unsupported   Status = 2
	ResourceLimit Status = 3
	Cancelled     Status = 4
	InternalError Status = 5
)

// Failure 保存错误码；正文作为 Compute 返回值独立拥有，不引用 C 内存。
type Failure struct{ Status Status }

// Error 返回可供日志使用的 ASCII 消息，无参数，不暴露原始请求。
func (failure *Failure) Error() string {
	return fmt.Sprintf("native calculation failed: status=%d", failure.Status)
}

// EngineVersion 返回 Core 拥有的静态版本字符串的 Go 副本，无需调用者释放。
func EngineVersion() string { return C.GoString(C.pbi_v1_engine_version()) }

// Compute 同步执行 JSON 批次，返回 Go 独占的响应字节和稳定错误。
// ctx 不得为 nil，取消/超时会传到原生令牌；request 仅在复制阶段读取，不保留 Go 指针。
// 无论成功或失败均释放原生缓冲区；取消监视 goroutine 退出后才销毁令牌。
// CGO 不能隔离 SIGSEGV/abort，生产复杂推演仍须放在独立 Worker 进程。
func Compute(ctx context.Context, request []byte) ([]byte, error) {
	return compute(ctx, request, nil)
}

// ComputeWithProgress 执行正式批次，并在当前原生计算线程同步调用 onProgress。
// ctx/request 的借用和释放同 Compute；onProgress 可为 nil，不得长时间阻塞或执行数据库操作。
// 观察者收到拥有值；句柄在全部同步回调及 C 调用返回后删除，panic 转为 ErrProgressCallback。
func ComputeWithProgress(ctx context.Context, request []byte, onProgress func(Progress)) ([]byte, error) {
	return compute(ctx, request, onProgress)
}

// compute 拥有一次调用的 C 输入/结果/令牌/观察者句柄；onProgress 为可空同步只读观察函数。
// 返回独占响应和稳定错误；先结束取消监视，再释放令牌，不跨语言保留 Go 指针。
func compute(ctx context.Context, request []byte, onProgress func(Progress)) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if len(request) > MaxRequestBytes {
		return nil, &Failure{Status: ResourceLimit}
	}
	token := C.pbi_v1_cancel_token_create()
	if token == nil {
		return nil, &Failure{Status: ResourceLimit}
	}
	defer C.pbi_v1_cancel_token_destroy(token)
	input := C.CBytes(request)
	defer C.free(input)
	var output C.pbi_buffer_v1
	defer C.pbi_v1_buffer_release(&output)
	var observer *progressObserver
	var handle cgo.Handle
	if onProgress != nil {
		observer = &progressObserver{handler: onProgress, token: token}
		handle = cgo.NewHandle(observer)
		defer handle.Delete()
	}
	done, watcherDone := make(chan struct{}), make(chan struct{})
	// 令牌仍由当前调用拥有；done/watcherDone 保证取消与释放不会竞争。
	go func() {
		defer close(watcherDone)
		select {
		case <-ctx.Done():
			C.pbi_v1_cancel_request(token)
		case <-done:
		}
	}()
	var status C.pbi_status_v1
	if observer == nil {
		status = C.pbi_v1_compute((*C.uint8_t)(input), C.size_t(len(request)), token, &output)
	} else {
		status = C.pbi_go_compute_with_progress((*C.uint8_t)(input), C.size_t(len(request)), token, C.uintptr_t(handle), &output)
	}
	close(done)
	<-watcherDone
	if observer != nil && observer.failed.Load() {
		return nil, ErrProgressCallback
	}
	if uint64(output.size) > MaxResultBytes {
		return nil, &Failure{Status: InternalError}
	}
	response := C.GoBytes(unsafe.Pointer(output.data), C.int(output.size))
	if status != C.PBI_OK_V1 {
		if status == C.PBI_CANCELLED_V1 && ctx.Err() != nil {
			return response, ctx.Err()
		}
		return response, &Failure{Status: Status(status)}
	}
	return response, nil
}
