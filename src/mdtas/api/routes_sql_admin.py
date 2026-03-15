from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from mdtas.api.auth import require_write_access
from mdtas.api.schemas import SqlAdminExecuteOut, SqlAdminExecuteRequest
from mdtas.db.session import get_session

router = APIRouter(tags=["sql-admin"])

_SQL_API_ENABLE_ENV = "MDTAS_ENABLE_SQL_API"
_SQL_API_ALLOW_WRITE_ENV = "MDTAS_SQL_API_ALLOW_WRITE"

_READONLY_SQL_VERBS = {"select", "with", "show", "explain", "pragma"}
_MUTATING_SQL_VERBS = {
    "insert",
    "update",
    "delete",
    "merge",
    "create",
    "alter",
    "drop",
    "truncate",
    "grant",
    "revoke",
    "vacuum",
    "reindex",
}


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_sql(sql: str) -> str:
    statement = sql.strip()
    if not statement:
        raise HTTPException(status_code=422, detail="SQL is required")

    # Enforce one statement per request to reduce blast radius.
    trimmed = statement.rstrip().rstrip(";").strip()
    if not trimmed:
        raise HTTPException(status_code=422, detail="SQL is required")

    if ";" in trimmed:
        raise HTTPException(status_code=422, detail="Only one SQL statement is allowed per request")

    return trimmed


@router.post("/admin/sql/execute", response_model=SqlAdminExecuteOut)
def execute_sql(
    payload: SqlAdminExecuteRequest,
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_session),
):
    if not _env_enabled(_SQL_API_ENABLE_ENV, default=False):
        raise HTTPException(
            status_code=403,
            detail=(
                f"SQL admin API is disabled. Set {_SQL_API_ENABLE_ENV}=true to enable."
            ),
        )

    statement = _normalize_sql(payload.sql)
    statement_type = statement.split(None, 1)[0].lower()

    allow_write = _env_enabled(_SQL_API_ALLOW_WRITE_ENV, default=False)
    if statement_type not in _READONLY_SQL_VERBS and not allow_write:
        raise HTTPException(
            status_code=403,
            detail=(
                "Write SQL is disabled for this API. "
                f"Set {_SQL_API_ALLOW_WRITE_ENV}=true to allow mutating statements."
            ),
        )

    try:
        result = session.execute(text(statement), payload.params or {})

        rows: list[dict[str, Any]] = []
        truncated = False
        rowcount = int(result.rowcount) if result.rowcount is not None and result.rowcount >= 0 else 0

        if result.returns_rows:
            fetched = result.fetchmany(payload.max_rows + 1)
            truncated = len(fetched) > payload.max_rows
            fetched = fetched[: payload.max_rows]
            rows = [dict(row._mapping) for row in fetched]
            if rowcount == 0:
                rowcount = len(rows)

        if statement_type in _MUTATING_SQL_VERBS:
            session.commit()
        else:
            session.rollback()

        return SqlAdminExecuteOut(
            statement_type=statement_type,
            rowcount=rowcount,
            rows=rows,
            truncated=truncated,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise HTTPException(status_code=400, detail=f"SQL execution failed: {exc}") from exc
