import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  enumerateMoveSetCombinations,
  inferFixedBattleSummary,
} from './fixedBattle';
import type {
  FixedBattleSummaryRequest,
  MoveSetCombinationsRequest,
} from '../types/fixedBattle';

const fixedSide = {
  pokemon_id: 149,
  form_id: null,
  level: 50,
  stat_profile_id: 'max_atk_plus',
  ability_identifier: 'multiscale',
  item_identifier: null,
};

const combinationRequest: MoveSetCombinationsRequest = {
  ruleset_id: 'pokemon-champion',
  version_group_id: 25,
  calculation_revision: 'battle-inference.summary-exploration.v2',
  attacker: { ...fixedSide, candidate_move_ids: [1, 2, 3, 4, 5] },
  defender: { ...fixedSide, candidate_move_ids: [11, 12, 13, 14] },
};

const summaryRequest: FixedBattleSummaryRequest = {
  ruleset_id: 'pokemon-champion',
  version_group_id: 25,
  attacker: { ...fixedSide, move_ids: [1, 2, 3, 4] },
  defender: { ...fixedSide, move_ids: [11, 12, 13, 14] },
  attacker_policy: 'uniform-random',
  defender_policy: 'uniform-random',
  limits: { max_nodes: 50_000, max_edges: 300_000, max_turns: 20 },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('fixed battle HTTP workflow', () => {
  it('enumerates move sets without creating a configuration job', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ruleset_id: 'pokemon-champion',
        version_group_id: 25,
        calculation_revision: 'battle-inference.summary-exploration.v2',
        attacker: {
          pokemon_id: 149,
          pokemon_name: 'dragonite',
          candidate_count: 5,
          move_set_count: 5,
          move_sets: [],
        },
        defender: {
          pokemon_id: 149,
          pokemon_name: 'dragonite',
          candidate_count: 4,
          move_set_count: 1,
          move_sets: [],
        },
        configuration_pair_count: 5,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await enumerateMoveSetCombinations(combinationRequest);

    expect(fetchMock.mock.calls[0][0]).toContain(
      '/inference/move-set-combinations',
    );
    expect(fetchMock.mock.calls[0][0]).not.toContain('configuration-jobs');
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string))
      .toEqual(combinationRequest);
    expect(result.configuration_pair_count).toBe(5);
  });

  it('submits only one chosen fixed snapshot to the exact summary endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ win_probability: { percent: 62.5 } }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await inferFixedBattleSummary(summaryRequest);

    expect(fetchMock.mock.calls[0][0]).toContain('/inference/fixed-one-on-one');
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    ) as FixedBattleSummaryRequest;
    expect(body.attacker.move_ids).toEqual([1, 2, 3, 4]);
    expect(body.defender.move_ids).toEqual([11, 12, 13, 14]);
    expect(body.attacker_policy).toBe('uniform-random');
  });

  it('renders structured mechanism rejection details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: {
            code: 'fixed_battle_mechanism_rejected',
            message: 'selection rejected',
            failures: [
              {
                requested_identifier: '5',
                reason: 'secondary effect is unsupported',
              },
            ],
          },
        }),
      }),
    );

    await expect(inferFixedBattleSummary(summaryRequest)).rejects.toMatchObject({
      code: 'fixed_battle_mechanism_rejected',
      message: expect.stringContaining('5: secondary effect is unsupported'),
    });
  });
});
