// 差分测试的进程边界适配器：标准输入每行一个整数向量，标准输出每行一个结果。
// 无网络、数据库或外部数据；失败时该行输出 ERROR，其后向量仍可执行。
#include "pbi/calculations.hpp"

#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

/// 从一行流读取有类型的必填值，缺失或越界时失败。
/// @param stream 当前向量行的可变解析流，不跨行读取。
/// @return 新值；输入无效时抛出 std::invalid_argument。
template <class T> T Read(std::istream& stream) {
  T value{};
  if (!(stream >> value)) {
    throw std::invalid_argument("missing or invalid vector field");
  }
  return value;
}

/// 将十分制性格编码转换为领域枚举，不接受不支持的倍率。
/// @param tenths 9、10 或 11。
/// @return 对应的标准性格；其他值抛出 std::invalid_argument。
pbi::NatureEffect ParseNature(int tenths) {
  switch (tenths) {
  case 9: return pbi::NatureEffect::decreased;
  case 10: return pbi::NatureEffect::neutral;
  case 11: return pbi::NatureEffect::increased;
  default: throw std::invalid_argument("unsupported nature effect");
  }
}

/// 编码规范化精确分数；整数省略 /1，以便跨语言逐行比较。
/// @param output 接收文本的可变输出流。
/// @param value 只读的已约分有理数。
/// @return 无；只写入调用方输出流。
void WriteRational(std::ostream& output, const pbi::Rational& value) {
  output << value.numerator();
  if (value.denominator() != 1) {
    output << '/' << value.denominator();
  }
}

/// 执行一个共享向量，生成精确结果，不将概率转换成 double。
/// @param input 当前行的可变解析流，operation 后必须提供对应字段。
/// @return 完整的一行结果；未知 operation、多余或无效字段抛出 std::invalid_argument。
std::string Execute(std::istream& input) {
  std::ostringstream output;
  const auto operation = Read<std::string>(input);
  if (operation == "hp" || operation == "stat") {
    const pbi::StatInput stat{Read<std::int32_t>(input), Read<std::int32_t>(input),
                              Read<std::int32_t>(input), Read<std::int32_t>(input)};
    if (operation == "hp") {
      output << pbi::CalculateHp(stat);
    } else {
      output << pbi::CalculateNonHp(stat, ParseNature(Read<int>(input)));
    }
  } else if (operation == "stage") {
    const auto value = Read<std::int64_t>(input);
    const auto stage = Read<std::int32_t>(input);
    output << pbi::ApplyStatStage(value, stage);
  } else if (operation == "ko") {
    const auto hp = Read<std::int32_t>(input);
    std::vector<std::int32_t> rolls;
    while (input >> std::ws && !input.eof()) {
      rolls.push_back(Read<std::int32_t>(input));
    }
    const auto result = pbi::EstimateKoChance(rolls, hp);
    WriteRational(output, result.ohko);
    output << ' ';
    WriteRational(output, result.two_hit);
    output << ' ' << result.guaranteed_ohko << ' ' << result.guaranteed_two_hit;
  } else {
    throw std::invalid_argument("unsupported vector operation");
  }
  input >> std::ws;
  if (!input.eof()) {
    throw std::invalid_argument("unexpected vector field");
  }
  return output.str();
}

} // namespace

/// 读取批量向量并独立执行；无参数，正常 EOF 返回 0，流故障返回 1。
/// @return 进程退出码；单条领域错误通过 ERROR 行报告，不终止后续向量。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      std::istringstream input{line};
      std::cout << Execute(input) << '\n';
    } catch (const std::exception& error) {
      std::cout << "ERROR " << error.what() << '\n';
    }
  }
  return std::cin.bad() ? 1 : 0;
}
