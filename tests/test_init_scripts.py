import textwrap
from pokemon_battle_inference.init import init_pokemon, init_types


def write_csv(tmp_path, name, content):
    path = tmp_path / name
    normalized = textwrap.dedent(content).strip() + "\n"
    path.write_text(normalized)
    return path


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
    result = init_pokemon.load_pokemon_stats(stats_file)
    assert result["1"]["hp"] == 45
    assert result["1"]["attack"] == 49
    # unspecified stats fall back to zero
    assert result["1"]["defense"] == 0
    assert result["1"]["speed"] == 45


def test_iter_pokemon_payloads_merges_sources(monkeypatch):
    stats = {"1": {"hp": 10, "attack": 20, "defense": 0, "special_attack": 0, "special_defense": 0, "speed": 0}}
    names = {"1": "bulbasaur"}
    types = {"1": {"type_1": 12, "type_2": 4}}
    moves = {"1": ["33", "45"]}
    abilities = {"1": ["65", "34"]}

    monkeypatch.setattr(init_pokemon, "load_pokemon_stats", lambda _: stats)
    monkeypatch.setattr(init_pokemon, "load_pokemon_names", lambda _: names)
    monkeypatch.setattr(init_pokemon, "load_pokemon_types", lambda _: types)
    monkeypatch.setattr(init_pokemon, "load_move_pool", lambda _: moves)
    monkeypatch.setattr(init_pokemon, "load_ability_pool", lambda _: abilities)

    payloads = list(init_pokemon.iter_pokemon_payloads())
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


def test_load_type_names(tmp_path):
    type_file = write_csv(
        tmp_path,
        "types.csv",
        """
        id,identifier,generation_id,damage_class_id
        10,fire,1,3
        11,water,1,3
        """,
    )
    result = init_types.load_type_names(type_file)
    assert result == {"10": "fire", "11": "water"}
