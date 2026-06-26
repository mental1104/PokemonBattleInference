import textwrap
from contextlib import contextmanager

from pokeop.persistence.importers import init_pokemon


def write_csv(tmp_path, name, content):
    path = tmp_path / name
    normalized = textwrap.dedent(content).strip() + "\n"
    path.write_text(normalized)
    return path


def test_empty_stats():
    """
    验证初始化导入器创建空能力值模板时会包含全部六项能力字段。
    这个模板用于后续合并 CSV 里的部分 stat 行；
    如果某个能力没有在输入 CSV 中出现，应保留默认值 0。
    """
    result = init_pokemon.InitPokemon._empty_stats()
    assert set(result.keys()) == set(init_pokemon.STAT_FIELDS)
    assert all(value == 0 for value in result.values())


def test_load_pokemon_stats(tmp_path):
    """
    验证从 pokemon_stats CSV 中读取同一只宝可梦的多行能力值。
    测试 CSV 只给 pokemon_id=1 提供 hp、attack、speed 三项，
    断言导入器能按 stat_id 映射字段并保留缺失 defense 的默认值 0。
    """
    stats_file = write_csv(
        tmp_path,
        "stats.csv",
        """
        pokemon_id,stat_id,base_stat,effort
        1,1,45,0
        1,2,49,0
        1,6,45,0
        """,
    )
    result = init_pokemon.InitPokemon.load_pokemon_stats(stats_file)
    assert result["1"]["hp"] == 45
    assert result["1"]["attack"] == 49
    assert result["1"]["defense"] == 0
    assert result["1"]["speed"] == 45


def test_load_pokemon_names(tmp_path):
    """
    验证从 pokemon CSV 中读取宝可梦 ID 到 identifier 的名称映射。
    测试输入包含 Bulbasaur 和 Ivysaur 两行，
    断言导入器只提取 id 和 identifier，形成 {"1": "bulbasaur", "2": "ivysaur"}。
    """
    name_file = write_csv(
        tmp_path,
        "pokemon.csv",
        """
        id,identifier,species_id,height,weight,base_experience,order,is_default
        1,bulbasaur,1,7,69,64,1,1
        2,ivysaur,2,10,130,142,2,1
        """,
    )
    result = init_pokemon.InitPokemon.load_pokemon_names(name_file)
    assert result == {"1": "bulbasaur", "2": "ivysaur"}


def test_load_pokemon_types(tmp_path):
    """
    验证从 pokemon_types CSV 中读取宝可梦的一号和二号属性槽。
    测试输入故意包含 slot=3 的额外行，
    断言导入器只保留 type_1 和 type_2，忽略不属于对战主属性槽的行。
    """
    type_file = write_csv(
        tmp_path,
        "pokemon_types.csv",
        """
        pokemon_id,type_id,slot
        1,12,1
        1,4,2
        1,9,3
        """,
    )
    result = init_pokemon.InitPokemon.load_pokemon_types(type_file)
    assert result == {"1": {"type_1": 12, "type_2": 4}}


def test_load_move_pool(tmp_path):
    """
    验证从 pokemon_moves CSV 中按 pokemon_id 聚合招式池。
    测试输入让 pokemon_id=1 拥有 move_id 33 和 45，
    pokemon_id=2 拥有 move_id 22，断言结果按宝可梦分组且保持读取顺序。
    """
    move_file = write_csv(
        tmp_path,
        "pokemon_moves.csv",
        """
        pokemon_id,move_id,method_id,level,order
        1,33,1,1,0
        1,45,1,3,0
        2,22,1,1,0
        """,
    )
    result = init_pokemon.InitPokemon.load_move_pool(move_file)
    assert result["1"] == ["33", "45"]
    assert result["2"] == ["22"]


def test_load_ability_pool(tmp_path):
    """
    验证从 pokemon_abilities CSV 中按 pokemon_id 聚合能力列表。
    测试输入给 pokemon_id=1 两个 ability_id，
    断言导入器返回 {"1": ["65", "34"]}，为后续 payload 合并提供能力池。
    """
    ability_file = write_csv(
        tmp_path,
        "pokemon_abilities.csv",
        """
        pokemon_id,ability_id,is_hidden,slot
        1,65,0,1
        1,34,0,2
        """,
    )
    result = init_pokemon.InitPokemon.load_ability_pool(ability_file)
    assert result == {"1": ["65", "34"]}


def test_iter_pokemon_payloads_merges_sources(monkeypatch):
    """
    验证 InitPokemon.iter_pokemon_payloads 会把多个 CSV 来源合成一个宝可梦载荷。
    测试用 monkeypatch 替换 stats、names、types、moves、abilities 五个读取函数，
    构造 pokemon_id=1 的 Bulbasaur 数据，断言最终 payload 同时包含能力值、
    名称、双属性、招式列表和能力列表。
    """
    stats = {
        "1": {
            "hp": 10,
            "attack": 20,
            "defense": 0,
            "special_attack": 0,
            "special_defense": 0,
            "speed": 0,
        }
    }
    names = {"1": "bulbasaur"}
    types = {"1": {"type_1": 12, "type_2": 4}}
    moves = {"1": ["33", "45"]}
    abilities = {"1": ["65", "34"]}

    monkeypatch.setattr(
        init_pokemon.InitPokemon,
        "load_pokemon_stats",
        staticmethod(lambda _: stats),
    )
    monkeypatch.setattr(
        init_pokemon.InitPokemon,
        "load_pokemon_names",
        staticmethod(lambda _: names),
    )
    monkeypatch.setattr(
        init_pokemon.InitPokemon,
        "load_pokemon_types",
        staticmethod(lambda _: types),
    )
    monkeypatch.setattr(
        init_pokemon.InitPokemon,
        "load_move_pool",
        staticmethod(lambda _: moves),
    )
    monkeypatch.setattr(
        init_pokemon.InitPokemon,
        "load_ability_pool",
        staticmethod(lambda _: abilities),
    )

    payloads = list(init_pokemon.InitPokemon.iter_pokemon_payloads())
    assert payloads == [
        (
            "1",
            {
                "hp": 10,
                "attack": 20,
                "defense": 0,
                "special_attack": 0,
                "special_defense": 0,
                "speed": 0,
                "name": "bulbasaur",
                "type_1": 12,
                "type_2": 4,
                "move_ids": ["33", "45"],
                "ability": ["65", "34"],
            },
        )
    ]


def test_init_persists_payloads(monkeypatch):
    """
    验证 InitPokemon.init 会把合并后的 payload 转换成 PokemonCreate 并调用持久化入口。
    测试替换 open_session、iter_pokemon_payloads 和 Pokemon.create，
    避免真实数据库访问，只捕获传入 create 的对象；
    最后断言创建了一个 id=1、name=bulbasaur 的 PokemonCreate。
    """
    payloads = [
        (
            "1",
            {
                "name": "bulbasaur",
                "type_1": 12,
                "type_2": 4,
                "hp": 45,
                "attack": 49,
                "defense": 49,
                "special_attack": 65,
                "special_defense": 65,
                "speed": 45,
                "move_ids": [33, 45],
                "ability": [65, 34],
            },
        )
    ]

    @contextmanager
    def fake_open_session():
        yield None

    created = []

    def fake_create(pokemon_create):
        created.append(pokemon_create)

    monkeypatch.setattr(
        init_pokemon.InitPokemon,
        "iter_pokemon_payloads",
        classmethod(lambda cls: iter(payloads)),
    )
    monkeypatch.setattr(init_pokemon, "open_session", fake_open_session)
    monkeypatch.setattr(
        init_pokemon.Pokemon,
        "create",
        staticmethod(fake_create),
    )

    init_pokemon.InitPokemon.init()

    assert len(created) == 1
    assert created[0].id == 1
    assert created[0].name == "bulbasaur"
