from pydantic import BaseModel

class TypesCreate(BaseModel):
    id: int
    name: str
