# 配置图有界benchmark复现

在项目根目录运行，依赖项目Python环境、CMake、C++20、Boost及nlohmann-json。先通过统一入口构建并验证`build/core`，再构建只链接该库的测量适配器；不要混用不同提交的头文件和静态库。维护容器中的路径对应`/source/core`及显式冻结的`/build/root-summary-abi11`。

```sh
# 指向同一份已验证Core源码及archive；输出独立的测量适配器，不修改正式库。
cmake -S tools/migration/benchmarks -B build/configuration-benchmark -DCMAKE_BUILD_TYPE=Release -DPBI_CORE_SOURCE_ROOT="$PWD/core" -DPBI_CORE_ARCHIVE_DIR="$PWD/build/core"
cmake --build build/configuration-benchmark -j2

# 冻结原完整20候选、前两个具体配置及原500/2000/8预算，报告目录由调用方选择。
python -m tools.migration.benchmark_configuration_graph --prepare --manifest build/benchmark-workload.json --source-revision "$(git rev-parse HEAD)"

# 单个测量示例；workers仅接受1或2，每次都重建真实图。
python -m tools.migration.benchmark_configuration_graph --manifest build/benchmark-workload.json --source-revision "$(git rev-parse HEAD)" --backend cpp --mode full --workers 1 --executable "$PWD/build/configuration-benchmark/pbi_fixed_benchmark" --output build/cpp-full-w1.json
```

分别运行`full`、`configuration_summary`两模式，`python`、`cpp`、`go`三后端和workers1/2，得到12份报告。Python不传executable；Go传同一Core版本的正式`pbi-core-worker`绝对路径。所有组必须使用相同冻结manifest、原Python源及测量工具字节。比较入口为`python -m tools.migration.compare_configuration_benchmark --reports`后接完整12个JSON路径，并提供`--engine-version`和`--output`；缺组、版本/来源/完整结果不同均拒绝生成比较。

正式结果及原始证据见`docs/benchmarks/configuration-graph-20261125.*`。该轮12组使用的原工具已随证据归档，当前工具另有三项静态类型修正及独立真实Go样本核验；不能把新工具SHA写回旧测量。Full和Summary分别比较，不用旧Full耗时替代Summary的Python参考。每组仅两个配置的单次测量，不代表44100全空间、数据库写入或HTTP吞吐。
