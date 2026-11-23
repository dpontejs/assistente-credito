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


def test_mcp_servers_passa_o_banco_para_o_servidor(tmp_path):
    from credito.assistant import mcp_servers

    config = mcp_servers(tmp_path / "p.db")
    assert config["credito"]["env"]["CREDITO_DB"] == str(tmp_path / "p.db")
    assert "PATH" in config["credito"]["env"]


def test_servidor_le_o_banco_de_credito_db(tmp_path, monkeypatch):
    from servers.credit_server import db_path

    monkeypatch.setenv("CREDITO_DB", str(tmp_path / "x.db"))
    assert db_path() == tmp_path / "x.db"
    monkeypatch.delenv("CREDITO_DB")
    assert db_path().name == "profiles.db"
