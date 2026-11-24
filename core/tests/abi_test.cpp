#include "pbi_core.h"
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <fstream>
#include <future>
#include <iterator>
#include <memory>
#include <string>
#include <vector>

namespace {
using Json = nlohmann::json;

/// 测试层 RAII 持有 C 返回缓冲区；栈退出和解析失败均归还相同 allocator。
struct OwnedBuffer {
  pbi_buffer_v1 value{};
  /// 析构时释放结果；不释放栈上描述符本身。
  ~OwnedBuffer() { pbi_v1_buffer_release(&value); }
};

/// 一次调用的独立结果，正文已复制，不借用 C 的任何内存。
struct CallResult { pbi_status_v1 status; Json body; };

/// @param name 共享向量文件名；@return 完整文件内容，打开失败抛出异常使测试失败。
std::string Fixture(const char* name) {
  std::ifstream input(std::string{PBI_VECTOR_DIR} + "/" + name);
  if (!input) throw std::runtime_error("cannot open ABI fixture");
  return {std::istreambuf_iterator<char>{input}, std::istreambuf_iterator<char>{}};
}

/// @param input 完整 JSON 文本；@param token 可空借用令牌；@return 释放 C 内存后的结果副本。
CallResult Call(const std::string& input, const pbi_cancel_token_v1* token = nullptr) {
  OwnedBuffer output;
  const auto status = pbi_v1_compute(reinterpret_cast<const std::uint8_t*>(input.data()), input.size(), token, &output.value);
  const auto body = output.value.data
      ? Json::parse(output.value.data, output.value.data + output.value.size) : Json{};
  return {status, body};
}

/// 所有语言使用同一固定文件核对版本、字段、槽位和完整批次结果。
TEST(CAbi, SharedFixtureAndVersion) {
  EXPECT_EQ(pbi_v1_abi_version(), 1U);
  EXPECT_STREQ(pbi_v1_engine_version(), "0.1.0");
  const auto result = Call(Fixture("abi-calculations.v1.request.json"));
  EXPECT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body, Json::parse(Fixture("abi-calculations.v1.response.json")));
}

/// 类型错误、未知字段/操作/版本及领域错误必须保留明确错误码，不能得到部分结果。
TEST(CAbi, InvalidAndUnsupportedRequests) {
  const std::vector<std::string> invalid{
      "", "{", "null", R"({"schema_version":true,"operations":[]})",
      R"({"schema_version":1,"operations":[{"kind":"stage","value":true,"stage":0}]})",
      R"({"schema_version":1,"operations":[{"kind":"stage","value":18446744073709551615,"stage":0}]})",
      R"({"schema_version":1,"operations":[{"kind":"stage","value":100,"stage":7}]})",
      R"({"schema_version":1,"operations":[{"kind":"ko","defender_hp":1,"rolls":[]}]})",
      R"({"schema_version":1,"operations":[{"kind":"stage","value":100,"stage":0,"unknown":1}]})"};
  for (const auto& input : invalid) {
    const auto result = Call(input);
    EXPECT_EQ(result.status, PBI_INVALID_INPUT_V1) << input;
    EXPECT_EQ(result.body.at("error").at("code"), "invalid_input");
    EXPECT_FALSE(result.body.contains("results"));
  }
  EXPECT_EQ(Call(R"({"schema_version":2,"operations":[]})").status, PBI_UNSUPPORTED_V1);
  EXPECT_EQ(Call(R"({"schema_version":1,"operations":[{"kind":"future"}]})").status, PBI_UNSUPPORTED_V1);
}

/// 字节/深度/操作预算和结果溢出均为资源错误，不静默截断。
TEST(CAbi, ResourceLimits) {
  EXPECT_EQ(Call(std::string(8 * 1024 * 1024 + 1, ' ')).status, PBI_RESOURCE_LIMIT_V1);
  EXPECT_EQ(Call(std::string(20, '[') + "0" + std::string(20, ']')).status, PBI_RESOURCE_LIMIT_V1);
  Json request{{"schema_version", 1}, {"operations", Json::array()}};
  for (int i = 0; i < 4097; ++i) request["operations"].push_back({{"kind", "stage"}, {"value", 1}, {"stage", 0}});
  EXPECT_EQ(Call(request.dump()).status, PBI_RESOURCE_LIMIT_V1);
  const Json large_rolls{{"kind", "ko"}, {"defender_hp", 3}, {"rolls", std::vector<int>(65537, 1)}};
  request["operations"] = Json::array({large_rolls});
  EXPECT_EQ(Call(request.dump()).status, PBI_RESOURCE_LIMIT_V1);
  const Json maximum_rolls{{"kind", "ko"}, {"defender_hp", 3}, {"rolls", std::vector<int>(65536, 1)}};
  request["operations"] = Json::array();
  for (int i = 0; i < 17; ++i) request["operations"].push_back(maximum_rolls);
  EXPECT_EQ(Call(request.dump()).status, PBI_RESOURCE_LIMIT_V1);
  EXPECT_EQ(Call(R"({"schema_version":1,"operations":[{"kind":"stage","value":9223372036854775807,"stage":6}]})").status, PBI_RESOURCE_LIMIT_V1);
}

/// 每次成功和失败均释放并清零；非空输出不允许被覆盖，避免泄漏原结果。
TEST(CAbi, OwnershipAndRepeatedRelease) {
  const auto request = Fixture("abi-calculations.v1.request.json");
  for (int i = 0; i < 256; ++i) {
    OwnedBuffer buffer;
    EXPECT_EQ(pbi_v1_compute(reinterpret_cast<const std::uint8_t*>(request.data()), request.size(), nullptr, &buffer.value), PBI_OK_V1);
    const auto* original = buffer.value.data;
    EXPECT_EQ(pbi_v1_compute(nullptr, 0, nullptr, &buffer.value), PBI_INVALID_INPUT_V1);
    EXPECT_EQ(buffer.value.data, original);
    pbi_v1_buffer_release(&buffer.value);
    EXPECT_EQ(buffer.value.data, nullptr);
    EXPECT_EQ(buffer.value.size, 0U);
    pbi_v1_buffer_release(&buffer.value);
  }
  pbi_v1_buffer_release(nullptr);
  EXPECT_EQ(pbi_v1_compute(nullptr, 0, nullptr, nullptr), PBI_INVALID_INPUT_V1);
  EXPECT_EQ(Call("invalid").status, PBI_INVALID_INPUT_V1);
}

/// 多线程独立调用返回相同版本和结果；没有线程全局错误或共享 JSON 状态。
TEST(CAbi, ConcurrentCalls) {
  const auto request = Fixture("abi-calculations.v1.request.json");
  const auto expected = Json::parse(Fixture("abi-calculations.v1.response.json"));
  std::vector<std::future<CallResult>> calls;
  for (int i = 0; i < 32; ++i) calls.push_back(std::async(std::launch::async, [request] { return Call(request); }));
  for (auto& call : calls) {
    const auto result = call.get();
    EXPECT_EQ(result.status, PBI_OK_V1);
    EXPECT_EQ(result.body, expected);
  }
}

/// 已取消令牌及真实运行中的批次均无部分结果；future 超时证明确有计算在运行。
TEST(CAbi, CancellationBeforeAndDuringBatch) {
  const auto destroy = &pbi_v1_cancel_token_destroy;
  std::unique_ptr<pbi_cancel_token_v1, decltype(destroy)> token(pbi_v1_cancel_token_create(), destroy);
  ASSERT_NE(token, nullptr);
  pbi_v1_cancel_request(token.get());
  EXPECT_EQ(Call(Fixture("abi-calculations.v1.request.json"), token.get()).status, PBI_CANCELLED_V1);
  token.reset(pbi_v1_cancel_token_create());
  ASSERT_NE(token, nullptr);
  Json request{{"schema_version", 1}, {"operations", Json::array()}};
  const Json operation{{"kind", "ko"}, {"defender_hp", 3}, {"rolls", std::vector<int>(256, 1)}};
  for (int i = 0; i < 4096; ++i) request["operations"].push_back(operation);
  const auto encoded = request.dump();
  auto work = std::async(std::launch::async, [&encoded, pointer = token.get()] { return Call(encoded, pointer); });
  EXPECT_EQ(work.wait_for(std::chrono::milliseconds(1)), std::future_status::timeout);
  pbi_v1_cancel_request(token.get());
  const auto result = work.get();
  EXPECT_EQ(result.status, PBI_CANCELLED_V1);
  EXPECT_FALSE(result.body.contains("results"));
}
} // namespace
