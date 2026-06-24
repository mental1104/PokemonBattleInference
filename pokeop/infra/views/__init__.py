"""Materialized-view management for derived battle read models."""

from pokeop.infra.views.registry import (
    MATERIALIZED_VIEWS,
    create_materialized_views,
    drop_materialized_views,
    recreate_materialized_views,
    refresh_materialized_views,
)

__all__ = [
    "MATERIALIZED_VIEWS",
    "create_materialized_views",
    "drop_materialized_views",
    "recreate_materialized_views",
    "refresh_materialized_views",
]

