---
name: pokemonbattleinference-guidelines
description: PokemonBattleInference 仓库专用维护指南。Codex 在修改 pokeop 数据导入、PokeAPI CSV、pokeop/persistence/raw/models 自动生成模型、pokeop/persistence/raw/dao 自动生成 DAO、PostgreSQL poke_raw schema、数据库初始化、跨世代宝可梦/招式/属性视图、伤害计算数据读取边界，或更新本仓库 Codex skill 时使用。
---

# PokemonBattleInference Guidelines

Use this skill for repository work under `/home/mental1104/code/PokemonBattleInference`, especially `pokeop`.

## Required Workflow

1. Before changing code that depends on raw PokeAPI CSV tables, regenerate model and DAO artifacts:

```bash
python3 tool/gen_model_from_csv.py pokeop/assets_data pokeop/persistence/raw/models
python3 tool/gen_dao_from_csv.py pokeop/assets_data pokeop/persistence/raw/models pokeop/persistence/raw/dao
```

2. Inspect generated diffs before editing generated files:

```bash
git diff -- pokeop/persistence/raw/models pokeop/persistence/raw/dao
```

3. Do not hand-edit files under `pokeop/persistence/raw/models/` or `pokeop/persistence/raw/dao/` unless the task is explicitly about emergency repair. Update `tool/gen_model_from_csv.py` or `tool/gen_dao_from_csv.py`, regenerate, then commit the generated output.
4. Treat `pokeop/assets_data` as the CSV root. It is a symlink to `submodules/pokeapi/data/v2/csv`.
5. Keep persistence generic. Do not encode Pokemon Champion-specific assumptions into raw import, generated models, DAOs, or reusable views. Put game/team-specific filters above the generic version-group/generation views.
6. When a task changes reusable repository rules, update this skill or a reference file in the same change.

## Skill Routing

- If a code change touches files under `submodules/common/`, use the applicable skill instructions from `submodules/common/.codex/skills` for those common-code edits.
- If a code change is for PokemonBattleInference business code outside `submodules/common/`, use this repository's `.codex/skills` instructions.
- When one task spans both areas, apply each repository's skill rules to its own files and keep common-library changes separate from PokemonBattleInference business-specific behavior.

## Shared Common Package Resolution

- Treat `submodules/common/python` as the authoritative in-repo source for `mental1104` during PokemonBattleInference development.
- `pokeop/__init__.py` must prefer `submodules/common/python`, then `submodules/common/export/python`, before `COMMON_ROOT`, `~/code/common`, or any system-installed `mental1104` package.
- VSCode/Pylance settings should stay aligned with runtime resolution: `python.analysis.extraPaths` should include `${workspaceFolder}/submodules/common/python`.
- Scripts that need `mental1104` before importing `pokeop` should explicitly put the repository root and `submodules/common/python` on `sys.path`, with `submodules/common/python` taking precedence over system packages.
- To verify actual runtime resolution, import `pokeop` first and use `importlib.util.find_spec("mental1104")`. Avoid importing `mental1104.db` only to inspect paths because package initialization can load optional dependencies such as PyMongo/OpenSSL.

## pokeop Package Layout

- Use `pokeop/assets_data` for static CSV data and `pokeop/assets_static` for web/static assets. Keep both names under the shared `assets_` prefix so filesystem sorting groups static resources together.
- Use `pokeop/domain` for business entities, value objects, and pure domain calculations.
- Use `pokeop/application` for gateway-independent use cases and business functions.
- Use `pokeop/persistence` for database-facing business persistence: SQLAlchemy bases/models, generated raw DAOs, schema declarations, importers, materialized views, and query repositories.
- Use `pokeop/infrastructure` only for generic infrastructure adapters such as logging, connection/session setup, connection pools, message queues, Flink, MongoDB, cache clients, and external-system clients.
- When infrastructure code becomes broadly reusable across future business repositories, move it to `submodules/common/` under the common repository's own skill rules instead of keeping it business-specific here.

## Layer Boundaries

- Keep dependency direction one-way: `api -> application -> domain`, and `application -> persistence` for data access orchestration.
- Keep `domain` independent of FastAPI, PostgreSQL, SQLAlchemy, DAO, repository implementations, CSV files, and external services. Domain code should receive already-built business objects or primitive values and perform pure business rules/calculations.
- Use `application` as the use-case orchestration layer. It may decide what data is needed, call repositories, build domain objects, invoke domain services/calculators, and return application DTOs. It should not contain SQL, SQLAlchemy session logic, or DAO internals.
- Use `persistence` to implement database access: SQLAlchemy models, DAOs, repository implementations, row records, view projections, SQL, importers, and database schema names.
- Use `api` only as an HTTP adapter: validate/translate request data, call application use cases, and translate application results into responses. Do not put domain calculations or database queries in API routers.
- Use top-level `tests/` for tests, mirroring the production layer under test when helpful, such as `tests/domain`, `tests/application`, and `tests/persistence`.

## Test Design

- Keep test functions focused on scenario selection, calling the behavior under test, and assertions.
- Do not inline large Pokemon, move, stat, status, ruleset, or fake-random setup blocks inside individual test cases when those objects are reusable.
- Put common test data behind helper factories or builders under the relevant test package, such as `tests/domain/battle/helpers.py` for battle-domain tests.
- Prefer named factory methods for recurring fixtures, for example common Pokemon profiles, battle snapshots, move profiles, status snapshots, and deterministic RNG.
- Every new or substantially changed test function must begin with a triple-double-quoted Chinese docstring of at least 100 Chinese characters that explains the scenario, inputs, expected behavior, and protected boundary.
- Treat test code as maintainable production-adjacent code: avoid copy-pasted setup, keep behavior readable, and make future test scenarios reuse existing factories before adding new raw constructors.

## Raw Data Notes

- `pokeop/persistence/bootstrap.py` imports generated models and DAOs, creates schema `poke_raw`, creates all `RawBase` tables, and optionally imports every CSV.
- `tool/gen_model_from_csv.py` creates one SQLAlchemy model per CSV. Tables with an `id` column use `id` as primary key; tables without `id` currently use all columns as a composite primary key.
- `tool/gen_dao_from_csv.py` creates one CSV import DAO per generated model. Empty CSV values are converted to stable defaults for generated NOT NULL columns: integer `0`, boolean `False`, text `""`.
- If import correctness depends on true SQL NULL rather than default sentinels, fix the model generator's primary-key strategy before changing DAO import conversion.
- Materialized views are managed through `pokeop.persistence.views`, not through `Base.metadata.create_all()`. Use `tool/manage_materialized_views.py` or `init_db(..., create_materialized_views=True/recreate_materialized_views=True/refresh_materialized_views=True)`.

## View Strategy

For cross-generation battle data, build views around `version_group_id` first and derive `generation_id` from `version_groups`. This matches PokeAPI move learnsets, move changelogs, machines, held items, and game-version data better than a single hard-coded generation or game.

Read `references/pokeop-data-views.md` when implementing or reviewing views, repositories, services, or damage-calculation data fetches.

Current materialized views live under schema `poke_champion` and are generated from SQL files in `pokeop/persistence/views/sql/poke_champion/`. They are Pokemon Champion rule projections over raw CSV data, with `ruleset_id`, `generation_id`, and `version_group_id` columns preserved so later generations/rulesets can follow the same shape.

## Validation

For narrow data-generation changes:

```bash
python3 tool/gen_model_from_csv.py pokeop/assets_data pokeop/persistence/raw/models
python3 tool/gen_dao_from_csv.py pokeop/assets_data pokeop/persistence/raw/models pokeop/persistence/raw/dao
python3 -m py_compile tool/gen_model_from_csv.py tool/gen_dao_from_csv.py
```

For application behavior, run the smallest relevant pytest target first:

```bash
pytest tests
```
