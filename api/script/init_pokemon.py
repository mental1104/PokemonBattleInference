import logging
import csv
from db import startup
from db import open_session
from models.pokemon import Pokemon
from schema.pokemon import PokemonCreate



class InitPokemon:
    @classmethod
    def _get_pokemon_stats(cls):
        _pokemon_stats_config = {}
        with open('/home/espeon/code/pokemon_calcu/api/script/config/pokemon_stats.csv') as f:
            reader = csv.reader(f)
            next(reader)
            
            # 一次读取csv的行数
            rows_per_iteration = 6

            while True:
                try:
                    rows = [next(reader) for _ in range(rows_per_iteration)]
                except StopIteration:
                    logging.info("读取结束")
                    break

                if not rows:
                    break
                
                init_str = ['hp', 'attack', 'defense', 'special_attack', 'special_defense', 'speed']
                id = rows[0][0]
                single_pokemon = {}
                for i in range(len(rows)):
                    single_pokemon[init_str[i]] = int(rows[i][2])
                _pokemon_stats_config[id] = single_pokemon
        return _pokemon_stats_config

    @classmethod
    def _get_pokemon_name_map(cls):
        with open('/home/espeon/code/pokemon_calcu/api/script/config/pokemon.csv') as f:
            id2name_map = {}
            
            reader = csv.reader(f)
            next(reader)

            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    logging.info("读取结束")
                    break

                id2name_map[row[0]] = row[1]
        return id2name_map

    @classmethod
    def _get_pokemon_type(cls):
        pokemon_list = {}
        with open('/home/espeon/code/pokemon_calcu/api/script/config/type/pokemon_types.csv') as f:
            pokemon_types = {}
            
            reader = csv.reader(f)
            next(reader)

            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    logging.info("读取结束")
                    break
                    
                if row[0] not in pokemon_types:
                    pokemon_types[row[0]] = []
                pokemon_types[row[0]].append(row)

            for key, val in pokemon_types.items():
                pokemon_list[key] = {}
                for elem in val:
                    if elem[2] == '1':
                        pokemon_list[key]['type_1'] = int(elem[1])
                    elif elem[2] == '2':
                        pokemon_list[key]['type_2'] = int(elem[1])
        
        return pokemon_list
    
    @classmethod
    def _get_pokemon_move_pool(cls):
        import csv
        from collections import defaultdict

        # 存储结果的字典
        pokemon_moves = defaultdict(list)

        # 读取 CSV 文件
        with open("/home/espeon/code/pokemon_calcu/api/script/config/move/pokemon_moves.csv", "r", encoding="utf-8") as file:
            reader = csv.reader(file)
            next(reader)  # 跳过表头

            for row in reader:
                if len(row) < 3:  # 确保数据行足够长
                    continue
                pokemon_id = row[0]  # 第一列 pokemon_id
                move_id = row[2]  # 第三列 move_id
                pokemon_moves[pokemon_id].append(move_id)
        
        return pokemon_moves
    
    @classmethod
    def _get_pokemon_ability_pool(cls):
        import csv
        from collections import defaultdict

        # 存储结果的字典
        pokemon_moves = defaultdict(list)

        # 读取 CSV 文件
        with open("/home/espeon/code/pokemon_calcu/api/script/config/ability/pokemon_abilities.csv", "r", encoding="utf-8") as file:
            reader = csv.reader(file)
            next(reader)  # 跳过表头

            for row in reader:
                if len(row) < 3:  # 确保数据行足够长
                    continue
                pokemon_id = row[0]  # 第一列 pokemon_id
                move_id = row[1]  # 第三列 move_id
                pokemon_moves[pokemon_id].append(move_id)
        
        return pokemon_moves

    @classmethod
    def init(cls):
        pokemon_stats_config = cls._get_pokemon_stats()
        name_map = cls._get_pokemon_name_map()
        type_map = cls._get_pokemon_type()
        move_pool = cls._get_pokemon_move_pool()
        ability_pool = cls._get_pokemon_ability_pool()
        for key, val in pokemon_stats_config.items():
            val.update({"name": name_map[key]})
            val.update(type_map[key])
            val.update({"move_ids": move_pool[key]})
            val.update({"ability": ability_pool[key]})

        with open_session() as session:
            print(len(pokemon_stats_config))
            for key, val in pokemon_stats_config.items():
                print(key)
                single_pokemon = {
                    "id" : int(key),
                }
                single_pokemon.update(val)
                pokemon_create = PokemonCreate(**single_pokemon)
                logging.info(pokemon_create)
                Pokemon.create(session, pokemon_create)

from models import *

def main():
    logging.basicConfig(
        level=getattr(logging, "INFO"),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
            " %(message)s"
    )
    startup()
    InitPokemon.init()    


if __name__ == '__main__':
    main()