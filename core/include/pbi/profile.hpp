#pragma once
#include "pbi/damage.hpp"
namespace pbi {
/// 性格可影响的能力轴，数值来自 PokeAPI；HP 不允许性格修正。
enum class NatureAxis { attack = 2, defense, special_attack, special_defense, speed };
/// 完整能力配置快照；所有计算和性格选择留在 Core，客户端只注入知识。
struct StatProfile {
  BattleStats base;
  BattleStats ivs;
  BattleStats evs;
  std::int32_t level;
  NatureAxis decreased;
  NatureAxis increased;
};
/// @param profile 只读种族值/IV/EV/等级/性格轴；@return 六项实际能力，不修改输入。
/// 复用原整数公式；未知性格轴明确失败，输出超出 BattleStats 的 int32 范围抛 overflow_error。
[[nodiscard]] BattleStats CalculateStats(const StatProfile& profile);
} // namespace pbi
