import { describe, expect, it } from 'vitest';
import {
  calculateConfigurationBudget,
  countMoveSets,
  normalizeCandidateMoveIds,
} from './configurationBudget';

describe('configurationBudget', () => {
  it.each([
    [1, 1],
    [3, 1],
    [4, 1],
    [10, 210],
  ])('counts %i candidates as %i unordered move sets', (candidateCount: number, expected: number) => {
    /** 直接锁定 Issue #88 的 1、3、4、10 个候选边界，避免页面重复实现组合公式。 */
    expect(countMoveSets(candidateCount)).toBe(expected);
  });

  it('calculates symmetric and asymmetric configuration-pair budgets', () => {
    /** 10+10 是最大配置对数量；19+1 验证总候选相同但分配不对称时仍允许提交。 */
    expect(calculateConfigurationBudget(10, 10)).toEqual({
      attacker_candidate_count: 10,
      defender_candidate_count: 10,
      total_candidate_count: 20,
      attacker_move_set_count: 210,
      defender_move_set_count: 210,
      configuration_pair_count: 44_100,
      exceeds_candidate_limit: false,
      exceeds_configuration_pair_limit: false,
    });
    expect(calculateConfigurationBudget(19, 1)).toMatchObject({
      total_candidate_count: 20,
      attacker_move_set_count: 3_876,
      defender_move_set_count: 1,
      configuration_pair_count: 3_876,
      exceeds_candidate_limit: false,
    });
  });

  it('reports the total-candidate hard limit independently from pair count', () => {
    /** 20+1 的组合对数量未必超过 44,100，但仍必须因候选总数大于 20 被客户端阻止。 */
    expect(calculateConfigurationBudget(20, 1)).toMatchObject({
      total_candidate_count: 21,
      exceeds_candidate_limit: true,
    });
  });

  it('normalizes candidate identities without preserving click order', () => {
    /** 相同 move_id 集合的重复项和点击顺序不进入提交身份。 */
    expect(normalizeCandidateMoveIds([8, 280, 8, 7])).toEqual([7, 8, 280]);
    expect(() => normalizeCandidateMoveIds([0])).toThrow(RangeError);
  });
});
