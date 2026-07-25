import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CONFIGURATION_JOB_CREATED_EVENT,
  HttpBattleConfigurationSpaceAdapter,
} from './configurationSpaceHttp';
import type { CreateBattleConfigurationJobRequest } from '../types/battleConfigurationSpace';

const command: CreateBattleConfigurationJobRequest = {
  contract_version: 'one-on-one-move-pool.v1',
  ruleset_id: 'pokemon-champion',
  version_group_id: 25,
  calculation_revision: 'battle-inference.summary-exploration.v2',
  dimensions: {
    pokemon: 'fixed',
    form: 'fixed',
    level: 'fixed',
    stats: 'fixed',
    ability: 'fixed',
    item: 'fixed',
    moves: 'candidate_pool',
    special_mechanics: 'disabled',
  },
  weight_assumption: 'uniform_configuration_pair',
  attacker_policy: 'uniform-random',
  defender_policy: 'uniform-random',
  mechanism_admission: 'supported_only',
  attacker: {
    fixed: {
      pokemon_id: 149,
      form_id: null,
      level: 50,
      stat_profile_id: 'max_atk_plus',
      ability_identifier: 'multiscale',
      item_identifier: null,
    },
    candidate_move_ids: [8, 89, 245, 280],
  },
  defender: {
    fixed: {
      pokemon_id: 461,
      form_id: null,
      level: 50,
      stat_profile_id: 'max_hp',
      ability_identifier: 'pressure',
      item_identifier: null,
    },
    candidate_move_ids: [8, 252, 400, 420],
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('HttpBattleConfigurationSpaceAdapter', () => {
  it('loads the real version-group-aware candidate pool', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        pokemon_id: 149,
        ruleset_id: 'pokemon-champion',
        version_group_id: 25,
        calculation_revision: 'battle-inference.summary-exploration.v2',
        moves: [],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await new HttpBattleConfigurationSpaceAdapter().listCandidateMoves({
      pokemon_id: 149,
      ruleset_id: 'pokemon-champion',
      version_group_id: 25,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/inference/candidate-pools/149?'),
      { method: 'GET' },
    );
    expect(fetchMock.mock.calls[0][0]).toContain('version_group_id=25');
  });

  it('creates a real job with an idempotency key and publishes its job id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'job-real-105',
        status: 'pending',
        submitted_configuration_pairs: 1,
        created_at: '2026-07-25T03:00:00Z',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const listener = vi.fn();
    window.addEventListener(CONFIGURATION_JOB_CREATED_EVENT, listener);

    const result = await new HttpBattleConfigurationSpaceAdapter().createJob(command);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toContain('/inference/configuration-jobs');
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toMatch(
      /^configuration-space-/,
    );
    expect(result.job_id).toBe('job-real-105');
    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent<{ jobId: string }>;
    expect(event.detail.jobId).toBe('job-real-105');

    window.removeEventListener(CONFIGURATION_JOB_CREATED_EVENT, listener);
  });

  it('renders strict admission failures as a readable API error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: {
            code: 'strict_mechanism_admission_rejected',
            message: 'selection rejected',
            failures: [
              {
                requested_identifier: 'thunderbolt',
                reason: 'paralysis secondary effect is unsupported',
              },
            ],
          },
        }),
      }),
    );

    await expect(
      new HttpBattleConfigurationSpaceAdapter().createJob(command),
    ).rejects.toMatchObject({
      code: 'strict_mechanism_admission_rejected',
      message: expect.stringContaining('thunderbolt'),
    });
  });
});
