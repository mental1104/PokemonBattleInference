# Local-first Testability Standards

This file defines what it means for PokemonBattleInference to satisfy Local-first Testability. It defines standards only; it does not prescribe concrete repairs.

## TST-ENTRY-001: Unified Test Entry

The repository must expose one canonical backend test entry from the repository root.

Satisfying conditions:

- The canonical backend entry is discoverable from project configuration or documentation.
- macOS and Linux use the same backend test entry.
- The entry delegates to the project-native test framework without forcing a framework rewrite.
- CI may add flags for log compactness or fail-fast behavior only when those flags do not change which tests are eligible to run.
- Technology-specific frontend tests may keep their native package entry, but they must not replace the backend canonical entry.

## TST-XPLAT-001: One Cross-platform Test Collection

The same tests should be collectable on macOS and Linux.

Satisfying conditions:

- The project does not maintain separate macOS and Linux test entrypoints.
- Platform or capability restrictions are expressed through test framework skip/fail behavior.
- A missing capability produces a precise `SKIP` when the environment is legitimately unavailable.
- A malformed environment produces `FAIL`, not `SKIP`.
- Platform checks live in fixtures, markers, or environment resolvers, not inside core assertions.

## TST-UNIT-001: Local-first Unit Tests

Unit tests for core and portable logic must run locally without integration infrastructure.

Satisfying conditions:

- `pokeop/domain` tests do not require Docker, PostgreSQL, message queues, Linux-only APIs, network services, or mutable host state.
- Portable `pokeop/application` tests avoid infrastructure unless they are explicitly composition/integration tests.
- Core domain behavior is directly verifiable on macOS through the canonical test framework.
- Platform-specific behavior is isolated behind `pokeop/infrastructure`, `pokeop/persistence`, API composition, or explicit test fixtures.

## TST-COV-001: Core-focused Coverage Policy

Coverage policy is project-owned and should focus first on portable/core behavior.

Satisfying conditions:

- Coverage thresholds, if enforced, live in project configuration such as `pytest.ini`, `pyproject.toml`, or a Makefile target.
- This standard does not define a universal numeric threshold.
- Coverage expectations prioritize `pokeop/domain` and portable `pokeop/application` behavior over platform glue.
- Lack of a coverage threshold is not automatically a failure unless the project has chosen to require one.

## TST-INT-001: Integration Environment Contract

Each integration suite defines the environment variables required to access its integration environment.

Satisfying conditions:

- The suite declares its complete Environment Contract.
- The project does not impose a universal variable naming scheme across all integrations.
- If every required variable is present, tests use that environment directly.
- If only some required variables are present, tests fail as configuration error.
- If no required variables are present on macOS, integration tests skip with an actionable reason.
- If no required variables are present on Linux and the project supports Docker provisioning for that dependency, the resolver may provision the environment, wait until it is ready, and inject the complete Environment Contract.
- After a ready Environment Contract exists, integration test bodies do not branch on macOS/Linux and do not care whether the environment came from remote Linux, CI preconfiguration, or local Docker.

## TST-LIFE-001: Integration Lifecycle Separation

Integration environment lifecycle must be separated from business assertions.

Satisfying lifecycle:

```text
resolve -> provision if needed -> wait_ready -> run tests -> cleanup if owned
```

Satisfying conditions:

- Test assertions receive a ready environment or do not run.
- Provisioning and readiness checks live in fixtures, helpers, or graph-owned environment setup, not in individual business assertions.
- Cleanup affects only resources provisioned by the test framework itself.
- User-provided, CI-provided, or remote integration environments are never torn down by test cleanup.

## GRAPH-LOOP-001: Closed Validation Loop

The Testability Graph must use one closed loop.

Satisfying conditions:

- The graph topology is `Validate -> Plan -> Implement -> Validate`.
- The first validation and post-implementation validation use the same standards.
- `Plan` only responds to actual validation failures.
- `Implement` only executes approved plan items.
- Repair execution is an edge decision, not a standalone node.
- Validation-only requests stop after validation.
