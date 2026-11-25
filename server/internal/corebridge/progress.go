package corebridge

/*
#include "progress.h"
*/
import "C"

import (
	"errors"
	"runtime/cgo"
	"sync/atomic"
)

// ProgressPhase 是真实构图的稳定阶段，不表示任务调度或心跳阶段。
type ProgressPhase string

const (
	ProgressBuilding ProgressPhase = "building"
	ProgressBuilt    ProgressPhase = "built"
)

// Progress 是一个拥有完整计数的 Go 副本，不借用 C 的 frame 或图节点。
type Progress struct {
	OperationIndex uint32        `json:"operation_index"`
	Phase          ProgressPhase `json:"phase"`
	Nodes          uint64        `json:"nodes"`
	Edges          uint64        `json:"edges"`
	Expanded       uint64        `json:"expanded"`
	Frontier       uint64        `json:"frontier"`
}

// ErrProgressCallback 表示调用者观察回调失败；不能让 panic 跨过 C 栈或交付部分计算。
var ErrProgressCallback = errors.New("native progress callback failed")

// progressObserver 由一次 Compute 拥有，C 只得到 cgo.Handle 整数；同步回调结束前不会销毁。
type progressObserver struct {
	handler func(Progress)
	token   *C.pbi_cancel_token_v1
	failed  atomic.Bool
}

// pbiGoProgressV1 从 C 同步接收只读 frame；handle 由当前调用持有，字段复制后才调用 Go 观察者。
// 回调 panic 被转换为取消和稳定错误，不允许异常跨语言栈，也不记录可能敏感的 panic 值。
//
//export pbiGoProgressV1
func pbiGoProgressV1(frame *C.pbi_progress_v1, handle C.uintptr_t) {
	observer := cgo.Handle(handle).Value().(*progressObserver)
	defer func() {
		if recover() != nil {
			observer.failed.Store(true)
			C.pbi_v1_cancel_request(observer.token)
		}
	}()
	if frame == nil || uint32(frame.struct_size) < uint32(C.sizeof_pbi_progress_v1) {
		observer.failed.Store(true)
		C.pbi_v1_cancel_request(observer.token)
		return
	}
	phase := ProgressBuilding
	if frame.phase == C.PBI_PROGRESS_BUILT_V1 {
		phase = ProgressBuilt
	} else if frame.phase != C.PBI_PROGRESS_BUILDING_V1 {
		observer.failed.Store(true)
		C.pbi_v1_cancel_request(observer.token)
		return
	}
	observer.handler(Progress{OperationIndex: uint32(frame.operation_index), Phase: phase,
		Nodes: uint64(frame.nodes), Edges: uint64(frame.edges), Expanded: uint64(frame.expanded), Frontier: uint64(frame.frontier)})
}
