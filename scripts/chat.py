"""Conversa com o assistente pelo terminal.

    uv run python scripts/chat.py --user ana --thread t1 "Meu cartão cobra 14% ao mês. É normal?"

Imprime a resposta e as ferramentas e skills chamadas no turno.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from langchain_core.messages import AIMessage, HumanMessage

from credito.assistant import open_assistant
from credito.graph import as_text


def turn_summary(messages: list) -> tuple[str, list[str], list[str]]:
    """Resposta final, ferramentas e skills usadas desde a última mensagem do usuário."""
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    calls = [c for m in messages[start:] if isinstance(m, AIMessage) for c in m.tool_calls]
    tools = [c["name"] for c in calls if c["name"] != "load_skill"]
    skills = [c["args"].get("name", "") for c in calls if c["name"] == "load_skill"]
    return as_text(messages[-1].content), tools, skills


async def main(user: str, thread: str, question: str) -> None:
    async with open_assistant() as assistant:
        config = {"configurable": {"thread_id": thread}}
        state = await assistant.graph.ainvoke({"messages": [HumanMessage(question)], "user_id": user}, config)
    answer, tools, skills = turn_summary(state["messages"])
    print(answer)
    print(f"\n[thread {thread}] ferramentas: {tools or '-'} | skills: {skills or '-'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--user", default="ana")
    parser.add_argument("--thread", default=str(uuid.uuid4())[:8])
    args = parser.parse_args()
    asyncio.run(main(args.user, args.thread, args.question))
