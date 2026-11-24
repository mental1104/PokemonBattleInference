-- 兼容旧运行表的增量初始化；只创建缺失对象，不删除或重建已有数据。
CREATE SCHEMA IF NOT EXISTS poke_runtime;
CREATE TABLE IF NOT EXISTS poke_runtime.battle_inference_jobs (
	job_id TEXT NOT NULL,
	ruleset_id TEXT NOT NULL,
	version_group_id INTEGER NOT NULL,
	calculation_revision TEXT NOT NULL,
	status VARCHAR(40) NOT NULL,
	attempt_count INTEGER NOT NULL,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	cancel_requested_at TIMESTAMP WITH TIME ZONE,
	last_failure_code VARCHAR(64),
	last_failure_diagnostic TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (job_id),
	CONSTRAINT battle_inference_jobs_status_ck CHECK (status IN ('pending', 'preparing', 'running', 'succeeded', 'completed_with_failures', 'cancel_requested', 'cancelled', 'failed')),
	CONSTRAINT battle_inference_jobs_attempt_count_ck CHECK (attempt_count >= 0),
	CONSTRAINT battle_inference_jobs_lease_ck CHECK ((lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL) OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS battle_inference_jobs_claim_idx ON poke_runtime.battle_inference_jobs (status, lease_expires_at, created_at);

CREATE TABLE IF NOT EXISTS poke_runtime.stat_configuration_preferences (
	id SERIAL NOT NULL,
	tenant_id TEXT NOT NULL,
	role VARCHAR(16) NOT NULL,
	reference_type VARCHAR(16) NOT NULL,
	reference_key TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	hidden BOOLEAN NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT stat_configuration_preferences_ref_uq UNIQUE (tenant_id, role, reference_type, reference_key),
	CONSTRAINT stat_configuration_preferences_role_ck CHECK (role IN ('attacker', 'defender')),
	CONSTRAINT stat_configuration_preferences_ref_type_ck CHECK (reference_type IN ('builtin', 'custom')),
	CONSTRAINT stat_configuration_preferences_sort_ck CHECK (sort_order >= 0)
);

CREATE INDEX IF NOT EXISTS stat_configuration_preferences_tenant_role_idx ON poke_runtime.stat_configuration_preferences (tenant_id, role, sort_order);

CREATE TABLE IF NOT EXISTS poke_runtime.stat_configurations (
	id TEXT NOT NULL,
	tenant_id TEXT NOT NULL,
	name VARCHAR(48) NOT NULL,
	nature_id VARCHAR(32) NOT NULL,
	role VARCHAR(16) NOT NULL,
	binding_kind VARCHAR(16) NOT NULL,
	pokemon_id INTEGER,
	ev_hp INTEGER NOT NULL,
	ev_attack INTEGER NOT NULL,
	ev_defense INTEGER NOT NULL,
	ev_special_attack INTEGER NOT NULL,
	ev_special_defense INTEGER NOT NULL,
	ev_speed INTEGER NOT NULL,
	iv_hp INTEGER NOT NULL,
	iv_attack INTEGER NOT NULL,
	iv_defense INTEGER NOT NULL,
	iv_special_attack INTEGER NOT NULL,
	iv_special_defense INTEGER NOT NULL,
	iv_speed INTEGER NOT NULL,
	is_deleted BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT stat_configurations_name_len_ck CHECK (char_length(name) BETWEEN 1 AND 48),
	CONSTRAINT stat_configurations_role_ck CHECK (role IN ('attacker', 'defender', 'both')),
	CONSTRAINT stat_configurations_binding_kind_ck CHECK (binding_kind IN ('global', 'pokemon')),
	CONSTRAINT stat_configurations_binding_ck CHECK ((binding_kind = 'global' AND pokemon_id IS NULL) OR (binding_kind = 'pokemon' AND pokemon_id IS NOT NULL AND pokemon_id > 0)),
	CONSTRAINT stat_configurations_ev_each_ck CHECK (ev_hp BETWEEN 0 AND 252 AND ev_attack BETWEEN 0 AND 252 AND ev_defense BETWEEN 0 AND 252 AND ev_special_attack BETWEEN 0 AND 252 AND ev_special_defense BETWEEN 0 AND 252 AND ev_speed BETWEEN 0 AND 252),
	CONSTRAINT stat_configurations_ev_total_ck CHECK (ev_hp + ev_attack + ev_defense + ev_special_attack + ev_special_defense + ev_speed <= 510),
	CONSTRAINT stat_configurations_iv_each_ck CHECK (iv_hp BETWEEN 0 AND 31 AND iv_attack BETWEEN 0 AND 31 AND iv_defense BETWEEN 0 AND 31 AND iv_special_attack BETWEEN 0 AND 31 AND iv_special_defense BETWEEN 0 AND 31 AND iv_speed BETWEEN 0 AND 31)
);

CREATE INDEX IF NOT EXISTS stat_configurations_tenant_pokemon_idx ON poke_runtime.stat_configurations (tenant_id, binding_kind, pokemon_id);

CREATE INDEX IF NOT EXISTS stat_configurations_tenant_role_idx ON poke_runtime.stat_configurations (tenant_id, role, is_deleted);

CREATE TABLE IF NOT EXISTS poke_runtime.battle_inference_cases (
	id BIGSERIAL NOT NULL,
	job_id TEXT NOT NULL,
	sequence_no INTEGER NOT NULL,
	configuration_pair_id TEXT NOT NULL,
	attacker_configuration_id TEXT NOT NULL,
	defender_configuration_id TEXT NOT NULL,
	attacker_move_ids INTEGER[] NOT NULL,
	defender_move_ids INTEGER[] NOT NULL,
	status VARCHAR(40) NOT NULL,
	attempt_count INTEGER NOT NULL,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	attacker_win_numerator TEXT,
	attacker_win_denominator TEXT,
	defender_win_numerator TEXT,
	defender_win_denominator TEXT,
	draw_numerator TEXT,
	draw_denominator TEXT,
	expected_turns_kind VARCHAR(32),
	expected_turns_numerator TEXT,
	expected_turns_denominator TEXT,
	node_count BIGINT NOT NULL,
	edge_count BIGINT NOT NULL,
	progress_phase VARCHAR(64),
	observed_node_count BIGINT NOT NULL,
	observed_edge_count BIGINT NOT NULL,
	expanded_node_count BIGINT NOT NULL,
	frontier_count BIGINT NOT NULL,
	action_pair_completed_count BIGINT NOT NULL,
	action_pair_total_count BIGINT NOT NULL,
	budget_consumed BIGINT NOT NULL,
	explanation_json TEXT,
	failure_code VARCHAR(64),
	diagnostic TEXT,
	last_failure_code VARCHAR(64),
	last_failure_diagnostic TEXT,
	result_fingerprint VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT battle_inference_cases_job_pair_uq UNIQUE (job_id, configuration_pair_id),
	CONSTRAINT battle_inference_cases_job_sequence_uq UNIQUE (job_id, sequence_no),
	CONSTRAINT battle_inference_cases_sequence_ck CHECK (sequence_no >= 0),
	CONSTRAINT battle_inference_cases_status_ck CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'truncated', 'cancelled')),
	CONSTRAINT battle_inference_cases_nonnegative_ck CHECK (attempt_count >= 0 AND node_count >= 0 AND edge_count >= 0 AND observed_node_count >= 0 AND observed_edge_count >= 0 AND expanded_node_count >= 0 AND frontier_count >= 0 AND action_pair_completed_count >= 0 AND action_pair_total_count >= 0 AND action_pair_completed_count <= action_pair_total_count AND budget_consumed >= 0),
	CONSTRAINT battle_inference_cases_lease_ck CHECK ((lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL) OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL)),
	CONSTRAINT battle_inference_cases_expected_turns_kind_ck CHECK (expected_turns_kind IS NULL OR expected_turns_kind IN ('finite', 'infinite', 'unavailable')),
	CONSTRAINT battle_inference_cases_result_shape_ck CHECK ((status IN ('pending', 'running') AND result_fingerprint IS NULL) OR (status = 'succeeded' AND attacker_win_numerator IS NOT NULL AND attacker_win_denominator IS NOT NULL AND defender_win_numerator IS NOT NULL AND defender_win_denominator IS NOT NULL AND draw_numerator IS NOT NULL AND draw_denominator IS NOT NULL AND expected_turns_kind IS NOT NULL AND failure_code IS NULL AND diagnostic IS NULL AND result_fingerprint IS NOT NULL) OR (status IN ('failed', 'truncated', 'cancelled') AND attacker_win_numerator IS NULL AND attacker_win_denominator IS NULL AND defender_win_numerator IS NULL AND defender_win_denominator IS NULL AND draw_numerator IS NULL AND draw_denominator IS NULL AND expected_turns_kind IS NULL AND expected_turns_numerator IS NULL AND expected_turns_denominator IS NULL AND failure_code IS NOT NULL AND diagnostic IS NOT NULL AND result_fingerprint IS NOT NULL)),
	FOREIGN KEY(job_id) REFERENCES poke_runtime.battle_inference_jobs (job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS battle_inference_cases_attacker_config_idx ON poke_runtime.battle_inference_cases (job_id, attacker_configuration_id, sequence_no);

CREATE INDEX IF NOT EXISTS battle_inference_cases_claim_idx ON poke_runtime.battle_inference_cases (job_id, status, lease_expires_at, sequence_no);

CREATE INDEX IF NOT EXISTS battle_inference_cases_defender_config_idx ON poke_runtime.battle_inference_cases (job_id, defender_configuration_id, sequence_no);

CREATE INDEX IF NOT EXISTS battle_inference_cases_failure_idx ON poke_runtime.battle_inference_cases (job_id, failure_code, sequence_no);

CREATE TABLE IF NOT EXISTS poke_runtime.battle_inference_job_execution_specs (
	job_id TEXT NOT NULL,
	contract_version TEXT NOT NULL,
	weight_assumption VARCHAR(64) NOT NULL,
	attacker_policy VARCHAR(64) NOT NULL,
	defender_policy VARCHAR(64) NOT NULL,
	mechanism_admission VARCHAR(64) NOT NULL,
	process_count INTEGER NOT NULL,
	queue_depth INTEGER NOT NULL,
	max_nodes_per_pair INTEGER NOT NULL,
	max_edges_per_pair INTEGER NOT NULL,
	max_turns INTEGER,
	PRIMARY KEY (job_id),
	CONSTRAINT battle_inference_job_execution_process_count_ck CHECK (process_count BETWEEN 1 AND 8),
	CONSTRAINT battle_inference_job_execution_queue_depth_ck CHECK (queue_depth BETWEEN process_count AND 32),
	CONSTRAINT battle_inference_job_execution_nodes_ck CHECK (max_nodes_per_pair BETWEEN 1 AND 2000000),
	CONSTRAINT battle_inference_job_execution_edges_ck CHECK (max_edges_per_pair BETWEEN 1 AND 8000000),
	CONSTRAINT battle_inference_job_execution_turns_ck CHECK (max_turns IS NULL OR max_turns BETWEEN 1 AND 10000),
	FOREIGN KEY(job_id) REFERENCES poke_runtime.battle_inference_jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS poke_runtime.battle_inference_job_progress (
	job_id TEXT NOT NULL,
	total_count INTEGER NOT NULL,
	pending_count INTEGER NOT NULL,
	running_count INTEGER NOT NULL,
	succeeded_count INTEGER NOT NULL,
	failed_count INTEGER NOT NULL,
	truncated_count INTEGER NOT NULL,
	cancelled_count INTEGER NOT NULL,
	cumulative_node_count BIGINT NOT NULL,
	cumulative_edge_count BIGINT NOT NULL,
	budget_consumed BIGINT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (job_id),
	CONSTRAINT battle_inference_job_progress_count_ck CHECK (total_count = pending_count + running_count + succeeded_count + failed_count + truncated_count + cancelled_count),
	CONSTRAINT battle_inference_job_progress_nonnegative_ck CHECK (total_count >= 0 AND pending_count >= 0 AND running_count >= 0 AND succeeded_count >= 0 AND failed_count >= 0 AND truncated_count >= 0 AND cancelled_count >= 0 AND cumulative_node_count >= 0 AND cumulative_edge_count >= 0 AND budget_consumed >= 0),
	FOREIGN KEY(job_id) REFERENCES poke_runtime.battle_inference_jobs (job_id) ON DELETE CASCADE
);
