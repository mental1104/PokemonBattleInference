#include "pbi_core.h"
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <fstream>
#include <future>
#include <memory>

namespace {
using Json = nlohmann::json;
/// @param kind 已公开正式操作；@return 拥有的同一冻结知识/目标输入，不修改golden文件。
Json Operation(std::string_view kind) {
  std::ifstream input(std::string{PBI_VECTOR_DIR} + "/abi-calculations.v1.request.json");
  if (!input) throw std::runtime_error("cannot read configuration cancellation fixture");
  Json fixture;
  input >> fixture;
  for (const auto& operation : fixture.at("operations")) if (operation.at("kind") == kind) return operation;
  throw std::runtime_error("required configuration cancellation fixture is missing");
}
/// 公共C ABI返回值与拥有正文，结果拷贝后由相同allocator释放原buffer。
struct CallResult { pbi_status_v1 status; Json body; };
/// @param encoded 已序列化完整批次；@param token 异步调用期间借用的同源令牌。
/// @return 真正公开pbi_v1_compute结果，不用测试替代其异常映射。
CallResult Compute(const std::string& encoded, const pbi_cancel_token_v1* token) {
  pbi_buffer_v1 output{};
  const auto status = pbi_v1_compute(reinterpret_cast<const std::uint8_t*>(encoded.data()), encoded.size(), token, &output);
  try {
    auto body = Json::parse(output.data, output.data + output.size);
    pbi_v1_buffer_release(&output);
    return {status, std::move(body)};
  } catch (...) {
    pbi_v1_buffer_release(&output);
    throw;
  }
}
/// @param kind 原已公开模板或EV操作；放大合法随机档/目标计算后确认仍在运行再取消。
/// 验证取消码和整批原子撤销，前置hp成功也不能残留在results中。
void ExpectRunningCancellation(std::string_view kind) {
  auto operation = Operation(kind);
  const auto damage_context = Operation("configuration_templates");
  auto goal = damage_context.at("goals")[0];
  operation["type_chart"] = damage_context.at("type_chart");
  goal["required_turns"] = 10;
  operation["goals"] = Json::array();
  for (std::size_t index = 0; index < 20; ++index) {
    goal["goal_id"] = "cancel-goal-" + std::to_string(index);
    operation["goals"].push_back(goal);
  }
  operation["policy"]["random_damage_multipliers"] = std::vector<double>(PBI_V1_MAX_ROLLS, 1.0);
  operation["max_candidates"] = 10;
  operation["speed_goals"] = Json::array();
  if (kind == "configuration_templates") operation["allowed_stat_presets"] = Json::array();
  const auto encoded = Json{{"schema_version", 1}, {"operations", Json::array({Operation("hp"), operation})}}.dump();
  const std::unique_ptr<pbi_cancel_token_v1, decltype(&pbi_v1_cancel_token_destroy)> token{pbi_v1_cancel_token_create(), pbi_v1_cancel_token_destroy};
  ASSERT_NE(token, nullptr);
  auto future = std::async(std::launch::async, [&] { return Compute(encoded, token.get()); });
  const auto running = future.wait_for(std::chrono::milliseconds(30));
  if (running != std::future_status::timeout) {
    const auto early = future.get();
    FAIL() << "configuration finished before cancellation: " << early.status << ' ' << early.body.value("error", Json{}).dump();
    return;
  }
  pbi_v1_cancel_request(token.get());
  const auto result = future.get();
  EXPECT_EQ(result.status, PBI_CANCELLED_V1);
  EXPECT_EQ(result.body.at("error").at("code"), "cancelled");
  EXPECT_FALSE(result.body.contains("results"));
}
/// 模板纯求值器的运行中取消不能作为普通runtime_error落入INTERNAL_ERROR兜底。
TEST(ConfigurationCancellation, RunningTemplateSolveIsCancelledAtomically) {
  ExpectRunningCancellation("configuration_templates");
}
/// EV网格/子集二分中的同源取消保留正式cancelled码，而不是内部错误或部分候选。
TEST(ConfigurationCancellation, RunningSpreadSearchIsCancelledAtomically) {
  ExpectRunningCancellation("configuration_spread_search");
}
} // namespace
