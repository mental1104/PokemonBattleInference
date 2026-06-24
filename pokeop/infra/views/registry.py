from __future__ import annotations

from typing import Sequence

from pokeop.infra.views.materialized import (
    MaterializedView,
    create_all,
    drop_all,
    recreate_all,
    refresh_all,
)


CHAMPION_SCHEMA = "poke_champion"


MATERIALIZED_VIEWS: Sequence[MaterializedView] = (
    MaterializedView(
        schema=CHAMPION_SCHEMA,
        name="ruleset_context_mv",
        select_sql="poke_champion/ruleset_context.sql",
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS ruleset_context_mv_pk "
            "ON poke_champion.ruleset_context_mv (ruleset_id)",
        ),
        comment="Pokemon Champion ruleset context: generation 9, scarlet-violet learnsets, zh-Hans names.",
    ),
    MaterializedView(
        schema=CHAMPION_SCHEMA,
        name="pokemon_profile_mv",
        select_sql="poke_champion/pokemon_profile.sql",
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS pokemon_profile_mv_pk "
            "ON poke_champion.pokemon_profile_mv (pokemon_id)",
            "CREATE INDEX IF NOT EXISTS pokemon_profile_mv_identifier_idx "
            "ON poke_champion.pokemon_profile_mv (pokemon_identifier)",
            "CREATE INDEX IF NOT EXISTS pokemon_profile_mv_type_1_idx "
            "ON poke_champion.pokemon_profile_mv (type_1_id)",
            "CREATE INDEX IF NOT EXISTS pokemon_profile_mv_type_2_idx "
            "ON poke_champion.pokemon_profile_mv (type_2_id)",
            "CREATE INDEX IF NOT EXISTS pokemon_profile_mv_ability_ids_gin "
            "ON poke_champion.pokemon_profile_mv USING gin (ability_ids)",
        ),
        comment="Pokemon Champion code-facing Pokemon stats, typing, forms, and abilities.",
    ),
    MaterializedView(
        schema=CHAMPION_SCHEMA,
        name="move_profile_mv",
        select_sql="poke_champion/move_profile.sql",
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS move_profile_mv_pk "
            "ON poke_champion.move_profile_mv (move_id)",
            "CREATE INDEX IF NOT EXISTS move_profile_mv_identifier_idx "
            "ON poke_champion.move_profile_mv (move_identifier)",
            "CREATE INDEX IF NOT EXISTS move_profile_mv_type_idx "
            "ON poke_champion.move_profile_mv (type_id)",
            "CREATE INDEX IF NOT EXISTS move_profile_mv_damage_class_idx "
            "ON poke_champion.move_profile_mv (damage_class_id)",
        ),
        comment="Pokemon Champion code-facing move metadata with version-aware changelog overlay.",
    ),
    MaterializedView(
        schema=CHAMPION_SCHEMA,
        name="type_efficacy_mv",
        select_sql="poke_champion/type_efficacy.sql",
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS type_efficacy_mv_pk "
            "ON poke_champion.type_efficacy_mv (damage_type_id, target_type_id)",
        ),
        comment="Pokemon Champion type chart for damage calculation.",
    ),
    MaterializedView(
        schema=CHAMPION_SCHEMA,
        name="pokemon_learnset_mv",
        select_sql="poke_champion/pokemon_learnset.sql",
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS pokemon_learnset_mv_pk "
            "ON poke_champion.pokemon_learnset_mv "
            "(pokemon_id, move_id, pokemon_move_method_id, level, learn_order, mastery)",
            "CREATE INDEX IF NOT EXISTS pokemon_learnset_mv_pokemon_idx "
            "ON poke_champion.pokemon_learnset_mv (pokemon_id)",
            "CREATE INDEX IF NOT EXISTS pokemon_learnset_mv_move_idx "
            "ON poke_champion.pokemon_learnset_mv (move_id)",
            "CREATE INDEX IF NOT EXISTS pokemon_learnset_mv_method_idx "
            "ON poke_champion.pokemon_learnset_mv (move_method_identifier)",
        ),
        comment="Pokemon Champion learnable moves, one row per Pokemon/move/method/level entry.",
    ),
    MaterializedView(
        schema=CHAMPION_SCHEMA,
        name="pokemon_catalog_zh_mv",
        select_sql="poke_champion/pokemon_catalog_zh.sql",
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS pokemon_catalog_zh_mv_pk "
            "ON poke_champion.pokemon_catalog_zh_mv (pokemon_id)",
            "CREATE INDEX IF NOT EXISTS pokemon_catalog_zh_mv_moves_gin "
            "ON poke_champion.pokemon_catalog_zh_mv USING gin (move_names)",
            "CREATE INDEX IF NOT EXISTS pokemon_catalog_zh_mv_abilities_gin "
            "ON poke_champion.pokemon_catalog_zh_mv USING gin (ability_names)",
        ),
        comment="Pokemon Champion zh-Hans catalog view for manual SQL analysis.",
    ),
)


def create_materialized_views() -> None:
    create_all(MATERIALIZED_VIEWS)


def drop_materialized_views() -> None:
    drop_all(MATERIALIZED_VIEWS)


def recreate_materialized_views() -> None:
    recreate_all(MATERIALIZED_VIEWS)


def refresh_materialized_views(*, concurrently: bool = False) -> None:
    refresh_all(MATERIALIZED_VIEWS, concurrently=concurrently)

