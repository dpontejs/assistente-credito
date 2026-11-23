"""Gera docs/grafo.md com o diagrama Mermaid do grafo, a partir do próprio código.

    uv run python scripts/draw_graph.py
"""

from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda

from credito.graph import Deps, build_graph


class _Stub(FakeListChatModel):
    """Modelo vazio: só a estrutura do grafo importa para o desenho."""

    def bind_tools(self, tools, **kwargs):
        return self


def main() -> None:
    stub = _Stub(responses=[""])
    noop = RunnableLambda(lambda _: None)
    graph = build_graph(Deps(model=stub, input_guard=noop, output_guard=noop, grader=noop,
                             rewriter=stub, tools=[], catalog=""))
    mermaid = graph.get_graph().draw_mermaid()
    out = Path(__file__).resolve().parent.parent / "docs" / "grafo.md"
    out.write_text(f"# Grafo do assistente\n\nGerado por `scripts/draw_graph.py`.\n\n```mermaid\n{mermaid}```\n")
    print(mermaid)


if __name__ == "__main__":
    main()
