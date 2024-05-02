import csv
import logging

from script import CONFIG_PATH
from db import open_session
from models.types import Types
from schema.types import TypesCreate

class InitTypes:

    @classmethod
    def _get_types_name_map(cls):
        _type_name_map = {}
        with open(CONFIG_PATH + '/type/types.csv') as f:
            reader = csv.reader(f)
            next(reader)

            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    logging.info("读取结束")
                    break

                _type_name_map[row[0]] = row[1]
        return _type_name_map

    @classmethod
    def init(cls):
        name_map = cls._get_types_name_map()
        with open_session() as session:
            for key, val in name_map.items():
                single_item = {
                    "id": int(key),
                    "name": val
                }
                type_create = TypesCreate(**single_item)
                logging.info(type_create)
                Types.create(session, type_create)
