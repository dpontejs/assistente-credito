"""Montagem do assistente real: Gemini, servidores MCP, índice das normas, skills e checkpointer."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import BaseTool

from credito.graph import Deps, build_graph
from credito.guards import InputVerdict, OutputVerdict
from credito.rag import GradeDocuments, build_vector_store, default_embeddings, make_search_tool
from credito.skills import load_catalog, make_load_skill_tool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "google_genai:gemini-3.6-flash"  # escolhido na avaliação (evals/RESULTADOS.md)

def mcp_servers(profiles_db: Path | None = None) -> dict:
    """Config dos servidores MCP; o banco de perfis vai por variável de ambiente para o servidor próprio."""
    own = {"command": sys.executable, "args": [str(ROOT / "servers" / "credit_server.py")]}
    if profiles_db is not None:
        own["env"] = {"CREDITO_DB": str(profiles_db), "PATH": os.environ.get("PATH", "")}
    return {
        # servidor próprio: calculadoras, taxas do BCB e perfil
        "credito": own,
        # servidor da comunidade: data de hoje para cronogramas e prazos
        "time": {"command": "uvx", "args": ["mcp-server-time", "--local-timezone=America/Fortaleza"]},
    }


MCP_SERVERS = mcp_servers()


@dataclass
class Assistant:
    graph: object
    tools: list[BaseTool]


@asynccontextmanager
async def open_assistant(
    db_path: Path = ROOT / "data" / "checkpoints.db",
    model_name: str | None = None,
    profiles_db: Path | None = None,
):
    """Abre os servidores MCP e o checkpointer e devolve o grafo pronto; tudo fecha ao sair do bloco."""
    import warnings

    from langchain.chat_models import init_chat_model
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")  # antes do import: o fastmcp lê na importação
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # langchain.mcp é beta e avisa a cada import
        from langchain.mcp import MCPAdapter

    # o adaptador do Gemini avisa a cada ferramenta que ignora 'additionalProperties' do schema
    logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)
    load_dotenv(ROOT / ".env")
    model = init_chat_model(model_name or os.environ.get("CREDITO_MODEL", DEFAULT_MODEL), temperature=0)
    store = await asyncio.to_thread(build_vector_store, ROOT / "data" / "docs", ROOT / "data" / "chroma",
                                    default_embeddings())
    local_tools = [make_search_tool(store), make_load_skill_tool(ROOT / "skills")]

    adapter = MCPAdapter({"mcpServers": mcp_servers(profiles_db)})
    async with adapter, AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        tools = [*await adapter.list_tools(), *local_tools]
        deps = Deps(
            model=model,
            input_guard=model.with_structured_output(InputVerdict),
            output_guard=model.with_structured_output(OutputVerdict),
            grader=model.with_structured_output(GradeDocuments),
            rewriter=model,
            tools=tools,
            catalog=load_catalog(ROOT / "skills"),
        )
        yield Assistant(graph=build_graph(deps, checkpointer=checkpointer), tools=tools)
