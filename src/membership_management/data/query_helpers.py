from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select
    from sqlalchemy.orm import Session

RowT = TypeVar("RowT", bound=tuple[object, ...])
ResultT = TypeVar("ResultT")


def first_as(session: Session, query: Select[RowT], cls: type[ResultT]) -> ResultT | None:
    """
    Execute `query` and map its first row into `cls` by column name, or None if there are no rows.
    `cls` must accept the query's selected column names as keyword arguments (e.g. a NamedTuple
    or dataclass whose field names match the selected columns).
    """
    row = session.execute(query).first()
    return cls(**row._mapping) if row is not None else None


def all_as(session: Session, query: Select[RowT], cls: type[ResultT]) -> Sequence[ResultT]:
    """
    Execute `query` and map every row into `cls` by column name. Same field-name contract as `first_as`.
    """
    rows = session.execute(query).all()
    return [cls(**row._mapping) for row in rows]
