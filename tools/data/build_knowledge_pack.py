"""从固定 PokeAPI CSV 生成首装可用的 SQLite 知识包与校验 manifest，不访问用户数据库。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing
from enum import IntEnum
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator


class _CsvRow(BaseModel):
    """外部 CSV 的声明式投影；未投影列保持在原 CSV，不冒充完整数据库迁移。"""
    model_config = ConfigDict(frozen=True, extra="ignore")

    @field_validator("*", mode="before")
    @classmethod
    def empty_as_null(cls, value: object) -> object:
        """value 为原 CSV 单元格；空字段统一为 null，必填字段仍由具体模型拒绝。"""
        return None if value == "" else value


class PokemonRow(_CsvRow):
    """物种/形态的基础标识与尺寸。"""
    id: int
    identifier: str
    species_id: int
    height: int
    weight: int


class SpeciesRow(_CsvRow):
    """进化关系仅用于派生 can_evolve，保留与能力/伤害计算的边界。"""
    id: int
    evolves_from_species_id: int | None


class SpeciesNameRow(_CsvRow):
    """物种多语言名称。"""
    pokemon_species_id: int
    local_language_id: int
    name: str


class StatRow(_CsvRow):
    """六项种族值源记录。"""
    pokemon_id: int
    stat_id: int
    base_stat: int


class PokemonTypeRow(_CsvRow):
    """属性槽顺序是知识快照的一部分，不重排。"""
    pokemon_id: int
    type_id: int
    slot: int


class PokemonAbilityRow(_CsvRow):
    """特性槽与隐藏标记，不把未知特性映射为无效果。"""
    pokemon_id: int
    ability_id: int
    slot: int
    is_hidden: Literal["0", "1"]


class MoveDamageClass(IntEnum):
    """CSV 中固定的伤害分类编号，仅投影知识，不在这里计算招式规则。"""
    status = 1
    physical = 2
    special = 3


class MoveRow(_CsvRow):
    """招式查询和直接伤害选择需要的原始固定字段；空威力不伪造默认值。"""
    id: int
    identifier: str
    generation_id: int
    type_id: int
    power: int | None
    pp: int | None
    accuracy: int | None
    priority: int
    target_id: int
    damage_class_id: MoveDamageClass
    effect_id: int | None
    effect_chance: int | None


class MoveNameRow(_CsvRow):
    """招式多语言名称。"""
    move_id: int
    local_language_id: int
    name: str


class TypeRow(_CsvRow):
    """完整属性查询标识，计算是否支持由 Core 明确决定。"""
    id: int
    identifier: str


class TypeNameRow(_CsvRow):
    """属性多语言名称。"""
    type_id: int
    local_language_id: int
    name: str


class NatureRow(_CsvRow):
    """性格改变的两项能力 ID；不在 Swift 中复制性格选择规则。"""
    id: int
    identifier: str
    decreased_stat_id: int
    increased_stat_id: int


class NatureNameRow(_CsvRow):
    """性格多语言名称。"""
    nature_id: int
    local_language_id: int
    name: str


class AbilityRow(_CsvRow):
    """完整特性标识，用于展示与明确支持范围选择。"""
    id: int
    identifier: str


class AbilityNameRow(_CsvRow):
    """特性多语言名称。"""
    ability_id: int
    local_language_id: int
    name: str


class EfficacyRow(_CsvRow):
    """百分制相克知识，直接注入 Core。"""
    damage_type_id: int
    target_type_id: int
    damage_factor: int


class SourceDigest(BaseModel):
    """无私有绝对路径的源文件摘要。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    file: str
    sha256: str


class KnowledgeCounts(BaseModel):
    """知识投影的完整行数合同，不包含独立用户库。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    pokemon: int
    pokemon_stats: int
    pokemon_types: int
    pokemon_abilities: int
    moves: int
    types: int
    natures: int
    abilities: int
    type_efficacy: int


class KnowledgeManifest(BaseModel):
    """每个交付包的版本、源输入和实际 SQLite 字节校验值。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    data_version: str
    source_revision: str
    input_sha256: str
    sqlite_sha256: str
    byte_size: int
    counts: KnowledgeCounts
    sources: tuple[SourceDigest, ...]


Row = TypeVar("Row", bound=_CsvRow)


class _PackBuilder:
    """拥有本次源记录与摘要；只向调用方明确指定的新构建文件写入。"""
    def __init__(self, source: Path) -> None:
        """source 为只读 CSV 根目录；初始化空摘要清单，不操作输出。"""
        self._source = source
        self._digests: list[SourceDigest] = []

    def _read(self, file: str, model: type[Row]) -> list[Row]:
        """file 为固定 CSV 文件名，model 为其 schema；返回已验证行并登记真实字节摘要。"""
        raw = (self._source / file).read_bytes()
        self._digests.append(SourceDigest(file=file, sha256=hashlib.sha256(raw).hexdigest()))
        return [model.model_validate(row) for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))]

    @staticmethod
    def _name(names: dict[tuple[int, int], str], entity: int, identifier: str) -> str:
        """names 为实体/语言索引，entity 为 ID，identifier 为最终回退；返回简中、英文或原标识。"""
        return names.get((entity, 12), names.get((entity, 9), identifier))

    def populate(self, connection: sqlite3.Connection, revision: str, schema: bytes) -> tuple[str, str]:
        """connection 为本次新库，revision 为固定源提交，schema 为 DDL；写入并返回数据版本/输入摘要。"""
        pokemon = self._read("pokemon.csv", PokemonRow)
        species = self._read("pokemon_species.csv", SpeciesRow)
        species_names = {(row.pokemon_species_id, row.local_language_id): row.name for row in self._read("pokemon_species_names.csv", SpeciesNameRow)}
        stats = self._read("pokemon_stats.csv", StatRow)
        pokemon_types = self._read("pokemon_types.csv", PokemonTypeRow)
        pokemon_abilities = self._read("pokemon_abilities.csv", PokemonAbilityRow)
        moves = self._read("moves.csv", MoveRow)
        move_names = {(row.move_id, row.local_language_id): row.name for row in self._read("move_names.csv", MoveNameRow)}
        types = self._read("types.csv", TypeRow)
        type_names = {(row.type_id, row.local_language_id): row.name for row in self._read("type_names.csv", TypeNameRow)}
        natures = self._read("natures.csv", NatureRow)
        nature_names = {(row.nature_id, row.local_language_id): row.name for row in self._read("nature_names.csv", NatureNameRow)}
        abilities = self._read("abilities.csv", AbilityRow)
        ability_names = {(row.ability_id, row.local_language_id): row.name for row in self._read("ability_names.csv", AbilityNameRow)}
        efficacy = self._read("type_efficacy.csv", EfficacyRow)
        self._digests.append(SourceDigest(file="schema.v1.sql", sha256=hashlib.sha256(schema).hexdigest()))
        input_hash = hashlib.sha256("\n".join(f"{item.file}:{item.sha256}" for item in sorted(self._digests, key=lambda item: item.file)).encode()).hexdigest()
        version = f"pokeapi-{revision[:12]}-{input_hash[:12]}"
        connection.executescript(schema.decode())
        connection.executemany("INSERT INTO metadata VALUES (?,?)", (("schema_version", "1"), ("data_version", version), ("source_revision", revision), ("input_sha256", input_hash)))
        connection.executemany("INSERT INTO types VALUES (?,?,?)", ((row.id, row.identifier, self._name(type_names, row.id, row.identifier)) for row in types))
        connection.executemany("INSERT INTO abilities VALUES (?,?,?)", ((row.id, row.identifier, self._name(ability_names, row.id, row.identifier)) for row in abilities))
        connection.executemany("INSERT INTO natures VALUES (?,?,?,?,?)", ((row.id, row.identifier, self._name(nature_names, row.id, row.identifier), row.decreased_stat_id, row.increased_stat_id) for row in natures))
        evolving = {row.evolves_from_species_id for row in species if row.evolves_from_species_id is not None}
        connection.executemany("INSERT INTO pokemon VALUES (?,?,?,?,?,?,?)", ((row.id, row.species_id, row.identifier, self._name(species_names, row.species_id, row.identifier), row.height, row.weight, int(row.species_id in evolving)) for row in pokemon))
        connection.executemany("INSERT INTO pokemon_stats VALUES (?,?,?)", ((row.pokemon_id, row.stat_id, row.base_stat) for row in stats))
        connection.executemany("INSERT INTO pokemon_types VALUES (?,?,?)", ((row.pokemon_id, row.type_id, row.slot) for row in pokemon_types))
        connection.executemany("INSERT INTO pokemon_abilities VALUES (?,?,?,?)", ((row.pokemon_id, row.ability_id, row.slot, int(row.is_hidden)) for row in pokemon_abilities))
        connection.executemany("INSERT INTO moves VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ((row.id, row.identifier, self._name(move_names, row.id, row.identifier), row.generation_id, row.type_id, row.power, row.pp, row.accuracy, row.priority, row.target_id, row.damage_class_id, row.effect_id, row.effect_chance) for row in moves))
        connection.executemany("INSERT INTO type_efficacy VALUES (?,?,?)", ((row.damage_type_id, row.target_type_id, row.damage_factor) for row in efficacy))
        connection.commit()
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("knowledge pack has broken references")
        if connection.execute("SELECT pokemon_id FROM pokemon_stats GROUP BY pokemon_id HAVING count(*) != 6").fetchone() is not None:
            raise ValueError("pokemon must have all six base stats")
        if connection.execute("SELECT count(*) FROM pokemon_stats").fetchone()[0] != len(pokemon) * 6:
            raise ValueError("pokemon base stat coverage is incomplete")
        if connection.execute("SELECT p.id FROM pokemon p LEFT JOIN pokemon_types t ON t.pokemon_id=p.id GROUP BY p.id HAVING count(t.type_id) NOT BETWEEN 1 AND 2").fetchone() is not None:
            raise ValueError("pokemon type coverage is incomplete")
        if connection.execute("SELECT count(*) FROM type_efficacy WHERE attacking BETWEEN 1 AND 18 AND defending BETWEEN 1 AND 18").fetchone()[0] != 324:
            raise ValueError("the modern type chart must contain all 324 pairs")
        connection.execute("VACUUM")
        return version, input_hash

    def manifest(self, path: Path, connection: sqlite3.Connection, revision: str, version: str, input_hash: str) -> KnowledgeManifest:
        """path 为已提交的新库，connection 只读查数量，其余为确定版本；返回完整字节校验 manifest。"""
        counts = {field: connection.execute(f"SELECT count(*) FROM {field}").fetchone()[0] for field in KnowledgeCounts.model_fields}
        return KnowledgeManifest(data_version=version, source_revision=revision, input_sha256=input_hash,
            sqlite_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), byte_size=path.stat().st_size,
            counts=KnowledgeCounts.model_validate(counts), sources=tuple(sorted(self._digests, key=lambda item: item.file)))


def build_knowledge_pack(source: Path, output: Path, revision: str) -> KnowledgeManifest:
    """生成完整新知识包，成功后替换明确输出，失败不覆盖原构建文件。

    Args:
        source: 固定 PokeAPI CSV 根目录，只读。
        output: SQLite 交付路径，禁止指向用户运行数据库。
        revision: 对应 CSV 的完整 40 位 Git 提交。
    Returns:
        包含实际 SQLite SHA-256 和行数的 manifest，旁边写入 manifest.json。
    """
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("source revision must be a full lowercase Git SHA")
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).resolve().parents[2] / "data/knowledge/schema.v1.sql").read_bytes()
    descriptor, temporary_name = tempfile.mkstemp(prefix="knowledge-build-", suffix=".sqlite", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    builder = _PackBuilder(source)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            version, input_hash = builder.populate(connection, revision, schema)
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            manifest = builder.manifest(temporary, connection, revision, version, input_hash)
        os.replace(temporary, output)
        output.with_name("manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """解析源目录、交付路径与固定提交；输出 manifest 摘要，不读取任何生产凭据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(build_knowledge_pack(args.source, args.output, args.revision).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
