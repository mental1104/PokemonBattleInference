import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, Iterable, Iterator, List, Tuple

from pokemon_battle_inference.domain.models.pokemon import PokemonCreate
from pokemon_battle_inference.infrastructure.db import open_session, startup
from pokemon_battle_inference.infrastructure.db.models import pokemon  # noqa: F401
from pokemon_battle_inference.infrastructure.db.models.pokemon import Pokemon
from pokemon_battle_inference.init import CONFIG_PATH

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
TYPE_SLOT_TO_FIELD = {"1": "type_1", "2": "type_2"}

CsvRow = Dict[str, str]
PokemonPayload = Dict[str, object]


@dataclass(frozen=True)
class PokemonCSVPaths:
    stats: Path
    names: Path
    types: Path
    moves: Path
    abilities: Path


DEFAULT_POKEMON_FILES = PokemonCSVPaths(
    stats=CONFIG_PATH / "pokemon_stats.csv",
    names=CONFIG_PATH / "pokemon.csv",
    types=CONFIG_PATH / "type" / "pokemon_types.csv",
    moves=CONFIG_PATH / "move" / "pokemon_moves.csv",
    abilities=CONFIG_PATH / "ability" / "pokemon_abilities.csv",
)


class InitPokemon:
    FILES: PokemonCSVPaths = DEFAULT_POKEMON_FILES

    @staticmethod
    def _empty_stats() -> Dict[str, int]:
        """
        作用：生成一份包含全部种族值字段的默认字典。
        输入：无。
        输出：Dict[str, int]，键为 STAT_FIELDS 中的字段名，值为 0。
        """
        return {field: 0 for field in STAT_FIELDS}

    @staticmethod
    def _iter_csv_rows(file_path: Path | str) -> Iterator[CsvRow]:
        """
        作用：读取 CSV 文件并按行产出字典形式的数据。
        输入：file_path（Path | str），CSV 文件路径。
        输出：Iterator[CsvRow]，每个元素为一行的字典（列名 -> 字符串值）。
        """
        path = Path(file_path)
        with path.open(encoding="utf-8", newline="") as csv_file:
            yield from csv.DictReader(csv_file)

    @classmethod
    def load_pokemon_stats(cls, file_path: Path | str) -> Dict[str, Dict[str, int]]:
        """
        作用：加载宝可梦基础种族值，并按宝可梦 ID 聚合成字典。
        输入：file_path（Path | str），pokemon_stats.csv 路径。
        输出：Dict[str, Dict[str, int]]，外层键为 pokemon_id，内层键为种族值字段名。
        """
        return cls._parse_pokemon_stats(cls._iter_csv_rows(file_path))

    @staticmethod
    def _parse_pokemon_stats(rows: Iterable[CsvRow]) -> Dict[str, Dict[str, int]]:
        """
        作用：将同一只宝可梦的六条种族值记录合并为一个字典。
        输入：rows（Iterable[CsvRow]），包含 pokemon_id/stat_id/base_stat 的行数据。
        输出：Dict[str, Dict[str, int]]，外层键为 pokemon_id，内层为种族值字段名 -> 数值。
        """
        grouped_stats: Dict[str, Dict[str, int]] = defaultdict(InitPokemon._empty_stats)
        for row in rows:
            pokemon_id = row["pokemon_id"]
            stat_key = STAT_ID_TO_FIELD.get(row["stat_id"])
            if not stat_key:
                continue
            grouped_stats[pokemon_id][stat_key] = int(row["base_stat"])
        return {pokemon_id: dict(stats) for pokemon_id, stats in grouped_stats.items()}

    @classmethod
    def load_pokemon_names(cls, file_path: Path | str) -> Dict[str, str]:
        """
        作用：加载宝可梦名称映射表。
        输入：file_path（Path | str），pokemon.csv 路径。
        输出：Dict[str, str]，键为 pokemon_id，值为 identifier。
        """
        return cls._parse_pokemon_names(cls._iter_csv_rows(file_path))

    @staticmethod
    def _parse_pokemon_names(rows: Iterable[CsvRow]) -> Dict[str, str]:
        """
        作用：从行数据中构建 id -> identifier 的映射。
        输入：rows（Iterable[CsvRow]），包含 id/identifier 的行数据。
        输出：Dict[str, str]，键为 id，值为 identifier。
        """
        return {row["id"]: row["identifier"] for row in rows}

    @classmethod
    def load_pokemon_types(cls, file_path: Path | str) -> Dict[str, Dict[str, int]]:
        """
        作用：加载宝可梦属性槽位（type_1/type_2）映射。
        输入：file_path（Path | str），pokemon_types.csv 路径。
        输出：Dict[str, Dict[str, int]]，外层键为 pokemon_id，内层键为 type_1/type_2。
        """
        return cls._parse_pokemon_types(cls._iter_csv_rows(file_path))

    @staticmethod
    def _parse_pokemon_types(rows: Iterable[CsvRow]) -> Dict[str, Dict[str, int]]:
        """
        作用：解析属性表并组装每只宝可梦的 type_1/type_2。
        输入：rows（Iterable[CsvRow]），包含 pokemon_id/type_id/slot 的行数据。
        输出：Dict[str, Dict[str, int]]，外层键为 pokemon_id，内层键为 type_1/type_2。
        """
        pokemon_types: Dict[str, Dict[str, int]] = defaultdict(dict)
        for row in rows:
            slot_field = TYPE_SLOT_TO_FIELD.get(row["slot"])
            if not slot_field:
                continue
            pokemon_types[row["pokemon_id"]][slot_field] = int(row["type_id"])
        return {pokemon_id: dict(types) for pokemon_id, types in pokemon_types.items()}

    @classmethod
    def load_move_pool(cls, file_path: Path | str) -> Dict[str, List[str]]:
        """
        作用：加载宝可梦技能池（move_ids）。
        输入：file_path（Path | str），pokemon_moves.csv 路径。
        输出：Dict[str, List[str]]，键为 pokemon_id，值为 move_id 列表。
        """
        return cls._parse_list_map(cls._iter_csv_rows(file_path), "pokemon_id", "move_id")

    @classmethod
    def load_ability_pool(cls, file_path: Path | str) -> Dict[str, List[str]]:
        """
        作用：加载宝可梦特性池（ability）。
        输入：file_path（Path | str），pokemon_abilities.csv 路径。
        输出：Dict[str, List[str]]，键为 pokemon_id，值为 ability_id 列表。
        """
        return cls._parse_list_map(
            cls._iter_csv_rows(file_path),
            "pokemon_id",
            "ability_id",
        )

    @staticmethod
    def _parse_list_map(
        rows: Iterable[CsvRow],
        key_field: str,
        value_field: str,
    ) -> Dict[str, List[str]]:
        """
        作用：按指定字段分组，聚合为 key -> [value] 的映射。
        输入：rows（Iterable[CsvRow]），key_field（分组键字段名），value_field（聚合值字段名）。
        输出：Dict[str, List[str]]，键为 key_field 值，值为 value_field 列表。
        """
        grouped: Dict[str, List[str]] = defaultdict(list)
        for row in rows:
            grouped[row[key_field]].append(row[value_field])
        return {pokemon_id: values for pokemon_id, values in grouped.items()}

    @classmethod
    def iter_pokemon_payloads(cls) -> Generator[Tuple[str, PokemonPayload], None, None]:
        """
        作用：整合多张 CSV 的信息，生成可写入数据库的 payload。
        输入：无（使用类上的 FILES 路径配置）。
        输出：Generator[Tuple[str, PokemonPayload]]，每项为 (pokemon_id, payload)。
        """
        stats_map = cls.load_pokemon_stats(cls.FILES.stats)
        name_map = cls.load_pokemon_names(cls.FILES.names)
        type_map = cls.load_pokemon_types(cls.FILES.types)
        move_map = cls.load_move_pool(cls.FILES.moves)
        ability_map = cls.load_ability_pool(cls.FILES.abilities)

        for pokemon_id, stats in stats_map.items():
            payload: PokemonPayload = dict(stats)
            payload["name"] = name_map.get(pokemon_id, "")
            payload.update(type_map.get(pokemon_id, {}))
            payload["move_ids"] = move_map.get(pokemon_id, [])
            payload["ability"] = ability_map.get(pokemon_id, [])
            yield pokemon_id, payload

    @classmethod
    def init(cls) -> None:
        """
        作用：读取 CSV 并写入数据库表 pokemon。
        输入：无（使用类上的 FILES 路径配置）。
        输出：无。通过 SQLAlchemy 持久化 PokemonCreate。
        """
        payloads = list(cls.iter_pokemon_payloads())
        with open_session():
            logging.info("准备写入 %s 条宝可梦数据", len(payloads))
            for pokemon_id, payload in payloads:
                single_pokemon = {"id": int(pokemon_id)}
                single_pokemon.update(payload)
                pokemon_create = PokemonCreate(**single_pokemon)
                logging.info("写入宝可梦 #%s", pokemon_id)
                Pokemon.create(pokemon_create)


def main():
    """
    作用：脚本入口，初始化日志与数据库并执行导入流程。
    输入：无。
    输出：无。
    """
    logging.basicConfig(
        level=getattr(logging, "INFO"),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
        " %(message)s",
    )
    startup()
    InitPokemon.init()


if __name__ == "__main__":
    main()
