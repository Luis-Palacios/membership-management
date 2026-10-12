from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.assimilation.database import Base

if TYPE_CHECKING:
    from membership_management.data.assimilation.models.events.event_person import EventPerson
    from membership_management.data.assimilation.models.membership_applications.membership_application import (  # noqa: E501
        MembershipApplication,
    )


class Person(Base):
    __tablename__ = "Persona"

    id: Mapped[int] = mapped_column(primary_key=True, name="Id_Persona", autoincrement=True)
    first_name: Mapped[str] = mapped_column(name="Nombre")
    last_name: Mapped[str] = mapped_column(name="Apellido")
    email: Mapped[str] = mapped_column(name="Correo_Electronico")
    phone_number: Mapped[str] = mapped_column(name="Telefono")
    cellphone_claro: Mapped[str] = mapped_column(name="Celular_Claro")
    cellphone_movistart: Mapped[str] = mapped_column(name="Celular_Movistar")
    sex: Mapped[str] = mapped_column(name="Sexo")

    membership_applications: Mapped[list["MembershipApplication"]] = relationship(
        back_populates="person",
    )

    events: Mapped[list["EventPerson"]] = relationship(
        "EventPerson",
        back_populates="person",
    )

    def __repr__(self) -> str:
        return f"Person(id={self.id}, first_name={self.first_name}, last_name={self.last_name})"
