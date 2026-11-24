#include "pbi_core.h"
#include "../src/turn_contract.hpp"
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <array>
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

/// C 回调测试拥有固定大小帧副本；cancel 非空时在首个真实进度中同步请求取消。
struct ProgressCapture {
  std::array<pbi_progress_v1, 8> frames{};
  std::size_t count = 0;
  bool overflow = false;
  pbi_cancel_token_v1* cancel = nullptr;
};

/// @param frame 同步借用 C 栈帧；@param context 指向当前调用拥有的捕获器，返回后不保留 frame 指针。
/// 固定数组复制不分配、不抛异常，令牌取消不销毁借用中的资源。
void CaptureProgress(const pbi_progress_v1* frame, std::uintptr_t context) noexcept {
  auto& capture = *reinterpret_cast<ProgressCapture*>(context);
  if (capture.count < capture.frames.size()) capture.frames[capture.count++] = *frame;
  else capture.overflow = true;
  if (capture.cancel) pbi_v1_cancel_request(capture.cancel);
}

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
  EXPECT_STREQ(pbi_v1_engine_version(), "0.8.0");
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

/// 旧在线任务的最大生成图预算仍可提交；显式拓扑输入预算不应错误拒绝合法固定战斗。
TEST(CAbi, FixedBattleLegacyBudgetsAndUnboundedEquations) {
  auto operation = FixtureOperation("fixed_battle");
  operation["graph_limits"] = {{"max_nodes", 2000000}, {"max_edges", 8000000}, {"max_turns", 10000}};
  operation["max_equation_nodes"] = nullptr;
  auto result = Call(Json{{"schema_version", 1}, {"operations", Json::array({FixtureOperation("graph"), operation})}}.dump());
  ASSERT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body["results"][1]["status"], "solved");
  EXPECT_EQ(result.body["results"][1]["statistics"]["nodes"], 2);
  // 属性合同直接验证 None 被原样交给 Core，不能只在小图上碰巧与 128 得到相同数值。
  const auto decoded = pbi::contract::ReadFixedBattleRequest(operation, PBI_V1_MAX_TOTAL_ROLLS,
      PBI_V1_MAX_GENERATED_NODES, PBI_V1_MAX_GENERATED_EDGES);
  EXPECT_FALSE(decoded.options.max_equation_nodes.has_value());
  operation.erase("graph_limits"); operation.erase("max_equation_nodes");
  const auto defaults = pbi::contract::ReadFixedBattleRequest(operation, PBI_V1_MAX_TOTAL_ROLLS,
      PBI_V1_MAX_GENERATED_NODES, PBI_V1_MAX_GENERATED_EDGES);
  EXPECT_EQ(defaults.options.graph_limits.max_nodes, 20000);
  EXPECT_EQ(defaults.options.graph_limits.max_edges, 80000);
  EXPECT_FALSE(defaults.options.graph_limits.max_turns.has_value());
  EXPECT_FALSE(defaults.options.max_equation_nodes.has_value());
  operation["graph_limits"] = {{"max_nodes", 2000001}};
  result = Call(Json{{"schema_version", 1}, {"operations", Json::array({operation})}}.dump());
  EXPECT_EQ(result.status, PBI_RESOURCE_LIMIT_V1);
  EXPECT_FALSE(result.body.contains("results"));
}

/// 构图保护得到 unknown，完整图确有全部节点/事件，未知机制和显式回合预算整批失败。
TEST(CAbi, TurnAndFixedBattleResultSemantics) {
  auto fixed = FixtureOperation("fixed_battle");
  fixed["include_graph"] = true;
  auto result = Call(Json{{"schema_version", 1}, {"operations", Json::array({fixed})}}.dump());
  ASSERT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body["results"][0]["graph"]["nodes"].size(), 2);
  EXPECT_EQ(result.body["results"][0]["graph"]["edges"].size(), 1);
  EXPECT_FALSE(result.body["results"][0]["graph"]["edges"][0]["paths"][0]["events"].empty());
  fixed["graph_limits"]["max_nodes"] = 1;
  result = Call(Json{{"schema_version", 1}, {"operations", Json::array({fixed})}}.dump());
  ASSERT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body["results"][0]["status"], "incomplete-graph");
  EXPECT_TRUE(result.body["results"][0]["win"].is_null());
  EXPECT_EQ(result.body["results"][0]["statistics"]["terminal_counts"]["unknown"], 1);
  EXPECT_EQ(result.body["results"][0]["graph"]["nodes"][0]["reason"], "max-nodes");
  auto turn = FixtureOperation("battle_turn");
  turn["state"]["attacker"]["spec"]["moves"][0]["effect_identifier"] = "unsupported-effect";
  result = Call(Json{{"schema_version", 1}, {"operations", Json::array({turn})}}.dump());
  EXPECT_EQ(result.status, PBI_UNSUPPORTED_V1);
  turn = FixtureOperation("battle_turn");
  turn["state"]["rules"]["damage_policy"]["random_damage_multipliers"] = Json::array({0.85, 1.0});
  turn["turn_limits"] = {{"max_branches", 1}, {"max_event_paths", 1}};
  result = Call(Json{{"schema_version", 1}, {"operations", Json::array({FixtureOperation("hp"), turn})}}.dump());
  EXPECT_EQ(result.status, PBI_RESOURCE_LIMIT_V1);
  EXPECT_FALSE(result.body.contains("results"));
}

/// 回调复制帧后仍可核对计数；首帧中同步取消会撤销包括之前成功操作在内的整个批次。
TEST(CAbi, ActualProgressBorrowingAndCancellation) {
  const auto input = Fixture("abi-calculations.v1.request.json");
  OwnedBuffer output;
  ProgressCapture capture;
  auto status = pbi_v1_compute_with_progress(reinterpret_cast<const std::uint8_t*>(input.data()), input.size(), nullptr,
      CaptureProgress, reinterpret_cast<std::uintptr_t>(&capture), &output.value);
  ASSERT_EQ(status, PBI_OK_V1);
  ASSERT_GE(capture.count, 2);
  EXPECT_FALSE(capture.overflow);
  EXPECT_EQ(capture.frames[0].phase, PBI_PROGRESS_BUILDING_V1);
  const auto& final = capture.frames[capture.count - 1];
  EXPECT_EQ(final.struct_size, sizeof(pbi_progress_v1));
  EXPECT_EQ(final.phase, PBI_PROGRESS_BUILT_V1);
  const auto response = Json::parse(output.value.data, output.value.data + output.value.size);
  EXPECT_EQ(final.nodes, response["results"][final.operation_index]["statistics"]["nodes"]);
  EXPECT_EQ(final.edges, response["results"][final.operation_index]["statistics"]["edges"]);
  pbi_v1_buffer_release(&output.value);
  const std::unique_ptr<pbi_cancel_token_v1, decltype(&pbi_v1_cancel_token_destroy)> token(pbi_v1_cancel_token_create(), pbi_v1_cancel_token_destroy);
  ASSERT_NE(token, nullptr);
  ProgressCapture cancelled;
  cancelled.cancel = token.get();
  status = pbi_v1_compute_with_progress(reinterpret_cast<const std::uint8_t*>(input.data()), input.size(), token.get(),
      CaptureProgress, reinterpret_cast<std::uintptr_t>(&cancelled), &output.value);
  EXPECT_EQ(status, PBI_CANCELLED_V1);
  const auto rejection = Json::parse(output.value.data, output.value.data + output.value.size);
  EXPECT_FALSE(rejection.contains("results"));
  ASSERT_GE(cancelled.count, 1);
  EXPECT_EQ(cancelled.frames[0].phase, PBI_PROGRESS_BUILDING_V1);
}

/// 图输入守恒/拓扑/枚举/方程预算明确失败；未知和封闭循环保留不同数学语义。
TEST(CAbi, GraphBoundariesAndUnavailableSemantics) {
  const auto baseline = FixtureOperation("graph");
  std::vector<std::pair<Json, pbi_status_v1>> failures;
  auto graph = baseline;
  graph["nodes"][0]["outcome"] = "future-outcome";
  failures.push_back({graph, PBI_UNSUPPORTED_V1});
  graph = baseline; graph["root"] = -1;
  failures.push_back({graph, PBI_INVALID_INPUT_V1});
  graph = baseline; graph["edges"][0]["target"] = true;
  failures.push_back({graph, PBI_INVALID_INPUT_V1});
  graph = baseline; graph["edges"][0]["probability"] = {{"numerator", "0"}, {"denominator", "1"}};
  failures.push_back({graph, PBI_INVALID_INPUT_V1});
  graph = baseline; graph["max_equation_nodes"] = PBI_V1_MAX_EQUATION_NODES + 1;
  failures.push_back({graph, PBI_RESOURCE_LIMIT_V1});
  graph = baseline; graph["max_equation_nodes"] = 0;
  failures.push_back({graph, PBI_INVALID_INPUT_V1});
  graph = baseline; graph["nodes"].push_back(graph["nodes"][0]);
  graph["edges"] = Json::array({{{"source", 0}, {"target", 2}, {"probability", {{"numerator", "1"}, {"denominator", "1"}}}},
      {{"source", 2}, {"target", 0}, {"probability", {{"numerator", "1"}, {"denominator", "2"}}}},
      {{"source", 2}, {"target", 1}, {"probability", {{"numerator", "1"}, {"denominator", "2"}}}}});
  graph["max_equation_nodes"] = 1;
  failures.push_back({graph, PBI_RESOURCE_LIMIT_V1});
  for (const auto& [input, expected] : failures) {
    const auto result = Call(Json{{"schema_version", 1}, {"operations", Json::array({FixtureOperation("hp"), input})}}.dump());
    EXPECT_EQ(result.status, expected);
    EXPECT_FALSE(result.body.contains("results"));
  }
  graph = baseline;
  graph["nodes"] = Json::array({{{"outcome", "unknown"}, {"cycle_resolution", "declare-draw"}}});
  graph["edges"] = Json::array(); graph["truncations"] = Json::array({"max-nodes"});
  const auto incomplete = Call(Json{{"schema_version", 1}, {"operations", Json::array({graph})}}.dump());
  ASSERT_EQ(incomplete.status, PBI_OK_V1);
  EXPECT_EQ(incomplete.body["results"][0]["status"], "incomplete-graph");
  EXPECT_TRUE(incomplete.body["results"][0]["win"].is_null());
  EXPECT_EQ(incomplete.body["results"][0]["expected_turns"]["status"], "unavailable");
  graph = baseline;
  graph["nodes"].erase(1);
  graph["edges"] = Json::array({{{"source", 0}, {"target", 0}, {"probability", {{"numerator", "1"}, {"denominator", "1"}}}}});
  const auto closed = Call(Json{{"schema_version", 1}, {"operations", Json::array({graph})}}.dump());
  ASSERT_EQ(closed.status, PBI_OK_V1);
  EXPECT_EQ(closed.body["results"][0]["closed_cycle"]["numerator"], "1");
  EXPECT_EQ(closed.body["results"][0]["draw"]["numerator"], "1");
  EXPECT_EQ(closed.body["results"][0]["expected_turns"]["status"], "infinite");
}

/// 图节点预算跨操作累计；不能每个图各自占用一份完整批次配额。
TEST(CAbi, GraphBatchNodeBudget) {
  auto graph = FixtureOperation("graph");
  graph["nodes"] = std::vector<Json>(PBI_V1_MAX_GRAPH_NODES / 2 + 1, Json{{"outcome", "draw"}, {"cycle_resolution", "declare-draw"}});
  graph["edges"] = Json::array();
  const auto result = Call(Json{{"schema_version", 1}, {"operations", Json::array({graph, graph})}}.dump());
  EXPECT_EQ(result.status, PBI_RESOURCE_LIMIT_V1);
  EXPECT_FALSE(result.body.contains("results"));
}

/// 合法行动保留 slot_id，策略选择不修改 PP；无 PP 与濒死分别是 Struggle 和 Pass。
TEST(CAbi, LegalActionsPolicyAndFallbacks) {
  auto operation = FixtureOperation("legal_actions");
  operation["policy"] = "first-legal-action";
  auto result = Call(Json{{"schema_version", 1}, {"operations", Json::array({operation})}}.dump());
  ASSERT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body["results"][0]["actions"].size(), 4);
  EXPECT_EQ(result.body["results"][0]["selections"].size(), 1);
  EXPECT_EQ(result.body["results"][0]["selections"][0]["action"]["slot_id"], 1001);
  for (auto& slot : operation["state"]["attacker"]["move_slots"]) slot["current_pp"] = 0;
  result = Call(Json{{"schema_version", 1}, {"operations", Json::array({operation})}}.dump());
  ASSERT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body["results"][0]["actions"][0]["kind"], "struggle");
  operation["state"]["attacker"]["current_hp"] = 0;
  result = Call(Json{{"schema_version", 1}, {"operations", Json::array({operation})}}.dump());
  ASSERT_EQ(result.status, PBI_OK_V1);
  EXPECT_EQ(result.body["results"][0]["actions"][0]["kind"], "pass");
}

/// 确认大图调用仍在运行后取消；同一个 C 令牌覆盖图解析、SCC 与消元，不返回部分结果。
TEST(CAbi, RunningGraphCancellation) {
  auto graph = FixtureOperation("graph");
  constexpr std::size_t count = 128;
  graph["nodes"] = std::vector<Json>(count, Json{{"outcome", "non-terminal"}, {"cycle_resolution", "solve-absorption-probability"}});
  graph["nodes"].push_back({{"outcome", "attacker-win"}, {"cycle_resolution", "declare-draw"}});
  graph["edges"] = Json::array();
  for (std::size_t source = 0; source < count; ++source) {
    for (std::size_t target = 0; target <= count; ++target) {
      graph["edges"].push_back({{"source", source}, {"target", target}, {"probability", {{"numerator", "1"}, {"denominator", "129"}}}});
    }
  }
  const auto encoded = Json{{"schema_version", 1}, {"operations", Json::array({graph})}}.dump();
  const std::unique_ptr<pbi_cancel_token_v1, decltype(&pbi_v1_cancel_token_destroy)> token(pbi_v1_cancel_token_create(), pbi_v1_cancel_token_destroy);
  ASSERT_NE(token, nullptr);
  auto future = std::async(std::launch::async, [&encoded, &token] { return Call(encoded, token.get()); });
  ASSERT_EQ(future.wait_for(std::chrono::milliseconds(30)), std::future_status::timeout);
  pbi_v1_cancel_request(token.get());
  const auto result = future.get();
  EXPECT_EQ(result.status, PBI_CANCELLED_V1);
  EXPECT_FALSE(result.body.contains("results"));
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

/// 原始成员预算先于归并，非法类型/空维度均整批拒绝，不保留前后成功操作。
TEST(CAbi, ConfigurationRawBudgetsAndStrictBoundaries) {
  const auto baseline = FixtureOperation("hp");
  auto stats = FixtureOperation("configuration_stats");
  stats["input"]["level"] = 1;
  stats["input"]["enumeration"] = {{"mode", "controlled"}, {"fields", Json::array({"attack"})},
      {"ev_values", Json::array({0, 1, 2, 3})}, {"natures", Json::array({Json::array({1, 1, 1, 1, 1})})}};
  stats["input"]["max_raw_profiles"] = 3;
  std::vector<std::pair<Json, pbi_status_v1>> failures{{stats, PBI_RESOURCE_LIMIT_V1}};
  auto invalid = stats; invalid["input"]["max_raw_profiles"] = true; failures.push_back({invalid, PBI_INVALID_INPUT_V1});
  invalid = stats; invalid["input"]["enumeration"]["natures"][0][0] = false; failures.push_back({invalid, PBI_INVALID_INPUT_V1});
  invalid = stats; invalid["input"]["enumeration"]["fields"] = Json::array({"unknown"}); failures.push_back({invalid, PBI_UNSUPPORTED_V1});
  invalid = stats; invalid["input"]["max_raw_profiles"] = 4; invalid["input"]["enumeration"]["ev_values"] = Json::array();
  failures.push_back({invalid, PBI_INVALID_INPUT_V1});
  auto moves = FixtureOperation("configuration_moves");
  auto& candidates = moves["input"]["candidates"];
  ASSERT_FALSE(candidates.empty()); const auto candidate = candidates[0]; candidates = Json::array({candidate, candidate, candidate});
  moves["input"]["requested_ids"] = Json::array(); moves["input"]["slot_counts"] = Json::array({1});
  moves["input"]["max_raw_combinations"] = 2; failures.push_back({moves, PBI_RESOURCE_LIMIT_V1});
  auto space = FixtureOperation("configuration_space");
  space["input"]["max_raw_pairs"] = 1; failures.push_back({space, PBI_RESOURCE_LIMIT_V1});
  auto job = FixtureOperation("job_move_pool");
  job["input"]["admission"]["candidates"] = Json::array(); failures.push_back({job, PBI_INVALID_INPUT_V1});
  for (const auto& [operation, status] : failures) {
    const auto actual = Call(Json{{"schema_version", 1}, {"operations", Json::array({baseline, operation, baseline})}}.dump());
    EXPECT_EQ(actual.status, status); EXPECT_FALSE(actual.body.contains("results"));
  }
}

/// 真正执行中的高维枚举读取同一取消令牌，不能等待巨大原空间枚举结束。
TEST(CAbi, RunningConfigurationCancellation) {
  auto operation = FixtureOperation("configuration_stats"); auto& input = operation["input"];
  std::vector<int> evs; for (int value = 0; value <= 252; ++value) evs.push_back(value);
  input["max_raw_profiles"] = 1000000000;
  input["enumeration"] = {{"mode", "controlled"},
      {"fields", Json::array({"hp", "attack", "defense", "special_attack", "special_defense", "speed"})},
      {"ev_values", evs}, {"natures", Json::array({Json::array({1, 1, 1, 1, 1})})}};
  const auto encoded = Json{{"schema_version", 1}, {"operations", Json::array({operation})}}.dump();
  const auto destroy = &pbi_v1_cancel_token_destroy;
  std::unique_ptr<pbi_cancel_token_v1, decltype(destroy)> token(pbi_v1_cancel_token_create(), destroy); ASSERT_NE(token, nullptr);
  auto work = std::async(std::launch::async, [&encoded, pointer = token.get()] { return Call(encoded, pointer); });
  EXPECT_EQ(work.wait_for(std::chrono::milliseconds(10)), std::future_status::timeout);
  pbi_v1_cancel_request(token.get());
  EXPECT_EQ(work.wait_for(std::chrono::seconds(2)), std::future_status::ready);
  const auto result = work.get(); EXPECT_EQ(result.status, PBI_CANCELLED_V1); EXPECT_FALSE(result.body.contains("results"));
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
