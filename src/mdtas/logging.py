import logging
import os


def setup_logging() -> None:
    level = os.getenv("MDTAS_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
