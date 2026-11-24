#pragma once
// 正式配置协议只负责边界转换，所有过滤、归并和精确权重由纯 Core 拥有。
#include "json_contract.hpp"
#include "pbi/configuration_space.hpp"
#include "pbi/configuration_admission.hpp"
#include "pbi/job_move_pool.hpp"

namespace pbi::contract {
/// 单一能力维度的拥有请求，保留完整五轴性格和归并前预算。
struct ConfigurationStatsRequest { ConfigurationStatInput input; };
/// 完整合法候选与命令过滤，不在 ABI 预先生成组合。
struct ConfigurationMovesRequest { ConfigurationMoveInput input; };
/// 双方标准四维命令及明确覆盖假设；不代表旧 job-v1 的 canonical case 身份。
struct ConfigurationSpaceRequest {
  ConfigurationPokemonInput attacker;
  ConfigurationPokemonInput defender;
  ConfigurationWeightAssumption assumption;
  std::size_t max_raw_pairs;
};
/// 一个显式机制描述查询，不隐式从展示名猜测效果。
struct ConfigurationEffectQuery { ConfigurationEffectSource source; std::optional<std::string> identifier; ConfigurationEffectFactory factory; };
/// 纯描述列表，不执行准入或候选过滤。
struct ConfigurationDescriptionQueries {
  std::vector<ConfigurationEffectQuery> effects;
  bool include_capabilities = false;
};
/// 完整strict准入事实，不接受外层预裁定的supported状态。
struct ConfigurationAdmissionQueries { std::vector<ConfigurationAdmissionInput> candidates; };
/// 无枚举副作用的完整覆盖查询，空维度也可独立完成严格准入。
struct ConfigurationCoverageRequest { std::variant<ConfigurationDescriptionQueries, ConfigurationAdmissionQueries> queries; };
/// 绑定原命令侧和具体招式ID的完整准入事实，招式快照用于限制no_effect路径。
struct JobAdmissionFact {
  BattleSide side;
  std::optional<std::int64_t> move_id;
  std::optional<MoveSpec> move;
  ConfigurationAdmissionInput admission;
};
/// 具体job-v1规划与完整关联准入，不持有原始case笛卡尔缓存。
struct JobMovePoolRequest {
  JobMovePool pool;
  std::vector<JobAdmissionFact> admission;
  std::size_t offset;
  std::size_t limit;
};
/// @param value 完整正式能力命令；@param stop 批次取消；@return 拥有且严格读取的请求。
[[nodiscard]] ConfigurationStatsRequest ReadConfigurationStatsRequest(const Json& value, CancellationToken stop);
/// @param value 完整正式招式命令；@param stop 批次取消；@return 不预先过滤的合法候选请求。
[[nodiscard]] ConfigurationMovesRequest ReadConfigurationMovesRequest(const Json& value, CancellationToken stop);
/// @param value 完整双方命令；@param stop 批次取消；@return 保留原始预算和覆盖假设的请求。
[[nodiscard]] ConfigurationSpaceRequest ReadConfigurationSpaceRequest(const Json& value, CancellationToken stop);
/// @param value 显式三类机制列表；@param stop 批次取消；@return 只读描述查询。
[[nodiscard]] ConfigurationCoverageRequest ReadConfigurationCoverageRequest(const Json& value, CancellationToken stop);
/// @param value 完整原job-v1命令/分页/关联准入；@param stop 批次取消。
/// @return 已严格核对事实归属且拥有规范ID池的请求，不裁剪候选。
[[nodiscard]] JobMovePoolRequest ReadJobMovePoolRequest(const Json& value, CancellationToken stop);
/// @param request 完整能力命令；@param stop 同源取消；@return 全部等价类、代表和精确成员数。
[[nodiscard]] Json EvaluateConfigurationStats(const ConfigurationStatsRequest& request, CancellationToken stop);
/// @param request 完整候选命令；@param stop 同源取消；@return 全部组合、原始成员和完整覆盖。
[[nodiscard]] Json EvaluateConfigurationMoves(const ConfigurationMovesRequest& request, CancellationToken stop);
/// @param request 完整双方命令；@param stop 同源取消；@return 双方类和精确配置对权重，不返回部分空间。
[[nodiscard]] Json EvaluateConfigurationSpace(const ConfigurationSpaceRequest& request, CancellationToken stop);
/// @param request 显式机制查询；@param stop 同源取消；@return 当前纯 Core 描述的全部缺失能力。
[[nodiscard]] Json EvaluateConfigurationCoverage(const ConfigurationCoverageRequest& request, CancellationToken stop);
/// @param request 完整具体池规划；@param stop 同源取消。
/// @return 整池准入通过后的有界页面和完整原全局分母；失败无部分case。
[[nodiscard]] Json EvaluateJobMovePool(const JobMovePoolRequest& request, CancellationToken stop);
} // namespace pbi::contract
