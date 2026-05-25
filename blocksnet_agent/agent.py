from __future__ import annotations

from typing import TYPE_CHECKING, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from blocksnet_agent.config import Settings
from blocksnet_agent.prompts import SYSTEM_PROMPT
from blocksnet_agent.tools import make_tools

if TYPE_CHECKING:
    from blocksnet_agent import AgentResult


class BlocksNetAgent:
    def __init__(self, settings: Settings | None = None, model: str | None = None):
        self._settings = settings or Settings()
        if model is not None:
            self._settings.model = model
        self._state: dict = {}
        self._llm = ChatOpenAI(
            base_url=self._settings.chat_url,
            api_key=self._settings.api_key,
            model=self._settings.model,
            temperature=0,
            max_tokens=4096,
        )
        tools = make_tools(self._state, self._settings.data_dir, self._settings.output_dir)
        self._graph = create_react_agent(model=self._llm, tools=tools, prompt=SYSTEM_PROMPT)

    def run(self, task: str) -> AgentResult:
        try:
            result = self._graph.invoke({"messages": [HumanMessage(content=task)]})
        except Exception as exc:
            output = f"Ошибка при запуске агента: {exc}"
            return cast(
                "AgentResult",
                {"input": task, "output": output, "log": [HumanMessage(content=task), _ai_message_with_usage(output)]},
            )
        messages: list[BaseMessage] = result["messages"]
        log = [
            _ensure_ai_usage(message) if isinstance(message, AIMessage) else message
            for message in messages
            if isinstance(message, (HumanMessage, AIMessage))
        ]
        output = next(
            (message.content for message in reversed(messages) if isinstance(message, AIMessage) and message.content),
            "Ответ не получен.",
        )
        return cast("AgentResult", {"input": task, "output": str(output), "log": log})

    def reset(self) -> None:
        """Очищает кэш загруженных данных."""
        self._state.clear()


def _estimate_tokens(content) -> int:
    text = content if isinstance(content, str) else str(content)
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text.split())) if text else 0


def _ai_message_with_usage(content: str) -> AIMessage:
    tokens = _estimate_tokens(content)
    return AIMessage(content=content, usage_metadata={"input_tokens": 0, "output_tokens": tokens, "total_tokens": tokens})


def _ensure_ai_usage(message: AIMessage) -> AIMessage:
    usage = getattr(message, "usage_metadata", None)
    if usage and usage.get("output_tokens") is not None:
        return message
    tokens = _estimate_tokens(message.content)
    try:
        message.usage_metadata = {"input_tokens": 0, "output_tokens": tokens, "total_tokens": tokens}
    except Exception:
        return _ai_message_with_usage(str(message.content))
    return message
