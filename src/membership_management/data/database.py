from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from membership_management.data.config import settings

MEMBERSHIP_DATABASE_URL = str(object=settings.members_database_url)

engine: Engine = create_engine(MEMBERSHIP_DATABASE_URL)

MembershipSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class MemberManagementBase(DeclarativeBase):
    pass