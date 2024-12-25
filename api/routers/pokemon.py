from fastapi import APIRouter
from typing import Optional
from api.schema.router.pokemon import PokemonListResponse
from api.db import open_session
from api.models.pokemon import Pokemon
import logging

router = APIRouter()


@router.get(
    "/list",
    response_model=PokemonListResponse
)
async def calculate_damage(
    keyword: Optional[str] = ''
):
    with open_session() as pg_session:
        result = Pokemon.get_by_fuzzy_name(pg_session, keyword)
        logging.info(keyword)
        return_value = []
        for item in result:
            return_value.append({
                "id": item.id,
                "name": item.name
            })

        return PokemonListResponse(**{
            "total": 0,
            "result": return_value
        })