#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pokeop.persistence.bootstrap import init_db
from pokeop.persistence.views import (
    create_materialized_views,
    drop_materialized_views,
    recreate_materialized_views,
    refresh_materialized_views,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage PokemonBattleInference materialized views.")
    parser.add_argument(
        "action",
        choices=("create", "drop", "recreate", "refresh"),
        help="Materialized-view action to run.",
    )
    parser.add_argument(
        "--import-csv",
        action="store_true",
        help="Import raw pokeop/assets_data CSV before managing materialized views.",
    )
    parser.add_argument(
        "--force-import",
        action="store_true",
        help="Force raw CSV import marker check when --import-csv is used.",
    )
    parser.add_argument(
        "--concurrently",
        action="store_true",
        help="Use REFRESH MATERIALIZED VIEW CONCURRENTLY for refresh action.",
    )
    args = parser.parse_args()

    init_db(
        create_tables=True,
        import_csv=args.import_csv,
        force_import=args.force_import,
    )

    if args.action == "create":
        create_materialized_views()
    elif args.action == "drop":
        drop_materialized_views()
    elif args.action == "recreate":
        recreate_materialized_views()
    elif args.action == "refresh":
        refresh_materialized_views(concurrently=args.concurrently)


if __name__ == "__main__":
    main()
