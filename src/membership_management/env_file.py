import os

# Which .env file the settings classes read, if any. Deployments must set ENVIRONMENT as a real env
# var (it's required by the data layer's Settings), so there this is None and a stray .env is never
# read: prod config comes from the task definition alone. Locally ENVIRONMENT isn't set in the shell,
# so .env is read, and it supplies ENVIRONMENT=local. Real env vars always win over the file.
ENV_FILE = None if os.getenv("ENVIRONMENT") in ("staging", "production") else ".env"
