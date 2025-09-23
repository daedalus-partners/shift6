from sqlalchemy.orm import Session
from ...db import get_db as _get_db

def get_db_dep() -> Session:
    # delegate to central generator
    yield from _get_db()


