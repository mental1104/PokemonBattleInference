#pragma once

#include <boost/multiprecision/cpp_int.hpp>
#include <boost/rational.hpp>
#include <cstdint>
#include <span>

namespace pbi {

/// 核心的任意精度整数与精确有理数；概率计算不得经过浮点数。
using Integer = boost::multiprecision::cpp_int;
/// 已约分的精确分数，分母恒为正；零值统一为 0/1。
using Rational = boost::rational<Integer>;

/// 单项能力值公式的输入快照；不持有知识库、数据库或可变战斗状态。
struct StatInput {
  std::int32_t base;
  std::int32_t iv;
  std::int32_t ev;
  std::int32_t level;
};

/// 非 HP 能力的标准性格修正；HP 不接受性格参数。
enum class NatureEffect { decreased, neutral, increased };

/// 击杀概率结果；两个概率均为精确分数，保证性判定保留 Python 原语义。
struct KoChance {
  Rational ohko;
  Rational two_hit;
  bool guaranteed_ohko;
  bool guaranteed_two_hit;
};

/// 计算现代 HP 公式；按 Python 参考实现逐层向下取整，不推定物种特例。
/// @param input 原始种族值、IV、EV 和等级；借用只读，允许参考公式的整数输入。
/// @return 精确整数 HP；结果超出 int64 时抛出 std::overflow_error。
[[nodiscard]] std::int64_t CalculateHp(const StatInput& input);

/// 计算非 HP 能力；使用 9/10、1 或 11/10 精确性格倍率。
/// @param input 与 CalculateHp 相同的只读整数输入。
/// @param nature 标准性格效果；非法枚举值抛出 std::invalid_argument。
/// @return 两次 floor 后的能力值；超出 int64 时抛出 std::overflow_error。
[[nodiscard]] std::int64_t CalculateNonHp(const StatInput& input, NatureEffect nature);

/// 把战斗能力等级应用到单项正整数能力值。
/// @param value 原能力值，必须大于 0；不会修改。
/// @param stage 必须在 -6 到 6；非法输入抛出 std::invalid_argument。
/// @return 至少为 1 的新能力值；超出 int64 时抛出 std::overflow_error。
[[nodiscard]] std::int64_t ApplyStatStage(std::int64_t value, std::int32_t stage);

/// 统计等概率独立伤害档位的一击与二击击杀率，不执行回合结束效果。
/// @param rolls 只读伤害档位，重复值仍代表独立随机槽；不得为空。
/// @param defender_hp 防守方当前 HP，必须大于 0。
/// @return 新的精确概率结果；非法输入抛出 std::invalid_argument。
[[nodiscard]] KoChance EstimateKoChance(std::span<const std::int64_t> rolls,
                          std::int32_t defender_hp);

} // namespace pbi
