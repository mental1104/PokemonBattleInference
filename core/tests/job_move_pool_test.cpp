#include "pbi/job_move_pool.hpp"
#include "pbi/configuration_admission.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param first 攻方池大小；@param second 守方池大小；@return 原v1身份与倒序原候选。
JobMovePoolInput Input(std::size_t first, std::size_t second) {
  JobMovePoolInput input{"pokemon-champion", 25, "legacy-r1",
      {{149, std::nullopt, 50, "max_atk_plus", "multiscale", std::nullopt}, {}},
      {{461, std::nullopt, 50, "max_atk_plus", "technician", std::nullopt}, {}}, {},
      ActionPolicy::uniform_random, ActionPolicy::uniform_random, "one-on-one-move-pool.v1"};
  for (std::size_t index = first; index > 0; --index) input.attacker.candidate_move_ids.push_back(static_cast<std::int64_t>(index));
  for (std::size_t index = second; index > 0; --index) input.defender.candidate_move_ids.push_back(static_cast<std::int64_t>(index));
  return input;
}
/// 原小池只取全池，不为1/2/3招子集或初始槽位置换创建额外case。
TEST(JobMovePool, PreservesSmallPoolCanonicalIdentity) {
  const JobMovePool pool{Input(3, 2)};
  ASSERT_EQ(pool.CaseCount(), 1);
  const auto item = pool.CaseAt(0);
  EXPECT_EQ(item.attacker_move_ids, (std::vector<std::int64_t>{1, 2, 3}));
  EXPECT_EQ(item.configuration_pair_id,
      R"(one-on-one-configuration:["one-on-one-move-pool.v1","pokemon-champion",25,"legacy-r1",[149,null,50,"max_atk_plus","multiscale",null,[1,2,3]],[461,null,50,"max_atk_plus","technician",null,[1,2]]])");
  EXPECT_EQ(item.configuration_weight, Rational{1});
  EXPECT_EQ(item.attacker_configuration_id.size(), std::string{"one-on-one-side-"}.size() + 64);
}
/// 10+10必须生成44100个具体case，按攻方外层/守方内层combinations顺序定位。
TEST(JobMovePool, Preserves44100ConcreteCasesAndLexicographicOrder) {
  const JobMovePool pool{Input(10, 10)};
  ASSERT_EQ(pool.CaseCount(), 44100);
  ASSERT_EQ(pool.AttackerMoveSetCount(), 210);
  const auto first = pool.CaseAt(0), next = pool.CaseAt(1), later = pool.CaseAt(210), last = pool.CaseAt(44099);
  EXPECT_EQ(first.attacker_move_ids, (std::vector<std::int64_t>{1, 2, 3, 4}));
  EXPECT_EQ(next.defender_move_ids, (std::vector<std::int64_t>{1, 2, 3, 5}));
  EXPECT_EQ(later.attacker_move_ids, (std::vector<std::int64_t>{1, 2, 3, 5}));
  EXPECT_EQ(last.defender_move_ids, (std::vector<std::int64_t>{7, 8, 9, 10}));
  EXPECT_EQ(first.configuration_weight, (Rational{1, 44100}));
  EXPECT_THROW((void)pool.CaseAt(44100), std::out_of_range);
}
/// 预算/重复/固定维度错误整体拒绝，分页不缩减分母并支持整页取消。
TEST(JobMovePool, RejectsInvalidPoolsAndCancelsPages) {
  EXPECT_THROW((void)JobMovePool{Input(11, 10)}, std::invalid_argument);
  auto duplicate = Input(2, 2);
  duplicate.attacker.candidate_move_ids = {1, 1};
  EXPECT_THROW((void)JobMovePool{duplicate}, std::invalid_argument);
  auto modes = Input(1, 1);
  modes.dimensions.stats = JobDimensionMode::candidate_pool;
  EXPECT_THROW((void)JobMovePool{modes}, std::invalid_argument);
  const JobMovePool pool{Input(5, 5)};
  EXPECT_EQ(pool.Page(24, 10).size(), 1);
  EXPECT_TRUE(pool.Page(25, 10).empty());
  CancellationSource stop;
  EXPECT_TRUE(stop.Request());
  EXPECT_THROW((void)pool.Page(0, 1, stop.Token()), std::runtime_error);
}
/// 透明占位整体supported不能遮住真实机制缺口，默认通用工厂不被改变。
TEST(ConfigurationAdmission, PreservesTransparentFactoryAndStrictPartialStatus) {
  const auto standard = DescribeConfigurationEffect(ConfigurationEffectSource::ability, "pressure");
  EXPECT_EQ(standard.status, ConfigurationEffectStatus::unsupported);
  const auto strict = DescribeConfigurationAdmission({ConfigurationEffectSource::ability, "pressure", "pressure", "Repository source.", true, false});
  EXPECT_EQ(strict.coverage.status, ConfigurationEffectStatus::supported);
  EXPECT_EQ(strict.status, ConfigurationAdmissionStatus::partial);
  EXPECT_FALSE(strict.Selectable());
  EXPECT_EQ(strict.missing_mechanism_identifiers, (std::vector<std::string>{"real_ability_behavior"}));
}
/// 允许明确no-effect的纯伤害/无道具，与基础字段不足或变化招式缺失不能混同。
TEST(ConfigurationAdmission, DistinguishesNoEffectAndMissingBaseExecution) {
  const ConfigurationAdmissionInput damage{ConfigurationEffectSource::move, std::nullopt, "base-damage", "Repository source.", true, true};
  EXPECT_EQ(DescribeConfigurationAdmission(damage).status, ConfigurationAdmissionStatus::no_effect);
  auto invalid = damage;
  invalid.base_executable = false;
  const auto rejected = DescribeConfigurationAdmission(invalid);
  EXPECT_FALSE(rejected.Selectable());
  EXPECT_EQ(rejected.missing_mechanism_identifiers, (std::vector<std::string>{"base-damage"}));
  auto status_move = damage;
  status_move.allow_no_effect = false;
  EXPECT_FALSE(DescribeConfigurationAdmission(status_move).Selectable());
}
} // namespace
} // namespace pbi
