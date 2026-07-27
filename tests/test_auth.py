"""Тесты auth-ядра и auth-адаптера.

Шаг 06 a2a-рефакторинга. Главные гарантии:
- ``AUTH_ENABLED=false`` (default) — доступ без токена.
- ``AUTH_ENABLED=true`` без токена → 401.
- ``AUTH_ENABLED=true`` + неверный токен → 401.
- ``AUTH_ENABLED=true`` + верный токен → 200.
- Сообщения об ошибке для «нет» и «неверный» — одинаковые (защита от enumeration).
- ``hmac.compare_digest`` используется (константное время).
- ``Principal.raw_token`` пустой в repr — нет утечки токена в логи.
"""

from __future__ import annotations

import hmac
import json

import pytest
from starlette.testclient import TestClient

from blocksnet_agent.authcore import (
    AuthError,
    ERROR_INVALID_TOKEN,
    Principal,
    StaticTokenVerifier,
    TokenVerifier,
    verify_bearer,
)
from blocksnet_agent.a2a.auth import (
    auth_middleware,
    configure_auth,
    is_auth_enabled,
)
from blocksnet_agent.a2a.server import build_app


# --- core: StaticTokenVerifier -------------------------------------------


def test_static_verifier_accepts_correct_bearer() -> None:
    """Правильный ``Bearer <token>`` → ``Principal``."""
    v = StaticTokenVerifier(token="secret123")
    p = v.verify("Bearer secret123")
    assert p is not None
    assert p.subject == "static"
    assert "scenario:read" in p.scopes


def test_static_verifier_rejects_wrong_token() -> None:
    """Неверный токен → ``None`` (не бросает)."""
    v = StaticTokenVerifier(token="secret123")
    assert v.verify("Bearer wrong") is None
    assert v.verify("Bearer secret1234") is None  # почти-правильный
    assert v.verify("Bearer ") is None  # пустой


def test_static_verifier_rejects_no_header() -> None:
    """Нет заголовка → ``None``."""
    v = StaticTokenVerifier(token="secret123")
    assert v.verify(None) is None
    assert v.verify("") is None


def test_static_verifier_requires_bearer_scheme() -> None:
    """Только схема ``Bearer`` — другие схемы не принимаются."""
    v = StaticTokenVerifier(token="secret")
    assert v.verify("Basic secret") is None
    assert v.verify("secret") is None  # без схемы


def test_static_verifier_uses_constant_time_compare() -> None:
    """``hmac.compare_digest`` — константное время (защита от timing attack)."""
    # Тест через monkeypatch на compare_digest — если кто-то заменит на ``==``,
    # этот тест провалится.
    v = StaticTokenVerifier(token="a")
    # Сравнение происходит внутри verify. Проверим, что compare_digest
    # был вызван (через mock).
    called = []

    real = hmac.compare_digest

    def fake(a, b):
        called.append((a, b))
        return real(a, b)

    import blocksnet_agent.authcore as core
    core.hmac.compare_digest = fake  # type: ignore[assignment]
    try:
        v.verify("Bearer a")
        assert len(called) == 1, "compare_digest должен вызываться ровно раз"
    finally:
        core.hmac.compare_digest = real  # type: ignore[assignment]


# --- core: verify_bearer ----------------------------------------------------


def test_verify_bearer_returns_principal_on_success() -> None:
    """Успешная проверка → ``Principal``."""
    v = StaticTokenVerifier(token="x")
    p = verify_bearer("Bearer x", v)
    assert isinstance(p, Principal)


def test_verify_bearer_raises_auth_error_on_missing() -> None:
    """Нет токена → ``AuthError`` со status_code=401."""
    v = StaticTokenVerifier(token="x")
    with pytest.raises(AuthError) as exc_info:
        verify_bearer(None, v)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ERROR_INVALID_TOKEN


def test_verify_bearer_raises_auth_error_on_wrong_token() -> None:
    """Неверный токен → ``AuthError`` (тот же status_code и message)."""
    v = StaticTokenVerifier(token="correct")
    with pytest.raises(AuthError) as exc_info:
        verify_bearer("Bearer wrong", v)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ERROR_INVALID_TOKEN


def test_messages_for_missing_and_wrong_are_identical() -> None:
    """Защита от enumeration: «нет» и «неверный» — одинаковый текст."""
    v = StaticTokenVerifier(token="correct")
    try:
        verify_bearer(None, v)
    except AuthError as e_missing:
        try:
            verify_bearer("Bearer wrong", v)
        except AuthError as e_wrong:
            assert e_missing.message == e_wrong.message, (
                "сообщения должны совпадать, иначе enumeration"
            )
            assert e_missing.code == e_wrong.code


# --- core: Principal без утечки токена ------------------------------------


def test_principal_repr_does_not_leak_token() -> None:
    """``repr(Principal)`` НЕ содержит ``raw_token`` (даже если он задан).

    Через ``__repr__`` ``raw_token`` намеренно скрыт — это защита от случайной
    утечки токена в логи при repr() / ``str()``.
    """
    p = Principal(subject="x", raw_token="super-secret-token")
    text = repr(p)
    assert "super-secret-token" not in text
    # Также при format() (используется в f-strings).
    assert "super-secret-token" not in f"{p}"


def test_principal_default_raw_token_is_empty() -> None:
    """Дефолт ``raw_token`` — пустая строка."""
    p = Principal(subject="x")
    assert p.raw_token == ""


# --- core: TokenVerifier protocol -----------------------------------------


def test_static_verifier_implements_protocol() -> None:
    """``StaticTokenVerifier`` соответствует ``TokenVerifier``."""
    v = StaticTokenVerifier(token="x")
    assert isinstance(v, TokenVerifier)


# --- core: empty token rejected -------------------------------------------


def test_empty_token_rejected_at_construction() -> None:
    """Пустой токен → ValueError на конструкторе."""
    with pytest.raises(ValueError, match="token must be non-empty"):
        StaticTokenVerifier(token="")


# --- adapter: A2A middleware ----------------------------------------------


@pytest.fixture
def app_with_auth(monkeypatch: pytest.MonkeyPatch):
    """A2A-приложение с AUTH_ENABLED=true и фиксированным токеном."""
    configure_auth(auth_enabled=True, mas_bearer_token="test-token-123")
    monkeypatch.setenv("A2A_AUTH_ENABLED", "true")
    monkeypatch.setenv("A2A_MAS_BEARER_TOKEN", "test-token-123")
    return build_app()


@pytest.fixture
def app_no_auth() -> None:
    """A2A-приложение с AUTH_ENABLED=false (default)."""
    configure_auth(auth_enabled=False, mas_bearer_token=None)
    return build_app()


def test_auth_disabled_allows_anonymous_access() -> None:
    """``AUTH_ENABLED=false`` — все эндпойнты доступны без токена."""
    configure_auth(auth_enabled=False, mas_bearer_token=None)
    app = build_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200


def test_auth_enabled_requires_token_for_protected_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AUTH_ENABLED=true`` + нет токена на защищённом пути → 401."""
    monkeypatch.setenv("A2A_AUTH_ENABLED", "true")
    monkeypatch.setenv("A2A_MAS_BEARER_TOKEN", "test-token-123")
    app = build_app()
    client = TestClient(app)
    # /health и agent-card — публичные, доступны.
    assert client.get("/health").status_code == 200
    assert client.get("/.well-known/agent-card.json").status_code == 200
    # /openapi.json тоже публичный (для discovery).
    assert client.get("/openapi.json").status_code == 200
    # Защищённый путь (/) без токена → 401.
    r = client.post("/", json={"jsonrpc": "2.0", "id": "1", "method": "ping"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == ERROR_INVALID_TOKEN
    assert body["message"]  # непустое


def test_auth_enabled_accepts_correct_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AUTH_ENABLED=true`` + правильный токен → эндпойнт НЕ блокируется 401.

    Конкретный ответ может быть любым (200/400/Method not found), но не 401.
    """
    monkeypatch.setenv("A2A_AUTH_ENABLED", "true")
    monkeypatch.setenv("A2A_MAS_BEARER_TOKEN", "test-token-123")
    app = build_app()
    client = TestClient(app)
    r = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "1", "method": "ping"},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert r.status_code != 401, (
        f"правильный токен не должен давать 401, получили {r.status_code}: {r.text}"
    )


def test_auth_enabled_rejects_wrong_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AUTH_ENABLED=true`` + неверный токен → 401 с единым сообщением."""
    monkeypatch.setenv("A2A_AUTH_ENABLED", "true")
    monkeypatch.setenv("A2A_MAS_BEARER_TOKEN", "test-token-123")
    app = build_app()
    client = TestClient(app)
    r1 = client.post("/", json={}, headers={"Authorization": "Bearer wrong"})
    r2 = client.post("/", json={})  # нет токена
    assert r1.status_code == 401
    assert r2.status_code == 401
    # Одинаковое сообщение.
    assert r1.json()["message"] == r2.json()["message"]


def test_auth_enabled_fails_fast_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AUTH_ENABLED=true`` без ``MAS_BEARER_TOKEN`` → RuntimeError."""
    from blocksnet_agent.a2a import auth as auth_module

    auth_module._verifier = None
    auth_module._auth_enabled = False
    with pytest.raises(RuntimeError, match="MAS_BEARER_TOKEN"):
        configure_auth(auth_enabled=True, mas_bearer_token=None)


def test_is_auth_enabled_reflects_configuration() -> None:
    """``is_auth_enabled()`` — после ``configure_auth(auth_enabled=...)``."""
    configure_auth(auth_enabled=False, mas_bearer_token=None)
    assert is_auth_enabled() is False
    configure_auth(auth_enabled=True, mas_bearer_token="x")
    assert is_auth_enabled() is True
    # Возвращаем в default.
    configure_auth(auth_enabled=False, mas_bearer_token=None)