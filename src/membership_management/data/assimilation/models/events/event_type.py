from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.assimilation.database import Base

if TYPE_CHECKING:
    from membership_management.data.assimilation.models.events.event import Event


class EventType(Base):
    __tablename__ = "Tipo_Evento"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, name="Id_TipoEvento")
    name: Mapped[str] = mapped_column(unique=True, index=True, nullable=False, name="Descripcion")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="event_type")

    def __repr__(self) -> str:
        return f"<EventType(id={self.id}, description={self.name})>"