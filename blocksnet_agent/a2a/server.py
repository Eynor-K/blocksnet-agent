"""A2A-сервис для BlocksNetAgent.

Шаг 05 a2a-рефакторинга. ``python -m blocksnet_agent.a2a`` (или
``python -m blocksnet_agent``) поднимает FastAPI-приложение с A2A-роутами.

Главные компоненты:
- ``/health`` — liveness для compose (шаг 07).
- ``/{...}`` — A2A JSON-RPC: SendMessage, GetTask, ListTasks, CancelTask.
- ``/.well-known/agent-card.json`` — карточка агента.

Стек:
- ``a2a-sdk==1.1.1`` (из шага 00.6 спайка).
- uvicorn — ASGI-сервер.
- FastAPI — обёртка.
- TaskManager — лимит конкурентности, TTL, per-run отмена (шаг 04).
"""

from __future__ import annotations

import logging
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from fastapi import FastAPI

from blocksnet_agent.a2a.agent_card import build_agent_card
from blocksnet_agent.a2a.auth import auth_middleware, configure_auth
from blocksnet_agent.a2a.executor import execute_run_pipeline
from blocksnet_agent.a2a.settings import A2ASettings
from blocksnet_agent.a2a.skills import SKILLS, get_skill
from blocksnet_agent.a2a.task_manager import TaskManager, TaskState as A2ATaskState

log = logging.getLogger("blocksnet_agent.a2a")


# --- мост между A2A SDK и TaskManager ---------------------------------------


class _A2ATaskBridge(AgentExecutor):
    """Реализация ``AgentExecutor`` для a2a-sdk 1.1.1.

    Принимает ``message/send`` с текстом вопроса, диспатчит в нужный skill,
    стримит ``TaskStatusUpdateEvent`` через ``EventQueue``.
    """

    def __init__(
        self,
        *,
        task_manager: TaskManager,
        settings: A2ASettings,
    ) -> None:
        self._task_manager = task_manager
        self._settings = settings

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Обрабатывает SendMessage."""
        user_text = ""
        for part in context.message.parts:
            # protobuf Part — oneof с прямыми полями.
            user_text += part.text or ""

        # a2a/06: scenario_id/project_id приходят в ``message.metadata``
        # (стандартное поле a2a-sdk 1.1.1, protobuf-``map<string,string>``).
        meta = dict(context.message.metadata or {})
        scenario_id = meta.get("scenario_id") or None
        project_id = meta.get("project_id") or None

        # Определяем skill — пока по skill_id из контекста или дефолт run_pipeline.
        skill_id = "run_pipeline"
        ctx_id = getattr(context, "context_id", None) or ""
        spec = get_skill(skill_id) or SKILLS[0]

        # Прогресс колбэк → TaskStatusUpdateEvent.
        def _on_progress(state: str, message: str) -> None:
            try:
                a2a_state = {
                    "submitted": TaskState.submitted,
                    "working": TaskState.working,
                    "completed": TaskState.completed,
                    "failed": TaskState.failed,
                    "canceled": TaskState.canceled,
                }[state]
            except KeyError:
                a2a_state = TaskState.working
            try:
                event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        task_id=context.task_id or "",
                        context_id=ctx_id,
                        status=TaskStatus(state=a2a_state, message=Message(
                            role=Role.ROLE_AGENT,
                            parts=[Part(text=message or "")],
                        )),
                        final=(a2a_state != TaskState.working),
                    )
                )
            except Exception:
                log.warning("failed to enqueue progress event", exc_info=True)

        # Запускаем через TaskManager (он сам стартует в пуле).
        input_payload = {
            "question": user_text,
            "max_iterations": None,
            "scenario_id": scenario_id,
            "project_id": project_id,
        }
        record = self._task_manager.submit(
            input_payload,
            runner=lambda rec, cb: spec.runner(
                input_payload=input_payload,
                task_manager=self._task_manager,
                output_dir=self._settings.output_dir,
                data_dir=self._settings.data_dir,
                deadline_sec=self._settings.deadline_sec,
                progress_cb=cb,
            ),
        )

        # Блокирующее ожидание — наш пул. Не asyncio.wait_for (см. шаг 04).
        if record.future is not None:
            try:
                record.future.result()
            except Exception:
                log.exception("task failed during execute()")

        # Эмитим финальное сообщение — текст + status.
        record = self._task_manager.get(record.task_id) or record
        output = record.output or {"status": "failed", "error_code": "NO_OUTPUT"}
        status_text = (
            f"{output.get('status', 'ok')}: {output.get('error', output.get('output', ''))[:200]}"
        )
        await event_queue.enqueue_event(
            Message(
                role=Role.ROLE_AGENT,
                parts=[Part(text=status_text)],
            )
        )
        # Если есть артефакты — эмитим как TaskArtifactUpdateEvent.
        for artifact_path in (output.get("artifacts") or []):
            try:
                await event_queue.enqueue_event(
                    TaskArtifactUpdateEvent(
                        task_id=record.task_id,
                        context_id=ctx_id,
                        artifact={
                            "parts": [{"text": str(artifact_path)}],
                        },
                    )
                )
            except Exception:
                log.warning("failed to enqueue artifact event", exc_info=True)

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Обрабатывает CancelTask."""
        task_id = context.task_id or ""
        cancelled = self._task_manager.cancel(task_id)
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=getattr(context, "context_id", None) or "",
                status=TaskStatus(
                    state=TaskState.canceled if cancelled else TaskState.failed,
                    message=Message(
                        role=Role.ROLE_AGENT,
                        parts=[Part(text="canceled" if cancelled else "no such task")],
                    ),
                ),
                final=True,
            )
        )


# --- сборка приложения -----------------------------------------------------


def _build_task_manager(settings: A2ASettings) -> TaskManager:
    return TaskManager(
        max_concurrent=settings.max_concurrent_tasks,
        task_ttl_sec=settings.task_ttl_sec,
        progress_interval_sec=settings.progress_interval_sec,
    )


def build_app(settings: A2ASettings | None = None) -> FastAPI:
    """Собирает FastAPI с A2A-роутами и /health.

    Args:
        settings: если None — создаётся ``A2ASettings()`` (читает env/.env).
    """
    if settings is None:
        settings = A2ASettings()  # type: ignore[call-arg]

    # a2a/06: инициализация auth перед регистрацией роутов (fail-fast если
    # ``AUTH_ENABLED=true`` без ``MAS_BEARER_TOKEN``).
    configure_auth(
        auth_enabled=settings.auth_enabled,
        mas_bearer_token=settings.mas_bearer_token,
    )

    task_manager = _build_task_manager(settings)
    card = build_agent_card(
        host=settings.host,
        port=settings.port,
        public_url=settings.public_url,
    )

    handler = DefaultRequestHandler(
        agent_executor=_A2ATaskBridge(task_manager=task_manager, settings=settings),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    app = FastAPI(title="blocksnet-mcp-a2a", version=card.version)
    # a2a/06: middleware auth (если ``AUTH_ENABLED=true`` — пропускает запрос
    # без валидного токена).
    app.middleware("http")(auth_middleware)

    # /health для compose/Docker (шаг 07).
    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "name": card.name,
            "version": card.version,
            "skills": [s.id for s in card.skills],
        }

    # A2A-роуты.
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    )
    return app


# Синглтон-приложение для удобства тестов и dev-сервера.
app: FastAPI | None = None


def get_app() -> FastAPI:
    """Ленивая инициализация — для тестов и ``uvicorn blocksnet_agent.a2a.server:app``."""
    global app
    if app is None:
        app = build_app()
    return app


def main() -> None:
    """``python -m blocksnet_agent.a2a`` — uvicorn ASGI-сервер."""
    import uvicorn

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    settings = A2ASettings()  # type: ignore[call-arg]
    application = build_app(settings)
    log.info(
        "starting A2A service on %s:%s (public=%s)",
        settings.host,
        settings.port,
        settings.public_url,
    )
    uvicorn.run(application, host=settings.host, port=settings.port, log_level="warning")


__all__ = ["build_app", "get_app", "main", "A2ATaskState"]