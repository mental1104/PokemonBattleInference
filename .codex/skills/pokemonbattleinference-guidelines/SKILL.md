---
name: pokemonbattleinference-guidelines
description: PokemonBattleInference 仓库专用维护指南。Codex 在修改 pokeop 数据导入、PokeAPI CSV、pokeop/model/poke_raw 自动生成模型、pokeop/dao/poke_raw 自动生成 DAO、PostgreSQL poke_raw schema、数据库初始化、跨世代宝可梦/招式/属性视图、伤害计算数据读取边界，或更新本仓库 Codex skill 时使用。
---

# PokemonBattleInference Guidelines

Use this skill for repository work under `/home/mental1104/code/PokemonBattleInference`, especially `pokeop`.

## Required Workflow

1. Before changing code that depends on raw PokeAPI CSV tables, regenerate model and DAO artifacts:

```bash
python3 tool/gen_model_from_csv.py pokeop/data pokeop/model/poke_raw
python3 tool/gen_dao_from_csv.py pokeop/data pokeop/model/poke_raw pokeop/dao/poke_raw
```

2. Inspect generated diffs before editing generated files:

```bash
git diff -- pokeop/model/poke_raw pokeop/dao/poke_raw
```

3. Do not hand-edit files under `pokeop/model/poke_raw/` or `pokeop/dao/poke_raw/` unless the task is explicitly about emergency repair. Update `tool/gen_model_from_csv.py` or `tool/gen_dao_from_csv.py`, regenerate, then commit the generated output.
4. Treat `pokeop/data` as the CSV root. It is a symlink to `submodules/pokeapi/data/v2/csv`.
5. Keep persistence generic. Do not encode Pokemon Champion-specific assumptions into raw import, generated models, DAOs, or reusable views. Put game/team-specific filters above the generic version-group/generation views.
6. When a task changes reusable repository rules, update this skill or a reference file in the same change.

## Raw Data Notes

- `pokeop/infra/db.py` imports generated models and DAOs, creates schema `poke_raw`, creates all `RawBase` tables, and optionally imports every CSV.
- `tool/gen_model_from_csv.py` creates one SQLAlchemy model per CSV. Tables with an `id` column use `id` as primary key; tables without `id` currently use all columns as a composite primary key.
- `tool/gen_dao_from_csv.py` creates one CSV import DAO per generated model. Empty CSV values are converted to stable defaults for generated NOT NULL columns: integer `0`, boolean `False`, text `""`.
- If import correctness depends on true SQL NULL rather than default sentinels, fix the model generator's primary-key strategy before changing DAO import conversion.
- Materialized views are managed through `pokeop.infra.views`, not through `Base.metadata.create_all()`. Use `tool/manage_materialized_views.py` or `init_db(..., create_materialized_views=True/recreate_materialized_views=True/refresh_materialized_views=True)`.

## View Strategy

For cross-generation battle data, build views around `version_group_id` first and derive `generation_id` from `version_groups`. This matches PokeAPI move learnsets, move changelogs, machines, held items, and game-version data better than a single hard-coded generation or game.

Read `references/pokeop-data-views.md` when implementing or reviewing views, repositories, services, or damage-calculation data fetches.

Current materialized views live under schema `poke_champion` and are generated from SQL files in `pokeop/infra/views/sql/poke_champion/`. They are Pokemon Champion rule projections over raw CSV data, with `ruleset_id`, `generation_id`, and `version_group_id` columns preserved so later generations/rulesets can follow the same shape.

## Validation

For narrow data-generation changes:

```bash
python3 tool/gen_model_from_csv.py pokeop/data pokeop/model/poke_raw
python3 tool/gen_dao_from_csv.py pokeop/data pokeop/model/poke_raw pokeop/dao/poke_raw
python3 -m py_compile tool/gen_model_from_csv.py tool/gen_dao_from_csv.py
```

For application behavior, run the smallest relevant pytest target first:

```bash
pytest tests
```
