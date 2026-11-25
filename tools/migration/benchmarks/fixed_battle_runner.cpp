// benchmark的薄计时适配器：仅调用同snapshot正式codec，不包含任何新的领域规则。
#include "turn_contract.hpp"
#include <chrono>
#include <ctime>
#include <iostream>
#include <sys/resource.h>

namespace {
using Clock = std::chrono::steady_clock;
using pbi::contract::Json;
/// @param start 已记录单调时点；@return 到当前时点的实际秒数，不使用日历时钟。
double Seconds(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }
/// @return 当前进程真实high-water RSS；只供Linux/macOS一次性benchmark，不参与领域计算。
std::uint64_t PeakRss() {
  rusage usage{};
  if (getrusage(RUSAGE_SELF, &usage) != 0) throw std::runtime_error("getrusage failed");
#ifdef __APPLE__
  return static_cast<std::uint64_t>(usage.ru_maxrss);
#else
  return static_cast<std::uint64_t>(usage.ru_maxrss) * 1024;
#endif
}
/// @param line 一条与正式fixed_battle完全相同的operation JSON。
/// @return 原正式完整结果的编码文本与明确的计时分层；不重建第二次图或投影删减数学值。
std::pair<std::string, Json> Run(const std::string& line) {
  const auto started_cpu = std::clock();
  const auto decode_started = Clock::now();
  const auto input = Json::parse(line);
  const auto decode_seconds = Seconds(decode_started);
  const auto preparation_started = Clock::now();
  const auto request = pbi::contract::ReadFixedBattleRequest(input, PBI_V1_MAX_ROLLS,
      PBI_V1_MAX_GENERATED_NODES, PBI_V1_MAX_GENERATED_EDGES);
  const auto preparation_seconds = Seconds(preparation_started);
  std::optional<pbi::GraphBuildProgress> observed;
  // 原真实built帧证明Full继续前沿而Summary短路，不用相同最终nodes/edges猜测语义。
  const pbi::GraphProgressObserver progress = [&](const pbi::GraphBuildProgress& frame) { observed = frame; };
  const auto evaluate_started = Clock::now();
  const auto result = pbi::contract::EvaluateFixedBattle(request, progress, {});
  if (!observed || observed->phase != pbi::GraphBuildPhase::built) throw std::runtime_error("missing actual built progress");
  const auto evaluate_seconds = Seconds(evaluate_started);
  const auto encode_started = Clock::now();
  auto encoded = result.dump();
  const auto encode_seconds = Seconds(encode_started);
  const auto cpu_seconds = static_cast<double>(std::clock() - started_cpu) / CLOCKS_PER_SEC;
  return {std::move(encoded), {{"json_decode_seconds", decode_seconds}, {"typed_preparation_seconds", preparation_seconds},
      {"evaluate_including_result_projection_seconds", evaluate_seconds}, {"result_json_encode_seconds", encode_seconds},
      {"process_cpu_seconds", cpu_seconds}, {"peak_rss_bytes", PeakRss()}, {"expanded_nodes", observed->expanded}, {"frontier", observed->frontier}}};
}
} // namespace
/// 无参数；每行仅计算一次正式操作，stdout输出原结果和计时，错误非零退出防止计入提速。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      auto [result, timing] = Run(line);
      std::cout << "{\"engine_version\":" << Json(pbi_v1_engine_version()).dump() << ",\"result\":" << result << ",\"timing\":" << timing.dump() << "}\n";
    } catch (const std::exception& error) {
      std::cerr << error.what() << '\n'; return 1;
    }
  }
  return std::cin.bad() || !std::cout ? 1 : 0;
}
