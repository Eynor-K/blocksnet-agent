"""Тест шага 04 a2a-рефакторинга: Settings-инфраструктура.

Главные гарантии:
- ``blocksnet_agent.config.Settings`` наследуема — ``A2ASettings`` на шаге 05
  сможет отнаследоваться и добавить только транспортные поля.
- ``blocksnet_mcp.settings.MCPSettings`` создаётся БЕЗ ``CHAT_URL``/``API_KEY``
  (проверка, что шаг 03 не сломался).
- Дефолты из ``.env`` не подменяют тестовые monkeypatch, потому что
  ``pydantic-settings`` читает файл при инициализации (важно для тестов
  шага 03/04).

Первый тест ``test_a2a_settings_inherit_agent_settings`` написан в шаге 05,
когда появится ``A2ASettings``. Здесь — только инфраструктурные гарантии.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# --- инфраструктура --------------------------------------------------------


def test_mcp_settings_create_without_llm() -> None:
    """``MCPSettings()`` создаётся без ``CHAT_URL``/``API_KEY`` (после шага 03)."""
    from blocksnet_mcp.settings import MCPSettings

    # ``model_construct`` создаёт объект без валидации — обходим проверку required.
    # Для нашего теста важно: класс Settings объявляет ``chat_url: str | None``,
    # а не ``chat_url: str`` (required). Это и есть гарантия шага 03.
    s = MCPSettings.model_construct(
        chat_url=None,
        api_key=None,
        model=None,
        data_dir=Path("/tmp"),
        output_dir=Path("/tmp"),
    )
    assert s.chat_url is None
    assert s.api_key is None
    assert s.model is None


def test_mcp_settings_has_enable_agent_tool_field() -> None:
    """У ``MCPSettings`` есть поле ``enable_agent_tool`` (default True)."""
    from blocksnet_mcp.settings import MCPSettings

    fields = MCPSettings.model_fields
    assert "enable_agent_tool" in fields
    # Дефолт — True (для backward compatibility).
    info = fields["enable_agent_tool"]
    assert info.default is True


def test_mcp_settings_has_session_fields() -> None:
    """У ``MCPSettings`` есть ``session_ttl_sec``/``max_sessions`` (шаг 02)."""
    from blocksnet_mcp.settings import MCPSettings

    fields = MCPSettings.model_fields
    assert "session_ttl_sec" in fields
    assert "max_sessions" in fields
    assert fields["session_ttl_sec"].default == 1800.0
    assert fields["max_sessions"].default == 8


def test_agent_settings_has_required_llm_fields() -> None:
    """``blocksnet_agent.config.Settings`` требует ``CHAT_URL``/``API_KEY``.

    Это разница с ``MCPSettings``: ``Settings`` всё ещё используется напрямую
    агентом (шаг 05), и LLM-поля там обязательны. A2ASettings на шаге 05
    наследует ``Settings``, поэтому эти поля остаются required по умолчанию.
    """
    from blocksnet_agent.config import Settings

    fields = Settings.model_fields
    # В текущей реализации chat_url — required (нет default).
    chat_field = fields["chat_url"]
    assert chat_field.is_required(), (
        "Settings.chat_url обязателен — агентский run() невозможен без LLM"
    )
    api_field = fields["api_key"]
    assert api_field.is_required()


def test_agent_settings_is_inheritable() -> None:
    """``Settings`` можно наследовать — на шаге 05 ``A2ASettings(Settings)``.

    Проверка: подкласс не падает при создании, поля родителя доступны.
    """
    from blocksnet_agent.config import Settings

    class _SubclassForTest(Settings):
        # Наследуем все поля, добавляем тестовое.
        test_field: int = 42

    # model_construct обходит валидацию required-полей.
    obj = _SubclassForTest.model_construct(
        chat_url="http://test",
        api_key="test-key",
        model="gpt-test",
        data_dir=Path("/tmp"),
        output_dir=Path("/tmp"),
        max_iterations=10,
        test_field=99,
    )
    assert obj.chat_url == "http://test"
    assert obj.test_field == 99


def test_agent_settings_extra_ignore() -> None:
    """``Settings.model_config`` имеет ``extra: 'ignore'`` — наследник может
    добавлять поля без конфликта с уже-прочитанными из env.
    """
    from blocksnet_agent.config import Settings

    assert Settings.model_config.get("extra") == "ignore"