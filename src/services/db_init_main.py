from __future__ import annotations

from mdtas.config import get_config
from mdtas.db.session import init_db
from mdtas.logging import setup_logging
from services.common import emit_service_event, safe_config_summary


def main() -> None:
    setup_logging()
    cfg = get_config()
    emit_service_event(service="db_init", event="starting", **safe_config_summary(cfg))
    init_db()
    emit_service_event(service="db_init", event="completed")


if __name__ == "__main__":
    main()
