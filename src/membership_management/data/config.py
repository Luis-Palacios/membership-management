from pydantic import AnyUrl

from membership_management.data.base_db_settings import BaseDbSettings


class Settings(BaseDbSettings):
    members_database_url: AnyUrl


settings = Settings()