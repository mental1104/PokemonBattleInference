from pydantic import BaseModel, Field
from typing import List


class PokemonResponse(BaseModel):
    id: int = Field(0, description="pokemon id")
    name: str = Field("", description="pokemon name")


class PokemonListResponse(BaseModel):
    result: List[PokemonResponse] = Field([])
    total: int = Field(0)