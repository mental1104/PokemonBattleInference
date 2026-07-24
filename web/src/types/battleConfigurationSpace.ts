import type {
  ConfigurationTaskStatus,
  OneOnOneMovePoolCommand,
} from './oneOnOneConfigurationSpace';

/** 候选机制在当前 calculation revision 下的覆盖状态。 */
export type MechanismSupportStatus =
  | 'supported'
  | 'partial'
  | 'no_effect'
  | 'unsupported';

/** 候选项随 version group 和 calculation revision 返回的结构化准入结论。 */
export interface CandidateMechanismAdmission {
  status: MechanismSupportStatus;
  selectable: boolean;
  reason: string;
  disabled_reason: string | null;
  missing_mechanism_identifiers: string[];
}

/**
 * 候选池中一条合法可学习招式及其机制准入结论。
 *
 * partial 与 unsupported 项仍会展示给用户，但不得进入精确推演输入；
 * supported 与 no_effect 均可选择。
 */
export interface CandidateMoveOption {
  move_id: number;
  identifier: string;
  display_name: string;
  type_identifier: string;
  type_name: string;
  damage_class: 'physical' | 'special' | 'status';
  power: number | null;
  admission: CandidateMechanismAdmission;
}

/** 读取一侧 version-group-aware 候选池所需的稳定参数。 */
export interface CandidateMovePoolRequest {
  pokemon_id: number;
  ruleset_id: string;
  version_group_id: number;
}

/** 一侧候选池及服务端准入上下文。 */
export interface CandidateMovePoolResponse {
  pokemon_id: number;
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  moves: CandidateMoveOption[];
}

/** 创建后台任务的请求直接复用 #82 已冻结的 canonical 前端合同。 */
export type CreateBattleConfigurationJobRequest = OneOnOneMovePoolCommand;

/** mock 或真实 adapter 创建任务后返回的最小确认信息。 */
export interface CreateBattleConfigurationJobResponse {
  job_id: string;
  status: Extract<ConfigurationTaskStatus, 'pending'>;
  submitted_configuration_pairs: number;
  created_at: string;
}

/** 页面提交后保留的不可变可读摘要，不承载结果页数据。 */
export interface FrozenBattleConfigurationSubmission {
  request: CreateBattleConfigurationJobRequest;
  attacker_name: string;
  defender_name: string;
  attacker_move_names: string[];
  defender_move_names: string[];
  total_candidate_count: number;
  configuration_pair_count: number;
  max_candidate_moves: number;
  max_configuration_pairs: number;
}

/** 候选池与后台任务 adapter 的共享 TypeScript mock 合同。 */
export interface BattleConfigurationSpaceAdapter {
  /** 读取一侧候选池；reject 时表示候选池暂不可用。 */
  listCandidateMoves(
    request: CandidateMovePoolRequest,
  ): Promise<CandidateMovePoolResponse>;

  /** 创建后台任务；服务端仍需重新执行准入与候选预算校验。 */
  createJob(
    request: CreateBattleConfigurationJobRequest,
  ): Promise<CreateBattleConfigurationJobResponse>;
}
