#include "pbi_core.h"
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <fstream>
#include <future>
#include <iterator>
#include <limits>
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

/// @param kind 共享文件内唯一操作种类；@return 拥有的冻结输入，缺失立即使测试失败。
Json FixtureOperation(const char* kind) {
  const auto fixture = Json::parse(Fixture("abi-calculations.v1.request.json"));
  for (const auto& operation : fixture.at("operations")) if (operation.at("kind") == kind) return operation;
  throw std::runtime_error("required operation is missing from the shared fixture");
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
  EXPECT_STREQ(pbi_v1_engine_version(), "0.3.0");
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

/// 伤害协议对未知机制/缺失知识与非法字段做精确分类，任一失败都撤销整批结果。
TEST(CAbi, DamageKnowledgeRulesAndValidation) {
  const auto baseline = FixtureOperation("damage");
  std::vector<std::pair<Json, pbi_status_v1>> failures;
  auto input = baseline;
  input["type_chart"] = Json::array();
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["attacker"]["ability"] = "multiscale";
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["defender"]["ability"] = "inner_focus";
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["weather"] = "future_weather";
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["move"]["category"] = "status";
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["generation_id"] = 10;
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["version_group_id"] = 31;
  EXPECT_EQ(Call(Json{{"schema_version", 1}, {"operations", Json::array({input})}}.dump()).status, PBI_OK_V1);
  input["version_group_id"] = 1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["type_chart"].push_back(input["type_chart"].front());
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["move"]["power"] = true;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["critical"] = 1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["attacker"]["extra"] = 1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["policy"] = {{"extra", 1}};
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["policy"] = {{"life_orb_damage_multiplier", nullptr}};
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["policy"] = {{"random_damage_multipliers", Json::array()}};
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["policy"] = {{"random_damage_multipliers", std::vector<double>(65537, 1.0)}};
  failures.push_back({input, PBI_RESOURCE_LIMIT_V1});
  input = baseline; input["policy"] = {{"random_damage_multipliers", std::vector<double>{1e100}}};
  failures.push_back({input, PBI_RESOURCE_LIMIT_V1});
  for (const auto& [operation, status] : failures) {
    const Json request{{"schema_version", 1}, {"operations", Json::array({baseline, operation, baseline})}};
    const auto result = Call(request.dump());
    EXPECT_EQ(result.status, status) << operation;
    EXPECT_FALSE(result.body.contains("results"));
  }
  input = baseline;
  input["policy"] = {{"random_damage_multipliers", std::vector<double>(65536, 1.0)}};
  Json request{{"schema_version", 1}, {"operations", Json::array()}};
  for (int index = 0; index < 17; ++index) request["operations"].push_back(input);
  EXPECT_EQ(Call(request.dump()).status, PBI_RESOURCE_LIMIT_V1);
}

/// 状态更新的非法节点、未知机制与预算均精确分类；先前合法更新不能作为部分结果泄漏。
TEST(CAbi, StateValidationAtomicUpdatesAndBudgets) {
  auto baseline = FixtureOperation("battle_state");
  baseline["updates"] = Json::array();
  std::vector<std::pair<Json, pbi_status_v1>> failures;
  auto input = baseline; input["state"]["attacker"]["current_hp"] = -1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["state"]["attacker"]["move_slots"][0]["current_pp"] = 31;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["state"]["attacker"]["stages"][0] = 7;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["state"]["attacker"]["spec"]["pokemon"]["types"] = {9, 9};
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["state"]["attacker"]["choice_lock_move_id"] = 1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["state"]["attacker"]["status"]["major"] = {{"kind", "burn"}, {"toxic_counter", 2}};
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["state"]["attacker"]["status"]["major"] = {{"kind", "future_status"}};
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["state"]["rules"]["allow_mega_evolution"] = true;
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["state"]["rules"]["move_execution_policy"]["consume_pp_on_miss"] = false;
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["updates"] = Json::array({{{"kind", "future_update"}}});
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["updates"] = Json::array({{{"kind", "hp"}, {"side", "attacker"}, {"value", 140}},
                                                  {{"kind", "pp"}, {"side", "attacker"}, {"move_id", 1}, {"value", 31}}});
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["updates"] = Json::array();
  for (int index = 0; index < 256; ++index) input["updates"].push_back({{"kind", "next_turn"}});
  const auto maximum = Call(Json{{"schema_version", 1}, {"operations", Json::array({input})}}.dump());
  ASSERT_EQ(maximum.status, PBI_OK_V1);
  EXPECT_EQ(maximum.body.at("results")[0].at("state").at("turn_number"), 257);
  EXPECT_TRUE(maximum.body.at("results")[0].at("same_key_as_input").get<bool>());
  input["updates"].push_back({{"kind", "next_turn"}});
  failures.push_back({input, PBI_RESOURCE_LIMIT_V1});
  for (const auto& [operation, status] : failures) {
    const auto actual = Call(Json{{"schema_version", 1}, {"operations", Json::array({baseline, operation, baseline})}}.dump());
    EXPECT_EQ(actual.status, status); EXPECT_FALSE(actual.body.contains("results"));
  }
  // 每项 2*65536 槽位、总输入不足 8MiB，精确验证组合策略预算而非只命中字节限制。
  input = baseline;
  input["state"]["rules"]["damage_policy"]["random_damage_multipliers"] = std::vector<int>(65536, 1);
  input["compare_to"] = input["state"];
  Json request{{"schema_version", 1}, {"operations", Json::array()}};
  for (int index = 0; index < 9; ++index) request["operations"].push_back(input);
  const auto encoded = request.dump(); ASSERT_LT(encoded.size(), PBI_V1_MAX_REQUEST_BYTES);
  EXPECT_EQ(Call(encoded).status, PBI_RESOURCE_LIMIT_V1);
}

/// 精确分数字符串支持十进制规范化并拒绝零分母/非法状态/数字超限，错误不会降成近似值。
TEST(CAbi, StatusExactFractionBoundaries) {
  const auto baseline = FixtureOperation("status_modifiers");
  auto input = baseline; input["base_multiplier"] = {{"numerator", "0001"}, {"denominator", "-0003"}};
  const auto normalized = Call(Json{{"schema_version", 1}, {"operations", Json::array({input})}}.dump());
  ASSERT_EQ(normalized.status, PBI_OK_V1);
  EXPECT_EQ(normalized.body.at("results")[0].at("adjusted_multiplier"), (Json{{"numerator", "-1"}, {"denominator", "3"}}));
  std::vector<std::pair<Json, pbi_status_v1>> failures;
  input = baseline; input["base_multiplier"]["denominator"] = "0";
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["base_multiplier"]["numerator"] = "1.0";
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["base_multiplier"]["numerator"] = 1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["base_multiplier"]["numerator"] = std::string(1025, '1');
  failures.push_back({input, PBI_RESOURCE_LIMIT_V1});
  input = baseline; input["speed"] = -1;
  failures.push_back({input, PBI_INVALID_INPUT_V1});
  input = baseline; input["generation_id"] = 10;
  failures.push_back({input, PBI_UNSUPPORTED_V1});
  input = baseline; input["speed"] = std::numeric_limits<std::int64_t>::max();
  input["paralysis_multiplier"] = {{"numerator", "2"}, {"denominator", "1"}};
  failures.push_back({input, PBI_RESOURCE_LIMIT_V1});
  for (const auto& [operation, status] : failures) {
    const auto actual = Call(Json{{"schema_version", 1}, {"operations", Json::array({operation})}}.dump());
    EXPECT_EQ(actual.status, status); EXPECT_FALSE(actual.body.contains("results"));
  }
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
