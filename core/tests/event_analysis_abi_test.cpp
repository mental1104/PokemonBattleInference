#include "pbi_core.h"
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <fstream>
#include <future>
#include <memory>
#include <string>

namespace {
using Json = nlohmann::json;
/// 测试调用独占C结果，异常/提前返回仍归还同一allocator。
struct EventBuffer {
  pbi_buffer_v1 value{};
  /// 释放本次调用拥有的结果；描述符本身位于栈上。
  ~EventBuffer() { pbi_v1_buffer_release(&value); }
};
/// 测试边界返回拥有JSON副本，不借用已释放的C字节。
struct EventReply { pbi_status_v1 status; Json response; };
/// @param operations 正式操作数组；@param token 可空借用令牌；@return 独立状态/完整响应。
EventReply Compute(const Json& operations, const pbi_cancel_token_v1* token = nullptr) {
  const auto encoded = Json{{"schema_version", 1}, {"operations", operations}}.dump();
  EventBuffer output;
  const auto status = pbi_v1_compute(reinterpret_cast<const std::uint8_t*>(encoded.data()), encoded.size(), token, &output.value);
  return {status, output.value.data ? Json::parse(output.value.data, output.value.data + output.value.size) : Json{}};
}
/// @param kind 共享向量内已有操作；@return 拥有的完整原oracle请求，缺失直接使测试失败。
Json Example(const char* kind) {
  std::ifstream stream(std::string{PBI_VECTOR_DIR} + "/abi-calculations.v1.request.json");
  if (!stream) throw std::runtime_error("shared ABI request fixture is unavailable");
  Json fixture;
  stream >> fixture;
  for (const auto& operation : fixture.at("operations")) if (operation.at("kind") == kind) return operation;
  throw std::runtime_error("required public operation is missing");
}

/// 单图/配置组原拓扑都占用同一批次节点配额，不能与其他graph各获得一份完整额度。
TEST(CAbiEvents, TopologyBudgetIsSharedAcrossOperationKinds) {
  for (const auto* kind : {"event_analysis", "configuration_event_analysis"}) {
    const auto analysis = Example(kind);
    std::size_t used = 0;
    if (analysis.at("kind") == "event_analysis") used = analysis.at("graph").at("nodes").size();
    else for (const auto& group : analysis.at("groups")) used += group.at("analysis").at("graph").at("nodes").size();
    ASSERT_GT(used, 0U);
    ASSERT_LE(used, PBI_V1_MAX_GRAPH_NODES);
    auto nodes = Json::array();
    for (std::size_t index = 0; index < PBI_V1_MAX_GRAPH_NODES - used + 1; ++index) {
      nodes.push_back({{"outcome", "draw"}, {"cycle_resolution", "declare-draw"}});
    }
    const Json graph{{"kind", "graph"}, {"nodes", std::move(nodes)}, {"edges", Json::array()},
        {"root", 0}, {"observer", "attacker"}, {"truncations", Json::array()}};
    const auto result = Compute(Json::array({analysis, graph}));
    EXPECT_EQ(result.status, PBI_RESOURCE_LIMIT_V1) << kind;
    EXPECT_EQ(result.response.at("error").at("code"), "resource_limit");
    EXPECT_FALSE(result.response.contains("results"));
  }
}

/// 只在显式reference_static下开放原无动态hook能力，默认/未知上下文的合同不变。
TEST(CAbiEvents, ReferenceStaticDamageContextIsExplicit) {
  std::ifstream stream(std::string{PBI_VECTOR_DIR} + "/reference-static-damage.v1.json");
  ASSERT_TRUE(stream.good());
  Json fixture;
  stream >> fixture;
  for (const auto& item : fixture.at("cases")) {
    auto operation = item.at("operation");
    auto result = Compute(Json::array({operation}));
    ASSERT_EQ(result.status, PBI_OK_V1);
    EXPECT_EQ(result.response.at("results").at(0), item.at("expected"));
    operation.erase("context");
    EXPECT_EQ(Compute(Json::array({operation})).status, PBI_UNSUPPORTED_V1);
    operation["context"] = "unknown";
    EXPECT_EQ(Compute(Json::array({operation})).status, PBI_UNSUPPORTED_V1);
    operation["context"] = nullptr;
    EXPECT_EQ(Compute(Json::array({operation})).status, PBI_INVALID_INPUT_V1);
  }
}

/// 两种公开事件入口真实运行大型计数自动机后取消，不能将runtime_error归为INTERNAL或发布前序hp。
TEST(CAbiEvents, RuntimeCancellationDiscardsTheWholeBatch) {
  for (const bool grouped : {false, true}) {
    auto analysis = Example("event_analysis");
    analysis["graph"]["edges"][0]["target"] = 0;
    analysis["query"]["min_occurrences"] = "100000";
    analysis["query"]["max_occurrences"] = nullptr;
    Json operation = analysis;
    if (grouped) operation = {{"kind", "configuration_event_analysis"}, {"total_configuration_count", "1"},
        {"groups", Json::array({{{"configuration_id", "large-loop"},
            {"configuration_weight", {{"numerator", "1"}, {"denominator", "1"}}}, {"analysis", analysis}}})}};
    const Json operations = Json::array({{{"kind", "hp"}, {"base", 80}, {"iv", 31}, {"ev", 0}, {"level", 50}}, operation});
    const std::unique_ptr<pbi_cancel_token_v1, decltype(&pbi_v1_cancel_token_destroy)> token{
        pbi_v1_cancel_token_create(), &pbi_v1_cancel_token_destroy};
    ASSERT_NE(token, nullptr);
    auto pending = std::async(std::launch::async, [&operations, raw = token.get()] { return Compute(operations, raw); });
    ASSERT_EQ(pending.wait_for(std::chrono::milliseconds{30}), std::future_status::timeout);
    pbi_v1_cancel_request(token.get());
    ASSERT_EQ(pending.wait_for(std::chrono::seconds{5}), std::future_status::ready);
    const auto result = pending.get();
    EXPECT_EQ(result.status, PBI_CANCELLED_V1);
    EXPECT_EQ(result.response.at("error").at("code"), "cancelled");
    EXPECT_FALSE(result.response.contains("results"));
  }
}
} // namespace
