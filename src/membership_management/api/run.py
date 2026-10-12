import uvicorn

from membership_management.api.config import api_settings


def main() -> None:
    uvicorn.run(
        "membership_management.api.main:app",
        host="0.0.0.0",  # noqa: S104 -- intentional: binds all interfaces inside a container
        port=api_settings.port,
        workers=api_settings.workers,
        timeout_keep_alive=api_settings.keep_alive_timeout_seconds,
        timeout_graceful_shutdown=api_settings.graceful_shutdown_timeout_seconds,
        limit_concurrency=api_settings.limit_concurrency,
        backlog=api_settings.backlog,
    )


if __name__ == "__main__":
    main()
