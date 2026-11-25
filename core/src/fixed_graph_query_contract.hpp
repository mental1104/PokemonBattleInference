#pragma once

#include "turn_contract.hpp"
#include "pbi/exploration_cursor.hpp"

namespace pbi::contract {
/// 原图浏览地址是外部不透明句柄，不参与Core概率/状态身份。
struct FixedGraphAddress { std::string graph_id; std::string calculation_revision; };
/// 根或给定cursor的折叠节点查询。
struct FixedGraphExplore {};
/// 只展开一个原分组，身份由唯一纯projection产生。
struct FixedGraphOutcomes { std::string group_id; };
/// 选择原正式边；任意精度输入只在验证实际图范围后转机器索引。
struct FixedGraphAdvance { ProjectionEdgeId edge_id; };
/// 原祖先深度，不以机器整数范围缩小客户端合法冲突输入。
struct FixedGraphBacktrack { std::optional<Integer> depth; };
/// cursor必须绑定实际重建配置，故仅在私有codec边界延迟其JSON解码；纯winning不接收JSON。
struct FixedGraphWinningQuery { Json value; };
/// 一个冻结请求的可复现查询；所有大图事件只存在于本次独立child的typed图中。
struct FixedGraphQueryRequest {
  FixedBattleRequest fixed;
  std::string expected_engine_version;
  std::string expected_rules_version;
  std::size_t expected_nodes;
  std::size_t expected_edges;
  FixedGraphAddress address;
  std::vector<ExplorationPathStep> cursor;
  std::variant<FixedGraphExplore, FixedGraphOutcomes, FixedGraphAdvance, FixedGraphBacktrack, FixedGraphWinningQuery> query;
};
/// @param value 完整冻结fixed请求和小查询；@param remaining_rolls 本批策略槽位余量。
/// @param available_nodes 本批生成图预算；@param available_edges 本批生成边预算。
/// @param stop 同源取消；@return 完整拥有请求，静态知识不重新读取PG或文件。
[[nodiscard]] FixedGraphQueryRequest ReadFixedGraphQueryRequest(const Json& value, std::size_t remaining_rolls,
    std::size_t available_nodes, std::size_t available_edges, CancellationToken stop);
/// @param request 同版本/计数绑定的冻结事实；@param current_engine owning envelope引擎版本。
/// @param current_rules owning envelope规则版本；@param stop 同源取消贯穿构图/求解/投影/查询。
/// @return 一个小DTO或原HTTP业务拒绝；不构造/编码完整图JSON、不复制整幅图的事件。
[[nodiscard]] Json EvaluateFixedGraphQuery(const FixedGraphQueryRequest& request, std::string_view current_engine, std::string_view current_rules, CancellationToken stop);
} // namespace pbi::contract
