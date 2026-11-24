#include "pbi/calculations.hpp"
#include <gtest/gtest.h>
#include <limits>
#include <stdexcept>
#include <vector>

namespace pbi {

/// 锁定原测试中的巨钳螳螂与仙子伊布能力配置及 floor 顺序。
TEST(Stats, ReferenceProfiles) {
  EXPECT_EQ(CalculateHp({95, 31, 252, 50}), 202);
  EXPECT_EQ(CalculateNonHp({130, 31, 252, 50}, NatureEffect::increased), 200);
  EXPECT_EQ(CalculateNonHp({130, 31, 252, 50}, NatureEffect::neutral), 182);
  EXPECT_EQ(CalculateNonHp({65, 31, 252, 50}, NatureEffect::increased), 128);
  EXPECT_THROW(static_cast<void>(CalculateNonHp({65, 31, 252, 50}, static_cast<NatureEffect>(99))),
               std::invalid_argument);
}

/// 任意精度中间计算仍须与数学 floor 一致，尤其是负 EV 参考公式。
TEST(Stats, IntegerFloorAndOverflow) {
  EXPECT_EQ(CalculateHp({0, 0, -1, 50}), 59);
  constexpr auto maximum = std::numeric_limits<std::int32_t>::max();
  EXPECT_EQ(CalculateHp({maximum, maximum, maximum, maximum}), 149879797590681199LL);
  EXPECT_THROW(static_cast<void>(ApplyStatStage(std::numeric_limits<std::int64_t>::max(), 6)),
               std::overflow_error);
}

/// 能力等级不得接受零值或超范围等级，最小结果保持为 1。
TEST(StatStage, Boundaries) {
  EXPECT_EQ(ApplyStatStage(110, -1), 73);
  EXPECT_EQ(ApplyStatStage(80, 6), 320);
  EXPECT_EQ(ApplyStatStage(1, -6), 1);
  EXPECT_THROW(static_cast<void>(ApplyStatStage(0, 0)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ApplyStatStage(100, 7)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ApplyStatStage(100, -7)), std::invalid_argument);
}

/// 16 档随机值保留原 246/256 二击率，同时禁止浮点近似。
TEST(KoChance, ReferenceRolls) {
  const std::vector<std::int32_t> rolls{99, 100, 101, 102, 104, 105, 106, 107,
                                       108, 109, 111, 112, 113, 114, 115, 117};
  const auto result = EstimateKoChance(rolls, 202);
  EXPECT_EQ(result.ohko, Rational{0});
  EXPECT_EQ(result.two_hit, Rational{123} / 128);
  EXPECT_FALSE(result.guaranteed_ohko);
  EXPECT_FALSE(result.guaranteed_two_hit);
  EXPECT_EQ(rolls.front(), 99);
}

/// 非二进制概率、重复档位和极端伤害均精确统计，输入快照不变。
TEST(KoChance, DuplicateWeightsAndIntegerEdges) {
  const std::vector<std::int32_t> rolls{1, 1, 3};
  const auto result = EstimateKoChance(rolls, 3);
  EXPECT_EQ(result.ohko, Rational{1} / 3);
  EXPECT_EQ(result.two_hit, Rational{5} / 9);
  EXPECT_EQ(rolls, (std::vector<std::int32_t>{1, 1, 3}));
  const std::vector<std::int32_t> extreme{std::numeric_limits<std::int32_t>::max()};
  EXPECT_TRUE(EstimateKoChance(extreme, 1).guaranteed_two_hit);
  EXPECT_THROW(static_cast<void>(EstimateKoChance({}, 1)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(EstimateKoChance(rolls, 0)), std::invalid_argument);
}

/// 精确概率基础必须能表达超过机器整数范围的分母，供后续状态图相乘使用。
TEST(Rational, ArbitraryPrecision) {
  const Integer denominator = Integer{1} << 200;
  const Rational tiny = Rational{1} / denominator;
  EXPECT_EQ(tiny * denominator, Rational{1});
  EXPECT_EQ(tiny + tiny, Rational{2} / denominator);
  EXPECT_EQ(tiny / tiny, Rational{1});
  const Rational zero = tiny - tiny;
  EXPECT_EQ(zero.numerator(), Integer{0});
  EXPECT_EQ(zero.denominator(), Integer{1});
  EXPECT_EQ((Rational{0, 16}), Rational{0});
}

} // namespace pbi
