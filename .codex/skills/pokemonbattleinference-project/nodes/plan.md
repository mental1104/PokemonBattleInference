# Plan Node

Plan consumes `ValidateResult` and proposes minimal repairs for actual failures. It is read-only.

## Load Rules

- Load this file only after the graph enters `Plan`.
- Consume the latest `ValidateResult`.
- Load standards only when needed to interpret a failed standard.
- Do not load `implement.md` during planning.

## Inputs

- Latest `ValidateResult`.
- Repair scope from the Router, if present.
- Repository evidence cited by validation.

## Responsibilities

- Analyze root cause only for `FAIL` items in the consumed `ValidateResult`.
- Propose the smallest practical modification for each in-scope failure.
- Associate every proposed change with the original `standard_id` and validation evidence.
- Identify files likely to change.
- Define how the same `Validate` node will verify the repair.
- Separate mandatory fixes from optional improvements.
- Mark which plan items are inside the current repair scope.

## Prohibited

- Do not modify code.
- Do not modify tests.
- Do not modify CI or build logic.
- Do not redefine standards.
- Do not plan work for issues that validation did not report.
- Do not bundle unrelated cleanup into a repair item.
- Do not decide graph edges; the Router decides whether scoped plan items may enter `Implement`.

## Required Output Shape

Return an `ImplementationPlan`:

```text
plan_item_id:
standard_id:
source_failure:
proposed_change:
expected_files:
validation_after_fix:
mandatory: true | false
inside_approved_scope: true | false
```

Keep the plan small enough that the Human can approve individual items.

## Completion

Planning is complete when every in-scope `FAIL` has either a minimal repair item or a clear reason it cannot be planned from available evidence. Return the plan to the Router, which decides whether to stop or continue to `Implement`.
