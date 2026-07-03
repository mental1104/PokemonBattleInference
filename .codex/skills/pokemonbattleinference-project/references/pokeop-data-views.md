# pokeop Raw Data And View Strategy

Use this reference when building views or query services over `poke_raw`.

## Current CSV Shape

`pokeop/assets_data` points at PokeAPI `data/v2/csv`. The raw import currently covers 177 CSV tables.

Key battle tables:

- Version axis: `generations`, `version_groups`, `versions`
- Pokemon identity and forms: `pokemon`, `pokemon_species`, `pokemon_forms`, `pokemon_form_types`
- Stats and typing: `pokemon_stats`, `stats`, `pokemon_types`, `pokemon_types_past`
- Move learnsets: `pokemon_moves`, `pokemon_move_methods`, `version_group_pokemon_move_methods`
- Move data: `moves`, `move_changelog`, `move_damage_classes`, `machines`
- Type chart: `types`, `type_efficacy`, `type_efficacy_past`
- Abilities and items: `abilities`, `pokemon_abilities`, `pokemon_abilities_past`, `items`, `pokemon_items`

Important row counts from the current CSV snapshot:

- `version_groups`: 31 rows, generations 1-9
- `pokemon`: 1350 rows
- `pokemon_forms`: 1527 rows
- `pokemon_stats`: 8100 rows
- `pokemon_moves`: 609934 rows
- `moves`: 937 rows
- `move_changelog`: 198 rows
- `type_efficacy`: 324 rows
- `type_efficacy_past`: 6 rows

## Design Principles

1. Make `version_group_id` the main query key.
   PokeAPI learnsets and move changes are stored by version group, not just generation. A Pokemon Champion-specific team should select a version group, then filter Pokemon and moves above the generic views.

2. Keep reusable views game-neutral.
   Prefer names like `v_pokemon_battle_profile_by_version_group`, `v_pokemon_learnable_moves_by_version_group`, and `v_move_battle_data_by_version_group`; avoid names or filters tied to Pokemon Champion.

3. Separate durable raw import from derived read models.
   Raw generated ORM models mirror CSV tables. Views can denormalize names, stats, type slots, move metadata, and learn methods for damage calculation.

4. Resolve historical data in views.
   In PokeAPI CSVs, `*_past.generation_id` behaves as the last generation where an old value applied. For a target generation, choose the nearest past row whose `generation_id` is greater than or equal to the target generation; otherwise use the current table. `move_changelog.changed_in_version_group_id` stores old values from before that version group changed the move.

5. Preserve identifiers and numeric IDs.
   Include both ids and `identifier` columns in read views. Domain code can keep enum/string conversion separate from persistence.

## Recommended View Layers

## Materialized View Management

Use `pokeop.persistence.views` as the only code path for derived materialized views:

- Define each view in `pokeop/persistence/views/registry.py`.
- Keep the SELECT body in `pokeop/persistence/views/sql/<schema>/<view>.sql`.
- Let the registry own schema names, materialized-view names, indexes, comments, and execution order.
- Do not add materialized-view models to `RawBase` or call `Base.metadata.create_all()` for views.

Operational entrypoint:

```bash
python3 tool/manage_materialized_views.py recreate
python3 tool/manage_materialized_views.py refresh
```

When raw CSV tables need to be created/imported first:

```bash
python3 tool/manage_materialized_views.py recreate --import-csv
```

Code entrypoint:

```python
from pokeop.persistence.bootstrap import init_db

init_db(create_tables=True, import_csv=True, recreate_materialized_views=True)
```

The current first ruleset schema is `poke_champion`. These views use Pokemon Champion rules (`version_group_id = 25`, `generation_id = 9`, `language_id = 12`) but preserve `ruleset_id`, `version_group_id`, and `generation_id` columns. Future first-to-ninth-generation views should use the same column shape, either by adding new ruleset rows or by creating a separate schema with the same view names.

### `v_version_group_context`

One row per version group:

- `version_group_id`
- `version_group_identifier`
- `generation_id`
- `generation_identifier`
- `version_group_order`

Use this as the anchor for all version-aware views.

### `v_pokemon_base_stats`

One row per `pokemon_id`, pivoting stat rows into damage-calculation columns:

- `pokemon_id`
- `hp`
- `attack`
- `defense`
- `special_attack`
- `special_defense`
- `speed`

Source tables: `pokemon_stats`, `stats`.

### `v_pokemon_types_by_generation`

One row per `generation_id`, `pokemon_id`, with type slots:

- Start from current `pokemon_types`.
- Override each slot with the nearest `pokemon_types_past` row where `past.generation_id >= target_generation_id`.
- Keep slot columns as `type_1_id`, `type_2_id`, plus identifiers.

Do not flatten this only by Pokemon. Clefairy/Clefable have `pokemon_types_past.generation_id = 5` for normal type, which applies to generations 1-5 before fairy was introduced. Magnemite/Magneton have `generation_id = 1` for pure electric before steel was introduced.

### `v_pokemon_battle_profile_by_version_group`

One row per `version_group_id`, `pokemon_id`:

- Version context fields
- Pokemon id/identifier/species id
- Default/battle form identifiers when available
- Base stats from `v_pokemon_base_stats`
- Effective type slots from `v_pokemon_types_by_generation`
- Optional aggregated ability ids by generation

For abilities, apply the same nearest-past-row rule using `pokemon_abilities_past`. After CSV import, empty `ability_id` values become `0`; treat `0` as "no ability in this historical slot", not as a real ability id.

This is the generic replacement for old CSV hand-merge payloads.

### `v_move_battle_data_by_version_group`

One row per `version_group_id`, `move_id`:

- Move id/identifier
- Effective type id
- Effective power, pp, accuracy, priority, target, effect, effect chance
- Damage class id/identifier

Use `moves` as the latest-value base. For each mutable column, overlay the nearest non-empty `move_changelog` value whose `changed_in_version_group_id` belongs to a version group with `order > target_version_group_order`.

Example: `karate-chop` is fighting in current `moves`, but `move_changelog` has an old normal type at `gold-silver`. For `red-blue`, the nearest future changelog row supplies normal; for `gold-silver` and later, the current fighting value applies unless another future old value is relevant to the target.

This view matters because move type/power/accuracy changed across generations, and damage calculation must not use the latest value for older games.

### `v_pokemon_learnable_moves_by_version_group`

One row per learnable move entry:

- `version_group_id`
- `generation_id`
- `pokemon_id`
- `move_id`
- `move_identifier`
- `pokemon_move_method_id`
- `move_method_identifier`
- `level`
- `order`
- `mastery`
- Effective move battle fields from `v_move_battle_data_by_version_group`

Source table: `pokemon_moves`. Join `pokemon_move_methods` for method names. Keep all methods; let service code choose `level-up`, `machine`, `tutor`, egg moves, or form-change moves based on the request.

### `v_type_efficacy_by_generation`

One row per `generation_id`, attacking type, defending type:

- Start from current `type_efficacy`.
- Override each type pair with the nearest `type_efficacy_past` row where `past.generation_id >= target_generation_id`.
- Exclude types that did not exist in the target generation unless a caller explicitly wants synthetic compatibility rows.

Damage calculation should read this by `generation_id` rather than using a hard-coded enum matrix.

## Pokemon Champion Integration Boundary

Model Pokemon Champion as caller data, not raw persistence:

- Store or pass the current Pokemon roster with `pokemon_id` or `pokemon_identifier`.
- Store or pass known moves by `move_id` or `move_identifier`.
- Include a `version_group_id` or game profile key for the ruleset.
- Query generic views with those filters.

This keeps future first-to-ninth-generation support possible and prevents Pokemon Champion-specific assumptions from leaking into generated raw tables.

## Known Risks To Address Before Full Import Reliance

- Tables without `id` are generated with every column as a composite primary key. This is a pragmatic ORM identity workaround, not a faithful schema. It forces nullable CSV fields into NOT NULL columns.
- The DAO generator currently converts empty CSV values to default sentinels for those generated NOT NULL columns. This keeps imports running but can blur the difference between unknown and actual `0`/empty string.
- If a future task needs exact raw null semantics, change the model generator to create a synthetic surrogate primary key or table-specific primary-key rules before changing the DAO defaults.
