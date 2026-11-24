#include "../src/state_contract.hpp"
#include <gtest/gtest.h>
#include <fstream>

namespace pbi::contract {
namespace {
/// @return 正式冻结state向量，不另建第二套状态schema或动态能力算法。
Json StateFixture() {
  std::ifstream input(std::string{PBI_VECTOR_DIR} + "/abi-calculations.v1.request.json");
  if (!input) throw std::runtime_error("cannot read transparent state fixture");
  Json value;
  input >> value;
  for (const auto& operation : value.at("operations")) if (operation.at("kind") == "battle_turn") return operation.at("state");
  throw std::runtime_error("required state fixture is missing");
}
/// Raw标识和显式context由唯一Core decoder解释，完整重放仍保留真实标识且Key遵循原UNKNOWN。
TEST(TransparentAbilityContract, PreservesRawIdentityAndOriginalUnknownRoundtripKey) {
  auto value = StateFixture();
  value["attacker"]["spec"]["pokemon"]["ability"] = "none";
  const auto baseline = ReadBattleStateValue(value);
  value["attacker"]["spec"]["pokemon"]["ability"] = "pressure";
  value["attacker"]["spec"]["ability_context"] = "transparent_inference";
  const auto pressure = ReadBattleStateValue(value);
  EXPECT_EQ(pressure.Key(), baseline.Key());
  const auto encoded = StateJson(pressure);
  EXPECT_EQ(encoded["attacker"]["spec"]["pokemon"]["ability"], "pressure");
  EXPECT_EQ(encoded["attacker"]["spec"]["ability_context"], "transparent_inference");
  EXPECT_EQ(ReadBattleStateValue(encoded).Key(), pressure.Key());
  value["attacker"]["spec"]["pokemon"]["ability"] = "pickpocket";
  const auto pickpocket = ReadBattleStateValue(value);
  EXPECT_EQ(pickpocket.Key(), pressure.Key());
  EXPECT_EQ(StateJson(pickpocket)["attacker"]["spec"]["pokemon"]["ability"], "pickpocket");
}
/// 默认严格上下文、非白名单与未知context仍明确拒绝，通用ReadPokemon不获宽泛UNKNOWN回退。
TEST(TransparentAbilityContract, RejectsImplicitAndUnknownNeutralAssumptions) {
  auto value = StateFixture();
  value["attacker"]["spec"]["pokemon"]["ability"] = "pressure";
  EXPECT_THROW((void)ReadBattleStateValue(value), RequestError);
  value["attacker"]["spec"]["ability_context"] = "transparent_inference";
  value["attacker"]["spec"]["pokemon"]["ability"] = "unimplemented-ability";
  EXPECT_THROW((void)ReadBattleStateValue(value), RequestError);
  value["attacker"]["spec"]["pokemon"]["ability"] = "pressure";
  value["attacker"]["spec"]["ability_context"] = "unknown-context";
  EXPECT_THROW((void)ReadBattleStateValue(value), RequestError);
  EXPECT_THROW((void)ReadPokemon(value["attacker"]["spec"]["pokemon"]), RequestError);
}
} // namespace
} // namespace pbi::contract
