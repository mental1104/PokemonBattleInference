import {
  countConfigurationPairs as countCanonicalConfigurationPairs,
  countMoveSets as countCanonicalMoveSets,
  MAX_TOTAL_CANDIDATE_MOVES,
  normalizeMoveIds,
} from '../types/oneOnOneConfigurationSpace';

export { MAX_TOTAL_CANDIDATE_MOVES };
export const MAX_CONFIGURATION_PAIRS = countCanonicalConfigurationPairs(10, 10);

/** 页面即时反馈使用的候选池组合预算。 */
export interface ConfigurationBudgetSummary {
  attacker_candidate_count: number;
  defender_candidate_count: number;
  total_candidate_count: number;
  attacker_move_set_count: number;
  defender_move_set_count: number;
  configuration_pair_count: number;
  exceeds_candidate_limit: boolean;
  exceeds_configuration_pair_limit: boolean;
}

/**
 * 计算一个候选池最终生成的无序技能组数量。
 *
 * 空页面状态返回 0；正整数候选数量直接复用 #82 的 canonical 组合函数。
 *
 * @param candidateCount 已通过机制准入并被用户选择的唯一招式数量，必须为非负整数。
 * @returns 0 个候选返回 0；1～3 个候选返回唯一全量技能组；4 个及以上返回 C(n, 4)。
 */
export function countMoveSets(candidateCount: number): number {
  if (!Number.isInteger(candidateCount) || candidateCount < 0) {
    throw new RangeError('candidateCount must be a non-negative integer');
  }
  return candidateCount === 0 ? 0 : countCanonicalMoveSets(candidateCount);
}

/**
 * 计算双方候选池占用的技能组和配置对预算。
 *
 * 页面允许任一侧暂时为空，因此在完整输入形成前不调用 canonical 双侧计数函数。
 *
 * @param attackerCandidateCount 攻击方已选且可执行的唯一招式数量。
 * @param defenderCandidateCount 防守方已选且可执行的唯一招式数量。
 * @returns 包含每侧技能组数、笛卡尔积配置对数量和两类硬上限状态的新对象。
 */
export function calculateConfigurationBudget(
  attackerCandidateCount: number,
  defenderCandidateCount: number,
): ConfigurationBudgetSummary {
  const attackerMoveSetCount = countMoveSets(attackerCandidateCount);
  const defenderMoveSetCount = countMoveSets(defenderCandidateCount);
  const totalCandidateCount = attackerCandidateCount + defenderCandidateCount;
  const configurationPairCount = attackerMoveSetCount * defenderMoveSetCount;

  return {
    attacker_candidate_count: attackerCandidateCount,
    defender_candidate_count: defenderCandidateCount,
    total_candidate_count: totalCandidateCount,
    attacker_move_set_count: attackerMoveSetCount,
    defender_move_set_count: defenderMoveSetCount,
    configuration_pair_count: configurationPairCount,
    exceeds_candidate_limit: totalCandidateCount > MAX_TOTAL_CANDIDATE_MOVES,
    exceeds_configuration_pair_limit:
      configurationPairCount > MAX_CONFIGURATION_PAIRS,
  };
}

/**
 * 将候选招式 ID 规范化为升序唯一数组。
 *
 * 空页面状态允许返回空数组；非空集合在去重后交给 #82 canonical normalizer 排序和校验。
 *
 * @param moveIds 用户选择产生的招式 ID；顺序不参与配置身份。
 * @returns 不修改输入数组的升序唯一快照。
 * @throws RangeError 任一 ID 不是正整数时抛出。
 */
export function normalizeCandidateMoveIds(
  moveIds: readonly number[],
): number[] {
  for (const moveId of moveIds) {
    if (!Number.isInteger(moveId) || moveId <= 0) {
      throw new RangeError('moveIds must contain positive integers');
    }
  }
  const uniqueMoveIds = [...new Set(moveIds)];
  return uniqueMoveIds.length === 0 ? [] : normalizeMoveIds(uniqueMoveIds);
}
