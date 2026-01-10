import textwrap
from contextlib import contextmanager

from pokeop.init import init_pokemon


def write_csv(tmp_path, name, content):
    path = tmp_path / name
    normalized = textwrap.dedent(content).strip() + "\n"
    path.write_text(normalized)
    return path


def test_empty_stats():
    result = init_pokemon.InitPokemon._empty_stats()
    assert set(result.keys()) == set(init_pokemon.STAT_FIELDS)
    assert all(value == 0 for value in result.values())


def test_load_pokemon_stats(tmp_path):
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
