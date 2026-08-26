# Implement Node

Implement executes plan items approved by the Router's repair scope and then returns to `Validate`.

## Load Rules

- Load this file only after the graph enters `Implement`.
- Consume only `ImplementationPlan` items marked inside the approved repair scope.
- Do not copy validator logic into this node.
- Load standards only when necessary to avoid violating the approved plan.

## Inputs

- Approved repair scope from the Router.
- `ImplementationPlan` items inside that approved scope.
- Repository files named by the approved plan.
- Validation evidence linked from the plan.

## Responsibilities

- Modify only files required by plan items inside the approved scope.
- Preserve unrelated working-tree changes.
- Keep each edit traceable to a `plan_item_id` and `standard_id`.
- Avoid widening scope when adjacent issues are noticed.
- Run only validation or test commands approved by the plan or needed to confirm the modified contract.
- After implementation, return to `Validate` and use the same validation rules as the initial validation.

## Prohibited

- Do not implement plan items outside the approved scope.
- Do not modify business code, tests, CI, or build logic unless that exact file class is in the approved plan.
- Do not redefine standards.
- Do not add graph nodes.
- Do not mark the graph complete without re-entering `Validate`.
- Do not clean up user-provided integration resources.

## Required Output Shape

Return an `ImplementationResult`:

```text
implemented_plan_items:
files_changed:
validation_commands_run:
known_limits:
next_edge: Validate
```

## Completion

Implementation is complete only after approved edits are made and the graph proceeds back to `Validate`.
