from __future__ import annotations

import logging
import os

import uvicorn

from mdtas.logging import setup_logging


logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    host = os.getenv("MDTAS_API_HOST", "0.0.0.0")
    port = int(os.getenv("MDTAS_API_PORT", "8000"))
    reload_enabled = os.getenv("MDTAS_API_RELOAD", "false").lower() == "true"
    logger.info("API service started on %s:%s", host, port)
    uvicorn.run("mdtas.api.app:app", host=host, port=port, reload=reload_enabled)


if __name__ == "__main__":
    main()
