---
name: vibe-coding-workflow
description: 'Use this PokemonBattleInference workflow to coordinate ChatGPT x Codex Vibe Coding through four phases: Phase 1 requirement support matrix and plan generation, Phase 2 review-test-only contract hardening, Phase 3 implementation-only changes, and Phase 4 verification and failure attribution. Trigger on "进入 Phase 1", "需求支持清单", "生成能力清单", "生成 Codex 方案", "需求转测试清单", "进入 Phase 2", "纯 review 测试", "只看测试", "测试固化", "review test only", "进入 Phase 3", "只改实现", "实现适配测试", "不要改测试", "implementation only", "进入 Phase 4", "验证测试", "失败归因", "测试不过分析", or "verification"; if the phase is not explicit, first output Phase Detection.'
---

# Vibe Coding 四阶段协作工作流

Use this skill inside the PokemonBattleInference repository to guide cross-development between Human, ChatGPT, and Codex. Treat this file as self-contained. At the start of every phase, rebuild context from repository state; do not assume earlier chat context is still available or correct.

## Core Roles

- Human: provide requirements, choose direction, make final decisions, and avoid acting as manual CI or manual detail reviewer.
- ChatGPT: decompose requirements, propose architecture, draft Codex prompts, review Codex output, and decide the next phase with the Human.
- Codex: read code, implement changes, add or modify tests when the phase permits, run tests, and output both Development Snapshot and Cross-check for ChatGPT Review.

## Repository Boundaries

- Keep dependency direction one-way: `api -> application -> domain`, and `application -> persistence`.
- Keep `domain` independent from FastAPI, PostgreSQL, SQLAlchemy, DAOs, repositories, CSV files, external services, `api`, `application`, and `persistence`.
- Use `application` for use-case orchestration: select required data, call repositories, build domain objects, invoke domain services, and return DTOs.
- Use `persistence` for database access: SQLAlchemy models, DAOs, repositories, schemas, importers, materialized views, projections, and SQL.
- Use `api` only as the HTTP adapter: validate and translate requests, call application use cases, and translate application results.
- Use top-level `tests/` for pytest tests, mirroring production layers when useful.
- If a stage does not involve database behavior, do not introduce `persistence`, database access, or external services.
- Do not hand-edit generated raw models or DAOs under `pokeop/persistence/raw/models/` or `pokeop/persistence/raw/dao/` unless the user explicitly asks for emergency repair or generator work.

## Phase Triggers

Phase 1 triggers:

- "进入 Phase 1"
- "需求支持清单"
- "生成能力清单"
- "生成 Codex 方案"
- "需求转测试清单"

Phase 2 triggers:

- "进入 Phase 2"
- "纯 review 测试"
- "只看测试"
- "测试固化"
- "review test only"

Phase 3 triggers:

- "进入 Phase 3"
- "只改实现"
- "实现适配测试"
- "不要改测试"
- "implementation only"

Phase 4 triggers:

- "进入 Phase 4"
- "验证测试"
- "失败归因"
- "测试不过分析"
- "verification"

If the user does not explicitly specify a phase, output Phase Detection before making substantive changes.

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

If the phase is unclear, do not directly make large implementation changes. Recommend the safest phase and wait for direction or perform only low-risk inspection/reporting.

## Required Context Rebuild

At the beginning of every phase, rebuild context from current repository facts.

Read or inspect:

- Current directory structure and relevant file list.
- `git status --short` to identify existing changes and avoid overwriting unrelated work.
- Relevant production code.
- Relevant tests.
- `README.md`.
- `AGENTS.md` if present in the repository path being edited.
- `.codex/skills/` repository guidance when present and relevant.
- `docs/skills/vibe_coding_workflow.md`.
- Recent Development Snapshot material if it exists in the repository.
- Recent Cross-check for ChatGPT Review material if it exists in the repository.

Use repository search to locate snapshots and cross-checks, for example by searching for `# Development Snapshot` and `# Cross-check for ChatGPT Review`. If these materials do not exist, state that they were not found. Never say "根据上次我们讨论" or rely on memory from earlier chat.

## Global Execution Rules

- Before editing files, state the intended edit boundary and verify it matches the detected phase.
- Preserve unrelated working-tree changes.
- Do not output meaningless logs, long diffs, or large source blocks.
- Do not fabricate files, test results, or architectural facts.
- Prefer the smallest relevant test command first.
- Report tests that could not be run and explain why.
- Every round must end with Development Snapshot and Cross-check for ChatGPT Review. If a section does not apply, write "不适用".

## Phase 1: 需求支持清单 / 方案生成

Goal: convert broad Human requirements into an executable capability list, test list, implementation boundary, and Codex prompt draft.

Inputs:

- Human natural-language requirements.
- Current repository code.
- Existing tests.
- Project layering rules.

Allowed actions:

- Read code, tests, docs, and repository guidance.
- Produce analysis, matrices, risk notes, and a prompt draft.
- Suggest test scenarios and implementation boundaries.

Forbidden actions:

- Do not directly make large production-code changes.
- Do not create broad implementation changes before the Human and ChatGPT approve the direction.
- Do not assume unsupported requirements are in scope.

Procedure:

1. Rebuild context from repository state.
2. Convert the Human request into discrete capabilities.
3. Mark each capability as supported, unsupported, partially supported, or unclear based on current code and tests.
4. Identify tests required to lock down the behavior.
5. Identify editable directories and prohibited directories.
6. Surface architectural risks, data dependencies, and boundary concerns.
7. Draft a Codex prompt for Phase 2 or Phase 3, depending on the safest next step.

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

## Phase 2: 纯 Review 测试

Goal: review and harden tests only. Tests should become an executable requirement specification.

Allowed actions:

- Read existing tests and production code needed to understand behavior.
- Add or modify tests.
- Improve test names and test structure so business semantics are explicit.
- Make only a tiny production-code exposure fix if tests cannot import the target behavior, and explicitly report it.

Forbidden actions:

- Do not modify production implementation.
- Do not change behavior to make tests pass.
- Do not introduce database, API, or external dependencies unless the requirement explicitly covers that integration layer.
- Do not over-bind tests to private implementation details.

Test quality rules:

- New or substantially changed test functions must begin with a triple-double-quoted Chinese docstring of at least 100 Chinese characters explaining the scenario, inputs, expected behavior, and protected boundary.
- Keep each test focused on scenario selection, behavior invocation, and assertions.
- Prefer reusable helpers or factories for recurring Pokemon, move, stat, status, ruleset, or deterministic random setup.
- Test names must express business behavior, not implementation mechanics.
- Tests should document what is supported, unsupported, ambiguous, and intentionally out of scope.

Procedure:

1. Rebuild context from repository state.
2. Read relevant existing tests and identify covered behavior.
3. Compare tests against Phase 1 requirements or the current Human request.
4. Identify missing boundary conditions, ambiguous scenarios, and tests coupled to implementation details.
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

## Phase 3: 实现阶段

Goal: implement production behavior to satisfy the tests fixed in Phase 2.

Allowed actions:

- Read tests as the contract.
- Read production code.
- Modify production implementation.
- Refactor production code when it preserves project boundaries and supports the contract.
- Run relevant tests.

Forbidden actions:

- Do not modify tests.
- Do not alter requirements by editing tests to match the implementation.
- Do not silently ignore test failures.
- Do not introduce forbidden dependencies across layers.

If a test is clearly wrong, stale, or incompatible with a necessary signature change, do not edit it in Phase 3. Report it as a Blocker and recommend switching to Phase 2 or Phase 4 for review.

Procedure:

1. Rebuild context from repository state.
2. Read relevant tests and extract the behavior contract.
3. Read production code and identify the minimal implementation path.
4. Implement missing behavior within layer boundaries.
5. Run relevant tests.
6. If tests fail, record the failure cause without changing tests.
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

Completion standard: implementation satisfies the fixed tests as much as possible; any remaining failure has a concrete explanation.

## Phase 4: 验证与差异分析

Goal: verify the reviewed code against tests and classify every failure before deciding whether to change tests or implementation.

Allowed actions:

- Run specified or relevant tests.
- Collect failure output.
- Inspect code and tests enough to classify failures.
- Recommend whether to modify tests, modify implementation, ask for requirement confirmation, or split the next fix.

Forbidden actions:

- Do not immediately fix failing tests without classification.
- Do not rewrite tests or implementation during pure verification unless the user explicitly overrides the phase boundary.
- Do not treat all failures as implementation defects by default.

Failure classification:

- A. Requirement change made tests obsolete.
- B. Architecture or solution change requires test adjustment.
- C. Function signature changed and tests no longer match the public contract.
- D. Implementation defect.
- E. Regression caused by related changes.
- F. Test is over-bound to implementation details.
- G. Environment problem.

Procedure:

1. Rebuild context from repository state.
2. Run the specified tests, or the smallest relevant tests when none are specified.
3. Summarize passed, failed, skipped, and errored tests.
4. For each failure, classify it as A-G and cite the evidence.
5. Recommend one action: change tests for new requirements, change implementation for the fixed contract, ask Human/ChatGPT to confirm direction, or split a next repair round.
6. Avoid making changes unless the user explicitly asks for a repair and the phase conflict is reported.

Output:

```markdown
# Verification Report

# Test Result Summary

| Command | Passed | Failed | Skipped | Error Summary |
| --- | --- | --- | --- | --- |

# Failure Classification

| Failure | Class | Evidence | Recommended Owner/Phase |
| --- | --- | --- | --- |

# Recommended Action

# Cross-check for ChatGPT Review
```

Completion standard: every failure has a classification, and Human/ChatGPT can decide whether to adjust tests, adjust implementation, confirm requirements, or split the next round.

## Phase Constraint Conflicts

If the phase constraint conflicts with the current user request:

1. Prioritize the user's current explicit request.
2. Report the conflict in the Deviation Report.
3. Stop and report if the request would break project layering.
4. If the user asks to modify tests during Phase 3, report "不符合 Phase 3", wait for confirmation, or recommend switching to Phase 2.
5. If the user asks to modify implementation during Phase 2, report the conflict and recommend switching to Phase 3 after the tests are accepted.
6. If the user asks for immediate fixes during Phase 4, classify failures first, then ask for or confirm the appropriate repair phase unless the request explicitly overrides this workflow.

## Required Output: Development Snapshot

Every round must include this section after phase-specific reporting.

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

Write "不适用" for sections that do not apply. Do not invent content.

## Required Output: Cross-check for ChatGPT Review

Every round must include this section after Development Snapshot.

```markdown
# Cross-check for ChatGPT Review

## 1. Requirement Checklist

- [x] 已完成：
- [~] 部分完成：
- [ ] 未完成：

For each item, cite the relevant implementation file and test file. If no file exists, state "不适用" or "未创建".

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
| --- | --- | --- | --- | --- |

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

## Quality Requirements

- Base all judgments on repository state.
- Keep each phase independently runnable.
- Keep tests business-semantic and maintainable.
- Avoid broad rewrites unless the phase and requirement justify them.
- Avoid database, persistence, API, or external-system dependencies when the task is purely domain-level.
- Keep reports concise enough for ChatGPT and the Human to review without acting as manual CI.
- Prefer clear blockers over speculative fixes when requirements, contracts, or architecture boundaries are unclear.
