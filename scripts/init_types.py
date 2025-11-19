import logging
from typing import Dict, Iterable

from mental1104 import iterator_csv

from pokemon_battle_inference.domain.models.types import TypesCreate
from pokemon_battle_inference.infrastructure.db import open_session
from pokemon_battle_inference.infrastructure.db.models.types import Types
from scripts import CONFIG_PATH

TYPE_FILE = CONFIG_PATH / "type" / "types.csv"


@iterator_csv(has_header=True)
def load_type_names(rows: Iterable[Dict[str, str]]) -> Dict[str, str]:
    """Create an `id -> identifier` lookup table for elemental types."""
    return {row["id"]: row["identifier"] for row in rows}


class InitTypes:
    @classmethod
    def init(cls):
        name_map = load_type_names(TYPE_FILE)
        with open_session() as session:
            for key, val in name_map.items():
                single_item = {"id": int(key), "name": val}
                type_create = TypesCreate(**single_item)
                logging.info(type_create)
                Types.create(session, type_create)
