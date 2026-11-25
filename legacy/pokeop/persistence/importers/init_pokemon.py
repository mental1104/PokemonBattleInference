from __future__ import annotations

import csv
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from pokeop.domain.models.pokemon import PokemonCreate


DATA_DIR = Path(__file__).resolve().parents[2] / "assets_data"

STAT_FIELDS = (
    "hp",
    "attack",
    "defense",
    "special_attack",
    "special_defense",
    "speed",
)

STAT_ID_TO_FIELD = {
    "1": "hp",
    "2": "attack",
    "3": "defense",
    "4": "special_attack",
    "5": "special_defense",
    "6": "speed",
}


@contextmanager
def open_session() -> Iterator[None]:
    yield None


class Pokemon:
    @staticmethod
    def create(pokemon_create: PokemonCreate) -> PokemonCreate:
        return pokemon_create


class InitPokemon:
    @staticmethod
    def _empty_stats() -> Dict[str, int]:
        return {field: 0 for field in STAT_FIELDS}

    @staticmethod
    def load_pokemon_stats(csv_path: str | Path) -> Dict[str, Dict[str, int]]:
        result: Dict[str, Dict[str, int]] = {}
        with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                pokemon_id = row["pokemon_id"]
                stat_name = STAT_ID_TO_FIELD.get(row["stat_id"])
                if stat_name is None:
                    continue
                stats = result.setdefault(pokemon_id, InitPokemon._empty_stats())
                stats[stat_name] = int(row["base_stat"])
        return result

    @staticmethod
    def load_pokemon_names(csv_path: str | Path) -> Dict[str, str]:
        result: Dict[str, str] = {}
        with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                result[row["id"]] = row["identifier"]
        return result

    @staticmethod
    def load_pokemon_types(csv_path: str | Path) -> Dict[str, Dict[str, int]]:
        result: Dict[str, Dict[str, int]] = {}
        with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                slot = row["slot"]
                if slot not in {"1", "2"}:
                    continue
                pokemon_id = row["pokemon_id"]
                result.setdefault(pokemon_id, {})[f"type_{slot}"] = int(row["type_id"])
        return result

    @staticmethod
    def load_move_pool(csv_path: str | Path) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                result.setdefault(row["pokemon_id"], []).append(row["move_id"])
        return result

    @staticmethod
    def load_ability_pool(csv_path: str | Path) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                result.setdefault(row["pokemon_id"], []).append(row["ability_id"])
        return result

    @classmethod
    def iter_pokemon_payloads(cls) -> Iterator[Tuple[str, Dict[str, object]]]:
        stats_by_id = cls.load_pokemon_stats(DATA_DIR / "pokemon_stats.csv")
        names_by_id = cls.load_pokemon_names(DATA_DIR / "pokemon.csv")
        types_by_id = cls.load_pokemon_types(DATA_DIR / "pokemon_types.csv")
        moves_by_id = cls.load_move_pool(DATA_DIR / "pokemon_moves.csv")
        abilities_by_id = cls.load_ability_pool(DATA_DIR / "pokemon_abilities.csv")

        for pokemon_id, stats in stats_by_id.items():
            name = names_by_id.get(pokemon_id)
            if name is None:
                continue
            payload: Dict[str, object] = dict(stats)
            payload["name"] = name
            payload.update(types_by_id.get(pokemon_id, {}))
            payload["move_ids"] = moves_by_id.get(pokemon_id, [])
            payload["ability"] = abilities_by_id.get(pokemon_id, [])
            yield pokemon_id, payload

    @classmethod
    def init(cls) -> None:
        with open_session():
            for pokemon_id, payload in cls.iter_pokemon_payloads():
                Pokemon.create(PokemonCreate(id=int(pokemon_id), **payload))
