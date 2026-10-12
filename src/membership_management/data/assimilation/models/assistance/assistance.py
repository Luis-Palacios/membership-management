from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.assimilation.database import Base


class Assistance(Base):
    __tablename__ = "Asistencia"

    person_id: Mapped[int] = mapped_column(
        ForeignKey(column="Persona.Id_Persona"), name="Persona", primary_key=True
    )

    assistance_date: Mapped[datetime] = mapped_column(name="Fecha_Asistencia", primary_key=True)
    assistance_type_id: Mapped[int] = mapped_column(name="Id_Tipo_Asistencia", primary_key=True)
    wish_tobe_contacted: Mapped[bool] = mapped_column(name="Desea_Contacto")