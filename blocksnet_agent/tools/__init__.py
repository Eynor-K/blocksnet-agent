from pathlib import Path

from langchain_core.tools import BaseTool

from blocksnet_agent.tools.data import make_data_tools
from blocksnet_agent.tools.indicators import make_indicators_tools
from blocksnet_agent.tools.network import make_network_tools
from blocksnet_agent.tools.provision import make_provision_tools
from blocksnet_agent.tools.services import make_services_tools


def make_tools(state: dict, data_dir: Path, output_dir: Path) -> list[BaseTool]:
    ctx = {"state": state, "data_dir": data_dir, "output_dir": output_dir}
    return (
        make_data_tools(ctx)
        + make_network_tools(ctx)
        + make_provision_tools(ctx)
        + make_services_tools(ctx)
        + make_indicators_tools(ctx)
    )


__all__ = ["make_tools"]
