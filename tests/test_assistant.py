import asyncio
from pathlib import Path

import pytest

from credito.assistant import MCP_SERVERS, open_assistant


def test_mcp_servers_aponta_para_os_dois_servidores():
    assert set(MCP_SERVERS) == {"credito", "time"}
    assert Path(MCP_SERVERS["credito"]["args"][0]).exists()
    assert MCP_SERVERS["time"]["command"] == "uvx"


@pytest.mark.network
def test_open_assistant_real(tmp_path):
    async def run():
        async with open_assistant(db_path=tmp_path / "checkpoints.db") as assistant:
            return {tool.name for tool in assistant.tools}

    names = asyncio.run(run())
    assert {"credito_get_profile", "time_get_current_time", "search_norms", "load_skill"} <= names
    assert len(names) >= 14
