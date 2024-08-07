import logging
from fastapi import APIRouter
router = APIRouter()

@router.get(
    ""
)
async def hello():
    logging.info("Hello world!")
    return "Hello World"
