from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

from fastapi import Header, HTTPException

READ_TOKEN_ENV = "MDTAS_API_READ_TOKEN"
WRITE_TOKEN_ENV = "MDTAS_API_WRITE_TOKEN"


def _token_map() -> dict[str, str]:
    tokens: dict[str, str] = {}
    read_token = os.getenv(READ_TOKEN_ENV, "").strip()
    write_token = os.getenv(WRITE_TOKEN_ENV, "").strip()
    if read_token:
        tokens["read"] = read_token
    if write_token:
        tokens["write"] = write_token
    return tokens


def _auth_enabled(tokens: Mapping[str, str]) -> bool:
    return bool(tokens)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "ApiKey"})


def require_read_access(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    tokens = _token_map()
    if not _auth_enabled(tokens):
        return

    if not x_api_key:
        raise _unauthorized("Missing X-API-Key header")

    accepted = [tokens[k] for k in ("read", "write") if k in tokens]
    if not any(hmac.compare_digest(x_api_key, candidate) for candidate in accepted):
        raise _unauthorized("Invalid API key")


def require_write_access(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    tokens = _token_map()
    if not _auth_enabled(tokens):
        return

    write_token = tokens.get("write")
    if not write_token:
        raise _unauthorized("Write access is disabled: set MDTAS_API_WRITE_TOKEN")

    if not x_api_key:
        raise _unauthorized("Missing X-API-Key header")

    if not hmac.compare_digest(x_api_key, write_token):
        raise _unauthorized("Invalid API key")
