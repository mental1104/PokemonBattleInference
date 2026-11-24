// Package corebridge 只适配版本化 C ABI，不实现任何宝可梦计算规则。
package corebridge

/*
#cgo CFLAGS: -I${SRCDIR}/../../../contracts/c
#cgo linux LDFLAGS: -lpbi_abi -lpbi_core -lstdc++ -lm
#cgo darwin LDFLAGS: -lpbi_abi -lpbi_core -lc++
#include "pbi_core.h"
#include <stdlib.h>
*/
import "C"

import (
	"context"
	"fmt"
	"unsafe"
)

// Status 表示原生层的稳定 v1 错误分类，与 contracts/c/pbi_core.h 对齐。
type Status int

// MaxRequestBytes 来自同一 C 头文件，避免 Go 在 C.CBytes 前复制超限输入。
const MaxRequestBytes = C.PBI_V1_MAX_REQUEST_BYTES

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
	status := C.pbi_v1_compute((*C.uint8_t)(input), C.size_t(len(request)), token, &output)
	close(done)
	<-watcherDone
	if uint64(output.size) > 1<<31-1 {
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
