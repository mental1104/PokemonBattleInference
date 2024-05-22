import logging
from fastapi import APIRouter
from common.util import get_type_efficacy
router = APIRouter()

get_type_efficacy()

@router.get(
    ""
)
async def hello():
    logging.info("Hello world")
    return "Hello World"
