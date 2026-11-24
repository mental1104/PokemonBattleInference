# 原图投影与冻结事实查询

引擎0.10.0、calculation-rules.v10，C ABI/schema仍v1。三个操作均执行同一纯Core算法，不由Go/Swift推导分组身份、游标、概率、行动历史或路径排序。完整可重放样本分别为`tests/vectors/state-graph-projection.v1.json`及`winning-paths.v1.json`。

`state_graph_projection`读取一个真实节点、全部相关出边及累计概率。`mode:node`返回原节点/分组/可展开结果，`mode:step`读取正式edge_id和depth返回原战报步骤；保留同后继的所有条件历史，不用首条路径代替完整分组。节点、边、snapshot身份及精确概率支持任意精度十进制传输；明确取消返回CANCELLED，不残留部分成功。

`winning_paths`接受完整原图与graph_id、calculation_revision、winner、limit以及可选cursor/遍历预算。有限DFS使用原100000默认预算，联合行动归并、代表路径、当前页前缀树、循环引用、精确覆盖和cursor由Core唯一生成。未分类封闭环按原结果保留不可用胜率，不自动补SCC改成零。输出的traversal_truncated/query_complete不能被HTTP层删去或改成完全覆盖。

`fixed_graph_query`接受`fixed_request`（原完整fixed_battle操作）、expected_engine_version、expected_rules_version、expected_nodes、expected_edges，以及含graph_id、calculation_revision、cursor的query。query.mode为explore、outcomes、advance、backtrack或winning_paths。Core先用同一冻结状态、知识、策略和预算重建正式typed图，再直接调用上述投影/搜索；一次请求只重建一次，完整cursor在同图内处理。版本或重建规模不匹配明确返回冲突，不从当前PG刷新旧缓存的问题定义。

Go的临时图缓存仅保存冻结请求、实际Core版本/统计和小摘要，沿用有限容量、TTL与FIFO，不保存整图JSON。原默认841节点/16095边的完整wire实测565290981字节、102688路径、1915328事件；普通32MiB结果保护保持不变，不能为此抬到数百MiB或裁事件。相同正式图的Release根查询实测2480字节/2.268秒，完整根分组1685644字节/2.437秒；这是指定样本的实测，查询以额外构图CPU换取有界传输。

本批实际验证：Linux正式CMake **131/131**；迁移差分/委托 **93 passed / 165外部依赖skip**；Go/Swift共享 **39** 全字段一致；Swift整包25项中20通过、5项因未连接真实HTTP明确跳过。真实Go/PG/原Python图/摘要HTTP **24/24**，winning **3/3**（含10组完整查询）零SKIP。记录位于`projection-abi10-20261124/`、`fixed-http-20261124/http-final2-all/`及`p3-server-20261124/winning-first/`。新Apple全套及本版Swift真实服务联跑仍需继续，不把Linux通过扩称全部平台验收。
