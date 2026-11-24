# C++ Core（P1 进行中）

当前可运行切片是现代能力值、能力等级、直接伤害及给定伤害档位的 KO 概率。`pbi_core` 是纯 C++20 静态库；不依赖数据库、HTTP、UI、CSV 或平台服务，不修改输入，状态只存在于调用栈和局部值中。

## 构建与统一验证

依赖 C++20 编译器、CMake 3.20+、Boost headers；默认 C ABI 适配器另需 nlohmann_json，测试另需 GoogleTest 的 CMake package。纯计算库可用 `PBI_BUILD_ABI=OFF` 排除 JSON 适配器。Debian 验证镜像使用 GCC 14.2、Boost 1.83、GoogleTest 1.16。CMake 不在构建时下载依赖。

从仓库根执行 macOS/Linux 共用入口：

```sh
make test
```

它先构建 Core 并执行 CTest，再运行全部 Python 测试（包括通过真实 C++ 进程的差分及 Go/Swift 原生测试委托）。缺少未显式配置的语言工具时会明确 SKIP，配置错误会 FAIL。Python/common 依赖沿用项目要求；Makefile 默认使用当前仓库固定版本的 common submodule，允许显式 `COMMON_ROOT` 覆盖。

只验证 Core：

```sh
make test-core
PBI_CORE_VECTOR_RUNNER="$PWD/build/core/pbi_core_vectors" python -m pytest tests/migration
```

只构建库、不依赖 GoogleTest：

```sh
cmake -S core -B build/core-library -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build/core-library --target pbi_core
```

NAS 上无需改变宿主编译器/Python，使用已声明的 maintenance 服务：

```sh
bash tools/migration/validate-nas.sh core
bash tools/migration/validate-nas.sh all
```

`all` 为每次运行创建专用 PostgreSQL 16，只连接该唯一容器名称；退出时停止该容器，`run --rm` 移除。它不发布数据库端口、不挂载生产数据、不改变 HomeLab 常驻服务。构建在 `/volume2/docker/pokemon-migration-validation/build`，报告在用户 Backup；可以通过 `POKEOP_BUILD_ROOT`、`POKEOP_REPORT_ROOT` 显式指定已有职责范围内的输出目录。

直接运行 pytest 时，如果没有配置 runner 且默认位置尚未构建，四个差分测试会说明构建步骤并 SKIP；显式配置但不可执行则 FAIL。`make test` 始终先构建，不能靠缺失二进制跳过差分。PostgreSQL 的 macOS/Linux 合同仍由原 fixture 管理；Core 单测和差分不请求该 fixture。

## 数值与行为合同

- `Integer` 使用 `boost::multiprecision::cpp_int`，`Rational` 使用 `boost::rational<Integer>`；分数约分、分母为正、零为 `0/1`。没有机器整数分母上限，也不使用 `double` 代替概率。
- 性格显式建模为降低/中性/提高，即 9/10、1、11/10。不支持的枚举值显式失败，不默认为中性。
- HP、非 HP 逐层 floor 与当前 Python 的现代公式一致。共享向量和 4,096 个固定种子配置各验证 HP/非 HP；全部 -6…6 等级在 7 个基数上验证。没有擅自增加脱壳忍者等原公式未实现的特例。
- 能力公式保留原整数输入形状，使用任意精度中间值并检查 int64 返回边界。在超过 IEEE-754 精确整数范围的非正常配置上，Python 原 float 除法可能舍入，新 Core 按数学整数公式处理；该边界由整数 oracle 验证，不宣称这类输入与旧 float 逐位相同。正式合法等级/IV/EV 范围内的已测向量没有行为差异。
- KO 输入中的重复档位各自保留随机权重；两击为有序的独立抽样。排序+二分计数与 Python 逐对枚举一致；144 组变长/重复/边界向量做精确比较。原 Python 展示小数只用于核对展示值，新 Core 结果保留分数。
- KO 不执行任何回合结束回血、扣血等效果。当前 API 没有这种输入，不能将它当作完整回合推演入口。
- 直接伤害通过 `DamageInput` 与 `TypeChartSnapshot` 注入策略、属性知识和双方快照。顺序保留原基础威力/能力阶段 floor、STAB/相克、屏障/会心/范围/保护、天气/场地、特性/道具、随机档位；每项 trace 与 Python 对照。binary64 仅用于原链已有的伤害倍率，概率不使用浮点数。整数比值使用任意精度分子/分母并正确舍入到 binary64，避免大整数先转 double 的双重舍入。
- 原代际 profile 与版本组解析迁入 Core，保持部分规则身份。输入不支持的特性/道具/天气/场地/变化招式或缺少知识时明确失败。multiscale/inner_focus、灼伤及其他实时 HP/状态效果仍归后续动态战斗层；完整边界及策略覆盖见 `contracts/c/README.md`。
- `pbi_core_vectors` 是差分/benchmark 的进程适配器，每行支持 `hp`、`stat`、`stage`、`ko`。结果精确编码为整数或 `numerator/denominator`；不支持的操作及非法输入逐行返回 `ERROR`，不终止下一条向量。它不作为正式跨语言 ABI。
- `pbi_abi_vectors` 每行直接调用真实 `pbi_v1_compute`，原样返回其完整 JSON 并释放结果。伤害差分使用这个入口，正式 Go/Swift 调用仍链接同一库。

实现中曾发现当前环境 `cpp_rational` 的 `0 / 16` 未规范化且与零不相等，原测试实际捕获该问题；已改用 `boost::rational<cpp_int>`，保留零概率、相消为零和 200 位分母测试。没有通过放宽相等断言绕过。

## 性能证据与未完成项

`docs/benchmarks/core-calculations-20261124.json` 是 20,000 个非 HP 配置、五次采样的真实批次记录：Python 中位数 7.221 ms；C++ 进程中位数 33.210 ms。C++ 数字包含进程启动、文本解析和管道 IO，Python 包含计算和输出序列化；这不是纯函数或 C ABI 调用开销比较。测量期间 NAS 另有原图 benchmark 和其他服务负载，不能据此推断完整 Core 性能或迁移提速。

复现：

```sh
PYTHONPATH=submodules/common/python:. python tools/migration/benchmark_calculations.py --runner build/core/pbi_core_vectors --output /tmp/pbi-calculations-benchmark.json
```

速度状态效果、完整规则集/动态伤害效果、不可变战斗状态、StateKey、效果分发、回合解析、概率转移、状态图、SCC、图求解、配置搜索与事件分析尚未迁移。首批 C ABI 和 Go/Swift 实际调用、取消/批量/内存合同已在 Linux/macOS 验证，详见 `contracts/c/README.md`；首批 iPhoneOS/Simulator 的 Core/Swift 静态产物和 XCFramework 也已通过真实 GitHub CI 构建及产物核验。新伤害批次的验证记录见 `docs/migration-progress.md`。尚无 App/模拟器运行或真机验收，P1/P2 仍均为 IN_PROGRESS。
