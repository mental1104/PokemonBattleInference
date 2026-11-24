#include "../src/projection_number_contract.hpp"
#include "../src/event_record_contract.hpp"
#include <gtest/gtest.h>

namespace pbi::contract {
/// 旧operation默认1024位保护不放宽，projection单独无损读取1500位并保持十进制语义。
TEST(ProjectionNumberContract, LegacyBudgetStaysUnchangedWhileProjectionKeepsLongIntegers) {
  const std::string text(1500, '9');
  try {
    static_cast<void>(ReadDecimalInteger(Json(text)));
    FAIL() << "legacy integer budget was silently widened";
  } catch (const RequestError& error) {
    EXPECT_EQ(error.code, PBI_RESOURCE_LIMIT_V1);
  }
  EXPECT_EQ(ReadProjectionInteger(Json(text), {}).str(), text);
  EXPECT_EQ(ReadProjectionInteger(Json("-0000123"), {}), Integer{-123});
  EXPECT_EQ(ReadProjectionInteger(Json("0000123"), {}), Integer{123});
}

/// 唯一事件事实parser仅在projection入口接受长条件权重，原event入口仍拒绝超1024位。
TEST(ProjectionNumberContract, EventPathWeightsUseExplicitOperationBudget) {
  const std::string denominator = "1" + std::string(1500, '0');
  const std::string remainder(1500, '9');
  // outcome是固定随机结果标识；返回完整原事件协议，不产生替代规则。
  const auto event = [](const char* outcome) -> Json {
    return {{"kind", "random"}, {"event_type", "custom"}, {"event_id", "long-weight"}, {"outcome_id", outcome}, {"numeric_value", nullptr}};
  };
  const Json paths = Json::array({
      {{"events", Json::array({event("first")})}, {"probability", {{"numerator", "1"}, {"denominator", denominator}}}},
      {{"events", Json::array({event("second")})}, {"probability", {{"numerator", remainder}, {"denominator", denominator}}}}});
  try {
    static_cast<void>(ReadEventSummaryValue(paths, {}));
    FAIL() << "legacy event path budget was silently widened";
  } catch (const RequestError& error) {
    EXPECT_EQ(error.code, PBI_RESOURCE_LIMIT_V1);
  }
  const auto result = ReadProjectionEventSummaryValue(paths, {});
  ASSERT_EQ(result.Paths().size(), 2);
  EXPECT_EQ(result.Paths()[0].probability.numerator(), Integer{1});
  EXPECT_EQ(result.Paths()[0].probability.denominator().str(), denominator);
  EXPECT_EQ(result.Paths()[1].probability.numerator().str(), remainder);
  EXPECT_EQ(result.Paths()[0].probability + result.Paths()[1].probability, Rational{1});
}

/// 新长数值解析使用同源取消，并以正式CABI CANCELLED结束而不是返回前缀或INTERNAL。
TEST(ProjectionNumberContract, LongIntegerReadCancellationUsesExplicitStatus) {
  CancellationSource source;
  static_cast<void>(source.Request());
  try {
    static_cast<void>(ReadProjectionInteger(Json(std::string(4000, '7')), source.Token()));
    FAIL() << "cancelled projection parser returned a partial integer";
  } catch (const RequestError& error) {
    EXPECT_EQ(error.code, PBI_CANCELLED_V1);
  }
}
} // namespace pbi::contract
