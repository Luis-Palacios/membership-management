from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.assimilation.database import Base

if TYPE_CHECKING:
    from membership_management.data.assimilation.models.events.event import Event
    from membership_management.data.assimilation.models.person.person import Person


class EventPerson(Base):
    __tablename__ = "Invitados"

    event_id: Mapped[int] = mapped_column(
        ForeignKey("Evento.Id_Evento"),
        name="Evento",
        primary_key=True,
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("Persona.Id_Persona"),
        name="Invitado",
        primary_key=True,
    )
    assisted: Mapped[bool] = mapped_column(name="Asistio")

    person: Mapped["Person"] = relationship("Person", back_populates="events", foreign_keys=[person_id])
    event: Mapped["Event"] = relationship("Event", back_populates="guests", foreign_keys=[event_id])
