#ifndef PBI_CORE_V1_H
#define PBI_CORE_V1_H

#include <stddef.h>
#include <stdint.h>

/// v1 固定资源合同；调用方可以在复制大输入前拒绝超限，不重复计算规则。
#define PBI_V1_MAX_REQUEST_BYTES (8u * 1024u * 1024u)
#define PBI_V1_MAX_OPERATIONS 4096u
#define PBI_V1_MAX_ROLLS 65536u
#define PBI_V1_MAX_TOTAL_ROLLS (1024u * 1024u)
/// 显式 JSON 拓扑的批次输入预算；该 graph 操作单图消元至多 128 瞬态节点，DAG 不受此限。
#define PBI_V1_MAX_GRAPH_NODES 65536u
#define PBI_V1_MAX_GRAPH_EDGES 262144u
#define PBI_V1_MAX_EQUATION_NODES 128u
#define PBI_V1_MAX_RESULT_BYTES (32u * 1024u * 1024u)
/// 生成图任务沿用原在线能力上限，与显式 JSON 拓扑输入预算分开。
#define PBI_V1_MAX_GENERATED_NODES 2000000u
#define PBI_V1_MAX_GENERATED_EDGES 8000000u
/// 结果输出保护不改变领域概率；超限明确整批失败，不把保护截断算作数学平局。
#define PBI_V1_MAX_RESULT_EVENT_PATHS (1024u * 1024u)
#define PBI_V1_MAX_RESULT_EVENTS (1024u * 1024u)
#define PBI_V1_MAX_INFERENCE_TURNS 10000u

#ifdef __cplusplus
#define PBI_NOEXCEPT noexcept
extern "C" {
#else
#define PBI_NOEXCEPT
#endif

/// v1 ABI 的稳定错误码；JSON 响应提供同义字符串，不通过线程全局状态传错。
typedef enum pbi_status_v1 {
  PBI_OK_V1 = 0,
  PBI_INVALID_INPUT_V1 = 1,
  PBI_UNSUPPORTED_V1 = 2,
  PBI_RESOURCE_LIMIT_V1 = 3,
  PBI_CANCELLED_V1 = 4,
  PBI_INTERNAL_ERROR_V1 = 5
} pbi_status_v1;

/// Core 独占分配的 UTF-8 JSON 字节，不保证 NUL 终止；调用者必须零初始化。
/// data/size 仅供读取；通过 pbi_v1_buffer_release 释放，不跨 allocator free。
typedef struct pbi_buffer_v1 {
  uint8_t* data;
  size_t size;
} pbi_buffer_v1;

/// 单向取消令牌；创建者拥有，所有借用它的 compute 返回后才能销毁。
typedef struct pbi_cancel_token_v1 pbi_cancel_token_v1;

/// 真实构图进度的两个稳定阶段；不把线程启动或心跳当成节点进展。
typedef enum pbi_progress_phase_v1 {
  PBI_PROGRESS_BUILDING_V1 = 0,
  PBI_PROGRESS_BUILT_V1 = 1
} pbi_progress_phase_v1;

/// 一次实际构图观察帧；所有计数均来自同一次调用，不包含指向 Core 状态的指针。
typedef struct pbi_progress_v1 {
  uint32_t struct_size;
  uint32_t operation_index;
  pbi_progress_phase_v1 phase;
  uint64_t nodes;
  uint64_t edges;
  uint64_t expanded;
  uint64_t frontier;
} pbi_progress_v1;

/// 回调在 compute 的调用线程同步执行；frame 仅借用至本次回调返回，不可保留其指针。
/// user_data 是调用者原样传入的数值句柄；Core 不解引用、不取得所有权。
/// 回调不得抛 C++ 异常、语言异常或长时间阻塞；需要持久化时先复制帧再交给外部循环。
typedef void (*pbi_progress_callback_v1)(const pbi_progress_v1* frame, uintptr_t user_data);

/// @return 静态 ABI 版本 1；无所有权转移，可并发调用。
uint32_t pbi_v1_abi_version(void) PBI_NOEXCEPT;

/// @return 静态 NUL 终止的引擎版本字符串，调用者不得释放或修改。
const char* pbi_v1_engine_version(void) PBI_NOEXCEPT;

/// @return 新的未取消令牌；分配失败返回 NULL，无异常越过 C 边界。
pbi_cancel_token_v1* pbi_v1_cancel_token_create(void) PBI_NOEXCEPT;

/// 永久置为取消；可与多个 compute 并发调用，不能重置复用为未取消。
/// @param token 借用的令牌，可为 NULL（无操作）；不取得所有权。
void pbi_v1_cancel_request(pbi_cancel_token_v1* token) PBI_NOEXCEPT;

/// @param token 拥有的令牌，可为 NULL；调用时不得有并发读写或计算。
void pbi_v1_cancel_token_destroy(pbi_cancel_token_v1* token) PBI_NOEXCEPT;

/// 执行版本化 JSON 批次；按输入顺序返回，任一错误/取消使整批无业务结果。
/// @param request 只读 UTF-8 字节，借用至函数返回；不得为 NULL。
/// @param request_size 实际字节数，不含结束符，最多 8 MiB。
/// @param cancellation 可为 NULL；非 NULL 时借用至函数返回，不修改调用者数据。
/// @param output 必须非 NULL 且 data=NULL/size=0；成功或错误 JSON 的所有权转给调用者。
/// @return 稳定状态码；参数无效或内存耗尽时可能无 JSON。任何 C++ 异常均被隔离。
/// 独立 output/输入可并发调用；调用者取消与最后一次提交检查竞争时，已完成结果可为 OK。
pbi_status_v1 pbi_v1_compute(const uint8_t* request, size_t request_size,
                            const pbi_cancel_token_v1* cancellation,
                            pbi_buffer_v1* output) PBI_NOEXCEPT;

/// 与 pbi_v1_compute 相同的正式批次，额外允许观察真实 fixed_battle 构图进度。
/// @param request 只读 UTF-8 请求，借用至函数返回；@param request_size 实际字节数，不含结束符。
/// @param cancellation 可空共享令牌；取消仍撤销整批，已经报告的进度不代表成功。
/// @param progress 可空同步回调；没有构图的操作不会制造进度帧，回调次数可以为零。
/// @param user_data 调用者拥有的数值上下文，必须在 compute 和全部同步回调返回后才销毁。
/// @param output 零初始化输出；@return 与 compute 相同的错误及拥有结果，不改变 ABI/schema 版本。
pbi_status_v1 pbi_v1_compute_with_progress(const uint8_t* request, size_t request_size,
                            const pbi_cancel_token_v1* cancellation,
                            pbi_progress_callback_v1 progress, uintptr_t user_data,
                            pbi_buffer_v1* output) PBI_NOEXCEPT;

/// @param buffer Core 返回的拥有型缓冲区，可为 NULL；释放后清零，可重复释放。
/// 不允许与读取/计算并发；不得放入外部分配的指针。
void pbi_v1_buffer_release(pbi_buffer_v1* buffer) PBI_NOEXCEPT;

#ifdef __cplusplus
}
#endif
#undef PBI_NOEXCEPT
#endif
