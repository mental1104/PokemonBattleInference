import { describe, expect, it } from 'vitest';
import { oneOnOneConfigurationContractFixture as fixture } from '../fixtures/oneOnOneConfigurationContract';
import {
  CONFIGURATION_DIMENSION_MODES,
  CONFIGURATION_EXECUTION_STATUSES,
  CONFIGURATION_TASK_STATUSES,
  CONFIGURATION_WEIGHT_ASSUMPTIONS,
  MECHANISM_ADMISSION_POLICIES,
  ONE_ON_ONE_ACTION_POLICIES,
  buildConfigurationId,
  countConfigurationPairs,
  countMoveSets,
  normalizeMoveIds,
} from './oneOnOneConfigurationSpace';

describe('one-on-one configuration-space contract', () => {
  it('keeps enum values aligned with the shared Python fixture', () => {
    expect(fixture.enum_values.dimension_mode).toEqual(CONFIGURATION_DIMENSION_MODES);
    expect(fixture.enum_values.configuration_weight_assumption).toEqual(
      CONFIGURATION_WEIGHT_ASSUMPTIONS,
    );
    expect(fixture.enum_values.action_policy).toEqual(ONE_ON_ONE_ACTION_POLICIES);
    expect(fixture.enum_values.mechanism_admission_policy).toEqual(
      MECHANISM_ADMISSION_POLICIES,
    );
    expect(fixture.enum_values.configuration_execution_status).toEqual(
      CONFIGURATION_EXECUTION_STATUSES,
    );
    expect(fixture.enum_values.configuration_task_status).toEqual(
      CONFIGURATION_TASK_STATUSES,
    );
  });

  it('uses the same 1, 3, 4 and 10 candidate combination counts', () => {
    for (const testCase of fixture.move_set_cases) {
      expect(countMoveSets(testCase.candidate_count)).toBe(
        testCase.expected_move_set_count,
      );
    }
  });

  it('freezes the 10 plus 10 worst-case count at 44,100 pairs', () => {
    const testCase = fixture.max_budget_case;
    expect(
      countConfigurationPairs(
        testCase.attacker_candidate_count,
        testCase.defender_candidate_count,
      ),
    ).toBe(testCase.expected_configuration_pair_count);
  });

  it('builds an order-invariant configuration id identical to Python', () => {
    const command = fixture.command;
    const configurationId = buildConfigurationId({
      contract_version: command.contract_version,
      ruleset_id: command.ruleset_id,
      version_group_id: command.version_group_id,
      calculation_revision: command.calculation_revision,
      attacker: command.attacker.fixed,
      attacker_move_ids: command.attacker.candidate_move_ids,
      defender: command.defender.fixed,
      defender_move_ids: command.defender.candidate_move_ids,
    });

    expect(normalizeMoveIds(command.attacker.candidate_move_ids)).toEqual(
      fixture.expected.normalized_attacker_move_ids,
    );
    expect(normalizeMoveIds(command.defender.candidate_move_ids)).toEqual(
      fixture.expected.normalized_defender_move_ids,
    );
    expect(configurationId).toBe(fixture.expected.configuration_id);
  });

  it('keeps batch summaries lightweight and failure weight explicit', () => {
    const summary = fixture.batch_summary;
    expect('graph_artifact' in summary).toBe(false);
    expect(summary.probabilities.unresolved_configuration_weight).toEqual({
      numerator: 1,
      denominator: 2,
    });
    expect(summary.coverage.failed_count + summary.coverage.truncated_count).toBe(2);
    expect(fixture.issue_page.items.map((item) => item.status)).toEqual([
      'failed',
      'truncated',
    ]);
    expect(summary.attacker_policy).toBe('uniform-random');
  });
});
