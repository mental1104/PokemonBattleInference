# Validate Node

Validate is a read-only graph node. It checks the repository against relevant standards and emits evidence. It does not design or execute repairs.

## Load Rules

- Load this file only after the graph enters `Validate`.
- Load `../standards/local-first-testability.md` when validating Local-first Testability.
- Do not load `plan.md` or `implement.md` during validation.
- For post-implementation validation, use the same standards loaded during the initial validation.

## Inputs

- Repository root.
- Current platform and available capabilities when relevant.
- Relevant standards.
- Current repository files and configuration.
- Optional Human-provided validation scope.

## Read-only Evidence Sources

Inspect only what is needed for the requested validation scope:

- `AGENTS.md` and `CONTRIBUTING.md` if present at the repository root.
- `.codex/skills/` organization.
- `Makefile`, `pytest.ini`, `pyproject.toml`, package manifests, and build scripts.
- `.github/workflows/` only as read-only evidence.
- Test layout under `tests/`.
- Environment-variable reads, pytest marks, skip/skipif usage, Docker/Compose targets, and database/bootstrap code.

Read-only/test commands may be run when useful:

- File listing and search commands such as `rg`, `find`, `sed`, `nl`, and `git status --short`.
- Test collection or targeted test commands when the Human asks for behavioral validation and the command does not require modifying repository state beyond normal test caches.

## Required Output Shape

Return a concise `ValidateResult` with one item per checked standard:

```text
standard_id:
status: PASS | FAIL | SKIP
mandatory: true | false
evidence:
reason:
expected:
actual:
```

Use `expected` and `actual` only when they help objectively describe the gap. Use `SKIP` only when the standard is outside the requested scope or cannot be evaluated because a legitimate capability is unavailable. Missing repository evidence for a mandatory standard should usually be `FAIL`, not `SKIP`.

## Prohibited

- Do not modify code.
- Do not modify tests.
- Do not modify CI or build logic.
- Do not design a repair plan.
- Do not output a repair proposal or minimum fix.
- Do not auto-enter `Implement`.
- Do not redefine standards.
- Do not use a different validation rule set after implementation.

## Completion

Validation is complete when all requested standards have a `PASS`, `FAIL`, or `SKIP` item with evidence. Return the result to the Router, which decides whether to stop or enter `Plan`.
