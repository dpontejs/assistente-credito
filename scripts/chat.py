"""Conversa com o assistente pelo terminal.

    uv run python scripts/chat.py --user ana --thread t1 "Meu cartão cobra 14% ao mês. É normal?"

Imprime a resposta e as ferramentas e skills chamadas no turno.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from langchain_core.messages import HumanMessage

from credito.assistant import open_assistant
from credito.ui import turns


async def main(user: str, thread: str, question: str) -> None:
    async with open_assistant() as assistant:
        config = {"configurable": {"thread_id": thread}}
        state = await assistant.graph.ainvoke({"messages": [HumanMessage(question)], "user_id": user}, config)
    turn = turns(state["messages"])[-1]
    print(turn.answer)
    print(f"\n[thread {thread}] ferramentas: {turn.tools or '-'} | skills: {turn.skills or '-'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--user", default="ana")
    parser.add_argument("--thread", default=str(uuid.uuid4())[:8])
    args = parser.parse_args()
    asyncio.run(main(args.user, args.thread, args.question))
