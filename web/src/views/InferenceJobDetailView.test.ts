import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createJobCaseGraph,
  getInferenceJob,
  listSucceededJobCases,
} from '../api/fixedBattle';
import InferenceJobDetailView from './InferenceJobDetailView.vue';

vi.mock('../api/fixedBattle', () => ({
  cancelInferenceJob: vi.fn(),
  createJobCaseGraph: vi.fn(),
  getInferenceJob: vi.fn(),
  listSucceededJobCases: vi.fn(),
}));

const getJobMock = vi.mocked(getInferenceJob);
const listCasesMock = vi.mocked(listSucceededJobCases);
const createGraphMock = vi.mocked(createJobCaseGraph);

beforeEach(() => {
  getJobMock.mockReset().mockResolvedValue({
    job_id: 'fixed-one-on-one-job-1',
    job_type: 'fixed-one-on-one',
    status: 'succeeded',
    phase: 'completed',
    ruleset_id: 'pokemon-champion',
    version_group_id: 25,
    calculation_revision: 'battle-inference.summary-exploration.v2',
    created_at: '2026-07-30T00:00:00Z',
    started_at: '2026-07-30T00:00:01Z',
    updated_at: '2026-07-30T00:00:03Z',
    finished_at: '2026-07-30T00:00:03Z',
    cancel_requested_at: null,
    can_cancel: false,
    progress: {
      phase: 'completed',
      counts: {
        total: 1,
        pending: 0,
        running: 0,
        succeeded: 1,
        failed: 0,
        truncated: 0,
        cancelled: 0,
        completed: 1,
      },
      state_nodes: { used: 221, limit: 50_000 },
      state_edges: { used: 576, limit: 300_000 },
      running_case: null,
      elapsed_seconds: 2.6,
    },
    error_code: null,
    error_message: null,
    links: {
      self: '/v1/inference/jobs/fixed-one-on-one-job-1',
      cancel: '/v1/inference/jobs/fixed-one-on-one-job-1/cancel',
    },
  });
  listCasesMock.mockReset().mockResolvedValue({
    job_id: 'fixed-one-on-one-job-1',
    offset: 0,
    limit: 1,
    total: 1,
    next_cursor: null,
    items: [
      {
        configuration_id: 'one-on-one-configuration:test',
        sequence_no: 0,
        status: 'succeeded',
        attacker_pokemon_id: 149,
        defender_pokemon_id: 149,
        attacker_move_ids: [337],
        defender_move_ids: [337],
        attacker_win_probability: { numerator: '1', denominator: '2', decimal: 0.5 },
        defender_win_probability: { numerator: '1', denominator: '2', decimal: 0.5 },
        draw_probability: { numerator: '0', denominator: '1', decimal: 0 },
        expected_turns_kind: 'finite',
        expected_turns: '2/1',
        node_count: 221,
        edge_count: 576,
        explanation: null,
        failure_code: null,
        diagnostic: null,
      },
    ],
  });
  createGraphMock.mockReset().mockResolvedValue({
    summary: {
      ruleset_id: 'pokemon-champion',
      version_group_id: 25,
      observer: 'attacker',
      attacker: {
        pokemon_id: 149,
        name: 'dragonite',
        level: 50,
        ability_identifier: 'multiscale',
        item_identifier: 'none',
        move_ids: [337],
        move_names: ['龙爪'],
        stats: { hp: 166 },
        dimension_labels: {},
      },
      defender: {
        pokemon_id: 149,
        name: 'dragonite',
        level: 50,
        ability_identifier: 'multiscale',
        item_identifier: 'none',
        move_ids: [337],
        move_names: ['龙爪'],
        stats: { hp: 198 },
        dimension_labels: {},
      },
      win_probability: { numerator: '1', denominator: '2', decimal: 0.5, percent: 50 },
      loss_probability: { numerator: '1', denominator: '2', decimal: 0.5, percent: 50 },
      draw_probability: { numerator: '0', denominator: '1', decimal: 0, percent: 0 },
      expected_turns: { available: true, numerator: 2, denominator: 1, decimal: 2 },
      attacker_policy: 'uniform-random',
      defender_policy: 'uniform-random',
      graph: {
        unique_state_count: 221,
        edge_count: 576,
        max_turn_number: 2,
        closed_cycle_count: 0,
        terminal_reachable_cycle_count: 0,
        is_complete: true,
        truncation_reasons: [],
      },
      representative_paths: [],
      included_mechanisms: [],
      excluded_mechanisms: [],
      configuration_coverage_percent: 100,
      completeness: {
        graph_complete: true,
        solver_status: 'solved',
        truncation_reasons: [],
        diagnostics: [],
        warnings: [],
      },
    },
    exploration: {
      graph_id: 'graph-job-1',
      root_node_id: 0,
      calculation_revision: 'battle-inference.summary-exploration.v2',
      expires_at: '2026-07-30T00:10:00Z',
      cursor: { steps: [] },
      expandable: true,
    },
  });
});

describe('InferenceJobDetailView', () => {
  it('opens the completed fixed job graph in the tree report screen', async () => {
    /** 已完成固定任务应能从详情页进入原有树状图和战报大屏，而不是停在控制面摘要。 */
    const wrapper = mount(InferenceJobDetailView, {
      props: { jobId: 'fixed-one-on-one-job-1' },
      global: {
        stubs: {
          BattleGraphTreeScreen: {
            template: '<section data-test="tree-screen">树状图和战报</section>',
          },
        },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain('所有可能性的概率总和');
    expect(wrapper.text()).toContain('50.00%');

    await wrapper.get('button.primary-button').trigger('click');
    await flushPromises();

    expect(listCasesMock).toHaveBeenCalledWith('fixed-one-on-one-job-1');
    expect(createGraphMock).toHaveBeenCalledWith(
      'fixed-one-on-one-job-1',
      'one-on-one-configuration:test',
    );
    expect(wrapper.find('[data-test="tree-screen"]').exists()).toBe(true);
  });
});
