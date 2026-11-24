#ifndef PBI_GO_PROGRESS_H
#define PBI_GO_PROGRESS_H
#include "pbi_core.h"

/// Go 桥私有入口；handle 为 cgo.Handle 数值，所有回调和 compute 返回后才由 Go 删除。
/// @param request 借用只读字节；@param request_size 字节数；@param token 借用的可空取消令牌。
/// @param handle 同步观察者句柄；@param output 零初始化结果；@return 正式 ABI 状态。
pbi_status_v1 pbi_go_compute_with_progress(const uint8_t* request, size_t request_size,
    const pbi_cancel_token_v1* token, uintptr_t handle, pbi_buffer_v1* output);
#endif
