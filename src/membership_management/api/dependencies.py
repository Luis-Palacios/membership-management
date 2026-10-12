from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.orm import Session

from membership_management.data.assimilation.database import SessionLocal


def get_assimilation_db() -> Generator[Session, Any, None]:
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_assimilation_db)]