#include "pbi/job_move_pool.hpp"
#include "sha256.hpp"
#include <algorithm>
#include <array>
#include <limits>

namespace pbi {
namespace {
/// @param value 原ASCII身份；拒绝首尾Python ASCII空白，不改变任何内部字符。
void ValidateText(const std::string& value) {
  const auto whitespace = [](unsigned char character) { return (character >= 9 && character <= 13) || (character >= 28 && character <= 32); };
  if (value.empty() || whitespace(value.front()) || whitespace(value.back())) throw std::invalid_argument("job identity must be nonempty and normalized");
  if (std::ranges::any_of(value, [](unsigned char character) { return character > 127; })) throw std::invalid_argument("job identity must use stable ASCII text");
}
/// @param selection 本对象拥有的单侧输入；原池只排序并拒绝重复，不做机制过滤。
void NormalizeSelection(JobMovePoolSelection& selection) {
  const auto& fixed = selection.fixed;
  if (fixed.pokemon_id <= 0 || (fixed.form_id && *fixed.form_id <= 0) || fixed.level < 1 || fixed.level > 100) {
    throw std::invalid_argument("job fixed Pokemon IDs and level must be valid");
  }
  ValidateText(fixed.stat_profile_id);
  ValidateText(fixed.ability_identifier);
  if (fixed.item_identifier) ValidateText(*fixed.item_identifier);
  auto& moves = selection.candidate_move_ids;
  std::ranges::sort(moves);
  if (moves.empty() || moves.front() <= 0 || std::ranges::adjacent_find(moves) != moves.end()) {
    throw std::invalid_argument("job candidate moves must be positive and unique and nonempty");
  }
}
/// @param n 已有<=20的候选数；@param k 0..4；@return 精确小规模组合数，无浮点。
std::size_t Choose(std::size_t n, std::size_t k) {
  if (k > n) return 0;
  std::size_t result = 1;
  for (std::size_t index = 1; index <= k; ++index) result = result * (n - index + 1) / index;
  return result;
}
/// @param moves 已排序唯一候选；@param ordinal 单侧字典序索引；@return 与原combinations一致的技能组。
std::vector<std::int64_t> MoveSet(const std::vector<std::int64_t>& moves, std::size_t ordinal) {
  if (moves.size() < 4) return moves;
  std::vector<std::int64_t> result;
  std::size_t start = 0;
  for (std::size_t remaining = 4; remaining > 0; --remaining) {
    for (std::size_t index = start; index + remaining <= moves.size(); ++index) {
      const auto suffixes = Choose(moves.size() - index - 1, remaining - 1);
      if (ordinal >= suffixes) { ordinal -= suffixes; continue; }
      result.push_back(moves[index]);
      start = index + 1;
      break;
    }
  }
  return result;
}
/// @param text 已验证ASCII身份；@param ascii Python ensure_ascii模式；@return 原紧凑JSON字符串。
std::string JsonString(const std::string& text, bool ascii) {
  std::string result = "\"";
  constexpr char hex[] = "0123456789abcdef";
  for (const unsigned char character : text) {
    switch (character) {
    case '"': result += "\\\""; break;
    case '\\': result += "\\\\"; break;
    case '\b': result += "\\b"; break;
    case '\f': result += "\\f"; break;
    case '\n': result += "\\n"; break;
    case '\r': result += "\\r"; break;
    case '\t': result += "\\t"; break;
    default:
      if (character < 32 || (ascii && character == 127)) {
        result += "\\u00"; result += hex[character >> 4]; result += hex[character & 15];
      } else result += static_cast<char>(character);
    }
  }
  return result + '"';
}
/// @param fixed 原固定配置；@param moves 规范技能组；@param ascii 原JSON模式。
/// @return 原七位置数组的内容，不含外层括号，供pair与side各自按合同封装。
std::string SidePayload(const JobFixedPokemon& fixed, const std::vector<std::int64_t>& moves, bool ascii) {
  auto result = std::to_string(fixed.pokemon_id) + ',' + (fixed.form_id ? std::to_string(*fixed.form_id) : "null") + ',' +
      std::to_string(fixed.level) + ',' + JsonString(fixed.stat_profile_id, ascii) + ',' + JsonString(fixed.ability_identifier, ascii) + ',' +
      (fixed.item_identifier ? JsonString(*fixed.item_identifier, ascii) : "null") + ",[";
  for (std::size_t index = 0; index < moves.size(); ++index) {
    if (index != 0) result += ',';
    result += std::to_string(moves[index]);
  }
  return result + ']';
}

} // namespace

JobMovePool::JobMovePool(JobMovePoolInput input) : input_(std::move(input)), attacker_count_(0), defender_count_(0) {
  if (input_.contract_version != "one-on-one-move-pool.v1") throw std::invalid_argument("unsupported one-on-one contract version");
  ValidateText(input_.ruleset_id);
  ValidateText(input_.calculation_revision);
  if (input_.version_group_id <= 0) throw std::invalid_argument("job version group must be positive");
  NormalizeSelection(input_.attacker);
  NormalizeSelection(input_.defender);
  if (input_.attacker.candidate_move_ids.size() > 20 || input_.defender.candidate_move_ids.size() > 20 - input_.attacker.candidate_move_ids.size()) {
    throw std::invalid_argument("attacker and defender candidate moves must total at most 20");
  }
  const auto& modes = input_.dimensions;
  for (const auto mode : {modes.pokemon, modes.form, modes.level, modes.stats, modes.ability, modes.item}) {
    if (mode != JobDimensionMode::fixed) throw std::invalid_argument("v1 only allows fixed non-move dimensions");
  }
  if (modes.moves != JobDimensionMode::candidate_pool || modes.special_mechanics != JobDimensionMode::disabled) {
    throw std::invalid_argument("v1 requires candidate move pools and disabled special mechanics");
  }
  for (const auto policy : {input_.attacker_policy, input_.defender_policy}) {
    if (policy != ActionPolicy::uniform_random && policy != ActionPolicy::first_legal_action) throw std::invalid_argument("unknown job action policy");
  }
  /// @param size 一侧原始候选数；@return 原具体技能组数，不按能力等价性归并。
  const auto count = [](std::size_t size) { return size < 4 ? std::size_t{1} : Choose(size, 4); };
  attacker_count_ = count(input_.attacker.candidate_move_ids.size());
  defender_count_ = count(input_.defender.candidate_move_ids.size());
}

JobMovePoolCase JobMovePool::CaseAt(std::size_t ordinal) const {
  if (ordinal >= CaseCount()) throw std::out_of_range("job case ordinal exceeds the complete pool");
  auto attacker = MoveSet(input_.attacker.candidate_move_ids, ordinal / defender_count_);
  auto defender = MoveSet(input_.defender.candidate_move_ids, ordinal % defender_count_);
  const auto first = SidePayload(input_.attacker.fixed, attacker, false), second = SidePayload(input_.defender.fixed, defender, false);
  auto pair_id = "one-on-one-configuration:[" + JsonString(input_.contract_version, false) + ',' + JsonString(input_.ruleset_id, false) + ',' +
      std::to_string(input_.version_group_id) + ',' + JsonString(input_.calculation_revision, false) + ",[" + first + "],[" + second + "]]";
  const auto attacker_id = "one-on-one-side-" + detail::Sha256("[\"attacker\"," + SidePayload(input_.attacker.fixed, attacker, true) + ']');
  const auto defender_id = "one-on-one-side-" + detail::Sha256("[\"defender\"," + SidePayload(input_.defender.fixed, defender, true) + ']');
  return {ordinal, std::move(pair_id), attacker_id, defender_id, std::move(attacker), std::move(defender), Rational{Integer{1}, Integer{CaseCount()}}};
}

std::vector<JobMovePoolCase> JobMovePool::Page(std::size_t offset, std::size_t limit, CancellationToken cancellation) const {
  if (offset > CaseCount()) throw std::out_of_range("job page offset exceeds the complete pool");
  if (cancellation.Requested()) throw std::runtime_error("job move pool enumeration cancelled");
  const auto count = std::min(limit, CaseCount() - offset);
  std::vector<JobMovePoolCase> result;
  result.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    if (cancellation.Requested()) throw std::runtime_error("job move pool enumeration cancelled");
    result.push_back(CaseAt(offset + index));
  }
  return result;
}
} // namespace pbi
