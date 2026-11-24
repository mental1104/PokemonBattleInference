#include "pbi/job_move_pool.hpp"
#include <algorithm>
#include <array>
#include <bit>
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
/// @param text 原ensure_ascii=True的完整UTF-8字节；@return 小写SHA-256摘要。
/// 仅用于旧side配置身份，按FIPS180-4分块；common正式C++子模块无对应SHA256可复用。
std::string Sha256(const std::string& text) {
  constexpr std::array<std::uint32_t, 64> constants{
      0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
      0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
      0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
      0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
      0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
      0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
      0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
      0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U};
  if (text.size() > std::numeric_limits<std::uint64_t>::max() / 8) throw std::length_error("job identity is too large for SHA256");
  const auto bits = static_cast<std::uint64_t>(text.size()) * 8;
  std::vector<unsigned char> message(text.begin(), text.end());
  message.push_back(0x80);
  while (message.size() % 64 != 56) message.push_back(0);
  for (int byte = 7; byte >= 0; --byte) message.push_back(static_cast<unsigned char>(bits >> (byte * 8)));
  std::array<std::uint32_t, 8> state{0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U};
  for (std::size_t block = 0; block < message.size(); block += 64) {
    std::array<std::uint32_t, 64> schedule{};
    for (std::size_t index = 0; index < 16; ++index) for (std::size_t byte = 0; byte < 4; ++byte) {
      schedule[index] = (schedule[index] << 8) | message[block + index * 4 + byte];
    }
    for (std::size_t index = 16; index < schedule.size(); ++index) {
      const auto first = schedule[index - 15], second = schedule[index - 2];
      const auto sigma0 = std::rotr(first, 7) ^ std::rotr(first, 18) ^ (first >> 3);
      const auto sigma1 = std::rotr(second, 17) ^ std::rotr(second, 19) ^ (second >> 10);
      schedule[index] = schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1;
    }
    auto working = state;
    for (std::size_t index = 0; index < schedule.size(); ++index) {
      const auto s1 = std::rotr(working[4], 6) ^ std::rotr(working[4], 11) ^ std::rotr(working[4], 25);
      const auto choose = (working[4] & working[5]) ^ (~working[4] & working[6]);
      const auto t1 = working[7] + s1 + choose + constants[index] + schedule[index];
      const auto s0 = std::rotr(working[0], 2) ^ std::rotr(working[0], 13) ^ std::rotr(working[0], 22);
      const auto majority = (working[0] & working[1]) ^ (working[0] & working[2]) ^ (working[1] & working[2]);
      working = {t1 + s0 + majority, working[0], working[1], working[2], working[3] + t1, working[4], working[5], working[6]};
    }
    for (std::size_t index = 0; index < state.size(); ++index) state[index] += working[index];
  }
  constexpr char hex[] = "0123456789abcdef";
  std::string digest;
  digest.reserve(64);
  for (const auto value : state) for (int nibble = 7; nibble >= 0; --nibble) digest += hex[(value >> (nibble * 4)) & 15];
  return digest;
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
  const auto attacker_id = "one-on-one-side-" + Sha256("[\"attacker\"," + SidePayload(input_.attacker.fixed, attacker, true) + ']');
  const auto defender_id = "one-on-one-side-" + Sha256("[\"defender\"," + SidePayload(input_.defender.fixed, defender, true) + ']');
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
