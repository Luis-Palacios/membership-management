from sqlalchemy import Engine, MetaData
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from membership_management.data.config import settings
from membership_management.data.pooled_engine import create_pooled_engine

engine: Engine = create_pooled_engine(
    settings,
    connect_args={
        # libpq's connect timeout. Without it a connect that gets no answer (e.g. localhost
        # resolving to an unreachable ::1) hangs forever instead of failing.
        "connect_timeout": settings.db_connect_timeout_seconds,
        # Server-side session settings, in milliseconds, applied to every pooled connection.
        "options": (
            f"-c statement_timeout={settings.db_query_timeout_seconds * 1000}"
            f" -c idle_in_transaction_session_timeout="
            f"{settings.db_idle_in_transaction_timeout_seconds * 1000}"
        ),
    },
)

MembershipSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class MemberManagementBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
