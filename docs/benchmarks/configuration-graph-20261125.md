# 同语义配置图有界基准

测量源码为正式Core 0.11；旧7组与恢复后的5组逐项核对同一原Python源码、冻结输入、测量工具SHA及引擎版本，12组比较通过后才生成此表。原生archive和Core源文件SHA已重新核对。完整输入、12份原始报告、测量时的Python工具与C++适配器保存在同目录`configuration-graph-20261125-evidence.tar.gz`，可独立审查原始计时与来源。

当前工具随后修复了三项静态类型问题：TypeAdapter显式类型、保留MoveCategory枚举、在两个分支中明确展开计数。strict mypy通过；新工具另跑Go Summary/单worker并比较原完整结果，独立保存于私有报告`typed-tool-smoke.json`，没有混入下表12组测量。测量时工具的字节仍完整保存在证据归档中。

运行环境为同一NAS维护容器、3GiB内存上限；各组先后执行，负载快照、实际cgroup限制及逐case CPU/RSS都保存在原始JSON。单次测量存在机器负载差异，表中Go与C++的差别只代表本次记录，语言收益须结合相同语义及过程开销阅读。

Original 10+10 candidate fixture, first two concrete pairs with global 44100 denominator and unchanged 500 nodes/2000 edges/8 turns. Each run rebuilds fresh; no cached graph queries. Full and configuration_summary compared separately. Evaluation includes result-model projection; process wall includes startup/CGO/JSON/stdio. Synthetic fact preparation measured separately; no PostgreSQL, HTTP or full-space throughput measurement. One bounded sample per implementation/workers/mode, not a statistical median or an extrapolated 44100-case result.

所有同模式精确结果、原权重和真实展开计数一致后生成下表。

| 模式 | Workers | Python wall(s) | C++ process(s) | Go process(s) | Python/C++ wall | Python/Go wall |
|---|---:|---:|---:|---:|---:|---:|
| full | 1 | 405.251852 | 44.853447 | 28.466708 | 9.04x | 14.24x |
| full | 2 | 142.169478 | 27.764301 | 16.945925 | 5.12x | 8.39x |
| configuration_summary | 1 | 13.990704 | 1.594373 | 1.039473 | 8.78x | 13.46x |
| configuration_summary | 2 | 7.127502 | 0.998403 | 0.556173 | 7.14x | 12.82x |

旧 270.777/140.881 秒保留在 legacy-graph-20261124 中，属于 Full 历史记录，未用作 Summary 的语言收益分母。
