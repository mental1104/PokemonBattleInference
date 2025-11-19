import logging
from collections import defaultdict
from typing import Dict, Generator, Iterable, List, Tuple

from mental1104 import iterator_csv

from pokemon_battle_inference.domain.models.pokemon import PokemonCreate
from pokemon_battle_inference.infrastructure.db import open_session, startup
from pokemon_battle_inference.infrastructure.db.models import pokemon  # noqa: F401
from pokemon_battle_inference.infrastructure.db.models.pokemon import Pokemon
from scripts import CONFIG_PATH

# Column order definition for stats tables so downstream code can stay agnostic to CSV order
STAT_FIELDS: Tuple[str, ...] = (
    "hp",
    "attack",
    "defense",
    "special_attack",
    "special_defense",
    "speed",
)
# Mapping from the CSV stat id (1-6) to human readable field name
STAT_ID_TO_FIELD: Dict[str, str] = {
    str(index): field for index, field in enumerate(STAT_FIELDS, start=1)
}

STATS_FILE = CONFIG_PATH / "pokemon_stats.csv"
NAME_FILE = CONFIG_PATH / "pokemon.csv"
TYPE_FILE = CONFIG_PATH / "type" / "pokemon_types.csv"
MOVE_FILE = CONFIG_PATH / "move" / "pokemon_moves.csv"
ABILITY_FILE = CONFIG_PATH / "ability" / "pokemon_abilities.csv"


def _empty_stats() -> Dict[str, int]:
    return {field: 0 for field in STAT_FIELDS}


@iterator_csv(has_header=True)
def load_pokemon_stats(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    """Aggregate the six stat rows per Pokémon into a single dictionary keyed by stat name."""
    grouped_stats: Dict[str, Dict[str, int]] = defaultdict(_empty_stats)
    for row in rows:
        pokemon_id = row["pokemon_id"]
        stat_key = STAT_ID_TO_FIELD.get(row["stat_id"])
        if not stat_key:
            continue
        grouped_stats[pokemon_id][stat_key] = int(row["base_stat"])
    return {pokemon_id: dict(stats) for pokemon_id, stats in grouped_stats.items()}


@iterator_csv(has_header=True)
def load_pokemon_names(rows: Iterable[Dict[str, str]]) -> Dict[str, str]:
    """Create an `id -> identifier` lookup table for Pokémon names."""
    return {row["id"]: row["identifier"] for row in rows}


@iterator_csv(has_header=True)
def load_pokemon_types(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    """Collect each Pokémon's type slots (type_1/type_2) in a dictionary."""
    pokemon_types: Dict[str, Dict[str, int]] = defaultdict(dict)
    slot_to_field = {"1": "type_1", "2": "type_2"}
    for row in rows:
        slot_field = slot_to_field.get(row["slot"])
        if not slot_field:
            continue
        pokemon_types[row["pokemon_id"]][slot_field] = int(row["type_id"])
    return {pokemon_id: dict(types) for pokemon_id, types in pokemon_types.items()}


@iterator_csv(has_header=True)
def load_move_pool(rows: Iterable[Dict[str, str]]) -> Dict[str, List[str]]:
    """Build a move id list per Pokémon."""
    pokemon_moves: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        pokemon_moves[row["pokemon_id"]].append(row["move_id"])
    return {pokemon_id: moves for pokemon_id, moves in pokemon_moves.items()}


@iterator_csv(has_header=True)
def load_ability_pool(rows: Iterable[Dict[str, str]]) -> Dict[str, List[str]]:
    """Build an ability id list per Pokémon."""
    pokemon_abilities: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        pokemon_abilities[row["pokemon_id"]].append(row["ability_id"])
    return {pokemon_id: abilities for pokemon_id, abilities in pokemon_abilities.items()}


def iter_pokemon_payloads() -> Generator[Tuple[str, Dict[str, object]], None, None]:
    """Yield `(pokemon_id, payload)` tuples ready to instantiate `PokemonCreate` models."""
    stats_map = load_pokemon_stats(STATS_FILE)
    name_map = load_pokemon_names(NAME_FILE)
    type_map = load_pokemon_types(TYPE_FILE)
    move_map = load_move_pool(MOVE_FILE)
    ability_map = load_ability_pool(ABILITY_FILE)

    for pokemon_id, stats in stats_map.items():
        payload = dict(stats)
        payload["name"] = name_map.get(pokemon_id, "")
        payload.update(type_map.get(pokemon_id, {}))
        payload["move_ids"] = move_map.get(pokemon_id, [])
        payload["ability"] = ability_map.get(pokemon_id, [])
        yield pokemon_id, payload


class InitPokemon:
    @classmethod
    def init(cls) -> None:
        """Materialize payloads and persist them with SQLAlchemy models."""
        payloads = list(iter_pokemon_payloads())
        with open_session():
            logging.info("准备写入 %s 条宝可梦数据", len(payloads))
            for pokemon_id, payload in payloads:
                single_pokemon = {"id": int(pokemon_id)}
                single_pokemon.update(payload)
                pokemon_create = PokemonCreate(**single_pokemon)
                logging.info("写入宝可梦 #%s", pokemon_id)
                Pokemon.create(pokemon_create)


def main():
    logging.basicConfig(
        level=getattr(logging, "INFO"),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
        " %(message)s",
    )
    startup()
    InitPokemon.init()


if __name__ == "__main__":
    main()
