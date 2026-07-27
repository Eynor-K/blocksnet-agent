"""Настройки A2A-сервиса: наследует ``Settings`` (LLM/MAX_ITERATIONS) и
добавляет только транспортное — host/port, max_concurrent_tasks, TTL/deadline.

a2a/05: идея — один источник правды для LLM-конфига (``Settings``), A2A-сервис
просто добавляет своё. Это исключает «три копии одного и того же дефолта»
и устраняет ручную синхронизацию.
"""

from __future__ import annotations

from pydantic import Field

from blocksnet_agent.config import Settings


class A2ASettings(Settings):
    """Транспортные настройки A2A-сервиса.

    Наследует:
    - ``chat_url``/``api_key``/``model``/``max_iterations`` из ``Settings``.
    - ``data_dir``/``output_dir`` — общие с агентом.
    - ``model_config`` (extra: "ignore", populate_by_name, env_file) — корректно.

    Добавляет:
    - ``host``/``port``/``public_url`` — FastAPI uvicorn-конфиг.
    - ``max_concurrent_tasks`` — лимит параллельных A2A-задач.
      ``max_concurrent_tasks=2`` осознанно: каждый ран держит GeoDataFrame
      кварталов и матрицу доступности в памяти.
    - ``task_ttl_sec`` — время жизни завершённой задачи в TaskManager.
    - ``deadline_sec`` — общий с MCP (через ``DEADLINE_SEC`` env).
    """

    # Транспорт.
    host: str = Field(default="0.0.0.0", validation_alias="A2A_HOST")
    port: int = Field(default=8080, validation_alias="A2A_PORT")
    public_url: str | None = Field(default=None, validation_alias="A2A_PUBLIC_URL")

    # Auth (a2a/06). ``AUTH_ENABLED=false`` — local dev (default).
    auth_enabled: bool = Field(default=False, validation_alias="A2A_AUTH_ENABLED")
    mas_bearer_token: str | None = Field(default=None, validation_alias="A2A_MAS_BEARER_TOKEN")

    # Конкурентность.
    max_concurrent_tasks: int = Field(
        default=2, validation_alias="A2A_MAX_CONCURRENT_TASKS"
    )

    # TTL/deadline.
    task_ttl_sec: float = Field(default=3600.0, validation_alias="A2A_TASK_TTL_SEC")
    # ``DEADLINE_SEC`` уже используется в MCP; здесь переоткрываем как alias.
    deadline_sec: int = Field(default=480, validation_alias="DEADLINE_SEC")

    # Прогресс.
    progress_interval_sec: float = Field(
        default=10.0, validation_alias="A2A_PROGRESS_INTERVAL_SEC"
    )

    def model_post_init(self, _) -> None:
        # Не вызываем родительский ``model_post_init``: он создаёт ``output_dir``,
        # что уже сделано в ``Settings.__init__``-цепочке. Дублирующее создание
        # безвредно (с ``exist_ok=True``), но избегаем его для чистоты.
        return


__all__ = ["A2ASettings"]