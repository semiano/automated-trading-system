from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}
