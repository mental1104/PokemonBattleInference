# 精确事件与配置加权分析

本合同从引擎0.9.0/rules.v9接入既有C ABI v1。权威完整请求与原Python期望为`tests/vectors/event-analysis.v1.json`，其中三例同时加入Go/Swift共享33样本；不读取数据库、UI或平台服务。

`event_analysis`接收`calculation_revision`、`inference_run_id`、`observer`、`graph`、`query`。graph拥有原nodes/edges/root/truncations及十进制`root_turn_number`；每条边保留完整概率和`event_paths`，每个路径拥有原结构化事件及条件权重。事件元数据只转换成typed Core；不接受外部预计算概率或用展示文本推断机制。

query的结构化predicate字段按AND组合，保留原actor/target/any角色、事件类型/业务种类、move/effect/event/outcome标识、any/first次数模式、回合区间、任意精度次数上下限与独立分布展示上限。Core真正构建产品自动机并进行精确求解，输出原基线胜负平、事件概率、事件与胜利联合概率、正反条件胜率、首次与次数分布、完整路径组覆盖和关键事件身份。条件概率分母为零时显式`undefined-zero-condition`及null，不能用0伪装成已定义。

`configuration_event_analysis`接收groups，每组含`configuration_id`、精确`configuration_weight`和一份未执行的完整event_analysis请求；另有十进制`total_configuration_count`及可选精确`unresolved_configuration_weight`。先对各组真正分析，再以原完整分母聚合；未分析/失败权重不重新归一化，不能只将成功组算成100%。配置身份、observer/query一致性及精确权重和均校验。

原拓扑与其他graph操作共用全批节点/边配额，仍受C ABI的8MiB请求和32MiB结果字节预算；结果超限整批失败，不裁掉路径或重新归一化。产品图求解/聚合/编码协作检查同一取消令牌，取消不发布前序已完成操作或部分组结果。首轮公开预算与运行中取消由`CAbiEvents`真实验证。

反事实纯域入口`AnalyzeCounterfactualEvents`保留原两个独立runner、不同revision/run ID验证及三个精确差值，原生测试中的runner真实执行两次固定战斗。原实现只有规则覆盖端口，没有通用规则键映射；本ABI没有把测试夹具的两份预先图公开为“重新推演”操作，也不冒称对应HTTP已迁移。
