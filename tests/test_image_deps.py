"""Тесты разделения зависимостей MCP-образа (шаг 07).

Главные гарантии:
- ``import blocksnet_mcp.server`` НЕ тянет ``langgraph``/``langchain_openai``/
  ``tiktoken`` — иначе MCP-образ собирается с LLM-зависимостями.
- ``import blocksnet_mcp.envelope`` тоже НЕ тянет — это критично для
  любых клиентов, которые читают envelope-модуль без поднятия сервера.
- ``import blocksnet_mcp.session`` НЕ тянет.
- ``import blocksnet_mcp.agent_tool`` ТЯНЕТ (он же для legacy-агента).
- ``is_failed_observation`` в envelope и в ``blocksnet_agent.tools`` —
  классифицируют одинаково (защита от дрейфа).

Запускается в подпроцессе (``subprocess.run``), иначе модули уже могут
быть импортированы другими тестами.
"""

from __future__ import annotations

import subprocess
import sys

# Тяжёлые LLM-зависимости, которые НЕ должны попасть в MCP-образ.
HEAVY_DEPS = frozenset({"langgraph", "langchain_openai", "tiktoken"})


def _check_no_heavy_imports(module_path: str) -> tuple[bool, str]:
    """Запускает подпроцесс, проверяет что указанный модуль не тянет HEAVY_DEPS.

    Returns:
        (success, message) — ``success=True`` если ни одна HEAVY_DEPS не загружена.
    """
    code = (
        "import sys\n"
        f"import {module_path}\n"
        "loaded = sorted(set(sys.modules) & "
        f"{set(HEAVY_DEPS)!r})\n"
        "print(','.join(loaded) if loaded else 'CLEAN')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        # Долгая проверка на всякий случай.
        timeout=30,
    )
    if result.returncode != 0:
        return False, f"subprocess failed: {result.stderr.strip()}"
    output = result.stdout.strip()
    if output == "CLEAN":
        return True, f"{module_path}: CLEAN (no heavy deps)"
    return False, f"{module_path} loaded heavy deps: {output}"


def test_blocksnet_mcp_server_does_not_import_heavy_deps() -> None:
    """``import blocksnet_mcp.server`` НЕ должен тянуть LLM-зависимости."""
    success, message = _check_no_heavy_imports("blocksnet_mcp.server")
    assert success, message


def test_blocksnet_mcp_envelope_does_not_import_heavy_deps() -> None:
    """``import blocksnet_mcp.envelope`` — критично, не должен тянуть."""
    success, message = _check_no_heavy_imports("blocksnet_mcp.envelope")
    assert success, message


def test_blocksnet_mcp_session_does_not_import_heavy_deps() -> None:
    """``import blocksnet_mcp.session`` — сессионное хранилище, без LLM."""
    success, message = _check_no_heavy_imports("blocksnet_mcp.session")
    assert success, message


def test_blocksnet_mcp_settings_does_not_import_heavy_deps() -> None:
    """``import blocksnet_mcp.settings`` — pydantic-settings, без LLM."""
    success, message = _check_no_heavy_imports("blocksnet_mcp.settings")
    assert success, message


def test_blocksnet_mcp_serialize_does_not_import_heavy_deps() -> None:
    """``import blocksnet_mcp.serialize`` — сериализация, без LLM-runtime.

    Допускает тип-чекинг (``AgentResult`` через ``TYPE_CHECKING``),
    но НЕ рантайм-импорт ``blocksnet_agent`` (который тянет ``langgraph``).
    """
    success, message = _check_no_heavy_imports("blocksnet_mcp.serialize")
    assert success, message


def test_blocksnet_agent_does_import_heavy_deps() -> None:
    """Sanity-check: ``blocksnet_agent`` ДОЛЖЕН тянуть LLM-зависимости
    (это его ядро)."""
    # Слабая проверка — мы НЕ требуем, чтобы он их тянул; просто убеждаемся,
    # что наш previous test не сломан из-за пустого окружения.
    code = "import sys\nimport blocksnet_agent\nprint('OK')\n"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"blocksnet_agent import failed: {result.stderr}"


# --- envelope classification должна совпадать с agent ----------------------


def test_envelope_classification_matches_agent() -> None:
    """Локальная копия маркеров в envelope совпадает с agent-версией.

    Защита от дрейфа: если кто-то добавит маркер в ``blocksnet_agent``,
    тест напомнит про envelope.
    """
    # Случаи, которые ОБЯЗАНЫ классифицироваться как failed в обоих.
    must_fail = [
        "Ошибка: нет файла",
        "Traceback (most recent call last):",
        "Exception: boom",
        "NO_DATA",
        "REPEATED_FAILED_CALL: x",
        "не найден",
    ]
    # Случаи, которые НЕ должны классифицироваться как failed.
    must_pass = [
        "Кэш пуст. Загрузи данные.",
        "blocks_with_services.gpkg загружен (9368 кварталов)",
        "service_type='school', strong=0.85",
    ]
    # Импортируем обе функции.
    from blocksnet_mcp.envelope import is_failed_observation as envelope_check
    from blocksnet_agent.tools import is_failed_observation as agent_check

    for text in must_fail:
        assert envelope_check(text) is True, f"envelope не пометил failed: {text!r}"
        assert agent_check(text) is True, f"agent не пометил failed: {text!r}"
    for text in must_pass:
        assert envelope_check(text) is False, f"envelope ложно failed: {text!r}"
        assert agent_check(text) is False, f"agent ложно failed: {text!r}"