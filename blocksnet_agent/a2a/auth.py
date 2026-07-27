"""A2A-auth-адаптер: оборачивает FastAPI в проверку Bearer-токена.

Шаг 06 a2a-рефакторинга. Логика проверки токена — в общем
``blocksnet_agent.authcore`` (константное время, единый текст ошибки).
Здесь только тонкий слой middleware + helper ``get_principal`` для
эндпойнтов.

Главные свойства:
- ``AUTH_ENABLED=false`` (default) — auth отключён, всё работает.
- ``AUTH_ENABLED=true`` + ``MAS_BEARER_TOKEN`` не задан → ошибка
  конфигурации на старте (fail-fast).
- ``AUTH_ENABLED=true`` + токен невалиден → ``AuthError`` → 401 с
  единым текстом.
- ``Principal`` доступен через ``get_principal()`` в эндпойнтах.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from blocksnet_agent.authcore import (
    AuthError,
    Principal,
    StaticTokenVerifier,
    TokenVerifier,
    verify_bearer,
)

log = logging.getLogger("blocksnet_agent.a2a.auth")


# Глобальный verifier, инициализируется в ``configure_auth``.
_verifier: TokenVerifier | None = None
_auth_enabled: bool = False


def configure_auth(*, auth_enabled: bool, mas_bearer_token: str | None) -> None:
    """Инициализирует auth по настройкам. Вызывается из ``build_app``.

    Raises:
        RuntimeError: если ``AUTH_ENABLED=true`` без ``MAS_BEARER_TOKEN``.
    """
    global _verifier, _auth_enabled
    _auth_enabled = auth_enabled
    if not auth_enabled:
        _verifier = None
        log.info("A2A auth DISABLED (AUTH_ENABLED=false)")
        return
    if not mas_bearer_token:
        raise RuntimeError(
            "AUTH_ENABLED=true but MAS_BEARER_TOKEN is not set — refusing to start"
        )
    _verifier = StaticTokenVerifier(mas_bearer_token)
    log.info("A2A auth ENABLED with static token verifier")


def is_auth_enabled() -> bool:
    return _auth_enabled


async def auth_middleware(request: Request, call_next):
    """FastAPI middleware: проверяет Bearer-токен, если ``AUTH_ENABLED=true``.

    Пути исключения (без токена): ``/.well-known/agent-card.json``, ``/health``,
    ``/docs``, ``/openapi.json``, ``/redoc``, ``/docs/oauth2-redirect``.
    Эти пути доступны клиентам без авторизации (discovery, liveness).
    """
    if not _auth_enabled:
        return await call_next(request)

    path = request.url.path
    public_paths = {
        "/.well-known/agent-card.json",
        "/health",
        "/docs",
        "/docs/oauth2-redirect",
        "/openapi.json",
        "/redoc",
    }
    if path in public_paths:
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    try:
        # ``_verifier`` гарантированно инициализирован (configure_auth провёл валидацию).
        principal = verify_bearer(auth_header, _verifier)  # type: ignore[arg-type]
    except AuthError as exc:
        from starlette.responses import JSONResponse

        # НЕ различаем «нет токена» и «неверный» в ответе — единый текст/код.
        log.warning(
            "A2A auth failed: %s path=%s code=%s",
            exc.message, path, exc.code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
            },
        )
    # Сохраняем Principal в request.state для эндпойнтов.
    request.state.principal = principal
    return await call_next(request)


def get_principal(request: Request) -> Principal | None:
    """Возвращает ``Principal`` текущего запроса (``None`` если auth выключен)."""
    return getattr(request.state, "principal", None)


__all__ = [
    "configure_auth",
    "is_auth_enabled",
    "auth_middleware",
    "get_principal",
]