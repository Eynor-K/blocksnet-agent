from typing import TypedDict

from langchain_core.messages import BaseMessage

from blocksnet_agent.agent import BlocksNetAgent


class AgentResult(TypedDict):
    input: str
    output: str
    log: list[BaseMessage]


__all__ = ["AgentResult", "BlocksNetAgent"]
