-- 初始离线知识投影；所有数据来自固定 PokeAPI CSV，不保存用户配置或同步状态。
PRAGMA user_version = 1;
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE types (id INTEGER PRIMARY KEY, identifier TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE abilities (id INTEGER PRIMARY KEY, identifier TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE natures (id INTEGER PRIMARY KEY, identifier TEXT NOT NULL, name TEXT NOT NULL,
  decreased_stat_id INTEGER NOT NULL, increased_stat_id INTEGER NOT NULL);
CREATE TABLE pokemon (id INTEGER PRIMARY KEY, species_id INTEGER NOT NULL, identifier TEXT NOT NULL,
  name TEXT NOT NULL, height INTEGER NOT NULL, weight INTEGER NOT NULL, can_evolve INTEGER NOT NULL CHECK(can_evolve IN (0,1)));
CREATE TABLE pokemon_stats (pokemon_id INTEGER NOT NULL REFERENCES pokemon(id), stat_id INTEGER NOT NULL CHECK(stat_id BETWEEN 1 AND 6),
  base_stat INTEGER NOT NULL, PRIMARY KEY(pokemon_id,stat_id)) WITHOUT ROWID;
CREATE TABLE pokemon_types (pokemon_id INTEGER NOT NULL REFERENCES pokemon(id), type_id INTEGER NOT NULL REFERENCES types(id),
  slot INTEGER NOT NULL, PRIMARY KEY(pokemon_id,slot)) WITHOUT ROWID;
CREATE TABLE pokemon_abilities (pokemon_id INTEGER NOT NULL REFERENCES pokemon(id), ability_id INTEGER NOT NULL REFERENCES abilities(id),
  slot INTEGER NOT NULL, is_hidden INTEGER NOT NULL CHECK(is_hidden IN (0,1)), PRIMARY KEY(pokemon_id,slot)) WITHOUT ROWID;
CREATE TABLE moves (id INTEGER PRIMARY KEY, identifier TEXT NOT NULL, name TEXT NOT NULL, generation_id INTEGER NOT NULL,
  type_id INTEGER NOT NULL REFERENCES types(id), power INTEGER, pp INTEGER, accuracy INTEGER, priority INTEGER NOT NULL,
  target_id INTEGER NOT NULL, damage_class_id INTEGER NOT NULL CHECK(damage_class_id BETWEEN 1 AND 3), effect_id INTEGER, effect_chance INTEGER);
CREATE TABLE type_efficacy (attacking INTEGER NOT NULL REFERENCES types(id), defending INTEGER NOT NULL REFERENCES types(id),
  percent INTEGER NOT NULL CHECK(percent>=0), PRIMARY KEY(attacking,defending)) WITHOUT ROWID;
CREATE INDEX pokemon_name ON pokemon(name);
CREATE INDEX pokemon_identifier ON pokemon(identifier);
CREATE INDEX moves_name ON moves(name);
CREATE INDEX moves_identifier ON moves(identifier);
