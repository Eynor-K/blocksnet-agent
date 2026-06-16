from typing import TypedDict

from langchain_core.messages import BaseMessage

from blocksnet_agent.agent import BlocksNetAgent


class AgentResult(TypedDict, total=False):
    input: str
    output: str
    log: list[BaseMessage]
    # Метакогнитивные поля структурированного вывода:
    confidence: float
    limitations: list[str]
    sections: dict[str, str]
    run_dir: str


__all__ = ["AgentResult", "BlocksNetAgent"]
