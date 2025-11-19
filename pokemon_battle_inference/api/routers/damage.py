from fastapi import APIRouter
from pokemon_battle_inference.services.pokemon_builder import PokemonDirector
from pokemon_battle_inference.domain.models.move import Move, MoveType
from pokemon_battle_inference.domain.models.types import Type
from pokemon_battle_inference.domain.calculations.damage.calculator import (
    DamageCalculator,
)
from pokemon_battle_inference.api.schemas.damage import DamageRequest, DamageResponse

router = APIRouter()

@router.post(
    "",
    response_model=DamageResponse
)
async def calculate_damage(
    input_data: DamageRequest
):
    """
    {
        "attacker": {
            "id": 10021,
            "level": 100,
            "basepoint": [
            0,
            252,
            0,
            0,
            0,
            252
            ],
            "individual_values": [
            31,
            31,
            31,
            31,
            31,
            31
            ],
            "nature": "Adamant"
        },
        "defenser": {
            "id": 598,
            "level": 100,
            "basepoint": [
            252,
            0,
            252,
            0,
            0,
            0
            ],
            "individual_values": [
            31,
            31,
            31,
            31,
            31,
            31
            ],
            "nature": "Impish"
        },
        "move": {
            "power": 100,
            "move_type": "physical_move",
            "type": "Ground"
        }
    }
    """
    director = PokemonDirector()
    attacker = director.construct_from_database(
        id=input_data.attacker.id, # Landorus-therian
        level=input_data.attacker.level,
        basepoint=input_data.attacker.basepoint,
        nature=input_data.attacker.nature
    )

    defenser = director.construct_from_database(
        id=input_data.defenser.id, # Landorus-therian
        level=input_data.defenser.level,
        basepoint=input_data.defenser.basepoint,
        nature=input_data.defenser.nature
    )

    move = Move(
        power=input_data.move.power, 
        type=Type.from_string(input_data.move.type),
        move_type=input_data.move.move_type)

    result = DamageCalculator().calculate(attacker, defenser, move)
    return DamageResponse(**result.__dict__)
