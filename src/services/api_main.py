from __future__ import annotations

import os

import uvicorn

from mdtas.config import get_config
from mdtas.db.session import init_db
from mdtas.logging import setup_logging
from services.common import emit_service_event, safe_config_summary


def main() -> None:
    setup_logging()
    cfg = get_config()
    summary = safe_config_summary(cfg)
    emit_service_event(service="api", event="starting", **summary)

    init_db()

    host = os.getenv("MDTAS_API_HOST", "0.0.0.0")
    port = int(os.getenv("MDTAS_API_PORT", "8000"))
    reload_enabled = os.getenv("MDTAS_API_RELOAD", "false").lower() == "true"
    emit_service_event(service="api", event="started", host=host, port=port, reload=reload_enabled)
    uvicorn.run("mdtas.api.app:app", host=host, port=port, reload=reload_enabled)


if __name__ == "__main__":
    main()
