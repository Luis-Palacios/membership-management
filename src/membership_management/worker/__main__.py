"""`python -m membership_management.worker`: the worker as its own process (an ECS service of its own,
with `EMBEDDED_WORKER=false` on the API). SIGTERM/SIGINT stop it after the item in hand; the leases
cover anything that was in flight."""

import logging
import signal
import sys
import threading
from types import FrameType

from membership_management.data.database import engine
from membership_management.notifications import auth_server
from membership_management.notifications.config import notification_settings
from membership_management.worker.runner import run_forever

logger = logging.getLogger("membership_management.worker")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not notification_settings.conversation_emails_enabled:
        logger.info("CONVERSATION_EMAILS_ENABLED is off: nothing to do, exiting")
        return 0
    stop = threading.Event()

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("%s received: stopping after the item in hand", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        run_forever(stop)
    finally:
        auth_server.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
