---
name: pokemonbattleinference-project
description: PokemonBattleInference 仓库统一项目级 Skill。Codex 在维护 pokeop 业务代码、domain/application/persistence/api 分层、PokeAPI CSV/raw import、PostgreSQL schema、materialized views、跨世代规则、伤害计算、测试、ChatGPT x Codex 四阶段协作、Development Snapshot、Cross-check 验收材料，或更新本仓库 Codex skill 时使用。
---

# PokemonBattleInference Project Skill

Use this skill for repository work under `/home/mental1104/code/PokemonBattleInference`, especially `pokeop`.

This is the single project-level skill for PokemonBattleInference. It merges the former `pokemonbattleinference-guidelines` and `vibe-coding-workflow` responsibilities. Do not split routine project rules and ChatGPT x Codex workflow into separate skills unless the Human explicitly asks.

## 0. Core Principle

PokemonBattleInference is not a CRUD project. It is a rule-heavy battle inference and damage-calculation system. Green tests are not enough: tests and implementation must preserve real Pokemon domain semantics, cross-generation boundaries, maintainable architecture, and reviewability.

Default preference:

1. Domain truth over convenient fake examples.
2. Explicit types over floating raw strings.
3. Stable layer boundaries over fast local hacks.
4. Policy/profile-driven rule differences over scattered generation `if` logic.
5. Business-semantic tests over coverage-only tests.
6. IDE/static-analysis readability over clever runtime indirection.
7. Small, verifiable steps over broad rewrites.

Python code style preference:

Although this repository uses Python, write core domain/application code as close as reasonably possible to statically typed compiled-language style.

Prefer:
- explicit domain types over raw strings/dicts
- Enum/value object/dataclass over ad-hoc runtime structures
- typed factory methods or explicit match dispatch over hidden runtime registries when reviewability and IDE navigation matter
- clear no-op objects over None-based branching
- type narrowing over broad Any/Optional propagation
- pyright/Pylance-friendly signatures
- explicit public APIs over magic/reflection/dynamic getattr/setattr

Avoid:
- excessive dynamic dispatch
- monkey patching
- reflection-driven business rules
- stringly-typed domain concepts
- dicts that hide important domain-to-implementation mappings
- runtime mutation of object shape
- clever Python tricks that make code harder to review, navigate, or statically analyze

The goal is not to make Python verbose for its own sake. The goal is domain correctness, maintainability, IDE navigation, and safer long-term refactoring.

## 1. Repository Scope And Skill Routing

- Use this skill for PokemonBattleInference business code outside `submodules/common/`.
- If a change touches `submodules/common/`, apply the relevant skill instructions from `submodules/common/.codex/skills` to those files.
- When one task spans both areas, keep common-library changes separate from PokemonBattleInference business-specific behavior.
- When a task changes reusable repository rules, update this skill or a reference file in the same change.

## 2. Required Context Rebuild

At the beginning of every substantial task or phase, rebuild context from current repository facts. Do not rely on earlier chat memory as the source of truth.

Inspect as relevant:

```bash
git status --short
find . -maxdepth 3 -type f | sort | sed -n '1,200p'
```

Read or inspect:

- Relevant production code.
- Relevant tests.
- `README.md`.
- `AGENTS.md` if present in the repository path being edited.
- `.codex/skills/` repository guidance when present and relevant.
- `docs/skills/vibe_coding_workflow.md` if present.
- Recent `# Development Snapshot` and `# Cross-check for ChatGPT Review` material if present.
- `references/pokeop-data-views.md` when implementing or reviewing views, repositories, services, or damage-calculation data fetches.

Search for snapshots/checks with repository search, for example:

```bash
rg "# Development Snapshot|# Cross-check for ChatGPT Review" .
```

If these materials are not found, state that they were not found. Never fabricate files, test results, repository facts, or architecture state.

## 3. Project Layout

- `pokeop/api`: FastAPI gateway layer. Only validate/translate request data, call application use cases, and translate results into HTTP responses.
- `pokeop/application`: gateway-independent use cases, command/query/DTO, orchestration, repository calls, domain object assembly, domain service invocation.
- `pokeop/domain`: pure business entities, value objects, enums, battle rules, damage formula, type effectiveness, modifiers, status rules, and calculations.
- `pokeop/persistence`: PostgreSQL-facing business persistence: SQLAlchemy bases/models, generated raw DAOs, schema declarations, importers, materialized views, query repositories, row records, SQL.
- `pokeop/infrastructure`: generic infrastructure adapters such as logging, connection/session setup, pools, message queues, Flink, MongoDB, Redis, cache clients, and external-system clients.
- `pokeop/assets_data`: PokeAPI CSV static data source. It is a symlink to `submodules/pokeapi/data/v2/csv`.
- `pokeop/assets_static`: Swagger UI and other static resources.
- `tests/`: top-level pytest tests, mirroring production layers when useful: `tests/domain`, `tests/application`, `tests/persistence`.

When infrastructure code becomes broadly reusable across future business repositories, move it to `submodules/common/` under the common repository's own skill rules instead of keeping it business-specific here.

## 4. Layer Boundaries

Keep dependency direction one-way:

```text
api -> application -> domain
application -> persistence
```

Rules:

- `domain` must not depend on FastAPI, PostgreSQL, SQLAlchemy, DAOs, repositories, CSV files, external services, `api`, `application`, or `persistence`.
- `domain` receives already-built business objects or primitive values and performs pure business rules/calculations.
- `application` may decide what data is needed, call repositories, build domain objects, invoke domain calculators/services, and return DTOs.
- `application` must not contain SQL, SQLAlchemy session logic, DAO internals, or raw view-specific query details.
- `persistence` implements database access: SQLAlchemy models, DAOs, repositories, schemas, importers, materialized views, projections, SQL.
- `api` must not contain domain calculations or database queries.
- If a stage does not involve database behavior, do not introduce `persistence`, database access, or external services.

Placement rule of thumb:

- Pure calculation/business rule: `domain`.
- One business action / use-case orchestration: `application`.
- Database query, SQLAlchemy, DAO, repository implementation, materialized-view record: `persistence`.
- HTTP request/response transformation: `api`.
- Connection pool, transaction wrapper, logging, MQ/Flink/Mongo/Redis/external client: `infrastructure`.
- Tests: `tests`.

## 5. Shared Common Package Resolution

- Treat `submodules/common/python` as the authoritative in-repo source for `mental1104` during PokemonBattleInference development.
- `pokeop/__init__.py` must prefer `submodules/common/python`, then `submodules/common/export/python`, before `COMMON_ROOT`, `~/code/common`, or any system-installed `mental1104` package.
- VSCode/Pylance settings should stay aligned with runtime resolution: `python.analysis.extraPaths` should include `${workspaceFolder}/submodules/common/python`.
- Scripts that need `mental1104` before importing `pokeop` should explicitly put the repository root and `submodules/common/python` on `sys.path`, with `submodules/common/python` taking precedence over system packages.
- To verify actual runtime resolution, import `pokeop` first and use `importlib.util.find_spec("mental1104")`. Avoid importing `mental1104.db` only to inspect paths because package initialization can load optional dependencies such as PyMongo/OpenSSL.

## 6. Raw PokeAPI CSV And Generated Artifacts

Before changing code that depends on raw PokeAPI CSV tables, regenerate model and DAO artifacts:

```bash
python3 tool/gen_model_from_csv.py pokeop/assets_data pokeop/persistence/raw/models
python3 tool/gen_dao_from_csv.py pokeop/assets_data pokeop/persistence/raw/models pokeop/persistence/raw/dao
```

Then inspect generated diffs:

```bash
git diff -- pokeop/persistence/raw/models pokeop/persistence/raw/dao
```

Rules:

- Do not hand-edit files under `pokeop/persistence/raw/models/` or `pokeop/persistence/raw/dao/` unless the task is explicitly about emergency repair.
- To change generated output, update `tool/gen_model_from_csv.py` or `tool/gen_dao_from_csv.py`, regenerate, and include generated output.
- Keep persistence generic. Do not encode Pokemon Champion-specific assumptions into raw import, generated models, DAOs, or reusable views.
- Put game/team-specific filters above the generic version-group/generation views.
- Do not expose database passwords, `.env`, tokens, private keys, or secrets in prompts, docs, diffs, or reports.

Raw data notes:

- `pokeop/persistence/bootstrap.py` imports generated models and DAOs, creates schema `poke_raw`, creates all `RawBase` tables, and optionally imports every CSV.
- `tool/gen_model_from_csv.py` creates one SQLAlchemy model per CSV. Tables with an `id` column use `id` as primary key; tables without `id` currently use all columns as a composite primary key.
- `tool/gen_dao_from_csv.py` creates one CSV import DAO per generated model. Empty CSV values are converted to stable defaults for generated NOT NULL columns: integer `0`, boolean `False`, text `""`.
- If import correctness depends on true SQL NULL rather than default sentinels, fix the model generator's primary-key strategy before changing DAO import conversion.
- `_csv_import_version` lives in `poke_raw` and records import version, including `imported_at`.

## 7. View Strategy And Data Boundary

For cross-generation battle data, build views around `version_group_id` first and derive `generation_id` from `version_groups`. This matches PokeAPI move learnsets, move changelogs, machines, held items, and game-version data better than a single hard-coded generation or game.

Materialized views:

- Managed through `pokeop.persistence.views`, not through `Base.metadata.create_all()`.
- SQL files live under `pokeop/persistence/views/sql/<schema>/<view>.sql`.
- Registry owns schema names, materialized-view names, indexes, comments, and execution order.
- Current first ruleset schema is `poke_champion`; views preserve `ruleset_id`, `generation_id`, and `version_group_id`.
- Future first-to-ninth-generation views should use the same column shape, either by adding new ruleset rows or by creating a separate schema with the same view names.

Operational commands:

```bash
python3 tool/manage_materialized_views.py recreate
python3 tool/manage_materialized_views.py refresh
python3 tool/manage_materialized_views.py recreate --import-csv
```

Code entrypoint:

```python
from pokeop.persistence.bootstrap import init_db

init_db(create_tables=True, import_csv=True, recreate_materialized_views=True)
```

Historical data rules:

- PokeAPI `*_past.generation_id` behaves as the last generation where an old value applied.
- For a target generation, choose the nearest past row whose `generation_id` is greater than or equal to the target generation; otherwise use the current table.
- `move_changelog.changed_in_version_group_id` stores old values from before that version group changed the move.
- Domain code should not understand PokeAPI historical table structure. Resolve historical data in views or persistence repositories.

Read `references/pokeop-data-views.md` before implementing or reviewing view/repository behavior.

## 8. Battle Rules And Domain Modeling Standards

### 8.1 Domain Truth First

Tests and examples must use plausible Pokemon facts when they claim to represent battle behavior.

Avoid fake combinations such as:

- Gen5 tests using Sylveon, because Sylveon is Gen6+.
- Scizor using Flamethrower when the test claims realistic learnability.
- Sylveon with Eviolite as a positive scenario, because Sylveon cannot evolve further.

Synthetic objects are allowed only when the test explicitly says it is testing formula mechanics rather than real learnsets or roster legality. Name/docstring must make that boundary clear.

### 8.2 Generation Semantics Must Be Conservative

Do not expose unverified generation buckets in public APIs.

Avoid public names like:

```python
GEN1_TO_GEN3
GEN4_TO_GEN5
gen6_or_gen7()
```

Prefer explicit public profiles:

```python
BattleRulesetProfile.GEN1
BattleRulesetProfile.GEN2
BattleRulesetProfile.GEN3
BattleRulesetProfile.GEN4
BattleRulesetProfile.GEN5
BattleRulesetProfile.GEN6
BattleRulesetProfile.GEN7
BattleRulesetProfile.GEN8
BattleRulesetProfile.GEN9
```

Internal private helpers may reuse identical field sets, but public names must not imply that generations are fully equivalent unless that equivalence has been verified and documented.

Known examples to protect:

- Sandstorm Rock special-defense boost is Gen4+, not all generations.
- Snow Ice defense boost is Gen9+, not Gen8.
- Critical hit multiplier is 2x before Gen6 and 1.5x in Gen6+.
- Sniper should scale from the current generation's critical multiplier: legacy 2x -> 3x, modern 1.5x -> 2.25x.

### 8.3 Rule Differences Belong In Policy/Profile

Do not scatter generation checks inside modifiers or calculation steps.

Preferred flow:

```text
ruleset resolver
  -> BattleRulesetProfile
      -> DamagePolicy / StatusPolicy / BattlePolicy
          -> modifier reads policy and executes
```

Good modifier style:

```python
if policy.snow_ice_defense_multiplier is not None:
    ...
```

Avoid modifier style:

```python
if generation >= 9:
    ...
```

Modifiers execute the current rule. Profiles/policies decide what the current rule is.

### 8.4 Prefer Explicit Enums And Value Objects Over Raw Strings

Important domain concepts should not float through domain code as naked strings.

Prefer:

```python
DamageItem.LIFE_ORB
DamageAbility.SNIPER
BattleRulesetProfile.GEN9
```

over repeated raw values such as:

```python
"life-orb"
"choice-band"
"sniper"
"technician"
```

Input strings may exist at API/application/persistence boundaries, but entering domain should parse or normalize them into enums/value objects.

Unknown behavior:

- Unknown ability/item should resolve to an explicit `UNKNOWN` enum/value and a no-op effect.
- Do not spread `None` checks across modifiers.
- Do not crash on unknown names unless the use case explicitly demands strict validation.

### 8.5 Prefer IDE-Jumpable Implementation Mapping

For small to medium domain mappings, prefer enum methods or explicit `match` statements that allow IDE/static navigation.

Preferred:

```python
def create_effect(self) -> ItemDamageEffect:
    match self:
        case DamageItem.LIFE_ORB:
            return LifeOrbEffect()
        case DamageItem.CHOICE_BAND:
            return ChoiceBandEffect()
        case DamageItem.UNKNOWN:
            return NoOpItemEffect()
```

Avoid hiding all important domain relationships in runtime dictionaries unless the registry pattern is clearly justified.

Goals:

- Pylance/pyright friendly.
- Ctrl-click navigable.
- Easy to review.
- Minimal optional/member-access noise.
- New contributors can understand where behavior lives.

### 8.6 Avoid Global Rule Objects When Builder/Profile Is Clearer

Avoid presenting one global object as if it is the only ruleset:

```python
GEN9_RULESET
```

Prefer profile/build style when possible:

```python
BattleRulesetProfile.GEN9.build()
BattleRulesetProfile.from_generation_id(9).build()
```

This makes the ruleset look like a generated snapshot of a profile, not a universal global singleton.

## 9. Test Design Standards

Tests are executable specification, not just coverage.

General rules:

- Keep test functions focused on scenario selection, calling behavior under test, and assertions.
- Do not inline large Pokemon, move, stat, status, ruleset, or fake-random setup blocks inside individual test cases when those objects are reusable.
- Put common test data behind helper factories or builders under the relevant test package, such as `tests/domain/battle/helpers.py` for battle-domain tests.
- Prefer named factory methods for recurring fixtures: common Pokemon profiles, battle snapshots, move profiles, status snapshots, ruleset profiles, deterministic RNG.
- Every new or substantially changed test function must begin with a triple-double-quoted Chinese docstring of at least 100 Chinese characters explaining the scenario, inputs, expected behavior, and protected boundary.
- Treat test code as maintainable production-adjacent code: avoid copy-pasted setup, keep behavior readable, and reuse existing factories before adding raw constructors.

Organization rules:

- Group tests by business concept, not by random accumulation order.
- One ability or ability family should usually have one test class.
- One item or item family should usually have one test class.
- Cross-generation rule differences should have explicit scenario names.
- Unknown/no-op behavior should have its own tests.

Preferred style:

```python
class TestTechnician:
    def test_boosts_low_power_moves(...):
        ...

    def test_does_not_boost_high_power_moves(...):
        ...

class TestSniper:
    def test_raises_legacy_critical_multiplier_to_three_times(...):
        ...

    def test_raises_modern_critical_multiplier_to_two_point_two_five_times(...):
        ...

class TestUnknownAbility:
    def test_unknown_ability_resolves_to_no_op_effect(...):
        ...
```

Avoid:

```python
def test_damage_1(...):
def test_item_bonus(...):
def test_unknown(...):
```

Test file ownership examples:

- Ability behavior belongs in ability-focused test files, not in unrelated critical-hit files just because Sniper affects critical hit damage.
- Critical-hit files should protect base critical rules; ability files should protect ability-specific critical modifiers.
- Weather/screen/status/item tests should live in their own focused test modules when behavior grows.

Test names should express business behavior, not implementation mechanics.

## 10. Static Analysis And Review Quality

Treat pytest passing as necessary but insufficient.

Also check:

- Pylance/pyright-style optional member access problems.
- Protocol property mismatch.
- Dict/value type incompatibility.
- Accidental `Any` leakage across public interfaces.
- Optional returns that force caller-side noise.
- Public API names that encode unverified assumptions.
- Mapping relationships that are hard to jump to or review.

A change is suspicious if it makes tests pass by weakening semantics, hiding type errors, or adding unstructured indirection.

## 11. ChatGPT x Codex Four-Phase Workflow

This project uses a Human + ChatGPT + Codex collaboration loop.

Roles:

- Human: provides requirements, chooses direction, makes final decisions, and avoids acting as manual CI or manual detail reviewer.
- ChatGPT: decomposes requirements, proposes architecture, drafts Codex prompts, reviews Codex output, and decides the next phase with the Human.
- Codex: reads code, implements changes, adds/modifies tests when the phase permits, runs tests, and outputs both Development Snapshot and Cross-check for ChatGPT Review.

Phase triggers:

- Phase 1: `进入 Phase 1`, `需求支持清单`, `生成能力清单`, `生成 Codex 方案`, `需求转测试清单`.
- Phase 2: `进入 Phase 2`, `纯 review 测试`, `只看测试`, `测试固化`, `review test only`.
- Phase 3: `进入 Phase 3`, `只改实现`, `实现适配测试`, `不要改测试`, `implementation only`.
- Phase 4: `进入 Phase 4`, `验证测试`, `失败归因`, `测试不过分析`, `verification`.

If the user does not explicitly specify a phase, output Phase Detection before large substantive changes.

```markdown
# Phase Detection

Detected Phase: Phase X / Unclear

Evidence:
- 看到哪些文件变化
- 看到哪些测试状态
- 看到哪些用户意图
- 为什么判断是这个阶段

If Unclear:
- 最安全建议阶段：
- 本轮动作边界：
```

If phase is unclear, do not make broad implementation changes. Recommend the safest phase or perform only low-risk inspection/reporting.

## 12. Global Execution Rules For Codex Rounds

- Before editing files, state the intended edit boundary and verify it matches the detected phase.
- Preserve unrelated working-tree changes.
- Do not output meaningless logs, long diffs, or large source blocks.
- Do not fabricate files, test results, or architectural facts.
- Prefer the smallest relevant test command first.
- Report tests that could not be run and explain why.
- Every round must end with `# Development Snapshot` and `# Cross-check for ChatGPT Review`.
- If a section does not apply, write `不适用`.
- Do not silently change tests during implementation-only Phase 3.
- Do not silently change implementation during review-test-only Phase 2.
- If phase constraint conflicts with the user's current explicit request, prioritize the user's explicit request, report the conflict in Deviation Report, and stop if the request would break project layering.

## 13. Phase 1: Requirement Support Matrix / Plan Generation

Goal: convert broad Human requirements into an executable capability list, test list, implementation boundary, and Codex prompt draft.

Allowed:

- Read code, tests, docs, and repository guidance.
- Produce analysis, matrices, risk notes, and prompt draft.
- Suggest test scenarios and implementation boundaries.

Forbidden:

- Do not directly make large production-code changes.
- Do not create broad implementation changes before Human and ChatGPT approve the direction.
- Do not assume unsupported requirements are in scope.

Procedure:

1. Rebuild context from repository state.
2. Convert Human request into discrete capabilities.
3. Mark each capability as supported, unsupported, partially supported, or unclear based on current code/tests.
4. Identify tests required to lock down behavior.
5. Identify editable directories and prohibited directories.
6. Surface architecture risks, data dependencies, and boundary concerns.
7. Draft a Codex prompt for Phase 2 or Phase 3.

Output:

```markdown
# Requirement Support Matrix

| Requirement | Current Support | Evidence | Test Need | Implementation Boundary | Notes |
| --- | --- | --- | --- | --- | --- |

# Suggested Test Scenarios

# Suggested Implementation Boundary

# Risks

# Suggested Codex Prompt Draft
```

Completion standard: Human and ChatGPT can decide whether to enter Phase 2.

## 14. Phase 2: Review-Test-Only Contract Hardening

Goal: review and harden tests only. Tests become executable requirement specification.

Allowed:

- Read existing tests and production code needed to understand behavior.
- Add or modify tests.
- Improve test names and test structure so business semantics are explicit.
- Make only a tiny production-code exposure fix if tests cannot import target behavior, and explicitly report it.

Forbidden:

- Do not modify production implementation.
- Do not change behavior to make tests pass.
- Do not introduce database, API, or external dependencies unless requirement explicitly covers that integration layer.
- Do not over-bind tests to private implementation details.

Procedure:

1. Rebuild context from repository state.
2. Read relevant existing tests and identify covered behavior.
3. Compare tests against Phase 1 requirements or current Human request.
4. Identify missing boundary conditions, ambiguous scenarios, fake-domain scenarios, and implementation-coupled tests.
5. Add or modify tests only where needed to encode the requirement contract.
6. Run the smallest relevant pytest target.
7. Report any import-only production exposure fix as a deviation.

Output:

```markdown
# Test Review Report

# Test Scenario Matrix

| Scenario | Requirement Encoded | Test File | Expected Behavior | Boundary Protected | Status |
| --- | --- | --- | --- | --- | --- |

# Added/Modified Tests

# Tests That Encode Requirements

# Ambiguous Tests

# Missing Tests

# Cross-check for ChatGPT Review
```

Completion standard: Human and ChatGPT can understand each test scenario line by line, and tests are solid enough to act as the Phase 3 contract.

## 15. Phase 3: Implementation-Only

Goal: implement production behavior to satisfy tests fixed in Phase 2.

Allowed:

- Read tests as the contract.
- Read production code.
- Modify production implementation.
- Refactor production code when it preserves project boundaries and supports the contract.
- Run relevant tests.

Forbidden:

- Do not modify tests.
- Do not alter requirements by editing tests to match implementation.
- Do not silently ignore test failures.
- Do not introduce forbidden dependencies across layers.

If a test is clearly wrong, stale, or incompatible with a necessary signature change, do not edit it in Phase 3. Report it as a Blocker and recommend switching to Phase 2 or Phase 4.

Procedure:

1. Rebuild context from repository state.
2. Read relevant tests and extract behavior contract.
3. Read production code and identify minimal implementation path.
4. Implement missing behavior within layer boundaries.
5. Run relevant tests.
6. If tests fail, record failure cause without changing tests.
7. Map each changed implementation area to the tests it supports.

Output:

```markdown
# Implementation Report

# Files Changed

# Contract Mapping

| Test Contract | Implementation File | Behavior Supported | Notes |
| --- | --- | --- | --- |

# Failed Tests If Any

# Blockers

# Cross-check for ChatGPT Review
```

Completion standard: implementation satisfies fixed tests as much as possible; any remaining failure has a concrete explanation.

## 16. Phase 4: Verification And Failure Attribution

Goal: verify reviewed code against tests and classify every failure before deciding whether to change tests or implementation.

Allowed:

- Run specified or relevant tests.
- Collect failure output.
- Inspect code and tests enough to classify failures.
- Recommend whether to modify tests, modify implementation, ask for requirement confirmation, or split the next fix.

Forbidden:

- Do not immediately fix failing tests without classification.
- Do not rewrite tests or implementation during pure verification unless the user explicitly overrides the phase boundary.
- Do not treat all failures as implementation defects by default.

Failure classification:

- A. Requirement change made tests obsolete.
- B. Architecture or solution change requires test adjustment.
- C. Function signature changed and tests no longer match public contract.
- D. Implementation defect.
- E. Regression caused by related changes.
- F. Test is over-bound to implementation details.
- G. Environment problem.

Procedure:

1. Rebuild context from repository state.
2. Run specified tests, or smallest relevant tests when none are specified.
3. Summarize passed, failed, skipped, and errored tests.
4. For each failure, classify it as A-G and cite evidence.
5. Recommend one action: change tests for new requirements, change implementation for fixed contract, ask Human/ChatGPT to confirm direction, or split next repair round.
6. Avoid making changes unless user explicitly asks for repair and phase conflict is reported.

Output:

```markdown
# Verification Report

# Test Result Summary

| Command | Passed | Failed | Skipped | Error Summary |
| --- | --- | --- | --- |

# Failure Classification

| Failure | Class | Evidence | Recommended Owner/Phase |
| --- | --- | --- | --- |

# Recommended Action

# Cross-check for ChatGPT Review
```

Completion standard: every failure has a classification, and Human/ChatGPT can decide whether to adjust tests, adjust implementation, confirm requirements, or split the next round.

## 17. Required Output: Development Snapshot

Every Codex round must include this section after phase-specific reporting:

```markdown
# Development Snapshot

## 1. Overall Summary

## 2. Files Changed

## 3. Capability Coverage

## 4. Knowledge / Contract / API Changes

## 5. Test Behavior

## 6. Public Models / Interfaces

## 7. Technical Decisions

## 8. Remaining TODO

## 9. Risks

## 10. Suggested Next Milestone

## 11. Architecture Review

## 12. Domain Vocabulary

## 13. Use Cases Covered

## 14. Missing Knowledge

## 15. Architecture Boundary

## 16. Future Consumers

## 17. Readiness
```

Write `不适用` for sections that do not apply. Do not invent content.

## 18. Required Output: Cross-check For ChatGPT Review

Every Codex round must include this section after Development Snapshot:

```markdown
# Cross-check for ChatGPT Review

## 1. Requirement Checklist

- [x] 已完成：
- [~] 部分完成：
- [ ] 未完成：

For each item, cite the relevant implementation file and test file. If no file exists, state `不适用` or `未创建`.

## 2. Deviation Report

- 是否新增了未要求的抽象：
- 是否修改了禁止修改的目录：
- 是否引入了数据库 / persistence / api：
- 是否改变已有接口语义：
- 是否修改测试：
- 是否修改实现：
- 阶段约束冲突：

## 3. Test Evidence

| Command | Passed | Failed | Skipped | Error Summary |
| --- | --- | --- | --- |

## 4. Acceptance Notes for ChatGPT

- 应重点验收的测试场景：
- 应重点验收的实现边界：
- 应重点验收的架构风险：
- 需要人工方向判断的事项：

## 5. Self-review Verdict

Verdict: ACCEPTABLE / ACCEPTABLE_WITH_RISKS / NEEDS_FIX

Reason:
```

The verdict must be exactly one of:

- `ACCEPTABLE`
- `ACCEPTABLE_WITH_RISKS`
- `NEEDS_FIX`

## 19. Validation Commands

For narrow data-generation changes:

```bash
python3 tool/gen_model_from_csv.py pokeop/assets_data pokeop/persistence/raw/models
python3 tool/gen_dao_from_csv.py pokeop/assets_data pokeop/persistence/raw/models pokeop/persistence/raw/dao
python3 -m py_compile tool/gen_model_from_csv.py tool/gen_dao_from_csv.py
```

For domain/application behavior, run the smallest relevant pytest target first, then broader tests if appropriate:

```bash
pytest tests/domain/battle/<target_test_file>.py
pytest tests/domain
pytest tests
```

When static type behavior matters and project config supports it, also run the relevant checker command documented in the repository. If no checker command is available, mention that static validation was limited to code inspection/Pylance-style concerns.

## 20. Final Quality Checklist

Before reporting completion, check:

- Layer boundaries are preserved.
- Domain remains persistence/API/framework independent.
- Generated raw models/DAOs were not hand-edited.
- Version-group and generation semantics are explicit.
- Historical raw data interpretation is not pushed into domain.
- Pokemon examples in tests are domain-realistic or explicitly synthetic.
- Public API does not expose unverified generation buckets.
- Ability/item/ruleset concepts are typed instead of raw-string driven where feasible.
- Unknown ability/item behavior is explicit and no-op when appropriate.
- Tests are organized by business concept and include Chinese docstrings when new/substantially changed.
- Pytest evidence is reported honestly.
- Pylance/pyright-style type problems are not ignored when visible.
- Development Snapshot and Cross-check are included.
