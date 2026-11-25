#include "progress.h"

/// cgo 导出的 Go 回调；frame 仅同步借用，Go 必须复制字段，不保留 C 栈地址。
extern void pbiGoProgressV1(pbi_progress_v1* frame, uintptr_t handle);

/// @param frame Core 同步借用帧；@param handle Go 拥有的数值句柄；复制到 C 栈后同步转发。
static void forward_progress(const pbi_progress_v1* frame, uintptr_t handle) {
  pbi_progress_v1 copy = *frame;
  pbiGoProgressV1(&copy, handle);
}

pbi_status_v1 pbi_go_compute_with_progress(const uint8_t* request, size_t request_size,
    const pbi_cancel_token_v1* token, uintptr_t handle, pbi_buffer_v1* output) {
  return pbi_v1_compute_with_progress(request, request_size, token, forward_progress, handle, output);
}
