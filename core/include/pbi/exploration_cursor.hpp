#pragma once

#include "pbi/state_graph_projection.hpp"

namespace pbi {
/// 原探索游标的一条实际选择边；完整图和即时快照共享身份关系，不共享节点生成公式。
/// source/edge/target保持不同强类型和任意精度，不依赖代表前驱或机器整数范围。
struct ExplorationPathStep {
  ProjectionNodeId source_node_id;
  ProjectionEdgeId edge_id;
  ProjectionNodeId target_node_id;
};
} // namespace pbi
