import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, Generator, Iterable, List, Tuple

from mental1104 import iterator_csv

from pokemon_battle_inference.domain.models.pokemon import PokemonCreate
from pokemon_battle_inference.infrastructure.db import open_session, startup
from pokemon_battle_inference.infrastructure.db.models import pokemon  # noqa: F401
from pokemon_battle_inference.infrastructure.db.models.pokemon import Pokemon
from pokemon_battle_inference.init import CONFIG_PATH
from pokemon_battle_inference.schema.pokemon import (
    STAT_FIELDS,
    STAT_ID_TO_FIELD,
    TYPE_SLOT_TO_FIELD,
)

class InitPokemon:
    FILES: Dict[str, Path] = {
        "stats": CONFIG_PATH / "pokemon_stats.csv",
        "names": CONFIG_PATH / "pokemon.csv",
        "types": CONFIG_PATH / "type" / "pokemon_types.csv",
        "moves": CONFIG_PATH / "move" / "pokemon_moves.csv",
        "abilities": CONFIG_PATH / "ability" / "pokemon_abilities.csv",
    }

    @staticmethod
    def _empty_stats() -> Dict[str, int]:
        """
        作用：生成一份包含全部种族值字段的默认字典。
        输入：无。
        输出：Dict[str, int]，键为 STAT_FIELDS 中的字段名，值为 0。
        """
        return {field: 0 for field in STAT_FIELDS}

    @staticmethod
    @iterator_csv(has_header=True)
    def load_pokemon_stats(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
        """
        作用：加载宝可梦基础种族值，并按宝可梦 ID 聚合成字典。
        输入：rows（Iterable[Dict[str, str]]），pokemon_stats.csv 内容。
        输出：Dict[str, Dict[str, int]]，外层键为 pokemon_id，内层键为种族值字段名。
        """
        grouped_stats: Dict[str, Dict[str, int]] = defaultdict(InitPokemon._empty_stats)
        for row in rows:
            pokemon_id = row["pokemon_id"]
            stat_key = STAT_ID_TO_FIELD.get(row["stat_id"])
            if not stat_key:
                continue
            grouped_stats[pokemon_id][stat_key] = int(row["base_stat"])
        return {pokemon_id: dict(stats) for pokemon_id, stats in grouped_stats.items()}

    @staticmethod
    @iterator_csv(has_header=True)
    def load_pokemon_names(rows: Iterable[Dict[str, str]]) -> Dict[str, str]:
        """
        作用：加载宝可梦名称映射表。
        输入：rows（Iterable[Dict[str, str]]），pokemon.csv 内容。
        输出：Dict[str, str]，键为 pokemon_id，值为 identifier。
        """
        return {row["id"]: row["identifier"] for row in rows}

    @staticmethod
    @iterator_csv(has_header=True)
    def load_pokemon_types(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
        """
        作用：加载宝可梦属性槽位（type_1/type_2）映射。
        输入：rows（Iterable[Dict[str, str]]），pokemon_types.csv 内容。
        输出：Dict[str, Dict[str, int]]，外层键为 pokemon_id，内层键为 type_1/type_2。
        """
        pokemon_types: Dict[str, Dict[str, int]] = defaultdict(dict)
        for row in rows:
            slot_field = TYPE_SLOT_TO_FIELD.get(row["slot"])
            if not slot_field:
                continue
            pokemon_types[row["pokemon_id"]][slot_field] = int(row["type_id"])
        return {pokemon_id: dict(types) for pokemon_id, types in pokemon_types.items()}

    @staticmethod
    @iterator_csv(has_header=True)
    def load_move_pool(rows: Iterable[Dict[str, str]]) -> Dict[str, List[str]]:
        """
        作用：加载宝可梦技能池（move_ids）。
        输入：rows（Iterable[Dict[str, str]]），pokemon_moves.csv 内容。
        输出：Dict[str, List[str]]，键为 pokemon_id，值为 move_id 列表。
        """
        grouped: Dict[str, List[str]] = defaultdict(list)
        for row in rows:
            grouped[row["pokemon_id"]].append(row["move_id"])
        return {pokemon_id: values for pokemon_id, values in grouped.items()}

    @staticmethod
    @iterator_csv(has_header=True)
    def load_ability_pool(rows: Iterable[Dict[str, str]]) -> Dict[str, List[str]]:
        """
        作用：加载宝可梦特性池（ability）。
        输入：rows（Iterable[Dict[str, str]]），pokemon_abilities.csv 内容。
        输出：Dict[str, List[str]]，键为 pokemon_id，值为 ability_id 列表。
        """
        grouped: Dict[str, List[str]] = defaultdict(list)
        for row in rows:
            grouped[row["pokemon_id"]].append(row["ability_id"])
        return {pokemon_id: values for pokemon_id, values in grouped.items()}

    @classmethod
    def iter_pokemon_payloads(cls) -> Generator[Tuple[str, Dict[str, object]], None, None]:
        """
        作用：整合多张 CSV 的信息，生成可写入数据库的 payload。
        输入：无（使用类上的 FILES 路径配置）。
        输出：Generator[Tuple[str, Dict[str, object]]]，每项为 (pokemon_id, payload)。
        """
        stats_map = cls.load_pokemon_stats(cls.FILES["stats"]) # type: ignore
        name_map = cls.load_pokemon_names(cls.FILES["names"]) # type: ignore
        type_map = cls.load_pokemon_types(cls.FILES["types"]) # type: ignore
        move_map = cls.load_move_pool(cls.FILES["moves"]) # type: ignore
        ability_map = cls.load_ability_pool(cls.FILES["abilities"]) # type: ignore

        for pokemon_id, stats in stats_map.items():
            payload: Dict[str, object] = dict(stats)
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
