/* 使用真正的 C 编译器调用同一库，验证头文件没有泄漏 C++ 类型或异常标记。 */
#include "pbi_core.h"

/* 无参数；成功版本化计算并释放结果返回 0，任一 ABI 合同不符返回 1。 */
int main(void) {
  const uint8_t request[] = "{\"schema_version\":1,\"operations\":[{\"kind\":\"stage\",\"value\":110,\"stage\":-1}]}";
  pbi_buffer_v1 output = {0};
  const pbi_status_v1 status = pbi_v1_compute(request, sizeof(request) - 1, NULL, &output);
  const int valid = pbi_v1_abi_version() == 1 && status == PBI_OK_V1 && output.size > 0;
  pbi_v1_buffer_release(&output);
  pbi_v1_buffer_release(&output);
  return valid && output.data == NULL && output.size == 0 ? 0 : 1;
}
