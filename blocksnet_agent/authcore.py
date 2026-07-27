"""Auth-ядро, общее для MCP и A2A-сервисов.

Шаг 06 a2a-рефакторинга. Логика аутентификации изолирована от транспорта
(FastMCP/FastAPI) — только сравнение токенов и формирование ошибок.

Источник истины по контракту — ``docs/mas_integration_implementation_plan.md``.
Коды ошибок (401/403) и формат токена сверяются там.

Использование::

    from blocksnet_agent.authcore import StaticTokenVerifier, AuthError

    verifier = StaticTokenVerifier(token="secret")
    principal = verifier.verify("Bearer secret")
    if principal is None:
        raise AuthError("invalid_token")

Главные свойства:
- ``AUTH_ENABLED=false`` (default) — проверка токена отключена, всё работает
  как раньше. Локальная разработка не ломается.
- ``hmac.compare_digest`` для сверки токенов — константное время, нет
  утечки через тайминг.
- Сообщения об ошибках НЕ различают «нет токена» и «неверный токен»
  (защита от enumeration).
- ``Principal`` — frozen dataclass с минимальным набором полей; готово к
  JWT-расширению в будущем.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# Коды ошибок (сверяются с mas_integration_implementation_plan.md).
ERROR_INVALID_TOKEN = "invalid_token"
ERROR_INSUFFICIENT_SCOPE = "insufficient_scope"


@dataclass(frozen=True)
class Principal:
    """Идентифицированный клиент: subject + scopes.

    Attributes:
        subject: ``sub`` (sub claim / username / service-account-id).
        scopes: набор разрешённых scope (например, ``{"scenario:read", "scenario:write"}``).
            Для статического токена это полный набор прав (без JWT-claims).
        raw_token: исходный токен (НЕ логировать, использовать только для audit).
            По умолчанию пустой — защита от случайной утечки через repr/log.

    a2a/06: ``__repr__`` скрывает ``raw_token`` — даже если токен задан
    и попадёт в логи через ``repr()``, текст не утёчет.
    """

    subject: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    raw_token: str = ""

    def __repr__(self) -> str:
        # ``raw_token`` намеренно не включается — это самый частый способ
        # случайной утечки секретов (print(principal), f"{principal}",
        # logger.info("user %s", principal)).
        return (
            f"Principal(subject={self.subject!r}, "
            f"scopes={set(self.scopes)!r}, "
            f"raw_token=<redacted len={len(self.raw_token)}>)"
        )

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class AuthError(Exception):
    """Ошибка аутентификации с human-readable message и machine-readable code.

    message: единый текст для всех вариантов невалидного токена.
    code: один из ``ERROR_INVALID_TOKEN``/``ERROR_INSUFFICIENT_SCOPE``.
    status_code: HTTP-статус (401/403).
    """

    def __init__(
        self,
        message: str = "Authentication required",
        *,
        code: str = ERROR_INVALID_TOKEN,
        status_code: int = 401,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


@runtime_checkable
class TokenVerifier(Protocol):
    """Интерфейс верификатора токенов — заменяемая реализация."""

    def verify(self, authorization_header: str | None) -> Principal | None:
        """Возвращает ``Principal`` если токен валиден, иначе ``None``.

        Args:
            authorization_header: значение HTTP-заголовка ``Authorization``
                (``"Bearer xxx"``). Может быть None.
        """


class StaticTokenVerifier:
    """Простейший верификатор: один статический токен из настроек.

    Сейчас — единственная реализация. На будущее — JWT/JWKS без изменения
    контракта (``TokenVerifier``).
    """

    def __init__(self, token: str, *, subject: str = "static") -> None:
        if not token:
            raise ValueError("token must be non-empty")
        self._token = token
        self._subject = subject

    def verify(self, authorization_header: str | None) -> Principal | None:
        if not authorization_header:
            return None
        # ``Bearer <token>`` — стандартная схема.
        parts = authorization_header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        presented = parts[1].strip()
        # ``hmac.compare_digest`` — константное время, нет утечки через тайминг.
        if not hmac.compare_digest(
            presented.encode("utf-8"), self._token.encode("utf-8")
        ):
            return None
        return Principal(
            subject=self._subject,
            scopes=frozenset({"scenario:read", "scenario:write"}),
            raw_token="",  # не хранить — защита от случайной утечки в логи
        )


# Сообщения для AuthError. Единые — чтобы злоумышленник не мог отличить
# «нет токена» от «неверный токен» через разные ответы (enumeration attack).
_GENERIC_INVALID = "Authentication required"


def verify_bearer(
    authorization_header: str | None,
    verifier: TokenVerifier,
) -> Principal:
    """Утилита: проверяет заголовок, бросает ``AuthError`` с единым сообщением.

    ВАЖНО: вызывающий код НЕ должен различать «нет токена» и «неверный
    токен» в ответе клиенту. Если нужна диагностика — пишите в лог ПОСЛЕ
    этой проверки, а не возвращайте разные сообщения.
    """
    principal = verifier.verify(authorization_header)
    if principal is None:
        raise AuthError(_GENERIC_INVALID, code=ERROR_INVALID_TOKEN, status_code=401)
    return principal


__all__ = [
    "AuthError",
    "ERROR_INVALID_TOKEN",
    "ERROR_INSUFFICIENT_SCOPE",
    "Principal",
    "StaticTokenVerifier",
    "TokenVerifier",
    "verify_bearer",
]