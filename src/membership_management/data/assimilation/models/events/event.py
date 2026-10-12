from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.assimilation.database import Base

if TYPE_CHECKING:
    from membership_management.data.assimilation.models.events.event_person import EventPerson
    from membership_management.data.assimilation.models.events.event_type import EventType


class Event(Base):
    __tablename__ = "Evento"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, name="Id_Evento")
    name: Mapped[str] = mapped_column(unique=True, index=True, nullable=False, name="Descripcion")
    event_type_id: Mapped[int] = mapped_column(
        ForeignKey("Tipo_Evento.Id_TipoEvento"),
        nullable=False,
        name="Id_Tipo",
    )

    date: Mapped[datetime] = mapped_column(nullable=False, name="Fecha")
    event_type: Mapped["EventType"] = relationship(
        "EventType", back_populates="events", foreign_keys=[event_type_id]
    )

    guests: Mapped[list["EventPerson"]] = relationship(
        "EventPerson",
        back_populates="event",
    )

    def __repr__(self) -> str:
        return (
            f"<Event(id={self.id}, name={self.name}, event_type_id={self.event_type_id}, date={self.date})>"
        )
